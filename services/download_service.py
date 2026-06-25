import asyncio
import re
import shutil
import subprocess
import time as _time
import requests as _requests
from pathlib import Path
import yt_dlp
from config.settings import DOWNLOADS_DIR, MAX_FILE_SIZE_BYTES
from utils.logger import logger

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Telegram Bot API hard limit for file uploads
MAX_TELEGRAM_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Video codecs that Telegram fully supports without issues
_TELEGRAM_SAFE_CODECS = {"h264", "avc", "avc1", "h265", "hevc"}


def _get_video_codec(filepath: Path) -> str:
    """Return the video codec name of a file using ffprobe, or empty string on error."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                str(filepath),
            ],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.strip().split(",")[0].lower()
    except Exception:
        return ""


def _reencode_to_h264(filepath: Path) -> Path:
    """
    Re-encode a video file to H.264/AAC inside an mp4 container.
    Used when the source codec (e.g. VP9 from Instagram) is not supported
    natively by Telegram's bot API.
    The original file is deleted; the re-encoded file is returned.
    """
    output = filepath.with_name(filepath.stem + "_h264.mp4")
    logger.info(f"[download_service] Re-encoding {filepath.name} (VP9 to H.264) for Telegram...")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-nostdin",
                "-i", str(filepath),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=600,
            check=True
        )
        filepath.unlink(missing_ok=True)
        logger.info(f"[download_service] Re-encode complete: {output.name} ({output.stat().st_size // (1024*1024)} MB)")
        return output
    except subprocess.CalledProcessError as e:
        logger.error(f"[download_service] ffmpeg re-encode failed: {e.stderr.decode()[-300:]}")
        # Return original file as fallback even if Telegram may reject it
        return filepath
    except Exception as e:
        logger.error(f"[download_service] Re-encode error: {e}")
        return filepath


async def _fetch_instagram_og(url: str) -> dict | None:
    """
    Scrape Instagram post HTML using a crawler User-Agent to extract Open Graph metadata.
    Returns a yt-dlp-like info dict with is_image=True.
    """
    import html
    import requests as _requests
    import re

    def _scrape():
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            )
        }
        try:
            resp = _requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None

            # Search for og:image
            og_image = ""
            og_image_match = re.search(
                r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
                resp.text
            )
            if not og_image_match:
                og_image_match = re.search(
                    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
                    resp.text
                )
            if og_image_match:
                og_image = html.unescape(og_image_match.group(1))

            # Search for og:title (use description as fallback)
            title = "Instagram Post"
            og_title_match = re.search(
                r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
                resp.text
            )
            if not og_title_match:
                og_title_match = re.search(
                    r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
                    resp.text
                )
            if og_title_match:
                title_text = html.unescape(og_title_match.group(1))
                # Strip out common prefixes like "Kiran Kumar on Instagram:" if present
                title = re.sub(r'^.*?on Instagram:\s*', '', title_text)
                if len(title) > 80:
                    title = title[:77] + "..."

            # Parse post ID from the URL to construct high-res media URL.
            # Handles /p/, /reel/, /tv/, and /share/p/ routes.
            post_id_match = re.search(r'/(?:p|reel|tv|share/p)/([^/]+)', url)
            post_id = post_id_match.group(1) if post_id_match else ""
            if post_id:
                image_url = f"https://www.instagram.com/p/{post_id}/media/?size=l"
            else:
                image_url = og_image

            if not image_url:
                return None

            return {
                "title": title,
                "extractor_key": "Instagram",
                "extractor": "instagram",
                "is_image": True,
                "image_url": image_url,
                "thumbnail": image_url,
                "url": url,
            }
        except Exception as err:
            logger.error(f"[download_service] Instagram Open Graph scrape failed: {err}")
            return None

    return await asyncio.to_thread(_scrape)


async def fetch_media_info(url: str) -> dict:
    """
    Fetch video/audio/image metadata without downloading.

    Handles:
    - Standard videos (YouTube, TikTok, etc.)
    - Image-only pins (Pinterest images) via ignore_no_formats_error
    - Playlist-wrapped posts (Instagram posts/carousels): drills into first entry
      so the bot sees the actual video/image formats, not the empty playlist shell.
    """
    # Normalize URL: replace double trailing slashes before query parameter or at end
    url = re.sub(r'/+(\?|$)', r'/\1', url)

    def _extract_single(target_url: str, ydl_opts: dict):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    def _extract():
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignore_no_formats_error': True,
        }
        info = _extract_single(url, ydl_opts)

        # Instagram posts (and some others) are returned as playlists at the
        # top level — the formats live inside each entry, not at playlist level.
        # Drill into the first entry to get actual formats / image URL.
        if info and info.get('_type') in ('playlist', 'multi_video'):
            playlist_title = info.get('title') or ''
            try:
                entries = list(info.get('entries') or [])
            except TypeError:
                entries = []

            if entries:
                first = entries[0]
                # Entry might be a lazy stub — re-extract it fully
                entry_url = first.get('url') or first.get('webpage_url') or ''
                if entry_url and entry_url != url:
                    try:
                        entry_info = _extract_single(entry_url, ydl_opts)
                        if entry_info:
                            # Preserve playlist-level title as fallback
                            if not entry_info.get('title'):
                                entry_info['title'] = playlist_title
                            return entry_info
                    except Exception:
                        pass

                # Fallback: first entry already has full data
                if first.get('formats') or first.get('url') or first.get('thumbnail'):
                    if not first.get('title'):
                        first['title'] = playlist_title
                    return first

        return info

    try:
        info = await asyncio.to_thread(_extract)
    except Exception as e:
        if "instagram.com" in url.lower():
            logger.info(f"[download_service] yt-dlp failed on Instagram URL, attempting Open Graph fallback...")
            info = await _fetch_instagram_og(url)
            if info is None:
                raise e
        else:
            raise e

    if info is None:
        raise ValueError("yt-dlp returned no information for this URL.")

    # Detect image-only content: no video/audio formats and no direct download URL
    # or if it was already marked as an image post by our fallback
    if info.get("is_image"):
        # Keep as image
        pass
    else:
        has_formats = bool(info.get("formats"))
        has_direct_url = bool(info.get("url"))

        if not has_formats and not has_direct_url:
            # Image-only post — mark it so the handler can offer an image download
            info["is_image"] = True

            # Try multiple sources for the image URL in order of preference:
            # 1. thumbnail field (direct)
            # 2. thumbnails list (last/largest entry)
            # 3. url field (some extractors put image URL here)
            image_url = info.get("thumbnail") or ""
            if not image_url:
                thumbs = info.get("thumbnails") or []
                if thumbs:
                    # Prefer last thumbnail (usually highest resolution)
                    image_url = thumbs[-1].get("url") or thumbs[0].get("url") or ""
            if not image_url:
                image_url = info.get("url") or ""

            if not image_url:
                logger.warning(
                    f"[fetch_media_info] is_image=True but no image URL found for: {info.get('title')!r}"
                )

            info["image_url"] = image_url
        else:
            info["is_image"] = False

    return info



def _download_image_direct(image_url: str, out_path: Path) -> Path:
    """
    Download a static image (JPEG/PNG/WebP) directly via requests.
    Used for Pinterest image pins, Instagram photos, etc.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Referer": "https://www.pinterest.com/",
    }
    resp = _requests.get(image_url, headers=headers, timeout=30, stream=True)
    resp.raise_for_status()

    # Derive extension from Content-Type header
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    ext_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = ext_map.get(content_type.split(";")[0].strip(), "jpg")
    final_path = out_path.with_suffix(f".{ext}")

    with open(final_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)

    return final_path


