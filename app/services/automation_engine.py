"""Core automation matching and execution engine."""
import logging
import json
import re
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.core.config import dm_settings
from app.services.instagram_api import InstagramAPI
from app.services.message_builder import MessageBuilder
from app.services.rate_limiter import RateLimiter
from app.services.dedup import DeduplicationService
from app.services.contact_service import ContactService
from app.db.cosmos_db import CosmosDBClient
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class AutomationEngine:
    """
    Core automation matching and execution engine.

    Responsibilities:
    - Load and cache automations from Cosmos DB
    - Match incoming triggers (messages, keywords) to automations
    - Execute automations (send DMs, branch logic, schedule follow-ups)
    - Handle rate limiting, deduplication, and logging
    """

    def __init__(
        self,
        cosmos_client: Optional[CosmosDBClient] = None,
        instagram_api: Optional[InstagramAPI] = None,
        rate_limiter: Optional[RateLimiter] = None,
        dedup_service: Optional[DeduplicationService] = None,
        contact_service: Optional[ContactService] = None,
        redis_conn=None
    ):
        """Initialize automation engine."""
        self.cosmos_client = cosmos_client or CosmosDBClient()
        self.instagram_api = instagram_api or InstagramAPI()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.dedup_service = dedup_service or DeduplicationService()
        self.contact_service = contact_service or ContactService()
        self.redis = redis_conn or redis_client

    def _get_automations_cache_key(self, account_id: str) -> str:
        """Build Redis key for cached automations."""
        return f"dm:automations:{account_id}"

    async def get_cached_automations(self, account_id: str) -> List[Dict[str, Any]]:
        """
        Load automations for account, with Redis caching.

        Cache TTL: AUTOMATION_CACHE_TTL_HOURS

        Args:
            account_id: Instagram account ID

        Returns:
            List of automation documents
        """
        try:
            cache_key = self._get_automations_cache_key(account_id)

            # Try to get from Redis
            cached = self.redis.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for automations of account {account_id}")
                return json.loads(cached)

            logger.debug(f"Cache miss for automations of account {account_id}, loading from Cosmos")

            # Load from Cosmos DB
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_AUTOMATIONS_CONTAINER
            )

            query = """
                SELECT * FROM c
                WHERE c.account_id = @account_id
                AND c.enabled = true
                AND c.deleted_at = null
            """
            automations = list(container.query_items(
                query=query,
                parameters=[{"name": "@account_id", "value": account_id}]
            ))

            # Cache for specified TTL
            ttl_seconds = dm_settings.AUTOMATION_CACHE_TTL_HOURS * 3600
            self.redis.setex(
                cache_key,
                ttl_seconds,
                json.dumps(automations)
            )

            logger.debug(f"Loaded {len(automations)} automations for account {account_id}")
            return automations

        except Exception as e:
            logger.error(f"Error getting cached automations: {str(e)}")
            return []

    async def match_automations(
        self,
        account_id: str,
        trigger_type: str,
        text: str,
        post_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find automations matching the trigger.

        Supports:
        - trigger_type: 'message' (for DM content matching)
        - Keyword matching: exact, contains, regex
        - Optional post_id filtering for specific post interactions

        Args:
            account_id: Instagram account ID
            trigger_type: Type of trigger ('message', 'comment', 'follow')
            text: Text content to match against keywords
            post_id: Optional post ID to filter automations by specific post

        Returns:
            List of matching automation documents
        """
        try:
            logger.debug(f"Matching automations for {account_id}: trigger_type={trigger_type}")

            # Get all active automations for account
            automations = await self.get_cached_automations(account_id)

            matched = []

            for automation in automations:
                # Filter by trigger type
                if automation.get("trigger", {}).get("type") != trigger_type:
                    continue

                # Filter by post_id if specified
                if post_id and automation.get("trigger", {}).get("post_id"):
                    if automation["trigger"]["post_id"] != post_id:
                        continue

                # Match keywords
                keywords = automation.get("trigger", {}).get("keywords", [])
                if self._match_keywords(text, keywords):
                    matched.append(automation)
                    logger.debug(
                        f"Matched automation {automation.get('id')} for account {account_id}"
                    )

            logger.info(f"Found {len(matched)} matching automations for account {account_id}")
            return matched

        except Exception as e:
            logger.error(f"Error matching automations: {str(e)}")
            return []

    def _match_keywords(self, text: str, keywords: List[Dict[str, str]]) -> bool:
        """
        Check if text matches any of the keywords.

        Keyword formats:
        {
            "match_type": "exact|contains|regex",
            "value": "keyword or pattern",
            "case_sensitive": false
        }

        Args:
            text: Text to match against
            keywords: List of keyword definitions

        Returns:
            True if any keyword matches
        """
        if not keywords:
            return True  # No keywords = match all

        for keyword in keywords:
            match_type = keyword.get("match_type", "contains").lower()
            value = keyword.get("value", "")
            case_sensitive = keyword.get("case_sensitive", False)

            # Prepare text and value for comparison
            compare_text = text if case_sensitive else text.lower()
            compare_value = value if case_sensitive else value.lower()

            try:
                if match_type == "exact":
                    if compare_text == compare_value:
                        return True

                elif match_type == "contains":
                    if compare_value in compare_text:
                        return True

                elif match_type == "regex":
                    flags = 0 if case_sensitive else re.IGNORECASE
                    if re.search(compare_value, compare_text, flags):
                        return True

            except Exception as e:
                logger.error(f"Error matching keyword {value}: {str(e)}")
                continue

        return False

    async def execute_automation(
        self,
        automation: Dict[str, Any],
        sender: Dict[str, Any],
        account_id: str,
        webhook_event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute an automation workflow.

        Steps:
        1. Deduplication check
        2. Follow status check (if required)
        3. Rate limit check
        4. Resolve branch (follower/non-follower)
        5. Send DM from matched step
        6. Log result
        7. Schedule follow-ups

        Args:
            automation: Automation document
            sender: Sender dict with ig_user_id, ig_username, etc.
            account_id: Instagram account ID
            webhook_event: Original webhook event that triggered execution

        Returns:
            Execution result dict with status, message_id, etc.
        """
        try:
            automation_id = automation.get("id")
            sender_id = sender.get("ig_user_id")
            sender_username = sender.get("ig_username", "unknown")

            logger.info(f"Executing automation {automation_id} for user {sender_username}")

            result = {
                "automation_id": automation_id,
                "sender_id": sender_id,
                "sender_username": sender_username,
                "status": "failed",
                "message_id": None,
                "timestamp": datetime.utcnow().isoformat()
            }

            # Step 1: Deduplication check
            is_duplicate = self.dedup_service.check_and_set_dedup(
                account_id=account_id,
                automation_id=automation_id,
                ig_user_id=sender_id
            )

            if is_duplicate:
                logger.info(f"Duplicate send detected for {sender_id}, automation {automation_id}")
                result["status"] = "duplicate"
                return result

            # Step 2: Follow status check (if required)
            require_follower = automation.get("conditions", {}).get("require_follower", False)
            is_follower = False

            if require_follower:
                try:
                    is_follower = await self.instagram_api.check_follow_status(
                        account_id, sender_id
                    )
                    logger.debug(f"Follow status for {sender_username}: {is_follower}")
                except Exception as e:
                    logger.error(f"Error checking follow status: {str(e)}")
                    result["status"] = "follow_check_failed"
                    return result

            # Step 3: Rate limit check
            if not self.rate_limiter.check_rate_limit(account_id):
                logger.warning(f"Rate limit exceeded for account {account_id}")
                result["status"] = "rate_limited"
                return result

            # Step 4: Resolve branch (follower or non-follower)
            branch = "follower_branch" if is_follower else "non_follower_branch"
            steps = automation.get(branch, [])

            if not steps:
                logger.debug(f"No steps in {branch} for automation {automation_id}")
                result["status"] = "no_steps"
                return result

            # Step 5: Get first step and send DM
            first_step = steps[0]
            step_id = first_step.get("id")
            message_template = first_step.get("message")

            if not message_template:
                logger.error(f"No message template in step {step_id}")
                result["status"] = "no_message"
                return result

            # Build message payload with postback encoding
            payload = MessageBuilder.build_message_with_postback_payloads(
                message_template, automation_id
            )

            # Send via Instagram API
            try:
                api_result = await self.instagram_api.send_dm(
                    account_id=account_id,
                    recipient_id=sender_id,
                    message_payload=message_template
                )

                message_id = api_result.get("message_id")
                logger.info(f"DM sent successfully: {message_id}")

                result["status"] = "sent"
                result["message_id"] = message_id
                result["step_id"] = step_id

            except Exception as e:
                logger.error(f"Failed to send DM: {str(e)}")
                result["status"] = "send_failed"
                result["error"] = str(e)
                return result

            # Step 6: Log result to message_logs
            await self._log_execution(
                account_id=account_id,
                automation_id=automation_id,
                step_id=step_id,
                sender_id=sender_id,
                message_id=message_id,
                status="sent",
                webhook_event=webhook_event
            )

            # Step 7: Schedule follow-ups (if any)
            follow_up_step = None
            if len(steps) > 1:
                follow_up_step = steps[1]
                await self._schedule_follow_up(
                    account_id=account_id,
                    automation_id=automation_id,
                    sender_id=sender_id,
                    follow_up_step=follow_up_step,
                    branch=branch
                )

            return result

        except Exception as e:
            logger.error(f"Error executing automation: {str(e)}")
            return {
                "automation_id": automation.get("id"),
                "sender_id": sender.get("ig_user_id"),
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    async def resolve_branch(
        self,
        step: Dict[str, Any],
        account_id: str,
        sender_id: str,
        automation: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate branch conditions and return the matching branch.

        Conditions:
        - is_follower: bool
        - has_tag: list of tags (any match)
        - interaction_count: comparison (lt, lte, eq, gte, gt)

        Args:
            step: Step with conditional branches
            account_id: Instagram account ID
            sender_id: Sender IG user ID
            automation: Full automation for context

        Returns:
            Matching branch step or None
        """
        try:
            conditions = step.get("conditions", {})

            # Get contact info
            contact = await self.contact_service.get_or_create_contact(
                account_id=account_id,
                ig_user_id=sender_id,
                ig_username=str(sender_id)  # Fallback if username not available
            )

            # Check is_follower condition
            if "is_follower" in conditions:
                required_follower = conditions.get("is_follower")
                try:
                    is_follower = await self.instagram_api.check_follow_status(
                        account_id, sender_id
                    )
                    if is_follower != required_follower:
                        return None
                except Exception as e:
                    logger.error(f"Error checking follower status: {str(e)}")
                    return None

            # Check has_tag condition
            if "has_tag" in conditions:
                required_tags = conditions.get("has_tag", [])
                contact_tags = contact.get("tags", [])
                if not any(tag in contact_tags for tag in required_tags):
                    return None

            # Check interaction_count condition
            if "interaction_count" in conditions:
                count_condition = conditions["interaction_count"]
                operator = count_condition.get("operator", "gte")
                required_count = count_condition.get("value", 0)
                actual_count = contact.get("interaction_count", 0)

                if not self._compare_values(actual_count, operator, required_count):
                    return None

            # All conditions passed
            return step.get("action")

        except Exception as e:
            logger.error(f"Error resolving branch: {str(e)}")
            return None

    def _compare_values(self, actual: int, operator: str, expected: int) -> bool:
        """Compare two values using operator."""
        if operator == "lt":
            return actual < expected
        elif operator == "lte":
            return actual <= expected
        elif operator == "eq":
            return actual == expected
        elif operator == "gte":
            return actual >= expected
        elif operator == "gt":
            return actual > expected
        return False

    async def _log_execution(
        self,
        account_id: str,
        automation_id: str,
        step_id: str,
        sender_id: str,
        message_id: str,
        status: str,
        webhook_event: Dict[str, Any]
    ) -> None:
        """Log message send execution to Cosmos DB."""
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_MESSAGE_LOGS_CONTAINER
            )

            log_entry = {
                "id": f"{message_id}",
                "account_id": account_id,
                "automation_id": automation_id,
                "step_id": step_id,
                "sender_id": sender_id,
                "message_id": message_id,
                "status": status,
                "created_at": datetime.utcnow().isoformat(),
                "webhook_event": webhook_event
            }

            container.create_item(body=log_entry)
            logger.debug(f"Logged message execution: {message_id}")

        except Exception as e:
            logger.error(f"Error logging execution: {str(e)}")

    async def _schedule_follow_up(
        self,
        account_id: str,
        automation_id: str,
        sender_id: str,
        follow_up_step: Dict[str, Any],
        branch: str
    ) -> None:
        """Schedule a follow-up message delivery."""
        try:
            delay_seconds = follow_up_step.get("delay_seconds", 0)
            scheduled_at = datetime.utcnow().timestamp() + delay_seconds

            container = self.cosmos_client.get_container_client(
                dm_settings.DM_SCHEDULED_TASKS_CONTAINER
            )

            task = {
                "id": f"{automation_id}_{sender_id}_{int(time.time())}",
                "account_id": account_id,
                "automation_id": automation_id,
                "sender_id": sender_id,
                "step_id": follow_up_step.get("id"),
                "scheduled_at": datetime.utcfromtimestamp(scheduled_at).isoformat(),
                "branch": branch,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }

            container.create_item(body=task)
            logger.info(f"Scheduled follow-up for {sender_id} in {delay_seconds}s")

        except Exception as e:
            logger.error(f"Error scheduling follow-up: {str(e)}")


# Global singleton instance
automation_engine = AutomationEngine()
