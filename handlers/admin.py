import time
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.database_service import (
    log_event, UserService, AdminService, StatisticsService, SystemStateService
)
from services.security_service import record_unauthorized_attempt
from services.queue_service import get_monitoring_stats
from services.backup_service import run_backup, BACKUPS_DIR
from utils.helpers import cleanup_temp_directories, format_size
from utils.logger import logger, admin_logger, LOGS_DIR

def check_admin(user_id: int) -> bool:
    from config.settings import OWNER_ID
    return AdminService.is_admin(user_id) is not None or user_id == OWNER_ID

async def show_admin_console(update: Update, context: CallbackContext):
    """Admin entrypoint dashboard."""
    user_id = update.effective_user.id
    
    if not check_admin(user_id):
        banned = record_unauthorized_attempt(user_id)
        msg = "⚠️ **Unauthorized Access**\n\nThis command is restricted. Repeated attempts may result in a permanent ban."
        if banned:
            msg = "❌ **Access Revoked**\n\nYour account has been permanently banned due to repeated unauthorized access attempts."
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
        
    keyboard = [
        [
            InlineKeyboardButton("👥 Users", callback_data="adm_users_list"),
            InlineKeyboardButton("📊 Statistics", callback_data="adm_global_stats")
        ],
        [
            InlineKeyboardButton("📥 Downloads", callback_data="adm_downloads"),
            InlineKeyboardButton("📄 Conversions", callback_data="adm_conversions")
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast_prompt"),
            InlineKeyboardButton("📝 Logs", callback_data="adm_logs_menu")
        ],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_prompt"),
            InlineKeyboardButton("✅ Unban User", callback_data="adm_unban_prompt")
        ],
        [
            InlineKeyboardButton("💾 Storage", callback_data="adm_storage_menu"),
            InlineKeyboardButton("⚙ Maintenance", callback_data="adm_run_maint")
        ],
        [
            InlineKeyboardButton("🧹 Cleanup", callback_data="adm_run_cleanup"),
            InlineKeyboardButton("❌ Close Dashboard", callback_data="adm_close")
        ]
    ]
    
    maint_status = "ENABLED 🛑" if context.bot_data.get("maintenance_mode") else "DISABLED 🟢"
    text = (
        f"🛠 **Productivity Hub Dashboard**\n\n"
        f"⚙️ **System Maintenance:** {maint_status}\n"
        f"Select an operation below:"
    )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_admin_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not check_admin(user_id):
        await query.message.reply_text("❌ Unauthorized.")
        return
        
    action = query.data
    
    if action == "adm_main":
        await show_admin_console(update, context)
        return
        
    elif action == "adm_close":
        await query.message.edit_text("🔒 **Dashboard Closed**")
        return
        
    elif action == "adm_global_stats":
        stats = StatisticsService.get_global_stats()
        detailed = StatisticsService.get_detailed_analytics()
        mon = get_monitoring_stats()
        
        from bot import get_uptime
        uptime_str = get_uptime()
        restarts = SystemStateService.get_restart_count()
        crashes = SystemStateService.get_crash_count()
        
        # Format tools list
        tools_str = ""
        for tool, count in detailed["popular_tools"].items():
            tools_str += f"   - **{tool}:** {count} actions\n"
            
        # Format formats list
        formats_str = ""
        for item in detailed["common_file_types"][:3]:
            formats_str += f"   - `.{item['format'].upper()}`: {item['count']} times\n"
            
        # Format conversions list
        convs_str = ""
        for item in detailed["popular_conversions"][:3]:
            convs_str += f"   - `{item['route']}`: {item['count']} times\n"
            
        # Format platforms list
        platforms_str = ""
        for item in detailed["top_platforms"][:3]:
            platforms_str += f"   - **{item['platform']}:** {item['count']} downloads\n"

        platforms_display = platforms_str or "   - None\n"
        formats_display = formats_str or "   - None\n"
        convs_display = convs_str or "   - None\n"
        tools_display = tools_str or "   - None\n"

        text = (
            f"📊 **Global Usage & Monitoring Stats**\n\n"
            f"👥 **Total Users:** {stats['total_users']} | **Today:** {stats['active_today']}\n"
            f"📈 **WAU:** {detailed['wau']} | **MAU:** {detailed['mau']}\n"
            f"📥 **Downloads (Today/Total):** {stats['downloads_today']}/{stats['total_downloads']}\n"
            f"🔄 **Conversions (Today/Total):** {stats['conversions_today']}/{stats['total_conversions']}\n"
            f"🔳 **QR Generated:** {stats['qr_generated']}\n"
            f"📦 **Files Compressed:** {stats['files_compressed']}\n"
            f"💾 **Storage Saved:** {format_size(stats['total_storage_saved_bytes'])}\n"
            f"🚨 **Suspicious Accounts:** {stats['suspicious_count']}\n\n"
            
            f"⚡ **Active Queue Stats**\n"
            f"   - **Active Tasks:** {mon['active_tasks']} / 2\n"
            f"   - **Pending Queue:** {mon['pending_tasks']} / 50\n"
            f"   - **Completed Tasks:** {mon['completed_tasks']}\n"
            f"   - **Failed Tasks:** {mon['failed_tasks']}\n"
            f"   - **Average Process Time:** {mon['avg_processing_time']:.1f}s\n\n"
            
            f"📈 **Popularity Rankings**\n"
            f"🔹 **Top Platforms:**\n{platforms_display}"
            f"🔹 **Top Formats:**\n{formats_display}"
            f"🔹 **Top Conversions:**\n{convs_display}"
            f"🔹 **Tool Usage:**\n{tools_display}"
            
            f"🖥 **System Health**\n"
            f"   - **CPU Usage:** {mon['cpu_usage']:.1f}%\n"
            f"   - **RAM Usage:** {mon['ram_usage']:.1f}%\n"
            f"   - **Uptime:** {uptime_str}\n"
            f"   - **Restarts:** {restarts}\n"
            f"   - **Crashes:** {crashes}"
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif action == "adm_users_list":
        users = StatisticsService.get_all_users()
        text = "👥 **Registered Users (Recent Active):**\n\n"
        for u in users[:15]:
            ban_tag = " [BANNED]" if u.get('is_banned') else ""
            text += f"• `{u['user_id']}` - {u['first_name']} (@{u['username'] or 'none'}){ban_tag}\n"
            
        if len(users) > 15:
            text += f"\n*(Showing 15 of {len(users)} users)*"
            
        keyboard = [[InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif action == "adm_downloads":
        dls = StatisticsService.get_recent_downloads(limit=10)
        text = "📥 **Recent Downloads (Last 10):**\n\n"
        if not dls:
            text += "*No downloads logged yet.*"
        else:
            for i, d in enumerate(dls, 1):
                text += f"{i}. **{d['platform']}** - {d['title'][:30]}\n   Size: {format_size(d['size'])} | User: `{d['user_id']}`\n\n"
        keyboard = [[InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif action == "adm_conversions":
        convs = StatisticsService.get_recent_conversions(limit=10)
        text = "📄 **Recent Conversions (Last 10):**\n\n"
        if not convs:
            text += "*No conversions logged yet.*"
        else:
            for i, c in enumerate(convs, 1):
                text += f"{i}. **{c['source_format'].upper()} -> {c['target_format'].upper()}**\n   File: {c['original_file'][:30]}\n   Size: {format_size(c['file_size'])} | User: `{c['user_id']}`\n\n"
        keyboard = [[InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif action == "adm_logs_menu":
        keyboard = [
            [
                InlineKeyboardButton("🤖 Main (bot.log)", callback_data="adm_log_bot"),
                InlineKeyboardButton("🚨 Errors (error.log)", callback_data="adm_log_error")
            ],
            [
                InlineKeyboardButton("📥 Downloads (downloads.log)", callback_data="adm_log_downloads"),
                InlineKeyboardButton("📄 Conversions (conversions.log)", callback_data="adm_log_conversions")
            ],
            [
                InlineKeyboardButton("🔒 Security (security.log)", callback_data="adm_log_security"),
                InlineKeyboardButton("👑 Admin (admin.log)", callback_data="adm_log_admin")
            ],
            [InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]
        ]
        await query.message.edit_text(
            "📝 **System Logs Menu**\n\nSelect a log file to download:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif action.startswith("adm_log_"):
        log_type = action.replace("adm_log_", "")
        log_file_map = {
            "bot": "bot.log",
            "error": "error.log",
            "downloads": "downloads.log",
            "conversions": "conversions.log",
            "security": "security.log",
            "admin": "admin.log"
        }
        filename = log_file_map.get(log_type, "bot.log")
        log_path = LOGS_DIR / filename
        
        if log_path.exists() and log_path.stat().st_size > 0:
            # We must notify admin first and send the file
            await query.message.reply_text(f"📤 Preparing log file dump for `{filename}`...")
            with open(log_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat.id,
                    document=f,
                    filename=filename,
                    caption=f"📝 Log file dump: {filename}"
                )
        else:
            await query.message.reply_text(f"❌ Log file `{filename}` is empty or does not exist.")
            
    elif action == "adm_storage_menu":
        # Get SQLite DB size
        from services.database_service import get_db_path
        db_file = Path(get_db_path())
        db_size = db_file.stat().st_size if db_file.exists() else 0
        
        # Get backups list
        backups_count = len(list(BACKUPS_DIR.glob("backup_*.zip"))) if BACKUPS_DIR.exists() else 0
        
        text = (
            f"💾 **Storage & Backup Operations**\n\n"
            f"📦 **SQLite Database Size:** {format_size(db_size)}\n"
            f"🗂 **Daily Backups Count:** {backups_count} / 7 (Last 7 days)\n\n"
            f"You can trigger a manual full system backup (Database, Settings, and Logs) below:"
        )
        keyboard = [
            [InlineKeyboardButton("💾 Trigger Manual Backup", callback_data="adm_storage_backup")],
            [InlineKeyboardButton("⬅️ Back to Console", callback_data="adm_main")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif action == "adm_storage_backup":
        success = run_backup()
        if success:
            await query.message.reply_text("✅ **System Backup Complete**\n\nSettings, logs, and database archived to `backups/` successfully.")
        else:
            await query.message.reply_text("❌ **Backup Operation Failed**\n\nCheck logs/error.log for tracebacks.")
        await show_admin_console(update, context)
        admin_logger.info(f"Admin {user_id} executed manual storage backup. Status: {success}")
        
    elif action == "adm_run_cleanup":
        deleted = cleanup_temp_directories()
        await query.message.reply_text(f"🧹 **Cleanup Sweep Complete**\n\nRemoved `{deleted}` expired files from temp storage.")
        log_event("ADMIN", f"Admin {user_id} triggered manual file sweep.")
        admin_logger.info(f"Admin {user_id} ran manual file sweep. Removed {deleted} files.")
        
    elif action == "adm_run_maint":
        current = context.bot_data.get("maintenance_mode", False)
        new_status = not current
        context.bot_data["maintenance_mode"] = new_status
        
        status_text = "ENABLED 🛑" if new_status else "DISABLED 🟢"
        await query.message.reply_text(f"⚙️ **System Maintenance:** {status_text}")
        await show_admin_console(update, context)
        log_event("ADMIN", f"Admin {user_id} toggled maintenance: {status_text}")
        admin_logger.info(f"Admin {user_id} toggled maintenance mode: {status_text}")
        
    elif action == "adm_broadcast_prompt":
        context.user_data["admin_state"] = "wait_broadcast_content"
        await query.message.reply_text(
            "📢 **Broadcast Configuration**\n\n"
            "Please send the message (text, photo, or document) you want to broadcast.\n\n"
            "To append inline URL buttons, add one or more lines at the end of the text/caption using the format:\n"
            "`BUTTON: Label | https://link.com`"
        )
        
    elif action == "adm_bc_confirm":
        payload = context.user_data.get("broadcast_payload")
        if not payload:
            await query.message.reply_text("❌ Broadcast payload expired or invalid.")
            return
            
        context.user_data.pop("broadcast_payload", None)
        status_msg = await query.message.reply_text("📢 Distributing broadcast messages...")
        
        users = StatisticsService.get_all_users()
        success = 0
        failed = 0
        
        # Build reply markup buttons
        keyboard = []
        for label, url in payload["buttons"]:
            keyboard.append([InlineKeyboardButton(label, url=url)])
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        for u in users:
            try:
                if payload["type"] == "text":
                    await context.bot.send_message(
                        chat_id=u['user_id'],
                        text=payload["text"],
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                elif payload["type"] == "photo":
                    await context.bot.send_photo(
                        chat_id=u['user_id'],
                        photo=payload["file_id"],
                        caption=payload["text"],
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                elif payload["type"] == "document":
                    await context.bot.send_document(
                        chat_id=u['user_id'],
                        document=payload["file_id"],
                        caption=payload["text"],
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                success += 1
            except Exception:
                failed += 1
                
        await status_msg.edit_text(
            f"📢 **Broadcast Summary:**\n\n"
            f"✅ **Successful:** `{success}` users\n"
            f"❌ **Failed:** `{failed}` users"
        )
        log_event("ADMIN", f"Admin {user_id} distributed broadcast to {success} users.")
        admin_logger.info(f"Admin {user_id} sent broadcast to {success} users (Failed: {failed})")
        
    elif action == "adm_bc_cancel":
        context.user_data.pop("broadcast_payload", None)
        await query.message.edit_text("❌ **Broadcast Cancelled**")
        await show_admin_console(update, context)
        
    elif action == "adm_ban_prompt":
        context.user_data["admin_state"] = "wait_ban"
        await query.message.reply_text("🚫 Send the Telegram User ID you want to **BAN**:")
        
    elif action == "adm_unban_prompt":
        context.user_data["admin_state"] = "wait_unban"
        await query.message.reply_text("✅ Send the Telegram User ID you want to **UNBAN**:")

async def handle_admin_broadcast_upload(update: Update, context: CallbackContext):
    """Processes uploaded media (photo or document) to be used for broadcast."""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        return
        
    photo = update.message.photo
    doc = update.message.document
    caption = update.message.caption or ""
    
    file_id = None
    file_type = None
    if photo:
        file_id = photo[-1].file_id
        file_type = "photo"
    elif doc:
        file_id = doc.file_id
        file_type = "document"
        
    if not file_id:
        await update.message.reply_text("❌ Uploaded media could not be parsed.")
        return
        
    # Parse caption for buttons
    lines = caption.splitlines()
    clean_lines = []
    buttons = []
    for line in lines:
        match = re.match(r"^BUTTON:\s*(.*?)\s*\|\s*(.*)$", line, re.IGNORECASE)
        if match:
            label = match.group(1).strip()
            url = match.group(2).strip()
            buttons.append((label, url))
        else:
            clean_lines.append(line)
            
    clean_caption = "\n".join(clean_lines).strip()
    
    payload = {
        "type": file_type,
        "text": clean_caption,
        "file_id": file_id,
        "buttons": buttons
    }
    context.user_data["broadcast_payload"] = payload
    context.user_data["admin_state"] = None
    
    await show_broadcast_preview(update, context, payload)

async def show_broadcast_preview(update: Update, context: CallbackContext, payload: dict):
    """Displays the broadcast message preview and control buttons to the admin."""
    chat_id = update.effective_chat.id
    
    # Build inline keyboard markup
    keyboard = []
    for label, url in payload["buttons"]:
        keyboard.append([InlineKeyboardButton(label, url=url)])
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    # Send content
    if payload["type"] == "text":
        await context.bot.send_message(
            chat_id=chat_id,
            text=payload["text"],
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    elif payload["type"] == "photo":
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=payload["file_id"],
            caption=payload["text"],
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    elif payload["type"] == "document":
        await context.bot.send_document(
            chat_id=chat_id,
            document=payload["file_id"],
            caption=payload["text"],
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    # Send controls
    control_keyboard = [
        [
            InlineKeyboardButton("✅ Confirm & Send", callback_data="adm_bc_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="adm_bc_cancel")
        ]
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📢 **Broadcast Preview**\n\n"
            "Above is how your broadcast will appear. "
            "Do you want to send it to all registered users?"
        ),
        reply_markup=InlineKeyboardMarkup(control_keyboard),
        parse_mode="Markdown"
    )

async def handle_admin_text_input(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not check_admin(user_id):
        return
        
    state = context.user_data.get("admin_state")
    if not state:
        return
        
    text = update.message.text
    context.user_data["admin_state"] = None
    
    if state == "wait_broadcast_content":
        if not text:
            await update.message.reply_text("❌ Broadcast text cannot be empty.")
            return
            
        # Parse buttons
        lines = text.splitlines()
        clean_lines = []
        buttons = []
        for line in lines:
            match = re.match(r"^BUTTON:\s*(.*?)\s*\|\s*(.*)$", line, re.IGNORECASE)
            if match:
                label = match.group(1).strip()
                url = match.group(2).strip()
                buttons.append((label, url))
            else:
                clean_lines.append(line)
                
        clean_text = "\n".join(clean_lines).strip()
        
        payload = {
            "type": "text",
            "text": clean_text,
            "buttons": buttons,
            "file_id": None
        }
        context.user_data["broadcast_payload"] = payload
        
        await show_broadcast_preview(update, context, payload)
        
    elif state in ("wait_ban", "wait_unban"):
        try:
            target_id = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Must be an integer.")
            return
            
        from config.settings import OWNER_ID
        if target_id == OWNER_ID:
            await update.message.reply_text("❌ Owner account cannot be banned.")
            return
            
        if state == "wait_ban":
            success = UserService.ban_user(target_id)
            if success:
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text="⚠️ **Access Denied**\n\nYour account has been banned by the Administrator."
                    )
                except Exception:
                    pass
                await update.message.reply_text(f"🚫 User `{target_id}` has been banned.")
                admin_logger.warning(f"Admin {user_id} banned user {target_id}.")
            else:
                await update.message.reply_text(f"❌ User `{target_id}` was not found.")
        else:
            success = UserService.unban_user(target_id)
            if success:
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text="✅ **Access Restored**\n\nYour account has been unbanned by the Administrator."
                    )
                except Exception:
                    pass
                await update.message.reply_text(f"✅ User `{target_id}` has been unbanned.")
                admin_logger.info(f"Admin {user_id} unbanned user {target_id}.")
            else:
                await update.message.reply_text(f"❌ User `{target_id}` was not found.")
