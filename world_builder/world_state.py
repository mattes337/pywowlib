"""
WorldState - In-memory mutable world with edge stitching and entity-aware terrain.

Provides a WorldState class that holds all heightmaps and entity instances in RAM,
supports edge stitching (internal averaging + boundary pinning to neighbor ADTs),
terrain flattening under footprinted entities, and lazy/on-demand loading of
adjacent tiles for cross-tile operations.

This module wraps the existing TerrainSculptor, ADT composer, and MPQ packer
without modifying them.

Usage:
    from world_builder.world_state import WorldState

    ws = WorldState.from_zone_def(zone_def, adt_source="path/to/extracted/Azeroth")
    ws.add_wmo("World\\wmo\\Building.wmo", position=(wx, wy), footprint=(20, 15))
    ws.flatten_for_entities(blend_margin=4.0)
    ws.pack_mpq(output_dir, "patch-4.MPQ")
"""

import logging
import math
import os
import shutil

log = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "numpy is required for world_state. Install it with: pip install numpy"
    )


# ---------------------------------------------------------------------------
# Constants (mirrored from adt_composer / terrain_sculptor)
# ---------------------------------------------------------------------------

TILE_SIZE = 533.33333333
CHUNK_SIZE = TILE_SIZE / 16.0
MAP_SIZE_MIN = -17066.66656
MAP_SIZE_MAX = 17066.66657

_HEIGHTMAP_RES = 129
_CHUNKS_PER_SIDE = 16

# Edge blend zone width in vertices (used for boundary smoothing)
_BLEND_VERTICES = 5


# ---------------------------------------------------------------------------
# Factory functions for entity instance dicts
# ---------------------------------------------------------------------------

def make_doodad(model, position, rotation=(0, 0, 0), scale=1.0,
                flags=0, unique_id=0, footprint=None):
    """Create a doodad instance dict.

    Args:
        model: M2 model path (backslash separators).
        position: (x, y, z) world coordinates.
        rotation: (rx, ry, rz) rotation in degrees.
        scale: Float scale (1.0 = normal).
        flags: MDDF flags.
        unique_id: Unique placement ID.
        footprint: Optional (width, depth) in yards for terrain flattening.

    Returns:
        dict with keys: model, position, rotation, scale, flags,
        unique_id, footprint.
    """
    return {
        'model': model,
        'position': tuple(position),
        'rotation': tuple(rotation),
        'scale': float(scale),
        'flags': int(flags),
        'unique_id': int(unique_id),
        'footprint': tuple(footprint) if footprint else None,
    }


def make_wmo(model, position, rotation=(0, 0, 0), scale=1.0,
             flags=0, unique_id=0, doodad_set=0, name_set=0,
             footprint=None):
    """Create a WMO instance dict.

    Args:
        model: WMO model path (backslash separators).
        position: (x, y, z) world coordinates.
        rotation: (rx, ry, rz) rotation in degrees.
        scale: Float scale (1.0 = normal).
        flags: MODF flags.
        unique_id: Unique placement ID.
        doodad_set: Doodad set index.
        name_set: Name set index.
        footprint: Optional (width, depth) in yards for terrain flattening.

    Returns:
        dict with keys: model, position, rotation, scale, flags,
        unique_id, doodad_set, name_set, footprint.
    """
    return {
        'model': model,
        'position': tuple(position),
        'rotation': tuple(rotation),
        'scale': float(scale),
        'flags': int(flags),
        'unique_id': int(unique_id),
        'doodad_set': int(doodad_set),
        'name_set': int(name_set),
        'footprint': tuple(footprint) if footprint else None,
    }


# ---------------------------------------------------------------------------
# WorldState class
# ---------------------------------------------------------------------------

