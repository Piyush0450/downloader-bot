"""
Admin Panel & Security Handler module.

Implements the hidden /admin command dashboard, security checks, user ban/unban commands,
maintenance mode toggling, system statistics, disk cleanup, and broadcast messaging system.
"""

import logging
from typing import Dict, Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from productivity_hub.services.admin_service import get_admin_service
from productivity_hub.database.database import get_db
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.admin")
admin_svc = get_admin_service()



def get_admin_dashboard_keyboard(owner_id: int) -> InlineKeyboardMarkup:
    """Generate the main admin dashboard inline keyboard layout."""
    keyboard = [
        [
            InlineKeyboardButton("🖥 System Status", callback_data=f"adm:sys_status:{owner_id}"),
            InlineKeyboardButton("👥 Users", callback_data=f"adm:users:{owner_id}")
        ],
        [
            InlineKeyboardButton("📊 Statistics", callback_data=f"adm:stats:{owner_id}"),
            InlineKeyboardButton("💾 Storage", callback_data=f"adm:storage:{owner_id}")
        ],
        [
            InlineKeyboardButton("⬇ Downloads", callback_data=f"adm:downloads:{owner_id}"),
            InlineKeyboardButton("🔄 Conversions", callback_data=f"adm:conversions:{owner_id}")
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data=f"adm:broadcast:{owner_id}"),
            InlineKeyboardButton("📜 System Logs", callback_data=f"adm:logs:{owner_id}")
        ],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data=f"adm:ban_prompt:{owner_id}"),
            InlineKeyboardButton("✅ Unban User", callback_data=f"adm:unban_prompt:{owner_id}")
        ],
        [
            InlineKeyboardButton("🧹 Run Cleanup", callback_data=f"adm:cleanup:{owner_id}"),
            InlineKeyboardButton("🔧 Toggle Maintenance", callback_data=f"adm:maint_toggle:{owner_id}")
        ],
        [
            InlineKeyboardButton("📦 Dependencies", callback_data=f"adm:deps:{owner_id}"),
            InlineKeyboardButton("❌ Close Panel", callback_data=f"adm:close:{owner_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle hidden /admin command.
    Checks admin authorization strictly using Telegram user_id.
    """
    user = update.effective_user
    if not user:
        return

    user_id = user.id
    db = get_db()

    # Admin Authorization Check
    is_authorized = await admin_svc.is_admin(user_id)
    if not is_authorized:
        # Security audit log
        await db.add_audit_log(
            "WARNING",
            "security",
            f"Unauthorized /admin command access attempt by user {user_id} (@{user.username})",
            user_id=user_id
        )
        logger.warning(f"Unauthorized /admin access attempt by user_id {user_id}")
        await update.effective_message.reply_text(
            "⛔ <b>Access Denied</b>\n\n"
            "You do not have administrative privileges to access this control panel. "
            "This unauthorized attempt has been logged for security audit.",
            parse_mode="HTML"
        )
        return

    # Check maintenance mode status
    is_maint = await admin_svc.is_maintenance_mode()
    maint_status = "🔴 ACTIVE (Maintenance)" if is_maint else "🟢 ONLINE (Normal)"

    dashboard_text = (
        f"👑 <b>Productivity Hub - Admin Control Panel</b>\n\n"
        f"<b>Admin:</b> {user.first_name} (<code>{user_id}</code>)\n"
        f"<b>Bot Status:</b> {maint_status}\n\n"
        f"Select an administrative tool below:"
    )

    await update.effective_message.reply_text(
        dashboard_text,
        parse_mode="HTML",
        reply_markup=get_admin_dashboard_keyboard(user_id)
    )


async def ban_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ban <user_id> [reason] or by replying to a user's message."""
    user = update.effective_user
    if not user or not await admin_svc.is_admin(user.id):
        return

    target_id = None
    reason = "Violation of bot terms"

    # Check if command is a reply to another message
    if update.message and update.message.reply_to_message:
        replied_msg = update.message.reply_to_message
        if replied_msg.from_user:
            target_id = replied_msg.from_user.id
            if context.args:
                reason = " ".join(context.args)

    # Else parse user_id from args
    elif context.args and len(context.args) > 0:
        try:
            target_id = int(context.args[0])
            if len(context.args) > 1:
                reason = " ".join(context.args[1:])
        except ValueError:
            await update.effective_message.reply_text("❌ Usage: `/ban <user_id> [reason]`", parse_mode="Markdown")
            return

    if not target_id:
        await update.effective_message.reply_text(
            "❌ Please specify a target user ID or reply to a user's message:\n`/ban <user_id> [reason]`",
            parse_mode="Markdown"
        )
        return

    success, msg = await admin_svc.ban_user(target_id, reason, user.id)
    await update.effective_message.reply_text(f"{'✅' if success else '❌'} {msg}")


async def unban_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unban <user_id>."""
    user = update.effective_user
    if not user or not await admin_svc.is_admin(user.id):
        return

    if not context.args or len(context.args) == 0:
        await update.effective_message.reply_text("❌ Usage: `/unban <user_id>`", parse_mode="Markdown")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid user ID integer.", parse_mode="Markdown")
        return

    success, msg = await admin_svc.unban_user(target_id, user.id)
    await update.effective_message.reply_text(f"{'✅' if success else '❌'} {msg}")


async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route admin dashboard button callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not await admin_svc.is_admin(user_id):
        await query.answer("⛔ Access Denied.", show_alert=True)
        return

    parts = query.data.split(":")
    if len(parts) < 2:
        return

    action = parts[1]
    await query.answer()

    if action == "sys_status":
        status = await admin_svc.get_system_status()
        text = (
            f"🖥 <b>System Diagnostics</b>\n\n"
            f"⏱ <b>Uptime:</b> <code>{status['uptime']}</code>\n"
            f"💻 <b>CPU:</b> <code>{status['cpu']}</code>\n"
            f"🧠 <b>RAM:</b> <code>{status['ram']}</code>\n"
            f"📥 <b>Queue Size:</b> <code>{status['queue_size']}</code>\n"
            f"⚡ <b>Active Tasks:</b> <code>{status['active_tasks']}</code>\n"
            f"💾 <b>Storage:</b> <code>{status['storage']}</code>\n\n"
            f"🎥 <b>FFmpeg:</b> <code>{status['ffmpeg']}</code>\n"
            f"🎬 <b>yt-dlp:</b> <code>{status['ytdlp']}</code>\n"
            f"🐍 <b>Python:</b> <code>{status['python_version']}</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "users":
        u_summary = await admin_svc.get_users_summary()
        text = (
            f"👥 <b>User Management Summary</b>\n\n"
            f"• <b>Total Registered Users:</b> <code>{u_summary['total_users']}</code>\n"
            f"• <b>Banned Users:</b> <code>{u_summary['banned_users']}</code>\n"
            f"• <b>Admin Accounts:</b> <code>{u_summary['admin_count']}</code>\n\n"
            f"<i>To ban or unban a user, use:</i>\n"
            f"<code>/ban &lt;user_id&gt; [reason]</code>\n"
            f"<code>/unban &lt;user_id&gt;</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "stats":
        stats = await admin_svc.get_all_statistics()
        text = (
            f"📊 <b>Global Application Statistics</b>\n\n"
            f"⚙️ <b>Total Tasks Submitted:</b> <code>{stats['total_tasks']}</code>\n"
            f"✅ <b>Completed Tasks:</b> <code>{stats['completed_tasks']}</code>\n"
            f"❌ <b>Failed Tasks:</b> <code>{stats['failed_tasks']}</code>\n\n"
            f"⬇️ <b>Media Downloads:</b> <code>{stats['total_downloads']}</code>\n"
            f"🔄 <b>File Conversions:</b> <code>{stats['total_conversions']}</code>\n"
            f"📱 <b>QR Code Events:</b> <code>{stats['total_qr']}</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "storage":
        st = await admin_svc.get_storage_details()
        text = (
            f"💾 <b>Disk & Storage Metrics</b>\n\n"
            f"• <b>Total Space:</b> <code>{st['total_gb']:.2f} GB</code>\n"
            f"• <b>Used Space:</b> <code>{st['used_gb']:.2f} GB ({st['pct_used']:.1f}%)</code>\n"
            f"• <b>Free Space:</b> <code>{st['free_gb']:.2f} GB</code>\n"
            f"• <b>Temp Folder Size:</b> <code>{st['temp_mb']:.2f} MB</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "maint_toggle":
        new_state = await admin_svc.toggle_maintenance_mode()
        state_str = "🔴 ACTIVE (Maintenance)" if new_state else "🟢 ONLINE (Normal)"
        await query.edit_message_text(
            f"🔧 <b>Maintenance Mode Status Changed!</b>\n\nNew State: <b>{state_str}</b>",
            parse_mode="HTML",
            reply_markup=get_admin_dashboard_keyboard(user_id)
        )

    elif action == "cleanup":
        res = await admin_svc.trigger_manual_cleanup()
        freed_mb = res.get("freed_bytes", 0) / (1024 * 1024)
        deleted_count = res.get("deleted_files", 0)
        text = (
            f"🧹 <b>Manual Cleanup Cycle Complete</b>\n\n"
            f"• <b>Deleted Stale Files:</b> <code>{deleted_count}</code>\n"
            f"• <b>Reclaimed Disk Space:</b> <code>{freed_mb:.2f} MB</code>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "logs":
        logs = await admin_svc.get_recent_logs(limit=10)
        log_lines = []
        for l in logs:
            log_lines.append(f"• <code>[{l['level']}]</code> {l['message'][:60]} ({l['created_at']})")
        
        log_text = "\n".join(log_lines) if log_lines else "<i>No recent audit log entries.</i>"
        text = f"📜 <b>Recent Audit & Security Logs</b>\n\n{log_text}"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "broadcast":
        context.user_data["pending_broadcast"] = True
        await query.edit_message_text(
            "📢 <b>Broadcast Message Builder</b>\n\n"
            "Please send the announcement text message you wish to broadcast to all registered users.\n\n"
            "<i>(Type /cancel to cancel broadcast)</i>",
            parse_mode="HTML"
        )

    elif action == "ban_prompt":
        await query.edit_message_text(
            "🚫 <b>Ban User Tool</b>\n\n"
            "To ban a user, send command:\n"
            "<code>/ban &lt;user_id&gt; [reason]</code>\n\n"
            "or reply to any message sent by that user with <code>/ban [reason]</code>.",
            parse_mode="HTML",
            reply_markup=get_admin_dashboard_keyboard(user_id)
        )

    elif action == "unban_prompt":
        await query.edit_message_text(
            "✅ <b>Unban User Tool</b>\n\n"
            "To unban a user, send command:\n"
            "<code>/unban &lt;user_id&gt;</code>",
            parse_mode="HTML",
            reply_markup=get_admin_dashboard_keyboard(user_id)
        )

    elif action == "deps":
        from productivity_hub.utils.dependency_checker import get_dependency_checker
        diagnostics = get_dependency_checker().get_full_diagnostics()
        dep_lines = ["📦 <b>System & Library Diagnostics</b>\n"]
        for k, v in diagnostics.items():
            icon = "✅" if v.available else "❌"
            dep_lines.append(f"{icon} <b>{k}</b>: <code>{v.details}</code>")
        await query.edit_message_text("\n".join(dep_lines), parse_mode="HTML", reply_markup=get_admin_dashboard_keyboard(user_id))

    elif action == "close":
        await query.delete_message()


async def handle_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text message input when admin is in broadcast mode."""
    user = update.effective_user
    if not user or not await admin_svc.is_admin(user.id):
        return

    if not context.user_data.get("pending_broadcast"):
        return

    if not update.message or not update.message.text:
        return

    b_text = update.message.text.strip()
    if b_text == "/cancel":
        context.user_data["pending_broadcast"] = False
        await update.message.reply_text("❌ Broadcast cancelled.")
        return

    # Clear pending flag & store broadcast content
    context.user_data["pending_broadcast"] = False
    context.user_data["broadcast_content"] = b_text

    # Show preview keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm & Send Broadcast", callback_data=f"adm_bc:confirm:{user.id}"),
            InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"adm_bc:cancel:{user.id}")
        ]
    ])

    await update.message.reply_text(
        f"📢 <b>Broadcast Preview:</b>\n\n"
        f"Announcement:\n"
        f"----------------------------\n"
        f"{b_text}\n"
        f"----------------------------\n\n"
        f"Click Confirm to begin broadcasting to all registered users.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def broadcast_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute or cancel broadcast after admin confirmation."""
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not await admin_svc.is_admin(user_id):
        await query.answer("⛔ Access Denied.", show_alert=True)
        return

    action = query.data.split(":")[1]
    await query.answer()

    if action == "confirm":
        b_content = context.user_data.pop("broadcast_content", None)
        if not b_content:
            await query.edit_message_text("⚠️ Broadcast session expired.")
            return

        status_msg = await query.edit_message_text("🚀 <b>Broadcasting message to users...</b>", parse_mode="HTML")

        res = await admin_svc.broadcast_message(context.bot, b_content, user_id)
        result_text = (
            f"✅ <b>Broadcast Completed!</b>\n\n"
            f"• <b>Total Users Target:</b> <code>{res['total']}</code>\n"
            f"• <b>Successfully Delivered:</b> <code>{res['sent']}</code>\n"
            f"• <b>Blocked by Users:</b> <code>{res['blocked']}</code>\n"
            f"• <b>Failed / Invalid:</b> <code>{res['failed']}</code>"
        )
        await status_msg.edit_text(result_text, parse_mode="HTML")

    elif action == "cancel":
        context.user_data.pop("broadcast_content", None)
        await query.edit_message_text("❌ Broadcast cancelled.")


def register_admin_handlers(application) -> None:
    """Register admin panel handlers with PTB application."""
    application.add_handler(CommandHandler("admin", admin_command_handler))
    application.add_handler(CommandHandler("ban", ban_command_handler))
    application.add_handler(CommandHandler("unban", unban_command_handler))
    application.add_handler(CallbackQueryHandler(admin_callback_router, pattern=r"^adm:"))
    application.add_handler(CallbackQueryHandler(broadcast_action_callback, pattern=r"^adm_bc:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_input), group=-1)
