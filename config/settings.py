import os
import sys
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Base Paths
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(find_dotenv() or (ROOT_DIR / ".env"))

# Validation errors list
errors = []

# BOT_TOKEN is mandatory
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    errors.append("BOT_TOKEN is missing. Please set it in your environment or .env file.")

# OWNER_ID is mandatory
OWNER_ID_RAW = os.getenv("OWNER_ID")
OWNER_ID = 0
if not OWNER_ID_RAW:
    errors.append("OWNER_ID is missing. Please set it (numeric user ID) in your environment or .env file.")
else:
    try:
        OWNER_ID = int(OWNER_ID_RAW)
    except ValueError:
        errors.append(f"OWNER_ID must be a numeric integer. Got: '{OWNER_ID_RAW}'")

# SECRET_KEY is mandatory and must be secure
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    errors.append("SECRET_KEY is missing. Please set it in your environment or .env file.")
elif SECRET_KEY == "productivity_hub_default_secret":
    errors.append("SECRET_KEY is using the insecure default value. Please generate a unique secret key.")

# BOT_MODE validation
BOT_MODE = os.getenv("BOT_MODE", "polling").lower()
if BOT_MODE not in ("polling", "webhook"):
    errors.append(f"BOT_MODE must be either 'polling' or 'webhook'. Got: '{BOT_MODE}'")

# WEBHOOK_URL is required only when BOT_MODE = webhook
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
if BOT_MODE == "webhook" and not WEBHOOK_URL:
    errors.append("WEBHOOK_URL is required when BOT_MODE is set to 'webhook'.")

# If validation errors occurred, raise a human-readable ValueError
if errors:
    print("\n[ERROR] CONFIGURATION ERROR:", file=sys.stderr)
    for err in errors:
        print(f"   - {err}", file=sys.stderr)
    print("==================================================\n", file=sys.stderr)
    raise ValueError("Configuration validation failed:\n" + "\n".join(errors))

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
