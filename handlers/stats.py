from telegram import Update
from telegram.ext import CallbackContext
from services.database_service import StatisticsService, log_event
from utils.helpers import format_size
from utils.logger import logger

async def handle_stats_command(update: Update, context: CallbackContext):
    """Retrieve and display the user's personal statistics."""
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    try:
        stats = StatisticsService.get_user_stats(user_id)
        if not stats:
            await update.message.reply_text("❌ No metrics recorded for your account yet.")
            return
            
        bandwidth = format_size(stats["storage_saved_bytes"])
        
        msg = (
            f"📊 **Usage Stats for {first_name}**\n\n"
            f"📥 **Downloads:** {stats['downloads']} items\n"
            f"🔄 **Conversions:** {stats['conversions']} files\n"
            f"⚙️ **Total Processed:** {stats['files_processed']} items\n"
            f"💾 **Storage Saved:** {bandwidth}\n"
            f"📅 **Registered:** {stats['join_date'].strftime('%Y-%m-%d %H:%M UTC')}"
        )
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        log_event("SYSTEM", f"User {user_id} viewed personal stats.")
    except Exception as e:
        logger.error(f"Failed handling stats command: {e}")
        await update.message.reply_text("❌ Failed to query statistics.")
 
async def handle_history_command(update: Update, context: CallbackContext):
    """Retrieve and display the user's recent action history."""
    user_id = update.effective_user.id
    
    try:
        history = StatisticsService.get_user_history(user_id, limit=5)
        if not history:
            await update.message.reply_text("📜 **Your History**\n\nNo actions logged yet. Start downloading or converting files!")
            return
            
        msg = "📜 **Your Recent Actions (Max 5):**\n\n"
        for i, item in enumerate(history, 1):
            time_str = item["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
            size_str = f" | {format_size(item['size'])}" if item["size"] else ""
            msg += f"{i}. **{item['action']}**\n   💬 {item['details']}{size_str}\n   *At: {time_str}*\n\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
        log_event("SYSTEM", f"User {user_id} viewed personal history.")
    except Exception as e:
        logger.error(f"Failed handling history command: {e}")
        await update.message.reply_text("❌ Failed to query history.")
