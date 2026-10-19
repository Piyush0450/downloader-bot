"""
Productivity Hub Telegram Bot - Main Entry Point & Orchestrator.

Implements the 13-step startup lifecycle sequence, orchestrates the aiohttp health endpoint,
Task Queue Service, Cleanup Service, and python-telegram-bot async application concurrently,
prints safe startup diagnostics, and handles SIGTERM / SIGINT for graceful shutdown.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is present in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Internal package imports
from productivity_hub.config.settings import Settings, ConfigError, get_settings
from productivity_hub.utils.logger import setup_logging, get_logger
from productivity_hub.database.database import init_db, close_db
from productivity_hub.database.migrations import run_migrations
from productivity_hub.services.queue_service import init_queue_service, get_queue_service, TaskQueueService
from productivity_hub.services.cleanup_service import start_cleanup_service, get_cleanup_service, CleanupService
from productivity_hub.web.health import HealthCheckServer
from productivity_hub.handlers import register_handlers

# Telegram Bot Imports (v20+ async architecture)
from telegram.ext import Application, ApplicationBuilder
from telegram.request import HTTPXRequest

# Required startup directory list
REQUIRED_DIRECTORIES: List[Path] = [
    Path("logs"),
    Path("temp/uploads"),
    Path("temp/downloads"),
    Path("temp/converted"),
    Path("temp/thumbnails"),
    Path("temp/compressed"),
    Path("temp/qr"),
    Path("temp/background_removed"),
    Path("backups"),
]


# ====================================================================
# DIRECTORY CREATION (STEP 3)
# ====================================================================

def create_required_directories(settings: Settings, logger: logging.Logger) -> None:
    """
    Step 3: Create required runtime directories (logs, temp folders, backups, db folder).
    """
    logger.info("[Step 3/13] Verifying and creating required runtime directories...")
    db_dir = Path(settings.DATABASE_PATH).parent
    dirs_to_create = REQUIRED_DIRECTORIES + [db_dir]

    for directory in dirs_to_create:
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Directory ready: {directory.resolve()}")

    logger.info(f"Successfully created/verified {len(dirs_to_create)} runtime directories.")


# ====================================================================
# SAFE STARTUP SUMMARY DISPLAY
# ====================================================================

def print_startup_summary(settings: Settings) -> None:
    """
    Print a safe, clean startup summary to standard stdout.
    STRICTLY ensures credentials (BOT_TOKEN, SECRET_KEY) are masked.
    """
    safe_info = settings.get_safe_summary()
    summary = f"""
====================================================================
🚀 PRODUCTIVITY HUB BOT - PHASE 2 BACKEND READY
====================================================================
  • Operational Mode      : {safe_info['BOT_MODE'].upper()}
  • Health Server Port    : {safe_info['PORT']}
  • Database Location     : {safe_info['DATABASE_PATH']}
  • Log Level             : {safe_info['LOG_LEVEL']}
  • Bot Token             : {safe_info['BOT_TOKEN']}
  • Primary Owner ID      : {safe_info['OWNER_ID']}
  • Channel Check         : {safe_info['CHANNEL_USERNAME'] or 'Disabled'}
  • Max Concurrent Tasks  : {safe_info['MAX_CONCURRENT_TASKS']}
  • Max User Active Tasks : {safe_info['MAX_USER_ACTIVE_TASKS']}
  • Task Queue Capacity   : {safe_info['MAX_QUEUE_SIZE']}
  • Temp Retention        : {safe_info['TEMP_RETENTION_MINUTES']} minutes
  • Max File Size Limit   : {safe_info['MAX_FILE_SIZE_MB']} MB
  • Maintenance Mode      : {'ON' if safe_info['MAINTENANCE_MODE'] else 'OFF'}
