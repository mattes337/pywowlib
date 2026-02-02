"""
Terrain Sculptor - Procedural terrain generation for WoW WotLK 3.3.5a.

Provides a fully automated pipeline that converts high-level zone definitions
into complete terrain data (heightmaps, textures, doodad/WMO placements,
water planes, area IDs) ready for consumption by adt_composer.

The module is self-contained: noise generation, terrain primitives,
composition, texture painting, doodad scattering, WMO placement,
water generation and area-ID stamping are all implemented here.

Dependencies:
    numpy  - required for array operations
    scipy  - optional, used for alpha-map upsampling (zoom)

Usage:
    from world_builder.terrain_sculptor import sculpt_zone

    terrain_data = sculpt_zone(zone_definition)
    # terrain_data is a dict ready for adt_composer integration
"""

import logging
import math
import random
import struct
from io import BytesIO

log = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "numpy is required for terrain_sculptor. "
        "Install it with: pip install numpy"
    )

try:
    from scipy.ndimage import zoom as _scipy_zoom
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Constants (mirrored from adt_composer for coordinate math)
# ---------------------------------------------------------------------------

TILE_SIZE = 5533.333333333        # Yards per ADT tile
CHUNK_SIZE = TILE_SIZE / 16.0     # ~345.83 yards per sub-chunk
MAP_SIZE_MIN = -17066.66656
MAP_SIZE_MAX = 17066.66657

_CHUNKS_PER_SIDE = 16
_TOTAL_CHUNKS = _CHUNKS_PER_SIDE * _CHUNKS_PER_SIDE  # 256

# Heightmap resolution per ADT tile: 16 chunks * 8 quads + 1 edge = 129
_HEIGHTMAP_RES = 129

# Alpha map resolution per MCNK chunk (big-alpha / highres)
_ALPHA_RES = 64

# Water type constants matching MH2O type IDs
WATER_TYPE_OCEAN = 0
WATER_TYPE_LAKE = 1
WATER_TYPE_LAVA = 2
WATER_TYPE_SWAMP = 3

_WATER_TYPE_MAP = {
    'ocean': WATER_TYPE_OCEAN,
    'lake': WATER_TYPE_LAKE,
    'lava': WATER_TYPE_LAVA,
    'swamp': WATER_TYPE_SWAMP,
}

# Default textures for the elevation-based rule cascade
_DEFAULT_TEXTURE_SAND = "Tileset\\Generic\\Sand01.blp"
_DEFAULT_TEXTURE_GRASS = "Tileset\\Generic\\Grass01.blp"
_DEFAULT_TEXTURE_ROCK = "Tileset\\Generic\\Rock01.blp"
_DEFAULT_TEXTURE_SNOW = "Tileset\\Generic\\Snow01.blp"
_DEFAULT_TEXTURE_CLIFF = "Tileset\\Generic\\Cliff01.blp"
_DEFAULT_TEXTURE_BLACK = "Tileset\\Generic\\Black.blp"


# ===================================================================
# Simplex Noise
# ===================================================================

