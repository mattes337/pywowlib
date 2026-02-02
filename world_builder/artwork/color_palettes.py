"""
Terrain theme color palettes for procedural artwork generation.

Defines RGB color schemes for different terrain biomes. Each palette maps
elevation bands (deep water through peaks) to colours so that heightmaps
can be rendered as stylised terrain illustrations.

Palettes:
    tropical  -- Lush island with jungle greens and sandy beaches
    volcanic  -- Dark rock with red/orange lava and fire tones
    temperate -- Classic green rolling hills with snowy peaks
    arctic    -- Ice and snow with pale blue water
    underground -- Dark cavern greys with crystal accents
    titan     -- Blue-grey stone with metallic highlights
"""


# ---------------------------------------------------------------------------
# Color palette data class
# ---------------------------------------------------------------------------

class ColorPalette:
    """Color scheme for a terrain theme.  All colours are RGB tuples (0-255)."""

    __slots__ = (
        'deep_water', 'shallow_water', 'beach', 'lowland',
        'midland', 'highland', 'peak', 'vegetation', 'snow',
    )

    def __init__(self, deep_water, shallow_water, beach, lowland,
                 midland, highland, peak, vegetation=None, snow=None):
        self.deep_water = deep_water
        self.shallow_water = shallow_water
        self.beach = beach
        self.lowland = lowland
        self.midland = midland
        self.highland = highland
        self.peak = peak
        self.vegetation = vegetation
        self.snow = snow


# ---------------------------------------------------------------------------
# Predefined palettes
# ---------------------------------------------------------------------------

PALETTES = {
    'tropical': ColorPalette(
        deep_water=(0, 50, 100),
        shallow_water=(50, 120, 180),
        beach=(210, 190, 140),
        lowland=(80, 140, 60),
        midland=(60, 100, 40),
        highland=(120, 100, 80),
        peak=(140, 120, 100),
        vegetation=(100, 180, 70),
    ),
    'volcanic': ColorPalette(
        deep_water=(0, 50, 100),
        shallow_water=(50, 120, 180),
        beach=(80, 70, 60),
        lowland=(100, 80, 60),
        midland=(140, 100, 70),
        highland=(180, 120, 80),
        peak=(220, 80, 40),
    ),
    'temperate': ColorPalette(
        deep_water=(20, 60, 120),
        shallow_water=(60, 130, 180),
        beach=(180, 170, 140),
        lowland=(100, 150, 80),
        midland=(80, 120, 60),
        highland=(120, 110, 90),
        peak=(180, 180, 190),
        snow=(240, 240, 250),
    ),
    'arctic': ColorPalette(
        deep_water=(20, 40, 80),
        shallow_water=(80, 120, 160),
        beach=(200, 210, 220),
        lowland=(220, 230, 240),
        midland=(200, 210, 220),
        highland=(180, 190, 200),
        peak=(240, 250, 255),
        snow=(250, 250, 255),
    ),
    'underground': ColorPalette(
        deep_water=(10, 20, 40),
        shallow_water=(30, 50, 80),
        beach=(50, 50, 60),
        lowland=(40, 40, 50),
        midland=(60, 60, 70),
        highland=(80, 80, 90),
        peak=(100, 100, 110),
    ),
    'titan': ColorPalette(
        deep_water=(20, 30, 60),
        shallow_water=(50, 70, 120),
        beach=(80, 80, 100),
        lowland=(90, 90, 110),
        midland=(100, 100, 120),
        highland=(120, 120, 140),
        peak=(150, 150, 170),
    ),
}


# ---------------------------------------------------------------------------
# Colour interpolation helpers
# ---------------------------------------------------------------------------

def interpolate_color(c1, c2, t):
    """
    Linearly interpolate between two RGB tuples.

    Args:
        c1: Start colour (r, g, b).
        c2: End colour (r, g, b).
        t:  Interpolation factor clamped to [0, 1].

    Returns:
        Interpolated (r, g, b) tuple with integer components.
    """
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def interpolate_terrain_color(height, water_level, palette):
    """
    Map a normalised height value to a terrain colour from *palette*.

    Height ranges (relative to *water_level*):
        height < water_level          : deep water -> shallow water
        water_level .. water_level+0.1: beach
        +0.1 .. 0.4                   : lowland
        0.4  .. 0.6                   : midland
        0.6  .. 0.8                   : highland
        0.8  .. 1.0                   : peak (with optional snow)

    Args:
        height:      Normalised height in [0, 1].
        water_level: Height threshold for the water surface.
        palette:     A ColorPalette instance.

    Returns:
        (r, g, b) tuple.
    """
    if height < water_level:
        depth_range = max(0.2, water_level)
        t = max(0.0, (height - (water_level - depth_range)) / depth_range)
        return interpolate_color(palette.deep_water, palette.shallow_water, t)

    if height < water_level + 0.1:
        return palette.beach

    beach_end = water_level + 0.1
    if height < 0.4:
        span = 0.4 - beach_end
        if span <= 0:
            return palette.lowland
        t = (height - beach_end) / span
        return interpolate_color(palette.beach, palette.lowland, t)

    if height < 0.6:
        t = (height - 0.4) / 0.2
        return interpolate_color(palette.lowland, palette.midland, t)

    if height < 0.8:
        t = (height - 0.6) / 0.2
        return interpolate_color(palette.midland, palette.highland, t)

    # 0.8 .. 1.0
    t = (height - 0.8) / 0.2
    if palette.snow is not None and height > 0.9:
        snow_t = (height - 0.9) / 0.1
        return interpolate_color(palette.peak, palette.snow, snow_t)
    return interpolate_color(palette.highland, palette.peak, t)
