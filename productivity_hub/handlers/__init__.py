"""
Handlers Subpackage Registration Module.

Registers command, message, callback query, and media/document handlers with the
python-telegram-bot Application instance for all 6 primary modules:
1. Universal Media Downloader
2. Universal File Converter
3. Image Background Remover
4. Universal File Compressor
5. QR Code Generator
6. QR Code Scanner
plus Admin Dashboard, Health, and Language settings.
"""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

from productivity_hub.handlers.start import start_command_handler
from productivity_hub.handlers.help import help_command_handler
from productivity_hub.handlers.language import language_command_handler, handle_language_callback
from productivity_hub.handlers.downloader import (
    download_command_handler,
    handle_download_format_callback,
    handle_download_cancel_callback,
    handle_download_retry_callback,
)
from productivity_hub.handlers.converter import convert_command_handler, handle_conversion_format_callback
from productivity_hub.handlers.background_remover import bg_remover_command_handler
from productivity_hub.handlers.compressor import compressor_command_handler, handle_compression_level_callback
from productivity_hub.handlers.qr_generator import qr_generator_menu_handler, handle_qr_category_callback
from productivity_hub.handlers.qr_scanner import qr_scanner_menu_handler
from productivity_hub.handlers.admin import register_admin_handlers
from productivity_hub.handlers.callbacks import main_callback_router
from productivity_hub.handlers.media_dispatcher import (
    unified_photo_handler,
    unified_document_handler,
    unified_text_handler,
    handle_image_action_callback,
)

logger = logging.getLogger("productivity_hub.handlers")


def register_handlers(application: Application) -> None:
    """
    Register all Telegram bot command, callback, document, and media handlers.

    Args:
        application: Active Telegram bot Application instance.
    """
    logger.info("Registering Telegram bot handlers...")

    # 1. Admin Handlers (Admin dashboard, ban, unban, broadcast, diagnostics)
    register_admin_handlers(application)

    # 2. Command Handlers
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("menu", start_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("lang", language_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))

    # Module commands
    application.add_handler(CommandHandler("download", download_command_handler))
    application.add_handler(CommandHandler("convert", convert_command_handler))
    application.add_handler(CommandHandler("bg", bg_remover_command_handler))
    application.add_handler(CommandHandler("background", bg_remover_command_handler))
    application.add_handler(CommandHandler("compress", compressor_command_handler))
    application.add_handler(CommandHandler("qr", qr_generator_menu_handler))
    application.add_handler(CommandHandler("qrgen", qr_generator_menu_handler))
    application.add_handler(CommandHandler("scan", qr_scanner_menu_handler))
    application.add_handler(CommandHandler("qrscan", qr_scanner_menu_handler))

    # 3. Callback Query Handlers (Specific patterns first)
    application.add_handler(CallbackQueryHandler(handle_language_callback, pattern=r"^lang:"))
    application.add_handler(CallbackQueryHandler(handle_download_format_callback, pattern=r"^dlfmt:"))
    application.add_handler(CallbackQueryHandler(handle_download_cancel_callback, pattern=r"^dl_cancel:"))
    application.add_handler(CallbackQueryHandler(handle_download_retry_callback, pattern=r"^dl_retry:"))
    application.add_handler(CallbackQueryHandler(handle_conversion_format_callback, pattern=r"^convfmt:"))
    application.add_handler(CallbackQueryHandler(handle_compression_level_callback, pattern=r"^cmp_lvl:"))
    application.add_handler(CallbackQueryHandler(handle_qr_category_callback, pattern=r"^qrgen_cat:"))
    application.add_handler(CallbackQueryHandler(handle_image_action_callback, pattern=r"^img_act:"))
    application.add_handler(CallbackQueryHandler(main_callback_router))

    # 4. Message Handlers (Photos, Documents, Text)
    application.add_handler(MessageHandler(filters.PHOTO, unified_photo_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, unified_document_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unified_text_handler))

    # 5. Global Exception Handler
    async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Unhandled exception while processing update: {context.error}", exc_info=context.error)
        if isinstance(update, Update):
            if update.callback_query:
                try:
                    await update.callback_query.answer("⚠️ An error occurred. Please try again.", show_alert=True)
                except Exception:
                    pass
            elif update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "⚠️ <b>An error occurred while processing your request.</b>\nPlease try again in a few moments.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    application.add_error_handler(global_error_handler)

    logger.info("All handlers registered successfully.")


__all__ = ["register_handlers"]