class SimplexNoise:
    """
    2D Simplex noise implementation with seeded permutation table.

    Provides reproducible noise generation via a seed value and
    fractal Brownian motion (fBm / octave noise) support.
    """

    # Skew factors for 2D simplex
    _F2 = 0.5 * (math.sqrt(3.0) - 1.0)
    _G2 = (3.0 - math.sqrt(3.0)) / 6.0

    # Gradient vectors for 2D
    _GRAD2 = [
        (1, 1), (-1, 1), (1, -1), (-1, -1),
        (1, 0), (-1, 0), (0, 1), (0, -1),
    ]

    def __init__(self, seed=0):
        """Initialise with a deterministic seed."""
        self._perm = self._generate_permutation(seed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_permutation(seed):
        """Build a 512-entry permutation table from *seed*."""
        rng = random.Random(seed)
        p = list(range(256))
        rng.shuffle(p)
        return p + p  # double for wrapping

    def _grad_dot(self, hash_val, x, y):
        g = self._GRAD2[hash_val & 7]
        return g[0] * x + g[1] * y

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def noise2d(self, x, y):
        """
        Evaluate 2D simplex noise at (*x*, *y*).

        Returns a float in the approximate range [-1.0, 1.0].
        """
        F2 = self._F2
        G2 = self._G2
        perm = self._perm

        s = (x + y) * F2
        i = int(math.floor(x + s))
        j = int(math.floor(y + s))

        t = (i + j) * G2
        x0 = x - (i - t)
        y0 = y - (j - t)

        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1

        x1 = x0 - i1 + G2
        y1 = y0 - j1 + G2
        x2 = x0 - 1.0 + 2.0 * G2
        y2 = y0 - 1.0 + 2.0 * G2

        ii = i & 255
        jj = j & 255

        n = 0.0

        t0 = 0.5 - x0 * x0 - y0 * y0
        if t0 > 0.0:
            t0 *= t0
            n += t0 * t0 * self._grad_dot(perm[ii + perm[jj]], x0, y0)

        t1 = 0.5 - x1 * x1 - y1 * y1
        if t1 > 0.0:
            t1 *= t1
            n += t1 * t1 * self._grad_dot(perm[ii + i1 + perm[jj + j1]], x1, y1)

        t2 = 0.5 - x2 * x2 - y2 * y2
        if t2 > 0.0:
            t2 *= t2
            n += t2 * t2 * self._grad_dot(perm[ii + 1 + perm[jj + 1]], x2, y2)

        # Scale to approximate [-1, 1]
        return 70.0 * n

    def octave_noise2d(self, x, y, octaves=4, persistence=0.5,
                       lacunarity=2.0):
        """
        Generate fractal Brownian motion (fBm) noise.

        Parameters:
            x, y:        Sample coordinates.
            octaves:     Number of noise layers (default 4).
            persistence: Amplitude decay per octave (0-1).
            lacunarity:  Frequency multiplier per octave (>1).

        Returns:
            float -- the accumulated noise value (range depends on octaves).
        """
        total = 0.0
        amplitude = 1.0
        frequency = 1.0
        max_amplitude = 0.0

        for _ in range(octaves):
            total += self.noise2d(x * frequency, y * frequency) * amplitude
            max_amplitude += amplitude
            amplitude *= persistence
            frequency *= lacunarity

        if max_amplitude > 0.0:
            total /= max_amplitude
        return total


# ===================================================================
# Terrain Primitives
# ===================================================================

def _smoothstep(t):
    """Hermite smoothstep: 3t^2 - 2t^3, element-wise on numpy arrays."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _norm_grid(size):
    """
    Return (x_norm, y_norm) broadcast-ready arrays in [0, 1].

    *size* is (width, height) -- width is the column count.
    """
    width, height = size
    y_coords = np.arange(height, dtype=np.float64).reshape(-1, 1) / max(height - 1, 1)
    x_coords = np.arange(width, dtype=np.float64).reshape(1, -1) / max(width - 1, 1)
    return x_coords, y_coords


def island(size, center, radius, elevation, falloff=0.3):
    """
    Raised landmass with smooth coastal falloff to zero.

    Parameters:
        size:      (width, height) in vertices.
        center:    (cx, cy) normalised coordinates (0-1).
        radius:    Normalised radius (0-1).
        elevation: Peak height at centre.
        falloff:   Falloff curve steepness (0-1). Larger = wider transition.

    Returns:
        2D numpy array (height, width) with elevation profile.
    """
    x_norm, y_norm = _norm_grid(size)
    cx, cy = center
    dist = np.sqrt((x_norm - cx) ** 2 + (y_norm - cy) ** 2)
    effective_falloff = max(falloff, 0.01)
    t = (radius - dist) / (radius * effective_falloff)
    return float(elevation) * _smoothstep(t)


def plateau(size, bounds, elevation, edge_steepness=5.0):
    """
    Flat elevated area with steep sigmoid edges.

    Parameters:
        size:            (width, height) in vertices.
        bounds:          (x_min, y_min, x_max, y_max) normalised (0-1).
        elevation:       Plateau height.
        edge_steepness:  Controls cliff slope sharpness.

    Returns:
        2D numpy array with flat top and steep sides.
    """
    x_norm, y_norm = _norm_grid(size)
    x_min, y_min, x_max, y_max = bounds

    # Signed distance to the rectangle interior (positive inside)
    dist_x = np.minimum(x_norm - x_min, x_max - x_norm)
    dist_y = np.minimum(y_norm - y_min, y_max - y_norm)
    dist = np.minimum(dist_x, dist_y)

    # Sigmoid falloff with a small offset so the cliff sits at the edge
    t = 1.0 / (1.0 + np.exp(-float(edge_steepness) * (dist - 0.02)))
    return float(elevation) * t


def volcano(size, center, base_radius, peak_height, caldera_radius,
            caldera_depth):
    """
    Volcanic cone with an inner caldera depression.

    Parameters:
        size:            (width, height) in vertices.
        center:          (cx, cy) normalised coordinates (0-1).
        base_radius:     Outer base radius (normalised).
        peak_height:     Maximum elevation at the rim.
        caldera_radius:  Inner caldera radius (normalised).
        caldera_depth:   Depth of caldera below the rim.

    Returns:
        2D numpy array with volcanic profile.
    """
    x_norm, y_norm = _norm_grid(size)
    cx, cy = center
    dist = np.sqrt((x_norm - cx) ** 2 + (y_norm - cy) ** 2)

    # Outer cone: linearly decreasing from peak at rim to zero at base
    cone = np.maximum(0.0, float(peak_height) * (1.0 - dist / float(base_radius)))

    # Caldera depression inside the caldera radius
    caldera_r = float(caldera_radius)
    caldera_d = float(caldera_depth)
    caldera = np.where(
        dist < caldera_r,
        -caldera_d * (1.0 - dist / caldera_r),
        0.0,
    )

    return cone + caldera


def valley(size, center, radius, depth, falloff=0.3):
    """
    Sunken basin (inverted island).

    Parameters:
        size:    (width, height) in vertices.
        center:  (cx, cy) normalised (0-1).
        radius:  Normalised radius.
        depth:   Positive depth value (result is negative).
        falloff: Edge falloff steepness.

    Returns:
        2D numpy array with negative depression.
    """
    return -island(size, center, radius, depth, falloff)


def ridge(size, start, end, width, height, falloff=0.2):
    """
    Linear elevated feature (mountain ridge, cliff line).

    Parameters:
        size:    (width_px, height_px) in vertices.
        start:   (sx, sy) normalised start point (0-1).
        end:     (ex, ey) normalised end point (0-1).
        width:   Ridge half-width (normalised).
        height:  Ridge peak elevation.
        falloff: Edge falloff steepness (0-1).

    Returns:
        2D numpy array with linear ridge profile.
    """
    w, h = size
    x_norm, y_norm = _norm_grid((w, h))
    sx, sy = start
    ex, ey = end

    dx = float(ex - sx)
    dy = float(ey - sy)
    line_len_sq = dx * dx + dy * dy
    if line_len_sq < 1e-12:
        return np.zeros((h, w), dtype=np.float64)

    # Project every point onto the line segment, get parameter t in [0, 1]
    t_param = ((x_norm - sx) * dx + (y_norm - sy) * dy) / line_len_sq
    t_param = np.clip(t_param, 0.0, 1.0)

    proj_x = sx + t_param * dx
    proj_y = sy + t_param * dy

    dist = np.sqrt((x_norm - proj_x) ** 2 + (y_norm - proj_y) ** 2)

    effective_falloff = max(falloff, 0.01)
    t = (float(width) - dist) / (float(width) * effective_falloff)
    return float(height) * _smoothstep(t)


# ===================================================================
# Blending Masks
# ===================================================================

def generate_mask(size, center, radius, shape='circle', falloff=0.2,
                  polygon=None):
    """
    Generate a 2D blending mask.

    Parameters:
        size:     (width, height) in vertices.
        center:   (cx, cy) normalised (0-1).
        radius:   Normalised radius (used for 'circle').
        shape:    'circle' or 'polygon'.
        falloff:  Edge transition width (0 = hard, 1 = very gradual).
        polygon:  List of (x, y) normalised vertices (for 'polygon' shape).

    Returns:
        2D numpy array with values 0.0 (outside) to 1.0 (inside).
    """
    width, height = size
    x_norm, y_norm = _norm_grid(size)
    cx, cy = center

    if shape == 'polygon' and polygon is not None:
        # Simple polygon mask via signed-distance approximation
        mask = _polygon_mask(x_norm, y_norm, polygon, falloff, width, height)
        return mask

    # Default: circle
    dist = np.sqrt((x_norm - cx) ** 2 + (y_norm - cy) ** 2)
    effective_falloff = max(falloff, 0.01)
    t = (float(radius) - dist) / (float(radius) * effective_falloff)
    return _smoothstep(t)


def _polygon_mask(x_norm, y_norm, polygon, falloff, width, height):
    """
    Generate a mask from a polygon using point-in-polygon testing
    with an approximate distance-based falloff.
    """
    mask = np.zeros((height, width), dtype=np.float64)
    for row in range(height):
        for col in range(width):
            px = float(x_norm[0, col]) if x_norm.ndim == 2 else float(x_norm[col])
            py = float(y_norm[row, 0]) if y_norm.ndim == 2 else float(y_norm[row])
            if _point_in_polygon(px, py, polygon):
                mask[row, col] = 1.0
            elif falloff > 0.0:
                d = _point_polygon_distance(px, py, polygon)
                if d < falloff:
                    t = 1.0 - d / falloff
                    mask[row, col] = t * t * (3.0 - 2.0 * t)
    return mask


# ===================================================================
# Geometry Utilities
# ===================================================================

def _point_in_polygon(px, py, polygon):
    """
    Ray-casting algorithm for point-in-polygon test.

    Parameters:
        px, py:  Point coordinates.
        polygon: List of (x, y) tuples forming a closed polygon.

    Returns:
        True if point is inside the polygon.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _point_polygon_distance(px, py, polygon):
    """
    Minimum distance from a point to any edge of a polygon.
    """
    min_dist = float('inf')
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        dist = _point_segment_distance(px, py, x1, y1, x2, y2)
        if dist < min_dist:
            min_dist = dist
    return min_dist


def _point_segment_distance(px, py, x1, y1, x2, y2):
    """Minimum distance from point (px, py) to line segment (x1,y1)-(x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-30:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def _polygon_area(polygon):
    """
    Shoelace formula for polygon area (normalised coordinates).
    """
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


# ===================================================================
# Heightmap Composition
# ===================================================================

def compose_heightmap(zone_def, tile_x, tile_y):
    """
    Generate a heightmap for one ADT tile by composing primitives.

    The tile's position within the zone grid is used to determine
    which region of the normalised (0-1) zone space the tile covers.
    Each subzone primitive is generated at full zone resolution, then
    the tile-local region is extracted.

    Args:
        zone_def: Zone definition dict.
        tile_x:   Tile X coordinate.
        tile_y:   Tile Y coordinate.

    Returns:
        2D numpy array (_HEIGHTMAP_RES x _HEIGHTMAP_RES) with heights.
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))
    sea_level = zone_def.get('sea_level', 0.0)
    seed = zone_def.get('seed', 0)

    # Tile position within the zone grid (0-based)
    local_tx = tile_x - base_x
    local_ty = tile_y - base_y

    # Normalised extents of this tile within the zone [0, 1]
    x_start = local_tx / float(grid_w)
    x_end = (local_tx + 1) / float(grid_w)
    y_start = local_ty / float(grid_h)
    y_end = (local_ty + 1) / float(grid_h)

    # We generate the primitive at the full zone resolution scaled to the
    # tile window.  The output size is always _HEIGHTMAP_RES x _HEIGHTMAP_RES.
    size = (_HEIGHTMAP_RES, _HEIGHTMAP_RES)
    heightmap = np.full((_HEIGHTMAP_RES, _HEIGHTMAP_RES), float(sea_level),
                        dtype=np.float64)

    for subzone in zone_def.get('subzones', []):
        terrain_type = subzone.get('terrain_type', 'noise')
        weight = subzone.get('weight', 1.0)
        center = subzone.get('center', (0.5, 0.5))
        radius = subzone.get('radius', 0.2)
        elev = subzone.get('elevation', (0, 50))
        params = subzone.get('terrain_params', {})
        falloff = subzone.get('falloff', 0.2)

        # Map the subzone centre/radius into tile-local normalised space
        local_center = (
            (center[0] - x_start) / (x_end - x_start),
            (center[1] - y_start) / (y_end - y_start),
        )
        local_radius = radius / (x_end - x_start)  # assume square tiles

        peak = elev[1] if isinstance(elev, (list, tuple)) else float(elev)

        # Generate primitive in tile-local coordinates
        if terrain_type == 'island':
            prim = island(size, local_center, local_radius, peak, falloff)
        elif terrain_type == 'plateau':
            bounds = params.get('bounds', subzone.get('bounds', None))
            steepness = params.get('edge_steepness', 5.0)
            if bounds is not None:
                local_bounds = (
                    (bounds[0] - x_start) / (x_end - x_start),
                    (bounds[1] - y_start) / (y_end - y_start),
                    (bounds[2] - x_start) / (x_end - x_start),
                    (bounds[3] - y_start) / (y_end - y_start),
                )
            else:
                # Fallback: derive bounds from center/radius
                local_bounds = (
                    local_center[0] - local_radius,
                    local_center[1] - local_radius,
                    local_center[0] + local_radius,
                    local_center[1] + local_radius,
                )
            prim = plateau(size, local_bounds, peak, steepness)
        elif terrain_type == 'volcano':
            caldera_r = params.get('caldera_radius', 0.05)
            caldera_d = params.get('caldera_depth', 20.0)
            local_caldera_r = caldera_r / (x_end - x_start)
            prim = volcano(size, local_center, local_radius,
                           peak, local_caldera_r, caldera_d)
        elif terrain_type == 'valley':
            depth = abs(peak) if peak != 0 else abs(elev[0])
            prim = valley(size, local_center, local_radius, depth, falloff)
        elif terrain_type == 'ridge':
            start_pt = params.get('start', center)
            end_pt = params.get('end', center)
            ridge_width = params.get('width', 0.05)
            local_start = (
                (start_pt[0] - x_start) / (x_end - x_start),
                (start_pt[1] - y_start) / (y_end - y_start),
            )
            local_end = (
                (end_pt[0] - x_start) / (x_end - x_start),
                (end_pt[1] - y_start) / (y_end - y_start),
            )
            local_width = ridge_width / (x_end - x_start)
            prim = ridge(size, local_start, local_end, local_width, peak,
                         falloff)
        elif terrain_type == 'noise':
            noise_params = subzone.get('noise_params', {})
            prim = _generate_noise_heightmap(
                size, seed, local_tx, local_ty,
                elev_min=elev[0] if isinstance(elev, (list, tuple)) else 0,
                elev_max=peak,
                scale=noise_params.get('scale', 30.0),
                octaves=noise_params.get('octaves', 3),
                persistence=noise_params.get('persistence', 0.4),
                lacunarity=noise_params.get('lacunarity', 2.0),
            )
        else:
            # Unknown type: treat as flat
            prim = np.full((_HEIGHTMAP_RES, _HEIGHTMAP_RES), peak,
                           dtype=np.float64)

        # Generate blending mask in tile-local space
        shape = subzone.get('shape', 'circle')
        poly = subzone.get('polygon', None)
        if shape == 'polygon' and poly is not None:
            local_poly = [
                ((p[0] - x_start) / (x_end - x_start),
                 (p[1] - y_start) / (y_end - y_start))
                for p in poly
            ]
            mask = generate_mask(size, local_center, local_radius,
                                 shape='polygon', falloff=falloff,
                                 polygon=local_poly)
        else:
            mask = generate_mask(size, local_center, local_radius,
                                 shape='circle', falloff=falloff)

        heightmap += prim * mask * float(weight)

    # Add small-scale noise detail for natural variation
    noise = SimplexNoise(seed=seed + tile_x * 1000 + tile_y)
    detail = np.zeros((_HEIGHTMAP_RES, _HEIGHTMAP_RES), dtype=np.float64)
    for row in range(_HEIGHTMAP_RES):
        for col in range(_HEIGHTMAP_RES):
            nx = (local_tx * _HEIGHTMAP_RES + col) * 0.02
            ny = (local_ty * _HEIGHTMAP_RES + row) * 0.02
            detail[row, col] = noise.octave_noise2d(nx, ny, octaves=2)
    heightmap += detail * 1.5

    # Clamp to a reasonable range
    heightmap = np.clip(heightmap, -500.0, 2000.0)
    return heightmap


