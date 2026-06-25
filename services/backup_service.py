import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from config.settings import ROOT_DIR, LOGS_DIR
from utils.logger import logger

BACKUPS_DIR = ROOT_DIR / "backups"

def run_backup() -> bool:
    """Creates a ZIP archive backup of the database, logs, and settings (.env).
    Keeps only the 7 most recent backups.
    """
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        backup_path = BACKUPS_DIR / backup_filename
        
        # Get active DB path dynamically
        from services.database_service import get_db_path
        db_file = Path(get_db_path())
        
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. Backup Database
            if db_file.exists():
                zipf.write(db_file, arcname=f"database/{db_file.name}")
                
            # 2. Backup Logs
            if LOGS_DIR.exists():
                for f in LOGS_DIR.glob("*"):
                    if f.is_file():
                        zipf.write(f, arcname=f"logs/{f.name}")
                        
            # 3. Backup Settings (.env)
            env_file = ROOT_DIR / ".env"
            if env_file.exists():
                zipf.write(env_file, arcname=".env")
                
        logger.info(f"System backup created successfully: {backup_filename}")
        
        # Enforce 7-day retention: sort backups by modification time and delete older ones
        all_backups = sorted(list(BACKUPS_DIR.glob("backup_*.zip")), key=lambda x: x.stat().st_mtime)
        if len(all_backups) > 7:
            for old_backup in all_backups[:-7]:
                try:
                    old_backup.unlink()
                    logger.info(f"Removed old backup: {old_backup.name}")
                except Exception as e:
                    logger.error(f"Failed to delete old backup {old_backup.name}: {e}")
                    
        return True
    except Exception as e:
        logger.error(f"Backup operation failed: {e}")
        return False
