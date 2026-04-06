"""Celery task for aggregating message logs into daily analytics."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db

logger = logging.getLogger(__name__)


class AnalyticsAggregator:
    """Handle aggregation of message logs into analytics."""

    def __init__(self):
        """Initialize analytics aggregator."""
        self.message_logs_container = dm_settings.DM_MESSAGE_LOGS_CONTAINER
        self.analytics_container = dm_settings.DM_ANALYTICS_CONTAINER

    def aggregate_message_logs(self) -> Dict[str, Any]:
        """
        Aggregate message logs from the previous day into daily analytics.

        This task runs daily at 1 AM and aggregates data for the previous day.

        Returns:
            Aggregation result with counts and metrics
        """
        try:
            logger.info("Starting message log aggregation")

            # Calculate date range for previous day
            now = datetime.utcnow()
            previous_day_start = (now - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            previous_day_end = previous_day_start + timedelta(days=1)

            logger.info(
                f"Aggregating logs from {previous_day_start} to {previous_day_end}"
            )

            # Query message logs for the day
            message_logs = self._fetch_message_logs(previous_day_start, previous_day_end)

            if not message_logs:
                logger.info("No message logs found for aggregation")
                return {
                    "status": "success",
                    "aggregated_count": 0,
                    "analytics_created": 0,
                }

            logger.info(f"Found {len(message_logs)} message logs to aggregate")

            # Aggregate data
            analytics_by_account = self._aggregate_by_account(message_logs)

            # Store aggregated analytics
            stored_count = 0
            for account_id, metrics in analytics_by_account.items():
                try:
                    self._store_daily_analytics(
                        account_id, previous_day_start, metrics
                    )
                    stored_count += 1
                except Exception as e:
                    logger.error(
                        f"Error storing analytics for account {account_id}: {str(e)}"
                    )

            logger.info(f"Analytics aggregation completed: {stored_count} accounts")

            return {
                "status": "success",
                "aggregated_count": len(message_logs),
                "analytics_created": stored_count,
            }

        except Exception as e:
            logger.exception(f"Error in analytics aggregation: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _fetch_message_logs(
        self, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        """
        Fetch message logs for a time period.

        Args:
            start_time: Start of time period
            end_time: End of time period

        Returns:
            List of message logs
        """
        try:
            container = cosmos_db.get_container_client(self.message_logs_container)

            start_iso = start_time.isoformat()
            end_iso = end_time.isoformat()

            query = (
                "SELECT c.* FROM c "
                "WHERE c.timestamp >= @start_time "
                "AND c.timestamp < @end_time "
                "AND c.partition_key = 'message_log'"
            )

            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@start_time", "value": start_iso},
                        {"name": "@end_time", "value": end_iso},
                    ],
                )
            )

            logger.debug(f"Fetched {len(results)} message logs")
            return results

        except Exception as e:
            logger.error(f"Error fetching message logs: {str(e)}")
            return []

    def _aggregate_by_account(
        self, message_logs: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate message logs by account and calculate metrics.

        Args:
            message_logs: List of message logs

        Returns:
            Aggregated metrics by account
        """
        try:
            analytics = defaultdict(lambda: {
                "total_messages_sent": 0,
                "total_messages_delivered": 0,
                "total_messages_failed": 0,
                "contacts_messaged": set(),
                "automations_triggered": defaultdict(int),
                "status_breakdown": defaultdict(int),
            })

            for log in message_logs:
                account_id = log.get("account_id")
                contact_id = log.get("contact_id")
                status = log.get("status", "unknown")
                automation_id = log.get("automation_id")

                if not account_id:
                    continue

                account_analytics = analytics[account_id]

                # Count messages by status
                if status == "sent":
                    account_analytics["total_messages_sent"] += 1
                elif status == "delivered":
                    account_analytics["total_messages_delivered"] += 1
                elif status == "failed":
                    account_analytics["total_messages_failed"] += 1

                account_analytics["status_breakdown"][status] += 1
                account_analytics["contacts_messaged"].add(contact_id)

                # Count automation triggers
                if automation_id:
                    account_analytics["automations_triggered"][automation_id] += 1

            # Convert to final format
            final_analytics = {}
            for account_id, metrics in analytics.items():
                final_analytics[account_id] = {
                    "total_messages_sent": metrics["total_messages_sent"],
                    "total_messages_delivered": metrics["total_messages_delivered"],
                    "total_messages_failed": metrics["total_messages_failed"],
                    "unique_contacts": len(metrics["contacts_messaged"]),
                    "status_breakdown": dict(metrics["status_breakdown"]),
                    "automations_triggered": dict(metrics["automations_triggered"]),
                }

            logger.debug(f"Aggregated data for {len(final_analytics)} accounts")
            return final_analytics

        except Exception as e:
            logger.error(f"Error aggregating by account: {str(e)}")
            return {}

    def _store_daily_analytics(
        self,
        account_id: str,
        date: datetime,
        metrics: Dict[str, Any],
    ) -> None:
        """
        Store aggregated daily analytics in database.

        Args:
            account_id: Account ID
            date: Date of analytics
            metrics: Aggregated metrics
        """
        try:
            container = cosmos_db.get_container_client(self.analytics_container)

            # Create analytics record
            date_str = date.strftime("%Y-%m-%d")
            analytics_record = {
                "id": f"analytics_{account_id}_{date_str}",
                "account_id": account_id,
                "date": date_str,
                "metrics": metrics,
                "created_at": datetime.utcnow().isoformat(),
            }

            container.create_item(analytics_record)
            logger.debug(
                f"Stored daily analytics for account {account_id} on {date_str}"
            )

        except Exception as e:
            logger.error(f"Error storing daily analytics: {str(e)}")
            raise

    def cleanup_old_analytics(self, retention_days: int = None) -> Dict[str, Any]:
        """
        Clean up message logs older than retention period.

        Args:
            retention_days: Days to retain (uses config if None)

        Returns:
            Cleanup result
        """
        try:
            if retention_days is None:
                retention_days = dm_settings.ANALYTICS_RETENTION_DAYS

            logger.info(f"Cleaning up message logs older than {retention_days} days")

            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            cutoff_iso = cutoff_date.isoformat()

            container = cosmos_db.get_container_client(self.message_logs_container)

            # Query old logs
            query = (
                "SELECT c.id FROM c "
                "WHERE c.timestamp < @cutoff_time "
                "AND c.partition_key = 'message_log'"
            )

            results = list(
                container.query_items(
                    query=query,
                    parameters=[{"name": "@cutoff_time", "value": cutoff_iso}],
                )
            )

            deleted_count = 0

            # Delete old logs
            for log in results:
                try:
                    container.delete_item(log["id"], partition_key=log.get("account_id", "unknown"))
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting log {log['id']}: {str(e)}")

            logger.info(f"Cleaned up {deleted_count} old message logs")

            return {
                "status": "success",
                "deleted_count": deleted_count,
            }

        except Exception as e:
            logger.exception(f"Error cleaning up old analytics: {str(e)}")
            return {"status": "error", "error": str(e)}


# Global aggregator instance
analytics_aggregator = AnalyticsAggregator()


# Celery tasks
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def aggregate_message_logs(self):
    """
    Celery task to aggregate message logs into daily analytics.

    This is scheduled to run daily at 1 AM.
    """
    try:
        result = analytics_aggregator.aggregate_message_logs()
        logger.info(f"Analytics aggregation result: {result}")
        return result

    except Exception as e:
        logger.error(f"Analytics aggregation task failed: {str(e)}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


@celery_app.task(bind=True)
def cleanup_old_analytics(self, retention_days: int = None):
    """
    Celery task to clean up old analytics data.

    Can be called on-demand or scheduled.
    """
    try:
        result = analytics_aggregator.cleanup_old_analytics(retention_days)
        logger.info(f"Analytics cleanup result: {result}")
        return result

    except Exception as e:
        logger.error(f"Analytics cleanup task failed: {str(e)}")
        raise