def _generate_noise_heightmap(size, seed, tile_x, tile_y,
                              elev_min=0, elev_max=50,
                              scale=30.0, octaves=3,
                              persistence=0.4, lacunarity=2.0):
    """
    Generate a heightmap from pure noise for 'noise' terrain type.
    """
    w, h = size
    noise = SimplexNoise(seed=seed)
    result = np.zeros((h, w), dtype=np.float64)

    for row in range(h):
        for col in range(w):
            nx = (tile_x * w + col) / scale
            ny = (tile_y * h + row) / scale
            n = noise.octave_noise2d(nx, ny, octaves=int(octaves),
                                     persistence=float(persistence),
                                     lacunarity=float(lacunarity))
            # Map from [-1, 1] to [elev_min, elev_max]
            result[row, col] = elev_min + (n + 1.0) * 0.5 * (elev_max - elev_min)

    return result


# ===================================================================
# Slope Calculation
# ===================================================================

def calculate_slope(heightmap):
    """
    Calculate slope in degrees from a heightmap.

    Uses numpy.gradient for finite differences.

    Args:
        heightmap: 2D numpy array of elevation values.

    Returns:
        2D numpy array with slope values in degrees.
    """
    dy, dx = np.gradient(heightmap)
    slope_rad = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    return np.degrees(slope_rad)


# ===================================================================
# Texture Painter
# ===================================================================

