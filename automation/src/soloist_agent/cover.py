from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


CANVAS_SIZE = (1080, 1350)
FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/SFNS.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    if not words:
        return ["SOLOIST"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines[:3]


def _gradient_overlay(size: tuple[int, int], start_y: int) -> Image.Image:
    width, height = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    span = max(1, height - start_y)
    for y in range(start_y, height):
        alpha = int(225 * ((y - start_y) / span) ** 0.72)
        draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
    return overlay


def create_product_cover(image_bytes: bytes, title: str) -> bytes:
    """Create a 4:5 editorial cover from a product photo."""
    with Image.open(BytesIO(image_bytes)) as source_image:
        source = ImageOps.exif_transpose(source_image).convert("RGB")

    background = ImageOps.fit(source, CANVAS_SIZE, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(28))
    background = ImageEnhance.Color(background).enhance(0.72)
    background = ImageEnhance.Brightness(background).enhance(0.42).convert("RGBA")

    canvas = Image.new("RGBA", CANVAS_SIZE, (15, 15, 15, 255))
    canvas.alpha_composite(background)
    draw = ImageDraw.Draw(canvas)

    eyebrow_font = _font(25)
    draw.text((72, 60), "SOLOIST / SELECTED", font=eyebrow_font, fill=(255, 255, 255, 210))
    draw.line((72, 103, 1008, 103), fill=(255, 255, 255, 80), width=2)

    panel_size = (842, 1050)
    panel = Image.new("RGBA", panel_size, (20, 20, 20, 255))
    product = ImageOps.fit(source, panel_size, method=Image.Resampling.LANCZOS).convert("RGBA")
    panel.alpha_composite(product)
    panel.alpha_composite(_gradient_overlay(panel_size, 625))

    panel_draw = ImageDraw.Draw(panel)
    title_font = _font(58)
    lines = _wrap_text(panel_draw, title.upper(), title_font, 720)
    line_height = 70
    title_y = 1010 - line_height * len(lines)
    for line in lines:
        panel_draw.text((58, title_y), line, font=title_font, fill="white", stroke_width=1)
        title_y += line_height

    label_font = _font(21)
    panel_draw.text((61, 1004), "NEW DROP  •  SOLOIST STORE", font=label_font, fill=(255, 255, 255, 190))

    rotated = panel.rotate(-2.2, resample=Image.Resampling.BICUBIC, expand=True)
    shadow = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((18, 18, rotated.width - 18, rotated.height - 18), 28, fill=(0, 0, 0, 175))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))

    x = (CANVAS_SIZE[0] - rotated.width) // 2
    y = 150
    canvas.alpha_composite(shadow, (x + 12, y + 18))
    canvas.alpha_composite(rotated, (x, y))

    footer_font = _font(22)
    footer = "SOLOIST"
    footer_box = draw.textbbox((0, 0), footer, font=footer_font)
    draw.text((1008 - (footer_box[2] - footer_box[0]), 1300), footer, font=footer_font, fill=(255, 255, 255, 220))

    output = BytesIO()
    canvas.convert("RGB").save(output, format="JPEG", quality=91, optimize=True, progressive=True)
    return output.getvalue()
