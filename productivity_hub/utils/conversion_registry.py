"""
Dynamic File Conversion Registry & Capability Discovery Engine.

Defines supported file conversion rules, source/target format pairs, and required system/python
backends. Dynamically verifies whether required engines (Pillow, FFmpeg, LibreOffice, pypdf,
reportlab, python-docx, openpyxl, pandas, zipfile) are operational before offering formats to users.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from productivity_hub.utils.dependency_checker import get_dependency_checker

logger = logging.getLogger("productivity_hub.utils.conversion_registry")


@dataclass
class ConversionRule:
    """
    Defines a supported file format conversion pair and its operational requirements.
    """
    source_format: str
    target_format: str
    category: str  # 'image', 'audio', 'video', 'document', 'spreadsheet', 'archive'
    required_engine: str  # 'pillow', 'ffmpeg', 'libreoffice', 'pypdf', 'reportlab', 'docx', 'openpyxl', 'pandas', 'zipfile', 'tarfile'
    description: str
    timeout_seconds: int = 60


# Comprehensive Conversion Matrix Rules
CONVERSION_RULES: List[ConversionRule] = [
    # ─── Images (Pillow) ───────────────────────────────────────────
    ConversionRule("png", "jpg", "image", "pillow", "PNG to JPG"),
    ConversionRule("png", "webp", "image", "pillow", "PNG to WEBP"),
    ConversionRule("png", "bmp", "image", "pillow", "PNG to BMP"),
    ConversionRule("png", "ico", "image", "pillow", "PNG to ICO"),
    ConversionRule("png", "pdf", "image", "pillow", "PNG to PDF"),

    ConversionRule("jpg", "png", "image", "pillow", "JPG to PNG"),
    ConversionRule("jpg", "webp", "image", "pillow", "JPG to WEBP"),
    ConversionRule("jpg", "bmp", "image", "pillow", "JPG to BMP"),
    ConversionRule("jpg", "pdf", "image", "pillow", "JPG to PDF"),

    ConversionRule("jpeg", "png", "image", "pillow", "JPEG to PNG"),
    ConversionRule("jpeg", "webp", "image", "pillow", "JPEG to WEBP"),
    ConversionRule("jpeg", "pdf", "image", "pillow", "JPEG to PDF"),

    ConversionRule("webp", "png", "image", "pillow", "WEBP to PNG"),
    ConversionRule("webp", "jpg", "image", "pillow", "WEBP to JPG"),
    ConversionRule("webp", "pdf", "image", "pillow", "WEBP to PDF"),

    ConversionRule("bmp", "png", "image", "pillow", "BMP to PNG"),
    ConversionRule("bmp", "jpg", "image", "pillow", "BMP to JPG"),
    ConversionRule("bmp", "pdf", "image", "pillow", "BMP to PDF"),

    ConversionRule("tiff", "png", "image", "pillow", "TIFF to PNG"),
    ConversionRule("tiff", "jpg", "image", "pillow", "TIFF to JPG"),
    ConversionRule("tiff", "pdf", "image", "pillow", "TIFF to PDF"),

    # ─── Audio (FFmpeg) ────────────────────────────────────────────
    ConversionRule("mp3", "wav", "audio", "ffmpeg", "MP3 to WAV"),
    ConversionRule("mp3", "aac", "audio", "ffmpeg", "MP3 to AAC"),
    ConversionRule("mp3", "ogg", "audio", "ffmpeg", "MP3 to OGG"),
    ConversionRule("mp3", "flac", "audio", "ffmpeg", "MP3 to FLAC"),
    ConversionRule("mp3", "m4a", "audio", "ffmpeg", "MP3 to M4A"),
    ConversionRule("mp3", "opus", "audio", "ffmpeg", "MP3 to OPUS"),

    ConversionRule("wav", "mp3", "audio", "ffmpeg", "WAV to MP3"),
    ConversionRule("wav", "flac", "audio", "ffmpeg", "WAV to FLAC"),
    ConversionRule("wav", "ogg", "audio", "ffmpeg", "WAV to OGG"),
    ConversionRule("wav", "m4a", "audio", "ffmpeg", "WAV to M4A"),

    ConversionRule("flac", "mp3", "audio", "ffmpeg", "FLAC to MP3"),
    ConversionRule("flac", "wav", "audio", "ffmpeg", "FLAC to WAV"),
    ConversionRule("flac", "m4a", "audio", "ffmpeg", "FLAC to M4A"),

    ConversionRule("m4a", "mp3", "audio", "ffmpeg", "M4A to MP3"),
    ConversionRule("m4a", "wav", "audio", "ffmpeg", "M4A to WAV"),

    ConversionRule("ogg", "mp3", "audio", "ffmpeg", "OGG to MP3"),
    ConversionRule("ogg", "wav", "audio", "ffmpeg", "OGG to WAV"),

    ConversionRule("opus", "mp3", "audio", "ffmpeg", "OPUS to MP3"),
    ConversionRule("opus", "wav", "audio", "ffmpeg", "OPUS to WAV"),

    ConversionRule("aac", "mp3", "audio", "ffmpeg", "AAC to MP3"),
    ConversionRule("aac", "wav", "audio", "ffmpeg", "AAC to WAV"),

    # ─── Video (FFmpeg) ────────────────────────────────────────────
    ConversionRule("mp4", "mkv", "video", "ffmpeg", "MP4 to MKV"),
    ConversionRule("mp4", "webm", "video", "ffmpeg", "MP4 to WEBM"),
    ConversionRule("mp4", "avi", "video", "ffmpeg", "MP4 to AVI"),
    ConversionRule("mp4", "mp3", "video", "ffmpeg", "Extract MP3 Audio"),
    ConversionRule("mp4", "wav", "video", "ffmpeg", "Extract WAV Audio"),

    ConversionRule("mkv", "mp4", "video", "ffmpeg", "MKV to MP4"),
    ConversionRule("mkv", "webm", "video", "ffmpeg", "MKV to WEBM"),
    ConversionRule("mkv", "mp3", "video", "ffmpeg", "Extract MP3 Audio"),

    ConversionRule("webm", "mp4", "video", "ffmpeg", "WEBM to MP4"),
    ConversionRule("webm", "mkv", "video", "ffmpeg", "WEBM to MKV"),
    ConversionRule("webm", "mp3", "video", "ffmpeg", "Extract MP3 Audio"),

    ConversionRule("mov", "mp4", "video", "ffmpeg", "MOV to MP4"),
    ConversionRule("mov", "mp3", "video", "ffmpeg", "Extract MP3 Audio"),

    ConversionRule("avi", "mp4", "video", "ffmpeg", "AVI to MP4"),
    ConversionRule("avi", "mkv", "video", "ffmpeg", "AVI to MKV"),
    ConversionRule("avi", "mp3", "video", "ffmpeg", "Extract MP3 Audio"),

    # ─── Documents (LibreOffice / pypdf / reportlab / docx) ────────
    ConversionRule("docx", "pdf", "document", "libreoffice", "DOCX to PDF", timeout_seconds=120),
    ConversionRule("docx", "txt", "document", "docx", "DOCX to Text"),
    ConversionRule("doc", "pdf", "document", "libreoffice", "DOC to PDF", timeout_seconds=120),
    ConversionRule("doc", "docx", "document", "libreoffice", "DOC to DOCX", timeout_seconds=120),
    ConversionRule("odt", "pdf", "document", "libreoffice", "ODT to PDF", timeout_seconds=120),
    ConversionRule("rtf", "pdf", "document", "libreoffice", "RTF to PDF", timeout_seconds=120),
    ConversionRule("pptx", "pdf", "document", "libreoffice", "PPTX to PDF", timeout_seconds=120),
    ConversionRule("ppt", "pdf", "document", "libreoffice", "PPT to PDF", timeout_seconds=120),

    ConversionRule("pdf", "txt", "document", "pypdf", "PDF to Text"),
    ConversionRule("txt", "pdf", "document", "reportlab", "Text to PDF"),
    ConversionRule("md", "txt", "document", "python", "Markdown to TXT"),
    ConversionRule("html", "txt", "document", "python", "HTML to Plain Text"),

    # ─── Spreadsheets (openpyxl / pandas) ──────────────────────────
    ConversionRule("xlsx", "csv", "spreadsheet", "openpyxl", "Excel (XLSX) to CSV"),
    ConversionRule("xlsx", "tsv", "spreadsheet", "openpyxl", "Excel (XLSX) to TSV"),
    ConversionRule("xlsx", "json", "spreadsheet", "openpyxl", "Excel (XLSX) to JSON"),
    ConversionRule("xlsx", "pdf", "spreadsheet", "libreoffice", "Excel (XLSX) to PDF", timeout_seconds=120),

    ConversionRule("csv", "xlsx", "spreadsheet", "openpyxl", "CSV to Excel (XLSX)"),
    ConversionRule("csv", "tsv", "spreadsheet", "python", "CSV to TSV"),
    ConversionRule("csv", "json", "spreadsheet", "python", "CSV to JSON"),

    ConversionRule("tsv", "csv", "spreadsheet", "python", "TSV to CSV"),
    ConversionRule("tsv", "xlsx", "spreadsheet", "openpyxl", "TSV to Excel (XLSX)"),
    ConversionRule("json", "csv", "spreadsheet", "pandas", "JSON to CSV"),

    # ─── Archives (zipfile / tarfile) ──────────────────────────────
    ConversionRule("tar", "zip", "archive", "tarfile", "TAR to ZIP"),
    ConversionRule("gz", "tar", "archive", "tarfile", "Extract GZ to TAR"),
    ConversionRule("zip", "tar", "archive", "zipfile", "ZIP to TAR"),
]


class ConversionRegistry:
    """
    Registry providing format lookup and dynamic library availability verification.
    """

    def __init__(self, rules: Optional[List[ConversionRule]] = None):
        self.rules = rules or CONVERSION_RULES
        self._checker = get_dependency_checker()

    def is_engine_available(self, engine_name: str) -> bool:
        """
        Check if the required tool/library for a conversion engine is available.
        """
        engine = engine_name.lower()
        if engine == "pillow":
            return self._checker.check_python_module("Pillow", "PIL").available
        elif engine == "ffmpeg":
            return self._checker.has_ffmpeg()
        elif engine == "libreoffice":
            return self._checker.has_libreoffice()
        elif engine == "pypdf":
            return self._checker.check_python_module("pypdf").available
        elif engine == "reportlab":
            return self._checker.check_python_module("reportlab").available
        elif engine == "docx":
            return self._checker.check_python_module("python-docx", "docx").available
        elif engine == "openpyxl":
            return self._checker.check_python_module("openpyxl").available
        elif engine == "pandas":
            return self._checker.check_python_module("pandas").available
        elif engine in ("zipfile", "tarfile", "python"):
            return True
        return False

    def is_available(self, source_format: str, target_format: str) -> bool:
        """
        Check whether a specific (source -> target) conversion is supported AND its engine is active.
        """
        source = source_format.strip().lower().lstrip(".")
        target = target_format.strip().lower().lstrip(".")

        for rule in self.rules:
            if rule.source_format == source and rule.target_format == target:
                return self.is_engine_available(rule.required_engine)
        return False

    def get_supported_target_formats(self, source_format: str) -> List[ConversionRule]:
        """
        Return list of all currently available target conversion rules for a given input format.
        Only returns rules whose engines are verified and operational.
        """
        source = source_format.strip().lower().lstrip(".")
        available_rules = []

        for rule in self.rules:
            if rule.source_format == source:
                if self.is_engine_available(rule.required_engine):
                    available_rules.append(rule)

        return available_rules

    def get_available_conversions(self, source_format: str) -> List[ConversionRule]:
        """Alias for get_supported_target_formats."""
        return self.get_supported_target_formats(source_format)

    def get_rule(self, source_format: str, target_format: str) -> Optional[ConversionRule]:
        """Retrieve rule definition for source and target format pair."""
        source = source_format.strip().lower().lstrip(".")
        target = target_format.strip().lower().lstrip(".")

        for rule in self.rules:
            if rule.source_format == source and rule.target_format == target:
                return rule
        return None


# Global registry singleton
_registry_instance: Optional[ConversionRegistry] = None


def get_conversion_registry() -> ConversionRegistry:
    """Retrieve global ConversionRegistry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ConversionRegistry()
    return _registry_instance
