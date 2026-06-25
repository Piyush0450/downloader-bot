import asyncio
import shutil
import subprocess
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from services.image_service import compress_image
from utils.logger import logger

def get_gs_path() -> str:
    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")

def compress_pdf_gs(in_path: Path, out_path: Path, setting: str) -> bool:
    gs = get_gs_path()
    if not gs:
        return False
    try:
        cmd = [
            gs,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={setting}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={out_path}",
            str(in_path)
        ]
        result = subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Ghostscript compression failed: {e}")
        return False

def compress_pdf_pypdf_sync(in_path: Path, out_path: Path):
    reader = PdfReader(in_path)
    writer = PdfWriter()
    
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
        
    with open(out_path, "wb") as f:
        writer.write(f)

async def compress_pdf(in_path: Path, out_path: Path, level: str) -> bool:
    """Compress PDF. Levels: 'low', 'medium', 'high'"""
    gs_map = {
        "low": "/printer",
        "medium": "/ebook",
        "high": "/screen"
    }
    gs_setting = gs_map.get(level, "/ebook")
    
    gs_path = get_gs_path()
    if gs_path:
        success = await asyncio.to_thread(compress_pdf_gs, in_path, out_path, gs_setting)
        if success:
            return True
            
    # Fallback to pypdf lossless stream compression
    await asyncio.to_thread(compress_pdf_pypdf_sync, in_path, out_path)
    return True
