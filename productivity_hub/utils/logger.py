"""
Logging Configuration Module.

Configures structured logging for the Productivity Hub application using Python's
built-in logging module and RotatingFileHandler. Ensures log files are properly segregated
(bot.log, error.log, security.log, admin.log) and mirrored to stdout for cloud deployment (Render).
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# Default constants for log rotation
LOG_DIR = Path("logs")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 5  # Keep up to 5 historical log backups

# Formatter strings
STANDARD_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] - %(message)s"
SEC_ADMIN_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_level_str: str = "INFO", log_dir: Path = LOG_DIR) -> logging.Logger:
    """
    Initialize application logging with rotating file handlers and console output.

    Args:
        log_level_str: String representation of log level ('DEBUG', 'INFO', 'WARNING', 'ERROR').
        log_dir: Directory path where log files will be created.

    Returns:
        logging.Logger: Root logger instance.
    """
    # 1. Create logs directory if missing
    log_dir.mkdir(parents=True, exist_ok=True)

    # 2. Determine numeric log level
    numeric_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # 3. Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear any pre-existing handlers to prevent duplicate log outputs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Formatter instances
    standard_formatter = logging.Formatter(STANDARD_FORMAT, datefmt=DATE_FORMAT)
    sec_formatter = logging.Formatter(SEC_ADMIN_FORMAT, datefmt=DATE_FORMAT)

    # 4. Console Handler (stdout) for Docker / Render container logging
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(standard_formatter)
    root_logger.addHandler(console_handler)

    # 5. Rotating Handler for General Bot Logs (bot.log)
    bot_file_handler = RotatingFileHandler(
        filename=log_dir / "bot.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )
    bot_file_handler.setLevel(numeric_level)
    bot_file_handler.setFormatter(standard_formatter)
    root_logger.addHandler(bot_file_handler)

    # 6. Rotating Handler for Error Logs Only (error.log)
    error_file_handler = RotatingFileHandler(
        filename=log_dir / "error.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(standard_formatter)
    root_logger.addHandler(error_file_handler)

    # 7. Dedicated Security Logger (security.log)
    security_logger = logging.getLogger("security")
    security_logger.setLevel(numeric_level)
    security_logger.propagate = False  # Don't duplicate in root logger
    sec_file_handler = RotatingFileHandler(
        filename=log_dir / "security.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )
    sec_file_handler.setLevel(numeric_level)
    sec_file_handler.setFormatter(sec_formatter)
    security_logger.addHandler(sec_file_handler)
    security_logger.addHandler(console_handler)

    # 8. Dedicated Admin Logger (admin.log)
    admin_logger = logging.getLogger("admin")
    admin_logger.setLevel(numeric_level)
    admin_logger.propagate = False  # Don't duplicate in root logger
    admin_file_handler = RotatingFileHandler(
        filename=log_dir / "admin.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )
    admin_file_handler.setLevel(numeric_level)
    admin_file_handler.setFormatter(sec_formatter)
    admin_logger.addHandler(admin_file_handler)
    admin_logger.addHandler(console_handler)

    # Silence noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    root_logger.info("Logging infrastructure initialized successfully.")
    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Retrieve a logger instance by name.

    Args:
        name: Logger name (e.g., 'productivity_hub.bot', 'security', 'admin').

    Returns:
        logging.Logger: Named logger instance.
    """
    return logging.getLogger(name or "productivity_hub")


def get_security_logger() -> logging.Logger:
    """Retrieve the dedicated security logger."""
    return logging.getLogger("security")


def get_admin_logger() -> logging.Logger:
    """Retrieve the dedicated admin logger."""
    return logging.getLogger("admin")
