import asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.compression_service import compress_pdf
from services.image_service import compress_image
from services.queue_service import enqueue_task
from services.database_service import UserService, log_event
from utils.helpers import cleanup_file, format_size, generate_temp_path
from utils.logger import logger
from config.settings import CONVERTED_DIR

async def handle_pdf_compress_callback(update: Update, context: CallbackContext):
    """Callback for PDF detection message when 'Compress PDF' is clicked."""
    query = update.callback_query
    await query.answer()
    
    data = context.user_data.get("compressor")
    if not data:
        await query.message.reply_text("❌ Session expired. Please re-upload your PDF.")
        return
        
    keyboard = [
        [
            InlineKeyboardButton("🟢 Low Compression", callback_data="comp_run_low"),
            InlineKeyboardButton("🟡 Medium Compression", callback_data="comp_run_medium")
        ],
        [
            InlineKeyboardButton("🔴 High Compression", callback_data="comp_run_high")
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")]
    ]
    await query.message.edit_text(
        f"📦 **PDF Compression Settings**\n\n"
        f"📁 **File:** {data['file_name']}\n"
        f"📏 **Original Size:** {format_size(data['file_size'])}\n\n"
        f"Choose compression level:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_compressor_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    data = context.user_data.get("compressor")
    
    if not data:
        await query.message.reply_text("❌ Session expired. Please re-upload your file.")
        return
        
    action = query.data
    
    if action == "comp_run_custom":
        context.user_data["comp_state"] = "wait_comp_pct"
        await query.message.reply_text("✏️ Please enter custom quality level (1-100):")
        return
        
    status_msg = await query.message.reply_text("⏳ Enqueuing compression task...")
    
    # Map presets
    level = "medium"
    img_qual = 50
    if action == "comp_run_low":
        level = "low"
        img_qual = 80
    elif action == "comp_run_high":
        level = "high"
        img_qual = 20
        
    desc = f"Compress {'PDF' if data['is_pdf'] else 'Image'} ({level})"
    
    async def worker_func():
        await status_msg.edit_text("⚡ Compressing file...")
        infile = None
        outfile = None
        try:
            tg_file = await context.bot.get_file(data["file_id"])
            ext = "pdf" if data["is_pdf"] else "png"
            infile = CONVERTED_DIR / f"comp_in_{generate_temp_path(ext).name}"
            await tg_file.download_to_drive(custom_path=infile)
            
            outfile = CONVERTED_DIR / f"comp_out_{generate_temp_path(ext).name}"
            
            if data["is_pdf"]:
                await compress_pdf(infile, outfile, level)
            else:
                await compress_image(infile, outfile, img_qual)
                
            if outfile.exists() and outfile.stat().st_size > 0:
                orig_size = data["file_size"]
                comp_size = outfile.stat().st_size
                
                saved = max(0, orig_size - comp_size)
                saved_pct = (saved / orig_size * 100) if orig_size > 0 else 0.0
                
                # Update database storage saved
                UserService.add_storage_saved(user_id, saved)
                
                caption = (
                    f"✅ **Compression Complete!**\n\n"
                    f"📏 **Original Size:** {format_size(orig_size)}\n"
                    f"📉 **Compressed Size:** {format_size(comp_size)}\n"
                    f"🎉 **Space Saved:** {saved_pct:.2f}%"
                )
                
                await status_msg.edit_text("📤 Uploading compressed file...")
                with open(outfile, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=data["file_name"],
                        caption=caption,
                        parse_mode="Markdown"
                    )
                await status_msg.delete()
                log_event("CONVERSIONS", f"User {user_id} compressed {ext} (Saved {saved_pct:.1f}%)")
            else:
                await status_msg.edit_text("❌ Compression failed to create file.")
        except Exception as e:
            logger.error(f"Compression task failed: {e}")
            await status_msg.edit_text("❌ Compression failed.")
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

async def handle_custom_comp_pct(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    state = context.user_data.get("comp_state")
    
    if state != "wait_comp_pct":
        return
        
    context.user_data["comp_state"] = None
    data = context.user_data.get("compressor")
    
    if not data:
        await update.message.reply_text("❌ Session expired. Please re-upload your file.")
        return
        
    text = update.message.text.strip()
    try:
        qual = int(text)
        if qual < 1 or qual > 100:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Invalid percentage. Enter a value between 1 and 100.")
        return
        
    desc = f"Compress image (custom {qual}%)"
    status_msg = await update.message.reply_text("⏳ Enqueuing compression task...")
    
    async def worker_func():
        await status_msg.edit_text(f"⚡ Compressing image with quality {qual}%...")
        infile = None
        outfile = None
        try:
            tg_file = await context.bot.get_file(data["file_id"])
            infile = CONVERTED_DIR / f"comp_cust_in_{generate_temp_path('png').name}"
            await tg_file.download_to_drive(custom_path=infile)
            
            outfile = CONVERTED_DIR / f"comp_cust_out_{generate_temp_path('png').name}"
            await compress_image(infile, outfile, qual)
            
            if outfile.exists() and outfile.stat().st_size > 0:
                orig_size = data["file_size"]
                comp_size = outfile.stat().st_size
                saved = max(0, orig_size - comp_size)
                saved_pct = (saved / orig_size * 100) if orig_size > 0 else 0.0
                
                UserService.add_storage_saved(user_id, saved)
                caption = (
                    f"✅ **Compression Complete!**\n\n"
                    f"📏 **Original Size:** {format_size(orig_size)}\n"
                    f"📉 **Compressed Size:** {format_size(comp_size)}\n"
                    f"🎉 **Space Saved:** {saved_pct:.2f}%"
                )
                
                await status_msg.edit_text("📤 Uploading compressed image...")
                with open(outfile, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=data["file_name"],
                        caption=caption,
                        parse_mode="Markdown"
                    )
                await status_msg.delete()
                log_event("CONVERSIONS", f"User {user_id} custom compressed image (Saved {saved_pct:.1f}%)")
            else:
                await status_msg.edit_text("❌ Compression failed.")
        except Exception as e:
            logger.error(f"Custom compression failed: {e}")
            await status_msg.edit_text("❌ Compression failed.")
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