class TexturePainter:
    """
    Rule-based texture layer assignment and alpha map generation.

    Applies a cascade of rules (subzone override -> slope -> elevation)
    to assign up to 4 texture layers per MCNK chunk, together with
    64x64 alpha maps for each non-base layer.
    """

    def __init__(self, zone_def):
        self.zone_def = zone_def
        self.noise = SimplexNoise(seed=zone_def.get('seed', 0) + 7777)

    def paint_textures(self, heightmap, tile_x, tile_y):
        """
        Generate texture layers and alpha maps for one ADT tile.

        Args:
            heightmap: 2D array (_HEIGHTMAP_RES x _HEIGHTMAP_RES).
            tile_x, tile_y: Tile coordinates.

        Returns:
            dict with keys:
                'texture_paths': list of unique texture path strings
                'splat_maps': dict {layer_index: list-of-lists [64][64]} per chunk
                    structured as a dict keyed by chunk_index (0..255)
        """
        slope_map = calculate_slope(heightmap)
        subzone_map = self._generate_subzone_map(heightmap.shape, tile_x, tile_y)

        # Per-tile texture list and per-chunk data
        texture_set = []  # ordered unique textures
        texture_index_map = {}  # path -> index
        chunk_layers = {}  # chunk_idx -> {'texture_ids': [...], 'alpha_maps': [...]}

        def _get_tex_id(path):
            if path is None:
                return None
            # Normalise to backslash for WoW convention
            path = path.replace("/", "\\")
            if path not in texture_index_map:
                texture_index_map[path] = len(texture_set)
                texture_set.append(path)
            return texture_index_map[path]

        for chunk_row in range(_CHUNKS_PER_SIDE):
            for chunk_col in range(_CHUNKS_PER_SIDE):
                chunk_idx = chunk_row * _CHUNKS_PER_SIDE + chunk_col

                # Vertex window for this chunk (9x9 outer vertices)
                vr = chunk_row * 8
                vc = chunk_col * 8
                vr_end = min(vr + 9, _HEIGHTMAP_RES)
                vc_end = min(vc + 9, _HEIGHTMAP_RES)

                chunk_h = heightmap[vr:vr_end, vc:vc_end]
                chunk_s = slope_map[vr:vr_end, vc:vc_end]
                chunk_sz = subzone_map[vr:vr_end, vc:vc_end]

                avg_elev = float(np.mean(chunk_h))
                max_slope = float(np.max(chunk_s))

                # Determine primary subzone for this chunk
                flat_sz = chunk_sz.flatten()
                primary_sz = -1
                if flat_sz.size > 0:
                    counts = np.bincount(flat_sz.astype(np.int64) + 1)
                    primary_sz = int(counts.argmax()) - 1

                # ---- Layer 0: base texture (always full coverage) ----
                base_tex = self._select_base_texture(avg_elev, primary_sz)
                layers = [_get_tex_id(base_tex)]
                alpha_maps = []  # base layer has no alpha map

                # ---- Layer 1: slope override (rock on steep areas) ----
                if max_slope > 15.0:
                    slope_tex = _DEFAULT_TEXTURE_ROCK
                    # Check subzone override
                    if primary_sz >= 0:
                        sz_textures = self.zone_def['subzones'][primary_sz].get('textures', [])
                        if len(sz_textures) > 1:
                            slope_tex = sz_textures[1]
                    layers.append(_get_tex_id(slope_tex))
                    alpha_maps.append(
                        self._generate_slope_alpha(chunk_s, threshold=15.0)
                    )

                # ---- Layer 2: detail / noise variation ----
                detail_tex = self._select_detail_texture(avg_elev, primary_sz)
                if detail_tex is not None:
                    layers.append(_get_tex_id(detail_tex))
                    alpha_maps.append(
                        self._generate_noise_alpha(chunk_col, chunk_row,
                                                   tile_x, tile_y)
                    )

                # Pad to at most 4 layers
                while len(layers) < 1:
                    layers.append(_get_tex_id(_DEFAULT_TEXTURE_BLACK))

                # Trim to 4 layers max (WoW limit per MCNK)
                layers = layers[:4]
                alpha_maps = alpha_maps[:3]  # max 3 alpha maps (layers 1-3)

                chunk_layers[chunk_idx] = {
                    'texture_ids': layers,
                    'alpha_maps': alpha_maps,
                }

        return {
            'texture_paths': texture_set,
            'chunk_layers': chunk_layers,
        }

    def _generate_subzone_map(self, hm_shape, tile_x, tile_y):
        """
        Generate a subzone identity map for the tile.

        Returns:
            2D int32 array with subzone indices (-1 = no subzone).
        """
        rows, cols = hm_shape
        subzone_map = np.full((rows, cols), -1, dtype=np.int32)

        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))
        local_tx = tile_x - base_x
        local_ty = tile_y - base_y
        x_start = local_tx / float(grid_w)
        x_end = (local_tx + 1) / float(grid_w)
        y_start = local_ty / float(grid_h)
        y_end = (local_ty + 1) / float(grid_h)

        for idx, subzone in enumerate(self.zone_def.get('subzones', [])):
            center = subzone.get('center', (0.5, 0.5))
            radius = subzone.get('radius', 0.2)

            # Map subzone circle to tile-local coordinates
            local_cx = (center[0] - x_start) / (x_end - x_start)
            local_cy = (center[1] - y_start) / (y_end - y_start)
            local_r = radius / (x_end - x_start)

            # Build a simple circular mask with hard edge (for subzone ID)
            x_norm, y_norm = _norm_grid((cols, rows))
            dist = np.sqrt((x_norm - local_cx) ** 2 + (y_norm - local_cy) ** 2)
            inside = dist <= local_r

            # Smaller subzones should overwrite larger ones
            subzone_map[inside] = idx

        return subzone_map

    def _select_base_texture(self, avg_elevation, primary_subzone_idx):
        """Select the base (layer 0) texture via rule cascade."""
        # Priority 1: subzone override
        if primary_subzone_idx >= 0:
            subzones = self.zone_def.get('subzones', [])
            if primary_subzone_idx < len(subzones):
                textures = subzones[primary_subzone_idx].get('textures', [])
                if textures:
                    return textures[0]

        # Priority 2: elevation-based
        if avg_elevation < 2.0:
            return _DEFAULT_TEXTURE_SAND
        elif avg_elevation < 50.0:
            return _DEFAULT_TEXTURE_GRASS
        elif avg_elevation < 120.0:
            return _DEFAULT_TEXTURE_ROCK
        else:
            return _DEFAULT_TEXTURE_SNOW

    def _select_detail_texture(self, avg_elevation, primary_subzone_idx):
        """Select a detail texture for noise-variation layer."""
        if primary_subzone_idx >= 0:
            subzones = self.zone_def.get('subzones', [])
            if primary_subzone_idx < len(subzones):
                textures = subzones[primary_subzone_idx].get('textures', [])
                if len(textures) > 1:
                    return textures[-1]

        # Elevation fallback detail
        if avg_elevation < 2.0:
            return None  # sand has no detail
        elif avg_elevation < 50.0:
            return _DEFAULT_TEXTURE_SAND  # grass/sand transition
        elif avg_elevation < 120.0:
            return _DEFAULT_TEXTURE_GRASS  # rock/grass transition
        return None

    def _generate_slope_alpha(self, chunk_slope, threshold=15.0):
        """
        Generate a 64x64 alpha map based on slope values.

        Areas with slope above *threshold* degrees get higher alpha.

        Args:
            chunk_slope: 2D array (up to 9x9) of slope values.
            threshold:   Slope in degrees below which alpha is 0.

        Returns:
            List-of-lists [64][64] with uint8 alpha values.
        """
        # Upsample to 64x64
        alpha_float = self._upsample(chunk_slope, _ALPHA_RES)

        # Normalise: slope contribution above threshold
        alpha_float = (alpha_float - threshold) / 10.0
        alpha_float = np.clip(alpha_float * 255.0, 0, 255)
        alpha_uint8 = alpha_float.astype(np.uint8)

        return alpha_uint8.tolist()

    def _generate_noise_alpha(self, chunk_col, chunk_row, tile_x, tile_y,
                              scale=0.08):
        """
        Generate a 64x64 alpha map using noise for natural variation.
        """
        alpha = np.zeros((_ALPHA_RES, _ALPHA_RES), dtype=np.uint8)
        base_x = (tile_x * _CHUNKS_PER_SIDE + chunk_col) * _ALPHA_RES
        base_y = (tile_y * _CHUNKS_PER_SIDE + chunk_row) * _ALPHA_RES

        for row in range(_ALPHA_RES):
            for col in range(_ALPHA_RES):
                nx = (base_x + col) * scale
                ny = (base_y + row) * scale
                n = self.noise.octave_noise2d(nx, ny, octaves=2)
                val = int((n + 1.0) * 127.5)
                alpha[row, col] = max(0, min(255, val))

        return alpha.tolist()

    @staticmethod
    def _upsample(array_2d, target_size):
        """
        Upsample a small 2D array to *target_size* x *target_size*.

        Uses scipy.ndimage.zoom if available, otherwise nearest-neighbour.
        """
        h, w = array_2d.shape
        if h == target_size and w == target_size:
            return array_2d.astype(np.float64)

        if _HAS_SCIPY:
            zoom_y = target_size / float(h)
            zoom_x = target_size / float(w)
            return _scipy_zoom(array_2d.astype(np.float64), (zoom_y, zoom_x),
                               order=1)

        # Nearest-neighbour fallback
        result = np.zeros((target_size, target_size), dtype=np.float64)
        for row in range(target_size):
            for col in range(target_size):
                sr = int(row * h / target_size)
                sc = int(col * w / target_size)
                sr = min(sr, h - 1)
                sc = min(sc, w - 1)
                result[row, col] = array_2d[sr, sc]
        return result


# ===================================================================
# Poisson Disk Sampling
# ===================================================================

def poisson_disk_sampling(width, height, min_distance, max_attempts=30,
                          rng=None):
    """
    Bridson's Poisson disk sampling in a rectangular domain.

    Parameters:
        width, height:  Domain size.
        min_distance:   Minimum distance between any two samples.
        max_attempts:   Candidates per active sample before rejection.
        rng:            random.Random instance (for reproducibility).

    Returns:
        List of (x, y) tuples.
    """
    if rng is None:
        rng = random.Random()

    if min_distance <= 0:
        return []

    cell_size = min_distance / math.sqrt(2.0)
    grid_w = int(math.ceil(width / cell_size))
    grid_h = int(math.ceil(height / cell_size))
    grid = {}  # (gx, gy) -> point index

    points = []
    active = []

    # Seed point
    x0 = rng.uniform(0, width)
    y0 = rng.uniform(0, height)
    points.append((x0, y0))
    active.append(0)
    gx0 = int(x0 / cell_size)
    gy0 = int(y0 / cell_size)
    grid[(gx0, gy0)] = 0

    while active:
        idx = rng.randint(0, len(active) - 1)
        px, py = points[active[idx]]
        found = False

        for _ in range(max_attempts):
            angle = rng.uniform(0, 2.0 * math.pi)
            dist = rng.uniform(min_distance, 2.0 * min_distance)
            nx = px + dist * math.cos(angle)
            ny = py + dist * math.sin(angle)

            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue

            gnx = int(nx / cell_size)
            gny = int(ny / cell_size)

            # Check neighbours in a 5x5 grid window
            too_close = False
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    key = (gnx + dx, gny + dy)
                    if key in grid:
                        ox, oy = points[grid[key]]
                        if (nx - ox) ** 2 + (ny - oy) ** 2 < min_distance ** 2:
                            too_close = True
                            break
                if too_close:
                    break

            if not too_close:
                new_idx = len(points)
                points.append((nx, ny))
                active.append(new_idx)
                grid[(gnx, gny)] = new_idx
                found = True
                break

        if not found:
            active.pop(idx)

    return points


