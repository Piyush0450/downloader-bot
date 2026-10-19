"""
Asynchronous Media Downloader Service.

Wraps yt-dlp execution safely in executor threads outside the asyncio event loop.
Validates target media URLs, extracts metadata & genuine quality formats prior to download,
safely bridges progress updates to Telegram via thread-safe coroutine execution,
enforces file size safety caps, and integrates FFmpeg for stream merging and audio extraction.
"""

import asyncio
import logging
import os
import ssl
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yt_dlp

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.validators import validate_media_url
from productivity_hub.utils.dependency_checker import get_dependency_checker
from productivity_hub.services.media_resolvers import get_fallback_manager

logger = logging.getLogger("productivity_hub.services.downloader")

DOWNLOAD_DIR = Path("temp/downloads")

# Standard Video Quality Tiers (Resolution label and target height)
STANDARD_VIDEO_TIERS: List[Tuple[int, str]] = [
    (2160, "2160p (4K)"),
    (1440, "1440p (2K)"),
    (1080, "1080p Full HD"),
    (720, "720p HD"),
    (480, "480p"),
    (360, "360p"),
]


class DownloaderError(Exception):
    """Raised when media extraction or downloading fails."""
    pass


class DownloaderService:
    """
    Async media downloading engine powered by yt-dlp.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_file_size_bytes = self.settings.MAX_FILE_SIZE_BYTES
        self.max_file_size_mb = self.settings.max_file_size_mb
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async def get_metadata(self, url: str) -> Dict[str, Any]:
        """
        Fetch video/audio metadata (title, duration, thumbnail, formats) WITHOUT downloading.
        Dynamically analyzes genuinely available stream formats and checks FFmpeg presence.

        Args:
            url: Target media URL.

        Returns:
            Dict[str, Any]: Extracted metadata and dynamically formatted quality options.

        Raises:
            DownloaderError: If URL is invalid or yt-dlp metadata extraction fails.
        """
        valid, service, clean_url = validate_media_url(url)
        if not valid:
            raise DownloaderError(f"URL is not supported or failed domain whitelist check.")

        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "socket_timeout": 25,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web", "ios", "mweb"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

        # Automatic cookies ingestion if cookies.txt is provided in workspace or env
        cookies_file = Path("cookies.txt")
        if cookies_file.is_file() and cookies_file.stat().st_size > 0:
            ydl_opts["cookiefile"] = str(cookies_file.resolve())

        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(None, self._sync_extract_info, clean_url, ydl_opts)
        except Exception as e:
            logger.warning(f"Primary yt-dlp metadata extraction failed for {clean_url}: {e}. Switching to fallback resolver engine...")
            
            # ATTEMPT MULTI-ENGINE FALLBACK
            fallback_mgr = get_fallback_manager()
            fallback_res = await fallback_mgr.resolve_fallback(clean_url, service, self.max_file_size_bytes)
            if fallback_res:
                logger.info(f"Fallback engine '{fallback_res.resolver_name}' successfully resolved {clean_url}")
                return fallback_res.to_metadata_dict()

            err_str = str(e)
            if "Private video" in err_str or "Sign in" in err_str:
                raise DownloaderError("This media is private or requires authentication and cannot be accessed.")
            elif "Video unavailable" in err_str or "not available" in err_str.lower():
                raise DownloaderError("This media is unavailable, removed, or region-restricted.")
            else:
                raise DownloaderError(f"Failed to fetch media metadata: {err_str[:120]}")

        if not info:
            raise DownloaderError("No media information could be extracted.")

        title = info.get("title", "Untitled Media")
        duration = info.get("duration", 0) or 0
        thumbnail = info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None)

        # Check FFmpeg availability for MP3 audio and video merging
        dep_checker = get_dependency_checker()
        ffmpeg_available = dep_checker.check_binary("ffmpeg").available

        # Parse available video formats and resolutions
        raw_formats = info.get("formats", [])
        video_raw_formats = []
        all_eff_heights = []

        for fmt in raw_formats:
            vcodec = fmt.get("vcodec", "none")
            if vcodec == "none":
                continue
            w = fmt.get("width")
            h = fmt.get("height")
            if not (w or h):
                continue
            # For vertical videos (Shorts, Reels, TikTok), effective height is min(width, height)
            eff_h = min(w, h) if (w and h and w < h) else (h or w or 0)
            if eff_h > 0:
                video_raw_formats.append((eff_h, fmt))
                all_eff_heights.append(eff_h)

        max_height = max(all_eff_heights) if all_eff_heights else 0

        # Helper to estimate format file size in bytes
        def _estimate_fmt_bytes(fmt_candidate: Dict[str, Any], is_video_only: bool = False) -> int:
            f_size = fmt_candidate.get("filesize") or fmt_candidate.get("filesize_approx")
            if f_size and f_size > 0:
                total_s = f_size
            else:
                tbr = fmt_candidate.get("tbr") or (fmt_candidate.get("vbr", 0) + fmt_candidate.get("abr", 128))
                if tbr and duration > 0:
                    total_s = int((tbr * 1000 / 8) * duration)
                else:
                    total_s = 0

            # If video has no audio stream and ffmpeg is used to merge bestaudio, add audio size
            if is_video_only and fmt_candidate.get("acodec") == "none" and duration > 0:
                # Approximate typical audio at 128 kbps
                audio_bytes = int((128 * 1000 / 8) * duration)
                total_s += audio_bytes
            return total_s

        video_formats: List[Dict[str, Any]] = []

        if video_raw_formats:
            # 1. Always offer "Auto / Best Quality" as the first choice
            # Find candidate for best quality
            best_fmt = max(video_raw_formats, key=lambda x: x[0])[1]
            best_est_bytes = _estimate_fmt_bytes(best_fmt, is_video_only=True)
            best_est_mb = best_est_bytes / (1024 * 1024) if best_est_bytes > 0 else 0
            best_size_str = f" (~{best_est_mb:.1f} MB)" if best_est_mb > 0 else ""
            best_exceeds = best_est_bytes > self.max_file_size_bytes

            video_formats.append({
                "format_id": "auto",
                "resolution": f"🌟 Auto / Best{best_size_str}",
                "height": max_height,
                "filesize_mb": round(best_est_mb, 1),
                "exceeds_limit": best_exceeds,
            })

            # 2. Select genuinely available quality tiers at or below max_height
            added_heights = set()
            for tier_h, tier_label in STANDARD_VIDEO_TIERS:
                if tier_h > max_height:
                    continue  # Never promise higher resolution than the source actually provides

                # Genuine availability check:
                # - Matches the highest available tier, OR
                # - Matches a format within ~30px, OR
                # - Known adaptive streaming platform (YouTube, Vimeo, etc.)
                is_highest_tier = not added_heights
                matches_stream = any(abs(h - tier_h) <= 30 for h in all_eff_heights)
                is_adaptive_platform = service in ("youtube", "vimeo")

                if is_highest_tier or matches_stream or is_adaptive_platform:
                    # Find best format matching this tier
                    matching_fmts = [f for h, f in video_raw_formats if h <= tier_h + 30]
                    target_fmt = max(matching_fmts, key=lambda f: f.get("height", 0) or 0) if matching_fmts else best_fmt
                    est_bytes = _estimate_fmt_bytes(target_fmt, is_video_only=True)
                    est_mb = est_bytes / (1024 * 1024) if est_bytes > 0 else 0
                    size_tag = f" (~{est_mb:.1f} MB)" if est_mb > 0 else ""
                    exceeds = est_bytes > self.max_file_size_bytes

                    video_formats.append({
                        "format_id": f"{tier_h}p",
                        "resolution": f"📹 {tier_label}{size_tag}",
                        "height": tier_h,
                        "filesize_mb": round(est_mb, 1),
                        "exceeds_limit": exceeds,
                    })
                    added_heights.add(tier_h)

            # If max_height is lower than 360 (e.g. 240p or 144p)
            if not added_heights and max_height > 0:
                est_bytes = _estimate_fmt_bytes(best_fmt, is_video_only=True)
                est_mb = est_bytes / (1024 * 1024) if est_bytes > 0 else 0
                size_tag = f" (~{est_mb:.1f} MB)" if est_mb > 0 else ""
                video_formats.append({
                    "format_id": f"{max_height}p",
                    "resolution": f"📹 {max_height}p{size_tag}",
                    "height": max_height,
                    "filesize_mb": round(est_mb, 1),
                    "exceeds_limit": est_bytes > self.max_file_size_bytes,
                })

        # 3. Audio Formats (Check FFmpeg before offering MP3)
        audio_formats: List[Dict[str, Any]] = []
        if ffmpeg_available:
            # 320 kbps MP3
            bytes_320 = int((320 * 1000 / 8) * duration) if duration > 0 else 0
            mb_320 = bytes_320 / (1024 * 1024) if bytes_320 > 0 else 0
            tag_320 = f" (~{mb_320:.1f} MB)" if mb_320 > 0 else ""
            audio_formats.append({
                "format_id": "audio_320",
                "resolution": f"🎵 Audio MP3 (320k){tag_320}",
                "quality": "320",
                "filesize_mb": round(mb_320, 1),
                "exceeds_limit": bytes_320 > self.max_file_size_bytes,
            })

            # 128 kbps MP3
            bytes_128 = int((128 * 1000 / 8) * duration) if duration > 0 else 0
            mb_128 = bytes_128 / (1024 * 1024) if bytes_128 > 0 else 0
            tag_128 = f" (~{mb_128:.1f} MB)" if mb_128 > 0 else ""
            audio_formats.append({
                "format_id": "audio_128",
                "resolution": f"🎵 Audio MP3 (128k){tag_128}",
                "quality": "128",
                "filesize_mb": round(mb_128, 1),
                "exceeds_limit": bytes_128 > self.max_file_size_bytes,
            })
        else:
            # If FFmpeg is missing, offer direct audio stream without conversion
            audio_formats.append({
                "format_id": "audio_direct",
                "resolution": "🎵 Audio Stream (Direct)",
                "quality": "direct",
                "filesize_mb": 0.0,
                "exceeds_limit": False,
            })

        # Format duration into mm:ss or hh:mm:ss
        hours, remainder = divmod(duration, 3600)
        mins, secs = divmod(remainder, 60)
        if hours > 0:
            duration_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        else:
            duration_str = f"{mins:02d}:{secs:02d}"

        return {
            "url": clean_url,
            "service": service,
            "title": title,
            "duration": duration,
            "duration_str": duration_str,
            "thumbnail": thumbnail,
            "video_formats": video_formats,
            "audio_formats": audio_formats,
            "max_height": max_height,
            "ffmpeg_available": ffmpeg_available,
        }

    async def download_media(
        self,
        url: str,
        format_id: str = "auto",
        is_audio_only: bool = False,
        audio_quality: str = "320",
        progress_callback: Optional[Callable[[str, float, str, str, int, int], Any]] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        """
        Download media file asynchronously with file size safety caps, thread-safe progress bridging,
        and FFmpeg-enabled stream merging.

        Args:
            url: Target media URL.
            format_id: Format selector ('auto', '1080p', '720p', etc.).
            is_audio_only: True if extracting MP3 audio.
            audio_quality: Bitrate string ('320' or '128').
            progress_callback: Callback (status, percent, speed_str, eta_str, downloaded_bytes, total_bytes).
            cancel_event: Async event to signal external cancellation.

        Returns:
            Dict[str, Any]: Result metadata including output file_path, file_size, title, and resolution note.

        Raises:
            DownloaderError: On size violation, cancellation, or yt-dlp error.
        """
        loop = asyncio.get_running_loop()

        dep_checker = get_dependency_checker()
        ffmpeg_ok = dep_checker.check_binary("ffmpeg").available

        # Generate unique temporary target filename
        target_filepath, _ = generate_safe_filepath(
            DOWNLOAD_DIR,
            f"media_{int(time.time())}_{uuid.uuid4().hex[:6]}.{'mp3' if is_audio_only else 'mp4'}",
            prefix="dl"
        )
        outtmpl = str(target_filepath.with_suffix("")) + ".%(ext)s"

        # Check if URL was resolved via a direct stream fallback engine
        fallback_mgr = get_fallback_manager()
        cached_res = fallback_mgr.get_cached_resolution(url)
        if not cached_res:
            _, _, clean_url = validate_media_url(url)
            cached_res = fallback_mgr.get_cached_resolution(clean_url)

        if cached_res and (cached_res.direct_stream_url or cached_res.direct_audio_url):
            target_stream = cached_res.direct_audio_url if (is_audio_only and cached_res.direct_audio_url) else cached_res.direct_stream_url
            if target_stream:
                logger.info(f"Using direct stream download via engine '{cached_res.resolver_name}' for {url}")
                return await self._download_direct_stream(
                    stream_url=target_stream,
                    target_filepath=target_filepath,
                    is_audio_only=is_audio_only,
                    audio_quality=audio_quality,
                    headers=cached_res.headers,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    title=cached_res.title,
                    duration=cached_res.duration,
                    format_id=format_id,
                )

        # Build Format Selector with height constraint and fallback
        if is_audio_only:
            if ffmpeg_ok:
                format_selector = "bestaudio[ext=m4a]/bestaudio/best"
            else:
                format_selector = "bestaudio/best"
        elif format_id in ("auto", "best"):
            if ffmpeg_ok:
                format_selector = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
            else:
                format_selector = "best[ext=mp4]/best"
        elif format_id.endswith("p") and format_id[:-1].isdigit():
            h = int(format_id[:-1])
            if ffmpeg_ok:
                format_selector = (
                    f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"bestvideo[height<={h}]+bestaudio/"
                    f"best[height<={h}][ext=mp4]/"
                    f"best[height<={h}]/best"
                )
            else:
                format_selector = f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
        else:
            format_selector = f"{format_id}/best"

        last_update_time = [0.0]
        progress_in_flight = [False]

        def yt_progress_hook(d: Dict[str, Any]):
            # 1. Cancellation check
            if cancel_event and cancel_event.is_set():
                raise DownloaderError("Download cancelled by user.")

            status = d.get("status", "")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

                # 2. Strict streaming size caps (Requirement 3 & 4)
                if downloaded > self.max_file_size_bytes:
                    raise DownloaderError(
                        f"Streamed bytes ({downloaded / (1024 * 1024):.1f} MB) exceeded maximum supported limit "
                        f"({self.max_file_size_mb:.1f} MB). Download stopped."
                    )
                if total and total > self.max_file_size_bytes:
                    raise DownloaderError(
                        f"Estimated media size ({total / (1024 * 1024):.1f} MB) exceeded maximum supported limit "
                        f"({self.max_file_size_mb:.1f} MB). Download aborted."
                    )

            if not progress_callback:
                return

            now = time.time()
            is_finished = (status == "finished")

            # Throttle progress updates to at least 3.0s between calls, and skip if an update is currently pending
            if not is_finished and (now - last_update_time[0] < 3.0 or progress_in_flight[0]):
                return

            last_update_time[0] = now
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            percent = (downloaded / total * 100) if total > 0 else 0.0
            speed_str = d.get("_speed_str", "N/A")
            eta_str = d.get("_eta_str", "N/A")

            # Safely bridge from worker thread to main asyncio event loop!
            # FIX FOR: 'Download failed: no running event loop'
            if asyncio.iscoroutinefunction(progress_callback):
                if loop.is_running() and not loop.is_closed():
                    progress_in_flight[0] = True

                    async def _coro_runner():
                        try:
                            await progress_callback(status, percent, speed_str, eta_str, downloaded, total)
                        except Exception as pe:
                            logger.debug(f"Progress callback exception ignored: {pe}")
                        finally:
                            progress_in_flight[0] = False

                    try:
                        asyncio.run_coroutine_threadsafe(_coro_runner(), loop)
                    except Exception as te:
                        progress_in_flight[0] = False
                        logger.debug(f"Could not dispatch progress callback to loop: {te}")
            else:
                try:
                    progress_callback(status, percent, speed_str, eta_str, downloaded, total)
                except Exception as pe:
                    logger.debug(f"Sync progress callback exception: {pe}")

        ydl_opts: Dict[str, Any] = {
            "format": format_selector,
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [yt_progress_hook],
            "max_filesize": self.max_file_size_bytes,
            "socket_timeout": 25,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web", "ios", "mweb"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

        # Automatic cookies ingestion if cookies.txt is provided in workspace or env
        cookies_file = Path("cookies.txt")
        if cookies_file.is_file() and cookies_file.stat().st_size > 0:
            ydl_opts["cookiefile"] = str(cookies_file.resolve())

        # Apply FFmpeg postprocessors if available
        if ffmpeg_ok:
            if not is_audio_only:
                ydl_opts["merge_output_format"] = "mp4"
                ydl_opts["postprocessor_args"] = {
                    "ffmpeg": ["-movflags", "+faststart"]
                }
            else:
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": audio_quality,
                }]

        logger.info(f"Starting async download for URL: {url} (Format: {format_id}, Max: {self.max_file_size_mb:.1f} MB)")

        try:
            # 300 second (5 min) overall download timeout
            info = await asyncio.wait_for(
                loop.run_in_executor(None, self._sync_extract_info, url, ydl_opts, True),
                timeout=300.0
            )
        except asyncio.TimeoutError:
            self._cleanup_partial(target_filepath.stem)
            logger.error(f"Download timed out after 300s for {url}")
            raise DownloaderError("Download timed out: the host is responding too slowly.")
        except asyncio.CancelledError:
            self._cleanup_partial(target_filepath.stem)
            logger.warning(f"Download cancelled for {url}")
            raise
        except Exception as e:
            self._cleanup_partial(target_filepath.stem)
            err_str = str(e)

            # Never trigger fallbacks if user cancelled or size limit was violated
            if (cancel_event and cancel_event.is_set()) or "cancelled" in err_str.lower():
                raise DownloaderError("Download cancelled by user.")
            if "exceeded maximum supported limit" in err_str.lower():
                raise DownloaderError(err_str)

            logger.warning(f"yt-dlp download failed for {url}: {err_str}. Checking fallback engines...")

            # ATTEMPT FALLBACK DOWNLOAD
            try:
                valid, service, clean_url = validate_media_url(url)
                fallback_res = await fallback_mgr.resolve_fallback(clean_url, service, self.max_file_size_bytes)
                if fallback_res and (fallback_res.direct_stream_url or fallback_res.direct_audio_url):
                    target_stream = fallback_res.direct_audio_url if (is_audio_only and fallback_res.direct_audio_url) else fallback_res.direct_stream_url
                    if target_stream:
                        logger.info(f"Switching to fallback engine '{fallback_res.resolver_name}' for download of {url}")
                        return await self._download_direct_stream(
                            stream_url=target_stream,
                            target_filepath=target_filepath,
                            is_audio_only=is_audio_only,
                            audio_quality=audio_quality,
                            headers=fallback_res.headers,
                            progress_callback=progress_callback,
                            cancel_event=cancel_event,
                            title=fallback_res.title,
                            duration=fallback_res.duration,
                            format_id=format_id,
                        )
            except Exception as fb_err:
                logger.error(f"Fallback download also failed: {fb_err}")

            if "exceeded maximum supported limit" in err_str.lower():
                raise DownloaderError(err_str)
            elif "Private video" in err_str or "Sign in" in err_str:
                raise DownloaderError("This media is private or requires authentication.")
            elif "Video unavailable" in err_str or "not available" in err_str.lower():
                raise DownloaderError("This media is unavailable or region-restricted.")
            elif "Requested format is not available" in err_str:
                raise DownloaderError("The requested resolution is unavailable for this media.")
            else:
                raise DownloaderError(f"Download failed: {err_str[:120]}")

        # Locate output file on disk
        actual_filepath = None
        for ext in ("mp4", "mp3", "m4a", "webm", "mkv"):
            candidate = target_filepath.with_suffix(f".{ext}")
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                actual_filepath = candidate
                break

        if not actual_filepath or not actual_filepath.exists():
            files = [
                f for f in DOWNLOAD_DIR.glob(f"{target_filepath.stem}*")
                if f.is_file() and f.stat().st_size > 0
            ]
            if files:
                actual_filepath = max(files, key=os.path.getctime)

        if not actual_filepath or not actual_filepath.exists() or actual_filepath.stat().st_size == 0:
            self._cleanup_partial(target_filepath.stem)
            raise DownloaderError("Downloaded file could not be verified on disk or is empty.")

        # Post-download file size verification
        file_size_bytes = actual_filepath.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)

        if file_size_bytes > self.max_file_size_bytes:
            actual_filepath.unlink(missing_ok=True)
            raise DownloaderError(
                f"Downloaded file ({file_size_mb:.1f} MB) exceeds maximum allowed size ({self.max_file_size_mb:.1f} MB). File removed."
            )

        title = info.get("title", "Downloaded Media") if info else "Downloaded Media"
        duration = info.get("duration", 0) if info else 0

        # Check if actual delivered resolution differed from requested resolution
        actual_height = info.get("height") or 0
        actual_width = info.get("width") or 0
        if actual_width and actual_height and actual_width < actual_height:
            eff_actual = actual_width
        else:
            eff_actual = actual_height

        resolution_note = None
        if not is_audio_only and format_id.endswith("p") and format_id[:-1].isdigit():
            requested_h = int(format_id[:-1])
            if eff_actual and eff_actual < (requested_h - 20):
                resolution_note = f"Requested {format_id}, delivered {eff_actual}p (highest available from source)"

        logger.info(f"Download finished successfully: {actual_filepath} ({file_size_mb:.2f} MB)")
        return {
            "file_path": actual_filepath,
            "file_size": file_size_bytes,
            "file_size_mb": file_size_mb,
            "title": title,
            "duration": duration,
            "format": format_id,
            "resolution_note": resolution_note,
        }

    async def _download_direct_stream(
        self,
        stream_url: str,
        target_filepath: Path,
        is_audio_only: bool = False,
        audio_quality: str = "320",
        headers: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str, float, str, str, int, int], Any]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        title: str = "Downloaded Media",
        duration: int = 0,
        format_id: str = "auto",
    ) -> Dict[str, Any]:
        """
        Download media directly from direct CDN stream with size safety caps,
        thread-safe progress updates, cancellation support, and FFmpeg postprocessing.
        """
        loop = asyncio.get_running_loop()
        dep_checker = get_dependency_checker()
        ffmpeg_ok = dep_checker.check_binary("ffmpeg").available

        raw_filepath = target_filepath.with_suffix(".raw")
        final_ext = "mp3" if is_audio_only else "mp4"
        final_filepath = target_filepath.with_suffix(f".{final_ext}")

        last_update_time = [0.0]
        progress_in_flight = [False]

        def _do_stream_download():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "*/*",
            }
            if headers:
                req_headers.update(headers)

            req = urllib.request.Request(stream_url, headers=req_headers)
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                content_len = resp.headers.get("Content-Length")
                total_bytes = int(content_len) if content_len and content_len.isdigit() else 0

                if total_bytes > self.max_file_size_bytes:
                    raise DownloaderError(
                        f"Media stream size ({total_bytes / (1024 * 1024):.1f} MB) exceeds maximum allowed limit ({self.max_file_size_mb:.1f} MB)."
                    )

                downloaded_bytes = 0
                start_time = time.time()

                with open(raw_filepath, "wb") as out_f:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise DownloaderError("Download cancelled by user.")

                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded_bytes += len(chunk)

                        if downloaded_bytes > self.max_file_size_bytes:
                            raise DownloaderError(
                                f"Streamed bytes ({downloaded_bytes / (1024 * 1024):.1f} MB) exceeded maximum supported limit ({self.max_file_size_mb:.1f} MB)."
                            )

                        now = time.time()
                        if progress_callback and (now - last_update_time[0] >= 3.0) and not progress_in_flight[0]:
                            last_update_time[0] = now
                            elapsed = max(now - start_time, 0.001)
                            speed_bps = downloaded_bytes / elapsed
                            speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s" if speed_bps > 1024 * 1024 else f"{speed_bps / 1024:.0f} KB/s"
                            rem_bytes = max(total_bytes - downloaded_bytes, 0)
                            eta_secs = int(rem_bytes / speed_bps) if speed_bps > 0 and total_bytes > 0 else 0
                            eta_str = f"{eta_secs}s" if eta_secs > 0 else "N/A"
                            percent = (downloaded_bytes / total_bytes * 100) if total_bytes > 0 else 50.0

                            if asyncio.iscoroutinefunction(progress_callback):
                                if loop.is_running() and not loop.is_closed():
                                    progress_in_flight[0] = True

                                    async def _coro_runner():
                                        try:
                                            await progress_callback("downloading", percent, speed_str, eta_str, downloaded_bytes, total_bytes)
                                        except Exception as pe:
                                            logger.debug(f"Direct stream progress error: {pe}")
                                        finally:
                                            progress_in_flight[0] = False

                                    try:
                                        asyncio.run_coroutine_threadsafe(_coro_runner(), loop)
                                    except Exception:
                                        progress_in_flight[0] = False
                            else:
                                try:
                                    progress_callback("downloading", percent, speed_str, eta_str, downloaded_bytes, total_bytes)
                                except Exception:
                                    pass

        try:
            await loop.run_in_executor(None, _do_stream_download)
        except Exception as e:
            raw_filepath.unlink(missing_ok=True)
            final_filepath.unlink(missing_ok=True)
            if isinstance(e, DownloaderError):
                raise
            raise DownloaderError(f"Direct stream download failed: {str(e)[:120]}")

        # Post-process with FFmpeg
        def _post_process():
            if is_audio_only:
                if ffmpeg_ok:
                    cmd = [
                        "ffmpeg", "-y", "-i", str(raw_filepath),
                        "-vn", "-acodec", "libmp3lame", "-b:a", f"{audio_quality}k",
                        str(final_filepath)
                    ]
                    res = subprocess.run(cmd, capture_output=True)
                    if res.returncode != 0:
                        logger.warning(f"FFmpeg audio extraction failed: {res.stderr.decode('utf-8', errors='ignore')[:120]}")
                        raw_filepath.rename(final_filepath)
                    else:
                        raw_filepath.unlink(missing_ok=True)
                else:
                    raw_filepath.rename(final_filepath)
            else:
                if ffmpeg_ok:
                    cmd = [
                        "ffmpeg", "-y", "-i", str(raw_filepath),
                        "-c", "copy", "-movflags", "+faststart",
                        str(final_filepath)
                    ]
                    res = subprocess.run(cmd, capture_output=True)
                    if res.returncode != 0:
                        logger.warning(f"FFmpeg faststart failed: {res.stderr.decode('utf-8', errors='ignore')[:120]}")
                        raw_filepath.rename(final_filepath)
                    else:
                        raw_filepath.unlink(missing_ok=True)
                else:
                    raw_filepath.rename(final_filepath)

        await loop.run_in_executor(None, _post_process)

        if not final_filepath.exists() or final_filepath.stat().st_size == 0:
            final_filepath.unlink(missing_ok=True)
            raise DownloaderError("Processed stream file could not be verified on disk or is empty.")

        file_size_bytes = final_filepath.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)

        if file_size_bytes > self.max_file_size_bytes:
            final_filepath.unlink(missing_ok=True)
            raise DownloaderError(
                f"Downloaded file ({file_size_mb:.1f} MB) exceeds maximum allowed size ({self.max_file_size_mb:.1f} MB). File removed."
            )

        logger.info(f"Direct stream download complete: {final_filepath} ({file_size_mb:.2f} MB)")
        return {
            "file_path": final_filepath,
            "file_size": file_size_bytes,
            "file_size_mb": file_size_mb,
            "title": title,
            "duration": duration,
            "format": format_id,
            "resolution_note": None,
        }

    @staticmethod
    def _sync_extract_info(url: str, opts: Dict[str, Any], download: bool = False) -> Dict[str, Any]:
        """Synchronous helper method executed safely inside executor thread."""
        opts["download"] = download
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download)

    @staticmethod
    def _cleanup_partial(stem: str) -> None:
        """Safely purge any partial/incomplete download files matching stem."""
        for p_file in DOWNLOAD_DIR.glob(f"{stem}*"):
            try:
                p_file.unlink(missing_ok=True)
            except Exception:
                pass


# Global DownloaderService singleton instance
_downloader_service_instance: Optional[DownloaderService] = None


def get_downloader_service() -> DownloaderService:
    """Retrieve global DownloaderService singleton instance."""
    global _downloader_service_instance
    if _downloader_service_instance is None:
        _downloader_service_instance = DownloaderService()
    return _downloader_service_instance
