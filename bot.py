import asyncio
import re
import time
import sys
import subprocess
import signal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext,
)

from config.settings import (
    BOT_TOKEN, BOT_MODE, PORT, WEBHOOK_URL, OWNER_ID, SECRET_KEY,
    DATABASE_DIR, LOGS_DIR, TEMP_DIR,
    PROXY_URL, CONNECT_RETRY_ATTEMPTS, CONNECT_RETRY_DELAY
)
from services.database_service import init_db, log_event, SystemStateService, get_db
from services.security_service import check_user_access
from services.startup_service import validate_startup
from utils.logger import logger, error_logger
from utils.helpers import cleanup_temp_directories

# Handlers
from handlers.start import start_command
from handlers.help import help_command
from handlers.download import handle_download_url, handle_downloader_callback
from handlers.converter import handle_document_upload, handle_converter_callback
from handlers.image_tools import handle_photo_upload, handle_image_callback, handle_image_resize_text
from handlers.qr_tools import show_qr_tools_menu, handle_qr_callback, handle_qr_input_processing, handle_qr_scan_callback
from handlers.compressor import handle_compressor_callback, handle_custom_comp_pct, handle_pdf_compress_callback
from handlers.text_tools import show_text_tools_prompt, handle_text_input, handle_text_callback
from handlers.stats import handle_stats_command
from handlers.admin import show_admin_console, handle_admin_callback, handle_admin_text_input

START_TIME = time.time()

# ─── Exit codes used to communicate between runner and worker ─────────────────
EXIT_OK          = 0   # clean stop by user
EXIT_NET_ERROR   = 2   # network/timeout - runner should retry


