import asyncio
import re
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.qr_service import generate_qr, scan_qr_image
from services.database_service import ConversionService
from services.security_service import RateLimiter, check_user_access
from utils.helpers import generate_temp_path, cleanup_file
from utils.logger import logger

def parse_vcard_fields(vcard_text: str) -> str:
    """Parse common vCard or MECARD contact fields for user-friendly display."""
    lines = vcard_text.splitlines()
    name = ""
    phone = ""
    email = ""
    
    # 1. Standard vCard
    for line in lines:
        line_clean = line.strip()
        if line_clean.upper().startswith("FN:"):
            name = line_clean[3:]
        elif line_clean.upper().startswith("TEL;"):
            phone = line_clean.split(":")[-1]
        elif line_clean.upper().startswith("EMAIL;"):
            email = line_clean.split(":")[-1]
            
    # 2. MECARD format: MECARD:N:Name;TEL:Phone;EMAIL:Email;;
    if not name and "MECARD:" in vcard_text.upper():
        mecard_data = vcard_text.replace("MECARD:", "").replace("mecard:", "")
        # Parse fields
        for part in mecard_data.split(";"):
            part_clean = part.strip()
            if part_clean.upper().startswith("N:"):
                name = part_clean[2:]
            elif part_clean.upper().startswith("TEL:"):
                phone = part_clean[4:]
            elif part_clean.upper().startswith("EMAIL:"):
                email = part_clean[6:]
                
    if not name and not phone and not email:
        return vcard_text  # Fallback to raw text
        
    return (
        f"👤 **Name:** {name or 'N/A'}\n"
        f"📞 **Phone:** {phone or 'N/A'}\n"
        f"📧 **Email:** {email or 'N/A'}"
    )

async def show_qr_tools_menu(update: Update, context: CallbackContext):
    """Show generator sub-menu."""
    if not await check_user_access(update, context):
        return
        
    keyboard = [
        [
            InlineKeyboardButton("📝 Text / URL", callback_data="qr_btn_text"),
            InlineKeyboardButton("📧 Email", callback_data="qr_btn_email")
        ],
        [
            InlineKeyboardButton("📞 Phone", callback_data="qr_btn_phone"),
            InlineKeyboardButton("📶 WiFi Network", callback_data="qr_btn_wifi")
        ],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "🔳 **QR Code Tools**\n\n"
        "Generate a QR code or scan one by uploading a photo."
    )
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_qr_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "qr_btn_text":
        context.user_data["qr_state"] = "wait_text"
        await query.message.reply_text("✏️ Please send the Text or URL you want to convert into a QR Code:")
    elif action == "qr_btn_email":
        context.user_data["qr_state"] = "wait_email"
        await query.message.reply_text(
            "✏️ Please send email details in this format:\n"
            "`email@example.com, Subject, Body text`"
        )
    elif action == "qr_btn_phone":
        context.user_data["qr_state"] = "wait_phone"
        await query.message.reply_text("✏️ Please send the phone number (with country code):")
    elif action == "qr_btn_wifi":
        context.user_data["qr_state"] = "wait_wifi"
        await query.message.reply_text(
            "✏️ Please send WiFi configuration in this format:\n"
            "`NetworkSSID, Password, Security(WPA/WEP/none)`"
        )

async def handle_qr_input_processing(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    state = context.user_data.get("qr_state")
    if not state:
        return
        
    text = update.message.text
    if not text:
        await update.message.reply_text("❌ Text input cannot be empty.")
        return
        
    context.user_data["qr_state"] = None
    status_msg = await update.message.reply_text("⚙️ Generating QR Code...")
    
    qr_data = ""
    try:
        if state == "wait_text":
            qr_data = text
        elif state == "wait_email":
            parts = [p.strip() for p in text.split(",", 2)]
            if len(parts) >= 1:
                email = parts[0]
                sub = parts[1] if len(parts) > 1 else ""
                body = parts[2] if len(parts) > 2 else ""
                qr_data = f"MATMSG:TO:{email};SUB:{sub};BODY:{body};;"
            else:
                raise ValueError("Invalid Email format.")
        elif state == "wait_phone":
            qr_data = f"tel:{text.replace(' ', '')}"
        elif state == "wait_wifi":
            parts = [p.strip() for p in text.split(",", 2)]
            if len(parts) >= 1:
                ssid = parts[0]
                passwd = parts[1] if len(parts) > 1 else ""
                sec = parts[2].upper() if len(parts) > 2 else "WPA"
                if sec not in ("WPA", "WEP", "NONE"):
                    sec = "WPA"
                qr_data = f"WIFI:S:{ssid};T:{sec};P:{passwd};;"
            else:
                raise ValueError("Invalid WiFi format.")
                
        if not qr_data:
            raise ValueError("Empty QR content.")
            
        qr_bytes = await generate_qr(qr_data)
        await status_msg.delete()
        
        await update.message.reply_photo(
            photo=qr_bytes,
            caption=f"🔳 **QR Code Generated!**\n\n📄 **Encoded Data:**\n`{qr_data}`",
            parse_mode="Markdown"
        )
        ConversionService.log_qr(user_id, "GENERATE")
    except Exception as e:
        logger.error(f"Failed generating QR: {e}")
        await status_msg.edit_text("❌ Failed to generate QR. Make sure details match the requested format.")

async def handle_qr_scan_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    file_id = context.user_data.get("qr_scan_file_id")
    
    if not file_id:
        await query.message.reply_text("❌ Scanned photo expired. Please upload photo again.")
        return
        
    context.user_data.pop("qr_scan_file_id", None)
    status_msg = await query.message.reply_text("🔍 Scanning image for QR codes...")
    
    temp_img = None
    try:
        tg_file = await context.bot.get_file(file_id)
        temp_img = generate_temp_path("png")
        await tg_file.download_to_drive(custom_path=temp_img)
        
        res = await scan_qr_image(temp_img)
        content = res["content"]
        res_type = res["type"]
        
        await status_msg.delete()
        if content:
            # Check contact card type
            if res_type == "CONTACT":
                parsed = parse_vcard_fields(content)
                header = "👤 **QR Contact Card Decoded**"
            elif res_type == "URL":
                parsed = f"🔗 **URL:**\n{content}"
                header = "✅ **QR Code URL Decoded**"
            else:
                parsed = f"📄 **Content:**\n`{content}`"
                header = "✅ **QR Code Decoded**"
                
            await query.message.reply_text(
                f"{header}\n\n{parsed}",
                parse_mode="Markdown"
            )
            ConversionService.log_qr(user_id, "SCAN")
        else:
            await query.message.reply_text("❌ No QR Code could be decoded from this image.")
    except Exception as e:
        logger.error(f"Failed scanning QR: {e}")
        await status_msg.edit_text("❌ Scan failed.")
    finally:
        cleanup_file(temp_img)
