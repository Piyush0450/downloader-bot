import asyncio
import time
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from services.download_service import fetch_media_info, download_media_item, get_progress_hook
from services.queue_service import enqueue_task
from services.database_service import DownloadService
from services.security_service import RateLimiter, check_user_access
from utils.helpers import cleanup_file, format_size
from utils.logger import logger
from utils.validators import is_valid_url

def format_duration(seconds) -> str:
    if not seconds:
        return "Unknown"
    seconds = int(seconds)  # handles float durations (e.g. Instagram returns 36.766)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

async def handle_download_url(update: Update, context: CallbackContext, url: str):
    """Processes URL input, fetches metadata and shows categories."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if RateLimiter.is_rate_limited(user_id):
        from services.security_service import record_suspicious_event
        await record_suspicious_event(update, context, "Rate limit exceeded (Spam)")
        return
        
    if not is_valid_url(url):
        from services.security_service import record_suspicious_event
        await record_suspicious_event(update, context, f"Invalid download URL: {url[:100]}")
        await update.message.reply_text("❌ Unsupported or invalid URL.")
        return
        
    status_msg = await update.message.reply_text("🔍 Fetching Media Information...")
    
    try:
        info = await fetch_media_info(url)
        title = info.get("title", "Unknown Title")
        duration = info.get("duration")
        duration_str = format_duration(duration)
        extractor = info.get("extractor_key", "Unknown")
        is_image = info.get("is_image", False)
        image_url = info.get("image_url", "")

        size = info.get("filesize") or info.get("filesize_approx")
        size_str = format_size(size) if size else "Unknown"
        thumbnail = info.get("thumbnail")

        # Save details
        context.user_data["downloader"] = {
            "url": url,
            "title": title,
            "extractor": extractor,
            "duration": duration,
            "filesize": size,
            "is_image": is_image,
            "image_url": image_url,
        }

        if is_image:
            caption = (
                "\u2139\ufe0f **Media Information**\n\n"
                f"\U0001F4DD **Title:** {title}\n"
                f"\U0001F4CD **Platform:** {extractor}\n"
                "\U0001F5BC\ufe0f **Type:** Image\n"
            )
            keyboard = [
                [InlineKeyboardButton("\u2B07\ufe0f Download Image", callback_data="dl_start_image")],
            ]
        else:
            caption = (
                "\u2139\ufe0f **Media Information**\n\n"
                f"\U0001F4DD **Title:** {title}\n"
                f"\u23f1 **Duration:** {duration_str}\n"
                f"\U0001F4E6 **Size:** {size_str}\n"
                f"\U0001F4CD **Platform:** {extractor}\n"
            )
            keyboard = [
                [
                    InlineKeyboardButton("\U0001F3A5 Video", callback_data="dl_video_menu"),
                    InlineKeyboardButton("\U0001F3B5 Audio", callback_data="dl_audio_menu")
                ],
                [InlineKeyboardButton("\u2139\ufe0f Information", callback_data="dl_more_info")]
            ]

        await status_msg.delete()
        if thumbnail:
            try:
                await update.message.reply_photo(
                    photo=thumbnail,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
            except Exception:
                pass

        await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error fetching metadata: {e}")
        await status_msg.edit_text("\u274c Failed to fetch media metadata. Please ensure it's a public link.")

async def handle_downloader_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    data = context.user_data.get("downloader")
    
    if not data:
        await query.message.reply_text("❌ Session expired. Please send the link again.")
        return
        
    action = query.data

    if action == "dl_more_info":
        info_text = (
            "\U0001F3A5 **Detailed Media Information**\n\n"
            f"\U0001F517 **URL:** {data['url']}\n"
            f"\U0001F4DD **Title:** {data['title']}\n"
            f"\u23f1 **Duration:** {format_duration(data['duration'])}\n"
            f"\U0001F4E6 **Estimated Size:** {format_size(data['filesize']) if data['filesize'] else 'Unknown'}\n"
            f"\U0001F4CD **Platform:** {data['extractor']}\n"
        )
        await query.message.reply_text(info_text, parse_mode="Markdown")
        return

    elif action == "dl_start_image":
        # Image-only download (Pinterest image pins, Instagram photos, etc.)
        is_image = data.get("is_image", False)
        image_url = data.get("image_url", "")
        if not is_image or not image_url:
            await query.message.reply_text("❌ No image URL available for this pin.")
            return
        status_msg = await query.message.reply_text("\u23f3 Downloading image...")

        async def image_worker():
            task_id = f"dl_{int(time.time())}_{user_id}"
            downloaded = None
            try:
                downloaded = await download_media_item(
                    url=data["url"],
                    format_spec="best",
                    task_id=task_id,
                    is_image=True,
                    image_url=image_url,
                )
                await status_msg.edit_text("\U0001F4E4 Uploading image...")
                with open(downloaded, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=f"\U0001F5BC\ufe0f {data['title']}",
                        connect_timeout=60,
                        read_timeout=300,
                        write_timeout=300,
                    )
                await status_msg.delete()
            except Exception as e:
                logger.error(f"Image download failed: {e}")
                await status_msg.edit_text(f"\u274c Image download failed: {e}")
            finally:
                if downloaded:
                    cleanup_file(downloaded)

        try:
            task, position, wait_time = await enqueue_task(
                user_id, context.bot, chat_id, f"Download {data['extractor']} image", image_worker
            )
        except ValueError as e:
            await status_msg.edit_text(str(e))
            return
        try:
            await task.future
        except Exception:
            pass
        return

        
    elif action == "dl_video_menu":
        keyboard = [
            [
                InlineKeyboardButton("360p", callback_data="dl_start_vid_360p"),
                InlineKeyboardButton("720p", callback_data="dl_start_vid_720p"),
                InlineKeyboardButton("1080p", callback_data="dl_start_vid_1080p")
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="dl_back_main")]
        ]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif action == "dl_audio_menu":
        keyboard = [
            [
                InlineKeyboardButton("128 kbps", callback_data="dl_start_aud_128k"),
                InlineKeyboardButton("192 kbps", callback_data="dl_start_aud_192k"),
                InlineKeyboardButton("320 kbps", callback_data="dl_start_aud_320k")
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="dl_back_main")]
        ]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif action == "dl_back_main":
        keyboard = [
            [
                InlineKeyboardButton("🎥 Video", callback_data="dl_video_menu"),
                InlineKeyboardButton("🎵 Audio", callback_data="dl_audio_menu")
            ],
            [InlineKeyboardButton("ℹ️ Information", callback_data="dl_more_info")]
        ]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Download triggers
    is_audio = "dl_start_aud_" in action
    is_video = "dl_start_vid_" in action
    if not (is_audio or is_video):
        return
        
    quality = action.split("_")[-1]
    
    # Define task specifications
    format_spec = "best"
    audio_bitrate = None
    if is_video:
        height = quality.replace("p", "")
        format_spec = (
            # P1: exact height, mp4+m4a streams (YouTube, Facebook)
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            # P2: exact height, any codec split streams
            f"/bestvideo[height<={height}]+bestaudio"
            # P3: single-file format at exact height
            f"/best[height<={height}]"
            # P4: LOWEST quality available — avoids downloading 1920p on 360p request
            #     This handles Instagram/TikTok where min height is 960p+
            + ("/worstvideo[ext=mp4]+bestaudio[ext=m4a]"
               "/worstvideo+bestaudio"
               if height == "360" else
               # P4b: for 720p/1080p pick best available (still capped by 50 MB guard)
               "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
               "/bestvideo+bestaudio")
            # P5: absolute fallback
            + "/best"
        )
    else:
        audio_bitrate = quality.replace("k", "")
        
    # Queue the task
    desc = f"Download {data['extractor']} {'audio' if is_audio else 'video'} ({quality})"
    
    # Status text
    status_text = f"⏳ Enqueuing download request..."
    status_msg = await query.message.reply_text(status_text)
    
    async def worker_func():
        # Actual download logic running in worker thread
        await status_msg.edit_text(f"⏳ Downloading your {'audio' if is_audio else 'video'} ({quality})...")
        task_id = f"dl_{int(time.time())}_{user_id}"
        loop = asyncio.get_event_loop()

        hook = get_progress_hook(loop, context.bot, chat_id, status_msg.message_id, f"📥 Downloading ({quality})...")
        downloaded = None
        try:
            downloaded = await download_media_item(
                url=data["url"],
                format_spec=format_spec,
                task_id=task_id,
                is_audio=is_audio,
                audio_bitrate=audio_bitrate,
                progress_hook=hook
            )

            file_size = downloaded.stat().st_size
            await status_msg.edit_text("📤 Uploading media...")

            with open(downloaded, "rb") as f:
                if is_audio:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=f"\U0001F3B5 {data['title']} ({quality})",
                        title=data["title"],
                        connect_timeout=60,
                        read_timeout=300,
                        write_timeout=300,
                    )
                else:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption=f"\U0001F3A5 {data['title']} ({quality})",
                        supports_streaming=True,
                        connect_timeout=60,
                        read_timeout=300,
                        write_timeout=300,
                    )

            await status_msg.delete()
            DownloadService.log_download(
                user_id=user_id,
                url=data["url"],
                platform=data["extractor"],
                title=data["title"],
                download_type="AUDIO" if is_audio else "VIDEO",
                quality=quality,
                size=file_size
            )
        except ValueError as e:
            # Raised by size guard in download_service (file too large)
            logger.warning(f"Download size exceeded: {e}")
            await status_msg.edit_text(
                f"❌ {e}\n\nPlease choose a lower quality option."
            )
        except Exception as e:
            logger.error(f"Downloader task execution failed: {e}")
            await status_msg.edit_text(
                "❌ Download/upload failed. The file may be too large or the platform "
                "restricted access. Try a lower quality or a different link."
            )
        finally:
            if downloaded:
                cleanup_file(downloaded)

    # Enqueue task
    try:
        task, position, wait_time = await enqueue_task(
            user_id, context.bot, chat_id, desc, worker_func
        )
    except ValueError as e:
        from services.security_service import record_suspicious_event
        await record_suspicious_event(update, context, "Queue spam / Cooldown bypass")
        await status_msg.edit_text(str(e))
        return
        
    if position > 0:
        await status_msg.edit_text(
            f"⏳ **Queue Position: #{position}**\n"
            f"Estimated Wait Time: {wait_time} minutes"
        )
        try:
            await task.future
        except Exception:
            pass
    else:
        try:
            await task.future
        except Exception:
            pass
