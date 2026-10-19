"""
Image Background Remover Handler.

Handles background removal requests, photo/document uploads intended for background stripping,
submits tasks to TaskQueueService, and returns high-resolution transparent PNG files.
"""

import logging
from pathlib import Path
import telegram.error
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import get_back_keyboard
from productivity_hub.services.background_removal_service import get_background_removal_service, BackgroundRemovalError
from productivity_hub.services.queue_service import get_queue_service, QueueOverflowError, UserTaskLimitError
from productivity_hub.services.cleanup_service import safe_delete_file, safe_delete_files
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.validators import get_oversized_file_message, get_oversized_suggestion_keyboard
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.background_remover")

UPLOAD_DIR = Path("temp/uploads")


@protected_handler(operation_type="default")
async def bg_remover_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /bg command or menu prompt."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    title = get_text("title_bg_remover", lang)
    desc = get_text("desc_bg_remover", lang)
    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            f"{title}\n\n{desc}\n\n📸 *Please upload or forward the image now:*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


@protected_handler(operation_type="background_removal")
async def handle_bg_removal_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Process uploaded image specifically for background removal when user triggered bg mode,
    or via direct photo upload.
    """
    message = update.effective_message
    if not message:
        return

    # Check if image was sent
    photo_obj = None
    if message.photo:
        photo_obj = message.photo[-1]
        filename = "photo.jpg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        photo_obj = message.document
        filename = message.document.file_name or "image.png"
    else:
        return

    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Pre-download file size check against Telegram download and max limits (Requirement 2)
    settings = get_settings()
    max_in_bytes = min(settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, settings.MAX_FILE_SIZE_BYTES)
    if getattr(photo_obj, "file_size", None) and photo_obj.file_size > max_in_bytes:
        oversized_msg = get_oversized_file_message(limit_bytes=max_in_bytes, actual_size_bytes=photo_obj.file_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=filename, lang=lang)
        await message.reply_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    bg_service = get_background_removal_service()
    if not bg_service.is_engine_available():
        await message.reply_text(
            "⚠️ *Background Removal Engine Unavailable:*\nThe neural inference backend is currently not installed in this environment.",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard(owner_id=user_id, lang=lang)
        )
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path, _ = generate_safe_filepath(UPLOAD_DIR, filename, prefix="bg_in")

    status_msg = await message.reply_text("📥 *Downloading image for background removal...*", parse_mode="Markdown")

    try:
        tg_file = await context.bot.get_file(photo_obj.file_id)
        await tg_file.download_to_drive(custom_path=target_path)
    except Exception as e:
        safe_delete_file(target_path, log_msg="telegram download error")
        logger.error(f"Failed to download image from Telegram: {e}")
        await status_msg.edit_text("❌ *Failed to download image from Telegram.*", parse_mode="Markdown")
        return

    # Post-download size validation if size was unknown before download
    actual_in_size = target_path.stat().st_size
    if actual_in_size > settings.MAX_FILE_SIZE_BYTES:
        safe_delete_file(target_path, log_msg="uploaded image exceeds maximum size")
        oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_in_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=filename, lang=lang)
        await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    queue_svc = get_queue_service()
    current_task_holder = {}

    async def _execute_bg_removal():
        task_id = current_task_holder.get("task_id")
        out_path = None
        try:
            await status_msg.edit_text("🪄 *Removing background with neural network...*", parse_mode="Markdown")
            res = await bg_service.remove_background(target_path, user_id=user_id)
            out_path = res["output_path"]

            if task_id:
                queue_svc.register_task_files(task_id, out_path)

            # Pre-upload size validation against Telegram limit (Requirements 4 & 5)
            actual_size = out_path.stat().st_size
            if actual_size > settings.TELEGRAM_UPLOAD_LIMIT_BYTES:
                oversized_msg = get_oversized_file_message(
                    limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                    actual_size_bytes=actual_size
                )
                kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=out_path.name, lang=lang)
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                return None

            await status_msg.edit_text("📤 *Uploading transparent PNG...*", parse_mode="Markdown")

            # Send as document to preserve PNG transparency (send_photo converts to non-alpha JPEG)
            # Delivery must finish uploading completely before deleting local files
            try:
                with open(out_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=message.chat_id,
                        document=f,
                        filename=f"transparent_{Path(filename).stem}.png",
                        caption="🪄 *Background Removed Successfully!*\nDelivered as transparent PNG via Productivity Hub",
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
                    kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=out_path.name, lang=lang)
                    await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                else:
                    logger.error(f"Telegram background-removed image upload failed: {te}")
                    await status_msg.edit_text("❌ *Upload failed: Telegram could not receive the file. Please try again later.*", parse_mode="Markdown")
                return None

            return res
        finally:
            safe_delete_files([target_path, out_path], exclude_task_id=task_id, log_msg="after background removal delivery")

    try:
        q_task = await queue_svc.submit_task(
            user_id=user_id,
            task_type="background_removal",
            coro_fn=_execute_bg_removal,
            associated_files=[target_path]
        )
        current_task_holder["task_id"] = q_task.task_id

        pos = queue_svc.get_queue_position(q_task.task_id)
        pos_str = f"Position in queue: #{pos}" if pos else "Processing now"
        await status_msg.edit_text(f"✅ *Task Enqueued!* ({pos_str})\nBackground removal will start shortly.", parse_mode="Markdown")

    except (QueueOverflowError, UserTaskLimitError) as qe:
        safe_delete_file(target_path, log_msg="queue limit reached")
        await status_msg.edit_text(f"⚠️ *Queue Error:* {qe}", parse_mode="Markdown")
    except Exception as e:
        safe_delete_file(target_path, log_msg="submission error")
        logger.error(f"Failed to submit background removal task: {e}")
        await status_msg.edit_text("❌ *Failed to process background removal.*", parse_mode="Markdown")



def register_bg_removal_handlers(application) -> None:
    """Register background remover commands and handlers."""
    application.add_handler(CommandHandler("bg", bg_remover_command_handler))
    application.add_handler(CommandHandler("background", bg_remover_command_handler))
