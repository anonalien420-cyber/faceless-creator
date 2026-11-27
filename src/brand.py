"""Brand kit helpers: colour conversion + ASS/drawtext styling.

Stdlib only. The brand block in config.yaml (see src.models.Brand)
drives title cards, end cards, lower-thirds, the watermark, captions,
and thumbnails so every output looks like one channel.

ASS colours are &HAABBGGRR (alpha, blue, green, red — reversed RGB).
ffmpeg drawtext wants 0xRRGGBB or a name. PIL wants an (r, g, b) tuple.
These helpers convert one hex string to each form.
"""

from __future__ import annotations

import re

try:
    from src.models import Brand
except ImportError:  # pragma: no cover - direct script execution
    from models import Brand


def hex_to_rgb(value: str, default=(255, 255, 255)) -> tuple:
    """'#FFCB05' / 'FFCB05' / '#FC5' -> (255, 203, 5)."""
    if not value:
        return default
    text = str(value).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", text):
        text = "".join(ch * 2 for ch in text)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return default
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def ass_color(value: str, alpha: int = 0) -> str:
    """Hex -> ASS &HAABBGGRR colour string (alpha 0 = opaque)."""
    r, g, b = hex_to_rgb(value)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def drawtext_color(value: str) -> str:
    """Hex -> ffmpeg drawtext 0xRRGGBB colour string."""
    r, g, b = hex_to_rgb(value)
    return f"0x{r:02X}{g:02X}{b:02X}"


def load_brand(config: dict) -> Brand:
    return Brand.from_config(config)


def font_file(font_name: str) -> str:
    """Best-effort mapping of a brand font name to a DejaVu TTF filename
    used by PIL. Falls back to DejaVu Sans Bold (always shipped with the
    Docker image / fonts-dejavu package)."""
    name = (font_name or "").lower()
    if "mono" in name:
        return "DejaVuSansMono-Bold.ttf"
    if "serif" in name:
        return "DejaVuSerif-Bold.ttf"
    return "DejaVuSans-Bold.ttf"
