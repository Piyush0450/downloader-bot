"""
Media Downloader Handler.

Intercepts media URLs, fetches metadata asynchronously via DownloaderService,
dynamically displays genuinely available quality options (Auto/Best, HD resolutions, MP3),
submits tasks to TaskQueueService, safely throttles progress updates to Telegram,
enforces file size & Telegram upload limits, and delivers completed media files with cleanup.
"""

import asyncio
import html
import logging
import time
from typing import Dict, Any, Set, Optional
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from productivity_hub.config.settings import get_settings
from productivity_hub.handlers.middleware import protected_handler
from productivity_hub.handlers.keyboards import parse_callback_data, get_back_keyboard
from productivity_hub.services.downloader_service import get_downloader_service, DownloaderError
from productivity_hub.services.queue_service import get_queue_service, QueueOverflowError, UserTaskLimitError
from productivity_hub.database.database import get_db
from productivity_hub.database.models import Download
from productivity_hub.services.cleanup_service import safe_delete_file
from productivity_hub.utils.validators import (
    validate_media_url,
    get_oversized_file_message,
    get_oversized_suggestion_keyboard
)
from productivity_hub.utils.i18n import get_text

logger = logging.getLogger("productivity_hub.handlers.downloader")

# Context storage key for active download session URLs
ACTIVE_DOWNLOAD_URLS: Dict[int, str] = {}

# In-flight download task tracking to prevent double-clicks & concurrent duplicate tasks
ACTIVE_DOWNLOADING_USERS: Set[int] = set()
ACTIVE_CANCEL_EVENTS: Dict[str, asyncio.Event] = {}


