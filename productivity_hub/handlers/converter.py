"""
Document & File Conversion Handler.

Intercepts uploaded documents & photos, inspects magic-byte signatures using FileDetector,
queries ConversionRegistry for functional target formats, presents conversion choice keyboards,
submits tasks to TaskQueueService, and delivers converted output files to users.
"""

import logging
from pathlib import Path
from typing import Dict, Any
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import parse_callback_data, get_back_keyboard
from productivity_hub.services.conversion_service import get_conversion_service, ConversionError
from productivity_hub.services.queue_service import get_queue_service, QueueOverflowError, UserTaskLimitError
from productivity_hub.utils.file_detector import detect_file_type
from productivity_hub.utils.conversion_registry import get_conversion_registry
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.database.database import get_db
from productivity_hub.database.models import Conversion
from productivity_hub.services.cleanup_service import safe_delete_file, safe_delete_files
from productivity_hub.utils.validators import get_oversized_file_message, get_oversized_suggestion_keyboard
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.converter")

UPLOAD_DIR = Path("temp/uploads")
# Context storage for uploaded files: user_id -> local_uploaded_filepath
UPLOADED_FILES: Dict[int, Path] = {}


@protected_handler(operation_type="default")
async def convert_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /convert command."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id
    context.user_data["active_mode"] = "converter"

    title = get_text("title_converter", lang)
    desc = get_text("desc_converter", lang)
    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            f"{title}\n\n{desc}\n\n📁 *Please upload the document or file you wish to convert now:*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


