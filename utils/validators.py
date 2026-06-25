from urllib.parse import urlparse
from config.settings import DOWNLOAD_WHITELIST, MAX_FILE_SIZE_BYTES
from utils.logger import logger

def is_valid_url(url: str) -> bool:
    """Validate if the string is a valid URL and belongs to a whitelisted domain."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        
        netloc = parsed.netloc.lower()
        if not netloc:
            return False
            
        for allowed in DOWNLOAD_WHITELIST:
            if netloc == allowed or netloc.endswith("." + allowed):
                return True
                
        return False
    except Exception as e:
        logger.error(f"Error validating URL {url}: {e}")
        return False

def validate_file_size(size_bytes: int) -> bool:
    """Check if the file is within maximum processing limits (2GB)."""
    return size_bytes <= MAX_FILE_SIZE_BYTES
