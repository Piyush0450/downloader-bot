"""
QR Code Generator Handler.

Presents category choices (Text, URL, Contact, Wi-Fi, Calendar, SMS, Payment),
captures structured user input, validates payloads, and delivers generated QR images.
"""

import logging
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import parse_callback_data, get_back_keyboard
from productivity_hub.services.qr_generation_service import get_qr_generation_service, QRGenerationError
from productivity_hub.services.cleanup_service import safe_delete_file
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.qr_generator")

# Tracks active QR generator state: user_id -> category string
ACTIVE_QR_GENERATOR_MODE: Dict[int, str] = {}


@protected_handler(operation_type="default")
async def qr_generator_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show QR generator category selection menu."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Website / URL", callback_data=f"qrgen_cat:url:{user_id}"),
            InlineKeyboardButton("📝 Plain Text", callback_data=f"qrgen_cat:text:{user_id}")
        ],
        [
            InlineKeyboardButton("📶 Wi-Fi Network", callback_data=f"qrgen_cat:wifi:{user_id}"),
            InlineKeyboardButton("👤 Contact (vCard)", callback_data=f"qrgen_cat:vcard:{user_id}")
        ],
        [
            InlineKeyboardButton("💬 SMS Message", callback_data=f"qrgen_cat:sms:{user_id}"),
            InlineKeyboardButton("📅 Calendar Event", callback_data=f"qrgen_cat:event:{user_id}")
        ],
        [
            InlineKeyboardButton("💳 Payment Link (UPI)", callback_data=f"qrgen_cat:payment:{user_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:qr:{user_id}")
        ]
    ])

    title = get_text("title_qr_generator", lang)
    desc = get_text("desc_qr_generator", lang)
    prompt_text = f"{title}\n\n{desc}\n\n👇 *Select the QR payload category to generate:*"

    if update.callback_query:
        await update.callback_query.edit_message_text(text=prompt_text, parse_mode="Markdown", reply_markup=keyboard)
    elif update.effective_message:
        await update.effective_message.reply_text(text=prompt_text, parse_mode="Markdown", reply_markup=keyboard)


async def handle_qr_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle selection of QR category."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, category, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    await query.answer()
    ACTIVE_QR_GENERATOR_MODE[user_id] = category

    instructions = {
        "url": "🌐 *Enter Website URL:*\nPlease send a full URL (e.g., `https://example.com`)",
        "text": "📝 *Enter Plain Text:*\nPlease send the text content you wish to encode into a QR code:",
        "wifi": (
            "📶 *Enter Wi-Fi Details:*\n"
            "Format: `SSID,Password,Security`\n"
            "Example: `MyHomeNetwork,SecretPass123,WPA`\n"
            "*(If open network with no password, use: `GuestWiFi,,nopass`)*"
        ),
        "vcard": (
            "👤 *Enter Contact Information:*\n"
            "Format: `Name,Phone,Email,Organization`\n"
            "Example: `John Doe,+1234567890,john@example.com,Acme Corp`"
        ),
        "sms": (
            "💬 *Enter SMS Details:*\n"
            "Format: `PhoneNumber,MessageText`\n"
            "Example: `+1234567890,Hello from Productivity Hub!`"
        ),
        "event": (
            "📅 *Enter Calendar Event:*\n"
            "Format: `Title,YYYYMMDDTHHMMSSZ,Location,Description`\n"
            "Example: `Team Meeting,20261101T090000Z,Conference Room,Quarterly Sync`"
        ),
        "payment": (
            "💳 *Enter UPI or Payment URI:*\n"
            "Format: `UPI_ID,Name,Amount` or raw URI\n"
            "Example: `username@bank,John Doe,250` or `upi://pay?pa=...`"
        ),
    }

    prompt = instructions.get(category, "Please enter content to encode:")
    keyboard = get_back_keyboard(owner_id=user_id)
    await query.edit_message_text(text=prompt, parse_mode="Markdown", reply_markup=keyboard)


