import os
import sys
import sqlite3
from pathlib import Path
from config.settings import (
    BOT_TOKEN, OWNER_ID, SECRET_KEY, DATABASE_DIR, LOGS_DIR, TEMP_DIR,
    DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR, BACKUPS_DIR,
    BOT_MODE
)
from utils.logger import logger

def validate_startup() -> bool:
    """Verifies environment variables, database connection, auto-creates folders,
    and displays a formatted startup banner.
    Returns True if validation succeeds, raises SystemExit or exits on critical errors.
    """
    errors = []
    
    # 1. Environment credentials validation
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is missing in environment.")
    if not OWNER_ID:
        errors.append("OWNER_ID is missing or invalid in environment.")
    if not SECRET_KEY:
        errors.append("SECRET_KEY is missing in environment.")
    elif SECRET_KEY == "productivity_hub_default_secret":
        errors.append("SECRET_KEY is set to the default insecure value.")
        
    # 2. Folder validation and auto-creation
    dirs_status = True
    required_dirs = [
        DATABASE_DIR, LOGS_DIR, TEMP_DIR,
        DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR,
        BACKUPS_DIR
    ]
    for d in required_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Failed to create directory {d}: {e}")
            dirs_status = False

    # 3. Database connection check
    db_connected = False
    from services.database_service import get_db_path
    db_path = get_db_path()
    try:
        # Ensure database directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Test SQLite connection
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        db_connected = True
    except Exception as e:
        errors.append(f"Database connectivity check failed: {e}")

    # Process validation failures
    if errors:
        logger.critical("STARTUP VALIDATION FAILED:")
        for err in errors:
            logger.critical(f"  - {err}")
        print("\nCRITICAL: Startup validation failed.", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    # 4. Formulate and log startup banner
    env_name = "Production" if BOT_MODE == "webhook" else "Development"
    db_status = "Connected" if db_connected else "Failed"
    sec_status = "OK" if (SECRET_KEY and SECRET_KEY != "productivity_hub_default_secret") else "WARNING"
    dirs_status_str = "OK" if dirs_status else "FAILED"
    
    banner = f"""
================================
Productivity Hub Bot
====================

Environment: {env_name}

Database: {db_status}

Security: {sec_status}

Directories: {dirs_status_str}

Bot Mode: {BOT_MODE.upper()}

Startup Validation: PASSED

================================
"""
    # Print to console and log at INFO level
    print(banner)
    logger.info("Startup Validation: PASSED")
    logger.info(f"Startup config loaded. Env: {env_name}, DB: {db_status}, Mode: {BOT_MODE.upper()}")
    
    return True
