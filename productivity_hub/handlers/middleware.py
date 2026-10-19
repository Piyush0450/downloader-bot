"""
Middleware & Access Control Pre-processor.

Enforces user registration, ban checks, maintenance mode restrictions, and per-user
rate limiting across all Telegram commands, messages, and callback queries.
"""

import functools
import logging
from typing import Callable, Optional
from telegram import Update
from telegram.ext import ContextTypes

from productivity_hub.config.settings import get_settings
from productivity_hub.services.user_service import get_user_service
from productivity_hub.services.admin_service import get_admin_service
from productivity_hub.utils.rate_limiter import get_rate_limiter
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.middleware")


async def validate_user_access(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    operation_type: str = "default"
) -> Optional[object]:
    """
    Validate incoming update against ban status, maintenance mode, and rate limits.

    Args:
        update: Incoming Telegram Update.
        context: Telegram Context.
        operation_type: Type string for rate limiter ('download', 'conversion', 'qr', 'default').

    Returns:
        Optional[User]: User model instance if access is granted, None if request blocked.
    """
    user_service = get_user_service()
    admin_service = get_admin_service()
    settings = get_settings()
    rate_limiter = get_rate_limiter()

    tg_user = update.effective_user
    if not tg_user:
        return None

    user_id = tg_user.id

    # 1. Register or fetch User profile from DB
    user = await user_service.get_or_create_user(tg_user)

    # Check admin privilege
    is_admin = await admin_service.is_admin(user_id)
    if is_admin:
        user.is_admin = True

    # 2. Ban Status Check
    is_banned, ban_reason = await user_service.check_ban_status(user_id)
    if is_banned:
        msg = get_text("err_banned", user.language, reason=ban_reason or "Violation of terms.")
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(msg, parse_mode="Markdown")
        logger.warning(f"Blocked banned user interaction: {user_id}")
        return None

    # 3. Dynamic Maintenance Mode Check
    is_maintenance = await admin_service.is_maintenance_mode()
    if is_maintenance and not is_admin:
        msg = (
            "🚧 <b>Bot is temporarily under maintenance.</b>\nPlease try again later."
            if user.language != "hi" else
            "🚧 <b>बॉट अस्थायी रूप से रखरखाव के अधीन है।</b>\nकृपया बाद में पुनः प्रयास करें।"
        )
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        logger.info(f"Blocked non-admin user during maintenance mode: {user_id}")
        return None

    # 4. Rate Limiter Check (Skip rate limit for owner/admins)
    if not is_admin:
        allowed, wait_time = await rate_limiter.check_rate_limit(user_id, operation_type)
        if not allowed:
            msg = get_text("err_rate_limit", user.language, wait_time=wait_time)
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(msg, parse_mode="Markdown")
            logger.info(f"Rate limited user {user_id} on operation '{operation_type}' ({wait_time}s wait).")
            return None

    return user


def protected_handler(operation_type: str = "default"):
    """
    Decorator for wrapping handler functions with pre-processor access control.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = await validate_user_access(update, context, operation_type)
            if not user:
                return None
            context.user_data["user"] = user
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
