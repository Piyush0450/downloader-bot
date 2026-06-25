from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.text_service import (
    to_sentence_case, remove_duplicate_lines, clean_text,
    pretty_print_json, get_text_stats
)
from services.security_service import RateLimiter, check_user_access
from utils.helpers import generate_temp_path, cleanup_file
from utils.logger import logger
from services.database_service import log_event
from config.settings import CONVERTED_DIR

async def show_text_tools_prompt(update: Update, context: CallbackContext):
    """Prompt user to type/send text."""
    if not await check_user_access(update, context):
        return
    context.user_data["text_state"] = "wait_text"
    await update.message.reply_text("📝 Please send the text you want to manipulate:")

async def handle_text_input(update: Update, context: CallbackContext):
    """Receive text input and display operational menu."""
    user_id = update.effective_user.id
    if RateLimiter.is_rate_limited(user_id):
        await update.message.reply_text("⚠️ Rate limit exceeded. Please wait.")
        return
        
    text = update.message.text
    if not text:
        await update.message.reply_text("❌ Please send valid text.")
        return
        
    context.user_data["text_state"] = None
    context.user_data["text_data"] = text
    
    keyboard = [
        [
            InlineKeyboardButton("🔠 UPPERCASE", callback_data="txt_upper"),
            InlineKeyboardButton("🔡 lowercase", callback_data="txt_lower")
        ],
        [
            InlineKeyboardButton("🔤 Title Case", callback_data="txt_title"),
            InlineKeyboardButton("✍️ Sentence Case", callback_data="txt_sentence")
        ],
        [
            InlineKeyboardButton("🚫 Remove Duplicates", callback_data="txt_dedup"),
            InlineKeyboardButton("🧽 Clean Text", callback_data="txt_clean")
        ],
        [
            InlineKeyboardButton("💻 JSON Formatter", callback_data="txt_json"),
            InlineKeyboardButton("📊 Word/Char Count", callback_data="txt_stats")
        ],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")]
    ]
    
    preview = text[:100] + "..." if len(text) > 100 else text
    await update.message.reply_text(
        f"📝 **Text Utilities Console**\n\n"
        f"Preview: *\"{preview}\"*\n\n"
        f"Choose an operation to perform on your text:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_text_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    text = context.user_data.get("text_data")
    
    if not text:
        await query.message.reply_text("❌ Session expired. Please send the text again.")
        return
        
    action = query.data
    
    try:
        res = ""
        action_name = ""
        
        if action == "txt_upper":
            res = text.upper()
            action_name = "UPPERCASE"
        elif action == "txt_lower":
            res = text.lower()
            action_name = "lowercase"
        elif action == "txt_title":
            res = text.title()
            action_name = "Title Case"
        elif action == "txt_sentence":
            res = to_sentence_case(text)
            action_name = "Sentence Case"
        elif action == "txt_dedup":
            res = remove_duplicate_lines(text)
            action_name = "Remove Duplicate Lines"
        elif action == "txt_clean":
            res = clean_text(text)
            action_name = "Text Cleaner"
        elif action == "txt_json":
            res = pretty_print_json(text)
            action_name = "JSON Formatter"
        elif action == "txt_stats":
            stats = get_text_stats(text)
            stats_msg = (
                f"📊 **Text Statistics**\n\n"
                f"🔹 **Characters:** {stats['chars']}\n"
                f"🔹 **Words:** {stats['words']}\n"
                f"🔹 **Lines:** {stats['lines']}"
            )
            await query.message.reply_text(stats_msg, parse_mode="Markdown")
            log_event("SYSTEM", f"User {user_id} requested text stats")
            return
            
        if res:
            formatted = f"✅ **Text Operation: {action_name}**\n\n```{res}```"
            if len(formatted) > 4000:
                # Send as file if too large
                out_path = CONVERTED_DIR / f"text_{generate_temp_path('txt').name}"
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(res)
                with open(out_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=f"text_{action_name.replace(' ', '_').lower()}.txt",
                        caption=f"📝 Result of {action_name}."
                    )
                cleanup_file(out_path)
            else:
                await query.message.reply_text(formatted, parse_mode="MarkdownV2" if "```" in formatted else "Markdown")
                
            log_event("SYSTEM", f"User {user_id} ran text action: {action_name}")
            
    except Exception as e:
        logger.error(f"Text action failed: {e}")
        await query.message.reply_text(f"❌ Operation failed: {str(e)}")
