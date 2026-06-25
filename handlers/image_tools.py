import asyncio
from pathlib import Path
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.image_service import (
    resize_image, crop_image, rotate_image, compress_image,
    generate_thumbnail, extract_metadata, remove_metadata
)
from services.queue_service import enqueue_task
from services.database_service import UserService, log_event
from services.security_service import RateLimiter
from utils.helpers import cleanup_file, format_size
from utils.logger import logger
from utils.helpers import generate_temp_path
from config.settings import CONVERTED_DIR

async def handle_photo_upload(update: Update, context: CallbackContext):
    """Entry point for direct photo uploads."""
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
        
    photo = update.message.photo[-1]
    file_id = photo.file_id
    file_size = photo.file_size
    
    # Store session details
    context.user_data["image_tool"] = {
        "file_id": file_id,
        "file_name": f"photo_{file_id[:8]}.png",
        "file_size": file_size
    }
    
    # Perform background scan for QR first
    from services.qr_service import scan_qr_image
    temp_img = generate_temp_path("png")
    qr_val = ""
    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=temp_img)
        res = await scan_qr_image(temp_img)
        qr_val = res["content"]
    except Exception as e:
        logger.error(f"Failed scanning photo for QR: {e}")
    finally:
        cleanup_file(temp_img)
        
    if qr_val:
        # Suggest QR decoding
        context.user_data["qr_scan_file_id"] = file_id
        keyboard = [
            [InlineKeyboardButton("🔍 Decode QR Code", callback_data="qr_scan_decode")],
            [InlineKeyboardButton("🖼 Image Tools Console", callback_data="img_menu_main")],
            [InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")]
        ]
        await update.message.reply_text(
            "🔳 **QR Code Detected in Image!**\n\nWould you like to decode it, or open the Image Tools Console?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        # Show image tools console immediately
        await show_image_tools_console(update, context, query_edit=False)

async def show_image_tools_console(update: Update, context: CallbackContext, query_edit: bool = False):
    data = context.user_data.get("image_tool")
    if not data:
        return
        
    keyboard = [
        [
            InlineKeyboardButton("JPG", callback_data="img_conv_jpg"),
            InlineKeyboardButton("WEBP", callback_data="img_conv_webp"),
            InlineKeyboardButton("BMP", callback_data="img_conv_bmp")
        ],
        [
            InlineKeyboardButton("TIFF", callback_data="img_conv_tiff"),
            InlineKeyboardButton("ICO", callback_data="img_conv_ico"),
            InlineKeyboardButton("PDF", callback_data="img_conv_pdf")
        ],
        [
            InlineKeyboardButton("📦 Compress", callback_data="img_op_compress"),
            InlineKeyboardButton("📏 Resize", callback_data="img_op_resize")
        ],
        [
            InlineKeyboardButton("✂️ Crop", callback_data="img_op_crop"),
            InlineKeyboardButton("🔄 Rotate", callback_data="img_op_rotate")
        ],
        [
            InlineKeyboardButton("🖼 Thumbnail", callback_data="img_op_thumb"),
            InlineKeyboardButton("ℹ️ View Metadata", callback_data="img_op_meta")
        ],
        [
            InlineKeyboardButton("🧹 Clean Metadata", callback_data="img_op_strip"),
            InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")
        ]
    ]
    
    text = (
        f"🖼 **Image Analysis Complete**\n\n"
        f"📁 **Name:** {data['file_name']}\n"
        f"📦 **Size:** {format_size(data['file_size'])}\n\n"
        f"Available Actions:"
    )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query_edit:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_image_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    data = context.user_data.get("image_tool")
    
    if not data:
        await query.message.reply_text("❌ Session expired. Please re-upload your image.")
        return
        
    action = query.data
    
    if action == "img_menu_main":
        await show_image_tools_console(update, context, query_edit=True)
        return
        
    elif action == "img_op_resize":
        context.user_data["img_state"] = "wait_resize"
        await query.message.reply_text(
            "📏 **Resize Dimensions**\n\nPlease send desired size:\n"
            "- Percentage: `50%` or `120%`\n"
            "- Exact: `800x600` (width x height)"
        )
        return
        
    elif action == "img_op_crop":
        keyboard = [
            [
                InlineKeyboardButton("1:1 (Square)", callback_data="img_run_crop_1.0"),
                InlineKeyboardButton("16:9 (Widescreen)", callback_data="img_run_crop_1.777")
            ],
            [
                InlineKeyboardButton("4:3 (Standard)", callback_data="img_run_crop_1.333"),
                InlineKeyboardButton("⬅️ Back", callback_data="img_menu_main")
            ]
        ]
        await query.message.edit_text("✂️ Select crop aspect ratio:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif action == "img_op_rotate":
        keyboard = [
            [
                InlineKeyboardButton("90° CW", callback_data="img_run_rot_-90"),
                InlineKeyboardButton("90° CCW", callback_data="img_run_rot_90")
            ],
            [
                InlineKeyboardButton("180°", callback_data="img_run_rot_180"),
                InlineKeyboardButton("⬅️ Back", callback_data="img_menu_main")
            ]
        ]
        await query.message.edit_text("🔄 Select rotation angle:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif action == "img_op_compress":
        keyboard = [
            [
                InlineKeyboardButton("Low (80% Quality)", callback_data="img_run_comp_80"),
                InlineKeyboardButton("Medium (50% Quality)", callback_data="img_run_comp_50")
            ],
            [
                InlineKeyboardButton("High (20% Quality)", callback_data="img_run_comp_20"),
                InlineKeyboardButton("⬅️ Back", callback_data="img_menu_main")
            ]
        ]
        await query.message.edit_text("📦 Select compression strength:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Direct task runners enqueued
    desc = f"Image Action: {action.upper()}"
    status_msg = await query.message.reply_text("⏳ Processing image...")
    
    async def worker_func():
        await status_msg.edit_text("⚡ Processing your image...")
        infile = None
        outfile = None
        try:
            tg_file = await context.bot.get_file(data["file_id"])
            infile = CONVERTED_DIR / f"img_in_{generate_temp_path('png').name}"
            await tg_file.download_to_drive(custom_path=infile)
            
            # 1. Format Conversions
            if action.startswith("img_conv_"):
                tgt_ext = action.split("_")[-1]
                outfile = CONVERTED_DIR / f"img_out_{generate_temp_path(tgt_ext).name}"
                from services.conversion_service import convert_image_sync
                await asyncio.to_thread(convert_image_sync, infile, outfile, tgt_ext)
                action_type = f"conv_{tgt_ext}"
            
            # 2. Crops
            elif action.startswith("img_run_crop_"):
                ratio = float(action.split("_")[-1])
                outfile = CONVERTED_DIR / f"img_crop_{generate_temp_path('png').name}"
                await crop_image(infile, outfile, ratio)
                action_type = "crop"
                
            # 3. Rotations
            elif action.startswith("img_run_rot_"):
                angle = int(action.split("_")[-1])
                outfile = CONVERTED_DIR / f"img_rot_{generate_temp_path('png').name}"
                await rotate_image(infile, outfile, angle)
                action_type = "rotate"
                
            # 4. Compressions
            elif action.startswith("img_run_comp_"):
                qual = int(action.split("_")[-1])
                outfile = CONVERTED_DIR / f"img_comp_{generate_temp_path('png').name}"
                await compress_image(infile, outfile, qual)
                action_type = "compress"
                
                # storage saved metrics
                in_size = infile.stat().st_size
                out_size = outfile.stat().st_size
                if in_size > out_size:
                    UserService.add_storage_saved(user_id, in_size - out_size)
                    
            # 5. Thumbnail
            elif action == "img_op_thumb":
                outfile = CONVERTED_DIR / f"img_thumb_{generate_temp_path('png').name}"
                await generate_thumbnail(infile, outfile)
                action_type = "thumbnail"
                
            # 6. EXIF Stripping
            elif action == "img_op_strip":
                outfile = CONVERTED_DIR / f"img_strip_{generate_temp_path('png').name}"
                await remove_metadata(infile, outfile)
                action_type = "strip_metadata"
                
            # 7. Metadata View (Instant task, not uploaded file)
            elif action == "img_op_meta":
                meta = await extract_metadata(infile)
                await status_msg.delete()
                
                meta_str = "ℹ️ **Image Metadata:**\n\n"
                for k, v in meta.items():
                    meta_str += f"🔹 **{k}:** `{v}`\n"
                await query.message.reply_text(meta_str[:4000], parse_mode="Markdown")
                return
                
            # Send result
            if outfile and outfile.exists():
                await status_msg.edit_text("📤 Uploading processed image...")
                with open(outfile, "rb") as f:
                    if outfile.suffix.lower() == ".pdf":
                        await context.bot.send_document(
                            chat_id=chat_id, document=f, filename="image.pdf", caption="📄 PDF page created from image."
                        )
                    else:
                        await context.bot.send_photo(
                            chat_id=chat_id, photo=f, caption=f"🖼 Image Action: {action_type.upper()} complete."
                        )
                await status_msg.delete()
                log_event("CONVERSIONS", f"User {user_id} performed image tool: {action_type}")
            else:
                await status_msg.edit_text("❌ Action failed.")
                
        except Exception as e:
            logger.error(f"Image action failed: {e}")
            await status_msg.edit_text(f"❌ Failed to process image: {str(e)[:50]}")
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

async def handle_image_resize_text(update: Update, context: CallbackContext):
    """Process custom dimensions typed in resize mode."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    state = context.user_data.get("img_state")
    
    if state != "wait_resize":
        return
        
    context.user_data["img_state"] = None
    data = context.user_data.get("image_tool")
    if not data:
        await update.message.reply_text("❌ Session expired. Please re-upload your image.")
        return
        
    text = update.message.text.strip().lower()
    desc = f"Image resize to {text}"
    status_msg = await update.message.reply_text("⏳ Enqueuing resize task...")
    
    async def worker_func():
        await status_msg.edit_text("⚡ Resizing image...")
        infile = None
        outfile = None
        try:
            tg_file = await context.bot.get_file(data["file_id"])
            infile = CONVERTED_DIR / f"img_resize_in_{generate_temp_path('png').name}"
            await tg_file.download_to_drive(custom_path=infile)
            
            # Read current size
            with Image.open(infile) as img:
                w, h = img.size
                
            new_w, new_h = w, h
            if "%" in text:
                pct = int(text.replace("%", ""))
                if pct < 10 or pct > 500:
                    raise ValueError("Percentage must be between 10% and 500%.")
                new_w = int(w * pct / 100)
                new_h = int(h * pct / 100)
            elif "x" in text:
                parts = text.split("x")
                new_w = int(parts[0])
                new_h = int(parts[1])
                if new_w < 10 or new_h < 10 or new_w > 5000 or new_h > 5000:
                    raise ValueError("Width/Height must be between 10px and 5000px.")
            else:
                raise ValueError("Invalid format. Write e.g. '50%' or '800x600'.")
                
            outfile = CONVERTED_DIR / f"img_resize_out_{generate_temp_path('png').name}"
            await resize_image(infile, outfile, new_w, new_h)
            
            await status_msg.edit_text("📤 Uploading resized image...")
            with open(outfile, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=f"📏 Resized from {w}x{h} to {new_w}x{new_h}."
                )
            await status_msg.delete()
            log_event("CONVERSIONS", f"User {user_id} resized image to {new_w}x{new_h}")
        except Exception as e:
            logger.error(f"Image resize failed: {e}")
            await status_msg.edit_text(f"❌ Resize failed: {str(e)[:50]}")
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