@protected_handler(operation_type="default")
async def download_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /download command."""
    user = context.user_data.get("user")
    lang = user.language if user else "en"
    user_id = update.effective_user.id
    context.user_data["active_mode"] = "downloader"

    title = get_text("title_downloader", lang)
    desc = get_text("desc_downloader", lang)
    keyboard = get_back_keyboard(owner_id=user_id, lang=lang)

    if update.effective_message:
        await update.effective_message.reply_text(
            f"{title}\n\n{desc}\n\n"
            f"🔗 <b>Please send the media link now:</b>\n"
            f"<i>Supports YouTube, Instagram, TikTok, Facebook, Twitter/X, Pinterest, Reddit, SoundCloud, and more.</i>",
            parse_mode="HTML",
            reply_markup=keyboard
        )


@protected_handler(operation_type="download")
async def media_url_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming text messages containing media URLs.
    Extracts metadata dynamically and presents genuine quality options.
    """
    if not update.effective_message or not update.effective_message.text:
        return

    text = update.effective_message.text.strip()
    valid, service, clean_url = validate_media_url(text)

    if not valid:
        return  # Pass through if text is not a recognized media URL

    user_id = update.effective_user.id
    user = context.user_data.get("user")
    lang = user.language if user else "en"

    # Store clean URL in active session dict and persistent context
    ACTIVE_DOWNLOAD_URLS[user_id] = clean_url
    context.user_data["active_download_url"] = clean_url

    status_msg = None
    for _ in range(2):
        try:
            status_msg = await update.effective_message.reply_text(
                "🔎 <b>Analyzing media link and discovering quality options...</b>",
                parse_mode="HTML"
            )
            break
        except Exception:
            await asyncio.sleep(1)

    if not status_msg:
        return

    downloader_svc = get_downloader_service()
    try:
        meta = await downloader_svc.get_metadata(clean_url)
    except DownloaderError as de:
        safe_err = html.escape(str(de))
        await status_msg.edit_text(f"❌ <b>Extraction Failed:</b>\n{safe_err}", parse_mode="HTML")
        return
    except Exception as e:
        logger.error(f"Unexpected metadata fetch error for {clean_url}: {e}", exc_info=True)
        await status_msg.edit_text("❌ <b>Failed to extract media metadata. Please check the URL.</b>", parse_mode="HTML")
        return

    # Build Dynamic Quality Selection Keyboard
    buttons = []

    # 1. Video Options
    v_formats = meta.get("video_formats", [])
    if v_formats:
        # If "auto" exists, place it on its own prominent row
        auto_fmts = [f for f in v_formats if f["format_id"] == "auto"]
        other_v_fmts = [f for f in v_formats if f["format_id"] != "auto"]

        if auto_fmts:
            auto_btn = auto_fmts[0]
            buttons.append([
                InlineKeyboardButton(
                    auto_btn["resolution"],
                    callback_data=f"dlfmt:{auto_btn['format_id']}:{user_id}"
                )
            ])

        # Other resolutions in rows of 2
        v_row = []
        for fmt in other_v_fmts:
            v_row.append(
                InlineKeyboardButton(
                    fmt["resolution"],
                    callback_data=f"dlfmt:{fmt['format_id']}:{user_id}"
                )
            )
            if len(v_row) == 2:
                buttons.append(v_row)
                v_row = []
        if v_row:
            buttons.append(v_row)

    # 2. Audio Options (MP3 / Direct)
    a_formats = meta.get("audio_formats", [])
    if a_formats:
        a_row = []
        for fmt in a_formats:
            a_row.append(
                InlineKeyboardButton(
                    fmt["resolution"],
                    callback_data=f"dlfmt:{fmt['format_id']}:{user_id}"
                )
            )
            if len(a_row) == 2:
                buttons.append(a_row)
                a_row = []
        if a_row:
            buttons.append(a_row)

    # 3. Actions / Navigation Row
    buttons.append([
        InlineKeyboardButton("❌ Cancel", callback_data=f"dlfmt:cancel:{user_id}"),
        InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{user_id}")
    ])
    keyboard = InlineKeyboardMarkup(buttons)

    safe_title = html.escape(str(meta.get("title", "Media")))
    platform_name = meta.get("service", "Web").upper()
    duration_str = meta.get("duration_str", "00:00")

    summary_text = (
        f"🎬 <b>{safe_title}</b>\n\n"
        f"⏱️ <b>Duration:</b> <code>{duration_str}</code> | 🌐 <b>Platform:</b> <code>{platform_name}</code>\n\n"
        f"👇 <b>Select your desired quality format:</b>"
    )

    rendered_photo = False
    if meta.get("thumbnail"):
        try:
            await update.effective_message.reply_photo(
                photo=meta["thumbnail"],
                caption=summary_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            rendered_photo = True
            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        except Exception as te:
            logger.warning(f"Could not render thumbnail {meta.get('thumbnail')}: {te}")

    if not rendered_photo:
        try:
            await status_msg.edit_text(text=summary_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            try:
                plain_summary = (
                    f"🎬 {meta.get('title', 'Media')}\n"
                    f"⏱️ Duration: {duration_str} | 🌐 Platform: {platform_name}\n\n"
                    f"👇 Select your desired quality format:"
                )
                await update.effective_message.reply_text(text=plain_summary, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Failed to deliver format options message: {e}")


async def handle_download_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle format selection callback queries (e.g. dlfmt:1080p:user_id, dlfmt:auto:user_id).
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, fmt_id, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    # Handle Cancellation from format selection
    if fmt_id == "cancel":
        ACTIVE_DOWNLOAD_URLS.pop(user_id, None)
        context.user_data.pop("active_download_url", None)
        await query.answer("Download cancelled.")
        try:
            await query.edit_message_caption(caption="❌ <b>Download cancelled.</b>", parse_mode="HTML")
        except Exception:
            try:
                await query.edit_message_text("❌ <b>Download cancelled.</b>", parse_mode="HTML")
            except Exception:
                pass
        return

    url = ACTIVE_DOWNLOAD_URLS.get(user_id) or context.user_data.get("active_download_url")
    if not url:
        await query.answer("❌ Download session expired. Please paste the media URL again.", show_alert=True)
        return

    # Prevent duplicate clicks / conflicting concurrent downloads for the same user
    if user_id in ACTIVE_DOWNLOADING_USERS:
        await query.answer("⚠️ You already have an active download in progress. Please wait for it to complete.", show_alert=True)
        return

    await query.answer()
    ACTIVE_DOWNLOADING_USERS.add(user_id)

    queue_svc = get_queue_service()
    downloader_svc = get_downloader_service()

    is_audio_only = fmt_id.startswith("audio_")
    audio_quality = fmt_id.replace("audio_", "") if is_audio_only and fmt_id != "audio_direct" else "320"
    format_selector = fmt_id

    # Disable buttons on the original message to prevent repeated clicking
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    status_msg = await query.message.reply_text(
        f"⏳ <b>Queuing download ({fmt_id.upper()})...</b>\n• <i>Initializing task queue...</i>",
        parse_mode="HTML"
    )

    current_task_holder: Dict[str, Any] = {}
    cancel_event = asyncio.Event()

    user = context.user_data.get("user")
    lang = user.language if user else "en"
    settings = get_settings()

    async def _execute_download_job():
        task_id = current_task_holder.get("task_id", f"dl_{int(time.time())}")
        ACTIVE_CANCEL_EVENTS[task_id] = cancel_event
        file_path = None
        last_ui_edit = [0.0]
        ui_edit_in_flight = [False]

        try:
            # Thread-safe progress update hook called from worker loop
            async def progress_hook(status: str, percent: float, speed: str, eta: str, downloaded: int, total: int):
                now = time.time()
                # Rate limit UI edits to at least 3.5s to prevent Telegram flood limits
                if (now - last_ui_edit[0] < 3.5) or ui_edit_in_flight[0]:
                    return

                ui_edit_in_flight[0] = True
                last_ui_edit[0] = now
                try:
                    # Visual progress bar (12 blocks)
                    filled_blocks = int(round(12 * (percent / 100.0)))
                    bar = "█" * filled_blocks + "░" * (12 - filled_blocks)

                    dl_mb = downloaded / (1024 * 1024)
                    tot_mb = total / (1024 * 1024) if total > 0 else 0
                    size_text = f"<code>{dl_mb:.1f} / {tot_mb:.1f} MB</code>" if tot_mb > 0 else f"<code>{dl_mb:.1f} MB</code>"

                    cancel_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚫 Cancel Download", callback_data=f"dl_cancel:{task_id}:{user_id}")]
                    ])

                    await status_msg.edit_text(
                        f"⏬ <b>Downloading Media...</b>\n\n"
                        f"[{bar}] <b>{percent:.1f}%</b>\n"
                        f"📦 <b>Size:</b> {size_text}\n"
                        f"⚡ <b>Speed:</b> <code>{speed}</code> | ⏱️ <b>ETA:</b> <code>{eta}</code>",
                        parse_mode="HTML",
                        reply_markup=cancel_kb
                    )
                except telegram.error.RetryAfter as ra:
                    logger.debug(f"Telegram throttled progress update: {ra.retry_after}s")
                except telegram.error.BadRequest as br:
                    if "message is not modified" not in str(br).lower():
                        logger.debug(f"Telegram edit message error: {br}")
                except Exception as ex:
                    logger.debug(f"Progress edit error: {ex}")
                finally:
                    ui_edit_in_flight[0] = False

            # Execute download through DownloaderService
            try:
                res = await downloader_svc.download_media(
                    url=url,
                    format_id=format_selector,
                    is_audio_only=is_audio_only,
                    audio_quality=audio_quality,
                    progress_callback=progress_hook,
                    cancel_event=cancel_event
                )
            except DownloaderError as de:
                de_str = str(de).lower()
                if "exceed" in de_str or "limit" in de_str:
                    oversized_msg = get_oversized_file_message(limit_bytes=settings.MAX_FILE_SIZE_BYTES)
                    kb = get_oversized_suggestion_keyboard(
                        owner_id=user_id,
                        filename="video.mp4" if not is_audio_only else "audio.mp3",
                        lang=lang
                    )
                    await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                else:
                    safe_de = html.escape(str(de))
                    retry_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data=f"dl_retry:{user_id}")],
                        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{user_id}")]
                    ])
                    await status_msg.edit_text(f"❌ <b>Download Failed:</b>\n{safe_de}", parse_mode="HTML", reply_markup=retry_kb)
                return None

            file_path = res["file_path"]
            title = res["title"]

            if task_id:
                queue_svc.register_task_files(task_id, file_path)

            # Pre-upload size validation against Telegram Bot API limits (Requirements 4 & 5)
            actual_size = file_path.stat().st_size
            if actual_size > settings.TELEGRAM_UPLOAD_LIMIT_BYTES:
                oversized_msg = get_oversized_file_message(
                    limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                    actual_size_bytes=actual_size
                )
                kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=file_path.name, lang=lang)
                await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                return None

            await status_msg.edit_text("📤 <b>Uploading file to Telegram...</b>\n• <i>Please wait...</i>", parse_mode="HTML")

            # Deliver media file to user
            safe_caption_title = html.escape(str(title))
            caption_parts = [f"<b>{safe_caption_title}</b>"]
            if res.get("resolution_note"):
                caption_parts.append(f"ℹ️ <i>{html.escape(res['resolution_note'])}</i>")
            caption_parts.append("Downloaded via Productivity Hub")
            final_caption = "\n\n".join(caption_parts)

            try:
                with open(file_path, "rb") as f:
                    if is_audio_only:
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=f,
                            caption=final_caption,
                            parse_mode="HTML",
                            read_timeout=180,
                            write_timeout=180
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=f,
                            caption=final_caption,
                            parse_mode="HTML",
                            supports_streaming=True,
                            read_timeout=180,
                            write_timeout=180
                        )
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            except telegram.error.TelegramError as te:
                err_str = str(te).lower()
                if "too big" in err_str or "entity too large" in err_str:
                    oversized_msg = get_oversized_file_message(
                        limit_bytes=settings.TELEGRAM_UPLOAD_LIMIT_BYTES,
                        actual_size_bytes=actual_size
                    )
                    kb = get_oversized_suggestion_keyboard(owner_id=user_id, filename=file_path.name, lang=lang)
                    await status_msg.edit_text(oversized_msg, parse_mode="Markdown", reply_markup=kb)
                else:
                    logger.error(f"Telegram media upload failed: {te}")
                    await status_msg.edit_text(
                        "❌ <b>Upload failed: Telegram was unable to receive the file. Please try a lower resolution.</b>",
                        parse_mode="HTML"
                    )
                return None

            # Record download in database audit history
            db = get_db()
            await db.record_download(Download(
                task_id=task_id or "dl_task",
                user_id=user_id,
                url=url,
                service="media",
                title=title,
                file_path=str(file_path),
                file_size=res["file_size"],
                status="completed"
            ))

            return res

        finally:
            # Automatic temporary file cleanup after delivery or failure
            if file_path:
                safe_delete_file(file_path, exclude_task_id=task_id, log_msg="after delivery/completion")
            ACTIVE_DOWNLOAD_URLS.pop(user_id, None)
            ACTIVE_DOWNLOADING_USERS.discard(user_id)
            ACTIVE_CANCEL_EVENTS.pop(task_id, None)

    try:
        q_task = await queue_svc.submit_task(
            user_id=user_id,
            task_type="download",
            coro_fn=_execute_download_job
        )
        current_task_holder["task_id"] = q_task.task_id

        pos = queue_svc.get_queue_position(q_task.task_id)
        pos_str = f"Position in queue: #{pos}" if pos else "Processing now"
        cancel_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Cancel", callback_data=f"dl_cancel:{q_task.task_id}:{user_id}")]
        ])
        await status_msg.edit_text(
            f"✅ <b>Task Enqueued!</b> ({pos_str})\nYour download will begin shortly.",
            parse_mode="HTML",
            reply_markup=cancel_kb
        )

    except (QueueOverflowError, UserTaskLimitError) as qe:
        ACTIVE_DOWNLOADING_USERS.discard(user_id)
        await status_msg.edit_text(f"⚠️ <b>Queue Error:</b> {html.escape(str(qe))}", parse_mode="HTML")
    except Exception as e:
        ACTIVE_DOWNLOADING_USERS.discard(user_id)
        logger.error(f"Failed to submit download task: {e}", exc_info=True)
        await status_msg.edit_text("❌ <b>Failed to submit download task.</b>", parse_mode="HTML")


