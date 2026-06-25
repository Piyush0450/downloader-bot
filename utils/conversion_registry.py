CONVERSION_MATRIX = {
    # DOCUMENTS
    "docx": ["pdf", "txt", "rtf", "odt", "html", "epub"],
    "pdf": ["docx", "txt", "html", "images", "epub"],
    "txt": ["pdf", "docx", "html", "rtf"],
    "rtf": ["docx", "pdf", "txt"],
    "odt": ["docx", "pdf", "txt"],
    "html": ["pdf", "docx", "txt"],
    
    # SPREADSHEETS
    "xlsx": ["csv", "ods", "pdf", "html", "json"],
    "csv": ["xlsx", "pdf", "json"],
    "ods": ["xlsx", "csv", "pdf"],
    
    # PRESENTATIONS
    "pptx": ["pdf", "images"],
    "odp": ["pdf", "images"],
    
    # IMAGES
    "png": ["jpg", "webp", "bmp", "tiff", "ico", "pdf"],
    "jpg": ["png", "webp", "bmp", "tiff", "ico", "pdf"],
    "jpeg": ["png", "webp", "bmp", "tiff", "ico", "pdf"],
    "webp": ["png", "jpg", "bmp", "pdf"],
    "bmp": ["png", "jpg", "webp"],
    "tiff": ["png", "jpg", "pdf"],
    
    # AUDIO
    "mp3": ["wav", "ogg", "aac", "flac"],
    "wav": ["mp3", "ogg", "aac"],
    "ogg": ["mp3", "wav"],
    "aac": ["mp3", "wav"],
    
    # VIDEO
    "mp4": ["mp3", "wav", "avi", "mkv", "mov", "webm", "gif"],
    "avi": ["mp4", "mkv", "mov"],
    "mkv": ["mp4", "avi", "mov"],
    "mov": ["mp4", "avi", "mkv"],
    "webm": ["mp4", "avi", "mov"],
    
    # ARCHIVES
    "zip": ["extract"],
    "rar": ["extract"],
    "7z": ["extract"]
}

def get_conversion_targets(source_format: str) -> list:
    """Return list of supported formats for a given source extension."""
    return CONVERSION_MATRIX.get(source_format.lower(), [])
