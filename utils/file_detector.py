import mimetypes
from pathlib import Path

CATEGORY_MAPPING = {
    # Documents
    "docx": "DOCX Document", "pdf": "PDF Document", "txt": "Text File",
    "rtf": "RTF Document", "odt": "OpenDocument Text", "html": "HTML Webpage",
    # Spreadsheets
    "xlsx": "Excel Spreadsheet", "csv": "CSV Data File", "ods": "OpenDocument Spreadsheet",
    # Presentations
    "pptx": "PowerPoint Presentation", "odp": "OpenDocument Presentation",
    # Images
    "png": "PNG Image", "jpg": "JPEG Image", "jpeg": "JPEG Image",
    "webp": "WEBP Image", "bmp": "BMP Image", "tiff": "TIFF Image",
    # Audio
    "mp3": "MP3 Audio", "wav": "WAV Audio", "ogg": "OGG Audio", "aac": "AAC Audio",
    # Video
    "mp4": "MP4 Video", "avi": "AVI Video", "mkv": "MKV Video",
    "mov": "MOV Video", "webm": "WEBM Video",
    # Archives
    "zip": "ZIP Archive", "rar": "RAR Archive", "7z": "7Z Archive"
}

def get_file_info(file_name: str, file_size: int) -> dict:
    """Analyze file name and size to return categories and clean details."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""
    mime_type, _ = mimetypes.guess_type(file_name)
    
    category = CATEGORY_MAPPING.get(ext, f"{ext.upper()} File" if ext else "Unknown File")
    
    # Identify broad groups
    group = "other"
    if ext in ("docx", "pdf", "txt", "rtf", "odt", "html"):
        group = "document"
    elif ext in ("xlsx", "csv", "ods"):
        group = "spreadsheet"
    elif ext in ("pptx", "odp"):
        group = "presentation"
    elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff"):
        group = "image"
    elif ext in ("mp3", "wav", "ogg", "aac"):
        group = "audio"
    elif ext in ("mp4", "avi", "mkv", "mov", "webm"):
        group = "video"
    elif ext in ("zip", "rar", "7z"):
        group = "archive"
        
    return {
        "name": file_name,
        "extension": ext,
        "category": category,
        "group": group,
        "size": file_size,
        "mime": mime_type or "application/octet-stream"
    }
