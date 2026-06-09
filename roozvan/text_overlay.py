"""Render Farsi RTL text overlays on text-free generated image backgrounds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REGULAR_FONTS = (
    str(REPO_ROOT / ".cache/fonts/fonts/ttf/Vazirmatn-Regular.ttf"),
    str(REPO_ROOT / "assets/fonts/Vazirmatn-Regular.ttf"),
    "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
DEFAULT_BOLD_FONTS = (
    str(REPO_ROOT / ".cache/fonts/fonts/ttf/Vazirmatn-Bold.ttf"),
    str(REPO_ROOT / "assets/fonts/Vazirmatn-Bold.ttf"),
    "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

RTL_LANGUAGE = "fa"
# Prefer breaking overlay copy at these separators before falling back to spaces.
CLAUSE_BREAK_CHARS = ("·", "،", "—", "|")
# Only merge when a line clearly continues an unclosed opener on the previous line.
CONTINUATION_OPENERS = ("(", "[", "«")
CONTINUATION_CLOSERS_PREFIX = (")", "]", "»")


@dataclass(frozen=True)
class OverlayText:
    kicker: str
    title: str
    body: str


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
    left, _, right, _ = draw.textbbox(
        (0, 0),
        text,
        font=font,
        direction="rtl",
        language=RTL_LANGUAGE,
    )
    return right - left


def _is_ascii_word(token: str) -> bool:
    cleaned = token.strip("()[]{}\"'«»")
    return bool(cleaned) and cleaned.isascii() and cleaned.replace("-", "").replace("'", "").isalnum()


def _is_safe_word_break(text: str, index: int) -> bool:
    left = text[:index].rstrip()
    right = text[index:].lstrip()
    if not left or not right:
        return True
    left_word = left.split()[-1]
    right_word = right.split()[0]
    if _is_ascii_word(left_word) and _is_ascii_word(right_word):
        return False
    return True


def _preferred_break_before(text: str, end: int) -> int:
    for index in range(end - 1, 0, -1):
        char = text[index]
        if char in CLAUSE_BREAK_CHARS:
            return index
        if char.isspace() and _is_safe_word_break(text, index):
            return index
    return -1


def _overlay_clauses(paragraph: str) -> list[str]:
    clauses = [paragraph.strip()]
    for separator in CLAUSE_BREAK_CHARS:
        expanded: list[str] = []
        for clause in clauses:
            parts = [part.strip() for part in clause.split(separator) if part.strip()]
            if len(parts) <= 1:
                expanded.append(clause)
                continue
            for index, part in enumerate(parts):
                if index == 0:
                    expanded.append(part)
                    continue
                if separator == "،":
                    expanded[-1] = f"{expanded[-1]}{separator} {part}"
                else:
                    expanded.append(f"{separator} {part}")
        clauses = expanded
    return [clause for clause in clauses if clause]


def _wrap_long_clause(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    clause = text.strip()
    if not clause:
        return []
    if text_width(draw, clause, font) <= max_width:
        return [clause]

    lines: list[str] = []
    start = 0
    length = len(clause)
    while start < length:
        while start < length and clause[start].isspace():
            start += 1
        if start >= length:
            break

        end = start + 1
        last_break = -1
        while end <= length:
            chunk = clause[start:end]
            break_at = _preferred_break_before(clause, end)
            if break_at >= start:
                last_break = break_at
            if text_width(draw, chunk.rstrip(), font) <= max_width:
                if end == length:
                    lines.append(clause[start:end].strip())
                    start = length
                    break
                end += 1
                continue
            if last_break > start:
                lines.append(clause[start:last_break].strip())
                start = last_break
            elif end > start + 1:
                lines.append(clause[start : end - 1].strip())
                start = end - 1
            else:
                lines.append(clause[start:end].strip())
                start = end
            break
        else:
            lines.append(clause[start:].strip())
            break
    return [line for line in lines if line]


def _has_unclosed_opener(text: str) -> bool:
    return text.count("(") > text.count(")") or text.count("[") > text.count("]")


def normalize_wrapped_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if normalized and (
            normalized[-1].endswith(CONTINUATION_OPENERS)
            or _has_unclosed_opener(normalized[-1])
            or stripped.startswith(CONTINUATION_CLOSERS_PREFIX)
        ):
            normalized[-1] = f"{normalized[-1]} {stripped}"
            continue
        normalized.append(stripped)
    return normalized


def wrap_rtl_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue

        clauses = _overlay_clauses(paragraph)
        if not clauses:
            lines.append("")
            continue

        current = ""
        for clause in clauses:
            piece = clause
            candidate = f"{current} {piece}".strip() if current else piece
            if text_width(draw, candidate, font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            for subline in _wrap_long_clause(draw, piece, font, max_width):
                lines.append(subline)
            current = ""

        if current:
            lines.append(current)

    merged = normalize_wrapped_lines(lines)
    fitted: list[str] = []
    for line in merged:
        if text_width(draw, line, font) <= max_width:
            fitted.append(line)
            continue
        fitted.extend(_wrap_long_clause(draw, line, font, max_width))
    return fitted


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
    bbox = draw.textbbox(
        (right, y),
        text,
        font=font,
        anchor="rt",
        direction="rtl",
        language=RTL_LANGUAGE,
    )
    draw.text(
        (right, y),
        text,
        font=font,
        fill=fill,
        anchor="rt",
        direction="rtl",
        language=RTL_LANGUAGE,
    )
    return bbox[3] - bbox[1]


def render_overlay(
    background_path: Path,
    output_path: Path,
    overlay_text: OverlayText,
    *,
    regular_font_path: Path | None = None,
    bold_font_path: Path | None = None,
    show_kicker: bool = True,
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

    if show_kicker and overlay_text.kicker.strip():
        kicker_font = load_font(bold_font_path, round(image.width * 0.038))
        kicker_padding_x = round(image.width * 0.028)
        kicker_padding_y = round(image.width * 0.012)
        kicker_width = text_width(draw, overlay_text.kicker, kicker_font)
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
            overlay_text.kicker,
            right=right - kicker_padding_x,
            y=y + kicker_padding_y,
            font=kicker_font,
            fill=(255, 255, 255, 255),
        )
        y += kicker_height + round(image.height * 0.022)

    title_font, title_lines = fit_font_size(
        draw,
        bold_font_path,
        overlay_text.title,
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
        overlay_text.body,
        max_width=max_width,
        max_lines=5,
        start_size=round(image.width * 0.040),
        min_size=round(image.width * 0.028),
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