# ===================================================================
# Doodad Scatter Engine
# ===================================================================

class DoodadScatterEngine:
    """
    Automated doodad (M2) placement using Poisson disk sampling
    with elevation and slope filtering.
    """

    def __init__(self, zone_def, heightmaps):
        """
        Args:
            zone_def:    Zone definition dict.
            heightmaps:  Dict {(tile_x, tile_y): 2D numpy array}.
        """
        self.zone_def = zone_def
        self.heightmaps = heightmaps
        self._slope_cache = {}
        self._rng = random.Random(zone_def.get('seed', 0) + 12345)

    def scatter_all(self):
        """
        Scatter doodads across all subzones.

        Returns:
            List of MDDF entry dicts.
        """
        entries = []
        for subzone in self.zone_def.get('subzones', []):
            if 'doodads' in subzone and subzone['doodads']:
                entries.extend(self._scatter_subzone(subzone))
        return entries

    def _scatter_subzone(self, subzone):
        """
        Scatter doodads within a single subzone.

        Returns:
            List of MDDF entry dicts with keys:
                model, position, rotation, scale, flags
        """
        entries = []
        center = subzone.get('center', (0.5, 0.5))
        radius = subzone.get('radius', 0.2)
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))

        # World-space extents of the subzone (approximate bounding box)
        # In normalised space, the subzone spans [center-radius, center+radius]
        # Convert to world yards: zone covers grid_w * TILE_SIZE in X
        zone_width = grid_w * TILE_SIZE
        zone_height = grid_h * TILE_SIZE

        for model_name, density in subzone.get('doodads', {}).items():
            if density <= 0:
                continue

            # Approximate area covered by this subzone in square yards
            area_yards = math.pi * (radius * zone_width) * (radius * zone_height)
            target_count = max(1, int(area_yards * density))
            min_dist = math.sqrt(area_yards / max(target_count, 1) / math.pi)
            min_dist = max(min_dist, 1.0)  # at least 1 yard apart

            # Sample in normalised [0, 1] space then convert
            # Use a bounding box around the subzone
            box_x = max(0.0, center[0] - radius)
            box_y = max(0.0, center[1] - radius)
            box_w = min(1.0, center[0] + radius) - box_x
            box_h = min(1.0, center[1] + radius) - box_y

            # Scale min_dist to normalised space
            norm_min_dist = min_dist / zone_width

            raw_points = poisson_disk_sampling(
                box_w, box_h, norm_min_dist,
                max_attempts=30, rng=self._rng
            )

            # Offset to zone-normalised coords and filter to subzone circle
            filters = subzone.get('doodad_filters', {})
            for px, py in raw_points:
                norm_x = box_x + px
                norm_y = box_y + py

                # Check inside subzone circle
                dx = norm_x - center[0]
                dy = norm_y - center[1]
                if dx * dx + dy * dy > radius * radius:
                    continue

                # Convert to world coordinates
                world_x, world_y = self._norm_to_world(norm_x, norm_y)

                # Sample height
                z = self._sample_height(norm_x, norm_y)

                # Apply filters
                if not self._is_valid_placement(z, norm_x, norm_y, filters):
                    continue

                yaw = self._rng.uniform(0.0, 360.0)
                scale = self._rng.uniform(0.8, 1.2)

                entries.append({
                    'model': model_name,
                    'position': (world_x, world_y, z),
                    'rotation': (0.0, yaw, 0.0),
                    'scale': scale,
                    'flags': 0,
                })

        return entries

    def _norm_to_world(self, norm_x, norm_y):
        """
        Convert normalised (0-1) zone coordinates to WoW world coordinates.

        WoW coordinate system: the map origin is at tile (0, 0) with
        MAP_SIZE_MAX = 17066.  World X decreases with tile_y, world Y
        decreases with tile_x.
        """
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        tile_fx = base_x + norm_x * grid_w
        tile_fy = base_y + norm_y * grid_h

        world_x = MAP_SIZE_MAX - tile_fy * TILE_SIZE
        world_y = MAP_SIZE_MAX - tile_fx * TILE_SIZE
        return world_x, world_y

    def _sample_height(self, norm_x, norm_y):
        """
        Sample the heightmap at normalised zone coordinates using bilinear
        interpolation.
        """
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        # Fractional tile coordinates
        tile_fx = norm_x * grid_w
        tile_fy = norm_y * grid_h

        tile_ix = int(math.floor(tile_fx))
        tile_iy = int(math.floor(tile_fy))
        local_x = tile_fx - tile_ix
        local_y = tile_fy - tile_iy

        key = (base_x + tile_ix, base_y + tile_iy)
        hm = self.heightmaps.get(key)
        if hm is None:
            return 0.0

        # Map local (0-1) to heightmap pixel
        col_f = local_x * (_HEIGHTMAP_RES - 1)
        row_f = local_y * (_HEIGHTMAP_RES - 1)

        c0 = int(col_f)
        r0 = int(row_f)
        c1 = min(c0 + 1, _HEIGHTMAP_RES - 1)
        r1 = min(r0 + 1, _HEIGHTMAP_RES - 1)
        fc = col_f - c0
        fr = row_f - r0

        v00 = float(hm[r0, c0])
        v01 = float(hm[r0, c1])
        v10 = float(hm[r1, c0])
        v11 = float(hm[r1, c1])

        return (v00 * (1 - fr) * (1 - fc) +
                v01 * (1 - fr) * fc +
                v10 * fr * (1 - fc) +
                v11 * fr * fc)

    def _sample_slope(self, norm_x, norm_y):
        """Sample slope (degrees) at normalised zone coordinates."""
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        tile_fx = norm_x * grid_w
        tile_fy = norm_y * grid_h
        tile_ix = int(math.floor(tile_fx))
        tile_iy = int(math.floor(tile_fy))

        key = (base_x + tile_ix, base_y + tile_iy)

        if key not in self._slope_cache:
            hm = self.heightmaps.get(key)
            if hm is None:
                return 0.0
            self._slope_cache[key] = calculate_slope(hm)

        slope_map = self._slope_cache[key]

        local_x = tile_fx - tile_ix
        local_y = tile_fy - tile_iy
        col = min(int(local_x * (_HEIGHTMAP_RES - 1)), _HEIGHTMAP_RES - 1)
        row = min(int(local_y * (_HEIGHTMAP_RES - 1)), _HEIGHTMAP_RES - 1)
        return float(slope_map[row, col])

    def _is_valid_placement(self, z, norm_x, norm_y, filters):
        """Apply elevation, slope and water-distance filters."""
        # Elevation filter
        if 'elevation' in filters:
            elev_min = filters['elevation'].get('min', -1000)
            elev_max = filters['elevation'].get('max', 2000)
            if not (elev_min <= z <= elev_max):
                return False

        # Slope filter
        if 'slope' in filters:
            slope_max = filters['slope'].get('max', 35.0)
            slope = self._sample_slope(norm_x, norm_y)
            if slope > slope_max:
                return False

        # Water distance filter (approximate: reject if below sea level)
        if 'water_distance' in filters:
            sea_level = self.zone_def.get('sea_level', 0.0)
            min_dist_height = filters['water_distance'].get('min', 2.0)
            if z < sea_level + min_dist_height:
                return False

        return True


# ===================================================================
# WMO Placement Engine
# ===================================================================