def get_uptime() -> str:
    """Return human readable uptime string."""
    diff = time.time() - START_TIME
    d = int(diff // 86400)
    h = int((diff % 86400) // 3600)
    m = int((diff % 3600) // 60)
    s = int(diff % 60)
    return f"{d}d {h}h {m}m {s}s"


def build_application():
    """Build a fresh telegram Application, applying proxy and custom timeouts."""
    from telegram.request import HTTPXRequest
    
    # Configure custom timeouts globally for standard and media requests
    request_kwargs = {
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "media_write_timeout": 300.0,
    }
    
    if PROXY_URL:
        request_kwargs["proxy"] = PROXY_URL
        logger.info(f"Using proxy: {PROXY_URL}")
        
    request = HTTPXRequest(**request_kwargs)
    builder = ApplicationBuilder().token(BOT_TOKEN).request(request)
    return builder.build()


# ─── Module-level application (used by webhook server) ───────────────────────
application = build_application()


# ─── Utility command routers ──────────────────────────────────────────────────
async def stats_command_router(update: Update, context: CallbackContext):
    if not await check_user_access(update, context):
        return
    await handle_stats_command(update, context)


async def history_command_router(update: Update, context: CallbackContext):
    if not await check_user_access(update, context):
        return
    from handlers.stats import handle_history_command
    await handle_history_command(update, context)


async def lang_command_router(update: Update, context: CallbackContext):
    if not await check_user_access(update, context):
        return
    await update.message.reply_text(
        "Language Settings\n\nOnly English (US) is currently supported. More languages coming soon!"
    )


# ─── Cancel command ───────────────────────────────────────────────────────────
async def cancel_command(update: Update, context: CallbackContext):
    """Cancel any running or queued tasks for the user."""
    if not await check_user_access(update, context):
        return
    user_id = update.effective_user.id

    from services.queue_service import cancel_user_task
    cancelled = cancel_user_task(user_id)

    if cancelled:
        await update.message.reply_text(
            "Task Cancelled\n\nYour active or queued task has been cancelled and removed."
        )
        log_event("SYSTEM", f"User {user_id} cancelled their running/queued task.")
    else:
        await update.message.reply_text("You have no active or queued tasks to cancel.")


# ─── Global callback router ───────────────────────────────────────────────────
async def global_callback_router(update: Update, context: CallbackContext):
    if not await check_user_access(update, context):
        return

    query = update.callback_query
    data = query.data

    if data == "menu_main":
        keyboard = [
            [
                InlineKeyboardButton("Downloader", callback_data="menu_dl"),
                InlineKeyboardButton("Converter", callback_data="menu_conv")
            ],
            [
                InlineKeyboardButton("Image Tools", callback_data="menu_img"),
                InlineKeyboardButton("QR Tools", callback_data="menu_qr")
            ],
            [
                InlineKeyboardButton("Compressor", callback_data="menu_comp"),
                InlineKeyboardButton("Text Tools", callback_data="menu_text")
            ]
        ]
        await query.message.edit_text(
            "**Main Menu**\nSelect a category tool to begin:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    elif data == "menu_dl":
        await query.message.reply_text(
            "Send the media URL you want to download from YouTube, TikTok, Instagram, Twitter, Facebook, etc."
        )
    elif data == "menu_conv":
        await query.message.reply_text(
            "Please upload the document, video, or audio file you want to convert."
        )
    elif data == "menu_img":
        await query.message.reply_text("Please upload the image you want to manipulate.")
    elif data == "menu_qr":
        await show_qr_tools_menu(update, context)
    elif data == "menu_comp":
        await query.message.reply_text("Please upload the Image or PDF file you want to compress.")
    elif data == "menu_text":
        await show_text_tools_prompt(update, context)

    elif data.startswith("dl_"):
        await handle_downloader_callback(update, context)
    elif data.startswith("conv_"):
        await handle_converter_callback(update, context)
    elif data.startswith("pdf_"):
        if data == "pdf_menu_conv":
            await handle_converter_callback(update, context)
        elif data == "pdf_menu_comp":
            await handle_pdf_compress_callback(update, context)
    elif data.startswith("qr_"):
        if data == "qr_scan_decode":
            await handle_qr_scan_callback(update, context)
        else:
            await handle_qr_callback(update, context)
    elif data.startswith("img_"):
        await handle_image_callback(update, context)
    elif data.startswith("comp_"):
        await handle_compressor_callback(update, context)
    elif data.startswith("adm_"):
        await handle_admin_callback(update, context)


# ─── Global text message router ───────────────────────────────────────────────
async def global_message_router(update: Update, context: CallbackContext):
    if not await check_user_access(update, context):
        return

    text = update.message.text

    if context.user_data.get("qr_state"):
        await handle_qr_input_processing(update, context)
        return
    elif context.user_data.get("img_state"):
        await handle_image_resize_text(update, context)
        return
    elif context.user_data.get("comp_state"):
        await handle_custom_comp_pct(update, context)
        return
    elif context.user_data.get("text_state"):
        await handle_text_input(update, context)
        return
    elif context.user_data.get("admin_state"):
        await handle_admin_text_input(update, context)
        return

    urls = re.findall(r'(https?://[^\s]+)', text)
    if urls:
        await handle_download_url(update, context, urls[0])
        return

    await handle_text_input(update, context)


# ─── Handler registration ─────────────────────────────────────────────────────
def register_bot_handlers(app):
    """Register all handlers on the given Application instance."""
    app.add_handler(CommandHandler("start",   start_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("stats",   stats_command_router))
    app.add_handler(CommandHandler("history", history_command_router))
    app.add_handler(CommandHandler("lang",    lang_command_router))
    app.add_handler(CommandHandler("cancel",  cancel_command))
    app.add_handler(CommandHandler("admin",   show_admin_console))
    app.add_handler(CallbackQueryHandler(global_callback_router))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.AUDIO | filters.VIDEO,
        handle_document_upload
    ))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_message_router))


# ─── Background schedulers ────────────────────────────────────────────────────
async def file_cleanup_scheduler():
    logger.info("Background file cleanup scheduler started.")
    while True:
        try:
            deleted = cleanup_temp_directories()
            if deleted > 0:
                logger.info(f"Scheduler swept and deleted {deleted} expired files.")
        except Exception as e:
            logger.error(f"Error in file cleanup sweep: {e}")
        await asyncio.sleep(15 * 60)


async def backup_and_logs_scheduler():
    from services.backup_service import run_backup
    logger.info("Background backup scheduler started.")
    while True:
        try:
            run_backup()
        except Exception as e:
            logger.error(f"Error in backup daemon: {e}")
        try:
            now = time.time()
            limit = 30 * 24 * 3600
            for f in LOGS_DIR.glob("*"):
                if f.is_file() and f.suffix != ".log":
                    if now - f.stat().st_mtime > limit:
                        f.unlink()
                        logger.info(f"Deleted old rotated log: {f.name}")
        except Exception as e:
            logger.error(f"Error in logs cleanup daemon: {e}")
        await asyncio.sleep(24 * 3600)


async def _set_commands_safe(app):
    """Set BotFather command list - non-fatal if network unavailable."""
    try:
        await app.bot.set_my_commands([
            ("start",   "Start the bot"),
            ("help",    "Show help menu"),
            ("stats",   "View statistics"),
            ("history", "View history"),
            ("lang",    "Change language"),
            ("cancel",  "Cancel active task"),
        ])
        logger.info("BotFather command list configured.")
    except Exception as e:
        logger.warning(f"Could not set bot commands (non-fatal): {e}")


# ─── FastAPI / Webhook integration ────────────────────────────────────────────
app = FastAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup()
    init_db()
    SystemStateService.increment_restart_count()
    register_bot_handlers(application)
    await application.initialize()
    await application.start()
    await _set_commands_safe(application)

    cleanup_task = asyncio.create_task(file_cleanup_scheduler())
    backup_task  = asyncio.create_task(backup_and_logs_scheduler())

    yield

    cleanup_task.cancel()
    backup_task.cancel()
    try:
        await asyncio.gather(cleanup_task, backup_task, return_exceptions=True)
    except Exception:
        pass
    await application.stop()
    await application.shutdown()


app.router.lifespan_context = lifespan


@app.post("/webhook")
async def telegram_webhook(request: Request):
    if BOT_MODE != "webhook":
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Not in webhook mode.")
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.get("/health")
@app.get("/")
async def health_check():
    return {"status": "healthy", "uptime": get_uptime()}


# ─────────────────────────────────────────────────────────────────────────────
#  WORKER MODE  (run_polling inside a fresh process each attempt)
#  Invoked via:  python bot.py --worker
# ─────────────────────────────────────────────────────────────────────────────
def run_worker():
    """
    Runs the actual run_polling call.
    Exits with EXIT_NET_ERROR on timeout/network issues so the
    runner process knows to retry.
    Exits with EXIT_OK on clean keyboard interrupt.
    """
    try:
        app_instance = build_application()
        register_bot_handlers(app_instance)
        app_instance.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        sys.exit(EXIT_OK)

    except (TimedOut, NetworkError) as e:
        print(f"[WORKER] Network error: {e}", flush=True, file=sys.stderr)
        sys.exit(EXIT_NET_ERROR)

    except KeyboardInterrupt:
        print("[WORKER] Stopped by user.", flush=True)
        sys.exit(EXIT_OK)

    except Exception as e:
        print(f"[WORKER] Unexpected error: {e}", flush=True, file=sys.stderr)
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
#  RUNNER MODE  (supervisor: spawns --worker subprocess and retries)
# ─────────────────────────────────────────────────────────────────────────────
def run_polling_with_retry():
    """
    Supervisor that spawns bot.py --worker in a subprocess.
    On EXIT_NET_ERROR it waits and retries.
    On EXIT_OK (user pressed Ctrl+C) it stops.
    This avoids the 'Event loop is closed' problem that occurs when
    run_polling() is called more than once in the same process.
    """
    python = sys.executable
    script  = __file__

    attempt = 0
    while True:
        attempt += 1
        print(
            f"[INFO] Connecting to Telegram... (attempt #{attempt})",
            flush=True
        )
        logger.info(f"Connecting to Telegram... (attempt #{attempt})")

        try:
            proc = subprocess.run(
                [python, script, "--worker"],
                # inherit stdin/stdout/stderr so the user sees bot logs directly
            )
        except KeyboardInterrupt:
            print("\n[INFO] Bot stopped by user.", flush=True)
            logger.info("Runner stopped by user (Ctrl+C).")
            break

        code = proc.returncode

        if code == EXIT_OK:
            logger.info("Bot stopped cleanly.")
            break

        if code == EXIT_NET_ERROR:
            msg = (
                f"[WARN] Cannot reach Telegram (attempt #{attempt}). "
                f"Retrying in {CONNECT_RETRY_DELAY}s..."
            )
            print(msg, flush=True)
            logger.warning(msg)
            if not PROXY_URL:
                print(
                    "[TIP] If Telegram is blocked in your region, "
                    "set PROXY_URL=socks5://host:port in your .env file.",
                    flush=True
                )
            if CONNECT_RETRY_ATTEMPTS and attempt >= CONNECT_RETRY_ATTEMPTS:
                logger.critical(
                    f"Max retry attempts ({CONNECT_RETRY_ATTEMPTS}) reached. Giving up."
                )
                sys.exit(1)
            time.sleep(CONNECT_RETRY_DELAY)

        else:
            # Non-network crash in worker
            logger.critical(f"Worker crashed with exit code {code}. Not retrying.")
            sys.exit(code)


# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    validate_startup()
    init_db()
    SystemStateService.increment_restart_count()

    if BOT_MODE == "webhook":
        logger.info(f"Starting webhook server on port {PORT}")
        uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
    else:
        logger.info("Starting polling runner...")
        run_polling_with_retry()


if __name__ == "__main__":
    # --worker flag: this is a subprocess spawned by the runner
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        run_worker()
    else:
        try:
            main()
        except KeyboardInterrupt:
            logger.info("Shutdown requested. Goodbye.")
        except Exception as e:
            try:
                SystemStateService.increment_crash_count()
            except Exception:
                pass
            error_logger.critical(f"System crash: {e}", exc_info=True)
            sys.exit(1)
