from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


WATERMARK_TERMS = (
    "线上商店",
    "线商店",
    "商店",
    "微店",
    "微信",
    "wechat",
    "whatsapp",
    "ydyj",
)


class ImageInspectionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OcrWord:
    block: int
    paragraph: int
    line: int
    left: int
    top: int
    width: int
    height: int
    confidence: float
    text: str


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())


def parse_tesseract_tsv(document: str) -> list[OcrWord]:
    words: list[OcrWord] = []
    for row in csv.DictReader(io.StringIO(document), delimiter="\t"):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1)
            words.append(
                OcrWord(
                    block=int(row.get("block_num") or 0),
                    paragraph=int(row.get("par_num") or 0),
                    line=int(row.get("line_num") or 0),
                    left=int(row.get("left") or 0),
                    top=int(row.get("top") or 0),
                    width=int(row.get("width") or 0),
                    height=int(row.get("height") or 0),
                    confidence=confidence,
                    text=text,
                )
            )
        except (TypeError, ValueError):
            continue
    return words


def overlay_reason(words: list[OcrWord], image_width: int, image_height: int) -> str:
    if image_width <= 0 or image_height <= 0:
        return "invalid_image"

    recognized = _normalized_text(" ".join(word.text for word in words if word.confidence >= 30))
    for term in WATERMARK_TERMS:
        if _normalized_text(term) in recognized:
            return f"watermark:{term}"

    lines: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        if word.confidence < 58 or not _normalized_text(word.text):
            continue
        lines.setdefault((word.block, word.paragraph, word.line), []).append(word)

    for line_words in lines.values():
        left = min(word.left for word in line_words)
        top = min(word.top for word in line_words)
        right = max(word.left + word.width for word in line_words)
        bottom = max(word.top + word.height for word in line_words)
        width_ratio = (right - left) / image_width
        height_ratio = (bottom - top) / image_height
        center_y = (top + bottom) / 2 / image_height
        normalized_line = _normalized_text("".join(word.text for word in line_words))
        if len(normalized_line) < 2:
            continue
        if center_y <= 0.25 and width_ratio >= 0.12 and height_ratio >= 0.018:
            return "large_text_at_top"
        if 0.30 <= center_y <= 0.70 and width_ratio >= 0.24 and height_ratio <= 0.12:
            return "central_overlay"
    return ""


def inspect_image_bytes(payload: bytes) -> str:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ImageInspectionUnavailable("Для проверки фото не установлен Pillow.") from exc

    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise ImageInspectionUnavailable("Для проверки надписей не установлен Tesseract OCR.")

    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Изображение не читается.") from exc
    # Faint seller watermarks disappear if portrait photos are reduced too aggressively.
    image.thumbnail((2200, 2200))

    with tempfile.TemporaryDirectory(prefix="soloist-image-") as directory:
        path = Path(directory) / "photo.png"
        image.save(path, format="PNG")
        try:
            result = subprocess.run(
                [tesseract, str(path), "stdout", "-l", "eng+chi_sim", "--psm", "11", "tsv"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ImageInspectionUnavailable("Tesseract не смог проверить изображение.") from exc
    return overlay_reason(parse_tesseract_tsv(result.stdout), image.width, image.height)
