"""
Start & Main Menu Handler.

Handles /start and /menu commands, sending a clean welcome message and rendering
the main inline keyboard menu.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import get_main_menu_keyboard
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.start")


@protected_handler(operation_type="default")
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start and /menu commands.
    """
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    welcome_title = get_text("welcome_title", lang)
    welcome_body = get_text("welcome_body", lang)
    full_msg = f"{welcome_title}\n\n{welcome_body}"

    keyboard = get_main_menu_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            text=full_msg,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    logger.info(f"Served main menu to user {user_id}")
