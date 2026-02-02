"""
Subzone discovery overlay generator for WoW WotLK 3.3.5a.

Produces the coloured overlay textures that are revealed as a player
discovers subzones (WorldMapOverlay.dbc entries).  Each overlay is a
tightly-cropped RGBA silhouette of the subzone boundary with a
characteristic colour, subtle noise, and an optional glowing border.
"""

import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise ImportError(
        "Pillow is required for subzone overlay generation.  "
        "Install with: pip install Pillow"
    )

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "NumPy is required for subzone overlay generation.  "
        "Install with: pip install numpy"
    )

_HAS_SCIPY = False
try:
    from scipy.ndimage import binary_dilation as _scipy_binary_dilation
    _HAS_SCIPY = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# World map constants (standard WoW dimensions)
# ---------------------------------------------------------------------------

_WORLD_MAP_WIDTH = 1002
_WORLD_MAP_HEIGHT = 668


# ---------------------------------------------------------------------------
# Boundary -> pixel helpers
# ---------------------------------------------------------------------------

def _extract_subzone_boundary(boundary, world_bounds, padding=10):
    """
    Convert subzone world-coordinate boundary to local pixel coordinates
    inside a tightly-cropped bounding box.

    Args:
        boundary:     List of (wx, wy) vertices.
        world_bounds: (left, right, top, bottom) of the full world map.
        padding:      Extra pixels around the bounding box.

    Returns:
        (bbox_size, local_pixels, map_offset)
        bbox_size:    (width, height) of the cropped region.
        local_pixels: List of (px, py) polygon vertices in local coords.
        map_offset:   (offset_x, offset_y) position on the full world map.
    """
    left, right, top, bottom = world_bounds
    w_span = right - left
    h_span = bottom - top

    # Normalise to [0, 1] and then to world-map pixels
    norm = []
    for wx, wy in boundary:
        nx = (wx - left) / w_span
        ny = (wy - top) / h_span
        norm.append((nx * _WORLD_MAP_WIDTH, ny * _WORLD_MAP_HEIGHT))

    # Bounding box in world-map pixel space
    min_px = min(p[0] for p in norm)
    max_px = max(p[0] for p in norm)
    min_py = min(p[1] for p in norm)
    max_py = max(p[1] for p in norm)

    width = int(max_px - min_px) + padding * 2
    height = int(max_py - min_py) + padding * 2

    # Ensure minimum size
    width = max(width, 16)
    height = max(height, 16)

    # Translate to local coordinates (relative to top-left of bbox)
    local_pixels = [
        (int(p[0] - min_px) + padding, int(p[1] - min_py) + padding)
        for p in norm
    ]

    map_offset = (int(min_px) - padding, int(min_py) - padding)

    return (width, height), local_pixels, map_offset


# ---------------------------------------------------------------------------
# Silhouette mask
# ---------------------------------------------------------------------------

def _create_silhouette_mask(pixels, size):
    """
    Create a grayscale mask from a filled polygon.

    Args:
        pixels: List of (x, y) polygon vertices.
        size:   (width, height) of the output mask.

    Returns:
        Pillow 'L' mode Image (0 = outside, 255 = inside).
    """
    mask = Image.new('L', size, 0)
    if len(pixels) >= 3:
        draw = ImageDraw.Draw(mask)
        draw.polygon(pixels, fill=255)
    return mask


# ---------------------------------------------------------------------------
# Colour and noise application
# ---------------------------------------------------------------------------

def _apply_overlay_style(mask, color_theme, alpha=180, noise_amount=10, seed=None):
    """
    Fill the masked area with *color_theme*, optional noise, and alpha.

    Args:
        mask:         Pillow 'L' mode mask image.
        color_theme:  (r, g, b) base colour.
        alpha:        Fill opacity (0-255).  ~70 % = 180.
        noise_amount: Maximum per-channel noise offset.
        seed:         Optional random seed.

    Returns:
        Pillow RGBA Image.
    """
    rng = np.random.RandomState(seed)
    w, h = mask.size
    mask_arr = np.array(mask)
    inside = mask_arr > 128

    img_arr = np.zeros((h, w, 4), dtype=np.uint8)

    # Generate noise for all inside pixels
    count = int(np.sum(inside))
    if count == 0:
        return Image.fromarray(img_arr, mode='RGBA')

    noise = rng.randint(-noise_amount, noise_amount + 1, size=(count, 3))
    base = np.array(color_theme, dtype=np.int16)
    colours = np.clip(base + noise, 0, 255).astype(np.uint8)

    img_arr[inside, 0] = colours[:, 0]
    img_arr[inside, 1] = colours[:, 1]
    img_arr[inside, 2] = colours[:, 2]
    img_arr[inside, 3] = alpha

    return Image.fromarray(img_arr, mode='RGBA')


