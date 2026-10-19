"""
Multi-Language Command & Callback Handlers.

Handles /lang and /language commands, rendering language selection options and saving
preferences in SQLite.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import get_language_keyboard, parse_callback_data, get_main_menu_keyboard
from productivity_hub.services.user_service import get_user_service
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.language")


@protected_handler(operation_type="default")
async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lang and /language commands."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id

    title = get_text("title_lang", lang)
    desc = get_text("desc_lang", lang)
    msg_text = f"{title}\n\n{desc}"

    keyboard = get_language_keyboard(owner_id=user_id, current_lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            text=msg_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )


async def handle_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback queries (e.g., lang:set_en:owner_id)."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, payload, owner_id = parse_callback_data(data)

    # Security check: Ensure clicking user matches owner
    if query.from_user.id != owner_id:
        err_msg = get_text("err_unauthorized_button", "en")
        await query.answer(err_msg, show_alert=True)
        return

    user_service = get_user_service()

    if payload.startswith("set_"):
        new_lang = payload.replace("set_", "").strip()
        await user_service.update_language(owner_id, new_lang)
        
        confirm_text = get_text("lang_changed", new_lang)
        await query.answer(confirm_text, show_alert=False)

        # Re-render main menu in new language
        welcome_title = get_text("welcome_title", new_lang)
        welcome_body = get_text("welcome_body", new_lang)
        full_msg = f"{confirm_text}\n\n{welcome_title}\n\n{welcome_body}"
        keyboard = get_main_menu_keyboard(owner_id=owner_id, lang=new_lang)

        await query.edit_message_text(
            text=full_msg,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
