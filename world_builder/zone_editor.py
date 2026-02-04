"""
Zone Editor - Load, query, and edit existing or planned WoW zones.

Provides tools to:
- Load existing ADT files into a zone_definition dict (round-trippable)
- Query terrain data at any position (elevation, textures, doodads, area IDs)
- Edit zone definitions (add/remove subzones, modify terrain, change textures)
- Export edited zones back to ADT-compatible format

Works with zone_definition dicts from both plan_zone() and load_zone_from_adts().

Usage:
    from world_builder.zone_editor import (
        load_zone_from_adts, query_position, add_landmark,
        modify_terrain_at, export_for_adt_composer,
    )
"""

import glob
import logging
import math
import os
import re
import random

log = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "numpy is required for zone_editor. Install it with: pip install numpy"
    )

from .terrain_sculptor import (
    TILE_SIZE, MAP_SIZE_MAX,
    _HEIGHTMAP_RES, _CHUNKS_PER_SIDE,
    compose_heightmap, calculate_slope, _find_area_id,
    TerrainSculptor, SimplexNoise, generate_mask,
)
from .zone_planner import (
    TEXTURE_PALETTES, DOODAD_PALETTES,
    _LANDMARK_TRANSLATORS, _AreaIDCounter, _resolve_position,
    _pick_textures, _pick_doodads,
)


# ---------------------------------------------------------------------------
# Coordinate Conversion Utilities
# ---------------------------------------------------------------------------

def world_to_norm(zone_def, world_x, world_y):
    """Convert WoW world coordinates to normalised (0-1) zone coordinates.

    Args:
        zone_def: Zone definition dict.
        world_x: WoW world X coordinate (north-south axis).
        world_y: WoW world Y coordinate (east-west axis).

    Returns:
        (norm_x, norm_y) tuple in [0, 1] range (may exceed bounds if
        outside the zone grid).
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    tile_fy = (MAP_SIZE_MAX - world_x) / TILE_SIZE
    tile_fx = (MAP_SIZE_MAX - world_y) / TILE_SIZE

    norm_x = (tile_fx - base_x) / float(grid_w)
    norm_y = (tile_fy - base_y) / float(grid_h)
    return (norm_x, norm_y)


def norm_to_world(zone_def, norm_x, norm_y):
    """Convert normalised (0-1) zone coordinates to WoW world coordinates.

    Args:
        zone_def: Zone definition dict.
        norm_x: Normalised X coordinate (0.0 to 1.0).
        norm_y: Normalised Y coordinate (0.0 to 1.0).

    Returns:
        (world_x, world_y) tuple in WoW world yards.
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    tile_fx = base_x + norm_x * grid_w
    tile_fy = base_y + norm_y * grid_h

    world_x = MAP_SIZE_MAX - tile_fy * TILE_SIZE
    world_y = MAP_SIZE_MAX - tile_fx * TILE_SIZE
    return (world_x, world_y)