class WMOPlacementEngine:
    """
    Coordinate-based WMO (World Map Object) placement.

    Reads explicit WMO definitions from subzone 'structures' lists,
    converts normalised coordinates to world space, and samples the
    heightmap for ground-level Z placement.
    """

    def __init__(self, zone_def, heightmaps):
        self.zone_def = zone_def
        self.heightmaps = heightmaps

    def place_all(self):
        """
        Place all WMOs defined across all subzones.

        Returns:
            List of MODF entry dicts with keys:
                model, position, rotation, scale, doodad_set, flags
        """
        entries = []
        for subzone in self.zone_def.get('subzones', []):
            for structure in subzone.get('structures', []):
                entry = self._place_single(structure)
                if entry is not None:
                    entries.append(entry)
        return entries

    def _place_single(self, structure):
        """
        Convert one structure definition to a MODF entry.
        """
        norm_pos = structure.get('position', (0.5, 0.5))
        rotation = structure.get('rotation', (0.0, 0.0, 0.0))
        scale = structure.get('scale', 1.0)
        doodad_set = structure.get('doodad_set', 0)
        model = structure.get('model', '')

        # Convert normalised position to world coordinates
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        tile_fx = base_x + norm_pos[0] * grid_w
        tile_fy = base_y + norm_pos[1] * grid_h

        world_x = MAP_SIZE_MAX - tile_fy * TILE_SIZE
        world_y = MAP_SIZE_MAX - tile_fx * TILE_SIZE

        # Sample height for Z
        z = self._sample_height(norm_pos[0], norm_pos[1])

        return {
            'model': model,
            'position': (world_x, world_y, z),
            'rotation': tuple(rotation),
            'scale': float(scale),
            'doodad_set': int(doodad_set),
            'flags': 0,
        }

    def _sample_height(self, norm_x, norm_y):
        """Sample heightmap at normalised zone coordinates."""
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        tile_fx = norm_x * grid_w
        tile_fy = norm_y * grid_h
        tile_ix = int(math.floor(tile_fx))
        tile_iy = int(math.floor(tile_fy))

        key = (base_x + tile_ix, base_y + tile_iy)
        hm = self.heightmaps.get(key)
        if hm is None:
            return 0.0

        local_x = tile_fx - tile_ix
        local_y = tile_fy - tile_iy
        col = min(int(local_x * (_HEIGHTMAP_RES - 1)), _HEIGHTMAP_RES - 1)
        row = min(int(local_y * (_HEIGHTMAP_RES - 1)), _HEIGHTMAP_RES - 1)
        return float(hm[row, col])


# ===================================================================
# Water Plane Generator
# ===================================================================

class WaterGenerator:
    """
    Generates water plane definitions (MH2O metadata) for each ADT tile.

    Produces a per-tile dict describing water regions and their properties.
    The actual MH2O binary encoding is left to the ADT composer; this module
    provides the logical description.
    """

    def __init__(self, zone_def):
        self.zone_def = zone_def

    def generate_all(self):
        """
        Generate water plane definitions for all tiles.

        Returns:
            Dict {(tile_x, tile_y): list of water region dicts} where each
            water region dict has keys:
                type_id, elevation, x_start, y_start, width, height
            (chunk coordinates within the 16x16 MCNK grid)
        """
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))

        water = {}

        # Global water plane (e.g. ocean)
        global_water = self.zone_def.get('global_water', None)
        if global_water is not None:
            elevation = global_water.get('elevation', 0.0)
            water_type = global_water.get('type', 'ocean')
            type_id = _WATER_TYPE_MAP.get(water_type, WATER_TYPE_OCEAN)

            for ty in range(grid_h):
                for tx in range(grid_w):
                    key = (base_x + tx, base_y + ty)
                    if key not in water:
                        water[key] = []
                    water[key].append({
                        'type_id': type_id,
                        'elevation': float(elevation),
                        'x_start': 0,
                        'y_start': 0,
                        'width': _CHUNKS_PER_SIDE,
                        'height': _CHUNKS_PER_SIDE,
                    })

        # Per-subzone water definitions
        for subzone in self.zone_def.get('subzones', []):
            for water_def in subzone.get('water', []):
                self._add_subzone_water(water, subzone, water_def)

        return water

    def _add_subzone_water(self, water_dict, subzone, water_def):
        """
        Add water regions for a subzone's water definition.
        """
        grid_w, grid_h = self.zone_def.get('grid_size', (1, 1))
        base_x, base_y = self.zone_def.get('base_coords', (32, 32))
        elevation = water_def.get('elevation', 0.0)
        water_type = water_def.get('type', 'ocean')
        type_id = _WATER_TYPE_MAP.get(water_type, WATER_TYPE_OCEAN)
        boundary = water_def.get('boundary', 'inherit')

        # Determine the normalised bounding box
        center = subzone.get('center', (0.5, 0.5))
        radius = subzone.get('radius', 0.2)

        if isinstance(boundary, list):
            # Explicit polygon boundary
            xs = [p[0] for p in boundary]
            ys = [p[1] for p in boundary]
            norm_x_min = min(xs)
            norm_x_max = max(xs)
            norm_y_min = min(ys)
            norm_y_max = max(ys)
        else:
            # 'inherit' or 'caldera' -- use subzone circle bounding box
            norm_x_min = center[0] - radius
            norm_x_max = center[0] + radius
            norm_y_min = center[1] - radius
            norm_y_max = center[1] + radius

        # Determine which tiles are affected
        tile_x_min = int(math.floor(norm_x_min * grid_w))
        tile_x_max = int(math.floor(norm_x_max * grid_w))
        tile_y_min = int(math.floor(norm_y_min * grid_h))
        tile_y_max = int(math.floor(norm_y_max * grid_h))

        for ty_local in range(max(0, tile_y_min), min(grid_h, tile_y_max + 1)):
            for tx_local in range(max(0, tile_x_min), min(grid_w, tile_x_max + 1)):
                key = (base_x + tx_local, base_y + ty_local)

                # Determine chunk range within this tile
                tile_norm_x_start = tx_local / float(grid_w)
                tile_norm_x_end = (tx_local + 1) / float(grid_w)
                tile_norm_y_start = ty_local / float(grid_h)
                tile_norm_y_end = (ty_local + 1) / float(grid_h)

                # Chunk range (0-15) within the tile
                chunk_x_start = max(0, int(
                    (norm_x_min - tile_norm_x_start) /
                    (tile_norm_x_end - tile_norm_x_start) * _CHUNKS_PER_SIDE
                ))
                chunk_x_end = min(_CHUNKS_PER_SIDE, int(math.ceil(
                    (norm_x_max - tile_norm_x_start) /
                    (tile_norm_x_end - tile_norm_x_start) * _CHUNKS_PER_SIDE
                )))
                chunk_y_start = max(0, int(
                    (norm_y_min - tile_norm_y_start) /
                    (tile_norm_y_end - tile_norm_y_start) * _CHUNKS_PER_SIDE
                ))
                chunk_y_end = min(_CHUNKS_PER_SIDE, int(math.ceil(
                    (norm_y_max - tile_norm_y_start) /
                    (tile_norm_y_end - tile_norm_y_start) * _CHUNKS_PER_SIDE
                )))

                if chunk_x_end <= chunk_x_start or chunk_y_end <= chunk_y_start:
                    continue

                if key not in water_dict:
                    water_dict[key] = []

                water_dict[key].append({
                    'type_id': type_id,
                    'elevation': float(elevation),
                    'x_start': chunk_x_start,
                    'y_start': chunk_y_start,
                    'width': chunk_x_end - chunk_x_start,
                    'height': chunk_y_end - chunk_y_start,
                })


# ===================================================================
# Area ID Stamper
# ===================================================================

