"""Celery task for polling and executing scheduled DM messages."""
import logging
from datetime import datetime
from typing import List, Dict, Any
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db

logger = logging.getLogger(__name__)


class ScheduledTaskExecutor:
    """Handle polling and execution of scheduled DM tasks."""

    def __init__(self):
        """Initialize scheduled task executor."""
        self.scheduled_tasks_container = dm_settings.DM_SCHEDULED_TASKS_CONTAINER
        self.contacts_container = dm_settings.DM_CONTACTS_CONTAINER
        self.message_logs_container = dm_settings.DM_MESSAGE_LOGS_CONTAINER

    def poll_and_execute_scheduled_tasks(self) -> Dict[str, Any]:
        """
        Poll scheduled_tasks container for due tasks and execute them.

        Checks conditions: no_reply, messaging_window active.
        This task runs every 30 seconds.

        Returns:
            Execution result with counts
        """
        try:
            logger.debug("Starting scheduled task polling")

            # Find due tasks
            due_tasks = self._find_due_tasks()

            if not due_tasks:
                logger.debug("No due scheduled tasks found")
                return {"status": "success", "executed_count": 0, "failed_count": 0}

            logger.info(f"Found {len(due_tasks)} due scheduled tasks")

            executed_count = 0
            failed_count = 0

            # Execute each task
            for task in due_tasks:
                try:
                    success = self._execute_scheduled_task(task)
                    if success:
                        executed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error executing scheduled task {task.get('id')}: {str(e)}")
                    failed_count += 1

            logger.info(
                f"Scheduled task polling completed: "
                f"{executed_count} executed, {failed_count} failed"
            )

            return {
                "status": "success",
                "executed_count": executed_count,
                "failed_count": failed_count,
            }

        except Exception as e:
            logger.exception(f"Error in scheduled task polling: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _find_due_tasks(self) -> List[Dict[str, Any]]:
        """
        Find scheduled tasks that are due for execution.

        Returns:
            List of due scheduled tasks
        """
        try:
            container = cosmos_db.get_container_client(self.scheduled_tasks_container)

            # Query for pending tasks scheduled in the past
            now = datetime.utcnow().isoformat()

            query = (
                "SELECT c.* FROM c "
                "WHERE c.status = 'pending' "
                "AND c.scheduled_at <= @now "
                "AND c.retry_count < c.max_retries"
            )

            results = list(
                container.query_items(
                    query=query,
                    parameters=[{"name": "@now", "value": now}],
                )
            )

            logger.debug(f"Found {len(results)} due scheduled tasks")
            return results

        except Exception as e:
            logger.error(f"Error finding due scheduled tasks: {str(e)}")
            return []

    def _execute_scheduled_task(self, task: Dict[str, Any]) -> bool:
        """
        Execute a single scheduled task.

        Checks conditions before sending message.

        Args:
            task: Scheduled task data

        Returns:
            True if successful, False otherwise
        """
        try:
            task_id = task.get("id")
            account_id = task.get("account_id")
            contact_id = task.get("contact_id")

            logger.info(f"Executing scheduled task {task_id}")

            # Check conditions
            if not self._check_conditions(account_id, contact_id, task):
                logger.info(f"Conditions not met for task {task_id}, will retry later")
                # Update task status
                self._update_task_status(task, "pending", retry=True)
                return False

            # Get message template
            message_template = task.get("message_template")

            if not message_template:
                logger.error(f"No message template in task {task_id}")
                self._update_task_status(task, "failed")
                return False

            from app.services.instagram_api import instagram_api
            from app.services.message_builder import message_builder

            # Build message
            context = {
                "account_id": account_id,
                "contact_id": contact_id,
                "task_id": task_id,
            }

            message = message_builder.build_message(message_template, context)

            if not message:
                logger.error(f"Failed to build message for task {task_id}")
                self._update_task_status(task, "failed")
                return False

            # Send message
            instagram_api.send_dm(account_id, contact_id, message)

            # Log delivery
            self._log_message_delivery(account_id, contact_id, task_id, message, "sent")

            # Mark task as completed
            self._update_task_status(task, "completed")

            logger.info(f"Successfully executed scheduled task {task_id}")
            return True

        except Exception as e:
            logger.error(f"Error executing scheduled task: {str(e)}")
            self._update_task_status(task, "failed")
            return False

    def _check_conditions(
        self, account_id: str, contact_id: str, task: Dict[str, Any]
    ) -> bool:
        """
        Check conditions before sending scheduled message.

        Conditions: no_reply, messaging_window active

        Args:
            account_id: Account ID
            contact_id: Contact ID
            task: Task data

        Returns:
            True if conditions are met
        """
        try:
            conditions = task.get("conditions", {})

            # Check no_reply condition
            if conditions.get("require_no_reply"):
                if not self._check_no_reply_condition(account_id, contact_id):
                    logger.debug(f"no_reply condition not met for contact {contact_id}")
                    return False

            # Check messaging_window condition
            if conditions.get("require_messaging_window"):
                if not self._check_messaging_window(account_id, contact_id):
                    logger.debug(
                        f"messaging_window condition not met for contact {contact_id}"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking conditions: {str(e)}")
            return False

    def _check_no_reply_condition(self, account_id: str, contact_id: str) -> bool:
        """
        Check if contact has not replied recently.

        Args:
            account_id: Account ID
            contact_id: Contact ID

        Returns:
            True if contact hasn't replied
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.last_message_received_at FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                return True

            # If last message received is older than 1 hour, consider as no recent reply
            last_reply = results[0].get("last_message_received_at")

            if not last_reply:
                return True

            last_reply_dt = datetime.fromisoformat(last_reply)
            time_since_reply = (datetime.utcnow() - last_reply_dt).total_seconds()

            return time_since_reply > 3600  # 1 hour

        except Exception as e:
            logger.error(f"Error checking no_reply condition: {str(e)}")
            return False

    def _check_messaging_window(self, account_id: str, contact_id: str) -> bool:
        """
        Check if messaging window is still active.

        Args:
            account_id: Account ID
            contact_id: Contact ID

        Returns:
            True if messaging window is active
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.messaging_window_expires FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                return False

            expires = results[0].get("messaging_window_expires")

            if not expires:
                return False

            expires_dt = datetime.fromisoformat(expires)
            return datetime.utcnow() < expires_dt

        except Exception as e:
            logger.error(f"Error checking messaging window: {str(e)}")
            return False

    def _update_task_status(
        self, task: Dict[str, Any], status: str, retry: bool = False
    ) -> None:
        """
        Update task status in database.

        Args:
            task: Task data
            status: New status
            retry: Whether this is a retry
        """
        try:
            container = cosmos_db.get_container_client(self.scheduled_tasks_container)

            task["status"] = status
            task["updated_at"] = datetime.utcnow().isoformat()

            if retry:
                task["retry_count"] = task.get("retry_count", 0) + 1
            elif status == "completed":
                task["completed_at"] = datetime.utcnow().isoformat()

            container.replace_item(task["id"], task, partition_key=task.get("account_id"))
            logger.debug(f"Updated task {task['id']} status to {status}")

        except Exception as e:
            logger.error(f"Error updating task status: {str(e)}")

    def _log_message_delivery(
        self,
        account_id: str,
        contact_id: str,
        task_id: str,
        message: Dict[str, Any],
        status: str,
    ) -> None:
        """
        Log message delivery.

        Args:
            account_id: Account ID
            contact_id: Contact ID
            task_id: Task ID
            message: Message content
            status: Delivery status
        """
        try:
            container = cosmos_db.get_container_client(self.message_logs_container)

            log_entry = {
                "id": f"msg_{int(datetime.utcnow().timestamp())}_{contact_id}",
                "account_id": account_id,
                "contact_id": contact_id,
                "task_id": task_id,
                "message": message,
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
            }

            container.create_item(log_entry)

        except Exception as e:
            logger.error(f"Error logging message delivery: {str(e)}")


# Global executor instance
scheduled_executor = ScheduledTaskExecutor()


# Celery task
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True)
def poll_and_execute_scheduled_tasks(self):
    """
    Celery task to poll and execute scheduled tasks.

    This is scheduled to run every 30 seconds.
    """
    try:
        result = scheduled_executor.poll_and_execute_scheduled_tasks()
        logger.debug(f"Scheduled task polling result: {result}")
        return result

    except Exception as e:
        logger.error(f"Scheduled task polling failed: {str(e)}")
        raise
