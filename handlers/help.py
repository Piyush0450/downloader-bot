from telegram import Update
from telegram.ext import CallbackContext
from services.security_service import check_user_access

async def help_command(update: Update, context: CallbackContext):
    """Help command handler displaying instructions for different categories."""
    if not await check_user_access(update, context):
        return
        
    help_text = (
        "❓ **Productivity Hub Bot Help**\n\n"
        "This bot operates via buttons, menus, and dynamic content detection. "
        "Simply send a link, image, or document, and the bot will analyze it to suggest options!\n\n"
        "💡 **Categories:**\n"
        "• **Downloader:** Just paste media links from YouTube, TikTok, Instagram, Twitter, etc.\n"
        "• **Converter:** Upload a document (DOCX, PDF, XLSX, ODS, etc.) or audio/video file.\n"
        "• **Image Tools:** Upload photos to resize, crop, rotate, generate thumbnails, or clean EXIF metadata.\n"
        "• **QR Tools:** Scan QR codes by sending photos or choose options in the menu to create QRs.\n"
        "• **Compressor:** Send PDFs or images and choose compression quality levels.\n"
        "• **Text Tools:** Send any text message to format JSON, count words, or transform casing."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")
