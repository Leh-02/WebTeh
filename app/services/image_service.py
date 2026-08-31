from __future__ import annotations
from io import BytesIO
from pathlib import Path
import secrets
from PIL import Image, UnidentifiedImageError

MAX_DIMENSION = 2400

def save_product_image(content: bytes, upload_dir: Path) -> str:
    try:
        image = Image.open(BytesIO(content))
        image.verify()
        image = Image.open(BytesIO(content))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Файл не є коректним зображенням.") from exc
    if image.width < 20 or image.height < 20:
        raise ValueError("Зображення має надто малий розмір.")
    if max(image.size) > MAX_DIMENSION:
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    filename = f"{secrets.token_hex(16)}.webp"
    target = upload_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=86, method=6)
    return f"/static/uploads/{filename}"
