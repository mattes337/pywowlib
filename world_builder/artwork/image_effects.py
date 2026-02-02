"""
Reusable image effects for procedural artwork generation.

Provides gradient generation, relief shading (hillshading), texture noise,
edge/coastline detection, radial glow, and lightning arc drawing.  All
routines operate on Pillow Image objects and accept/return them so they
compose naturally in a pipeline.

Dependencies:
    Pillow  -- image manipulation
    NumPy   -- array math for shading and noise
    SciPy   -- morphological operations and Sobel filter (optional graceful fallback)
"""

import math
import random
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    raise ImportError(
        "Pillow is required for artwork generation.  Install with: pip install Pillow"
    )

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "NumPy is required for artwork generation.  Install with: pip install numpy"
    )

_HAS_SCIPY = False
try:
    from scipy.ndimage import sobel as _scipy_sobel
    from scipy.ndimage import zoom as _scipy_zoom
    from scipy.ndimage import binary_dilation as _scipy_binary_dilation
    from scipy.ndimage import binary_erosion as _scipy_binary_erosion
    _HAS_SCIPY = True
except ImportError:
    log.warning(
        "SciPy not available -- hillshading and coastline effects will use "
        "simplified fallback algorithms.  Install with: pip install scipy"
    )


# ---------------------------------------------------------------------------
# Gradient generation
# ---------------------------------------------------------------------------

def generate_vertical_gradient(size, top_color, bottom_color):
    """
    Create a vertical linear gradient from *top_color* to *bottom_color*.

    Args:
        size:         (width, height) tuple.
        top_color:    RGB tuple at the top edge.
        bottom_color: RGB tuple at the bottom edge.

    Returns:
        Pillow RGB Image.
    """
    width, height = size
    img = Image.new('RGB', size)
    pixels = img.load()

    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        row_color = (r, g, b)
        for x in range(width):
            pixels[x, y] = row_color

    return img


def generate_solid_background(size, color):
    """Create a solid-colour RGB image."""
    return Image.new('RGB', size, color)


# ---------------------------------------------------------------------------
# Relief shading (hillshading)
# ---------------------------------------------------------------------------

def _resample_array(arr, target_height, target_width):
    """Resample a 2-D array to *(target_height, target_width)*."""
    if _HAS_SCIPY:
        scale_y = target_height / arr.shape[0]
        scale_x = target_width / arr.shape[1]
        return _scipy_zoom(arr, (scale_y, scale_x), order=1)

    # Simple nearest-neighbour fallback
    src_h, src_w = arr.shape
    out = np.empty((target_height, target_width), dtype=arr.dtype)
    for y in range(target_height):
        sy = int(y * src_h / target_height)
        for x in range(target_width):
            sx = int(x * src_w / target_width)
            out[y, x] = arr[min(sy, src_h - 1), min(sx, src_w - 1)]
    return out


def apply_relief_shading(img, heightmap, light_angle=315, intensity=0.4):
    """
    Apply hillshading to *img* using *heightmap* gradients.

    The light source is placed at *light_angle* (degrees, 0=North, CW) at
    45-degree elevation -- the WoW-standard north-west illumination.

    Args:
        img:         Pillow RGB Image to shade.
        heightmap:   2-D NumPy array (float, normalised 0-1).
        light_angle: Azimuth of the light source in degrees.
        intensity:   Blend factor (0 = no shading, 1 = full shading).

    Returns:
        Shaded Pillow RGB Image.
    """
    hm = np.asarray(heightmap, dtype=np.float64)

    if _HAS_SCIPY:
        dx = _scipy_sobel(hm, axis=1)
        dy = _scipy_sobel(hm, axis=0)
    else:
        # Simple central-difference gradient
        dx = np.zeros_like(hm)
        dy = np.zeros_like(hm)
        dx[:, 1:-1] = (hm[:, 2:] - hm[:, :-2]) / 2.0
        dy[1:-1, :] = (hm[2:, :] - hm[:-2, :]) / 2.0

    slope = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    aspect = np.arctan2(-dx, dy)

    azimuth_rad = np.radians(light_angle)
    altitude_rad = np.radians(45)

    shading = (np.cos(altitude_rad) * np.cos(slope) +
               np.sin(altitude_rad) * np.sin(slope) *
               np.cos(azimuth_rad - aspect))

    shading = ((shading + 1.0) / 2.0 * 255.0)
    shading = np.clip(shading, 0, 255).astype(np.uint8)

    # Resample to image dimensions
    shading_resized = _resample_array(shading, img.size[1], img.size[0])

    shading_img = Image.fromarray(shading_resized, mode='L').convert('RGB')
    result = ImageChops.multiply(img.convert('RGB'), shading_img)

    return Image.blend(img.convert('RGB'), result, intensity)


# ---------------------------------------------------------------------------
# Coastline effects
# ---------------------------------------------------------------------------

