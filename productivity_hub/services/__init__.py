"""
Services Subpackage for Productivity Hub.

Exports all core domain services:
- TaskQueueService (background task processing & concurrency)
- CleanupService (automated temp storage sweeper)
- UserService (user registration & permissions)
- DownloaderService (universal media extraction)
- ConversionService (dynamic format conversion matrix)
- BackgroundRemovalService (AI background removal)
- CompressionService (adaptive file compression)
- QRGenerationService (structured QR code creation)
- QRScanningService (robust QR code decoding)
- AdminService (operational dashboard, diagnostics & control)
"""

from .queue_service import (
    TaskQueueService,
    QueueTask,
    init_queue_service,
    get_queue_service,
    QueueOverflowError,
    UserTaskLimitError,
    TaskNotFoundError,
)
from .cleanup_service import (
    CleanupService,
    start_cleanup_service,
    get_cleanup_service,
)
from .user_service import (
    UserService,
    get_user_service,
)
from .downloader_service import (
    DownloaderService,
    get_downloader_service,
    DownloaderError,
)
from .conversion_service import (
    ConversionService,
    get_conversion_service,
    ConversionError,
)
from .background_removal_service import (
    BackgroundRemovalService,
    get_background_removal_service,
    BackgroundRemovalError,
)
from .compression_service import (
    CompressionService,
    get_compression_service,
    CompressionResult,
    CompressionError,
)
from .qr_generation_service import (
    QRGenerationService,
    get_qr_generation_service,
    QRGenerationError,
)
from .qr_scanning_service import (
    QRScanningService,
    get_qr_scanning_service,
    DecodedQRPayload,
    QRScanningError,
)
from .admin_service import (
    AdminService,
    get_admin_service,
)

__all__ = [
    "TaskQueueService",
    "QueueTask",
    "init_queue_service",
    "get_queue_service",
    "QueueOverflowError",
    "UserTaskLimitError",
    "TaskNotFoundError",
    "CleanupService",
    "start_cleanup_service",
    "get_cleanup_service",
    "UserService",
    "get_user_service",
    "DownloaderService",
    "get_downloader_service",
    "DownloaderError",
    "ConversionService",
    "get_conversion_service",
    "ConversionError",
    "BackgroundRemovalService",
    "get_background_removal_service",
    "BackgroundRemovalError",
    "CompressionService",
    "get_compression_service",
    "CompressionResult",
    "CompressionError",
    "QRGenerationService",
    "get_qr_generation_service",
    "QRGenerationError",
    "QRScanningService",
    "get_qr_scanning_service",
    "DecodedQRPayload",
    "QRScanningError",
    "AdminService",
    "get_admin_service",
]
