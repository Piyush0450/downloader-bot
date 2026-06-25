import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.conversion_service import execute_format_conversion
from services.queue_service import enqueue_task
from services.database_service import ConversionService
from services.security_service import RateLimiter, check_user_access
from utils.file_detector import get_file_info
from utils.helpers import cleanup_file, format_size, generate_temp_path
from utils.logger import logger
from utils.conversion_registry import get_conversion_targets
from utils.validators import validate_file_size
from config.settings import CONVERTED_DIR

async def handle_document_upload(update: Update, context: CallbackContext):
    """Router for all incoming uploaded files (documents, audios, videos)."""
    if context.user_data.get("admin_state") == "wait_broadcast_content":
        from handlers.admin import handle_admin_broadcast_upload
        await handle_admin_broadcast_upload(update, context)
        return
        
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if RateLimiter.is_rate_limited(user_id):
        from services.security_service import record_suspicious_event
        await record_suspicious_event(update, context, "Rate limit exceeded (Spam)")
        return
        
    doc = update.message.document
    audio = update.message.audio
    video = update.message.video
    
    file_id = None
    file_name = "file"
    file_size = 0
    mime = "application/octet-stream"
    
    if doc:
        file_id = doc.file_id
        file_name = doc.file_name or "document"
        file_size = doc.file_size
        mime = doc.mime_type
    elif audio:
        file_id = audio.file_id
        file_name = audio.file_name or "audio.mp3"
        file_size = audio.file_size
        mime = audio.mime_type
    elif video:
        file_id = video.file_id
        file_name = video.file_name or "video.mp4"
        file_size = video.file_size
        mime = video.mime_type
        
    if not file_id:
        return
        
    # Check logical size limit (2GB)
    if not validate_file_size(file_size):
        await update.message.reply_text("❌ File exceeds the maximum processing limit of 2 GB.")
        return
        
    # Detect File
    info = get_file_info(file_name, file_size)
    ext = info["extension"]
    
    targets = get_conversion_targets(ext)
    
    # Store session details
    context.user_data["converter"] = {
        "file_id": file_id,
        "file_name": file_name,
        "file_size": file_size,
        "ext": ext,
        "mime": mime
    }
    
    # Contextual check for PDF which also supports compression
    if ext == "pdf":
        keyboard = [
            [
                InlineKeyboardButton("🔄 Convert PDF", callback_data="pdf_menu_conv"),
                InlineKeyboardButton("📦 Compress PDF", callback_data="pdf_menu_comp")
            ],
            [InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")]
        ]
        context.user_data["compressor"] = {
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "is_pdf": True
        }
        await update.message.reply_text(
            f"📄 **PDF Document Detected**\n\n"
            f"📁 **Name:** {file_name}\n"
            f"📏 **Size:** {format_size(file_size)}\n\n"
            f"What action would you like to perform?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
        
    if not targets:
        await update.message.reply_text(
            f"📄 **File Analysis Complete**\n\n"
            f"📁 **Name:** {file_name}\n"
            f"⚙️ **Type:** {info['category']}\n"
            f"📦 **Size:** {format_size(file_size)}\n\n"
            f"⚠️ *No conversions available for this format.*"
        )
        return
        
    # Dynamically build buttons from conversion targets registry
    keyboard = []
    row = []
    for tgt in targets:
        row.append(InlineKeyboardButton(tgt.upper(), callback_data=f"conv_{ext}_{tgt}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")])
    
    await update.message.reply_text(
        f"📄 **File Analysis Complete**\n\n"
        f"📁 **Name:** {file_name}\n"
        f"⚙️ **Type:** {info['category']}\n"
        f"📦 **Size:** {format_size(file_size)}\n\n"
        f"Available Actions:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_converter_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    data = context.user_data.get("converter")
    
    if not data:
        await query.message.reply_text("❌ Session expired. Please re-upload your file.")
        return
        
    action = query.data
    
    # Handle PDF routing redirect
    if action == "pdf_menu_conv":
        ext = data["ext"]
        targets = get_conversion_targets(ext)
        keyboard = []
        row = []
        for tgt in targets:
            row.append(InlineKeyboardButton(tgt.upper(), callback_data=f"conv_{ext}_{tgt}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
        await query.message.edit_text("🔄 Select conversion target for PDF:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    if not action.startswith("conv_"):
        return
        
    parts = action.split("_")
    source_ext = parts[1]
    target_ext = parts[2]
    
    desc = f"Convert {source_ext.upper()} to {target_ext.upper()}"
    status_msg = await query.message.reply_text("⏳ Enqueuing conversion task...")
    
    async def worker_func():
        await status_msg.edit_text(f"⏳ Downloading and converting to {target_ext.upper()}...")
        infile = None
        outfile = None
        try:
            tg_file = await context.bot.get_file(data["file_id"])
            # Save using original extension to let validator identify types correctly
            infile = CONVERTED_DIR / f"in_{generate_temp_path(source_ext).name}"
            await tg_file.download_to_drive(custom_path=infile)
            
            # Execute
            outfile = await execute_format_conversion(infile, target_ext)
            
            if not outfile.exists() or outfile.stat().st_size == 0:
                raise RuntimeError("Resulting file is empty or does not exist.")
                
            out_size = outfile.stat().st_size
            await status_msg.edit_text("📤 Uploading converted file...")
            
            # Determine response method based on format
            out_name = f"{Path(data['file_name']).stem}.{target_ext}"
            
            with open(outfile, "rb") as f:
                if target_ext == "pdf":
                    await context.bot.send_document(chat_id=chat_id, document=f, filename=out_name, caption="📄 Converted PDF document.")
                elif target_ext == "images":
                    # ZIP of images
                    await context.bot.send_document(chat_id=chat_id, document=f, filename=f"{Path(data['file_name']).stem}_images.zip", caption="📦 Converted ZIP archive.")
                elif target_ext in ("mp3", "wav", "ogg", "aac", "flac"):
                    await context.bot.send_audio(chat_id=chat_id, audio=f, filename=out_name, caption="🎵 Converted Audio.")
                elif target_ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico"):
                    await context.bot.send_photo(chat_id=chat_id, photo=f, caption="🖼 Converted Image.")
                else:
                    await context.bot.send_document(chat_id=chat_id, document=f, filename=out_name, caption="📄 Converted File.")
                    
            await status_msg.delete()
            ConversionService.log_conversion(
                user_id=user_id,
                original_file=data["file_name"],
                source_format=source_ext,
                target_format=target_ext,
                file_size=out_size
            )
        except Exception as e:
            logger.error(f"Converter worker failed: {e}")
            await status_msg.edit_text(f"❌ Conversion failed. Details: {str(e)[:100]}")
        finally:
            cleanup_file(infile)
            cleanup_file(outfile)

    # Queue task
    try:
        task, position, wait_time = await enqueue_task(
            user_id, context.bot, chat_id, desc, worker_func
        )
    except ValueError as e:
        from services.security_service import record_suspicious_event
        await record_suspicious_event(update, context, "Queue spam / Cooldown bypass")
        await status_msg.edit_text(str(e))
        return
        
    if position > 0:
        await status_msg.edit_text(
            f"⏳ **Queue Position: #{position}**\n"
            f"Estimated Wait Time: {wait_time} minutes"
        )
        try:
            await task.future
        except Exception:
            pass
    else:
        try:
            await task.future
        except Exception:
            pass
