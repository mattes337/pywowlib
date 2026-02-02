"""
Loading screen art generator for WoW WotLK 3.3.5a.

Procedurally generates scenic landscape compositions displayed when a
player enters a zone or dungeon instance.  Four visual themes are
supported, each assembling five layers (sky, background, midground,
foreground, accent) from simple geometric drawing primitives.

Themes:
    tropical    -- Sunset gradient sky, island silhouette, palm trees, ocean
    volcanic    -- Dark-red sky, volcanic peak, lava flows, black rocks
    underground -- Solid dark ceiling, cavern walls, stone pillars, crystals
    titan       -- Blue-grey gradient sky, titan architecture, lightning
"""

import math
import random as _random_mod
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise ImportError(
        "Pillow is required for loading screen generation.  "
        "Install with: pip install Pillow"
    )

from .image_effects import (
    generate_vertical_gradient,
    generate_solid_background,
    add_radial_glow,
    add_lightning_arcs,
)
from .text_rendering import draw_centred_text, load_font


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

LOADING_SCREEN_THEMES = {
    'tropical': {
        'sky': ('gradient', (255, 180, 100), (100, 150, 200)),
        'background': ('island_silhouette', (20, 60, 40)),
        'midground': ('palm_trees', (40, 80, 50)),
        'foreground': ('water_horizon', (50, 120, 180)),
        'accent': ('sun_glow', (255, 200, 100)),
    },
    'volcanic': {
        'sky': ('gradient', (60, 40, 40), (180, 80, 60)),
        'background': ('mountain_peak', (80, 50, 40)),
        'midground': ('lava_flows', (255, 100, 50)),
        'foreground': ('volcanic_rocks', (60, 40, 30)),
        'accent': ('fire_glow', (255, 150, 50)),
    },
    'underground': {
        'sky': ('solid', (20, 20, 30)),
        'background': ('cavern_walls', (40, 40, 50)),
        'midground': ('titan_pillars', (60, 60, 80)),
        'foreground': ('rocky_ground', (30, 30, 40)),
        'accent': ('energy_crystals', (100, 150, 255)),
    },
    'titan': {
        'sky': ('gradient', (40, 40, 60), (100, 100, 140)),
        'background': ('titan_architecture', (80, 80, 100)),
        'midground': ('titan_statues', (100, 100, 120)),
        'foreground': ('floor_tiles', (60, 60, 80)),
        'accent': ('arcane_lightning', (150, 200, 255)),
    },
}


# ---------------------------------------------------------------------------
# Sky layers
# ---------------------------------------------------------------------------

def _generate_sky(spec, size):
    """Generate the sky/background base layer."""
    layer_type = spec[0]
    if layer_type == 'gradient':
        return generate_vertical_gradient(size, spec[1], spec[2])
    elif layer_type == 'solid':
        return generate_solid_background(size, spec[1])
    return generate_solid_background(size, (0, 0, 0))


# ---------------------------------------------------------------------------
# Silhouette generators
# ---------------------------------------------------------------------------

def _generate_island_silhouette(size, color):
    """
    Procedural island landmass with a volcanic peak.

    Draws a curved base shape across the lower portion of the image with
    a triangular peak near the centre.
    """
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size

    # Island base (curved bottom area)
    base_points = [
        (0, h),
        (int(w * 0.15), int(h * 0.75)),
        (int(w * 0.3), int(h * 0.68)),
        (int(w * 0.5), int(h * 0.62)),
        (int(w * 0.7), int(h * 0.68)),
        (int(w * 0.85), int(h * 0.75)),
        (w, h),
    ]
    draw.polygon(base_points, fill=color + (255,))

    # Volcanic peak (triangle)
    peak_points = [
        (int(w * 0.42), int(h * 0.62)),
        (int(w * 0.50), int(h * 0.28)),
        (int(w * 0.58), int(h * 0.62)),
    ]
    draw.polygon(peak_points, fill=color + (255,))

    return img