# ---------------------------------------------------------------------------
# Border glow
# ---------------------------------------------------------------------------

def _add_border_glow(img, mask, glow_color=(255, 255, 255), glow_alpha=128):
    """
    Add a glowing border around the edges of *mask*.

    Uses morphological dilation to find edge pixels (dilated - original).

    Args:
        img:        Pillow RGBA overlay image.
        mask:       Pillow 'L' mode silhouette mask.
        glow_color: RGB colour for the glow pixels.
        glow_alpha: Alpha value for glow pixels.

    Returns:
        Pillow RGBA Image with border composited.
    """
    mask_arr = np.array(mask) > 128

    if _HAS_SCIPY:
        dilated = _scipy_binary_dilation(mask_arr, iterations=1)
    else:
        # Simple manual dilation (shift in 4 directions)
        dilated = mask_arr.copy()
        if mask_arr.shape[0] > 1:
            dilated[1:, :] |= mask_arr[:-1, :]
            dilated[:-1, :] |= mask_arr[1:, :]
        if mask_arr.shape[1] > 1:
            dilated[:, 1:] |= mask_arr[:, :-1]
            dilated[:, :-1] |= mask_arr[:, 1:]

    edges = dilated & ~mask_arr

    border_arr = np.zeros((mask_arr.shape[0], mask_arr.shape[1], 4), dtype=np.uint8)
    border_arr[edges, 0] = glow_color[0]
    border_arr[edges, 1] = glow_color[1]
    border_arr[edges, 2] = glow_color[2]
    border_arr[edges, 3] = glow_alpha

    border = Image.fromarray(border_arr, mode='RGBA')
    return Image.alpha_composite(img, border)


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

def generate_subzone_overlay(subzone, world_bounds, padding=10, seed=None):
    """
    Generate a single subzone discovery overlay.

    Pipeline:
        1. Convert boundary to local pixel coordinates
        2. Create silhouette mask (filled polygon)
        3. Apply colour + noise
        4. Add border glow

    Args:
        subzone:      A SubzoneDefinition (or any object with *name*,
                      *boundary*, and *color_theme* attributes).
        world_bounds: (left, right, top, bottom) world coordinates.
        padding:      Pixels of padding around the subzone bounding box.
        seed:         Optional random seed for reproducible noise.

    Returns:
        dict with keys:
            'image'        -- Pillow RGBA Image
            'map_position' -- (x, y) offset on the full world map
            'size'         -- (width, height)
    """
    bbox_size, local_pixels, map_offset = _extract_subzone_boundary(
        subzone.boundary, world_bounds, padding=padding,
    )

    mask = _create_silhouette_mask(local_pixels, bbox_size)
    styled = _apply_overlay_style(mask, subzone.color_theme, seed=seed)
    styled = _add_border_glow(styled, mask)

    return {
        'image': styled,
        'map_position': map_offset,
        'size': bbox_size,
    }


def generate_subzone_overlays(subzones, world_map_bounds, padding=10):
    """
    Generate overlays for all subzones.

    Args:
        subzones:        List of SubzoneDefinition objects.
        world_map_bounds: (left, right, top, bottom) world coordinates.
        padding:         Pixels of padding per overlay.

    Returns:
        dict mapping subzone name (str) to RGBA Pillow Image.
    """
    results = {}
    for idx, sz in enumerate(subzones):
        log.info("Generating overlay %d/%d: %s", idx + 1, len(subzones), sz.name)
        info = generate_subzone_overlay(
            sz, world_map_bounds, padding=padding, seed=idx,
        )
        results[sz.name] = info['image']

    log.info("Generated %d subzone overlays", len(results))
    return results
