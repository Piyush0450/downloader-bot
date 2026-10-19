"""
Image Background Removal Service.

Dedicated service for removing image backgrounds and generating transparent PNGs.
Uses a cached rembg / U²-Net session with memory safety caps and input validation.
Performs strictly background removal without any unrelated image manipulations.
"""

import asyncio
import io
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.utils.safe_filename import generate_safe_filepath

logger = logging.getLogger("productivity_hub.services.background_remover")

BG_REMOVED_DIR = Path("temp/background_removed")
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_000_000  # Protection against decompression bombs


class BackgroundRemovalError(Exception):
    """Raised when background removal model fails or is unavailable."""
    pass


class BackgroundRemovalService:
    """
    Dedicated background removal service using cached neural inference.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_file_size_mb = self.settings.MAX_FILE_SIZE
        BG_REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        self._session = None
        self._engine_available: Optional[bool] = None

    def is_engine_available(self) -> bool:
        """Check whether the rembg library is installed and importable."""
        if self._engine_available is not None:
            return self._engine_available
        try:
            import importlib.util
            rembg_ok = importlib.util.find_spec("rembg") is not None
            onnx_ok = importlib.util.find_spec("onnxruntime") is not None
            self._engine_available = rembg_ok and onnx_ok
        except Exception:
            self._engine_available = False
        return self._engine_available

    def _get_or_create_session(self):
        """
        Lazily initialize and cache the rembg session once per process using lightweight model.
        """
        if self._session is not None:
            return self._session

        if not self.is_engine_available():
            raise BackgroundRemovalError(
                "Background removal engine (rembg) is not installed in the environment."
            )

        try:
            from rembg import new_session
            # u2netp is lightweight (~4MB) and ideal for 512MB RAM cloud containers
            self._session = new_session("u2netp")
            logger.info("Initialized cached background removal session (model: u2netp).")
            return self._session
        except Exception as e:
            logger.error(f"Failed to initialize background removal model session: {e}", exc_info=True)
            raise BackgroundRemovalError(f"Model initialization failed: {str(e)}")

    async def remove_background(
        self,
        source_image_path: Path,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Remove background from an image file asynchronously and return transparent PNG.

        Args:
            source_image_path: Input image file Path.
            user_id: Telegram user ID.

        Returns:
            Dict[str, Any]: Output file metadata (output_path, file_size, dimensions).
        """
        if not source_image_path.exists():
            raise BackgroundRemovalError("Source image file does not exist.")

        file_size_bytes = source_image_path.stat().st_size
        if file_size_bytes > self.max_file_size_mb * 1024 * 1024:
            raise BackgroundRemovalError(
                f"Image file exceeds maximum allowed size ({self.max_file_size_mb} MB)."
            )

        # Validate image format and dimensions safely
        try:
            with Image.open(source_image_path) as img:
                width, height = img.size
                if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                    raise BackgroundRemovalError(
                        f"Image dimensions ({width}x{height}) exceed maximum allowed {MAX_IMAGE_DIMENSION}px."
                    )
                if (width * height) > MAX_IMAGE_PIXELS:
                    raise BackgroundRemovalError("Image pixel count exceeds memory safety limits.")
        except Exception as e:
            if isinstance(e, BackgroundRemovalError):
                raise
            raise BackgroundRemovalError(f"Invalid image format: {str(e)}")

        target_path, _ = generate_safe_filepath(
            BG_REMOVED_DIR, f"bg_removed_{source_image_path.stem}.png", prefix="bg"
        )

        loop = asyncio.get_running_loop()
        try:
            output_path = await loop.run_in_executor(
                None, self._sync_remove_background, source_image_path, target_path
            )
        except Exception as e:
            logger.error(f"Background removal failed for user {user_id}: {e}", exc_info=True)
            raise BackgroundRemovalError(f"Background removal failed: {str(e)}")

        # Validate resulting output file
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise BackgroundRemovalError("Background removal produced an empty or missing output file.")

        with Image.open(output_path) as out_img:
            if out_img.mode != "RGBA":
                raise BackgroundRemovalError("Output image does not contain a transparency channel.")

        out_size_bytes = output_path.stat().st_size
        logger.info(f"Background removed successfully for user {user_id}: {output_path.name} ({out_size_bytes} bytes)")

        return {
            "output_path": output_path,
            "file_name": output_path.name,
            "file_size": out_size_bytes,
            "width": width,
            "height": height,
        }

    def _sync_remove_background(self, source_path: Path, target_path: Path) -> Path:
        """Synchronous inference execution inside thread executor."""
        session = self._get_or_create_session()
        from rembg import remove

        with open(source_path, "rb") as input_file:
            input_bytes = input_file.read()

        output_bytes = remove(input_bytes, session=session)

        # Ensure output is a valid transparent PNG
        with Image.open(io.BytesIO(output_bytes)) as result_img:
            rgba_img = result_img.convert("RGBA")
            rgba_img.save(target_path, "PNG")

        return target_path


# Global BackgroundRemovalService singleton
_bg_service_instance: Optional[BackgroundRemovalService] = None


def get_background_removal_service() -> BackgroundRemovalService:
    """Retrieve global BackgroundRemovalService instance."""
    global _bg_service_instance
    if _bg_service_instance is None:
        _bg_service_instance = BackgroundRemovalService()
    return _bg_service_instance