def norm_to_tile(zone_def, norm_x, norm_y):
    """Convert normalised coordinates to tile and chunk indices.

    Args:
        zone_def: Zone definition dict.
        norm_x, norm_y: Normalised coordinates (0-1).

    Returns:
        dict: {
            'tile_x': int, 'tile_y': int,
            'chunk_row': int, 'chunk_col': int,
            'local_x': float, 'local_y': float,  # fractional within tile [0,1]
        }
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    tile_fx = norm_x * grid_w
    tile_fy = norm_y * grid_h
    tile_ix = int(math.floor(tile_fx))
    tile_iy = int(math.floor(tile_fy))

    local_x = tile_fx - tile_ix
    local_y = tile_fy - tile_iy

    chunk_col = min(int(local_x * _CHUNKS_PER_SIDE), _CHUNKS_PER_SIDE - 1)
    chunk_row = min(int(local_y * _CHUNKS_PER_SIDE), _CHUNKS_PER_SIDE - 1)

    return {
        'tile_x': base_x + tile_ix,
        'tile_y': base_y + tile_iy,
        'chunk_row': chunk_row,
        'chunk_col': chunk_col,
        'local_x': local_x,
        'local_y': local_y,
    }


def tile_to_norm(zone_def, tile_x, tile_y, chunk_row=0, chunk_col=0):
    """Convert tile/chunk coordinates to normalised zone coordinates.

    Args:
        zone_def: Zone definition dict.
        tile_x, tile_y: Absolute tile coordinates.
        chunk_row, chunk_col: Chunk indices within tile (0-15).

    Returns:
        (norm_x, norm_y) tuple.
    """
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    local_tx = tile_x - base_x
    local_ty = tile_y - base_y

    norm_x = (local_tx + (chunk_col + 0.5) / _CHUNKS_PER_SIDE) / float(grid_w)
    norm_y = (local_ty + (chunk_row + 0.5) / _CHUNKS_PER_SIDE) / float(grid_h)
    return (norm_x, norm_y)


# ---------------------------------------------------------------------------
# Heightmap Cache
# ---------------------------------------------------------------------------

def _ensure_heightmaps(zone_def):
    """Ensure _loaded_heightmaps exists in zone_def.

    If zone_def was created by plan_zone() (no loaded heightmaps),
    generates them via TerrainSculptor and stores them.

    Returns:
        dict: The _loaded_heightmaps dict {(tile_x, tile_y): numpy array}.
    """
    if '_loaded_heightmaps' in zone_def:
        return zone_def['_loaded_heightmaps']

    sculptor = TerrainSculptor(zone_def)
    heightmaps = sculptor.generate_heightmaps()
    zone_def['_loaded_heightmaps'] = heightmaps
    return heightmaps


def _sample_heightmap(heightmaps, zone_def, norm_x, norm_y):
    """Sample elevation at normalised coordinates using bilinear interpolation."""
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    tile_fx = norm_x * grid_w
    tile_fy = norm_y * grid_h
    tile_ix = int(math.floor(tile_fx))
    tile_iy = int(math.floor(tile_fy))

    key = (base_x + tile_ix, base_y + tile_iy)
    hm = heightmaps.get(key)
    if hm is None:
        return 0.0

    local_x = tile_fx - tile_ix
    local_y = tile_fy - tile_iy

    col_f = local_x * (_HEIGHTMAP_RES - 1)
    row_f = local_y * (_HEIGHTMAP_RES - 1)

    c0 = int(col_f)
    r0 = int(row_f)
    c1 = min(c0 + 1, _HEIGHTMAP_RES - 1)
    r1 = min(r0 + 1, _HEIGHTMAP_RES - 1)
    fc = col_f - c0
    fr = row_f - r0

    if isinstance(hm, np.ndarray):
        v00 = float(hm[r0, c0])
        v01 = float(hm[r0, c1])
        v10 = float(hm[r1, c0])
        v11 = float(hm[r1, c1])
    else:
        v00 = float(hm[r0][c0])
        v01 = float(hm[r0][c1])
        v10 = float(hm[r1][c0])
        v11 = float(hm[r1][c1])

    return (v00 * (1 - fr) * (1 - fc) +
            v01 * (1 - fr) * fc +
            v10 * fr * (1 - fc) +
            v11 * fr * fc)


# ---------------------------------------------------------------------------
# Loading from ADT Files
# ---------------------------------------------------------------------------

def load_zone_from_adts(adt_dir, map_name, base_coords=None, name=None):
    """Load existing ADT files and reconstruct a zone_definition dict.

    Scans adt_dir for files matching {map_name}_{X}_{Y}.adt, reads each
    one, and assembles a zone_definition compatible with plan_zone() output
    and sculpt_for_adt_composer() input.

    Args:
        adt_dir: Directory containing ADT files.
        map_name: Map directory name (e.g. "Azeroth").
        base_coords: Optional (x, y) override for base tile coords.
            If None, auto-detected from filenames.
        name: Display name for the zone. Defaults to map_name.

    Returns:
        dict: zone_definition with keys:
            name, grid_size, base_coords, sea_level, seed, subzones,
            texture_palette, doodad_palette, global_water,
            _loaded_heightmaps, _loaded_tile_data
    """
    from .adt_composer import read_adt

    if name is None:
        name = map_name

    # Discover ADT files
    pattern = os.path.join(adt_dir, "{}_*_*.adt".format(map_name))
    adt_files = glob.glob(pattern)
    if not adt_files:
        # Try case-insensitive search
        all_files = os.listdir(adt_dir) if os.path.isdir(adt_dir) else []
        prefix = map_name.lower() + "_"
        adt_files = [
            os.path.join(adt_dir, f) for f in all_files
            if f.lower().startswith(prefix) and f.lower().endswith('.adt')
        ]

    if not adt_files:
        raise FileNotFoundError(
            "No ADT files found matching {}_*_*.adt in {}".format(
                map_name, adt_dir))

    # Parse tile coordinates from filenames
    tile_coords = {}
    coord_pattern = re.compile(
        r'{}[_](\d+)[_](\d+)\.adt$'.format(re.escape(map_name)),
        re.IGNORECASE)

    for filepath in adt_files:
        basename = os.path.basename(filepath)
        m = coord_pattern.search(basename)
        if m:
            tx, ty = int(m.group(1)), int(m.group(2))
            tile_coords[(tx, ty)] = filepath

    if not tile_coords:
        raise ValueError("Could not parse tile coordinates from ADT filenames")

    # Determine grid bounds
    all_tx = [k[0] for k in tile_coords]
    all_ty = [k[1] for k in tile_coords]
    min_tx, max_tx = min(all_tx), max(all_tx)
    min_ty, max_ty = min(all_ty), max(all_ty)

    if base_coords is None:
        base_coords = (min_tx, min_ty)

    grid_size = (max_tx - min_tx + 1, max_ty - min_ty + 1)

    # Read all ADT files
    heightmaps = {}
    tile_data_loaded = {}
    all_area_ids = set()
    all_texture_paths = set()
    all_doodads = {}
    sea_level_candidates = []

    for (tx, ty), filepath in tile_coords.items():
        log.info("Reading ADT: %s", filepath)
        try:
            adt_data = read_adt(filepath)
        except Exception as exc:
            log.warning("Failed to read %s: %s", filepath, exc)
            continue

        # Store heightmap
        hm = adt_data['heightmap']
        if isinstance(hm, list):
            hm = np.array(hm, dtype=np.float64)
        heightmaps[(tx, ty)] = hm

        # Collect textures
        for path in adt_data.get('texture_paths', []):
            all_texture_paths.add(path)

        # Collect area IDs from chunks
        for chunk_row_data in adt_data.get('chunks', []):
            if chunk_row_data is None:
                continue
            for chunk_data in chunk_row_data:
                if chunk_data is not None:
                    aid = chunk_data.get('area_id', 0)
                    if aid > 0:
                        all_area_ids.add(aid)

        # Collect doodad info
        for dinst in adt_data.get('doodad_instances', []):
            nid = dinst.get('name_id', 0)
            m2_names = adt_data.get('m2_filenames', [])
            if nid < len(m2_names):
                m2_path = m2_names[nid]
                all_doodads[m2_path] = all_doodads.get(m2_path, 0) + 1

        # Estimate sea level from lowest heights
        flat_hm = hm.flatten()
        low_pct = np.percentile(flat_hm, 5)
        sea_level_candidates.append(low_pct)

        tile_data_loaded[(tx, ty)] = adt_data

    # Estimate sea level
    if sea_level_candidates:
        sea_level = float(np.median(sea_level_candidates))
    else:
        sea_level = 0.0

    # Build subzones from area IDs
    subzones = []
    area_id_chunks = {}  # area_id -> list of (norm_x, norm_y)

    for (tx, ty), adt_data in tile_data_loaded.items():
        chunks = adt_data.get('chunks', [])
        for crow in range(_CHUNKS_PER_SIDE):
            for ccol in range(_CHUNKS_PER_SIDE):
                if crow < len(chunks) and chunks[crow] is not None:
                    chunk = chunks[crow][ccol] if ccol < len(chunks[crow]) else None
                else:
                    chunk = None
                if chunk is None:
                    continue
                aid = chunk.get('area_id', 0)
                if aid <= 0:
                    continue

                # Compute normalised position of this chunk center
                local_tx = tx - base_coords[0]
                local_ty = ty - base_coords[1]
                nx = (local_tx + (ccol + 0.5) / _CHUNKS_PER_SIDE) / float(grid_size[0])
                ny = (local_ty + (crow + 0.5) / _CHUNKS_PER_SIDE) / float(grid_size[1])

                if aid not in area_id_chunks:
                    area_id_chunks[aid] = []
                area_id_chunks[aid].append((nx, ny))

    # Convert area ID clusters into subzone definitions
    for aid, positions in area_id_chunks.items():
        if not positions:
            continue
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)

        # Radius: distance from centroid to farthest point
        max_dist = 0.0
        for px, py in positions:
            d = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if d > max_dist:
                max_dist = d
        radius = max(max_dist + 0.02, 0.05)  # small padding

        subzones.append({
            'name': 'area_{}'.format(aid),
            'area_id': aid,
            'center': (cx, cy),
            'radius': radius,
            'terrain_type': 'loaded',
            'elevation': (0, 100),
            'falloff': 0.2,
            'weight': 1.0,
            'textures': [],
            'doodads': {},
            'structures': [],
            'water': [],
        })

    # Build texture palette from discovered textures
    texture_palette = {}
    for path in all_texture_paths:
        parts = path.replace('/', '\\').split('\\')
        if len(parts) >= 2:
            zone_part = parts[-2] if len(parts) > 1 else 'unknown'
            if zone_part not in texture_palette:
                texture_palette[zone_part] = []
            texture_palette[zone_part].append(path)

    # Build doodad palette from discovered doodads
    total_area_yards = grid_size[0] * grid_size[1] * TILE_SIZE * TILE_SIZE
    doodad_palette = {}
    for m2_path, count in all_doodads.items():
        density = count / max(total_area_yards, 1.0)
        doodad_palette[m2_path] = density

    # Determine global water
    global_water = None
    if sea_level_candidates:
        min_height = float(min(sea_level_candidates))
        if min_height < sea_level + 5.0:
            global_water = {'elevation': sea_level, 'type': 'ocean'}

    zone_def = {
        'name': name,
        'grid_size': grid_size,
        'base_coords': base_coords,
        'sea_level': sea_level,
        'seed': 0,
        'subzones': subzones,
        'texture_palette': texture_palette,
        'doodad_palette': doodad_palette,
        '_loaded_heightmaps': heightmaps,
        '_loaded_tile_data': tile_data_loaded,
    }

    if global_water is not None:
        zone_def['global_water'] = global_water

    log.info("Loaded zone '%s': %d tiles, %d subzones, %d textures, %d doodad types",
             name, len(tile_coords), len(subzones),
             len(all_texture_paths), len(all_doodads))

    return zone_def


def load_single_adt(adt_filepath, base_coords=None, name=None):
    """Load a single ADT file into a minimal zone_definition.

    Args:
        adt_filepath: Path to a single ADT file.
        base_coords: Tile coordinates override. If None, derived from file.
        name: Zone display name.

    Returns:
        dict: zone_definition for one tile.
    """
    from .adt_composer import read_adt

    adt_data = read_adt(adt_filepath)
    tx = adt_data.get('tile_x', 32)
    ty = adt_data.get('tile_y', 32)

    if base_coords is None:
        base_coords = (tx, ty)
    if name is None:
        name = os.path.splitext(os.path.basename(adt_filepath))[0]

    hm = adt_data['heightmap']
    if isinstance(hm, list):
        hm = np.array(hm, dtype=np.float64)

    heightmaps = {(tx, ty): hm}

    # Estimate sea level
    sea_level = float(np.percentile(hm.flatten(), 5))

    # Build minimal subzone from area_id
    area_id = adt_data.get('area_id', 0)
    subzones = [{
        'name': name,
        'area_id': area_id,
        'center': (0.5, 0.5),
        'radius': 0.5,
        'terrain_type': 'loaded',
        'elevation': (float(np.min(hm)), float(np.max(hm))),
        'falloff': 0.3,
        'weight': 1.0,
        'textures': adt_data.get('texture_paths', [])[:4],
        'doodads': {},
        'structures': [],
        'water': [],
    }]

    return {
        'name': name,
        'grid_size': (1, 1),
        'base_coords': base_coords,
        'sea_level': sea_level,
        'seed': 0,
        'subzones': subzones,
        'texture_palette': {},
        'doodad_palette': {},
        '_loaded_heightmaps': heightmaps,
        '_loaded_tile_data': {(tx, ty): adt_data},
    }


# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

def query_position(zone_def, x, y):
    """Query all terrain data at a normalised (x, y) coordinate.

    Args:
        zone_def: Zone definition dict.
        x: Normalised X coordinate (0.0 to 1.0).
        y: Normalised Y coordinate (0.0 to 1.0).

    Returns:
        dict with keys: position, world_position, tile, chunk,
        elevation, subzone, subzones_covering, water
    """
    heightmaps = _ensure_heightmaps(zone_def)

    # Sample elevation
    elevation = _sample_heightmap(heightmaps, zone_def, x, y)

    # World position
    world_x, world_y = norm_to_world(zone_def, x, y)

    # Tile and chunk
    tile_info = norm_to_tile(zone_def, x, y)

    # Find covering subzones
    covering = _find_covering_subzones(zone_def, x, y)

    # Area ID (most specific subzone)
    area_id = _find_area_id(zone_def, x, y)

    # Primary subzone name
    primary_name = None
    if covering:
        primary_name = covering[0].get('name')

    # Water check
    water = _check_water_at(zone_def, x, y, elevation)

    return {
        'position': (x, y),
        'world_position': (world_x, world_y, elevation),
        'tile': (tile_info['tile_x'], tile_info['tile_y']),
        'chunk': (tile_info['chunk_row'], tile_info['chunk_col']),
        'elevation': elevation,
        'subzone': primary_name,
        'area_id': area_id,
        'subzones_covering': covering,
        'water': water,
    }


def query_tile(zone_def, tile_x, tile_y):
    """Return a summary of a specific tile.

    Args:
        zone_def: Zone definition dict.
        tile_x: Absolute tile X coordinate.
        tile_y: Absolute tile Y coordinate.

    Returns:
        dict with tile summary info.
    """
    heightmaps = _ensure_heightmaps(zone_def)
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    local_tx = tile_x - base_x
    local_ty = tile_y - base_y

    x_start = local_tx / float(grid_w)
    y_start = local_ty / float(grid_h)
    x_end = (local_tx + 1) / float(grid_w)
    y_end = (local_ty + 1) / float(grid_h)

    # Elevation stats
    hm = heightmaps.get((tile_x, tile_y))
    if hm is not None:
        if isinstance(hm, np.ndarray):
            elev_min = float(np.min(hm))
            elev_max = float(np.max(hm))
            elev_mean = float(np.mean(hm))
        else:
            flat = [hm[r][c] for r in range(len(hm)) for c in range(len(hm[r]))]
            elev_min = min(flat)
            elev_max = max(flat)
            elev_mean = sum(flat) / len(flat)
    else:
        elev_min = elev_max = elev_mean = 0.0

    # Find overlapping subzones
    tile_subzones = []
    for sz in zone_def.get('subzones', []):
        cx, cy = sz.get('center', (0.5, 0.5))
        r = sz.get('radius', 0.2)
        # Check if subzone circle overlaps tile rectangle
        closest_x = max(x_start, min(cx, x_end))
        closest_y = max(y_start, min(cy, y_end))
        dist = math.sqrt((cx - closest_x) ** 2 + (cy - closest_y) ** 2)
        if dist <= r:
            tile_subzones.append({
                'name': sz.get('name', 'unnamed'),
                'area_id': sz.get('area_id', 0),
                'terrain_type': sz.get('terrain_type', 'noise'),
            })

    # Water check
    has_water = False
    water_types = set()
    if zone_def.get('global_water'):
        has_water = True
        water_types.add(zone_def['global_water'].get('type', 'ocean'))
    for sz in zone_def.get('subzones', []):
        for w in sz.get('water', []):
            has_water = True
            water_types.add(w.get('type', 'ocean'))

    return {
        'tile_coords': (tile_x, tile_y),
        'local_coords': (local_tx, local_ty),
        'norm_bounds': (x_start, y_start, x_end, y_end),
        'elevation_stats': {
            'min': elev_min, 'max': elev_max, 'mean': elev_mean,
        },
        'subzones': tile_subzones,
        'has_water': has_water,
        'water_types': sorted(water_types),
    }


def query_subzone_at(zone_def, x, y):
    """Return which subzone(s) cover a normalised (x, y) point.

    Args:
        zone_def: Zone definition dict.
        x, y: Normalised coordinates (0-1).

    Returns:
        list of dict, sorted by radius ascending (most specific first).
        Each dict has: name, area_id, terrain_type, radius,
        distance_to_center, is_primary.
    """
    return _find_covering_subzones(zone_def, x, y)


def _find_covering_subzones(zone_def, x, y):
    """Find all subzones covering a point, sorted by radius."""
    results = []
    for sz in zone_def.get('subzones', []):
        cx, cy = sz.get('center', (0.5, 0.5))
        r = sz.get('radius', 0.2)
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        if dist <= r:
            results.append({
                'name': sz.get('name', 'unnamed'),
                'area_id': sz.get('area_id', 0),
                'terrain_type': sz.get('terrain_type', 'noise'),
                'radius': r,
                'distance_to_center': dist,
                'is_primary': False,
            })

    results.sort(key=lambda e: e['radius'])
    if results:
        results[0]['is_primary'] = True
    return results


def _check_water_at(zone_def, x, y, elevation):
    """Check for water at a position."""
    # Global water
    gw = zone_def.get('global_water')
    if gw is not None:
        water_elev = gw.get('elevation', 0.0)
        if elevation < water_elev:
            return {
                'type': gw.get('type', 'ocean'),
                'elevation': water_elev,
                'depth': water_elev - elevation,
            }

    # Per-subzone water
    for sz in zone_def.get('subzones', []):
        cx, cy = sz.get('center', (0.5, 0.5))
        r = sz.get('radius', 0.2)
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        if dist <= r:
            for w in sz.get('water', []):
                water_elev = w.get('elevation', 0.0)
                if elevation < water_elev:
                    return {
                        'type': w.get('type', 'ocean'),
                        'elevation': water_elev,
                        'depth': water_elev - elevation,
                    }
    return None


# ---------------------------------------------------------------------------
# Subzone Edit Operations
# ---------------------------------------------------------------------------

def add_subzone(zone_def, name, center, radius, terrain_type='noise',
                elevation=(0, 50), textures=None, doodads=None,
                area_id=None, **kwargs):
    """Add a new subzone to a zone definition.

    Args:
        zone_def: Zone definition dict (modified in-place).
        name: Subzone display name.
        center: (x, y) normalised coordinates or position name string.
        radius: Normalised radius.
        terrain_type: Terrain primitive type.
        elevation: (min, max) tuple.
        textures: List of BLP paths (max 4).
        doodads: Dict {m2_path: density} or None.
        area_id: Explicit area_id or None for auto-allocation.
        **kwargs: Additional subzone fields.

    Returns:
        dict: The added subzone dict.
    """
    cx, cy = _resolve_position(center)

    if area_id is None:
        max_aid = 0
        for sz in zone_def.get('subzones', []):
            aid = sz.get('area_id', 0)
            if aid > max_aid:
                max_aid = aid
        area_id = max_aid + 1

    subzone = {
        'name': name,
        'area_id': area_id,
        'center': (cx, cy),
        'radius': float(radius),
        'terrain_type': terrain_type,
        'elevation': elevation,
        'falloff': kwargs.get('falloff', 0.2),
        'weight': kwargs.get('weight', 1.0),
        'textures': textures or [],
        'doodads': doodads or {},
        'structures': kwargs.get('structures', []),
        'water': kwargs.get('water', []),
    }

    # Optional fields
    for key in ('noise_params', 'terrain_params', 'doodad_filters',
                'shape', 'polygon'):
        if key in kwargs:
            subzone[key] = kwargs[key]

    zone_def.setdefault('subzones', []).append(subzone)

    # Invalidate heightmap cache since terrain changed
    zone_def.pop('_loaded_heightmaps', None)

    return subzone


def remove_subzone(zone_def, name=None, area_id=None, index=None):
    """Remove a subzone by name, area_id, or index.

    Returns:
        dict or None: The removed subzone.
    """
    subzones = zone_def.get('subzones', [])

    if index is not None:
        if 0 <= index < len(subzones):
            removed = subzones.pop(index)
            zone_def.pop('_loaded_heightmaps', None)
            return removed
        return None

    for i, sz in enumerate(subzones):
        if name is not None and sz.get('name') == name:
            removed = subzones.pop(i)
            zone_def.pop('_loaded_heightmaps', None)
            return removed
        if area_id is not None and sz.get('area_id') == area_id:
            removed = subzones.pop(i)
            zone_def.pop('_loaded_heightmaps', None)
            return removed

    return None


def modify_subzone(zone_def, name=None, area_id=None, index=None, **updates):
    """Modify properties of an existing subzone.

    Args:
        zone_def: Zone definition dict (modified in-place).
        name/area_id/index: Identifier for the subzone to modify.
        **updates: Fields to update.

    Returns:
        dict or None: The modified subzone.
    """
    subzones = zone_def.get('subzones', [])
    target = None

    if index is not None:
        if 0 <= index < len(subzones):
            target = subzones[index]
    elif name is not None:
        for sz in subzones:
            if sz.get('name') == name:
                target = sz
                break
    elif area_id is not None:
        for sz in subzones:
            if sz.get('area_id') == area_id:
                target = sz
                break

    if target is None:
        return None

    # Resolve position if provided as string
    if 'center' in updates:
        updates['center'] = _resolve_position(updates['center'])

    target.update(updates)

    # Invalidate heightmap cache
    terrain_keys = {'center', 'radius', 'terrain_type', 'elevation',
                    'falloff', 'weight', 'noise_params', 'terrain_params'}
    if terrain_keys & set(updates.keys()):
        zone_def.pop('_loaded_heightmaps', None)

    return target


# ---------------------------------------------------------------------------
# Landmark Operations
# ---------------------------------------------------------------------------

def add_landmark(zone_def, landmark_type, position, archetype=None, **kwargs):
    """Add a landmark using existing zone_planner translators.

    Args:
        zone_def: Zone definition dict (modified in-place).
        landmark_type: Supported type string (e.g. 'volcano', 'peak').
        position: Named string or (x, y) tuple.
        archetype: Archetype key for palette selection. If None, inferred.
        **kwargs: Additional landmark parameters.

    Returns:
        list: The subzone(s) added.
    """
    ltype = landmark_type.lower()
    translator = _LANDMARK_TRANSLATORS.get(ltype)
    if translator is None:
        raise ValueError(
            "Unknown landmark type '{}'. Valid: {}".format(
                ltype, ', '.join(sorted(set(_LANDMARK_TRANSLATORS.keys())))))

    if archetype is None:
        archetype = _detect_archetype(zone_def)
    if archetype is None:
        archetype = 'forested_highlands'

    # Area ID counter starting from max existing + 1
    max_aid = 0
    for sz in zone_def.get('subzones', []):
        aid = sz.get('area_id', 0)
        if aid > max_aid:
            max_aid = aid
    ids = _AreaIDCounter(max_aid + 1)

    landmark = dict(kwargs)
    landmark['type'] = ltype
    landmark['position'] = position

    new_subzones = translator(landmark, archetype, ids)
    zone_def.setdefault('subzones', []).extend(new_subzones)

    # Invalidate cache
    zone_def.pop('_loaded_heightmaps', None)

    return new_subzones


def remove_landmark(zone_def, name):
    """Remove a landmark (subzone) by name."""
    return remove_subzone(zone_def, name=name)


# ---------------------------------------------------------------------------
# Terrain Modification
# ---------------------------------------------------------------------------

def modify_terrain_at(zone_def, x, y, radius, operation, amount,
                      falloff=0.3):
    """Modify terrain height at a normalised position.

    Operates on _loaded_heightmaps by directly modifying stored arrays.
    For planned zones, generates heightmaps first.

    Args:
        zone_def: Zone definition dict (modified in-place).
        x, y: Normalised center of modification.
        radius: Normalised radius of effect.
        operation: 'raise', 'lower', 'flatten', 'smooth', or 'noise'.
        amount: Height delta in yards (raise/lower) or target height (flatten).
        falloff: Edge transition width.

    Returns:
        dict: {'affected_tiles': [...], 'elevation_delta': {'min', 'max'}}
    """
    heightmaps = _ensure_heightmaps(zone_def)
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    affected_tiles = []
    delta_min = 0.0
    delta_max = 0.0

    for ty in range(grid_h):
        for tx in range(grid_w):
            tile_x = base_x + tx
            tile_y = base_y + ty

            key = (tile_x, tile_y)
            hm = heightmaps.get(key)
            if hm is None:
                continue

            if not isinstance(hm, np.ndarray):
                hm = np.array(hm, dtype=np.float64)
                heightmaps[key] = hm

            # Check if the modification circle overlaps this tile
            x_start = tx / float(grid_w)
            x_end = (tx + 1) / float(grid_w)
            y_start = ty / float(grid_h)
            y_end = (ty + 1) / float(grid_h)

            closest_x = max(x_start, min(x, x_end))
            closest_y = max(y_start, min(y, y_end))
            dist_to_tile = math.sqrt((x - closest_x) ** 2 + (y - closest_y) ** 2)
            if dist_to_tile > radius:
                continue

            # Map the brush to tile-local coordinates
            size = (_HEIGHTMAP_RES, _HEIGHTMAP_RES)
            local_cx = (x - x_start) / (x_end - x_start)
            local_cy = (y - y_start) / (y_end - y_start)
            local_r = radius / (x_end - x_start)

            mask = generate_mask(size, (local_cx, local_cy), local_r,
                                 shape='circle', falloff=falloff)

            old_hm = hm.copy()

            if operation == 'raise':
                hm += float(amount) * mask
            elif operation == 'lower':
                hm -= float(amount) * mask
            elif operation == 'flatten':
                hm[:] = hm * (1.0 - mask) + float(amount) * mask
            elif operation == 'smooth':
                # Simple box blur within the mask
                from scipy.ndimage import uniform_filter
                smoothed = uniform_filter(hm, size=5)
                hm[:] = hm * (1.0 - mask) + smoothed * mask
            elif operation == 'noise':
                noise_gen = SimplexNoise(seed=random.randint(0, 2**31))
                noise_arr = np.zeros_like(hm)
                for row in range(_HEIGHTMAP_RES):
                    for col in range(_HEIGHTMAP_RES):
                        noise_arr[row, col] = noise_gen.octave_noise2d(
                            col * 0.05, row * 0.05, octaves=3)
                hm += float(amount) * noise_arr * mask

            delta = hm - old_hm
            d_min = float(np.min(delta))
            d_max = float(np.max(delta))
            if d_min < delta_min:
                delta_min = d_min
            if d_max > delta_max:
                delta_max = d_max

            affected_tiles.append(key)

    return {
        'affected_tiles': affected_tiles,
        'elevation_delta': {'min': delta_min, 'max': delta_max},
    }


# ---------------------------------------------------------------------------
# Texture and Doodad Area Operations
# ---------------------------------------------------------------------------

def change_textures_in_area(zone_def, x, y, radius, new_textures,
                            target_subzone=None):
    """Change texture assignments within a circular area.

    Args:
        zone_def: Zone definition dict (modified in-place).
        x, y: Normalised center.
        radius: Normalised radius.
        new_textures: List of BLP texture paths (max 4).
        target_subzone: If specified, only modify this subzone.

    Returns:
        dict: {'modified_subzones': [str, ...]}
    """
    modified = []
    for sz in zone_def.get('subzones', []):
        if target_subzone is not None and sz.get('name') != target_subzone:
            continue
        cx, cy = sz.get('center', (0.5, 0.5))
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        r = sz.get('radius', 0.2)
        if dist <= r + radius:
            sz['textures'] = list(new_textures)[:4]
            modified.append(sz.get('name', 'unnamed'))

    return {'modified_subzones': modified}


def add_doodads_in_area(zone_def, x, y, radius, model_path, density,
                        filters=None):
    """Add doodad placements within a circular area.

    Adds the doodad to all subzones overlapping the area.

    Args:
        zone_def: Zone definition dict (modified in-place).
        x, y: Normalised center.
        radius: Normalised radius.
        model_path: M2 model path.
        density: Objects per square yard.
        filters: Optional doodad_filters dict.

    Returns:
        dict: {'subzones_modified': [str, ...]}
    """
    modified = []
    for sz in zone_def.get('subzones', []):
        cx, cy = sz.get('center', (0.5, 0.5))
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        r = sz.get('radius', 0.2)
        if dist <= r + radius:
            doodads = sz.get('doodads', {})
            doodads[model_path] = density
            sz['doodads'] = doodads
            if filters is not None:
                sz['doodad_filters'] = filters
            modified.append(sz.get('name', 'unnamed'))

    return {'subzones_modified': modified}


def remove_doodads_in_area(zone_def, x, y, radius, model_path=None):
    """Remove doodad entries from subzones covering the area.

    Args:
        zone_def: Zone definition dict (modified in-place).
        x, y: Normalised center.
        radius: Normalised radius.
        model_path: Specific model to remove, or None for all.

    Returns:
        dict: {'subzones_modified': [str, ...], 'doodads_removed': int}
    """
    modified = []
    removed_count = 0

    for sz in zone_def.get('subzones', []):
        cx, cy = sz.get('center', (0.5, 0.5))
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        r = sz.get('radius', 0.2)
        if dist <= r + radius:
            doodads = sz.get('doodads', {})
            if model_path is not None:
                if model_path in doodads:
                    del doodads[model_path]
                    removed_count += 1
                    modified.append(sz.get('name', 'unnamed'))
            else:
                removed_count += len(doodads)
                doodads.clear()
                modified.append(sz.get('name', 'unnamed'))

    return {'subzones_modified': modified, 'doodads_removed': removed_count}


# ---------------------------------------------------------------------------
# Archetype Detection
# ---------------------------------------------------------------------------

def _detect_archetype(zone_def):
    """Attempt to detect the archetype from palettes in zone_def."""
    tp = zone_def.get('texture_palette', {})
    dp = zone_def.get('doodad_palette', {})

    # Check texture palette keys
    if tp:
        best_match = None
        best_score = 0
        for arch_key, arch_palette in TEXTURE_PALETTES.items():
            if arch_palette == tp:
                return arch_key
            # Partial match: count shared texture paths
            arch_paths = set()
            for paths in arch_palette.values():
                arch_paths.update(paths)
            zone_paths = set()
            for paths in tp.values():
                if isinstance(paths, list):
                    zone_paths.update(paths)
            overlap = len(arch_paths & zone_paths)
            if overlap > best_score:
                best_score = overlap
                best_match = arch_key
        if best_match and best_score > 0:
            return best_match

    # Check doodad palette
    if dp:
        best_match = None
        best_score = 0
        for arch_key, arch_doodads in DOODAD_PALETTES.items():
            overlap = len(set(arch_doodads.keys()) & set(dp.keys()))
            if overlap > best_score:
                best_score = overlap
                best_match = arch_key
        if best_match and best_score > 0:
            return best_match

    return None


# ---------------------------------------------------------------------------
# Export for Round-Trip
# ---------------------------------------------------------------------------

def export_for_adt_composer(zone_def):
    """Export a zone_definition for direct consumption by adt_composer.

    For zones with _loaded_heightmaps, uses stored data directly.
    For planned zones, delegates to terrain_sculptor.sculpt_for_adt_composer().

    Returns:
        Dict {(tile_x, tile_y): tile_data_dict} where each contains:
        heightmap, texture_paths, splat_map, area_id
    """
    heightmaps = zone_def.get('_loaded_heightmaps')

    if heightmaps is None:
        # Delegate to terrain sculptor for procedurally-generated zones
        from .terrain_sculptor import sculpt_for_adt_composer as _sculpt
        return _sculpt(zone_def)

    # For loaded zones, assemble output from stored data
    grid_w, grid_h = zone_def.get('grid_size', (1, 1))
    base_x, base_y = zone_def.get('base_coords', (32, 32))

    loaded_tile_data = zone_def.get('_loaded_tile_data', {})
    result = {}

    for ty in range(grid_h):
        for tx in range(grid_w):
            tile_x = base_x + tx
            tile_y = base_y + ty
            key = (tile_x, tile_y)

            hm = heightmaps.get(key)
            if hm is None:
                continue

            # Convert numpy to list-of-lists for adt_composer
            if isinstance(hm, np.ndarray):
                hm_list = hm.tolist()
            else:
                hm_list = hm

            # Get texture paths and area_id from loaded data if available
            loaded = loaded_tile_data.get(key, {})
            tex_paths = loaded.get('texture_paths', ['Tileset\\Generic\\Black.blp'])
            area_id = loaded.get('area_id', 0)

            # Get splat map from loaded data
            # read_adt returns splat_map as {layer_idx: {(crow,ccol): 64x64}}
            # create_adt expects {layer_idx: [[64][64]]}
            # For loaded data, use a simple default splat
            splat_map = None
            raw_splat = loaded.get('splat_map', {})
            if raw_splat:
                splat_map = {}
                for layer_idx, chunks_data in raw_splat.items():
                    if isinstance(chunks_data, dict):
                        # Per-chunk alpha; use chunk (0,0) as representative
                        first_chunk = next(iter(chunks_data.values()), None)
                        if first_chunk is not None:
                            splat_map[layer_idx] = first_chunk
                    else:
                        splat_map[layer_idx] = chunks_data

            result[key] = {
                'heightmap': hm_list,
                'texture_paths': tex_paths[:4],
                'splat_map': splat_map,
                'area_id': area_id,
            }

    return result