def add_coastline_effects(img, heightmap, water_level):
    """
    Enhance water edges with a dark-blue border and pale foam line.

    Uses morphological dilation/erosion when SciPy is available, otherwise
    falls back to a simplified edge-detection approach.

    Args:
        img:         Pillow RGBA or RGB Image.
        heightmap:   2-D NumPy array (float, normalised 0-1).
        water_level: Height threshold for the water surface.

    Returns:
        Pillow RGBA Image with coastline overlay.
    """
    hm = np.asarray(heightmap, dtype=np.float64)
    water_mask = hm <= water_level
    land_mask = ~water_mask

    if _HAS_SCIPY:
        water_dilated = _scipy_binary_dilation(water_mask, iterations=2)
        coastline_edge = water_dilated & land_mask

        land_eroded = _scipy_binary_erosion(land_mask, iterations=1)
        foam_line = land_mask & ~land_eroded
    else:
        # Simplified: pixels adjacent to water
        shifted_masks = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                shifted = np.zeros_like(water_mask)
                src_y = slice(max(0, -dy), hm.shape[0] + min(0, -dy))
                dst_y = slice(max(0, dy), hm.shape[0] + min(0, dy))
                src_x = slice(max(0, -dx), hm.shape[1] + min(0, -dx))
                dst_x = slice(max(0, dx), hm.shape[1] + min(0, dx))
                shifted[dst_y, dst_x] = water_mask[src_y, src_x]
                shifted_masks.append(shifted)
        any_water_neighbour = shifted_masks[0]
        for m in shifted_masks[1:]:
            any_water_neighbour = any_water_neighbour | m
        coastline_edge = any_water_neighbour & land_mask
        foam_line = coastline_edge  # reuse for simplicity

    # Resample masks to image size
    target_h, target_w = img.size[1], img.size[0]
    edge_resized = _resample_array(
        coastline_edge.astype(np.uint8), target_h, target_w
    )
    foam_resized = _resample_array(
        foam_line.astype(np.uint8), target_h, target_w
    )

    # Build RGBA overlay using NumPy for speed
    overlay_arr = np.zeros((target_h, target_w, 4), dtype=np.uint8)

    edge_mask = edge_resized > 0
    overlay_arr[edge_mask] = (0, 40, 80, 180)

    foam_mask = foam_resized > 0
    # Only apply foam where edge was not already drawn
    foam_only = foam_mask & ~edge_mask
    overlay_arr[foam_only] = (200, 220, 240, 120)

    overlay = Image.fromarray(overlay_arr, mode='RGBA')
    return Image.alpha_composite(img.convert('RGBA'), overlay)


# ---------------------------------------------------------------------------
# Radial glow
# ---------------------------------------------------------------------------

def add_radial_glow(img, center, color, radius, falloff=2.0):
    """
    Add a radial gradient glow at *center*.

    The glow intensity decreases with distance following
    ``(1 - d/radius) ** falloff``.

    Args:
        img:     Pillow Image (RGB or RGBA).
        center:  (x, y) centre of the glow.
        color:   RGB tuple for the glow colour.
        radius:  Maximum radius in pixels.
        falloff: Exponent controlling how fast the glow fades.

    Returns:
        Pillow RGBA Image with glow composited.
    """
    width, height = img.size
    cx, cy = center

    # Build distance array with NumPy for speed
    ys = np.arange(height) - cy
    xs = np.arange(width) - cx
    xx, yy = np.meshgrid(xs, ys)
    dist = np.sqrt(xx ** 2 + yy ** 2)

    mask = dist < radius
    intensity = np.zeros((height, width), dtype=np.float64)
    intensity[mask] = (1.0 - dist[mask] / radius) ** falloff
    alpha = (intensity * 200).clip(0, 255).astype(np.uint8)

    overlay_arr = np.zeros((height, width, 4), dtype=np.uint8)
    overlay_arr[..., 0] = color[0]
    overlay_arr[..., 1] = color[1]
    overlay_arr[..., 2] = color[2]
    overlay_arr[..., 3] = alpha

    overlay = Image.fromarray(overlay_arr, mode='RGBA')
    return Image.alpha_composite(img.convert('RGBA'), overlay)


# ---------------------------------------------------------------------------
# Lightning arcs
# ---------------------------------------------------------------------------

def add_lightning_arcs(img, color, branches=8, seed=None):
    """
    Draw branching lightning bolts across the image.

    Args:
        img:      Pillow Image (RGB or RGBA).
        color:    RGB tuple for the lightning colour.
        branches: Number of main lightning bolts.
        seed:     Optional random seed for reproducibility.

    Returns:
        Pillow RGBA Image with lightning composited.
    """
    rng = random.Random(seed)
    width, height = img.size

    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    fill_color = color + (200,)
    glow_color = color + (80,)

    for _ in range(branches):
        x = rng.randint(0, width - 1)
        y = 0
        points = [(x, y)]

        while y < height:
            x += rng.randint(-30, 30)
            x = max(0, min(width - 1, x))
            y += rng.randint(50, 100)
            points.append((x, min(y, height - 1)))

        # Draw glow (wider, semi-transparent)
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=glow_color, width=7)

        # Draw core line
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=fill_color, width=3)

        # Small sub-branches
        for pt in points[1:-1]:
            if rng.random() < 0.4:
                bx = pt[0] + rng.randint(-60, 60)
                by = pt[1] + rng.randint(20, 60)
                bx = max(0, min(width - 1, bx))
                by = max(0, min(height - 1, by))
                draw.line([pt, (bx, by)], fill=glow_color, width=2)

    return Image.alpha_composite(img.convert('RGBA'), overlay)


# ---------------------------------------------------------------------------
# Texture noise
# ---------------------------------------------------------------------------

def apply_texture_noise(img, amount=10, seed=None):
    """
    Add subtle per-pixel random noise to an image.

    Each pixel channel is offset by a random value in [-amount, +amount],
    clamped to [0, 255].

    Args:
        img:    Pillow Image (RGB or RGBA).
        amount: Maximum noise offset per channel.
        seed:   Optional random seed.

    Returns:
        Pillow Image of the same mode.
    """
    arr = np.array(img)
    rng = np.random.RandomState(seed)

    if arr.ndim == 3 and arr.shape[2] == 4:
        # RGBA -- only modify RGB channels
        noise = rng.randint(-amount, amount + 1, size=arr.shape[:2] + (3,))
        rgb = arr[..., :3].astype(np.int16) + noise
        arr[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    else:
        noise = rng.randint(-amount, amount + 1, size=arr.shape)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    return Image.fromarray(arr, mode=img.mode)
