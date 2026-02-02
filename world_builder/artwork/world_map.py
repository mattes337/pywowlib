"""
World map art generator for WoW WotLK 3.3.5a.

Procedurally generates the stylised zone overview illustration shown when
the player opens the Map UI (WorldMapArea).  The pipeline is:

    heightmap -> terrain colour -> subzone overlays -> hillshading
              -> coastline effects -> subzone labels -> final image

All drawing is done with Pillow; SciPy is used for shading if available.
"""

import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise ImportError(
        "Pillow is required for world map generation.  Install with: pip install Pillow"
    )

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "NumPy is required for world map generation.  Install with: pip install numpy"
    )

from .color_palettes import PALETTES, ColorPalette, interpolate_terrain_color
from .image_effects import (
    apply_relief_shading,
    add_coastline_effects,
    _resample_array,
)
from .text_rendering import load_font, draw_text_outlined


# ---------------------------------------------------------------------------
# Subzone data holder
# ---------------------------------------------------------------------------

class SubzoneDefinition:
    """
    Lightweight container for a subzone's display metadata.

    Attributes:
        name:        Human-readable subzone name.
        boundary:    List of (world_x, world_y) vertices forming a closed polygon.
        color_theme: RGB tuple for the subzone's characteristic colour.
    """

    __slots__ = ('name', 'boundary', 'color_theme')

    def __init__(self, name, boundary, color_theme):
        self.name = name
        self.boundary = list(boundary)
        self.color_theme = tuple(color_theme)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _world_to_pixel(world_point, world_bounds, image_size):
    """
    Convert a single (wx, wy) world coordinate to (px, py) pixel coordinate.

    Args:
        world_point:  (wx, wy) world coordinate.
        world_bounds: (left, right, top, bottom) in world units.
        image_size:   (width, height) in pixels.

    Returns:
        (px, py) integer pixel coordinate.
    """
    left, right, top, bottom = world_bounds
    wx, wy = world_point
    px = int((wx - left) / (right - left) * image_size[0])
    py = int((wy - top) / (bottom - top) * image_size[1])
    return (px, py)


def _polygon_to_pixels(boundary, world_bounds, image_size):
    """Convert a list of world-coordinate vertices to pixel coordinates."""
    return [_world_to_pixel(pt, world_bounds, image_size) for pt in boundary]


def _polygon_centroid(points):
    """
    Return the centroid of a polygon given as a list of (x, y) tuples.

    Uses the arithmetic mean of the vertices (adequate for labels).
    """
    if not points:
        return (0, 0)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return (cx, cy)


# ---------------------------------------------------------------------------
# Terrain base layer
# ---------------------------------------------------------------------------

def generate_terrain_base(heightmap, water_level, palette, size):
    """
    Colour-code a heightmap into a terrain illustration.

    Each pixel is mapped from its height value to an RGB colour using
    :func:`interpolate_terrain_color`.  The heightmap is resampled to
    *size* before colouring.

    Args:
        heightmap:   2-D NumPy array (float, 0-1 normalised).
        water_level: Height threshold for the water surface.
        palette:     A :class:`ColorPalette` instance.
        size:        (width, height) output dimensions.

    Returns:
        Pillow RGB Image.
    """
    hm = np.asarray(heightmap, dtype=np.float64)
    resampled = _resample_array(hm, size[1], size[0])

    # Vectorised colour mapping via NumPy
    img_arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)

    for y in range(size[1]):
        for x in range(size[0]):
            color = interpolate_terrain_color(
                resampled[y, x], water_level, palette
            )
            img_arr[y, x, 0] = color[0]
            img_arr[y, x, 1] = color[1]
            img_arr[y, x, 2] = color[2]

    return Image.fromarray(img_arr, mode='RGB')


# ---------------------------------------------------------------------------
# Subzone colour overlay
# ---------------------------------------------------------------------------

def apply_subzone_colors(base_img, subzones, world_bounds):
    """
    Overlay translucent subzone colours onto *base_img*.

    Each subzone polygon is filled with its ``color_theme`` at 40 % opacity.

    Args:
        base_img:     Pillow RGB or RGBA Image.
        subzones:     List of :class:`SubzoneDefinition`.
        world_bounds: (left, right, top, bottom) in world units.

    Returns:
        Pillow RGBA Image.
    """
    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for subzone in subzones:
        pixels = _polygon_to_pixels(
            subzone.boundary, world_bounds, base_img.size
        )
        if len(pixels) < 3:
            continue
        rgba = subzone.color_theme + (102,)  # ~40 % alpha
        draw.polygon(pixels, fill=rgba)

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)


