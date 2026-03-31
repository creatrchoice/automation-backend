"""Configuration for Instagram DM Automation Platform."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List


class DMAutomationSettings(BaseSettings):
    """All application settings loaded from environment variables."""

    # ===== Instagram App Configuration =====
    INSTAGRAM_APP_ID: str = Field(default="", description="Instagram App ID for OAuth")
    INSTAGRAM_APP_SECRET: str = Field(default="", description="Instagram App Secret for OAuth")
    INSTAGRAM_REDIRECT_URI: str = Field(
        default="http://localhost:8000/api/v1/auth/instagram/callback",
        description="OAuth redirect URI registered in Meta Developer Dashboard"
    )
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = Field(default="", description="Default Instagram Business Account ID")
    INSTAGRAM_API_VERSION: str = Field(default="v21.0", description="Instagram Graph API version")
    INSTAGRAM_API_BASE_URL: str = Field(
        default="https://graph.instagram.com",
        description="Instagram Graph API base URL"
    )

    # ===== Webhook Configuration =====
    WEBHOOK_VERIFY_TOKEN: str = Field(default="", description="Webhook verification token for Instagram")
    WEBHOOK_TIMEOUT_SECONDS: int = Field(default=30, description="Webhook processing timeout")
    MAX_WEBHOOK_RETRIES: int = Field(default=3, description="Max webhook delivery retry attempts")

    # ===== Security / JWT =====
    JWT_SECRET_KEY: str = Field(default="", description="JWT secret key for token signing")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="JWT access token expiration")
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="JWT refresh token expiration")

    # ===== Encryption =====
    AZURE_KEY_VAULT_URL: str = Field(default="", description="Azure Key Vault URL for secret encryption")
    ENCRYPTION_KEY: str = Field(default="", description="Fernet encryption key (fallback if no Key Vault)")
    ENCRYPTION_ALGORITHM: str = Field(default="AES-256-GCM", description="Encryption algorithm for tokens")

    # ===== Azure Service Bus =====
    AZURE_SERVICE_BUS_CONNECTION_STRING: str = Field(
        default="",
        description="Azure Service Bus connection string"
    )
    AZURE_SERVICE_BUS_QUEUE_NAME: str = Field(
        default="instagram-webhooks",
        description="Queue name for DM processing"
    )

    # ===== Azure Cosmos DB =====
    AZURE_COSMOS_ENDPOINT: str = Field(default="", description="Cosmos DB endpoint URL")
    AZURE_COSMOS_KEY: str = Field(default="", description="Cosmos DB primary key")
    DM_DATABASE_NAME: str = Field(default="dm_automation_db", description="Cosmos DB database name")

    # Cosmos DB Container Names
    DM_USERS_CONTAINER: str = Field(default="users", description="Users container")
    DM_IG_ACCOUNTS_CONTAINER: str = Field(default="instagram_accounts", description="Instagram accounts container")
    DM_AUTOMATIONS_CONTAINER: str = Field(default="automations", description="Automations container")
    DM_CONTACTS_CONTAINER: str = Field(default="contacts", description="Contacts container")
    DM_MESSAGE_LOGS_CONTAINER: str = Field(default="message_logs", description="Message logs container")
    DM_WEBHOOK_EVENTS_CONTAINER: str = Field(default="webhook_events", description="Webhook events container")
    DM_SCHEDULED_TASKS_CONTAINER: str = Field(default="scheduled_tasks", description="Scheduled tasks container")
    DM_ANALYTICS_CONTAINER: str = Field(default="analytics_daily", description="Analytics container")

    # ===== Redis =====
    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_USERNAME: str = Field(default="", description="Redis username")
    REDIS_PASSWORD: str = Field(default="", description="Redis password")
    REDIS_SSL: bool = Field(default=False, description="Use SSL for Redis connection")

    # ===== Rate Limiting =====
    DM_RATE_LIMIT_PER_HOUR: int = Field(default=200, description="Max DMs per account per hour")
    CONTACT_RATE_LIMIT_PER_HOUR: int = Field(default=1000, description="Max contacts queried per hour")
    WEBHOOK_RATE_LIMIT_PER_SECOND: int = Field(default=100, description="Max webhook events per second")

    # ===== Deduplication & Caching =====
    DEDUP_TTL_HOURS: int = Field(default=24, description="Message dedup cache TTL in hours")
    AUTOMATION_CACHE_TTL_HOURS: int = Field(default=2, description="Automation config cache TTL")
    CONTACT_CACHE_TTL_HOURS: int = Field(default=1, description="Contact data cache TTL")
    ACCOUNT_MAP_CACHE_TTL_HOURS: int = Field(default=6, description="Account mapping cache TTL")

    # ===== Message Configuration =====
    MAX_MESSAGE_LENGTH: int = Field(default=1000, description="Max DM message length")
    MAX_CAROUSEL_ELEMENTS: int = Field(default=10, description="Max carousel elements in template")
    MAX_BUTTONS_PER_ELEMENT: int = Field(default=3, description="Max buttons per carousel element")
    MESSAGING_WINDOW_HOURS: int = Field(default=24, description="Hours after last contact message to send DM")

    # ===== Automation Configuration =====
    MAX_AUTOMATION_STEPS: int = Field(default=20, description="Max steps in an automation chain")
    MAX_CONDITIONS_PER_STEP: int = Field(default=10, description="Max conditions per step")
    AUTO_RETRY_FAILED_DELIVERY: bool = Field(default=True, description="Automatically retry failed deliveries")
    AUTO_RETRY_DELAY_SECONDS: int = Field(default=300, description="Delay before retrying failed message")

    # ===== Analytics =====
    ANALYTICS_BATCH_SIZE: int = Field(default=100, description="Batch size for analytics aggregation")
    ANALYTICS_RETENTION_DAYS: int = Field(default=90, description="Days to retain detailed analytics")
    PERFORMANCE_TRACKING_ENABLED: bool = Field(default=True, description="Enable latency tracking")

    # ===== CORS =====
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated list of allowed CORS origins"
    )

    # ===== Application =====
    ENVIRONMENT: str = Field(default="development", description="Environment name")
    DEBUG: bool = Field(default=False, description="Debug mode")

    # ===== Feature Flags =====
    ENABLE_HUMAN_HANDOFF: bool = Field(default=True, description="Enable human handoff feature")
    ENABLE_CONTACT_ENRICHMENT: bool = Field(default=False, description="Enable contact enrichment")
    ENABLE_AI_MESSAGE_GENERATION: bool = Field(default=False, description="Enable AI message generation")

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string into list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


# Single settings instance used throughout the app
dm_settings = DMAutomationSettings()

# Alias for backward compatibility (some modules import 'settings')
settings = dm_settings
