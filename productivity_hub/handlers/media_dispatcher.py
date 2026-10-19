"""
Unified Media, Document, and Message Dispatcher.

Directs incoming user messages, documents, and photos to the appropriate functional handler
based on the active user session mode, file MIME type, and interactive action prompts:
1. Universal Media Downloader (URLs)
2. Dynamic Universal File Converter (Documents & Media)
3. Image Background Remover (Photos & Images)
4. Universal File Compressor (Files, Media & Archives)
5. QR Code Generator (Structured text payloads)
6. QR Code Scanner (Image decoding)
"""

import logging
from pathlib import Path
from typing import Dict, Optional
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import parse_callback_data, get_main_menu_keyboard
from productivity_hub.handlers.downloader import media_url_text_handler
from productivity_hub.handlers.converter import document_upload_handler, UPLOADED_FILES
from productivity_hub.handlers.background_remover import handle_bg_removal_image
from productivity_hub.handlers.compressor import show_compression_level_options
from productivity_hub.handlers.qr_generator import process_qr_text_input
from productivity_hub.handlers.qr_scanner import process_qr_scan_upload, get_qr_scanning_service
from productivity_hub.services.background_removal_service import get_background_removal_service
from productivity_hub.services.queue_service import get_queue_service, QueueOverflowError, UserTaskLimitError
from productivity_hub.utils.validators import (
    validate_url,
    validate_media_url,
    get_oversized_file_message,
    get_oversized_suggestion_keyboard
)
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.file_detector import detect_file_type
from productivity_hub.services.cleanup_service import safe_delete_file, safe_delete_files
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.dispatcher")

UPLOAD_DIR = Path("temp/uploads")
PENDING_IMAGE_ACTIONS: Dict[int, Path] = {}


