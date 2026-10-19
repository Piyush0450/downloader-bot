"""
QR Code Scanner Handler.

Prompts user for QR image uploads, decodes single/multi-payloads via QRScanningService,
identifies structured contents (URLs, Wi-Fi, Contacts, Events, SMS, Payments),
and displays copyable representations with explicit, safe link buttons.
"""

import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import get_back_keyboard
from productivity_hub.services.qr_scanning_service import get_qr_scanning_service, DecodedQRPayload
from productivity_hub.services.cleanup_service import safe_delete_file
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.validators import get_oversized_file_message
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.qr_scanner")

UPLOAD_DIR = Path("temp/uploads")


@protected_handler(operation_type="default")
async def qr_scanner_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show QR scanner instructions prompt."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    title = get_text("title_qr_scanner", lang)
    desc = get_text("desc_qr_scanner", lang)
    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    prompt = (
        f"{title}\n\n{desc}\n\n"
        f"📷 *Please upload or forward an image containing a QR code now:*"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text=prompt, parse_mode="Markdown", reply_markup=keyboard)
    elif update.effective_message:
        await update.effective_message.reply_text(text=prompt, parse_mode="Markdown", reply_markup=keyboard)


@protected_handler(operation_type="qr")
async def process_qr_scan_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Process image uploaded for QR code decoding.
    Returns True if handled, False otherwise.
    """
    message = update.effective_message
    if not message:
        return False

    photo_obj = None
    if message.photo:
        photo_obj = message.photo[-1]
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        photo_obj = message.document
    else:
        return False

    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Pre-download file size check (Requirement 2)
    settings = get_settings()
    max_in_bytes = min(settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, settings.MAX_FILE_SIZE_BYTES)
    if getattr(photo_obj, "file_size", None) and photo_obj.file_size > max_in_bytes:
        oversized_msg = get_oversized_file_message(limit_bytes=max_in_bytes, actual_size_bytes=photo_obj.file_size)
        await message.reply_text(oversized_msg, parse_mode="Markdown")
        return True

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path, _ = generate_safe_filepath(UPLOAD_DIR, "qr_scan.png", prefix="scan")

    status_msg = await message.reply_text("🔍 *Scanning image for QR codes...*", parse_mode="Markdown")

    try:
        try:
            tg_file = await context.bot.get_file(photo_obj.file_id)
            await tg_file.download_to_drive(custom_path=target_path)
        except Exception as e:
            logger.error(f"Failed to download QR image: {e}")
            await status_msg.edit_text("❌ *Failed to download image from Telegram.*", parse_mode="Markdown")
            return True

        if target_path.stat().st_size > settings.MAX_FILE_SIZE_BYTES:
            actual_size = target_path.stat().st_size
            oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_size)
            await status_msg.edit_text(oversized_msg, parse_mode="Markdown")
            return True

        scanner_svc = get_qr_scanning_service()
        try:
            results = await scanner_svc.scan_image(target_path, user_id=user_id)
        except Exception as e:
            logger.error(f"Error scanning QR image: {e}")
            await status_msg.edit_text("❌ *An error occurred while scanning the image.*", parse_mode="Markdown")
            return True

        if not results:
            await status_msg.edit_text(
                "⚠️ *No readable QR code found in this image.*\n\n"
                "Please ensure the QR code is clearly visible, in focus, and has good lighting.",
                parse_mode="Markdown",
                reply_markup=get_back_keyboard(owner_id=user_id, lang=lang)
            )
            return True

        # Build report for each detected QR code
        for idx, qr in enumerate(results, 1):
            header = f"🔍 *QR Code Result #{idx}* — {qr.type_display}\n\n"

            # Structured details
            detail_lines = []
            for k, v in qr.details.items():
                detail_lines.append(f"• *{k}*: `{v}`")
            detail_text = "\n".join(detail_lines) if detail_lines else ""

            raw_block = f"\n\n📋 *Raw Content:*\n```text\n{qr.raw_text}\n```"

            full_text = f"{header}{detail_text}{raw_block}"

            # Action buttons
            buttons = []
            if qr.is_safe_url and qr.safe_url:
                buttons.append([InlineKeyboardButton("🔗 Open Link", url=qr.safe_url)])

            buttons.append([InlineKeyboardButton("⬅️ Back to QR Tools", callback_data=f"menu:qr:{user_id}")])
            keyboard = InlineKeyboardMarkup(buttons)

            await message.reply_text(
                text=full_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )

        await status_msg.delete()
        return True
    finally:
        safe_delete_file(target_path, log_msg="after QR scanning")



def register_qr_scanner_handlers(application) -> None:
    """Register QR scanner commands."""
    application.add_handler(CommandHandler("scan", qr_scanner_menu_handler))
    application.add_handler(CommandHandler("qrscan", qr_scanner_menu_handler))
