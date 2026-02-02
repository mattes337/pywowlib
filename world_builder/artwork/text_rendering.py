"""
Text rendering utilities for procedural artwork.

Provides WoW-style text with outlines and shadows, font loading with
platform-aware fallbacks, and convenience helpers for centred label
placement on map images.
"""

import os
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise ImportError(
        "Pillow is required for text rendering.  Install with: pip install Pillow"
    )


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

# Search order for fallback fonts.  First match wins.
_FONT_SEARCH_PATHS = [
    # Windows
    "C:/Windows/Fonts/georgia.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/times.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def load_font(size=18, bold=False):
    """
    Load a TrueType font at *size* points with platform fallbacks.

    Tries well-known system font paths before falling back to Pillow's
    built-in default bitmap font.

    Args:
        size: Point size of the font.
        bold: If True, prefer bold variants (best-effort).

    Returns:
        PIL ImageFont instance.
    """
    # Try bold variants first when requested
    if bold:
        bold_paths = [
            "C:/Windows/Fonts/georgiab.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        ]
        for path in bold_paths:
            try:
                return ImageFont.truetype(path, size=size)
            except (IOError, OSError):
                continue

    for path in _FONT_SEARCH_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except (IOError, OSError):
            continue

    log.warning("No TrueType font found; using Pillow default bitmap font.")
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Outlined text (WoW-style)
# ---------------------------------------------------------------------------

def draw_text_outlined(draw, position, text, font=None,
                       fill=(255, 255, 220), outline=(0, 0, 0),
                       outline_width=1):
    """
    Draw text with a solid outline by rendering in 8 directions.

    This replicates the WoW client's outlined label style.

    Args:
        draw:          PIL ImageDraw instance.
        position:      (x, y) top-left corner of the text.
        text:          String to render.
        font:          PIL ImageFont (default bitmap font if None).
        fill:          RGB text colour.
        outline:       RGB outline colour.
        outline_width: Pixel thickness of the outline.
    """
    if font is None:
        font = load_font()

    x, y = position

    # Draw outline (8 compass directions)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline)

    # Draw main fill
    draw.text((x, y), text, font=font, fill=fill)


def draw_text_shadowed(draw, position, text, font=None,
                       fill=(255, 240, 200), shadow=(0, 0, 0),
                       shadow_offset=(3, 3), outline=(100, 80, 50),
                       outline_width=2):
    """
    Draw text with both a drop shadow and an outline.

    Layer order: shadow -> outline -> fill text.

    Args:
        draw:          PIL ImageDraw instance.
        position:      (x, y) position of the text.
        text:          String to render.
        font:          PIL ImageFont (default bitmap font if None).
        fill:          RGB colour for the main text.
        shadow:        RGB colour for the drop shadow.
        shadow_offset: (dx, dy) pixel offset for the shadow.
        outline:       RGB colour for the outline.
        outline_width: Pixel thickness of the outline.
    """
    if font is None:
        font = load_font()

    x, y = position
    sx, sy = shadow_offset

    # 1. Shadow
    draw.text((x + sx, y + sy), text, font=font, fill=shadow)

    # 2. Outline
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline)

    # 3. Fill
    draw.text((x, y), text, font=font, fill=fill)


# ---------------------------------------------------------------------------
# Label placement helpers
# ---------------------------------------------------------------------------

def get_text_size(text, font=None):
    """
    Return (width, height) of *text* rendered with *font*.

    Uses a temporary ImageDraw to measure the bounding box.
    """
    if font is None:
        font = load_font()
    # Create 1x1 dummy image to access textbbox
    dummy = Image.new('RGB', (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def draw_centred_text(img, text, y_fraction=0.1, font=None,
                      fill=(255, 240, 200), shadow=(0, 0, 0),
                      outline=(100, 80, 50)):
    """
    Draw text horizontally centred on *img* at *y_fraction* from the top.

    Uses shadow + outline style (loading-screen style).

    Args:
        img:        Pillow Image to draw on (modified in place).
        text:       String to render.
        y_fraction: Vertical position as a fraction of image height.
        font:       PIL ImageFont (loads large serif if None).
        fill:       RGB main text colour.
        shadow:     RGB shadow colour.
        outline:    RGB outline colour.

    Returns:
        The same Image (modified in place).
    """
    if font is None:
        font = load_font(size=72)

    draw = ImageDraw.Draw(img)
    tw, th = get_text_size(text, font)

    x = (img.size[0] - tw) // 2
    y = int(img.size[1] * y_fraction)

    draw_text_shadowed(
        draw, (x, y), text, font=font,
        fill=fill, shadow=shadow, outline=outline,
        shadow_offset=(4, 4), outline_width=2,
    )
    return img