def _generate_palm_trees(size, color, seed=None):
    """
    Procedural palm tree silhouettes (3-5 trees).

    Each tree has a narrow trunk and radiating elliptical fronds.
    """
    rng = _random_mod.Random(seed)
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size

    num_trees = rng.randint(3, 5)
    fill = color + (255,)

    for i in range(num_trees):
        x = (i + 1) * w // (num_trees + 1) + rng.randint(-20, 20)
        y_base = h - rng.randint(40, 120)
        trunk_h = rng.randint(100, 180)
        trunk_w = 8

        # Trunk
        draw.rectangle(
            [x - trunk_w // 2, y_base - trunk_h, x + trunk_w // 2, y_base],
            fill=fill,
        )

        # Fronds (ellipses radiating from top of trunk)
        top_y = y_base - trunk_h
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            fx = x + int(math.cos(rad) * 45)
            fy = top_y + int(math.sin(rad) * 30)
            draw.ellipse(
                [fx - 35, fy - 12, fx + 35, fy + 12],
                fill=fill,
            )

    return img


def _generate_mountain_peak(size, color):
    """Procedural mountain / volcanic peak silhouette."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (255,)

    # Main mountain
    draw.polygon([
        (0, h),
        (int(w * 0.35), int(h * 0.65)),
        (int(w * 0.50), int(h * 0.20)),
        (int(w * 0.65), int(h * 0.65)),
        (w, h),
    ], fill=fill)

    # Secondary peak
    draw.polygon([
        (int(w * 0.60), h),
        (int(w * 0.72), int(h * 0.50)),
        (int(w * 0.80), int(h * 0.35)),
        (int(w * 0.88), int(h * 0.50)),
        (w, h),
    ], fill=fill)

    return img


def _generate_lava_flows(size, color):
    """Procedural lava river streaks across the lower half."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (160,)

    rng = _random_mod.Random(42)  # deterministic
    for _ in range(5):
        x_start = rng.randint(int(w * 0.2), int(w * 0.8))
        y_start = rng.randint(int(h * 0.3), int(h * 0.5))
        pts = [(x_start, y_start)]
        for _ in range(6):
            x_start += rng.randint(-40, 40)
            y_start += rng.randint(30, 60)
            pts.append((max(0, min(w - 1, x_start)), min(h - 1, y_start)))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=fill, width=rng.randint(4, 10))

    return img


def _generate_volcanic_rocks(size, color):
    """Procedural dark rock formations along the bottom."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (255,)

    rng = _random_mod.Random(7)
    num_rocks = rng.randint(8, 14)
    for _ in range(num_rocks):
        cx = rng.randint(0, w)
        cy = rng.randint(int(h * 0.80), h)
        rw = rng.randint(30, 80)
        rh = rng.randint(20, 50)
        draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=fill)

    # Ground fill below rocks
    draw.rectangle([0, int(h * 0.92), w, h], fill=fill)

    return img


def _generate_cavern_walls(size, color):
    """Procedural cavern wall contours along the sides and top."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (200,)

    # Left wall
    draw.polygon([
        (0, 0), (int(w * 0.15), 0),
        (int(w * 0.12), int(h * 0.3)),
        (int(w * 0.08), int(h * 0.6)),
        (int(w * 0.10), h),
        (0, h),
    ], fill=fill)

    # Right wall
    draw.polygon([
        (w, 0), (int(w * 0.85), 0),
        (int(w * 0.88), int(h * 0.3)),
        (int(w * 0.92), int(h * 0.6)),
        (int(w * 0.90), h),
        (w, h),
    ], fill=fill)

    # Ceiling stalactites
    rng = _random_mod.Random(99)
    for _ in range(12):
        cx = rng.randint(int(w * 0.15), int(w * 0.85))
        tip_y = rng.randint(int(h * 0.05), int(h * 0.25))
        bw = rng.randint(10, 30)
        draw.polygon([
            (cx - bw, 0), (cx + bw, 0), (cx, tip_y),
        ], fill=fill)

    return img


def _generate_titan_pillars(size, color):
    """Procedural stone pillar silhouettes."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (220,)

    for i in range(3):
        cx = (i + 1) * w // 4
        pw = 50
        ph = int(h * 0.75)
        # Pillar body
        draw.rectangle([cx - pw // 2, h - ph, cx + pw // 2, h], fill=fill)
        # Capital (wider top)
        draw.rectangle([cx - pw, h - ph, cx + pw, h - ph + 20], fill=fill)

    return img


def _generate_rocky_ground(size, color):
    """Procedural ground fill with rocky bumps."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (255,)

    # Ground area
    ground_top = int(h * 0.85)
    rng = _random_mod.Random(55)

    points = [(0, h)]
    for x in range(0, w + 1, 20):
        y = ground_top + rng.randint(-8, 8)
        points.append((x, y))
    points.append((w, h))
    draw.polygon(points, fill=fill)

    return img