====================================================================
[System Status]: Core Queue, Database, Cleanup, and Web Engine active.
====================================================================
"""
    try:
        print(summary, flush=True)
    except UnicodeEncodeError:
        print(summary.encode("ascii", errors="replace").decode("ascii"), flush=True)


# ====================================================================
# MAIN APPLICATION LIFECYCLE CLASS
# ====================================================================

class ProductivityHubBot:
    """
    Orchestrates the 13-step startup sequence, concurrent execution of services,
    and graceful teardown.
    """

    def __init__(self):
        self.settings: Optional[Settings] = None
        self.logger: Optional[logging.Logger] = None
        self.health_server: Optional[HealthCheckServer] = None
        self.queue_service: Optional[TaskQueueService] = None
        self.cleanup_service: Optional[CleanupService] = None
        self.telegram_app: Optional[Application] = None
        self.stop_event: asyncio.Event = asyncio.Event()

    async def run_lifecycle(self) -> None:
        """Executes the complete 13-step startup sequence."""
        print("Starting Productivity Hub Bot Phase 2 initialization...", flush=True)

        # Step 1: Load Env Vars
        print("[Step 1/13] Loading environment variables...", flush=True)

        # Step 2: Validate Config
        print("[Step 2/13] Validating configuration...", flush=True)
        try:
            self.settings = get_settings()
        except ConfigError as ce:
            print(f"\n❌ CONFIGURATION ERROR:\n{ce}\n", file=sys.stderr, flush=True)
            sys.exit(1)

        # Step 6 (Early): Setup Logging
        self.logger = setup_logging(self.settings.LOG_LEVEL)
        self.logger.info("[Step 1/13] Environment variables loaded successfully.")
        self.logger.info("[Step 2/13] Configuration loaded and validated successfully.")

        # Step 3: Create Required Directories
        create_required_directories(self.settings, self.logger)

        # Step 4: Initialize Async Database
        self.logger.info("[Step 4/13] Initializing SQLite database connection...")
        await init_db(self.settings.DATABASE_PATH)
        self.logger.info("Database connection established & baseline schema verified.")

        # Step 5: Run Database Migrations
        self.logger.info("[Step 5/13] Running pending database migrations...")
        await run_migrations(self.settings.DATABASE_PATH)

        # Step 6: Logging system confirmation
        self.logger.info("[Step 6/13] Logging infrastructure fully active.")

        # Step 8: Initialize Task Queue Service
        self.logger.info("[Step 8/13] Initializing Task Queue Service...")
        self.queue_service = await init_queue_service(self.settings)

        # Step 7: Recover Stale Tasks
        self.logger.info("[Step 7/13] Executing stale task recovery...")
        await self.queue_service.recover_stale_tasks()

        # Step 9: Start Temporary Storage Cleanup Service
        self.logger.info("[Step 9/13] Launching background Temporary Storage Cleanup Service...")
        self.cleanup_service = await start_cleanup_service(
            retention_minutes=self.settings.TEMP_RETENTION_MINUTES,
            check_interval_seconds=300
        )
        await self.cleanup_service.run_startup_cleanup()

        # Step 10: Start Health Server
        self.logger.info(f"[Step 10/13] Launching HTTP Health Check Server on port {self.settings.PORT}...")
        self.health_server = HealthCheckServer(port=self.settings.PORT)
        await self.health_server.start()

        # Step 11: Start Telegram Bot Application
        self.logger.info("[Step 11/13] Building Telegram Bot Application...")
        req_kwargs = {
            "connection_pool_size": 20,
            "connect_timeout": 30.0,
            "read_timeout": 60.0,
            "write_timeout": 120.0,
            "pool_timeout": 30.0,
        }
        proxy_url = getattr(self.settings, "PROXY_URL", None) or os.getenv("PROXY_URL")
        if proxy_url:
            req_kwargs["proxy_url"] = proxy_url
            self.logger.info(f"Configuring Telegram proxy: {proxy_url}")

        req = HTTPXRequest(**req_kwargs)
        self.telegram_app = ApplicationBuilder().token(self.settings.BOT_TOKEN).request(req).build()
        await self.telegram_app.initialize()
        await self.telegram_app.start()

        # Step 12: Register Handlers
        self.logger.info("[Step 12/13] Registering handlers and callbacks...")
        register_handlers(self.telegram_app)

        # Step 13: Start Polling / Webhook Mode & Display Summary
        self.logger.info("[Step 13/13] Starting Telegram bot polling engine...")
        if self.telegram_app.updater:
            await self.telegram_app.updater.start_polling(bootstrap_retries=-1)

        # Print clean, safe summary to console
        print_startup_summary(self.settings)

        # Register Signal Handlers for Graceful Shutdown
        self._register_signal_handlers()

        # Block until shutdown signal is received
        self.logger.info("Bot is active and running. Awaiting shutdown signals (SIGTERM/SIGINT)...")
        await self.stop_event.wait()

        # Perform Graceful Shutdown
        await self._shutdown()

    def _register_signal_handlers(self) -> None:
        """Register OS signals (SIGTERM, SIGINT) for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def _signal_trigger():
            if not self.stop_event.is_set():
                self.logger.warning("Shutdown signal received from OS. Initiating graceful teardown...")
                self.stop_event.set()

        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, _signal_trigger)
                except NotImplementedError:
                    signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(_signal_trigger))
        else:
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(_signal_trigger))

    async def _shutdown(self) -> None:
        """
        Execute graceful shutdown sequence:
        1. Stop Queue Service from accepting new tasks
        2. Stop Cleanup Service background task
        3. Stop Telegram app & updater
        4. Stop Health Web Server
        5. Close database connection cleanly
        """
        self.logger.info("==================================================")
        self.logger.info("🛑 INITIATING GRACEFUL SHUTDOWN SEQUENCE")
        self.logger.info("==================================================")

        # 1. Stop Queue Service
        if self.queue_service:
            try:
                self.logger.info("Stopping Task Queue Service...")
                await self.queue_service.stop()
            except Exception as e:
                self.logger.error(f"Error stopping Task Queue Service: {e}")

        # 2. Stop Cleanup Service
        if self.cleanup_service:
            try:
                self.logger.info("Stopping Cleanup Service...")
                await self.cleanup_service.stop()
            except Exception as e:
                self.logger.error(f"Error stopping Cleanup Service: {e}")

        # 3. Stop Telegram Application
        if self.telegram_app:
            try:
                self.logger.info("Stopping Telegram application and polling...")
                if self.telegram_app.updater and self.telegram_app.updater.running:
                    await self.telegram_app.updater.stop()
                await self.telegram_app.stop()
                await self.telegram_app.shutdown()
                self.logger.info("Telegram application shut down cleanly.")
            except Exception as e:
                self.logger.error(f"Error shutting down Telegram app: {e}")

        # 4. Stop Health Web Server
        if self.health_server:
            try:
                self.logger.info("Stopping Health Check HTTP server...")
                await self.health_server.stop()
            except Exception as e:
                self.logger.error(f"Error stopping health server: {e}")

        # 5. Close Database Connection
        try:
            self.logger.info("Closing database connections...")
            await close_db()
        except Exception as e:
            self.logger.error(f"Error closing database: {e}")

        self.logger.info("==================================================")
        self.logger.info("✅ SHUTDOWN COMPLETE. Goodbye!")
        self.logger.info("==================================================")


def main() -> None:
    """Main script entrypoint."""
    bot = ProductivityHubBot()
    try:
        asyncio.run(bot.run_lifecycle())
    except (KeyboardInterrupt, SystemExit):
        print("\nProcess terminated by user or OS.", flush=True)
    except Exception as e:
        print(f"\nCRITICAL UNHANDLED FATAL ERROR: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
