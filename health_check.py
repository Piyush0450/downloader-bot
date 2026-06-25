import os
import sys
import sqlite3
import shutil
from pathlib import Path

def check_env_vars() -> bool:
    print("Checking Environment Variables...")
    required = ["BOT_TOKEN", "OWNER_ID", "SECRET_KEY"]
    missing = []
    for var in required:
        val = os.getenv(var)
        if not val:
            missing.append(var)
    if missing:
        print(f"  [ERROR] Missing required variables: {', '.join(missing)}")
        return False
        
    secret = os.getenv("SECRET_KEY")
    if secret == "productivity_hub_default_secret":
        print("  [WARN] SECRET_KEY is set to insecure default.")
    else:
        print("  [OK] Required environment credentials found.")
    return True

def check_database() -> bool:
    print("Checking Database Connection...")
    from config.settings import DATABASE_URL
    
    db_path = DATABASE_URL
    if db_path.startswith("sqlite:///"):
        db_path = db_path.replace("sqlite:///", "")
    else:
        db_path = "database/bot.db"
        
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"  [OK] Database connected successfully. Tables found: {', '.join(tables) or 'None'}")
        conn.close()
        return True
    except Exception as e:
        print(f"  [ERROR] Database connection check failed: {e}")
        return False

def check_temp_directories() -> bool:
    print("Checking Directory Structures...")
    from config.settings import DATABASE_DIR, LOGS_DIR, TEMP_DIR, DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR, BACKUPS_DIR
    dirs = {
        "Database Folder": DATABASE_DIR,
        "Logs Folder": LOGS_DIR,
        "Temp Folder": TEMP_DIR,
        "Downloads Folder": DOWNLOADS_DIR,
        "Uploads Folder": UPLOADS_DIR,
        "Converted Folder": CONVERTED_DIR,
        "Thumbnails Folder": THUMBNAILS_DIR,
        "Backups Folder": BACKUPS_DIR
    }
    all_ok = True
    for name, path in dirs.items():
        if not path.exists():
            print(f"  [ERROR] {name} is missing at: {path}")
            all_ok = False
        else:
            print(f"  [OK] {name} exists.")
    return all_ok

def check_storage() -> bool:
    print("Checking Storage Performance & Disk Capacity...")
    from config.settings import TEMP_DIR
    
    test_file = TEMP_DIR / "health_check_write_test.tmp"
    try:
        test_file.write_text("healthcheck_test_data")
        content = test_file.read_text()
        if content != "healthcheck_test_data":
            raise ValueError("Read back data does not match written data.")
        test_file.unlink()
        print("  [OK] Storage read/write test passed.")
    except Exception as e:
        print(f"  [ERROR] Storage write test failed: {e}")
        return False
        
    try:
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_gb = free / (1024**3)
        print(f"  [OK] Free disk space: {free_gb:.2f} GB")
        if free_gb < 0.1:  # less than 100MB
            print("  [WARN] Free disk space is critically low (< 100MB).")
    except Exception as e:
        print(f"  [WARN] Could not read disk usage stats: {e}")
        
    return True

def run_health_check() -> int:
    print("=========================================")
    print("Productivity Hub Bot Health Check Utility")
    print("=========================================")
    
    try:
        from dotenv import load_dotenv, find_dotenv
        load_dotenv(find_dotenv())
    except ImportError:
        pass
        
    env_ok = check_env_vars()
    db_ok = check_database()
    dirs_ok = check_temp_directories()
    storage_ok = check_storage()
    
    print("=========================================")
    if env_ok and db_ok and dirs_ok and storage_ok:
        print("SUCCESS: System is healthy & production-ready.")
        return 0
    else:
        print("FAILURE: System is not configured properly.")
        return 1

if __name__ == "__main__":
    sys.exit(run_health_check())
