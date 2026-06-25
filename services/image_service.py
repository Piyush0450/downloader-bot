import asyncio
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS
from config.settings import TEMP_DIR
from utils.helpers import generate_temp_path

# Pillow functions wrapped for thread pools
def resize_image_sync(in_path: Path, out_path: Path, w: int, h: int):
    with Image.open(in_path) as img:
        fmt = img.format or "PNG"
        resized = img.resize((w, h), Image.Resampling.LANCZOS)
        resized.save(out_path, fmt)

def center_crop_sync(in_path: Path, out_path: Path, aspect_ratio: float):
    with Image.open(in_path) as img:
        fmt = img.format or "PNG"
        w, h = img.size
        
        current_ratio = w / h
        if current_ratio > aspect_ratio:
            new_w = int(h * aspect_ratio)
            left = (w - new_w) // 2
            right = left + new_w
            top = 0
            bottom = h
        else:
            new_h = int(w / aspect_ratio)
            top = (h - new_h) // 2
            bottom = top + new_h
            left = 0
            right = w
            
        cropped = img.crop((left, top, right, bottom))
        cropped.save(out_path, fmt)

def rotate_image_sync(in_path: Path, out_path: Path, angle: int):
    with Image.open(in_path) as img:
        fmt = img.format or "PNG"
        rotated = img.rotate(angle, expand=True)
        rotated.save(out_path, fmt)

def compress_image_sync(in_path: Path, out_path: Path, quality: int):
    with Image.open(in_path) as img:
        fmt = (img.format or "JPEG").upper()
        if fmt in ("JPG", "JPEG"):
            img.save(out_path, "JPEG", quality=quality)
        elif fmt == "PNG":
            lvl = max(1, min(9, int((100 - quality) / 10)))
            img.save(out_path, "PNG", compress_level=lvl)
        elif fmt == "WEBP":
            img.save(out_path, "WEBP", quality=quality)
        else:
            img.save(out_path, fmt)

def generate_thumbnail_sync(in_path: Path, out_path: Path):
    """Generate a quick square or aspect-fitted 150x150 thumbnail."""
    with Image.open(in_path) as img:
        fmt = img.format or "PNG"
        # Fits inside 150x150 keeping aspect ratio
        img.thumbnail((150, 150), Image.Resampling.LANCZOS)
        img.save(out_path, fmt)

def extract_metadata_sync(in_path: Path) -> dict:
    meta = {}
    with Image.open(in_path) as img:
        meta["Format"] = img.format
        meta["Dimensions"] = f"{img.width}x{img.height} px"
        meta["Color Mode"] = img.mode
        
        exif = img.getexif()
        if exif:
            for tag_id, val in exif.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if isinstance(val, bytes):
                    val = val[:50] + b'...' if len(val) > 50 else val
                meta[str(tag_name)] = str(val)
    return meta

def remove_metadata_sync(in_path: Path, out_path: Path):
    with Image.open(in_path) as img:
        fmt = img.format or "PNG"
        data = list(img.getdata())
        clean_img = Image.new(img.mode, img.size)
        clean_img.putdata(data)
        clean_img.save(out_path, fmt)

# --- ASYNC WRAPPERS ---

async def resize_image(in_path: Path, out_path: Path, w: int, h: int):
    await asyncio.to_thread(resize_image_sync, in_path, out_path, w, h)

async def crop_image(in_path: Path, out_path: Path, ratio: float):
    await asyncio.to_thread(center_crop_sync, in_path, out_path, ratio)

async def rotate_image(in_path: Path, out_path: Path, angle: int):
    await asyncio.to_thread(rotate_image_sync, in_path, out_path, angle)

async def compress_image(in_path: Path, out_path: Path, quality: int):
    await asyncio.to_thread(compress_image_sync, in_path, out_path, quality)

async def generate_thumbnail(in_path: Path, out_path: Path):
    await asyncio.to_thread(generate_thumbnail_sync, in_path, out_path)

async def extract_metadata(in_path: Path) -> dict:
    return await asyncio.to_thread(extract_metadata_sync, in_path)

async def remove_metadata(in_path: Path, out_path: Path):
    await asyncio.to_thread(remove_metadata_sync, in_path, out_path)