# ---------------------------------------------------------------------------
# Subzone labels
# ---------------------------------------------------------------------------

def add_subzone_labels(img, subzones, world_bounds, font_size=18):
    """
    Render outlined text labels at each subzone's centroid.

    Args:
        img:          Pillow Image (modified in place and returned).
        subzones:     List of :class:`SubzoneDefinition`.
        world_bounds: (left, right, top, bottom) in world units.
        font_size:    Label font size in points.

    Returns:
        The same Image with labels drawn.
    """
    draw = ImageDraw.Draw(img.convert('RGBA') if img.mode != 'RGBA' else img)
    font = load_font(size=font_size)

    for subzone in subzones:
        centroid = _polygon_centroid(subzone.boundary)
        px, py = _world_to_pixel(centroid, world_bounds, img.size)

        draw_text_outlined(
            draw, (px, py), subzone.name, font=font,
            fill=(255, 255, 220), outline=(0, 0, 0), outline_width=1,
        )

    return img


# ---------------------------------------------------------------------------
# World map bounds estimation
# ---------------------------------------------------------------------------

def _estimate_world_bounds(subzones, heightmap):
    """
    Estimate world-coordinate bounds from subzone boundary vertices.

    If no subzone boundaries are provided, defaults to a square centred
    at the origin that covers the heightmap aspect ratio.

    Returns:
        (left, right, top, bottom) tuple.
    """
    all_x = []
    all_y = []
    for sz in subzones:
        for wx, wy in sz.boundary:
            all_x.append(wx)
            all_y.append(wy)

    if all_x and all_y:
        margin_x = (max(all_x) - min(all_x)) * 0.05
        margin_y = (max(all_y) - min(all_y)) * 0.05
        return (
            min(all_x) - margin_x,
            max(all_x) + margin_x,
            min(all_y) - margin_y,
            max(all_y) + margin_y,
        )

    # Fallback: unit square scaled to heightmap shape
    h, w = heightmap.shape
    return (0.0, float(w), 0.0, float(h))


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

def generate_world_map(heightmap, subzones, water_level=0.0,
                       size=(1002, 668), zone_name="Zone",
                       color_palette=None):
    """
    Procedurally generate the complete world-map artwork.

    Pipeline:
        1. Terrain base layer (heightmap -> colour)
        2. Subzone colour overlays (40 % opacity polygons)
        3. Relief shading (hillshading)
        4. Coastline effects (edge + foam)
        5. Subzone name labels

    Args:
        heightmap:     2-D NumPy array (float, 0-1 normalised).
        subzones:      List of :class:`SubzoneDefinition`.
        water_level:   Height threshold for the water surface.
        size:          (width, height) output resolution.
        zone_name:     Zone name (metadata only).
        color_palette: A :class:`ColorPalette` or palette name string.
                       Defaults to 'temperate'.

    Returns:
        Pillow RGBA Image.
    """
    hm = np.asarray(heightmap, dtype=np.float64)

    # Resolve palette
    if color_palette is None:
        palette = PALETTES['temperate']
    elif isinstance(color_palette, str):
        palette = PALETTES.get(color_palette, PALETTES['temperate'])
    else:
        palette = color_palette

    world_bounds = _estimate_world_bounds(subzones, hm)

    # Step 1: terrain base
    log.info("Generating terrain base for '%s' at %s", zone_name, size)
    img = generate_terrain_base(hm, water_level, palette, size)

    # Step 2: subzone overlays
    if subzones:
        log.info("Applying subzone colour overlays (%d subzones)", len(subzones))
        img = apply_subzone_colors(img, subzones, world_bounds)

    # Step 3: relief shading
    log.info("Applying relief shading")
    img_rgb = img.convert('RGB') if img.mode != 'RGB' else img
    img_rgb = apply_relief_shading(img_rgb, hm, light_angle=315, intensity=0.4)
    img = img_rgb.convert('RGBA')

    # Step 4: coastline effects
    log.info("Adding coastline effects")
    img = add_coastline_effects(img, hm, water_level)

    # Step 5: subzone labels
    if subzones:
        log.info("Rendering subzone labels")
        img = add_subzone_labels(img, subzones, world_bounds)

    log.info("World map generation complete for '%s'", zone_name)
    return img