class WorldState:
    """In-memory mutable world state with edge stitching and entity-aware terrain.

    Holds all heightmaps and entity instances in RAM. Supports:
    - Edge stitching between adjacent tiles
    - On-demand loading of neighbor tiles from disk
    - Terrain flattening under footprinted entities
    - Export to ADT binary and MPQ packing
    """

    def __init__(self):
        # Grid definition
        self.base_coords = (0, 0)
        self.grid_size = (0, 0)
        self.map_name = "Azeroth"
        self.zone_def = None

        # Per-tile terrain (mutable numpy arrays)
        self.heightmaps = {}      # {(tx,ty): np.ndarray(129,129)}
        self.textures = {}        # {(tx,ty): {'texture_paths': [...], 'splat_map': {...}}}
        self.area_ids = {}        # {(tx,ty,chunk_row,chunk_col): int}
        self.water = {}           # {(tx,ty): [water_region_dict, ...]}

        # Entity instances
        self.doodads = []
        self.wmos = []

        # On-demand loading
        self._adt_source = None
        self._dirty_tiles = set()
        self._loaded_tiles = set()

        # Unique ID counter
        self._uid_counter = 1

    # ------------------------------------------------------------------
    # Unique ID generator
    # ------------------------------------------------------------------

    def _next_unique_id(self):
        uid = self._uid_counter
        self._uid_counter += 1
        return uid

    # ------------------------------------------------------------------
    # Coordinate utilities
    # ------------------------------------------------------------------

    def norm_to_world(self, norm_x, norm_y):
        """Convert zone-normalised (0-1) coordinates to WoW world coordinates.

        Normalised coords are relative to the working grid:
        (0, 0) = top-left corner of base tile, (1, 1) = bottom-right
        corner of the last tile in the grid.

        Args:
            norm_x: Normalised X (0-1 across grid width).
            norm_y: Normalised Y (0-1 across grid height).

        Returns:
            (world_x, world_y) tuple.
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        tile_x_float = base_x + norm_x * grid_w
        tile_y_float = base_y + norm_y * grid_h

        world_x = MAP_SIZE_MAX - tile_y_float * TILE_SIZE
        world_y = MAP_SIZE_MAX - tile_x_float * TILE_SIZE
        return world_x, world_y

    def world_to_norm(self, world_x, world_y):
        """Convert WoW world coordinates to zone-normalised (0-1).

        Args:
            world_x: WoW world X coordinate.
            world_y: WoW world Y coordinate.

        Returns:
            (norm_x, norm_y) tuple.
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        tile_y_float = (MAP_SIZE_MAX - world_x) / TILE_SIZE
        tile_x_float = (MAP_SIZE_MAX - world_y) / TILE_SIZE

        norm_x = (tile_x_float - base_x) / grid_w if grid_w > 0 else 0.0
        norm_y = (tile_y_float - base_y) / grid_h if grid_h > 0 else 0.0
        return norm_x, norm_y

    def world_to_tile_pixel(self, world_x, world_y):
        """Convert world coordinates to (tile_key, row, col) in heightmap.

        Args:
            world_x: WoW world X coordinate.
            world_y: WoW world Y coordinate.

        Returns:
            ((tile_x, tile_y), row, col) or None if outside all tiles.
        """
        tile_y_float = (MAP_SIZE_MAX - world_x) / TILE_SIZE
        tile_x_float = (MAP_SIZE_MAX - world_y) / TILE_SIZE

        tile_x = int(math.floor(tile_x_float))
        tile_y = int(math.floor(tile_y_float))

        frac_x = tile_x_float - tile_x
        frac_y = tile_y_float - tile_y

        col = frac_x * (_HEIGHTMAP_RES - 1)
        row = frac_y * (_HEIGHTMAP_RES - 1)

        return (tile_x, tile_y), int(round(row)), int(round(col))

    def get_height_at(self, world_x, world_y):
        """Bilinear-interpolated height at world coordinates.

        Triggers lazy load if the tile is not yet loaded.

        Args:
            world_x: WoW world X coordinate.
            world_y: WoW world Y coordinate.

        Returns:
            float height, or 0.0 if tile unavailable.
        """
        tile_y_float = (MAP_SIZE_MAX - world_x) / TILE_SIZE
        tile_x_float = (MAP_SIZE_MAX - world_y) / TILE_SIZE

        tile_x = int(math.floor(tile_x_float))
        tile_y = int(math.floor(tile_y_float))

        if not self._ensure_tile(tile_x, tile_y):
            return 0.0

        hm = self.heightmaps.get((tile_x, tile_y))
        if hm is None:
            return 0.0

        frac_x = tile_x_float - tile_x
        frac_y = tile_y_float - tile_y

        col_f = frac_x * (_HEIGHTMAP_RES - 1)
        row_f = frac_y * (_HEIGHTMAP_RES - 1)

        r0 = int(math.floor(row_f))
        c0 = int(math.floor(col_f))
        r1 = min(r0 + 1, _HEIGHTMAP_RES - 1)
        c1 = min(c0 + 1, _HEIGHTMAP_RES - 1)
        r0 = max(0, min(r0, _HEIGHTMAP_RES - 1))
        c0 = max(0, min(c0, _HEIGHTMAP_RES - 1))

        dr = row_f - r0
        dc = col_f - c0

        h00 = float(hm[r0, c0])
        h01 = float(hm[r0, c1])
        h10 = float(hm[r1, c0])
        h11 = float(hm[r1, c1])

        return (h00 * (1 - dr) * (1 - dc) +
                h01 * (1 - dr) * dc +
                h10 * dr * (1 - dc) +
                h11 * dr * dc)

    # ------------------------------------------------------------------
    # On-demand / lazy tile loading
    # ------------------------------------------------------------------

    def set_adt_source(self, source):
        """Set the source for on-demand tile loading.

        Args:
            source: One of:
                - str: Directory path containing ADT files named
                  {MapName}_{x}_{y}.adt
                - callable(tile_x, tile_y) -> filepath_or_None
        """
        self._adt_source = source

    def _resolve_adt_path(self, tile_x, tile_y):
        """Find ADT file path from source.

        Returns:
            str filepath or None if not available.
        """
        if self._adt_source is None:
            return None

        if callable(self._adt_source):
            return self._adt_source(tile_x, tile_y)

        # Directory-based: look for {MapName}_{x}_{y}.adt
        dirpath = self._adt_source
        filename = "{}_{:d}_{:d}.adt".format(self.map_name, tile_x, tile_y)
        filepath = os.path.join(dirpath, filename)
        if os.path.isfile(filepath):
            return filepath
        return None

    def _ensure_tile(self, tile_x, tile_y):
        """Load a tile on demand if not already present.

        If the tile is in _loaded_tiles, returns immediately.
        Otherwise, attempts to load via _adt_source.
        Loaded tiles are NOT marked dirty (they're reference data
        until modified).

        Returns:
            bool: True if tile is available, False if not loadable.
        """
        key = (tile_x, tile_y)
        if key in self._loaded_tiles:
            return True

        filepath = self._resolve_adt_path(tile_x, tile_y)
        if filepath is None:
            return False

        try:
            from .adt_composer import read_adt
            adt_data = read_adt(filepath)

            # Extract heightmap as numpy array
            hm_list = adt_data.get('heightmap', [])
            if hm_list:
                self.heightmaps[key] = np.array(hm_list, dtype=np.float64)

            self._loaded_tiles.add(key)
            log.debug("Lazy-loaded tile (%d, %d) from %s", tile_x, tile_y, filepath)
            return True
        except Exception as e:
            log.warning("Failed to load tile (%d, %d): %s", tile_x, tile_y, e)
            return False

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_zone_def(cls, zone_def, adt_source=None):
        """Create WorldState from a zone definition via TerrainSculptor.

        Replaces the old sculpt_for_adt_composer() pipeline.

        Args:
            zone_def: Zone definition dict from plan_zone().
            adt_source: Optional ADT source for on-demand neighbor loading.
                        str (directory path) or callable(tx, ty) -> filepath.

        Returns:
            WorldState instance with generated terrain and entities.
        """
        from .terrain_sculptor import TerrainSculptor

        ws = cls()
        ws.zone_def = zone_def
        ws.base_coords = tuple(zone_def.get('base_coords', (32, 32)))
        ws.grid_size = tuple(zone_def.get('grid_size', (1, 1)))
        ws.map_name = zone_def.get('name', 'Azeroth')

        if adt_source is not None:
            ws.set_adt_source(adt_source)

        sculptor = TerrainSculptor(zone_def)

        # Generate heightmaps as numpy arrays
        raw_heightmaps = sculptor.generate_heightmaps()
        for key, hm in raw_heightmaps.items():
            if isinstance(hm, np.ndarray):
                ws.heightmaps[key] = hm.copy()
            else:
                ws.heightmaps[key] = np.array(hm, dtype=np.float64)
            ws._loaded_tiles.add(key)
            ws._dirty_tiles.add(key)

        # Generate textures
        tex_result = sculptor.generate_textures(raw_heightmaps)
        for key in ws.heightmaps:
            tile_tex = tex_result['tile_data'].get(key, {})
            tile_tex_paths = tile_tex.get('texture_paths', [])
            chunk_layers = tile_tex.get('chunk_layers', {})

            # Build per-tile texture_paths (max 4) by frequency
            tex_freq = {}
            for cl in chunk_layers.values():
                for tid in cl.get('texture_ids', []):
                    if tid is not None and tid < len(tile_tex_paths):
                        path = tile_tex_paths[tid]
                        tex_freq[path] = tex_freq.get(path, 0) + 1

            sorted_tex = sorted(tex_freq.items(), key=lambda x: -x[1])
            final_tex_paths = [t[0] for t in sorted_tex[:4]]
            if not final_tex_paths:
                final_tex_paths = ["Tileset\\Generic\\Black.blp"]

            # Build splat_map
            splat_map = {}
            for layer_idx in range(1, len(final_tex_paths)):
                splat_map[layer_idx] = [[128] * 64 for _ in range(64)]

            ws.textures[key] = {
                'texture_paths': final_tex_paths,
                'splat_map': splat_map if splat_map else None,
            }

        # Generate doodads - convert to instance dicts
        raw_doodads = sculptor.generate_doodads(raw_heightmaps)
        for d in raw_doodads:
            ws.doodads.append(make_doodad(
                model=d.get('model', d.get('model_path', '')),
                position=d.get('position', (0, 0, 0)),
                rotation=d.get('rotation', (0, 0, 0)),
                scale=d.get('scale', 1.0),
                flags=d.get('flags', 0),
                unique_id=ws._next_unique_id(),
            ))

        # Generate WMOs
        raw_wmos = sculptor.generate_wmos(raw_heightmaps)
        for w in raw_wmos:
            ws.wmos.append(make_wmo(
                model=w.get('model', w.get('model_path', '')),
                position=w.get('position', (0, 0, 0)),
                rotation=w.get('rotation', (0, 0, 0)),
                scale=w.get('scale', 1.0),
                flags=w.get('flags', 0),
                unique_id=ws._next_unique_id(),
                doodad_set=w.get('doodad_set', 0),
                name_set=w.get('name_set', 0),
            ))

        # Generate water
        raw_water = sculptor.generate_water()
        ws.water = dict(raw_water)

        # Generate area IDs
        ws.area_ids = sculptor.generate_area_ids()

        # Run edge stitching
        ws.stitch_edges()

        return ws

    @classmethod
    def from_sculpted(cls, tile_data, base_coords, grid_size, map_name="Azeroth"):
        """Create WorldState from already-sculpted tile_data dict.

        For backward compatibility with sculpt_for_adt_composer() output.

        Args:
            tile_data: Dict {(tile_x, tile_y): tile_data_dict} from
                       sculpt_for_adt_composer() or TerrainSculptor.export_for_adt_composer().
            base_coords: (tile_x, tile_y) of top-left tile.
            grid_size: (width, height) in tiles.
            map_name: Map name string.

        Returns:
            WorldState instance.
        """
        ws = cls()
        ws.base_coords = tuple(base_coords)
        ws.grid_size = tuple(grid_size)
        ws.map_name = map_name

        for key, td in tile_data.items():
            # Heightmap
            hm = td.get('heightmap')
            if hm is not None:
                if isinstance(hm, np.ndarray):
                    ws.heightmaps[key] = hm.copy()
                else:
                    ws.heightmaps[key] = np.array(hm, dtype=np.float64)
            ws._loaded_tiles.add(key)
            ws._dirty_tiles.add(key)

            # Textures
            ws.textures[key] = {
                'texture_paths': td.get('texture_paths', []),
                'splat_map': td.get('splat_map'),
            }

            # Water
            tile_water = td.get('water', [])
            if tile_water:
                ws.water[key] = tile_water

            # Area IDs
            area_id_map = td.get('area_id_map', {})
            for (cr, cc), aid in area_id_map.items():
                ws.area_ids[(key[0], key[1], cr, cc)] = aid
            if not area_id_map:
                default_aid = td.get('area_id', 0)
                for cr in range(_CHUNKS_PER_SIDE):
                    for cc in range(_CHUNKS_PER_SIDE):
                        ws.area_ids[(key[0], key[1], cr, cc)] = default_aid

            # Doodads
            for d in td.get('doodads', []):
                ws.doodads.append(make_doodad(
                    model=d.get('model', d.get('model_path', '')),
                    position=d.get('position', (0, 0, 0)),
                    rotation=d.get('rotation', (0, 0, 0)),
                    scale=d.get('scale', 1.0),
                    flags=d.get('flags', 0),
                    unique_id=ws._next_unique_id(),
                ))

            # WMOs
            for w in td.get('wmos', []):
                ws.wmos.append(make_wmo(
                    model=w.get('model', w.get('model_path', '')),
                    position=w.get('position', (0, 0, 0)),
                    rotation=w.get('rotation', (0, 0, 0)),
                    scale=w.get('scale', 1.0),
                    flags=w.get('flags', 0),
                    unique_id=ws._next_unique_id(),
                    doodad_set=w.get('doodad_set', 0),
                    name_set=w.get('name_set', 0),
                ))

        # Stitch edges
        ws.stitch_edges()

        return ws

    # ------------------------------------------------------------------
    # Edge stitching
    # ------------------------------------------------------------------

    def stitch_edges(self):
        """Run full edge stitching: internal averaging, boundary pinning, blend.

        This is the main stitching entry point. Call after any heightmap
        modification that affects tile edges.
        """
        self.stitch_internal_edges()
        self.stitch_boundary_edges()

    def stitch_internal_edges(self):
        """Average shared vertices between adjacent tiles within the grid.

        For horizontally-adjacent tiles: average left[:,128] with right[:,0].
        For vertically-adjacent tiles: average top[128,:] with bottom[0,:].
        Corner vertices shared by 4 tiles are averaged across all 4.
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        # Horizontal edges (left-right pairs)
        for ty in range(grid_h):
            for tx in range(grid_w - 1):
                left_key = (base_x + tx, base_y + ty)
                right_key = (base_x + tx + 1, base_y + ty)
                left_hm = self.heightmaps.get(left_key)
                right_hm = self.heightmaps.get(right_key)
                if left_hm is not None and right_hm is not None:
                    avg = (left_hm[:, 128] + right_hm[:, 0]) * 0.5
                    left_hm[:, 128] = avg
                    right_hm[:, 0] = avg

        # Vertical edges (top-bottom pairs)
        for ty in range(grid_h - 1):
            for tx in range(grid_w):
                top_key = (base_x + tx, base_y + ty)
                bot_key = (base_x + tx, base_y + ty + 1)
                top_hm = self.heightmaps.get(top_key)
                bot_hm = self.heightmaps.get(bot_key)
                if top_hm is not None and bot_hm is not None:
                    avg = (top_hm[128, :] + bot_hm[0, :]) * 0.5
                    top_hm[128, :] = avg
                    bot_hm[0, :] = avg

        # 4-tile corner vertices
        for ty in range(grid_h - 1):
            for tx in range(grid_w - 1):
                tl = self.heightmaps.get((base_x + tx, base_y + ty))
                tr = self.heightmaps.get((base_x + tx + 1, base_y + ty))
                bl = self.heightmaps.get((base_x + tx, base_y + ty + 1))
                br = self.heightmaps.get((base_x + tx + 1, base_y + ty + 1))
                corners = [h for h in [tl, tr, bl, br] if h is not None]
                if len(corners) >= 2:
                    vals = []
                    if tl is not None:
                        vals.append(float(tl[128, 128]))
                    if tr is not None:
                        vals.append(float(tr[128, 0]))
                    if bl is not None:
                        vals.append(float(bl[0, 128]))
                    if br is not None:
                        vals.append(float(br[0, 0]))
                    avg_val = sum(vals) / len(vals)
                    if tl is not None:
                        tl[128, 128] = avg_val
                    if tr is not None:
                        tr[128, 0] = avg_val
                    if bl is not None:
                        bl[0, 128] = avg_val
                    if br is not None:
                        br[0, 0] = avg_val

    def stitch_boundary_edges(self):
        """Pin boundary tile edges to lazy-loaded neighbor ADTs.

        For each tile on the grid boundary, attempts to load the neighbor
        tile. If available, pins our edge to the neighbor's shared edge
        (neighbor is authoritative) and applies a blend zone.
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        for ty in range(grid_h):
            for tx in range(grid_w):
                tile_key = (base_x + tx, base_y + ty)
                hm = self.heightmaps.get(tile_key)
                if hm is None:
                    continue

                # North boundary (ty == 0): pin row 0 to neighbor-above row 128
                if ty == 0:
                    neighbor = (base_x + tx, base_y - 1)
                    if self._ensure_tile(*neighbor):
                        nhm = self.heightmaps.get(neighbor)
                        if nhm is not None:
                            hm[0, :] = nhm[128, :]
                            self._blend_edge(hm, 'north')

                # South boundary (ty == grid_h - 1): pin row 128 to neighbor-below row 0
                if ty == grid_h - 1:
                    neighbor = (base_x + tx, base_y + grid_h)
                    if self._ensure_tile(*neighbor):
                        nhm = self.heightmaps.get(neighbor)
                        if nhm is not None:
                            hm[128, :] = nhm[0, :]
                            self._blend_edge(hm, 'south')

                # West boundary (tx == 0): pin col 0 to neighbor-left col 128
                if tx == 0:
                    neighbor = (base_x - 1, base_y + ty)
                    if self._ensure_tile(*neighbor):
                        nhm = self.heightmaps.get(neighbor)
                        if nhm is not None:
                            hm[:, 0] = nhm[:, 128]
                            self._blend_edge(hm, 'west')

                # East boundary (tx == grid_w - 1): pin col 128 to neighbor-right col 0
                if tx == grid_w - 1:
                    neighbor = (base_x + grid_w, base_y + ty)
                    if self._ensure_tile(*neighbor):
                        nhm = self.heightmaps.get(neighbor)
                        if nhm is not None:
                            hm[:, 128] = nhm[:, 0]
                            self._blend_edge(hm, 'east')

    def pin_edges_to_arrays(self, edge_arrays, blend_vertices=32):
        """Pin boundary edges to actual neighbor height arrays.

        Each edge array should be a 129-element array of absolute heights
        from the neighboring tile's shared edge.

        Args:
            edge_arrays: Dict with optional keys 'north', 'south', 'east',
                         'west'. Values are numpy arrays of shape (129,).
            blend_vertices: Number of vertex rows/cols to blend over.
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        for ty in range(grid_h):
            for tx in range(grid_w):
                tile_key = (base_x + tx, base_y + ty)
                hm = self.heightmaps.get(tile_key)
                if hm is None:
                    continue

                if ty == 0 and 'north' in edge_arrays:
                    hm[0, :] = edge_arrays['north']
                    self._blend_edge_n(hm, 'north', blend_vertices)
                if ty == grid_h - 1 and 'south' in edge_arrays:
                    hm[128, :] = edge_arrays['south']
                    self._blend_edge_n(hm, 'south', blend_vertices)
                if tx == 0 and 'west' in edge_arrays:
                    hm[:, 0] = edge_arrays['west']
                    self._blend_edge_n(hm, 'west', blend_vertices)
                if tx == grid_w - 1 and 'east' in edge_arrays:
                    hm[:, 128] = edge_arrays['east']
                    self._blend_edge_n(hm, 'east', blend_vertices)

    def pin_edges_to_elevation(self, target_elevation, blend_vertices=32):
        """Pin all boundary edges to a fixed elevation and blend inward.

        Use this when neighbor ADTs are not available. Forces all four
        edges of every boundary tile to the target elevation, then
        applies a smooth blend inward so the interior terrain transitions
        gradually.

        Args:
            target_elevation: Height value to pin edges to (world Z).
            blend_vertices: Number of vertex rows/cols to blend over
                            (default 32, ~quarter of the 129-vertex tile).
        """
        base_x, base_y = self.base_coords
        grid_w, grid_h = self.grid_size

        for ty in range(grid_h):
            for tx in range(grid_w):
                tile_key = (base_x + tx, base_y + ty)
                hm = self.heightmaps.get(tile_key)
                if hm is None:
                    continue

                if ty == 0:
                    hm[0, :] = target_elevation
                    self._blend_edge_n(hm, 'north', blend_vertices)
                if ty == grid_h - 1:
                    hm[128, :] = target_elevation
                    self._blend_edge_n(hm, 'south', blend_vertices)
                if tx == 0:
                    hm[:, 0] = target_elevation
                    self._blend_edge_n(hm, 'west', blend_vertices)
                if tx == grid_w - 1:
                    hm[:, 128] = target_elevation
                    self._blend_edge_n(hm, 'east', blend_vertices)

    def _blend_edge(self, hm, direction):
        """Apply linear blend from pinned edge inward (default width)."""
        self._blend_edge_n(hm, direction, _BLEND_VERTICES)

    def _blend_edge_n(self, hm, direction, n):
        """Apply smoothstep blend from pinned edge inward over n vertices.

        Args:
            hm: numpy heightmap array (129x129), modified in-place.
            direction: 'north', 'south', 'east', or 'west'.
            n: Number of vertex rows/cols to blend over.
        """
        if direction == 'north':
            pinned = hm[0, :].copy()
            for i in range(1, n):
                t = i / float(n)
                t = t * t * (3.0 - 2.0 * t)  # smoothstep
                hm[i, :] = pinned * (1.0 - t) + hm[i, :] * t
        elif direction == 'south':
            pinned = hm[128, :].copy()
            for i in range(1, n):
                t = i / float(n)
                t = t * t * (3.0 - 2.0 * t)
                hm[128 - i, :] = pinned * (1.0 - t) + hm[128 - i, :] * t
        elif direction == 'west':
            pinned = hm[:, 0].copy()
            for i in range(1, n):
                t = i / float(n)
                t = t * t * (3.0 - 2.0 * t)
                hm[:, i] = pinned * (1.0 - t) + hm[:, i] * t
        elif direction == 'east':
            pinned = hm[:, 128].copy()
            for i in range(1, n):
                t = i / float(n)
                t = t * t * (3.0 - 2.0 * t)
                hm[:, 128 - i] = pinned * (1.0 - t) + hm[:, 128 - i] * t

    # ------------------------------------------------------------------
    # Terrain flattening for entities
    # ------------------------------------------------------------------

    def flatten_for_entity(self, entity, blend_margin=4.0):
        """Flatten terrain under a single entity's footprint.

        Args:
            entity: Entity dict with 'position', 'rotation', and 'footprint'.
            blend_margin: Yards outside the footprint for smooth blend.
        """
        fp = entity.get('footprint')
        if fp is None:
            return

        width, depth = fp
        pos = entity['position']
        wx, wy, wz = pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0
        yaw_deg = entity.get('rotation', (0, 0, 0))[2]
        yaw = math.radians(yaw_deg)

        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)

        half_w = width / 2.0
        half_d = depth / 2.0
        outer_half_w = half_w + blend_margin
        outer_half_d = half_d + blend_margin

        # Determine which tiles are affected
        # Sample corner positions of the outer bounding box (rotated)
        corners_local = [
            (-outer_half_d, -outer_half_w),
            (-outer_half_d, outer_half_w),
            (outer_half_d, -outer_half_w),
            (outer_half_d, outer_half_w),
        ]
        world_corners = []
        for lx, ly in corners_local:
            cx = wx + lx * cos_yaw - ly * sin_yaw
            cy = wy + lx * sin_yaw + ly * cos_yaw
            world_corners.append((cx, cy))

        # Find tile range
        tile_keys = set()
        for cx, cy in world_corners:
            ty_f = (MAP_SIZE_MAX - cx) / TILE_SIZE
            tx_f = (MAP_SIZE_MAX - cy) / TILE_SIZE
            tile_keys.add((int(math.floor(tx_f)), int(math.floor(ty_f))))

        # Collect all vertices inside the footprint to compute median height
        inside_heights = []
        for tk in tile_keys:
            self._ensure_tile(*tk)
            hm = self.heightmaps.get(tk)
            if hm is None:
                continue

            for r in range(_HEIGHTMAP_RES):
                for c in range(_HEIGHTMAP_RES):
                    vwx, vwy = self._pixel_to_world(tk, r, c)
                    dx = vwx - wx
                    dy = vwy - wy
                    local_x = dx * cos_yaw + dy * sin_yaw
                    local_y = -dx * sin_yaw + dy * cos_yaw
                    if abs(local_x) <= half_d and abs(local_y) <= half_w:
                        inside_heights.append(float(hm[r, c]))

        if not inside_heights:
            return

        target_height = float(np.median(inside_heights))

        # Apply flattening + blend
        for tk in tile_keys:
            hm = self.heightmaps.get(tk)
            if hm is None:
                continue

            modified = False
            for r in range(_HEIGHTMAP_RES):
                for c in range(_HEIGHTMAP_RES):
                    vwx, vwy = self._pixel_to_world(tk, r, c)
                    dx = vwx - wx
                    dy = vwy - wy
                    local_x = dx * cos_yaw + dy * sin_yaw
                    local_y = -dx * sin_yaw + dy * cos_yaw

                    abs_lx = abs(local_x)
                    abs_ly = abs(local_y)

                    if abs_lx <= half_d and abs_ly <= half_w:
                        # Inside footprint: flatten
                        hm[r, c] = target_height
                        modified = True
                    elif abs_lx <= outer_half_d and abs_ly <= outer_half_w:
                        # Blend zone: smoothstep from target to original
                        edge_dist = max(abs_lx - half_d, abs_ly - half_w, 0.0)
                        t = min(edge_dist / blend_margin, 1.0) if blend_margin > 0 else 1.0
                        # Smoothstep
                        t = t * t * (3.0 - 2.0 * t)
                        hm[r, c] = target_height * (1.0 - t) + float(hm[r, c]) * t
                        modified = True

            if modified:
                self._dirty_tiles.add(tk)

        # Update entity Z to the flattened height
        entity['position'] = (wx, wy, target_height)

    def flatten_for_entities(self, blend_margin=4.0):
        """Flatten terrain under all footprinted entities.

        Processes WMOs first (larger footprints), then doodads.
        Re-stitches edges after all flattening.

        Args:
            blend_margin: Yards outside footprints for smooth blend.
        """
        # WMOs first
        for wmo in self.wmos:
            if wmo.get('footprint'):
                self.flatten_for_entity(wmo, blend_margin)

        # Doodads second
        for doodad in self.doodads:
            if doodad.get('footprint'):
                self.flatten_for_entity(doodad, blend_margin)

        # Re-stitch after flattening
        self.stitch_edges()

    def _pixel_to_world(self, tile_key, row, col):
        """Convert heightmap pixel (row, col) to world (x, y) coordinates.

        Args:
            tile_key: (tile_x, tile_y) tuple.
            row: Heightmap row (0-128).
            col: Heightmap column (0-128).

        Returns:
            (world_x, world_y) tuple.
        """
        tile_x, tile_y = tile_key
        frac_x = col / (_HEIGHTMAP_RES - 1.0)
        frac_y = row / (_HEIGHTMAP_RES - 1.0)

        world_x = MAP_SIZE_MAX - (tile_y + frac_y) * TILE_SIZE
        world_y = MAP_SIZE_MAX - (tile_x + frac_x) * TILE_SIZE
        return world_x, world_y

    # ------------------------------------------------------------------
    # Entity management
    # ------------------------------------------------------------------

    def add_doodad(self, model, position, rotation=(0, 0, 0), scale=1.0,
                   footprint=None, **kwargs):
        """Add a doodad to the world.

        If position is a 2-tuple (wx, wy), Z is auto-sampled from the
        heightmap. A 3-tuple provides explicit (wx, wy, wz).

        Args:
            model: M2 model path.
            position: (x, y) or (x, y, z) world coordinates.
            rotation: (rx, ry, rz) in degrees.
            scale: Float scale (1.0 = normal).
            footprint: Optional (width, depth) in yards.
            **kwargs: Extra fields (flags, etc.).

        Returns:
            dict: The created doodad instance.
        """
        pos = self._resolve_position(position)
        uid = kwargs.pop('unique_id', self._next_unique_id())

        doodad = make_doodad(
            model=model,
            position=pos,
            rotation=rotation,
            scale=scale,
            flags=kwargs.pop('flags', 0),
            unique_id=uid,
            footprint=footprint,
        )
        self.doodads.append(doodad)

        # Mark tile dirty
        tile_key, _, _ = self.world_to_tile_pixel(pos[0], pos[1])
        self._dirty_tiles.add(tile_key)

        return doodad

    def add_wmo(self, model, position, rotation=(0, 0, 0), scale=1.0,
                footprint=None, doodad_set=0, **kwargs):
        """Add a WMO to the world.

        If position is a 2-tuple (wx, wy), Z is auto-sampled from the
        heightmap. A 3-tuple provides explicit (wx, wy, wz).

        Args:
            model: WMO model path.
            position: (x, y) or (x, y, z) world coordinates.
            rotation: (rx, ry, rz) in degrees.
            scale: Float scale (1.0 = normal).
            footprint: Optional (width, depth) in yards.
            doodad_set: Doodad set index.
            **kwargs: Extra fields (flags, name_set, etc.).

        Returns:
            dict: The created WMO instance.
        """
        pos = self._resolve_position(position)
        uid = kwargs.pop('unique_id', self._next_unique_id())

        wmo = make_wmo(
            model=model,
            position=pos,
            rotation=rotation,
            scale=scale,
            flags=kwargs.pop('flags', 0),
            unique_id=uid,
            doodad_set=doodad_set,
            name_set=kwargs.pop('name_set', 0),
            footprint=footprint,
        )
        self.wmos.append(wmo)

        tile_key, _, _ = self.world_to_tile_pixel(pos[0], pos[1])
        self._dirty_tiles.add(tile_key)

        return wmo

    def remove_doodad(self, unique_id=None, model=None, index=None):
        """Remove a doodad by unique_id, model path, or list index.

        Args:
            unique_id: Remove first doodad with this unique_id.
            model: Remove first doodad with this model path.
            index: Remove doodad at this list index.

        Returns:
            dict or None: The removed doodad, or None if not found.
        """
        return self._remove_entity(self.doodads, unique_id, model, index)

    def remove_wmo(self, unique_id=None, model=None, index=None):
        """Remove a WMO by unique_id, model path, or list index.

        Args:
            unique_id: Remove first WMO with this unique_id.
            model: Remove first WMO with this model path.
            index: Remove WMO at this list index.

        Returns:
            dict or None: The removed WMO, or None if not found.
        """
        return self._remove_entity(self.wmos, unique_id, model, index)

    def _remove_entity(self, entity_list, unique_id, model, index):
        """Remove an entity from a list by various criteria."""
        if index is not None:
            if 0 <= index < len(entity_list):
                return entity_list.pop(index)
            return None

        for i, e in enumerate(entity_list):
            if unique_id is not None and e.get('unique_id') == unique_id:
                return entity_list.pop(i)
            if model is not None and e.get('model') == model:
                return entity_list.pop(i)
        return None

    def _resolve_position(self, position):
        """Resolve a 2-tuple position to 3-tuple by sampling heightmap Z.

        Args:
            position: (x, y) or (x, y, z).

        Returns:
            (x, y, z) tuple.
        """
        if len(position) == 2:
            wx, wy = position
            wz = self.get_height_at(wx, wy)
            return (wx, wy, wz)
        return tuple(position)

    # ------------------------------------------------------------------
    # Export pipeline
    # ------------------------------------------------------------------

    def export(self, dirty_only=True, big_alpha=True):
        """Export tiles to ADT binary bytes.

        Args:
            dirty_only: If True, only export tiles in _dirty_tiles.
                        If False, export all loaded tiles.
            big_alpha: If True, write 4096-byte highres alphas.
                       If False, write 2048-byte lowres alphas
                       (for Azeroth and other maps without MPHD 0x4).

        Returns:
            dict: {(tile_x, tile_y): adt_bytes}
        """
        from .adt_composer import (create_adt, add_doodad_to_adt, add_wmo_to_adt,
                                   update_mcrf)

        tiles_to_export = self._dirty_tiles if dirty_only else set(self.heightmaps.keys())
        result = {}

        for key in tiles_to_export:
            hm = self.heightmaps.get(key)
            if hm is None:
                continue

            tile_x, tile_y = key

            # Get texture data
            tex = self.textures.get(key, {})
            texture_paths = tex.get('texture_paths', ["Tileset\\Generic\\Black.blp"])
            splat_map = tex.get('splat_map')

            # Generate height-based alpha maps if splat_map is trivial
            if len(texture_paths) > 1:
                splat_map = self._generate_height_splat(hm, len(texture_paths))

            # Get area ID (most common for this tile)
            tile_area_id = self._get_tile_area_id(tile_x, tile_y)

            # Create base ADT
            hm_list = hm.tolist()
            adt_bytes = create_adt(
                tile_x=tile_x,
                tile_y=tile_y,
                heightmap=hm_list,
                texture_paths=texture_paths,
                splat_map=splat_map,
                area_id=tile_area_id,
                big_alpha=big_alpha,
            )

            # Add doodads for this tile
            tile_doodads = self._entities_in_tile(self.doodads, tile_x, tile_y)
            for d in tile_doodads:
                raw_scale = d.get('scale', 1.0)
                if isinstance(raw_scale, float) and raw_scale < 100:
                    scale_int = int(raw_scale * 1024)
                else:
                    scale_int = int(raw_scale)
                try:
                    adt_bytes = add_doodad_to_adt(
                        adt_bytes,
                        m2_path=d['model'],
                        position=d['position'],
                        rotation=d.get('rotation', (0, 0, 0)),
                        scale=scale_int,
                        unique_id=d.get('unique_id', 0),
                        flags=d.get('flags', 0),
                    )
                except Exception as e:
                    log.warning("Failed to add doodad %s: %s", d.get('model'), e)

            # Add WMOs for this tile
            tile_wmos = self._entities_in_tile(self.wmos, tile_x, tile_y)
            for w in tile_wmos:
                raw_scale = w.get('scale', 1.0)
                if isinstance(raw_scale, float) and raw_scale < 100:
                    scale_int = int(raw_scale * 1024)
                else:
                    scale_int = int(raw_scale)
                # Compute bounding extents from footprint if available
                extents = None
                fp = w.get('footprint')
                pos = w['position']
                if fp and len(fp) >= 2:
                    hw = fp[0] / 2.0  # half width
                    hd = fp[1] / 2.0  # half depth
                    half_ext = max(hw, hd)
                    extents = (
                        (pos[0] - half_ext, pos[1] - half_ext, pos[2]),
                        (pos[0] + half_ext, pos[1] + half_ext, pos[2] + 40.0),
                    )
                try:
                    adt_bytes = add_wmo_to_adt(
                        adt_bytes,
                        wmo_path=w['model'],
                        position=w['position'],
                        rotation=w.get('rotation', (0, 0, 0)),
                        extents=extents,
                        unique_id=w.get('unique_id', 0),
                        flags=w.get('flags', 0),
                        doodad_set=w.get('doodad_set', 0),
                        name_set=w.get('name_set', 0),
                        scale=scale_int,
                    )
                except Exception as e:
                    log.warning("Failed to add WMO %s: %s", w.get('model'), e)

            # Update per-chunk MCRF references so objects render correctly
            if tile_doodads or tile_wmos:
                adt_bytes = update_mcrf(adt_bytes, tile_x, tile_y)

            result[key] = adt_bytes

        return result

    def pack_mpq(self, output_dir, patch_name="patch-4.MPQ",
                 wow_data_dir=None, big_alpha=True):
        """Export dirty tiles, pack into MPQ, optionally copy to WoW Data.

        Args:
            output_dir: Directory for output files.
            patch_name: MPQ filename.
            wow_data_dir: If provided, copy MPQ to this directory.
            big_alpha: If True, write 4096-byte highres alpha maps.
                       If False, write 2048-byte lowres alpha maps
                       (for Azeroth and other maps without MPHD 0x4).

        Returns:
            str: Path to the generated MPQ file.
        """
        from .mpq_packer import MPQPacker

        os.makedirs(output_dir, exist_ok=True)

        exported = self.export(dirty_only=True, big_alpha=big_alpha)
        packer = MPQPacker(output_dir, patch_name=patch_name)

        for (tile_x, tile_y), adt_bytes in exported.items():
            packer.add_adt(self.map_name, tile_x, tile_y, adt_bytes)

        mpq_path = packer.build_mpq()
        log.info("Packed %d tiles into %s", len(exported), mpq_path)

        if wow_data_dir:
            dest = os.path.join(wow_data_dir, patch_name)
            if os.path.isfile(mpq_path):
                shutil.copy2(mpq_path, dest)
                log.info("Copied MPQ to %s", dest)
            else:
                # Fallback: try directory-based output
                alt = os.path.join(output_dir, patch_name)
                if os.path.isfile(alt):
                    shutil.copy2(alt, dest)

        return mpq_path

    def _entities_in_tile(self, entity_list, tile_x, tile_y):
        """Filter entities to those within a tile's world bounds.

        Args:
            entity_list: List of entity dicts with 'position' key.
            tile_x: Tile X coordinate.
            tile_y: Tile Y coordinate.

        Returns:
            List of entity dicts within the tile.
        """
        tile_wx_max = MAP_SIZE_MAX - tile_y * TILE_SIZE
        tile_wx_min = tile_wx_max - TILE_SIZE
        tile_wy_max = MAP_SIZE_MAX - tile_x * TILE_SIZE
        tile_wy_min = tile_wy_max - TILE_SIZE

        result = []
        for e in entity_list:
            pos = e.get('position', (0, 0, 0))
            wx, wy = pos[0], pos[1]
            if tile_wx_min <= wx <= tile_wx_max and tile_wy_min <= wy <= tile_wy_max:
                result.append(e)
        return result

    def _generate_height_splat(self, heightmap, num_textures):
        """Generate height-based per-chunk alpha maps for texture blending.

        Creates spatially-varying alpha maps so different textures appear at
        different elevations within the tile.  Uses per-chunk keys
        ``(layer_idx, chunk_row, chunk_col)`` so each of the 256 sub-chunks
        gets its own 64x64 alpha based on local terrain height.

        Args:
            heightmap: numpy array (129, 129) of absolute heights.
            num_textures: Number of texture layers (1-4).

        Returns:
            dict or None: ``{(layer_idx, crow, ccol): list[64][64]}``
            with alpha values 0-255, or *None* if only one texture.
        """
        if num_textures <= 1:
            return None

        h_min = float(heightmap.min())
        h_max = float(heightmap.max())
        h_range = h_max - h_min
        if h_range < 0.01:
            h_range = 1.0

        # Pre-compute bilinear sampling coordinates for a 64x64 grid
        # mapped onto a 9x9 chunk heightmap sub-grid (indices 0..8).
        alpha_coords = np.linspace(0, 8.0, 64)  # 64 sample points in [0,8]

        splat = {}

        for crow in range(16):
            for ccol in range(16):
                # Extract chunk's 9x9 height sub-grid
                r0 = crow * 8
                c0 = ccol * 8
                chunk_h = heightmap[r0:r0 + 9, c0:c0 + 9]

                # Bilinear resample 9x9 -> 64x64 using numpy vectorisation
                row_idx = np.clip(alpha_coords, 0, 8).astype(np.float64)
                col_idx = np.clip(alpha_coords, 0, 8).astype(np.float64)
                ri = np.floor(row_idx).astype(int)
                ci = np.floor(col_idx).astype(int)
                rf = row_idx - ri
                cf = col_idx - ci
                ri = np.clip(ri, 0, 7)
                ci = np.clip(ci, 0, 7)

                # Build 64x64 grid of heights via outer-product style indexing
                h00 = chunk_h[ri][:, ci]           # (64,64)
                h01 = chunk_h[ri][:, ci + 1]
                h10 = chunk_h[ri + 1][:, ci]
                h11 = chunk_h[ri + 1][:, ci + 1]

                rf2 = rf[:, np.newaxis]            # (64,1) for broadcasting
                cf2 = cf[np.newaxis, :]            # (1,64)

                resampled = (h00 * (1 - rf2) * (1 - cf2) +
                             h01 * (1 - rf2) * cf2 +
                             h10 * rf2 * (1 - cf2) +
                             h11 * rf2 * cf2)

                # Normalise to [0, 1] using tile-wide range
                t = (resampled - h_min) / h_range

                if num_textures == 2:
                    # Layer 1 = higher elevations
                    a1 = np.clip(t * 255, 0, 255).astype(int)
                    splat[(1, crow, ccol)] = a1.tolist()
                elif num_textures == 3:
                    # Layer 1 = mid-range elevations
                    a1 = np.clip((1.0 - np.abs(2.0 * t - 1.0)) * 255, 0, 255).astype(int)
                    # Layer 2 = high elevations
                    a2 = np.clip(np.maximum(0, 2.0 * t - 1.0) * 255, 0, 255).astype(int)
                    splat[(1, crow, ccol)] = a1.tolist()
                    splat[(2, crow, ccol)] = a2.tolist()
                elif num_textures >= 4:
                    # Layer 1 = low-mid
                    a1 = np.clip(np.maximum(0, 1.0 - np.abs(3.0 * t - 1.0)) * 255, 0, 255).astype(int)
                    # Layer 2 = mid-high
                    a2 = np.clip(np.maximum(0, 1.0 - np.abs(3.0 * t - 2.0)) * 255, 0, 255).astype(int)
                    # Layer 3 = high
                    a3 = np.clip(np.maximum(0, 3.0 * t - 2.0) * 255, 0, 255).astype(int)
                    splat[(1, crow, ccol)] = a1.tolist()
                    splat[(2, crow, ccol)] = a2.tolist()
                    splat[(3, crow, ccol)] = a3.tolist()

        return splat

    def _get_tile_area_id(self, tile_x, tile_y):
        """Get the most common area ID for a tile.

        Returns:
            int: Most frequent area_id, or 0 if none set.
        """
        counts = {}
        for cr in range(_CHUNKS_PER_SIDE):
            for cc in range(_CHUNKS_PER_SIDE):
                aid = self.area_ids.get((tile_x, tile_y, cr, cc), 0)
                counts[aid] = counts.get(aid, 0) + 1
        return max(counts, key=counts.get) if counts else 0

    # ------------------------------------------------------------------
    # ML terrain generation (CNN target + vertex relaxation)
    # ------------------------------------------------------------------

    def _get_terrain_generator(self):
        """Lazy-create a TerrainGenerator instance.

        Caches on self._terrain_gen. Falls back gracefully if torch is
        unavailable or no model file exists.
        """
        if hasattr(self, '_terrain_gen'):
            return self._terrain_gen

        from .terrain_model import TerrainGenerator
        # Default model path: terrain_model.pth next to this module
        model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'terrain_model.pth')
        self._terrain_gen = TerrainGenerator(model_path)
        return self._terrain_gen

    def _resolve_edge_arrays(self, tile_x, tile_y, edge_arrays=None):
        """Resolve boundary edges for a tile from neighbors or explicit input.

        Priority: explicit edge_arrays > loaded neighbor tile > flat fallback.

        Args:
            tile_x, tile_y: tile coordinates.
            edge_arrays: optional dict with 'north', 'south', 'west', 'east'.

        Returns:
            dict with all four edge keys, each np.ndarray(129).
        """
        from .terrain_model import resolve_missing_edges

        edges = dict(edge_arrays or {})

        # Try to fill missing edges from loaded/lazy-loaded neighbors
        neighbor_map = {
            'north': ((tile_x, tile_y - 1), lambda hm: hm[_HEIGHTMAP_RES - 1, :]),
            'south': ((tile_x, tile_y + 1), lambda hm: hm[0, :]),
            'west':  ((tile_x - 1, tile_y), lambda hm: hm[:, _HEIGHTMAP_RES - 1]),
            'east':  ((tile_x + 1, tile_y), lambda hm: hm[:, 0]),
        }

        for edge_name, (nkey, selector) in neighbor_map.items():
            if edge_name in edges:
                continue
            # Check already-loaded heightmaps first
            nhm = self.heightmaps.get(nkey)
            if nhm is not None:
                edges[edge_name] = selector(nhm).copy()
                continue
            # Try lazy load
            if self._ensure_tile(*nkey):
                nhm = self.heightmaps.get(nkey)
                if nhm is not None:
                    edges[edge_name] = selector(nhm).copy()

        return resolve_missing_edges(edges)

    def generate_tile_ml(self, tile_x, tile_y, edge_arrays=None,
                         extra_pins=None):
        """Generate a single tile using CNN target + vertex relaxation.

        1. Resolve edges from neighbors, game data, or explicit arrays.
        2. Compute Coons base from edges.
        3. Run CNN to get target heightmap (or Coons base as fallback).
        4. Create TerrainRelaxer with pinned edges.
        5. Run relaxation -> final heightmap.
        6. Store in self.heightmaps.

        Args:
            tile_x, tile_y: tile coordinates.
            edge_arrays: optional dict with 'north','south','west','east'
                         arrays(129) of absolute heights.
            extra_pins: optional list of (row, col, height) for user pins.

        Returns:
            np.ndarray(129, 129) - the generated heightmap.
        """
        gen = self._get_terrain_generator()
        edges = self._resolve_edge_arrays(tile_x, tile_y, edge_arrays)

        hm = gen.generate(
            north=edges['north'],
            south=edges['south'],
            west=edges['west'],
            east=edges['east'],
            pinned_edges=edges,
            extra_pins=extra_pins,
        )

        self.heightmaps[(tile_x, tile_y)] = hm
        self._loaded_tiles.add((tile_x, tile_y))
        self._dirty_tiles.add((tile_x, tile_y))

        log.debug("Generated ML tile (%d, %d) range=[%.1f, %.1f]",
                  tile_x, tile_y, float(hm.min()), float(hm.max()))
        return hm

    def modify_vertex(self, tile_x, tile_y, row, col, new_height,
                      propagation_threshold=0.5, max_depth=3):
        """Modify a single vertex with constrained propagation to neighbors.

        1. Pin the vertex in this tile's heightmap.
        2. Re-run relaxation for this tile.
        3. If edge vertices changed significantly, update neighbor tiles'
           corresponding edge pins and re-relax them.
        4. Repeat recursively up to max_depth.

        Args:
            tile_x, tile_y: tile coordinates.
            row, col: vertex position in heightmap (0-128).
            new_height: target height value.
            propagation_threshold: min edge change to trigger neighbor update.
            max_depth: max recursive propagation depth.

        Returns:
            set of (tile_x, tile_y) keys that were modified.
        """
        key = (tile_x, tile_y)
        hm = self.heightmaps.get(key)
        if hm is None:
            return set()

        # Save old edges for comparison
        old_north = hm[0, :].copy()
        old_south = hm[_HEIGHTMAP_RES - 1, :].copy()
        old_west = hm[:, 0].copy()
        old_east = hm[:, _HEIGHTMAP_RES - 1].copy()

        # Build edge pins from current tile edges
        edges = {
            'north': old_north, 'south': old_south,
            'west': old_west, 'east': old_east,
        }

        # Re-relax with the new pin
        from .terrain_model import TerrainRelaxer, coons_patch
        gen = self._get_terrain_generator()

        base = coons_patch(edges['north'], edges['south'],
                           edges['west'], edges['east'])
        target = gen._predict_target(base, edges['north'], edges['south'],
                                     edges['west'], edges['east'])

        relaxer = TerrainRelaxer(
            coons_base=base, target=target, pinned_edges=edges,
            max_delta=gen.max_delta, alpha=gen.alpha,
            beta=gen.beta, damping=gen.damping,
        )
        relaxer.pin_vertex(row, col, new_height)
        self.heightmaps[key] = relaxer.relax(iterations=gen.iterations)
        self._dirty_tiles.add(key)

        modified = {key}

        if max_depth <= 0:
            return modified

        # Check if edge vertices changed and propagate
        new_hm = self.heightmaps[key]
        edge_changes = {
            'south': (new_hm[_HEIGHTMAP_RES - 1, :], old_south,
                      (tile_x, tile_y + 1), 'north'),
            'north': (new_hm[0, :], old_north,
                      (tile_x, tile_y - 1), 'south'),
            'east':  (new_hm[:, _HEIGHTMAP_RES - 1], old_east,
                      (tile_x + 1, tile_y), 'west'),
            'west':  (new_hm[:, 0], old_west,
                      (tile_x - 1, tile_y), 'east'),
        }

        for _, (new_edge, old_edge, nkey, nedge_name) in edge_changes.items():
            max_diff = float(np.max(np.abs(new_edge - old_edge)))
            if max_diff < propagation_threshold:
                continue

            # Update neighbor if it exists
            nhm = self.heightmaps.get(nkey)
            if nhm is None:
                continue

            # Pin the neighbor's shared edge to our new edge values
            # and re-generate
            neighbor_edges = self._resolve_edge_arrays(nkey[0], nkey[1])
            neighbor_edges[nedge_name] = new_edge.copy()

            gen_n = self._get_terrain_generator()
            base_n = coons_patch(
                neighbor_edges['north'], neighbor_edges['south'],
                neighbor_edges['west'], neighbor_edges['east'])
            target_n = gen_n._predict_target(
                base_n, neighbor_edges['north'], neighbor_edges['south'],
                neighbor_edges['west'], neighbor_edges['east'])

            relaxer_n = TerrainRelaxer(
                coons_base=base_n, target=target_n,
                pinned_edges=neighbor_edges,
                max_delta=gen_n.max_delta, alpha=gen_n.alpha,
                beta=gen_n.beta, damping=gen_n.damping,
            )
            self.heightmaps[nkey] = relaxer_n.relax(
                iterations=gen_n.iterations)
            self._dirty_tiles.add(nkey)
            modified.add(nkey)

        return modified

    def generate_grid_ml(self, base_coords=None, grid_size=None,
                         external_edges=None):
        """Generate a grid of tiles with self-consistent internal edges.

        Steps:
        1. Generate each tile independently with external edge pins.
        2. For internal edges between generated tiles, average predictions.
        3. Re-relax all tiles with averaged internal edges.
        4. Repeat averaging + re-relax for convergence (2 passes).

        Args:
            base_coords: (tile_x, tile_y) of top-left tile.
                         Uses self.base_coords if None.
            grid_size: (width, height) in tiles. Uses self.grid_size if None.
            external_edges: optional dict with keys like
                'north', 'south', 'east', 'west' containing arrays(129)
                for the grid's outer boundary.

        Returns:
            dict {(tile_x, tile_y): np.ndarray(129, 129)}
        """
        if base_coords is None:
            base_coords = self.base_coords
        if grid_size is None:
            grid_size = self.grid_size

        bx, by = base_coords
        gw, gh = grid_size
        ext = external_edges or {}

        # Step 1: Generate each tile independently
        for dy in range(gh):
            for dx in range(gw):
                tx, ty = bx + dx, by + dy
                tile_edges = {}

                # External edges for boundary tiles
                if dy == 0 and 'north' in ext:
                    tile_edges['north'] = ext['north']
                if dy == gh - 1 and 'south' in ext:
                    tile_edges['south'] = ext['south']
                if dx == 0 and 'west' in ext:
                    tile_edges['west'] = ext['west']
                if dx == gw - 1 and 'east' in ext:
                    tile_edges['east'] = ext['east']

                self.generate_tile_ml(tx, ty, edge_arrays=tile_edges)

        # Step 2-3: Iterative internal edge averaging (2 passes)
        for _pass in range(2):
            # Average horizontal internal edges
            for dy in range(gh):
                for dx in range(gw - 1):
                    left_key = (bx + dx, by + dy)
                    right_key = (bx + dx + 1, by + dy)
                    left_hm = self.heightmaps.get(left_key)
                    right_hm = self.heightmaps.get(right_key)
                    if left_hm is not None and right_hm is not None:
                        avg = (left_hm[:, _HEIGHTMAP_RES - 1]
                               + right_hm[:, 0]) * 0.5
                        left_hm[:, _HEIGHTMAP_RES - 1] = avg
                        right_hm[:, 0] = avg

            # Average vertical internal edges
            for dy in range(gh - 1):
                for dx in range(gw):
                    top_key = (bx + dx, by + dy)
                    bot_key = (bx + dx, by + dy + 1)
                    top_hm = self.heightmaps.get(top_key)
                    bot_hm = self.heightmaps.get(bot_key)
                    if top_hm is not None and bot_hm is not None:
                        avg = (top_hm[_HEIGHTMAP_RES - 1, :]
                               + bot_hm[0, :]) * 0.5
                        top_hm[_HEIGHTMAP_RES - 1, :] = avg
                        bot_hm[0, :] = avg

            # Re-relax each tile with pinned (now-averaged) edges
            for dy in range(gh):
                for dx in range(gw):
                    tx, ty = bx + dx, by + dy
                    hm = self.heightmaps.get((tx, ty))
                    if hm is None:
                        continue

                    edges = {
                        'north': hm[0, :].copy(),
                        'south': hm[_HEIGHTMAP_RES - 1, :].copy(),
                        'west': hm[:, 0].copy(),
                        'east': hm[:, _HEIGHTMAP_RES - 1].copy(),
                    }
                    self.generate_tile_ml(tx, ty, edge_arrays=edges)

        return {(bx + dx, by + dy): self.heightmaps[(bx + dx, by + dy)]
                for dy in range(gh) for dx in range(gw)
                if (bx + dx, by + dy) in self.heightmaps}
