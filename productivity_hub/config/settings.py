"""
Application Configuration Module.

Loads environment variables using python-dotenv, validates mandatory fields,
supplies sensible defaults for optional settings, and ensures sensitive credentials
are NEVER exposed in logs or console output.
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv


class ConfigError(ValueError):
    """Custom exception raised when application configuration is invalid or incomplete."""
    pass


@dataclass
class Settings:
    """
    Strongly-typed application settings dataclass.
    
    Attributes:
        BOT_TOKEN: Telegram Bot API Token obtained from @BotFather (MANDATORY).
        OWNER_ID: Numeric Telegram User ID of the primary administrator (MANDATORY).
        SECRET_KEY: Cryptographic key used for signing/encryption (Auto-generated if missing).
        WEBHOOK_URL: Public HTTPS URL for webhook mode (Optional).
        CHANNEL_USERNAME: Telegram channel username required for membership checks (Optional).
        BOT_MODE: Operational mode: 'polling' or 'webhook' (Default: 'polling').
        PORT: HTTP port for the health check web server (Default: 8000).
        DATABASE_PATH: File path to the SQLite database (Default: 'database/app.sqlite3').
        LOG_LEVEL: Logging verbosity level (Default: 'INFO').
        MAX_CONCURRENT_TASKS: Global limit for concurrent task processing (Default: 5).
        MAX_USER_ACTIVE_TASKS: Per-user limit for concurrent active tasks (Default: 3).
        MAX_USER_QUEUE_TASKS: Per-user limit for queued tasks (Default: 10).
        MAX_QUEUE_SIZE: Global capacity limit for the task queue (Default: 50).
        TEMP_RETENTION_MINUTES: Temporary file retention threshold in minutes (Default: 60).
        MAX_FILE_SIZE: Maximum file upload/download size limit in MB (Default: 50).
        MAINTENANCE_MODE: Flag indicating if the bot is in maintenance mode (Default: False).
    """

    # Mandatory
    BOT_TOKEN: str
    OWNER_ID: int

    # Optional / Defaults
    SECRET_KEY: str
    WEBHOOK_URL: Optional[str] = None
    CHANNEL_USERNAME: Optional[str] = None
    BOT_MODE: str = "polling"
    PORT: int = 8000
    DATABASE_PATH: str = "database/app.sqlite3"
    LOG_LEVEL: str = "INFO"
    MAX_CONCURRENT_TASKS: int = 2
    MAX_USER_ACTIVE_TASKS: int = 1
    MAX_USER_QUEUE_TASKS: int = 3
    MAX_QUEUE_SIZE: int = 50
    TEMP_RETENTION_MINUTES: int = 60
    MAX_FILE_SIZE: int = 50
    MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024
    TELEGRAM_UPLOAD_LIMIT_BYTES: int = 50 * 1024 * 1024
    TELEGRAM_DOWNLOAD_LIMIT_BYTES: int = 20 * 1024 * 1024
    MAINTENANCE_MODE: bool = False

    def __post_init__(self):
        # Harmonize MAX_FILE_SIZE and MAX_FILE_SIZE_BYTES
        if self.MAX_FILE_SIZE_BYTES == 50 * 1024 * 1024 and self.MAX_FILE_SIZE != 50:
            self.MAX_FILE_SIZE_BYTES = self.MAX_FILE_SIZE * 1024 * 1024
        elif self.MAX_FILE_SIZE == 50 and self.MAX_FILE_SIZE_BYTES != 50 * 1024 * 1024:
            self.MAX_FILE_SIZE = max(1, self.MAX_FILE_SIZE_BYTES // (1024 * 1024))

        if self.TELEGRAM_UPLOAD_LIMIT_BYTES > self.MAX_FILE_SIZE_BYTES:
            self.TELEGRAM_UPLOAD_LIMIT_BYTES = self.MAX_FILE_SIZE_BYTES

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_BYTES

    @property
    def max_file_size_mb(self) -> float:
        return self.MAX_FILE_SIZE_BYTES / (1024 * 1024)

    @classmethod
    def load_from_env(cls, env_path: Optional[str] = None) -> "Settings":
        """
        Load environment variables from a .env file and environment, validate required parameters,
        and instantiate Settings.

        Args:
            env_path: Optional custom path to a .env file.

        Returns:
            Settings: Validated configuration instance.

        Raises:
            ConfigError: If any mandatory variable is missing or invalid.
        """
        # Load .env file if available
        if env_path:
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            load_dotenv(override=False)

        # 1. Validate mandatory BOT_TOKEN
        raw_bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not raw_bot_token:
            raise ConfigError(
                "CRITICAL: Mandatory environment variable 'BOT_TOKEN' is missing or empty. "
                "Please obtain a valid token from @BotFather and set BOT_TOKEN in your environment or .env file."
            )

        # 2. Validate mandatory OWNER_ID
        raw_owner_id = os.getenv("OWNER_ID", "").strip()
        if not raw_owner_id:
            raise ConfigError(
                "CRITICAL: Mandatory environment variable 'OWNER_ID' is missing or empty. "
                "Please set OWNER_ID to your numeric Telegram user ID."
            )
        try:
            owner_id = int(raw_owner_id)
        except ValueError:
            raise ConfigError(
                f"CRITICAL: Environment variable 'OWNER_ID' must be a valid integer, got '{raw_owner_id}'."
            )

        # 3. Handle SECRET_KEY (Generate secure 64-char hex key if not provided)
        raw_secret_key = os.getenv("SECRET_KEY", "").strip()
        if not raw_secret_key:
            secret_key = secrets.token_hex(32)
        else:
            secret_key = raw_secret_key

        # 4. Optional variables with defaults and type casting
        raw_webhook_url = os.getenv("WEBHOOK_URL", "").strip() or None
        
        raw_channel_username = os.getenv("CHANNEL_USERNAME", "").strip() or None
        if raw_channel_username and not raw_channel_username.startswith("@"):
            raw_channel_username = f"@{raw_channel_username}"

        bot_mode = os.getenv("BOT_MODE", "polling").strip().lower()
        if bot_mode not in ("polling", "webhook"):
            bot_mode = "polling"

        port = cls._safe_int("PORT", os.getenv("PORT"), 8000)
        database_path = os.getenv("DATABASE_PATH", "database/app.sqlite3").strip()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        
        if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            log_level = "INFO"

        max_concurrent_tasks = cls._safe_int("MAX_CONCURRENT_TASKS", os.getenv("MAX_CONCURRENT_TASKS"), 2)
        max_user_active_tasks = cls._safe_int("MAX_USER_ACTIVE_TASKS", os.getenv("MAX_USER_ACTIVE_TASKS"), 1)
        max_user_queue_tasks = cls._safe_int("MAX_USER_QUEUE_TASKS", os.getenv("MAX_USER_QUEUE_TASKS"), 3)
        max_queue_size = cls._safe_int("MAX_QUEUE_SIZE", os.getenv("MAX_QUEUE_SIZE"), 50)
        temp_retention_minutes = cls._safe_int("TEMP_RETENTION_MINUTES", os.getenv("TEMP_RETENTION_MINUTES"), 60)

        # File size limits (support both MAX_FILE_SIZE in MB and MAX_FILE_SIZE_BYTES)
        raw_size_bytes = os.getenv("MAX_FILE_SIZE_BYTES", "").strip()
        raw_size_mb = os.getenv("MAX_FILE_SIZE", "").strip() or os.getenv("MAX_FILE_SIZE_MB", "").strip()

        if raw_size_bytes:
            max_file_size_bytes = cls._safe_int("MAX_FILE_SIZE_BYTES", raw_size_bytes, 50 * 1024 * 1024)
            max_file_size = max(1, max_file_size_bytes // (1024 * 1024))
        else:
            max_file_size = cls._safe_int("MAX_FILE_SIZE", raw_size_mb, 50)
            max_file_size_bytes = max_file_size * 1024 * 1024

        telegram_upload_limit_bytes = cls._safe_int(
            "TELEGRAM_UPLOAD_LIMIT_BYTES",
            os.getenv("TELEGRAM_UPLOAD_LIMIT_BYTES"),
            min(max_file_size_bytes, 50 * 1024 * 1024)
        )
        telegram_download_limit_bytes = cls._safe_int(
            "TELEGRAM_DOWNLOAD_LIMIT_BYTES",
            os.getenv("TELEGRAM_DOWNLOAD_LIMIT_BYTES"),
            min(max_file_size_bytes, 20 * 1024 * 1024)
        )

        raw_maintenance = os.getenv("MAINTENANCE_MODE", "false").strip().lower()
        maintenance_mode = raw_maintenance in ("true", "1", "yes", "on")

        return cls(
            BOT_TOKEN=raw_bot_token,
            OWNER_ID=owner_id,
            SECRET_KEY=secret_key,
            WEBHOOK_URL=raw_webhook_url,
            CHANNEL_USERNAME=raw_channel_username,
            BOT_MODE=bot_mode,
            PORT=port,
            DATABASE_PATH=database_path,
            LOG_LEVEL=log_level,
            MAX_CONCURRENT_TASKS=max_concurrent_tasks,
            MAX_USER_ACTIVE_TASKS=max_user_active_tasks,
            MAX_USER_QUEUE_TASKS=max_user_queue_tasks,
            MAX_QUEUE_SIZE=max_queue_size,
            TEMP_RETENTION_MINUTES=temp_retention_minutes,
            MAX_FILE_SIZE=max_file_size,
            MAX_FILE_SIZE_BYTES=max_file_size_bytes,
            TELEGRAM_UPLOAD_LIMIT_BYTES=telegram_upload_limit_bytes,
            TELEGRAM_DOWNLOAD_LIMIT_BYTES=telegram_download_limit_bytes,
            MAINTENANCE_MODE=maintenance_mode,
        )

    @staticmethod
    def _safe_int(name: str, val: Optional[str], default: int) -> int:
        """Helper to safely parse integer configuration options with default fallback."""
        if val is None or not val.strip():
            return default
        try:
            return int(val.strip())
        except ValueError:
            return default

    def get_safe_summary(self) -> Dict[str, Any]:
        """
        Return a sanitized dictionary of non-sensitive settings suitable for logging and status summaries.
        Strictly masks BOT_TOKEN and SECRET_KEY to prevent credential leaks.
        """
        token_masked = f"{self.BOT_TOKEN[:6]}...{self.BOT_TOKEN[-4:]}" if len(self.BOT_TOKEN) > 10 else "***MASKED***"
        return {
            "BOT_TOKEN": token_masked,
            "OWNER_ID": self.OWNER_ID,
            "SECRET_KEY": "***MASKED***",
            "WEBHOOK_URL": self.WEBHOOK_URL,
            "CHANNEL_USERNAME": self.CHANNEL_USERNAME,
            "BOT_MODE": self.BOT_MODE,
            "PORT": self.PORT,
            "DATABASE_PATH": self.DATABASE_PATH,
            "LOG_LEVEL": self.LOG_LEVEL,
            "MAX_CONCURRENT_TASKS": self.MAX_CONCURRENT_TASKS,
            "MAX_USER_ACTIVE_TASKS": self.MAX_USER_ACTIVE_TASKS,
            "MAX_USER_QUEUE_TASKS": self.MAX_USER_QUEUE_TASKS,
            "MAX_QUEUE_SIZE": self.MAX_QUEUE_SIZE,
            "TEMP_RETENTION_MINUTES": self.TEMP_RETENTION_MINUTES,
            "MAX_FILE_SIZE_MB": self.MAX_FILE_SIZE,
            "MAX_FILE_SIZE_BYTES": self.MAX_FILE_SIZE_BYTES,
            "TELEGRAM_UPLOAD_LIMIT_BYTES": self.TELEGRAM_UPLOAD_LIMIT_BYTES,
            "MAINTENANCE_MODE": self.MAINTENANCE_MODE,
        }


# Global lazy settings cache
_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Retrieve or initialize the global Settings instance.

    Returns:
        Settings: Application configuration singleton.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings.load_from_env()
    return _settings_instance
