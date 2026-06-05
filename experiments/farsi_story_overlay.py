#!/usr/bin/env python3
"""Overlay Farsi story text on an existing text-free generated image."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roozvan.models import ScoredItem
from run_pipeline import write_html_report, write_json


DEFAULT_REGULAR_FONTS = (
    str(ROOT_DIR / ".cache/fonts/fonts/ttf/Vazirmatn-Regular.ttf"),
    str(ROOT_DIR / "assets/fonts/Vazirmatn-Regular.ttf"),
    "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
DEFAULT_BOLD_FONTS = (
    str(ROOT_DIR / ".cache/fonts/fonts/ttf/Vazirmatn-Bold.ttf"),
    str(ROOT_DIR / "assets/fonts/Vazirmatn-Bold.ttf"),
    "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


@dataclass(frozen=True)
class StoryText:
    kicker: str
    title: str
    body: str


OVERLAY_CATEGORY_LABELS_FA = {
    "transit": "حمل‌ونقل",
    "traffic": "ترافیک",
    "money": "هزینه‌ها",
    "jobs": "کار",
    "weather": "هواشناسی",
    "event": "رویداد",
    "food": "خوراکی",
    "travel": "سفر",
    "community": "جامعه",
    "lifestyle": "زندگی ونکوور",
    "sports": "ورزش",
    "culture": "فرهنگ",
    "safety": "ایمنی",
    "government": "دولت",
    "other": "ونکوور",
}


def overlay_category_label_fa(category: str | None) -> str:
    return OVERLAY_CATEGORY_LABELS_FA.get(str(category or "").strip(), "ونکوور")


def first_existing_path(candidates: tuple[str, ...]) -> Path:
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(f"None of these font paths exist: {candidates!r}")


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    layout_engine = ImageFont.Layout.RAQM if hasattr(ImageFont.Layout, "RAQM") else None
    if layout_engine is not None:
        return ImageFont.truetype(str(path), size, layout_engine=layout_engine)
    return ImageFont.truetype(str(path), size)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, direction="rtl")
    return right - left


def wrap_rtl_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width(draw, candidate, font) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
        lines.append(current)
    return lines


def fit_font_size(
    draw: ImageDraw.ImageDraw,
    font_path: Path,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    start_size: int,
    min_size: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(start_size, min_size - 1, -2):
        font = load_font(font_path, size)
        lines = wrap_rtl_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = load_font(font_path, min_size)
    return font, wrap_rtl_text(draw, text, font, max_width)


def add_top_gradient(base: Image.Image, height: int) -> Image.Image:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pixels = overlay.load()
    width = base.width
    for y in range(min(height, base.height)):
        if y < height * 0.72:
            alpha = 178
        else:
            alpha = round(178 * (1 - ((y - height * 0.72) / (height * 0.28))))
        for x in range(width):
            pixels[x, y] = (0, 0, 0, max(0, min(178, alpha)))
    return Image.alpha_composite(base.convert("RGBA"), overlay)


def draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, int, int, int],
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def draw_rtl_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    right: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
) -> int:
    bbox = draw.textbbox((right, y), text, font=font, anchor="rt", direction="rtl")
    draw.text((right, y), text, font=font, fill=fill, anchor="rt", direction="rtl")
    return bbox[3] - bbox[1]


def render_overlay(
    background_path: Path,
    output_path: Path,
    story_text: StoryText,
    *,
    regular_font_path: Path | None = None,
    bold_font_path: Path | None = None,
) -> Path:
    bold_font_path = bold_font_path or first_existing_path(DEFAULT_BOLD_FONTS)
    regular_font_path = regular_font_path or first_existing_path(DEFAULT_REGULAR_FONTS)

    image = Image.open(background_path).convert("RGBA")
    image = add_top_gradient(image, round(image.height * 0.44))
    draw = ImageDraw.Draw(image)

    margin_x = round(image.width * 0.075)
    max_width = image.width - 2 * margin_x
    right = image.width - margin_x
    y = round(image.height * 0.052)

    kicker_font = load_font(bold_font_path, round(image.width * 0.038))
    kicker_padding_x = round(image.width * 0.028)
    kicker_padding_y = round(image.width * 0.012)
    kicker_width = text_width(draw, story_text.kicker, kicker_font)
    kicker_height = round(image.width * 0.064)
    chip = (
        right - kicker_width - 2 * kicker_padding_x,
        y,
        right,
        y + kicker_height,
    )
    draw_rounded_rect(draw, chip, radius=round(kicker_height * 0.45), fill=(23, 118, 99, 235))
    draw_rtl_line(
        draw,
        story_text.kicker,
        right=right - kicker_padding_x,
        y=y + kicker_padding_y,
        font=kicker_font,
        fill=(255, 255, 255, 255),
    )
    y += kicker_height + round(image.height * 0.022)

    title_font, title_lines = fit_font_size(
        draw,
        bold_font_path,
        story_text.title,
        max_width=max_width,
        max_lines=3,
        start_size=round(image.width * 0.071),
        min_size=round(image.width * 0.052),
    )
    title_line_gap = round(title_font.size * 0.17)
    for line in title_lines:
        line_height = draw_rtl_line(
            draw,
            line,
            right=right,
            y=y,
            font=title_font,
            fill=(255, 255, 255, 255),
        )
        y += line_height + title_line_gap

    y += round(image.height * 0.014)
    body_font, body_lines = fit_font_size(
        draw,
        regular_font_path,
        story_text.body,
        max_width=max_width,
        max_lines=4,
        start_size=round(image.width * 0.040),
        min_size=round(image.width * 0.032),
    )
    body_line_gap = round(body_font.size * 0.25)
    for line in body_lines:
        line_height = draw_rtl_line(
            draw,
            line,
            right=right,
            y=y,
            font=body_font,
            fill=(245, 248, 250, 245),
        )
        y += line_height + body_line_gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        image.convert("RGB").save(output_path, format="JPEG", quality=95, optimize=True)
    else:
        image.save(output_path)
    return output_path


def update_dump_preview(dump_dir: Path, source_index: int, image_path: Path) -> None:
    selected_path = dump_dir / "selected.json"
    data = json.loads(selected_path.read_text(encoding="utf-8"))
    for raw_item in data:
        if raw_item.get("source_index") == source_index:
            raw_item["item"]["story_image_path"] = str(image_path)
            break
    else:
        raise ValueError(f"source_index {source_index} not found in {selected_path}")
    write_json(selected_path, data)
    write_html_report(dump_dir / "index.html", [ScoredItem.from_dict(item) for item in data])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--kicker", default="حمل‌ونقل عمومی")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--regular-font", type=Path)
    parser.add_argument("--bold-font", type=Path)
    parser.add_argument("--dump-dir", type=Path)
    parser.add_argument("--source-index", type=int)
    args = parser.parse_args()

    render_overlay(
        args.background,
        args.output,
        StoryText(kicker=args.kicker, title=args.title, body=args.body),
        regular_font_path=args.regular_font,
        bold_font_path=args.bold_font,
    )
    if args.dump_dir is not None:
        if args.source_index is None:
            parser.error("--source-index is required with --dump-dir")
        update_dump_preview(args.dump_dir, args.source_index, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
