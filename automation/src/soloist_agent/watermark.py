from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path


class WatermarkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WatermarkedImage:
    body: bytes
    content_type: str
    extension: str


FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
    "/Library/Fonts/Arial Bold Italic.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    try:
        return ImageFont.truetype("DejaVuSansCondensed-BoldOblique.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _spaced_width(draw, text: str, font, spacing: int, stroke_width: int) -> int:
    widths = [
        draw.textlength(character, font=font)
        for character in text
    ]
    return round(sum(widths) + spacing * max(0, len(text) - 1) + stroke_width * 2)


def _draw_spaced_text(
    draw,
    position: tuple[int, int],
    text: str,
    *,
    font,
    spacing: int,
    fill: tuple[int, int, int, int],
    stroke_width: int,
    stroke_fill: tuple[int, int, int, int],
) -> None:
    x, y = position
    for character in text:
        draw.text(
            (round(x), y),
            character,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        x += draw.textlength(character, font=font) + spacing


def apply_center_watermark(
    payload: bytes,
    *,
    text: str = "SOLOIST",
    opacity: int = 165,
) -> WatermarkedImage:
    """Place a centered editorial-style watermark on an image."""
    try:
        from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - Pillow is a runtime dependency
        raise WatermarkError("Pillow is required for image watermarking") from exc

    label = text.strip().upper() or "SOLOIST"
    alpha = max(25, min(230, int(opacity)))
    try:
        source = Image.open(io.BytesIO(payload))
        source = ImageOps.exif_transpose(source)
        source.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise WatermarkError("Unsupported image") from exc

    width, height = source.size
    if width < 80 or height < 80:
        raise WatermarkError("Image is too small")

    base = source.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(28, min(round(width * 0.17), round(height * 0.22)))
    font = _font(font_size)
    spacing = max(1, round(font_size * 0.025))
    stroke_width = max(2, round(font_size * 0.04))
    text_width = _spaced_width(draw, label, font, spacing, stroke_width)
    target_width = round(width * 0.78)
    if text_width > target_width:
        font_size = max(18, round(font_size * target_width / text_width))
        font = _font(font_size)
        spacing = max(1, round(font_size * 0.025))
        stroke_width = max(2, round(font_size * 0.04))
        text_width = _spaced_width(draw, label, font, spacing, stroke_width)

    bbox = draw.textbbox((0, 0), label, font=font, stroke_width=stroke_width)
    text_height = bbox[3] - bbox[1]
    x = round((width - text_width) / 2)
    y = round((height - text_height) / 2 - bbox[1])
    shadow = max(2, round(font_size * 0.045))

    _draw_spaced_text(
        draw,
        (x + shadow, y + shadow),
        label,
        font=font,
        spacing=spacing,
        fill=(0, 0, 0, max(45, round(alpha * 0.72))),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, max(50, round(alpha * 0.78))),
    )
    _draw_spaced_text(
        draw,
        (x, y),
        label,
        font=font,
        spacing=spacing,
        fill=(255, 255, 255, alpha),
        stroke_width=stroke_width,
        stroke_fill=(10, 10, 10, max(55, round(alpha * 0.78))),
    )

    result = Image.alpha_composite(base, overlay)
    output = io.BytesIO()
    has_transparency = source.mode in {"RGBA", "LA"} or "transparency" in source.info
    if has_transparency:
        result.save(output, format="PNG", optimize=True)
        return WatermarkedImage(output.getvalue(), "image/png", ".png")
    result.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    return WatermarkedImage(output.getvalue(), "image/jpeg", ".jpg")
