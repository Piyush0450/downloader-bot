import os
import sys
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Base Paths
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(find_dotenv() or (ROOT_DIR / ".env"))

# Configuration settings loading (Validation is performed in startup service)
BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID_RAW = os.getenv("OWNER_ID")
OWNER_ID = 0
if OWNER_ID_RAW:
    try:
        OWNER_ID = int(OWNER_ID_RAW)
    except ValueError:
        pass

SECRET_KEY = os.getenv("SECRET_KEY")
BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# Optional Settings & Configurations
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
DATABASE_PATH = os.getenv("DATABASE_PATH")
if DATABASE_PATH:
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
else:
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT_DIR}/database/bot.db")

PORT_RAW = os.getenv("PORT", "8000")
try:
    PORT = int(PORT_RAW)
except ValueError:
    PORT = 8000

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Proxy Configuration (optional — useful when Telegram is blocked in your region)
# Example: PROXY_URL=socks5://user:pass@host:port  OR  http://host:port
PROXY_URL = os.getenv("PROXY_URL", "").strip()

# Connection Retry Configuration
CONNECT_RETRY_ATTEMPTS = 0   # 0 = retry forever until connected
CONNECT_RETRY_DELAY = 10     # seconds between retries

# Directory Structures Setup
DATABASE_DIR = ROOT_DIR / "database"
LOGS_DIR = ROOT_DIR / "logs"
TEMP_DIR = ROOT_DIR / "temp"
DOWNLOADS_DIR = TEMP_DIR / "downloads"
UPLOADS_DIR = TEMP_DIR / "uploads"
CONVERTED_DIR = TEMP_DIR / "converted"
THUMBNAILS_DIR = TEMP_DIR / "thumbnails"
BACKUPS_DIR = ROOT_DIR / "backups"

# Ensure all folders exist (including backups)
for folder in (DATABASE_DIR, LOGS_DIR, TEMP_DIR, DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR, BACKUPS_DIR):
    folder.mkdir(parents=True, exist_ok=True)

# Whitelists & Limits
DOWNLOAD_WHITELIST = [
    "youtube.com", "youtu.be", "instagram.com", "facebook.com", "fb.watch",
    "tiktok.com", "twitter.com", "x.com", "reddit.com", "pinterest.com",
    "pin.it", "snapchat.com"
]

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB logical limit
MAX_PROCESSING_TIME = 600  # 10 minutes (in seconds)
AUTO_DELETE_TIME = 900  # 15 minutes (in seconds)

# Security rate limit config
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = 15  # requests per window

# Security Warning & Ban thresholds
SUSPICIOUS_WARN_THRESHOLD = 3
SUSPICIOUS_BAN_THRESHOLD = 5