async def download_media_item(
    url: str,
    format_spec: str,
    task_id: str,
    is_audio: bool = False,
    audio_bitrate: str = None,
    progress_hook=None,
    is_image: bool = False,
    image_url: str = "",
) -> Path:
    """Download media from URL inside a thread pool."""
    out_base = DOWNLOADS_DIR / task_id

    # ── Image-only path (Pinterest photos, Instagram images, etc.) ────────────
    if is_image and image_url:
        logger.info(f"[download_service] Direct image download: {image_url[:80]}")
        result = await asyncio.to_thread(_download_image_direct, image_url, out_base)
        return result

    # ── Normal video / audio path ────────────────────────────────────────────
    out_tmpl = str(out_base) + ".%(ext)s"

    def _download():
        ydl_opts = {
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
            'overwrites': True,
        }
        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]

        if is_audio:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': audio_bitrate or '192',
                }],
            })
        else:
            ydl_opts.update({
                'format': format_spec,
                'merge_output_format': 'mp4',
            })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except PermissionError:
            # Windows: ffmpeg may still hold the .temp.mp4 handle after merge.
            # Sleep briefly to let the OS release the file handle, then we
            # will rename the .temp.* file ourselves in the scan below.
            logger.warning("[download_service] Windows PermissionError during rename — waiting for file handle release...")
            _time.sleep(3)

    await asyncio.to_thread(_download)

    # ── Scan for the output file (including .temp.* on Windows rename failure)
    # Try up to 3 times with a short wait in case of delayed file release.
    for attempt in range(3):
        for p in DOWNLOADS_DIR.iterdir():
            if not p.name.startswith(task_id):
                continue

            # Windows edge-case: yt-dlp failed to rename .temp.mp4 → .mp4
            if '.temp.' in p.name:
                final = Path(str(p).replace('.temp.', '.'))
                try:
                    shutil.copy2(str(p), str(final))
                    p.unlink(missing_ok=True)
                    p = final
                    logger.info(f"[download_service] Manually renamed temp file to {final.name}")
                except Exception as rename_err:
                    logger.warning(f"[download_service] Could not rename temp file: {rename_err}")
                    continue

            # Re-encode VP9/non-H.264 video so Telegram can process it
            if not is_audio:
                codec = _get_video_codec(p)
                if codec and codec not in _TELEGRAM_SAFE_CODECS:
                    p = await asyncio.to_thread(_reencode_to_h264, p)

            file_size_bytes = p.stat().st_size
            # Guard: Telegram bot API rejects files larger than 50 MB
            if file_size_bytes > MAX_TELEGRAM_UPLOAD_BYTES:
                p.unlink(missing_ok=True)
                raise ValueError(
                    f"File is {file_size_bytes // (1024 * 1024)} MB — exceeds "
                    "Telegram's 50 MB upload limit. Try a lower quality."
                )
            return p

        if attempt < 2:
            _time.sleep(2)  # wait and retry scan

    raise FileNotFoundError("Downloaded file could not be found after download.")


def get_progress_hook(loop, bot, chat_id, message_id, prefix="📥 Downloading..."):
    """Returns a thread-safe yt-dlp progress hook that throttles status messages to avoid rate limits."""
    import time
    last_update_time = 0.0

    def hook(d):
        nonlocal last_update_time
        if d.get('status') == 'downloading':
            now = time.time()
            # Throttle updates to at most once every 3 seconds to prevent Telegram rate-limiting
            if now - last_update_time < 3.0:
                return
            last_update_time = now

            percent = d.get('_percent_str', '').strip()
            percent = ANSI_ESCAPE.sub('', percent)
            speed = d.get('_speed_str', '').strip()
            speed = ANSI_ESCAPE.sub('', speed)
            eta = d.get('_eta_str', '').strip()
            eta = ANSI_ESCAPE.sub('', eta)

            msg = f"{prefix}\n"
            if percent:
                msg += f"📊 Progress: `{percent}`\n"
            if speed:
                msg += f"⚡ Speed: `{speed}`\n"
            if eta:
                msg += f"⏳ ETA: `{eta}`"

            async def edit():
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=msg,
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            asyncio.run_coroutine_threadsafe(edit(), loop)

    return hook