async def process_qr_generation_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Process incoming user text if user is in an active QR generator flow.
    Returns True if handled, False otherwise.
    """
    if not update.effective_message or not update.effective_message.text:
        return False

    user_id = update.effective_user.id
    category = ACTIVE_QR_GENERATOR_MODE.get(user_id)
    if not category:
        return False

    raw_text = update.effective_message.text.strip()
    qr_svc = get_qr_generation_service()

    payload = raw_text
    display_type = category.upper()

    try:
        # Build category-specific payloads
        if category == "wifi":
            parts = [p.strip() for p in raw_text.split(",")]
            ssid = parts[0]
            password = parts[1] if len(parts) > 1 else ""
            security = parts[2] if len(parts) > 2 else "WPA"
            payload = qr_svc.format_wifi_payload(ssid=ssid, password=password, security=security)
            display_type = f"Wi-Fi ({ssid})"

        elif category == "vcard":
            parts = [p.strip() for p in raw_text.split(",")]
            name = parts[0]
            phone = parts[1] if len(parts) > 1 else ""
            email = parts[2] if len(parts) > 2 else ""
            org = parts[3] if len(parts) > 3 else ""
            payload = qr_svc.format_vcard_payload(name=name, phone=phone, email=email, organization=org)
            display_type = f"Contact ({name})"

        elif category == "sms":
            parts = [p.strip() for p in raw_text.split(",", 1)]
            phone = parts[0]
            msg = parts[1] if len(parts) > 1 else ""
            payload = qr_svc.format_sms_payload(phone=phone, message=msg)
            display_type = f"SMS ({phone})"

        elif category == "event":
            parts = [p.strip() for p in raw_text.split(",")]
            title = parts[0]
            dtstart = parts[1] if len(parts) > 1 else ""
            location = parts[2] if len(parts) > 2 else ""
            desc = parts[3] if len(parts) > 3 else ""
            payload = qr_svc.format_event_payload(title=title, start_datetime=dtstart, location=location, description=desc)
            display_type = f"Event ({title})"

        elif category == "payment":
            if not raw_text.startswith("upi://") and "@" in raw_text:
                parts = [p.strip() for p in raw_text.split(",")]
                upi_id = parts[0]
                name = parts[1] if len(parts) > 1 else ""
                amount = parts[2] if len(parts) > 2 else ""
                payload = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
            display_type = "UPI Payment"

        status_msg = await update.effective_message.reply_text("⏳ *Generating high-contrast QR code...*", parse_mode="Markdown")

        img_path = None
        try:
            img_path, p_type = await qr_svc.generate_qr_image(payload, payload_type=category, user_id=user_id)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to QR Tools", callback_data=f"menu:qr:{user_id}")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data=f"menu:main:{user_id}")]
            ])

            # Upload must finish before local file is deleted
            with open(img_path, "rb") as photo_file:
                await update.effective_message.reply_photo(
                    photo=photo_file,
                    caption=f"✅ *QR Code Generated!*\n📂 *Payload Type:* `{display_type}`\nGenerated via Productivity Hub",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )

            await status_msg.delete()
            return True
        finally:
            if img_path:
                safe_delete_file(img_path, log_msg="after QR image delivery")
            ACTIVE_QR_GENERATOR_MODE.pop(user_id, None)

    except Exception as e:
        logger.error(f"Failed to generate QR from input: {e}")
        await update.effective_message.reply_text(f"❌ *Failed to generate QR code:* {e}", parse_mode="Markdown")
        return True


# Alias for backward and cross-module compatibility
process_qr_text_input = process_qr_generation_text


def register_qr_generator_handlers(application) -> None:
    """Register QR generator command and callback handlers."""
    application.add_handler(CommandHandler("qr", qr_generator_menu_handler))
    application.add_handler(CommandHandler("qrgen", qr_generator_menu_handler))
    application.add_handler(CallbackQueryHandler(handle_qr_category_callback, pattern=r"^qrgen_cat:"))