@protected_handler(operation_type="default")
async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle all incoming non-command text messages.
    Routes to QR generator input parser, Media Downloader URL extractor, or guidance.
    """
    message = update.effective_message
    if not message or not message.text:
        return

    # 1. Check if user is actively providing input for QR Code Generation
    handled_qr = await process_qr_text_input(update, context)
    if handled_qr:
        return

    text = message.text.strip()
    active_mode = context.user_data.get("active_mode")

    # 2. Check if text is a media URL
    is_media_url, _, _ = validate_media_url(text)
    if is_media_url or validate_url(text):
        await media_url_text_handler(update, context)
        return

    # 3. Check if user is in an active tool mode that expected a file/URL
    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    if active_mode == "downloader":
        await message.reply_text(
            "⚠️ *Invalid Media URL:*\nPlease send a valid URL from YouTube, Instagram, TikTok, Facebook, Twitter/X, Snapchat, etc.",
            parse_mode="Markdown"
        )
        return
    elif active_mode == "bg_remover":
        await message.reply_text(
            "📸 *Background Remover Waiting:*\nPlease upload or forward the image you want the background removed from.",
            parse_mode="Markdown"
        )
        return
    elif active_mode == "compressor":
        await message.reply_text(
            "📦 *File Compressor Waiting:*\nPlease upload the document, image, video, audio, or PDF you want to compress.",
            parse_mode="Markdown"
        )
        return
    elif active_mode == "qr_scanner":
        await message.reply_text(
            "🔍 *QR Scanner Waiting:*\nPlease upload an image containing a QR code.",
            parse_mode="Markdown"
        )
        return
    elif active_mode == "converter":
        await message.reply_text(
            "🔄 *File Converter Waiting:*\nPlease upload the document or file you want to convert.",
            parse_mode="Markdown"
        )
        return

    # 4. Default fallback: Helpful guide with main menu
    await message.reply_text(
        "💡 *How can I help you?*\n\n"
        "• Send a *media link* to download video or audio\n"
        "• Send an *image or document* to convert, compress, or edit\n"
        "• Use /menu to view all productivity tools",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(owner_id=user_id, lang=lang)
    )


@protected_handler(operation_type="default")
async def unified_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming photo messages.
    Dispatches to Background Remover, QR Scanner, Compressor, Converter, or interactive prompt.
    """
    message = update.effective_message
    if not message or not message.photo:
        return

    user_id = update.effective_user.id
    active_mode = context.user_data.get("active_mode")

    user = context.user_data.get("user")
    lang = user.language if user else "en"

    if active_mode == "bg_remover":
        await handle_bg_removal_image(update, context)
        return
    elif active_mode == "qr_scanner":
        await process_qr_scan_upload(update, context)
        return
    elif active_mode == "converter":
        await document_upload_handler(update, context)
        return

    # Check known file size against limits before downloading (Requirement 2)
    settings = get_settings()
    max_in_bytes = min(settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, settings.MAX_FILE_SIZE_BYTES)
    photo_obj = message.photo[-1]
    if getattr(photo_obj, "file_size", None) and photo_obj.file_size > max_in_bytes:
        oversized_msg = get_oversized_file_message(limit_bytes=max_in_bytes, actual_size_bytes=photo_obj.file_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename="photo.jpg", lang=lang)
        await message.reply_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    # Download photo to local temp storage
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path, _ = generate_safe_filepath(UPLOAD_DIR, "photo.jpg", prefix="img")

    # Clean up previous pending image action file if any
    old_pending = PENDING_IMAGE_ACTIONS.get(user_id)
    if old_pending and old_pending != target_path:
        safe_delete_file(old_pending, log_msg="replaced by newer photo")

    status_msg = await message.reply_text("📥 *Receiving image...*", parse_mode="Markdown")
    try:
        tg_file = await context.bot.get_file(photo_obj.file_id)
        await tg_file.download_to_drive(custom_path=target_path)
    except Exception as e:
        safe_delete_file(target_path, log_msg="photo download failed")
        logger.error(f"Failed to download photo: {e}")
        await status_msg.edit_text("❌ *Failed to download photo from Telegram.*", parse_mode="Markdown")
        return

    # Post-download size validation if size was unknown before download
    actual_in_size = target_path.stat().st_size
    if actual_in_size > settings.MAX_FILE_SIZE_BYTES:
        safe_delete_file(target_path, log_msg="uploaded photo exceeds maximum size")
        oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_in_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename="photo.jpg", lang=lang)
        await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    if active_mode == "compressor":
        await status_msg.delete()
        await show_compression_level_options(update, context, target_path, "photo.jpg")
        return

    # Store pending image path for interactive action selection
    PENDING_IMAGE_ACTIONS[user_id] = target_path
    size_kb = target_path.stat().st_size / 1024

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🪄 Remove Background", callback_data=f"img_act:bg:{user_id}"),
            InlineKeyboardButton("📦 Compress Image", callback_data=f"img_act:compress:{user_id}")
        ],
        [
            InlineKeyboardButton("🔄 Convert Format", callback_data=f"img_act:convert:{user_id}"),
            InlineKeyboardButton("📷 Image to QR (Scan)", callback_data=f"img_act:scan:{user_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"img_act:cancel:{user_id}")
        ]
    ])

    await status_msg.edit_text(
        f"🖼️ *Image Received!* (`{size_kb:.1f} KB`)\n\n"
        f"👇 *What would you like to do with this image?*",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@protected_handler(operation_type="default")
async def unified_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming document messages.
    If image mime-type, dispatches through image pipeline; otherwise routes to Compressor or Converter.
    """
    message = update.effective_message
    if not message or not message.document:
        return

    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    doc = message.document
    mime = doc.mime_type or ""
    active_mode = context.user_data.get("active_mode")

    # Pre-download file size check against Telegram download and max limits (Requirement 2)
    settings = get_settings()
    max_in_bytes = min(settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, settings.MAX_FILE_SIZE_BYTES)
    if getattr(doc, "file_size", None) and doc.file_size > max_in_bytes:
        oversized_msg = get_oversized_file_message(limit_bytes=max_in_bytes, actual_size_bytes=doc.file_size)
        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=doc.file_name or "document", lang=lang)
        await message.reply_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
        return

    # If it is an image uploaded as uncompressed document
    if mime.startswith("image/"):
        if active_mode == "bg_remover":
            await handle_bg_removal_image(update, context)
            return
        elif active_mode == "qr_scanner":
            await process_qr_scan_upload(update, context)
            return

    # If user explicitly opened compressor
    if active_mode == "compressor":
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = doc.file_name or "document"
        target_path, _ = generate_safe_filepath(UPLOAD_DIR, filename, prefix="comp_in")
        status_msg = await message.reply_text("📥 *Receiving file for compression...*", parse_mode="Markdown")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(custom_path=target_path)
            
            # Post-download size validation
            if target_path.stat().st_size > settings.MAX_FILE_SIZE_BYTES:
                actual_in_size = target_path.stat().st_size
                safe_delete_file(target_path, log_msg="uploaded doc exceeds maximum size")
                oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_in_size)
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown")
                return

            await status_msg.delete()
            await show_compression_level_options(update, context, target_path, filename)
            return
        except Exception as e:
            safe_delete_file(target_path, log_msg="document compression download failed")
            logger.error(f"Failed to download document for compression: {e}")
            await status_msg.edit_text("❌ *Failed to download file from Telegram.*", parse_mode="Markdown")
            return

    # If user explicitly wanted background removal but sent document
    if active_mode == "bg_remover":
        await handle_bg_removal_image(update, context)
        return

    # If user explicitly wanted QR scan
    if active_mode == "qr_scanner":
        await process_qr_scan_upload(update, context)
        return

    # If uncompressed image without explicit mode, provide interactive image action menu
    if mime.startswith("image/"):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = doc.file_name or "image.png"
        target_path, _ = generate_safe_filepath(UPLOAD_DIR, filename, prefix="img")

        old_pending = PENDING_IMAGE_ACTIONS.get(user_id)
        if old_pending and old_pending != target_path:
            safe_delete_file(old_pending, log_msg="replaced by newer image doc")

        status_msg = await message.reply_text("📥 *Receiving image...*", parse_mode="Markdown")
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(custom_path=target_path)

            if target_path.stat().st_size > settings.MAX_FILE_SIZE_BYTES:
                actual_in_size = target_path.stat().st_size
                safe_delete_file(target_path, log_msg="uploaded image doc exceeds maximum size")
                oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES, actual_size_bytes=actual_in_size)
                kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=filename, lang=lang)
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                return

            PENDING_IMAGE_ACTIONS[user_id] = target_path
            size_kb = target_path.stat().st_size / 1024

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🪄 Remove Background", callback_data=f"img_act:bg:{user_id}"),
                    InlineKeyboardButton("📦 Compress Image", callback_data=f"img_act:compress:{user_id}")
                ],
                [
                    InlineKeyboardButton("🔄 Convert Format", callback_data=f"img_act:convert:{user_id}"),
                    InlineKeyboardButton("🔍 Scan for QR Code", callback_data=f"img_act:scan:{user_id}")
                ],
                [
                    InlineKeyboardButton("❌ Cancel", callback_data=f"img_act:cancel:{user_id}")
                ]
            ])
            await status_msg.edit_text(
                f"🖼️ *Image Document Received!* (`{size_kb:.1f} KB`)\n\n"
                f"👇 *What would you like to do with this image?*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        except Exception as e:
            safe_delete_file(target_path, log_msg="image document download failed")
            logger.error(f"Failed to receive image document: {e}")
            await status_msg.edit_text("❌ *Failed to download file.*", parse_mode="Markdown")
            return

    # Default for all other document types: Universal File Converter
    await document_upload_handler(update, context)


async def handle_image_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle interactive action buttons for uploaded images (Background Removal, Compression, Conversion, QR Scan).
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, sub_action, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer("⚠️ Unauthorized button click.", show_alert=True)
        return

    source_path = PENDING_IMAGE_ACTIONS.get(user_id)
    if not source_path or not source_path.exists():
        await query.answer("❌ Image session expired. Please re-upload your image.", show_alert=True)
        return

    await query.answer()

    if sub_action == "cancel":
        safe_delete_file(source_path, log_msg="action cancelled by user")
        PENDING_IMAGE_ACTIONS.pop(user_id, None)
        await query.edit_message_text("❌ *Action cancelled. Image discarded.*", parse_mode="Markdown")
        return

    elif sub_action == "compress":
        await query.message.delete()
        await show_compression_level_options(update, context, source_path, source_path.name)
        return

    elif sub_action == "convert":
        # Pass path to converter session
        UPLOADED_FILES[user_id] = source_path
        PENDING_IMAGE_ACTIONS.pop(user_id, None)
        await query.message.delete()

        # Present converter options for the image
        from productivity_hub.utils.conversion_registry import get_conversion_registry
        from productivity_hub.services.conversion_service import get_conversion_service
        from productivity_hub.handlers.keyboards import build_paginated_keyboard

        file_info = detect_file_type(source_path)
        ext = file_info.extension.lower()
        registry = get_conversion_registry()
        conv_service = get_conversion_service()
        active_rules = [
            rule for rule in registry.get_available_conversions(ext)
            if conv_service.is_conversion_available(rule.source_format, rule.target_format)
        ]

        if not active_rules:
            safe_delete_file(source_path, log_msg="no available conversions for image")
            UPLOADED_FILES.pop(user_id, None)
            await query.message.reply_text(f"⚠️ No active conversions available for `{ext.upper()}`.", parse_mode="Markdown")
            return

        items = [(f"🔄 {rule.description}", rule.target_format) for rule in active_rules]
        kb = build_paginated_keyboard(
            items=items,
            page=0,
            page_size=6,
            callback_prefix="convfmt",
            owner_id=user_id,
            lang="en",
            row_width=2
        )
        await query.message.reply_text(
            f"📄 *File:* `{source_path.name}`\n"
            f"🔍 *Format:* `{ext.upper()}`\n\n"
            f"👇 *Select conversion target:*",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    elif sub_action == "scan":
        await query.edit_message_text("🔍 *Scanning image for QR codes...*", parse_mode="Markdown")
        scanner_svc = get_qr_scanning_service()
        try:
            try:
                results = await scanner_svc.scan_image(source_path, user_id=user_id)
            except Exception as e:
                logger.error(f"Error scanning QR: {e}")
                await query.edit_message_text("❌ *An error occurred while scanning QR code.*", parse_mode="Markdown")
                return

            if not results:
                await query.edit_message_text(
                    "⚠️ *No readable QR code found in this image.*\nEnsure it is clear, in focus, and properly lit.",
                    parse_mode="Markdown"
                )
                return

            for idx, qr in enumerate(results, 1):
                detail_lines = [f"• *{k}*: `{v}`" for k, v in qr.details.items()]
                detail_text = "\n".join(detail_lines) if detail_lines else ""
                raw_block = f"\n\n📋 *Raw Content:*\n```text\n{qr.raw_text}\n```"
                full_text = f"🔍 *QR Code Result #{idx}* — {qr.type_display}\n\n{detail_text}{raw_block}"

                buttons = []
                if qr.is_safe_url and qr.safe_url:
                    buttons.append([InlineKeyboardButton("🔗 Open Link", url=qr.safe_url)])
                buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data=f"menu:main:{user_id}")])

                await query.message.reply_text(
                    text=full_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True
                )
            return
        finally:
            safe_delete_file(source_path, log_msg="after image scan action")
            PENDING_IMAGE_ACTIONS.pop(user_id, None)

    elif sub_action == "bg":
        bg_service = get_background_removal_service()
        if not bg_service.is_engine_available():
            safe_delete_file(source_path, log_msg="bg engine unavailable")
            PENDING_IMAGE_ACTIONS.pop(user_id, None)
            await query.edit_message_text(
                "⚠️ *Background Removal Engine Unavailable:*\nThe neural inference backend is not installed in this environment.",
                parse_mode="Markdown"
            )
            return

        PENDING_IMAGE_ACTIONS.pop(user_id, None)
        await query.edit_message_text("⏳ *Enqueuing background removal task...*", parse_mode="Markdown")
        queue_svc = get_queue_service()

        current_task_holder = {}

        async def _execute_bg():
            task_id = current_task_holder.get("task_id")
            out_path = None
            try:
                await query.edit_message_text("🪄 *Removing background with neural network...*", parse_mode="Markdown")
                res = await bg_service.remove_background(source_path, user_id=user_id)
                out_path = res["output_path"]

                if task_id:
                    queue_svc.register_task_files(task_id, out_path)

                # Pre-upload size validation against Telegram limit (Requirements 4 & 5)
                settings = get_settings()
                actual_size = out_path.stat().st_size
                if actual_size > settings.TELEGRAM_UPLOAD_LIMIT_BYTES:
                    oversized_msg = get_oversized_file_message(
                        limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                        actual_size_bytes=actual_size
                    )
                    kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=out_path.name, lang="en")
                    await query.edit_message_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                    return None

                await query.edit_message_text("📤 *Uploading transparent PNG...*", parse_mode="Markdown")
                # Telegram upload must complete before deleting files
                try:
                    with open(out_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=f,
                            filename=f"transparent_{source_path.stem}.png",
                            caption="🪄 *Background Removed Successfully!*\nDelivered as transparent PNG via Productivity Hub",
                            parse_mode="Markdown"
                        )
                    await query.message.delete()
                except telegram.error.TelegramError as te:
                    err_str = str(te).lower()
                    if "too big" in err_str or "entity too large" in err_str:
                        oversized_msg = get_oversized_file_message(
                            limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                            actual_size_bytes=actual_size
                        )
                        kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=out_path.name, lang="en")
                        await query.edit_message_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                    else:
                        logger.error(f"Telegram upload failed: {te}")
                        await query.edit_message_text("❌ *Upload failed: Telegram could not receive the file. Please try again later.*", parse_mode="Markdown")
                    return None

                return res
            finally:
                safe_delete_files([source_path, out_path], exclude_task_id=task_id, log_msg="after bg action delivery")

        try:
            q_task = await queue_svc.submit_task(
                user_id=user_id,
                task_type="background_removal",
                coro_fn=_execute_bg,
                associated_files=[source_path]
            )
            current_task_holder["task_id"] = q_task.task_id

            pos = queue_svc.get_queue_position(q_task.task_id)
            pos_str = f"Position in queue: #{pos}" if pos else "Processing now"
            await query.edit_message_text(f"✅ *Task Enqueued!* ({pos_str})\nBackground removal will start shortly.", parse_mode="Markdown")
        except (QueueOverflowError, UserTaskLimitError) as qe:
            safe_delete_file(source_path, log_msg="queue limit reached")
            await query.edit_message_text(f"⚠️ *Queue Error:* {qe}", parse_mode="Markdown")
        except Exception as e:
            safe_delete_file(source_path, log_msg="submission error")
            logger.error(f"Failed to submit background removal task: {e}")
            await query.edit_message_text("❌ *Failed to submit task.*", parse_mode="Markdown")