def stamp_area_ids(zone_def):
    """
    Assign area IDs to every MCNK chunk based on subzone boundaries.

    Uses a point-in-circle test for each chunk's centre position.
    When multiple subzones overlap, the smallest (most specific)
    subzone wins.

    Args:
        zone_def: Zone definition dict.

    Returns:
        Dict {(tile_x, tile_y, chunk_row, chunk_col): area_id}.
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    area_ids = {}

    for ty in range(grid_h):
        for tx in range(grid_w):
            tile_x = base_x + tx
            tile_y = base_y + ty

            for chunk_row in range(_CHUNKS_PER_SIDE):
                for chunk_col in range(_CHUNKS_PER_SIDE):
                    # Chunk centre in normalised zone coordinates
                    norm_x = (tx + (chunk_col + 0.5) / _CHUNKS_PER_SIDE) / float(grid_w)
                    norm_y = (ty + (chunk_row + 0.5) / _CHUNKS_PER_SIDE) / float(grid_h)

                    area_id = _find_area_id(zone_def, norm_x, norm_y)
                    area_ids[(tile_x, tile_y, chunk_row, chunk_col)] = area_id

    return area_ids


def _find_area_id(zone_def, norm_x, norm_y):
    """
    Find the most specific subzone containing the normalised point.

    Picks the subzone with the smallest radius (most specific)
    among all containing subzones. Returns 0 if no subzone matches.
    """
    best_area_id = 0
    best_radius = float('inf')

    for subzone in zone_def.get('subzones', []):
        center = subzone.get('center', (0.5, 0.5))
        radius = subzone.get('radius', 0.2)

        dx = norm_x - center[0]
        dy = norm_y - center[1]
        if dx * dx + dy * dy <= radius * radius:
            if radius < best_radius:
                best_radius = radius
                best_area_id = subzone.get('area_id', 0)

    return best_area_id


# ===================================================================
# TerrainSculptor (Main Facade)
# ===================================================================

class TerrainSculptor:
    """
    Main facade class for automated terrain generation.

    Orchestrates heightmap generation, texture painting, doodad/WMO
    placement, water planes and area-ID stamping from a zone definition.
    """

    def __init__(self, zone_definition):
        """
        Args:
            zone_definition: Zone definition dict (see module docstring
                             for the expected structure).
        """
        self.zone_def = zone_definition
        self.grid_size = zone_definition.get('grid_size', (1, 1))
        self.base_coords = zone_definition.get('base_coords', (32, 32))

    # ------------------------------------------------------------------
    # Generation methods
    # ------------------------------------------------------------------

    def generate_heightmaps(self):
        """
        Generate heightmaps for all ADT tiles in the zone.

        Returns:
            Dict {(tile_x, tile_y): 2D numpy array (129x129)}.
        """
        heightmaps = {}
        grid_w, grid_h = self.grid_size
        base_x, base_y = self.base_coords

        for ty in range(grid_h):
            for tx in range(grid_w):
                tile_x = base_x + tx
                tile_y = base_y + ty
                heightmaps[(tile_x, tile_y)] = compose_heightmap(
                    self.zone_def, tile_x, tile_y
                )

        return heightmaps

    def generate_textures(self, heightmaps):
        """
        Generate texture layers and alpha maps for all tiles.

        Args:
            heightmaps: Dict returned by generate_heightmaps().

        Returns:
            Dict with keys:
                'texture_paths': global ordered list of texture path strings
                'tile_data': {(tile_x, tile_y): {
                    'texture_paths': list,
                    'chunk_layers': {chunk_idx: {
                        'texture_ids': [int, ...],
                        'alpha_maps': [list-of-lists, ...]
                    }}
                }}
        """
        painter = TexturePainter(self.zone_def)

        tile_data = {}
        all_textures = []
        all_texture_set = {}

        for (tile_x, tile_y), heightmap in heightmaps.items():
            td = painter.paint_textures(heightmap, tile_x, tile_y)
            tile_data[(tile_x, tile_y)] = td

            # Merge into global texture list
            for path in td['texture_paths']:
                if path not in all_texture_set:
                    all_texture_set[path] = len(all_textures)
                    all_textures.append(path)

        return {
            'texture_paths': all_textures,
            'tile_data': tile_data,
        }

    def generate_doodads(self, heightmaps):
        """
        Generate doodad placements (MDDF entries) for the entire zone.

        Args:
            heightmaps: Dict returned by generate_heightmaps().

        Returns:
            List of MDDF entry dicts.
        """
        engine = DoodadScatterEngine(self.zone_def, heightmaps)
        return engine.scatter_all()

    def generate_wmos(self, heightmaps):
        """
        Generate WMO placements (MODF entries) for the entire zone.

        Args:
            heightmaps: Dict returned by generate_heightmaps().

        Returns:
            List of MODF entry dicts.
        """
        engine = WMOPlacementEngine(self.zone_def, heightmaps)
        return engine.place_all()

    def generate_water(self):
        """
        Generate water plane definitions for all tiles.

        Returns:
            Dict {(tile_x, tile_y): list of water region dicts}.
        """
        gen = WaterGenerator(self.zone_def)
        return gen.generate_all()

    def generate_area_ids(self):
        """
        Generate area-ID assignments for every MCNK chunk.

        Returns:
            Dict {(tile_x, tile_y, chunk_row, chunk_col): area_id}.
        """
        return stamp_area_ids(self.zone_def)

    # ------------------------------------------------------------------
    # Integration helpers
    # ------------------------------------------------------------------

    def export_for_adt_composer(self):
        """
        Run the full pipeline and return data in the format expected by
        adt_composer.create_adt().

        For each tile, returns:
            heightmap   - 2D list (compatible with adt_composer's bilinear sampler)
            texture_paths - list of texture path strings (max 4 per tile)
            splat_map   - dict {layer_index: [[row][col]]} alpha maps
            area_id     - int (most common area_id for the tile, used as default)
            doodads     - list of MDDF dicts for this tile
            wmos        - list of MODF dicts for this tile
            water       - list of water region dicts for this tile

        Returns:
            Dict {(tile_x, tile_y): {
                'heightmap': list-of-lists,
                'texture_paths': list[str],
                'splat_map': dict,
                'area_id': int,
                'area_id_map': dict {(chunk_row, chunk_col): int},
                'doodads': list[dict],
                'wmos': list[dict],
                'water': list[dict],
            }}
        """
        heightmaps = self.generate_heightmaps()
        textures = self.generate_textures(heightmaps)
        doodads = self.generate_doodads(heightmaps)
        wmos = self.generate_wmos(heightmaps)
        water = self.generate_water()
        area_ids = self.generate_area_ids()

        result = {}
        grid_w, grid_h = self.grid_size
        base_x, base_y = self.base_coords

        for ty in range(grid_h):
            for tx in range(grid_w):
                tile_x = base_x + tx
                tile_y = base_y + ty
                key = (tile_x, tile_y)

                # Heightmap as plain list-of-lists
                hm = heightmaps[key]
                hm_list = hm.tolist()

                # Texture data for this tile
                tile_tex = textures['tile_data'].get(key, {})
                tile_tex_paths = tile_tex.get('texture_paths', [_DEFAULT_TEXTURE_BLACK])
                chunk_layers = tile_tex.get('chunk_layers', {})

                # Build per-tile texture_paths (max 4) and splat_map
                # Collect the most common textures across all chunks
                tex_freq = {}
                for cl in chunk_layers.values():
                    for tid in cl.get('texture_ids', []):
                        if tid is not None and tid < len(tile_tex_paths):
                            path = tile_tex_paths[tid]
                            tex_freq[path] = tex_freq.get(path, 0) + 1

                # Sort by frequency, take top 4
                sorted_tex = sorted(tex_freq.items(), key=lambda x: -x[1])
                final_tex_paths = [t[0] for t in sorted_tex[:4]]
                if not final_tex_paths:
                    final_tex_paths = [_DEFAULT_TEXTURE_BLACK]

                # Build splat_map: for layers > 0, combine alpha maps from
                # all 256 chunks into a single 64x64 map per layer.
                # The adt_composer expects splat_map[layer_index] as a 2D
                # array where the 64x64 block for chunk (row, col) is tiled
                # in row-major order.
                # Actually, adt_composer applies the same alpha to all chunks,
                # so we produce a per-chunk override structure.
                splat_map = {}
                for layer_idx in range(1, len(final_tex_paths)):
                    # For each chunk, try to find an alpha map for this layer
                    # Build a combined 64x64 default
                    splat_map[layer_idx] = [[128] * 64 for _ in range(64)]

                # Area IDs for this tile
                tile_area_ids = {}
                for chunk_row in range(_CHUNKS_PER_SIDE):
                    for chunk_col in range(_CHUNKS_PER_SIDE):
                        aid = area_ids.get(
                            (tile_x, tile_y, chunk_row, chunk_col), 0
                        )
                        tile_area_ids[(chunk_row, chunk_col)] = aid

                # Most common area_id as the tile default
                aid_counts = {}
                for aid in tile_area_ids.values():
                    aid_counts[aid] = aid_counts.get(aid, 0) + 1
                default_area_id = max(aid_counts, key=aid_counts.get) if aid_counts else 0

                # Filter doodads/WMOs to this tile's world bounds
                tile_doodads = self._filter_entries_to_tile(
                    doodads, tile_x, tile_y
                )
                tile_wmos = self._filter_entries_to_tile(
                    wmos, tile_x, tile_y
                )

                # Water for this tile
                tile_water = water.get(key, [])

                result[key] = {
                    'heightmap': hm_list,
                    'texture_paths': final_tex_paths,
                    'splat_map': splat_map if splat_map else None,
                    'area_id': default_area_id,
                    'area_id_map': tile_area_ids,
                    'doodads': tile_doodads,
                    'wmos': tile_wmos,
                    'water': tile_water,
                }

        return result

    def _filter_entries_to_tile(self, entries, tile_x, tile_y):
        """
        Filter placement entries to those whose world position falls
        within the given tile.
        """
        # Tile world bounds (WoW coordinates)
        tile_world_x_max = MAP_SIZE_MAX - tile_y * TILE_SIZE
        tile_world_x_min = tile_world_x_max - TILE_SIZE
        tile_world_y_max = MAP_SIZE_MAX - tile_x * TILE_SIZE
        tile_world_y_min = tile_world_y_max - TILE_SIZE

        result = []
        for entry in entries:
            pos = entry.get('position', (0, 0, 0))
            wx, wy = pos[0], pos[1]
            if (tile_world_x_min <= wx <= tile_world_x_max and
                    tile_world_y_min <= wy <= tile_world_y_max):
                result.append(entry)
        return result


# ===================================================================
# High-Level API
# ===================================================================

def sculpt_zone(zone_def):
    """
    Generate complete terrain data from a zone definition.

    This is the primary entry point for fully automated terrain generation.
    It orchestrates heightmap composition, texture painting, doodad/WMO
    placement, water planes and area-ID stamping.

    Args:
        zone_def: Zone definition dict with the following structure::

            {
                'name': str,
                'grid_size': (width, height),   # in ADT tiles
                'base_coords': (x, y),          # starting tile coords
                'sea_level': float,
                'seed': int,
                'global_water': {'elevation': float, 'type': str},
                'subzones': [SubzoneDefinition, ...],
            }

        Each SubzoneDefinition is a dict with keys:
            name, area_id, center, radius, shape, falloff,
            terrain_type, elevation, terrain_params, noise_params,
            weight, textures, doodads, doodad_filters, structures, water

    Returns:
        dict with keys:
            heightmaps  - {(tile_x, tile_y): numpy array (129x129)}
            textures    - {texture_paths: [...], tile_data: {...}}
            doodads     - [MDDF entry dicts]
            wmos        - [MODF entry dicts]
            water       - {(tile_x, tile_y): [water region dicts]}
            area_ids    - {(tile_x, tile_y, chunk_row, chunk_col): area_id}
    """
    sculptor = TerrainSculptor(zone_def)

    heightmaps = sculptor.generate_heightmaps()
    textures = sculptor.generate_textures(heightmaps)
    doodads = sculptor.generate_doodads(heightmaps)
    wmos = sculptor.generate_wmos(heightmaps)
    water = sculptor.generate_water()
    area_ids = sculptor.generate_area_ids()

    return {
        'heightmaps': heightmaps,
        'textures': textures,
        'doodads': doodads,
        'wmos': wmos,
        'water': water,
        'area_ids': area_ids,
    }


def sculpt_for_adt_composer(zone_def):
    """
    Convenience wrapper that runs sculpt_zone and reformats the output
    for direct consumption by adt_composer.create_adt().

    Args:
        zone_def: Zone definition dict (same as sculpt_zone).

    Returns:
        Dict {(tile_x, tile_y): tile_data_dict} where each tile_data_dict
        contains heightmap, texture_paths, splat_map, area_id, area_id_map,
        doodads, wmos, and water.
    """
    sculptor = TerrainSculptor(zone_def)
    return sculptor.export_for_adt_composer()


# ===================================================================
# ADT Import Functions
# ===================================================================

def import_heightmap_from_adt(adt_filepath):
    """
    Import a heightmap from an existing ADT file as a numpy array.

    Reads the ADT file using adt_composer.read_adt() and converts the
    129x129 heightmap list-of-lists to a numpy ndarray.

    Args:
        adt_filepath: Path to the ADT file (string or path-like object).

    Returns:
        numpy.ndarray: 2D float64 array of shape (129, 129) containing
            the terrain height values.

    Raises:
        ImportError: If the parent ADTFile library is not available.
        ValueError: If the ADT file cannot be parsed.
    """
    from . import adt_composer

    log.debug("Importing heightmap from ADT: %s", adt_filepath)
    adt_data = adt_composer.read_adt(adt_filepath)

    heightmap_list = adt_data['heightmap']
    heightmap = np.array(heightmap_list, dtype=np.float64)

    log.debug("Imported heightmap shape: %s, range: [%.2f, %.2f]",
              heightmap.shape, float(np.min(heightmap)), float(np.max(heightmap)))

    return heightmap


def import_texture_rules_from_adt(adt_filepath):
    """
    Analyze an existing ADT file and infer texture painting rules.

    Reads the ADT, then for each texture layer correlates alpha map
    weights with heightmap elevation and computed slope values.  This
    produces elevation and slope range rules that approximate the
    original texture painting, suitable for use with TexturePainter.

    Args:
        adt_filepath: Path to the ADT file (string or path-like object).

    Returns:
        dict: {
            'texture_paths': list of str,
            'elevation_rules': list of dict, one per texture layer:
                {'texture': str, 'min_elevation': float, 'max_elevation': float},
            'slope_rules': list of dict, one per texture layer:
                {'texture': str, 'min_slope': float, 'max_slope': float},
        }

    Raises:
        ImportError: If the parent ADTFile library is not available.
        ValueError: If the ADT file cannot be parsed.
    """
    from . import adt_composer

    log.debug("Importing texture rules from ADT: %s", adt_filepath)
    adt_data = adt_composer.read_adt(adt_filepath)

    heightmap = np.array(adt_data['heightmap'], dtype=np.float64)
    slope_map = calculate_slope(heightmap)
    texture_paths = adt_data['texture_paths']
    splat_data = adt_data['splat_map']

    # Alpha weight threshold: only consider cells where the alpha is
    # above this value as "active" for the texture layer.
    alpha_threshold = 25

    elevation_rules = []
    slope_rules = []

    # Layer 0 is the base layer (no alpha map, always present).
    # We infer its range as the full heightmap range.
    if texture_paths:
        elevation_rules.append({
            'texture': texture_paths[0],
            'min_elevation': float(np.min(heightmap)),
            'max_elevation': float(np.max(heightmap)),
        })
        slope_rules.append({
            'texture': texture_paths[0],
            'min_slope': 0.0,
            'max_slope': float(np.max(slope_map)),
        })

    # For layers 1+, analyze correlation with per-chunk alpha maps.
    for layer_idx in range(1, len(texture_paths)):
        per_chunk_alphas = splat_data.get(layer_idx, {})

        if not per_chunk_alphas:
            # No alpha data for this layer; use defaults
            elevation_rules.append({
                'texture': texture_paths[layer_idx],
                'min_elevation': float(np.min(heightmap)),
                'max_elevation': float(np.max(heightmap)),
            })
            slope_rules.append({
                'texture': texture_paths[layer_idx],
                'min_slope': 0.0,
                'max_slope': float(np.max(slope_map)),
            })
            continue

        # Collect elevation and slope samples weighted by alpha
        weighted_elevations = []
        weighted_slopes = []

        for (chunk_row, chunk_col), alpha_2d in per_chunk_alphas.items():
            # The outer vertices for this chunk span rows
            # [chunk_row*8 .. chunk_row*8+8] and cols [chunk_col*8 .. chunk_col*8+8]
            # in the 129x129 heightmap.  The alpha map is 64x64 per chunk.
            vr_start = chunk_row * 8
            vc_start = chunk_col * 8

            for alpha_row in range(64):
                for alpha_col in range(64):
                    alpha_val = alpha_2d[alpha_row][alpha_col]
                    if alpha_val < alpha_threshold:
                        continue

                    # Map alpha cell to heightmap coordinates
                    # 64 alpha cells cover the 8 vertex intervals of a chunk
                    hm_row = vr_start + int(alpha_row * 8.0 / 64.0)
                    hm_col = vc_start + int(alpha_col * 8.0 / 64.0)
                    hm_row = min(hm_row, _HEIGHTMAP_RES - 1)
                    hm_col = min(hm_col, _HEIGHTMAP_RES - 1)

                    weighted_elevations.append(float(heightmap[hm_row, hm_col]))
                    weighted_slopes.append(float(slope_map[hm_row, hm_col]))

        if weighted_elevations:
            elev_arr = np.array(weighted_elevations)
            slope_arr = np.array(weighted_slopes)
            elevation_rules.append({
                'texture': texture_paths[layer_idx],
                'min_elevation': float(np.percentile(elev_arr, 5)),
                'max_elevation': float(np.percentile(elev_arr, 95)),
            })
            slope_rules.append({
                'texture': texture_paths[layer_idx],
                'min_slope': float(np.percentile(slope_arr, 5)),
                'max_slope': float(np.percentile(slope_arr, 95)),
            })
        else:
            # No active samples; use full range as fallback
            elevation_rules.append({
                'texture': texture_paths[layer_idx],
                'min_elevation': float(np.min(heightmap)),
                'max_elevation': float(np.max(heightmap)),
            })
            slope_rules.append({
                'texture': texture_paths[layer_idx],
                'min_slope': 0.0,
                'max_slope': float(np.max(slope_map)),
            })

    log.debug("Inferred %d elevation rules and %d slope rules",
              len(elevation_rules), len(slope_rules))

    return {
        'texture_paths': texture_paths,
        'elevation_rules': elevation_rules,
        'slope_rules': slope_rules,
    }
