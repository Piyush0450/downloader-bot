"""
Universal File Compression Service.

Handles multi-category compression for Images, PDF documents, Audio, Video, and Archives.
Adapts compression parameters based on file category, enforces timeouts, compares
before/after sizes, and reports accurate savings without false gains.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image
import pypdf

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.utils.file_detector import detect_file_type
from productivity_hub.utils.safe_filename import generate_safe_filepath
from productivity_hub.utils.dependency_checker import get_dependency_checker

logger = logging.getLogger("productivity_hub.services.compression")

COMPRESSED_DIR = Path("temp/compressed")


class CompressionError(Exception):
    """Raised when file compression fails."""
    pass


@dataclass
class CompressionResult:
    """Detailed compression statistics and output file metadata."""
    output_path: Path
    original_size: int
    compressed_size: int
    bytes_saved: int
    percent_saved: float
    is_reduced: bool
    category: str
    level: str
    details: str


class CompressionService:
    """
    Unified multi-format file compressor.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_file_size_mb = self.settings.MAX_FILE_SIZE
        COMPRESSED_DIR.mkdir(parents=True, exist_ok=True)
        self.checker = get_dependency_checker()

    async def compress_file(
        self,
        source_path: Path,
        level: str = "medium",  # 'low', 'medium', 'high'
        user_id: int = 0
    ) -> CompressionResult:
        """
        Compress file asynchronously based on detected category.

        Args:
            source_path: Input file Path.
            level: Compression intensity ('low', 'medium', 'high').
            user_id: Telegram user ID.

        Returns:
            CompressionResult: Detailed compression metrics and output path.
        """
        if not source_path.exists():
            raise CompressionError("Source file does not exist.")

        original_size = source_path.stat().st_size
        file_info = detect_file_type(source_path)
        ext = file_info.extension.lower()

        logger.info(f"Starting compression for user {user_id}: {source_path.name} ({ext}, level={level})")

        # Determine category
        image_exts = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}
        audio_exts = {"mp3", "wav", "flac", "m4a", "ogg", "aac", "opus"}
        video_exts = {"mp4", "mkv", "avi", "mov", "webm"}

        loop = asyncio.get_running_loop()

        if ext in image_exts:
            category = "image"
            target_path, _ = generate_safe_filepath(COMPRESSED_DIR, f"comp_{source_path.stem}.{ext}", prefix="cmp")
            await loop.run_in_executor(None, self._compress_image_sync, source_path, target_path, ext, level)

        elif ext == "pdf":
            category = "pdf"
            target_path, _ = generate_safe_filepath(COMPRESSED_DIR, f"comp_{source_path.stem}.pdf", prefix="cmp")
            await loop.run_in_executor(None, self._compress_pdf_sync, source_path, target_path, level)

        elif ext in audio_exts and self.checker.has_ffmpeg():
            category = "audio"
            target_path, _ = generate_safe_filepath(COMPRESSED_DIR, f"comp_{source_path.stem}.mp3", prefix="cmp")
            await loop.run_in_executor(None, self._compress_audio_sync, source_path, target_path, level)

        elif ext in video_exts and self.checker.has_ffmpeg():
            category = "video"
            target_path, _ = generate_safe_filepath(COMPRESSED_DIR, f"comp_{source_path.stem}.mp4", prefix="cmp")
            await loop.run_in_executor(None, self._compress_video_sync, source_path, target_path, level)

        else:
            # Generic file / archive packaging fallback
            category = "archive"
            target_path, _ = generate_safe_filepath(COMPRESSED_DIR, f"comp_{source_path.stem}.zip", prefix="cmp")
            await loop.run_in_executor(None, self._compress_generic_zip_sync, source_path, target_path)

        if not target_path.exists() or target_path.stat().st_size == 0:
            raise CompressionError("Compression produced an empty or missing output file.")

        compressed_size = target_path.stat().st_size
        bytes_saved = original_size - compressed_size
        percent_saved = (bytes_saved / original_size * 100.0) if original_size > 0 else 0.0
        is_reduced = bytes_saved > 0

        # If file could not be reduced, do not falsely report gain
        if not is_reduced:
            details = "File is already optimally compressed; re-compression did not reduce file size."
        else:
            details = f"Saved {bytes_saved / 1024:.1f} KB ({percent_saved:.1f}% reduction)."

        return CompressionResult(
            output_path=target_path,
            original_size=original_size,
            compressed_size=compressed_size,
            bytes_saved=bytes_saved,
            percent_saved=percent_saved,
            is_reduced=is_reduced,
            category=category,
            level=level,
            details=details
        )

    def _compress_image_sync(self, source: Path, target: Path, ext: str, level: str) -> None:
        """Image compression via Pillow."""
        quality_map = {"low": 85, "medium": 65, "high": 45}
        quality = quality_map.get(level.lower(), 65)

        with Image.open(source) as img:
            fmt = "JPEG" if ext in ("jpg", "jpeg") else ext.upper()
            if ext in ("jpg", "jpeg"):
                rgb_img = img.convert("RGB")
                rgb_img.save(target, format=fmt, quality=quality, optimize=True)
            elif ext == "png":
                # Convert RGBA to P (palette) for high compression if requested
                if level == "high":
                    img.convert("P", palette=Image.ADAPTIVE).save(target, format="PNG", optimize=True)
                else:
                    img.save(target, format="PNG", optimize=True)
            elif ext == "webp":
                img.save(target, format="WEBP", quality=quality, method=6)
            else:
                img.save(target, quality=quality, optimize=True)

    def _compress_pdf_sync(self, source: Path, target: Path, level: str) -> None:
        """PDF compression via Ghostscript or pypdf streams."""
        gs_cmd = shutil.which("gs") or shutil.which("gswin64c")
        gs_setting_map = {"low": "/printer", "medium": "/ebook", "high": "/screen"}
        gs_setting = gs_setting_map.get(level.lower(), "/ebook")

        if gs_cmd:
            try:
                cmd = [
                    gs_cmd,
                    "-sDEVICE=pdfwrite",
                    "-dCompatibilityLevel=1.4",
                    f"-dPDFSETTINGS={gs_setting}",
                    "-dNOPAUSE",
                    "-dQUIET",
                    "-dBATCH",
                    f"-sOutputFile={target}",
                    str(source)
                ]
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                if res.returncode == 0 and target.exists() and target.stat().st_size > 0:
                    return
            except Exception as e:
                logger.warning(f"Ghostscript compression failed, falling back to pypdf: {e}")

        # Fallback to pypdf lossless stream compression
        reader = pypdf.PdfReader(str(source))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)

        with open(target, "wb") as f:
            writer.write(f)

    def _compress_audio_sync(self, source: Path, target: Path, level: str) -> None:
        """Audio re-encoding compression via FFmpeg."""
        bitrate_map = {"low": "192k", "medium": "128k", "high": "64k"}
        bitrate = bitrate_map.get(level.lower(), "128k")

        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-vn", "-acodec", "libmp3lame", "-b:a", bitrate,
            str(target)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if res.returncode != 0:
            raise CompressionError(f"FFmpeg audio compression failed: {res.stderr.decode('utf-8', errors='replace')[:200]}")

    def _compress_video_sync(self, source: Path, target: Path, level: str) -> None:
        """Video compression via FFmpeg with controlled CRF and scale."""
        # Level presets
        if level == "high":
            crf = "32"
            scale = "scale='min(854,iw)':-2"
            audio_br = "96k"
        elif level == "low":
            crf = "23"
            scale = "scale='min(1920,iw)':-2"
            audio_br = "160k"
        else:  # medium
            crf = "28"
            scale = "scale='min(1280,iw)':-2"
            audio_br = "128k"

        cmd = [
            "ffmpeg", "-y", "-i", str(source),
            "-vf", scale,
            "-c:v", "libx264", "-crf", crf, "-preset", "fast",
            "-c:a", "aac", "-b:a", audio_br,
            str(target)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        if res.returncode != 0:
            raise CompressionError(f"FFmpeg video compression failed: {res.stderr.decode('utf-8', errors='replace')[:200]}")

    def _compress_generic_zip_sync(self, source: Path, target: Path) -> None:
        """Generic file packaging with ZIP maximum deflation."""
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.write(source, arcname=source.name)


# Global CompressionService singleton
_compression_service_instance: Optional[CompressionService] = None


def get_compression_service() -> CompressionService:
    """Retrieve global CompressionService instance."""
    global _compression_service_instance
    if _compression_service_instance is None:
        _compression_service_instance = CompressionService()
    return _compression_service_instance