def _generate_energy_crystals(size, color):
    """Procedural glowing crystal clusters."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    rng = _random_mod.Random(33)

    for _ in range(6):
        cx = rng.randint(int(w * 0.15), int(w * 0.85))
        cy = rng.randint(int(h * 0.3), int(h * 0.7))
        ch = rng.randint(20, 60)
        cw = rng.randint(8, 20)

        # Crystal shape (narrow diamond)
        draw.polygon([
            (cx, cy - ch),
            (cx + cw, cy),
            (cx, cy + ch // 3),
            (cx - cw, cy),
        ], fill=color + (200,))

        # Glow halo
        draw.ellipse(
            [cx - ch, cy - ch, cx + ch, cy + ch],
            fill=color + (30,),
        )

    return img


def _generate_titan_architecture(size, color):
    """
    Procedural titan building silhouettes -- pillars, arches, beams.
    """
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (255,)

    pillar_w = 60
    num_pillars = 3

    for i in range(num_pillars):
        cx = (i + 1) * w // (num_pillars + 1)
        pillar_h = int(h * 0.80)

        # Pillar body
        draw.rectangle(
            [cx - pillar_w // 2, h - pillar_h, cx + pillar_w // 2, h],
            fill=fill,
        )

        # Arch top (semicircle approximation)
        arch_r = pillar_w
        draw.arc(
            [cx - arch_r, h - pillar_h - 50, cx + arch_r, h - pillar_h + 50],
            start=180, end=360, fill=fill, width=10,
        )

    # Connecting beam
    beam_y = h - int(h * 0.80)
    draw.rectangle([int(w * 0.10), beam_y, int(w * 0.90), beam_y + 20], fill=fill)

    return img


def _generate_titan_statues(size, color):
    """Procedural humanoid statue silhouettes."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (200,)

    # Two statues flanking centre
    for side in (-1, 1):
        cx = w // 2 + side * int(w * 0.25)
        base_y = int(h * 0.90)
        head_r = 25

        # Body (tall rectangle)
        body_w = 40
        body_h = int(h * 0.45)
        draw.rectangle(
            [cx - body_w // 2, base_y - body_h, cx + body_w // 2, base_y],
            fill=fill,
        )

        # Head (circle)
        head_y = base_y - body_h - head_r
        draw.ellipse(
            [cx - head_r, head_y - head_r, cx + head_r, head_y + head_r],
            fill=fill,
        )

        # Shoulders (wider rectangle)
        draw.rectangle(
            [cx - body_w, base_y - body_h, cx + body_w, base_y - body_h + 20],
            fill=fill,
        )

    return img


def _generate_floor_tiles(size, color):
    """Procedural tiled floor perspective pattern."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (255,)
    line_color = tuple(min(c + 30, 255) for c in color) + (180,)

    # Ground base
    ground_top = int(h * 0.80)
    draw.rectangle([0, ground_top, w, h], fill=fill)

    # Grid lines (perspective converging toward horizon)
    horizon_y = ground_top
    vanishing_x = w // 2

    # Vertical perspective lines
    for i in range(10):
        x = i * w // 9
        draw.line([(x, h), (vanishing_x, horizon_y)], fill=line_color, width=1)

    # Horizontal lines (spaced more at bottom)
    for i in range(1, 8):
        frac = (i / 8.0) ** 1.5
        y = horizon_y + int((h - horizon_y) * frac)
        draw.line([(0, y), (w, y)], fill=line_color, width=1)

    return img


def _generate_water_horizon(size, color):
    """Procedural ocean horizon with wave hints."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    fill = color + (200,)

    # Water body (lower 40%)
    water_top = int(h * 0.60)
    draw.rectangle([0, water_top, w, h], fill=fill)

    # Subtle wave lines
    rng = _random_mod.Random(11)
    highlight = tuple(min(c + 40, 255) for c in color) + (80,)
    for _ in range(6):
        y = rng.randint(water_top + 10, h - 10)
        x_start = rng.randint(0, w // 3)
        x_end = x_start + rng.randint(50, 200)
        draw.line([(x_start, y), (min(x_end, w), y)], fill=highlight, width=1)

    return img


# ---------------------------------------------------------------------------
# Layer dispatcher
# ---------------------------------------------------------------------------

_LAYER_GENERATORS = {
    'island_silhouette': _generate_island_silhouette,
    'palm_trees': _generate_palm_trees,
    'mountain_peak': _generate_mountain_peak,
    'lava_flows': _generate_lava_flows,
    'volcanic_rocks': _generate_volcanic_rocks,
    'cavern_walls': _generate_cavern_walls,
    'titan_pillars': _generate_titan_pillars,
    'rocky_ground': _generate_rocky_ground,
    'energy_crystals': _generate_energy_crystals,
    'titan_architecture': _generate_titan_architecture,
    'titan_statues': _generate_titan_statues,
    'floor_tiles': _generate_floor_tiles,
    'water_horizon': _generate_water_horizon,
}


def _generate_layer(spec, size):
    """
    Generate a single composition layer from its *spec*.

    Returns an RGBA Image.
    """
    layer_type = spec[0]
    color = spec[1] if len(spec) > 1 else (128, 128, 128)

    gen_func = _LAYER_GENERATORS.get(layer_type)
    if gen_func is not None:
        return gen_func(size, color)

    # Unknown layer type -- return transparent
    log.warning("Unknown layer type '%s'; returning transparent layer", layer_type)
    return Image.new('RGBA', size, (0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Accent effects
# ---------------------------------------------------------------------------

def _apply_accent(img, spec, size):
    """
    Apply the accent effect described by *spec* onto *img*.

    Accent types:
        sun_glow      -- radial gradient at (80%, 30%)
        fire_glow     -- radial gradient at (50%, 30%)
        energy_crystals -- already handled as a layer
        arcane_lightning -- branching lightning arcs
    """
    accent_type = spec[0]
    color = spec[1] if len(spec) > 1 else (255, 255, 255)
    w, h = size

    if accent_type == 'sun_glow':
        return add_radial_glow(
            img, center=(int(w * 0.80), int(h * 0.30)),
            color=color, radius=int(min(w, h) * 0.4), falloff=2.0,
        )
    elif accent_type == 'fire_glow':
        return add_radial_glow(
            img, center=(int(w * 0.50), int(h * 0.30)),
            color=color, radius=int(min(w, h) * 0.35), falloff=2.5,
        )
    elif accent_type == 'arcane_lightning':
        return add_lightning_arcs(img, color=color, branches=8, seed=42)
    elif accent_type == 'energy_crystals':
        # Already rendered as a layer; add a subtle glow
        return add_radial_glow(
            img, center=(w // 2, int(h * 0.5)),
            color=color, radius=int(min(w, h) * 0.3), falloff=3.0,
        )

    return img


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

def generate_loading_screen(zone_name, theme='tropical',
                            size=(1024, 768), custom_elements=None):
    """
    Procedurally generate a loading-screen image.

    Layers are composited in order: sky -> background -> midground ->
    foreground -> accent effects -> zone-name text.

    Args:
        zone_name:       Display text for the zone name.
        theme:           One of 'tropical', 'volcanic', 'underground', 'titan'.
        size:            (width, height) output dimensions.
        custom_elements: Optional dict overriding individual layer specs.

    Returns:
        Pillow RGBA Image.
    """
    layers_spec = LOADING_SCREEN_THEMES.get(theme)
    if layers_spec is None:
        log.warning("Unknown theme '%s'; falling back to 'tropical'", theme)
        layers_spec = LOADING_SCREEN_THEMES['tropical']

    # Allow per-layer overrides
    if custom_elements:
        layers_spec = dict(layers_spec)
        layers_spec.update(custom_elements)

    # Step 1: sky base
    log.info("Generating loading screen '%s' (%s theme, %s)", zone_name, theme, size)
    img = _generate_sky(layers_spec['sky'], size)

    # Step 2-4: composite background, midground, foreground
    for layer_name in ('background', 'midground', 'foreground'):
        layer_img = _generate_layer(layers_spec[layer_name], size)
        img = Image.alpha_composite(img.convert('RGBA'), layer_img)

    # Step 5: accent effects
    img = _apply_accent(img, layers_spec['accent'], size)

    # Step 6: zone name text
    img_rgb = img.convert('RGB')
    draw_centred_text(img_rgb, zone_name, y_fraction=0.10)

    log.info("Loading screen complete for '%s'", zone_name)
    return img_rgb.convert('RGBA')
