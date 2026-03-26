"""Photo upload processing — validation, re-encoding, and thumbnail generation."""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from .config import settings

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

Image.MAX_IMAGE_PIXELS = 50_000_000  # ~50 megapixels — generous for phone photos


# ---------------------------------------------------------------------------
# Synchronous processing (runs in thread pool)
# ---------------------------------------------------------------------------

def process_photo_sync(raw_bytes: bytes) -> tuple[str, bytes, bytes]:
    """Validate, sanitize, and re-encode an uploaded image.

    Returns ``(filename, original_jpeg_bytes, thumbnail_jpeg_bytes)``.
    Raises ``ValueError`` on invalid or corrupt input.
    """
    # Step 1: verify() for fast structural rejection
    try:
        probe = Image.open(io.BytesIO(raw_bytes))
        probe.verify()  # checks header integrity, consumes file handle
    except Exception as e:
        raise ValueError(f"Invalid image file: {e}")

    # Step 2: re-open (verify closes the stream) and fully decode
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()  # forces full pixel decode — catches truncated files
    except Exception as e:
        raise ValueError(f"Corrupt image data: {e}")

    # Step 3: fix phone rotation via EXIF orientation tag (before resize)
    img = ImageOps.exif_transpose(img)

    # Step 4: convert to RGB — RGBA/CMYK/P/L cannot save as JPEG
    if img.mode in ("RGBA", "PA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode == "P":
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Step 5: constrain original to max 2048px
    img.thumbnail((2048, 2048), Image.LANCZOS)

    filename = f"{uuid.uuid4().hex}.jpg"

    # Step 6: save original — omit exif= kwarg to strip ALL metadata (GPS, etc.)
    orig_buf = io.BytesIO()
    img.save(orig_buf, "JPEG", quality=85, optimize=True)

    # Step 7: generate 400px thumbnail
    thumb = img.copy()
    thumb.thumbnail((400, 400), Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, "JPEG", quality=80, optimize=True)

    return filename, orig_buf.getvalue(), thumb_buf.getvalue()


# ---------------------------------------------------------------------------
# Async wrappers (called from route handlers)
# ---------------------------------------------------------------------------

async def save_photo(raw_bytes: bytes) -> str:
    """Process and save a photo to disk. Returns the filename.

    Runs Pillow processing and file I/O in a thread pool to avoid
    blocking the event loop.
    """
    filename, orig_bytes, thumb_bytes = await asyncio.to_thread(
        process_photo_sync, raw_bytes
    )
    orig_path = settings.photo_dir / "originals" / filename
    thumb_path = settings.photo_dir / "thumbnails" / filename
    await asyncio.to_thread(orig_path.write_bytes, orig_bytes)
    await asyncio.to_thread(thumb_path.write_bytes, thumb_bytes)
    return filename


def delete_photo(filename: str) -> None:
    """Best-effort delete of original and thumbnail files."""
    (settings.photo_dir / "originals" / filename).unlink(missing_ok=True)
    (settings.photo_dir / "thumbnails" / filename).unlink(missing_ok=True)
