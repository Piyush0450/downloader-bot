"""
Help & User Guide Handler.

Renders feature breakdown and command usage guidelines.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import get_back_keyboard
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.help")


@protected_handler(operation_type="default")
async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    title = get_text("help_title", lang)
    body = get_text("help_body", lang)
    full_msg = f"{title}\n\n{body}"

    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            text=full_msg,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
