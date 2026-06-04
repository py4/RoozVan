"""Apply the RoozVan logo watermark to generated story and post images."""

from __future__ import annotations

import functools
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_LOGO_PATH = Path("assets/logo.png")
DEFAULT_LOGO_WIDTH_FRACTION = 0.12
DEFAULT_LOGO_MARGIN_FRACTION = 0.03
BACKING_PADDING_FRACTION = 0.14
DARK_REGION_LUMINANCE_THRESHOLD = 125
DARK_BACKING_ALPHA = 255
LIGHT_BACKING_ALPHA = 215


@functools.lru_cache(maxsize=4)
def _load_logo_rgba(logo_path: str) -> Image.Image:
    logo = Image.open(logo_path).convert("RGBA")
    width, height = logo.size
    circle_mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(circle_mask)
    inset = round(min(width, height) * 0.035)
    draw.ellipse((inset, inset, width - inset - 1, height - inset - 1), fill=255)

    gray = logo.convert("L")
    white_mask = gray.point(lambda value: 0 if value > 245 else 255)
    alpha = Image.composite(white_mask, Image.new("L", (width, height), 0), circle_mask)
    logo.putalpha(alpha)
    return logo


def _mean_luminance(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = box
    left = max(0, left)
    top = max(0, top)
    right = min(image.width, right)
    bottom = min(image.height, bottom)
    if right <= left or bottom <= top:
        return 255.0
    region = image.crop((left, top, right, bottom)).convert("L")
    pixels = region.getdata()
    if not pixels:
        return 255.0
    return sum(pixels) / len(pixels)


def _logo_backing(
    logo_width: int,
    logo_height: int,
    *,
    padding_px: int,
    alpha: int,
) -> Image.Image:
    plate_width = logo_width + 2 * padding_px
    plate_height = logo_height + 2 * padding_px
    plate = Image.new("RGBA", (plate_width, plate_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    draw.ellipse((0, 0, plate_width - 1, plate_height - 1), fill=(255, 255, 255, alpha))
    return plate


def apply_logo_overlay(
    image_path: Path | str,
    *,
    logo_path: Path | str = DEFAULT_LOGO_PATH,
    width_fraction: float = DEFAULT_LOGO_WIDTH_FRACTION,
    margin_fraction: float = DEFAULT_LOGO_MARGIN_FRACTION,
) -> Path:
    """Stamp a small logo on the bottom-left of an image file (in place)."""
    path = Path(image_path)
    logo_file = Path(logo_path)
    if not logo_file.is_file():
        raise FileNotFoundError(f"Logo file not found: {logo_file}")

    base = Image.open(path).convert("RGBA")
    logo = _load_logo_rgba(str(logo_file.resolve()))

    target_width = max(1, round(base.width * width_fraction))
    scale = target_width / logo.width
    target_height = max(1, round(logo.height * scale))
    logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)

    margin = max(1, round(min(base.width, base.height) * margin_fraction))
    position = (margin, base.height - target_height - margin)
    padding_px = max(4, round(target_width * BACKING_PADDING_FRACTION))
    backing_box = (
        position[0] - padding_px,
        position[1] - padding_px,
        position[0] + target_width + padding_px,
        position[1] + target_height + padding_px,
    )
    luminance = _mean_luminance(base, backing_box)
    backing_alpha = DARK_BACKING_ALPHA if luminance < DARK_REGION_LUMINANCE_THRESHOLD else LIGHT_BACKING_ALPHA
    backing = _logo_backing(
        target_width,
        target_height,
        padding_px=padding_px,
        alpha=backing_alpha,
    )
    backing_position = (position[0] - padding_px, position[1] - padding_px)
    base.alpha_composite(backing, backing_position)
    base.alpha_composite(logo, position)

    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        base.convert("RGB").save(path, format="JPEG", quality=95, optimize=True)
    elif suffix == ".webp":
        base.save(path, format="WEBP", quality=95)
    else:
        base.save(path, format="PNG")

    return path