async def handle_download_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle active download cancellation via '🚫 Cancel Download' button.
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    action, task_id, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    await query.answer("Cancelling download...")

    # Signal cancel event to abort yt-dlp worker
    cancel_evt = ACTIVE_CANCEL_EVENTS.get(task_id)
    if cancel_evt:
        cancel_evt.set()

    queue_svc = get_queue_service()
    cancelled = await queue_svc.cancel_task(task_id, user_id)
    ACTIVE_DOWNLOADING_USERS.discard(user_id)

    if cancelled:
        try:
            await query.edit_message_text("🚫 <b>Download task cancelled by user.</b>", parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            await query.edit_message_text("🚫 <b>Download cancelled.</b>", parse_mode="HTML")
        except Exception:
            pass


async def handle_download_retry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle download retry request after an error.
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    _, _, owner_id = parse_callback_data(data)

    user_id = query.from_user.id
    if user_id != owner_id:
        await query.answer(get_text("err_unauthorized_button", "en"), show_alert=True)
        return

    await query.answer()
    url = ACTIVE_DOWNLOAD_URLS.get(user_id) or context.user_data.get("active_download_url")
    if not url:
        await query.edit_message_text("❌ Session expired. Please send the media link again.")
        return

    # Trigger fresh analysis
    mock_msg = query.message
    if mock_msg:
        mock_msg.text = url
        await media_url_text_handler(update, context)