@protected_handler(operation_type="conversion")
async def document_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming uploaded documents and photos.
    """
    message = update.effective_message
    if not message:
        return

    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Identify file source (Document or Photo)
    tg_file_obj = None
    original_filename = "upload_file"

    if message.document:
        tg_file_obj = message.document
        original_filename = message.document.file_name or "document"
    elif message.photo:
        tg_file_obj = message.photo[-1]  # Highest resolution photo
        original_filename = "photo.jpg"
    else:
        return

    # Check known file size against limits before downloading (Requirement 2)
    settings = get_settings()
    max_in_bytes = min(settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, settings.MAX_FILE_SIZE_BYTES)
    if getattr(tg_file_obj, "file_size", None) and tg_file_obj.file_size > max_in_bytes:
        oversized_msg = get_oversized_file_message(limit_bytes=max_in_bytes, actual_size_bytes=tg_file_obj.file_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=original_filename, lang=lang)
        await message.reply_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path, display_name = generate_safe_filepath(UPLOAD_DIR, original_filename, prefix="up")

    # Clean up any previously pending upload by the user
    old_file = UPLOADED_FILES.get(user_id)
    if old_file and old_file != target_path:
        safe_delete_file(old_file, log_msg="replaced by newer upload")

    status_msg = await message.reply_text("📥 *Receiving and analyzing uploaded file...*", parse_mode="Markdown")

    try:
        # Download file from Telegram servers
        file_handle = await context.bot.get_file(tg_file_obj.file_id)
        await file_handle.download_to_drive(custom_path=target_path)
    except Exception as e:
        safe_delete_file(target_path, log_msg="telegram download failed")
        logger.error(f"Failed to download file from Telegram: {e}", exc_info=True)
        await status_msg.edit_text("❌ *Failed to download uploaded file from Telegram servers.*", parse_mode="Markdown")
        return

    # Post-download size validation if size was unknown before download
    actual_in_size = target_path.stat().st_size
    if actual_in_size > settings.MAX_FILE_SIZE_BYTES:
        safe_delete_file(target_path, log_msg="uploaded file exceeds maximum size")
        oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_in_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=original_filename, lang=lang)
        await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    # Smart Magic-Byte Signature Detection
    file_info = detect_file_type(target_path)
    detected_ext = file_info.extension.lower()

    # Store uploaded path in session
    UPLOADED_FILES[user_id] = target_path

    # Query Available Conversion Targets
    registry = get_conversion_registry()
    conv_service = get_conversion_service()
    available_rules = registry.get_available_conversions(detected_ext)

    # Filter rules through circuit breaker status
    active_rules = [
        rule for rule in available_rules
        if conv_service.is_conversion_available(rule.source_format, rule.target_format)
    ]

    if not active_rules:
        # Clean up unsupported uploaded file immediately
        safe_delete_file(target_path, log_msg="no available conversions")
        UPLOADED_FILES.pop(user_id, None)
        await status_msg.edit_text(
            f"📄 *File Received:* `{display_name}`\n"
            f"🔍 *Detected Type:* `{detected_ext.upper()}` ({file_info.mime_type})\n\n"
            f"⚠️ *No supported conversions available for this file type.*",
            parse_mode="Markdown"
        )
        return

    from productivity_hub.handlers.keyboards import build_paginated_keyboard
    format_items = [(f"🔄 {rule.description}", rule.target_format) for rule in active_rules]
    keyboard = build_paginated_keyboard(
        items=format_items,
        page=0,
        page_size=6,
        callback_prefix="convfmt",
        owner_id=user_id,
        lang=lang,
        row_width=2
    )

    size_mb = target_path.stat().st_size / (1024 * 1024)
    summary_text = (
        f"📄 *File:* `{display_name}`\n"
        f"📏 *Size:* `{size_mb:.2f} MB` | 🔍 *Detected Format:* `{detected_ext.upper()}`\n\n"
        f"👇 *Select your desired target conversion format:*"
    )

    await status_msg.edit_text(text=summary_text, parse_mode="Markdown", reply_markup=keyboard)


async def handle_conversion_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle conversion target format selection callback queries (e.g. convfmt:pdf:user_id).
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, target_ext, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    source_path = UPLOADED_FILES.pop(user_id, None)
    if not source_path or not source_path.exists():
        await query.answer("❌ File session expired. Please upload your file again.", show_alert=True)
        return

    await query.answer()
    queue_svc = get_queue_service()
    conv_svc = get_conversion_service()

    status_msg = await query.message.reply_text("⏳ *Enqueuing file conversion task...*", parse_mode="Markdown")

    current_task_holder: Dict[str, Any] = {}
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    async def _execute_conversion_job():
        task_id = current_task_holder.get("task_id")
        result_path = None
        try:
            # Execute conversion
            res = await conv_svc.convert_file(
                source_path=source_path,
                target_format=target_ext,
                user_id=user_id
            )

            result_path = res["result_file"]
            if task_id:
                queue_svc.register_task_files(task_id, result_path)

            # Check pre-upload limit (Requirement 4 & 5)
            settings = get_settings()
            actual_size = result_path.stat().st_size
            if actual_size > settings.TELEGRAM_UPLOAD_LIMIT_BYTES:
                oversized_msg = get_oversized_file_message(
                    limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                    actual_size_bytes=actual_size
                )
                kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=result_path.name, lang=lang)
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                return None

            await status_msg.edit_text("📤 *Uploading converted file to Telegram...*", parse_mode="Markdown")

            # Deliver converted file to user (Telegram upload must complete before local files are deleted)
            try:
                with open(result_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        filename=result_path.name,
                        caption=f"✅ *Conversion Complete!* ({res['source_format'].upper()} ➔ {res['target_format'].upper()})\nConverted via Productivity Hub",
                        parse_mode="Markdown"
                    )
                await status_msg.delete()
            except telegram.error.TelegramError as te:
                err_str = str(te).lower()
                if "too big" in err_str or "entity too large" in err_str:
                    oversized_msg = get_oversized_file_message(
                        limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                        actual_size_bytes=actual_size
                    )
                    kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=result_path.name, lang=lang)
                    await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                else:
                    logger.error(f"Telegram document delivery failed: {te}")
                    await status_msg.edit_text("❌ *Upload failed: Telegram could not receive the file. Please try again later.*", parse_mode="Markdown")
                return None

            # Audit Record
            db = get_db()
            await db.record_conversion(Conversion(
                task_id=task_id or "conv_task",
                user_id=user_id,
                source_format=res["source_format"],
                target_format=res["target_format"],
                source_file=source_path.name,
                result_file=result_path.name,
                file_size=res["file_size"],
                status="completed"
            ))

            return res
        finally:
            # Automatic temporary file cleanup after delivery or error
            safe_delete_files([source_path, result_path], exclude_task_id=task_id, log_msg="after conversion delivery")

    try:
        q_task = await queue_svc.submit_task(
            user_id=user_id,
            task_type="conversion",
            coro_fn=_execute_conversion_job,
            associated_files=[source_path]
        )
        current_task_holder["task_id"] = q_task.task_id

        pos = queue_svc.get_queue_position(q_task.task_id)
        pos_str = f"Position in queue: #{pos}" if pos else "Processing now"
        await status_msg.edit_text(f"✅ *Task Enqueued!* ({pos_str})\nYour conversion will begin shortly.", parse_mode="Markdown")

    except (QueueOverflowError, UserTaskLimitError) as qe:
        safe_delete_file(source_path, log_msg="queue limit reached")
        await status_msg.edit_text(f"⚠️ *Queue Error:* {qe}", parse_mode="Markdown")
    except Exception as e:
        safe_delete_file(source_path, log_msg="conversion submission error")
        logger.error(f"Failed to submit conversion task: {e}", exc_info=True)
        await status_msg.edit_text("❌ *Failed to submit conversion task.*", parse_mode="Markdown")

