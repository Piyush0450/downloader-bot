from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from services.security_service import check_user_access

async def start_command(update: Update, context: CallbackContext):
    """Start command handler displaying introductory messages and category menus."""
    if not await check_user_access(update, context):
        return
        
    first_name = update.effective_user.first_name
    
    # Message 1: Greeting
    msg1 = (
        f"👋 Hello {first_name}\n\n"
        f"Welcome to Productivity Hub Bot.\n\n"
        f"Your all-in-one toolkit for downloading, converting, compressing, and managing files."
    )
    
    # Message 2: Available commands
    msg2 = (
        f" Available commands:\n\n"
        f"/start - Start the bot & show main menu\n"
        f"/help - View documentation and guides\n"
        f"/stats - View personal statistics\n"
        f"/history - View recent action history\n"
        f"/lang - Change interface language"
    )
    
    # Message 3: Main menu buttons
    msg3 = "📥 **Main Menu**\nChoose a utility category:"
    
    keyboard = [
        [
            InlineKeyboardButton("📥 Downloader", callback_data="menu_dl"),
            InlineKeyboardButton("📄 Converter", callback_data="menu_conv")
        ],
        [
            InlineKeyboardButton("🖼 Image Tools", callback_data="menu_img"),
            InlineKeyboardButton("🔳 QR Tools", callback_data="menu_qr")
        ],
        [
            InlineKeyboardButton("📦 Compressor", callback_data="menu_comp"),
            InlineKeyboardButton("📝 Text Tools", callback_data="menu_text")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg1)
    await update.message.reply_text(msg2)
    await update.message.reply_text(msg3, reply_markup=reply_markup, parse_mode="Markdown")
