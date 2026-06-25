import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from config.settings import LOGS_DIR, LOG_LEVEL

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
formatter = logging.Formatter(LOG_FORMAT)

# Ensure logs directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Parse logging level
numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)

def create_rotating_handler(filename):
    handler = RotatingFileHandler(
        LOGS_DIR / filename,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8"
    )
    handler.setFormatter(formatter)
    return handler

# Root Logger (bot.log)
logger = logging.getLogger()
logger.setLevel(numeric_level)
if not logger.handlers:
    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    # File
    logger.addHandler(create_rotating_handler("bot.log"))

# Separate Loggers Helper
def setup_separate_logger(name, filename):
    l = logging.getLogger(name)
    l.setLevel(numeric_level)
    l.propagate = False  # Avoid logging duplicates to root logger
    if not l.handlers:
        l.addHandler(create_rotating_handler(filename))
        # Keep console handler for visibility
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        l.addHandler(console)
    return l

# Initialize specific rotating loggers
error_logger = setup_separate_logger("error", "error.log")
downloads_logger = setup_separate_logger("downloads", "downloads.log")
conversions_logger = setup_separate_logger("conversions", "conversions.log")
security_logger = setup_separate_logger("security", "security.log")
admin_logger = setup_separate_logger("admin", "admin.log")

# Mute noisy third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
