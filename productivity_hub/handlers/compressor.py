"""
Universal File Compressor Handler.

Handles /compress command, presents adaptive compression level selection (Low, Medium, High),
submits tasks to TaskQueueService, and returns compressed files with precise reduction metrics.
"""

import logging
from pathlib import Path
from typing import Dict
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import parse_callback_data, get_back_keyboard
from productivity_hub.services.compression_service import get_compression_service, CompressionError
from productivity_hub.services.queue_service import get_queue_service, QueueOverflowError, UserTaskLimitError
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.file_detector import detect_file_type
from productivity_hub.services.cleanup_service import safe_delete_file, safe_delete_files
from productivity_hub.utils.validators import get_oversized_file_message
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.compressor")

UPLOAD_DIR = Path("temp/uploads")
COMPRESSOR_PENDING_FILES: Dict[int, Path] = {}


@protected_handler(operation_type="default")
async def compressor_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /compress command or menu prompt."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    title = get_text("title_compressor", lang)
    desc = get_text("desc_compressor", lang)
    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            f"{title}\n\n{desc}\n\n📦 *Please upload your file (document, image, video, audio, or PDF) now:*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


async def show_compression_level_options(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_path: Path,
    original_name: str
) -> None:
    """
    Present the 3 compression levels (Low, Medium, High) for an uploaded file.
    """
    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Clean up previous pending compression file if any
    old_path = COMPRESSOR_PENDING_FILES.get(user_id)
    if old_path and old_path != file_path:
        safe_delete_file(old_path, log_msg="replaced by newer compression file")

    # Check file size against max supported limits
    settings = get_settings()
    actual_size = file_path.stat().st_size
    if actual_size > settings.MAX_FILE_SIZE_BYTES:
        safe_delete_file(file_path, log_msg="uploaded file exceeds maximum size")
        oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_size)
        await update.effective_message.reply_text(oversized_msg, parse_mode="Markdown")
        return

    COMPRESSOR_PENDING_FILES[user_id] = file_path
    file_info = detect_file_type(file_path)
    size_mb = file_path.stat().st_size / (1024 * 1024)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Low (Best Quality)", callback_data=f"cmp_lvl:low:{user_id}"),
            InlineKeyboardButton("🟡 Medium (Balanced)", callback_data=f"cmp_lvl:medium:{user_id}")
        ],
        [
            InlineKeyboardButton("🔴 High (Maximum Savings)", callback_data=f"cmp_lvl:high:{user_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{user_id}")
        ]
    ])

    await update.effective_message.reply_text(
        f"📦 *File Received:* `{original_name}`\n"
        f"📏 *Current Size:* `{size_mb:.2f} MB` | 🔍 *Type:* `{file_info.extension.upper()}`\n\n"
        f"👇 *Select compression level:*",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def handle_compression_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle compression level selection (cmp_lvl:medium:user_id).
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, level, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    source_path = COMPRESSOR_PENDING_FILES.pop(user_id, None)
    if not source_path or not source_path.exists():
        await query.answer("❌ File session expired. Please upload your file again.", show_alert=True)
        return

    await query.answer()
    queue_svc = get_queue_service()
    comp_svc = get_compression_service()

    status_msg = await query.message.reply_text("⏳ *Enqueuing file compression task...*", parse_mode="Markdown")

    current_task_holder = {}

    async def _execute_compression_job():
        task_id = current_task_holder.get("task_id")
        out_path = None
        settings = get_settings()
        try:
            await status_msg.edit_text(f"📦 *Compressing file ({level.capitalize()} level)...*", parse_mode="Markdown")
            res = await comp_svc.compress_file(source_path, level=level, user_id=user_id)
            out_path = res.output_path

            if task_id:
                queue_svc.register_task_files(task_id, out_path)

            orig_kb = res.original_size / 1024
            comp_kb = res.compressed_size / 1024

            if res.is_reduced:
                caption = (
                    f"✅ *Compression Complete!*\n\n"
                    f"• Original Size: `{orig_kb:.1f} KB`\n"
                    f"• Compressed Size: `{comp_kb:.1f} KB`\n"
                    f"• Savings: *{res.percent_saved:.1f}%* ({res.bytes_saved / 1024:.1f} KB saved)\n"
                    f"• Level: `{level.upper()}`\n\n"
                    f"Compressed via Productivity Hub"
                )
            else:
                caption = (
                    f"ℹ️ *File Optimization Complete*\n\n"
                    f"• Size: `{comp_kb:.1f} KB`\n"
                    f"• Note: File was already optimally compressed. No quality was degraded.\n\n"
                    f"Delivered via Productivity Hub"
                )

            # Pre-upload size validation against Telegram limit (Requirements 4 & 5)
            actual_size = out_path.stat().st_size
            if actual_size > settings.TELEGRAM_UPLOAD_LIMIT_BYTES:
                oversized_msg = get_oversized_file_message(
                    limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                    actual_size_bytes=actual_size
                )
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown")
                return None

            await status_msg.edit_text("📤 *Uploading compressed file...*", parse_mode="Markdown")

            # Deliver compressed file to user (Telegram upload must complete before local files are deleted)
            try:
                with open(out_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        filename=f"compressed_{source_path.name}",
                        caption=caption,
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
                    await status_msg.edit_text(oversized_msg, parse_mode="Markdown")
                else:
                    logger.error(f"Telegram compressed upload failed: {te}")
                    await status_msg.edit_text("❌ *Upload failed: Telegram could not receive the file. Please try again later.*", parse_mode="Markdown")
                return None

            return res
        finally:
            safe_delete_files([source_path, out_path], exclude_task_id=task_id, log_msg="after compression delivery")

    try:
        q_task = await queue_svc.submit_task(
            user_id=user_id,
            task_type="compressor",
            coro_fn=_execute_compression_job,
            associated_files=[source_path]
        )
        current_task_holder["task_id"] = q_task.task_id

        pos = queue_svc.get_queue_position(q_task.task_id)
        pos_str = f"Position in queue: #{pos}" if pos else "Processing now"
        await status_msg.edit_text(f"✅ *Task Enqueued!* ({pos_str})\nCompression will start shortly.", parse_mode="Markdown")

    except (QueueOverflowError, UserTaskLimitError) as qe:
        safe_delete_file(source_path, log_msg="queue limit reached")
        await status_msg.edit_text(f"⚠️ *Queue Error:* {qe}", parse_mode="Markdown")
    except Exception as e:
        safe_delete_file(source_path, log_msg="submission error")
        logger.error(f"Failed to submit compression task: {e}")
        await status_msg.edit_text("❌ *Failed to submit compression task.*", parse_mode="Markdown")



def register_compressor_handlers(application) -> None:
    """Register compressor commands and callback handlers."""
    application.add_handler(CommandHandler("compress", compressor_command_handler))
    application.add_handler(CallbackQueryHandler(handle_compression_level_callback, pattern=r"^cmp_lvl:"))
