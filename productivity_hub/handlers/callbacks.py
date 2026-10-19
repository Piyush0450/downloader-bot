"""
Central Callback Query Router & Authorization Guard.

Routes all inline keyboard callbacks (menu:*, qr:*, cancel:*, etc.), validates owner_id security
tokens, and renders interactive submenus in the user's active language.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from productivity_hub.handlers.keyboards import (
    parse_callback_data,
    get_main_menu_keyboard,
    get_qr_menu_keyboard,
    get_back_keyboard,
)
from productivity_hub.services.user_service import get_user_service
from productivity_hub.services.queue_service import get_queue_service
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.callbacks")


async def main_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Central router for processing all InlineKeyboardButton callback queries.
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, payload, owner_id = parse_callback_data(data)

    user_service = get_user_service()
    tg_user = query.from_user

    # Fetch user profile for language preference
    user = await user_service.get_or_create_user(tg_user)
    lang = user.language

    # ----------------------------------------------------------------
    # SECURITY CHECK: Verify clicking user is the menu owner
    # ----------------------------------------------------------------
    if owner_id != 0 and tg_user.id != owner_id:
        err_msg = get_text("err_unauthorized_button", lang)
        await query.answer(err_msg, show_alert=True)
        logger.warning(f"Blocked unauthorized button click from user {tg_user.id} on menu owned by {owner_id}.")
        return

    await query.answer()

    # ----------------------------------------------------------------
    # ROUTING LOGIC
    # ----------------------------------------------------------------

    # Helper to safely edit messages without crashing on 'Message is not modified'
    async def safe_edit(text: str, reply_markup=None, parse_mode="Markdown"):
        try:
            await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.warning(f"Error editing message in callback router: {e}")

    # 1. MENU NAVIGATION
    if action == "menu":
        if payload == "main":
            context.user_data.pop("active_mode", None)
            title = get_text("welcome_title", lang)
            body = get_text("welcome_body", lang)
            full_msg = f"{title}\n\n{body}"
            keyboard = get_main_menu_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(text=full_msg, parse_mode="Markdown", reply_markup=keyboard)

        elif payload == "downloader":
            context.user_data["active_mode"] = "downloader"
            title = get_text("title_downloader", lang)
            desc = get_text("desc_downloader", lang)
            keyboard = get_back_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(
                text=f"{title}\n\n{desc}\n\n🔗 *Please send the media link now (YouTube, Instagram, TikTok, etc.):*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif payload == "converter":
            context.user_data["active_mode"] = "converter"
            title = get_text("title_converter", lang)
            desc = get_text("desc_converter", lang)
            keyboard = get_back_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(
                text=f"{title}\n\n{desc}\n\n📁 *Please upload the document or file you want to convert now:*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif payload == "bg_remover":
            context.user_data["active_mode"] = "bg_remover"
            title = get_text("title_bg_remover", lang)
            desc = get_text("desc_bg_remover", lang)
            keyboard = get_back_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(
                text=f"{title}\n\n{desc}\n\n📸 *Please upload or forward the image now:*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif payload == "compressor":
            context.user_data["active_mode"] = "compressor"
            title = get_text("title_compressor", lang)
            desc = get_text("desc_compressor", lang)
            keyboard = get_back_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(
                text=f"{title}\n\n{desc}\n\n📦 *Please upload the file you wish to compress now:*",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif payload == "qr":
            context.user_data.pop("active_mode", None)
            title = get_text("title_qr_menu", lang)
            desc = get_text("desc_qr_menu", lang)
            keyboard = get_qr_menu_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(text=f"{title}\n\n{desc}", parse_mode="Markdown", reply_markup=keyboard)

        elif payload == "help":
            context.user_data.pop("active_mode", None)
            title = get_text("help_title", lang)
            body = get_text("help_body", lang)
            keyboard = get_back_keyboard(owner_id=tg_user.id, lang=lang)
            await safe_edit(text=f"{title}\n\n{body}", parse_mode="Markdown", reply_markup=keyboard)

    # 2. QR TOOLS SUBMENU NAVIGATION
    elif action == "qr":
        if payload == "generator":
            from productivity_hub.handlers.qr_generator import qr_generator_menu_handler
            await qr_generator_menu_handler(update, context)

        elif payload == "scanner":
            context.user_data["active_mode"] = "qr_scanner"
            from productivity_hub.handlers.qr_scanner import qr_scanner_menu_handler
            await qr_scanner_menu_handler(update, context)

    # 3. TASK CANCELLATION
    elif action == "cancel":
        task_id = payload
        queue_svc = get_queue_service()
        cancelled = await queue_svc.cancel_task(task_id, tg_user.id)
        if cancelled:
            await safe_edit(text=f"🚫 Task `{task_id[:8]}` has been cancelled.", parse_mode="Markdown")
        else:
            await query.answer("Could not cancel task (it may have already finished or expired).", show_alert=True)
