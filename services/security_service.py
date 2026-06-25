import time
from pathlib import Path
from collections import defaultdict
from config.settings import TEMP_DIR, RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_REQUESTS, SUSPICIOUS_WARN_THRESHOLD, SUSPICIOUS_BAN_THRESHOLD
from services.database_service import log_event, UserService, AdminService
from utils.logger import logger, security_logger
from telegram import Update
from telegram.ext import CallbackContext

_request_history = defaultdict(list)

class RateLimiter:
    @staticmethod
    def is_rate_limited(user_id: int) -> bool:
        """Check if a user has exceeded the rate limit."""
        now = time.time()
        user_history = _request_history[user_id]
        
        # Keep only requests within the active window
        active_requests = [t for t in user_history if now - t < RATE_LIMIT_WINDOW]
        _request_history[user_id] = active_requests
        
        if len(active_requests) >= RATE_LIMIT_MAX_REQUESTS:
            logger.warning(f"User {user_id} rate limited.")
            security_logger.warning(f"User {user_id} hit rate limit threshold (Spam).")
            log_event("UNAUTHORIZED", f"User {user_id} hit rate limit threshold.")
            return True
            
        _request_history[user_id].append(now)
        return False

def record_unauthorized_attempt(user_id: int) -> bool:
    """Record an unauthorized attempt. If attempts >= 5, automatically ban the user.
    Returns True if the user has been banned.
    """
    if AdminService.is_admin(user_id):
        return False
    AdminService.track_suspicious(user_id)
    attempts = AdminService.get_suspicious(user_id)
    security_logger.warning(f"Unauthorized admin access by user {user_id}. Attempt count: {attempts}")
    if attempts >= SUSPICIOUS_BAN_THRESHOLD:
        UserService.ban_user(user_id)
        logger.error(f"User {user_id} automatically banned due to {attempts} suspicious attempts.")
        security_logger.error(f"User {user_id} auto-banned due to suspicious attempts.")
        log_event("ADMIN", f"Auto-banned user {user_id} due to suspicious attempts.")
        return True
    return False

async def record_suspicious_event(update: Update, context: CallbackContext, reason: str):
    """Record suspicious activity, warn the user, or permanently ban them based on thresholds."""
    user = update.effective_user
    if not user:
        return
        
    user_id = user.id
    if AdminService.is_admin(user_id):
        return
    AdminService.track_suspicious(user_id)
    attempts = AdminService.get_suspicious(user_id)
    
    security_logger.warning(
        f"Suspicious activity by user {user_id} ({user.first_name}): {reason} "
        f"(Count: {attempts})"
    )
    log_event("SUSPICIOUS", f"User {user_id} triggered: {reason} (Count: {attempts})")
    
    if attempts >= SUSPICIOUS_BAN_THRESHOLD:
        UserService.ban_user(user_id)
        logger.error(f"User {user_id} auto-banned after {attempts} security events.")
        security_logger.error(f"User {user_id} auto-banned.")
        log_event("ADMIN", f"System auto-banned user {user_id} due to suspicious attempts.")
        
        ban_msg = "❌ **Access Revoked**\n\nYour account has been permanently banned due to security policy violations."
        if update.message:
            await update.message.reply_text(ban_msg, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.message.reply_text(ban_msg, parse_mode="Markdown")
            
    elif attempts >= SUSPICIOUS_WARN_THRESHOLD:
        warn_msg = (
            f"⚠️ **Security Warning**\n\nYour account has flagged suspicious operations: *{reason}*.\n"
            f"Repeated policy violations will lead to a permanent ban."
        )
        if update.message:
            await update.message.reply_text(warn_msg, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.message.reply_text(warn_msg, parse_mode="Markdown")

def is_safe_path(path: Path, base_dir: Path = TEMP_DIR) -> bool:
    """Ensure the path resolved is strictly under the base directory (no path traversal)."""
    try:
        resolved_path = Path(path).resolve()
        resolved_base = Path(base_dir).resolve()
        return resolved_base in resolved_path.parents or resolved_path == resolved_base
    except Exception as e:
        logger.error(f"Path safety check failed for {path}: {e}")
        return False

async def check_user_access(update, context) -> bool:
    """Check if the user is banned or the bot is in maintenance mode.
    Also registers or updates the user in the database.
    """
    user = update.effective_user
    if not user:
        return False
        
    user_id = user.id
    
    # 1. Create or update user
    db_user = UserService.get_or_create_user(user_id, user.username, user.first_name)
    
    # 2. Check if user is banned
    if db_user.get('is_banned'):
        if update.message:
            await update.message.reply_text("❌ Your account is banned from using this bot.")
        elif update.callback_query:
            await update.callback_query.answer("❌ You are banned.", show_alert=True)
        return False
        
    # 3. Check maintenance mode
    is_maint = context.bot_data.get("maintenance_mode", False)
    if is_maint and not AdminService.is_admin(user_id):
        maint_msg = "🚧 **Maintenance Mode Enabled**\n\nPlease try again later."
        if update.message:
            await update.message.reply_text(maint_msg, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.answer("🚧 Bot is in maintenance.", show_alert=True)
        return False
        
    UserService.update_last_seen(user_id)
    return True

