"""
Intermediate JSON format for WoW WotLK 3.3.5a zone and dungeon export/import.

Provides schema constants, JSON I/O helpers, validation, slug generation,
and an IDAllocator class for discovering next-free DBC IDs.  The intermediate
format is a directory of JSON files that fully describe a zone or dungeon in
a tool-agnostic way, suitable for round-tripping between World Builder
pipelines and external editors.

Manifest layout (manifest.json):
    format_version  - semver string ("1.0.0")
    type            - "zone" or "dungeon"
    name            - display name (e.g. "The Deadmines")
    slug            - filesystem-safe identifier (e.g. "the-deadmines")
    tiles           - list of {x, y, file} tile references
    files           - dict with at least "map" and "areas" keys

Target build: WotLK 3.3.5a (build 12340)
"""

import os
import json
import re
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

FORMAT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def slugify(name):
    """
    Convert a display name to a filesystem-safe slug.

    Lowercases the string, replaces non-alphanumeric characters with hyphens,
    collapses consecutive hyphens into one, and strips leading/trailing hyphens.

    Examples:
        slugify("The Deadmines")   -> "the-deadmines"
        slugify("Elwynn Forest")   -> "elwynn-forest"
        slugify("--Foo  Bar!--")   -> "foo-bar"
    """
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------

def load_json(filepath):
    """
    Load and parse a JSON file.

    Args:
        filepath: Path to the JSON file.

    Returns:
        dict: Parsed JSON data.
    """
    with open(filepath, 'r') as f:
        return json.load(f)


def save_json(filepath, data, indent=2):
    """
    Write a dict to a JSON file, creating parent directories as needed.

    Args:
        filepath: Destination file path.
        data: Dict (or list) to serialize.
        indent: JSON indentation level (default 2).
    """
    parent = os.path.dirname(filepath)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=indent)


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------

def validate_manifest(data):
    """
    Validate a manifest.json dict against the intermediate format schema.

    Returns a list of error strings.  An empty list means the manifest is valid.

    Required fields:
        format_version, type, name, slug, tiles, files

    Constraints:
        - type must be "zone" or "dungeon"
        - tiles must be a list of dicts with x, y, file keys
        - files must be a dict with at least "map" and "areas" keys
    """
    errors = []

    required = ["format_version", "type", "name", "slug", "tiles", "files"]
    for field in required:
        if field not in data:
            errors.append("Missing required field: {}".format(field))

    # Stop early if fundamental fields are missing
    if errors:
        return errors

    # Type validation
    if data["type"] not in ("zone", "dungeon"):
        errors.append("type must be 'zone' or 'dungeon', got '{}'".format(data["type"]))

    # Tiles validation
    if not isinstance(data["tiles"], list):
        errors.append("tiles must be a list")
    else:
        for i, tile in enumerate(data["tiles"]):
            if not isinstance(tile, dict):
                errors.append("tiles[{}] must be a dict".format(i))
            else:
                for key in ("x", "y", "file"):
                    if key not in tile:
                        errors.append("tiles[{}] missing key '{}'".format(i, key))

    # Files validation
    if not isinstance(data["files"], dict):
        errors.append("files must be a dict")
    else:
        for key in ("map", "areas"):
            if key not in data["files"]:
                errors.append("files missing required key '{}'".format(key))

    return errors


# ---------------------------------------------------------------------------
# Zone template generation
# ---------------------------------------------------------------------------

def create_zone_template(name, output_dir, tile_coords=None):
    """
    Generate minimal valid JSON template files for a new zone.

    Creates the following files inside *output_dir*:
        manifest.json   - zone manifest
        map.json        - map metadata placeholder
        areas.json      - area definitions placeholder
        tiles/<x>_<y>.json - one tile file per coordinate, flat terrain

    Each tile contains 256 chunks (16x16), each with 145 zero height values
    and a single default texture "Tileset\\Generic\\Black.blp".

    Args:
        name: Display name for the zone (e.g. "Tel'Abim").
        output_dir: Directory to write template files into.
        tile_coords: List of (x, y) tuples.  Default: [(32, 32)].

    Returns:
        str: Path to the generated manifest.json.
    """
    if tile_coords is None:
        tile_coords = [(32, 32)]

    slug = slugify(name)

    # Build tile list and tile data files
    tiles = []
    for x, y in tile_coords:
        tile_filename = "tiles/{}_{}.json".format(x, y)
        tiles.append({"x": x, "y": y, "file": tile_filename})

        # Each chunk: 145 heights (9x9 outer + 8x8 inner = 145), one texture
        chunk = {
            "heights": [0.0] * 145,
            "textures": ["Tileset\\Generic\\Black.blp"],
        }
        # 16x16 = 256 chunks per tile
        tile_data = {
            "tile_x": x,
            "tile_y": y,
            "chunks": [chunk] * 256,
        }

        tile_path = os.path.join(output_dir, tile_filename)
        save_json(tile_path, tile_data)

    # Map metadata
    map_data = {
        "name": name,
        "slug": slug,
        "instance_type": 0,
    }
    map_path = os.path.join(output_dir, "map.json")
    save_json(map_path, map_data)

    # Area definitions
    areas_data = {
        "zones": [
            {
                "name": name,
                "slug": slug,
                "parent_area_id": 0,
            }
        ],
    }
    areas_path = os.path.join(output_dir, "areas.json")
    save_json(areas_path, areas_data)

    # Manifest
    manifest = {
        "format_version": FORMAT_VERSION,
        "type": "zone",
        "name": name,
        "slug": slug,
        "tiles": tiles,
        "files": {
            "map": "map.json",
            "areas": "areas.json",
        },
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    save_json(manifest_path, manifest)

    log.info("Created zone template '%s' at %s", name, output_dir)
    return manifest_path


# ---------------------------------------------------------------------------
# Dungeon template generation
# ---------------------------------------------------------------------------

def create_dungeon_template(name, output_dir, room_count=1):
    """
    Generate minimal valid JSON template files for a new dungeon.

    Creates the following files inside *output_dir*:
        manifest.json      - dungeon manifest
        map.json           - map metadata placeholder
        areas.json         - area definitions placeholder
        dungeon.json       - dungeon-specific metadata
        wmo/root.json      - WMO root definition
        wmo/group_NNN.json - one per room, basic box geometry

    Each room group has 8 vertices (box corners), 12 triangles (6 faces x 2),
    and a single default material.

    Args:
        name: Display name for the dungeon (e.g. "Vault of Storms").
        output_dir: Directory to write template files into.
        room_count: Number of rooms/groups to generate (default 1).

    Returns:
        str: Path to the generated manifest.json.
    """
    slug = slugify(name)

    # Default box geometry: 30x30x10 yard room centered at origin
    hw = 15.0  # half-width
    hl = 15.0  # half-length
    hh = 10.0  # height

    box_vertices = [
        [-hw, -hl, 0.0],
        [ hw, -hl, 0.0],
        [ hw,  hl, 0.0],
        [-hw,  hl, 0.0],
        [-hw, -hl,  hh],
        [ hw, -hl,  hh],
        [ hw,  hl,  hh],
        [-hw,  hl,  hh],
    ]

    # 12 triangles (2 per face, 6 faces), vertex indices
    box_triangles = [
        # Floor (facing up)
        [0, 2, 1], [0, 3, 2],
        # Ceiling (facing down)
        [4, 5, 6], [4, 6, 7],
        # Front wall (facing inward, -Y)
        [0, 1, 5], [0, 5, 4],
        # Back wall (facing inward, +Y)
        [2, 3, 7], [2, 7, 6],
        # Left wall (facing inward, -X)
        [3, 0, 4], [3, 4, 7],
        # Right wall (facing inward, +X)
        [1, 2, 6], [1, 6, 5],
    ]

    # Build WMO group files
    groups = []
    for i in range(room_count):
        group_filename = "wmo/group_{:03d}.json".format(i)
        groups.append(group_filename)

        group_data = {
            "group_index": i,
            "name": "Room {:d}".format(i),
            "vertices": box_vertices,
            "triangles": box_triangles,
            "material": "Tileset\\Generic\\Black.blp",
        }

        group_path = os.path.join(output_dir, group_filename)
        save_json(group_path, group_data)

    # WMO root
    root_data = {
        "name": name,
        "slug": slug,
        "group_count": room_count,
        "groups": groups,
        "materials": [
            {
                "texture": "Tileset\\Generic\\Black.blp",
                "flags": 0,
            }
        ],
    }
    root_path = os.path.join(output_dir, "wmo/root.json")
    save_json(root_path, root_data)

    # Map metadata
    map_data = {
        "name": name,
        "slug": slug,
        "instance_type": 1,
    }
    map_path = os.path.join(output_dir, "map.json")
    save_json(map_path, map_data)

    # Area definitions
    areas_data = {
        "zones": [
            {
                "name": name,
                "slug": slug,
                "parent_area_id": 0,
            }
        ],
    }
    areas_path = os.path.join(output_dir, "areas.json")
    save_json(areas_path, areas_data)

    # Dungeon metadata
    dungeon_data = {
        "name": name,
        "slug": slug,
        "room_count": room_count,
        "wmo_root": "wmo/root.json",
    }
    dungeon_path = os.path.join(output_dir, "dungeon.json")
    save_json(dungeon_path, dungeon_data)

    # Manifest -- tile list is empty for dungeons, but include a single
    # tile entry referencing the dungeon interior coordinate (32, 32)
    manifest = {
        "format_version": FORMAT_VERSION,
        "type": "dungeon",
        "name": name,
        "slug": slug,
        "tiles": [{"x": 32, "y": 32, "file": "dungeon.json"}],
        "files": {
            "map": "map.json",
            "areas": "areas.json",
            "dungeon": "dungeon.json",
            "wmo_root": "wmo/root.json",
        },
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    save_json(manifest_path, manifest)

    log.info("Created dungeon template '%s' (%d rooms) at %s", name, room_count, output_dir)
    return manifest_path


# ---------------------------------------------------------------------------
# IDAllocator - DBC-aware ID assignment
# ---------------------------------------------------------------------------

class IDAllocator(object):
    """
    Scans existing DBC files and allocates next-free IDs.

    Reads Map.dbc, AreaTable.dbc, WorldMapArea.dbc, WorldMapOverlay.dbc,
    LoadingScreens.dbc, DungeonEncounter.dbc, AreaTrigger.dbc, and
    LFGDungeons.dbc on init.  Each next_* method returns max_id + 1 and
    then increments its internal counter so successive calls return unique
    IDs without re-reading the DBC.
    """

    def __init__(self, dbc_dir):
        """
        Args:
            dbc_dir: Path to DBFilesClient directory containing DBC files.
        """
        from .dbc_injector import DBCInjector

        self._dbc_dir = dbc_dir

        # Read each DBC and extract the current max ID (field 0).
        # If a DBC file does not exist, start from 0 so next_* returns 1.
        self._counters = {}

        dbc_files = {
            "map": "Map.dbc",
            "area": "AreaTable.dbc",
            "worldmaparea": "WorldMapArea.dbc",
            "worldmapoverlay": "WorldMapOverlay.dbc",
            "loading_screen": "LoadingScreens.dbc",
            "encounter": "DungeonEncounter.dbc",
            "areatrigger": "AreaTrigger.dbc",
            "lfgdungeon": "LFGDungeons.dbc",
        }

        for key, filename in dbc_files.items():
            filepath = os.path.join(dbc_dir, filename)
            if os.path.exists(filepath):
                try:
                    dbc = DBCInjector(filepath)
                    self._counters[key] = dbc.get_max_id()
                except Exception as e:
                    log.warning("Failed to read %s: %s (starting from 0)", filename, e)
                    self._counters[key] = 0
            else:
                log.debug("DBC not found: %s (starting from 0)", filepath)
                self._counters[key] = 0

        # AreaBit is stored at field index 3 of AreaTable.dbc
        area_path = os.path.join(dbc_dir, "AreaTable.dbc")
        if os.path.exists(area_path):
            try:
                dbc = DBCInjector(area_path)
                self._area_bit_counter = dbc.find_max_field(3)
            except Exception as e:
                log.warning("Failed to read AreaTable.dbc for area_bit: %s", e)
                self._area_bit_counter = 0
        else:
            self._area_bit_counter = 0

    def _next(self, key):
        """Increment and return the next ID for the given counter key."""
        self._counters[key] += 1
        return self._counters[key]

    def next_map_id(self):
        """Return the next available Map.dbc ID."""
        return self._next("map")

    def next_area_id(self):
        """Return the next available AreaTable.dbc ID."""
        return self._next("area")

    def next_area_bit(self):
        """Return the next available AreaBit value (AreaTable field 3)."""
        self._area_bit_counter += 1
        return self._area_bit_counter

    def next_worldmaparea_id(self):
        """Return the next available WorldMapArea.dbc ID."""
        return self._next("worldmaparea")

    def next_worldmapoverlay_id(self):
        """Return the next available WorldMapOverlay.dbc ID."""
        return self._next("worldmapoverlay")

    def next_loading_screen_id(self):
        """Return the next available LoadingScreens.dbc ID."""
        return self._next("loading_screen")

    def next_encounter_id(self):
        """Return the next available DungeonEncounter.dbc ID."""
        return self._next("encounter")

    def next_areatrigger_id(self):
        """Return the next available AreaTrigger.dbc ID."""
        return self._next("areatrigger")

    def next_lfgdungeon_id(self):
        """Return the next available LFGDungeons.dbc ID."""
        return self._next("lfgdungeon")


# ---------------------------------------------------------------------------
# Tile image format: compact PNG + meta.json tile representation
# ---------------------------------------------------------------------------

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


class TileImageWriter(object):
    """
    Writes tile data as PNG images + meta.json.

    Converts the heavy per-chunk arrays (heightmap, shadows, alpha maps,
    normals, vertex colors) into compact PNG files, reducing tile size
    from ~20 MB JSON to ~200 KB.
    """

    def __init__(self, tile_dir):
        """
        Args:
            tile_dir: Directory to write PNG files and meta.json into.
        """
        if not _HAS_PIL:
            raise ImportError("Pillow (PIL) is required for image tile format")
        self.tile_dir = tile_dir
        if not os.path.exists(tile_dir):
            os.makedirs(tile_dir)

    def write_heightmap(self, chunks):
        """
        Write a 129x129 16-bit grayscale PNG from per-chunk 145-float heights.

        Extracts outer 9x9 vertices from each chunk's interleaved 145-float
        layout and combines them into a tile-level 129x129 grid.

        Args:
            chunks: List of 256 chunk dicts, each with 'heightmap' (145 floats).

        Returns:
            tuple: (filename, height_min, height_scale) or (None, 0, 0) if
                   no height data.
        """
        if not chunks:
            return None, 0.0, 0.0

        # Extract outer 9x9 from each chunk into 129x129 grid
        grid = [[0.0] * 129 for _ in range(129)]
        has_data = False

        for chunk_idx, chunk in enumerate(chunks):
            heights_145 = chunk.get('heightmap', [])
            if not heights_145:
                continue
            has_data = True
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            idx = 0
            for interleaved_row in range(17):
                if interleaved_row % 2 == 0:
                    outer_row_idx = interleaved_row // 2
                    global_row = chunk_row * 8 + outer_row_idx
                    for col_idx in range(9):
                        if idx < len(heights_145):
                            global_col = chunk_col * 8 + col_idx
                            if global_row < 129 and global_col < 129:
                                grid[global_row][global_col] = heights_145[idx]
                        idx += 1
                else:
                    idx += 8

        if not has_data:
            return None, 0.0, 0.0

        # Find range for normalisation
        flat = [v for row in grid for v in row]
        height_min = min(flat)
        height_max = max(flat)
        height_scale = height_max - height_min
        if height_scale < 1e-6:
            height_scale = 1.0

        # Build 16-bit image
        img = Image.new('I;16', (129, 129))
        pixels = img.load()
        for r in range(129):
            for c in range(129):
                normalised = (grid[r][c] - height_min) / height_scale
                pixels[c, r] = int(normalised * 65535 + 0.5)

        filename = "heightmap.png"
        img.save(os.path.join(self.tile_dir, filename))
        return filename, height_min, height_scale

    def write_shadow_map(self, chunks):
        """
        Write a 1024x1024 8-bit grayscale PNG from per-chunk 64x64 shadow bitmaps.

        Args:
            chunks: List of 256 chunk dicts, each optionally with 'shadow_map'
                    (64x64 2D list of 0/1 values).

        Returns:
            str or None: Filename if written, None if no shadow data.
        """
        has_data = any(c.get('shadow_map') for c in chunks)
        if not has_data:
            return None

        img = Image.new('L', (1024, 1024), 0)
        pixels = img.load()

        for chunk_idx, chunk in enumerate(chunks):
            shadow = chunk.get('shadow_map')
            if not shadow:
                continue
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16
            base_y = chunk_row * 64
            base_x = chunk_col * 64

            for sr in range(min(64, len(shadow))):
                row_data = shadow[sr]
                for sc in range(min(64, len(row_data))):
                    if row_data[sc]:
                        pixels[base_x + sc, base_y + sr] = 255

        filename = "shadow.png"
        img.save(os.path.join(self.tile_dir, filename))
        return filename

    def write_alpha_maps(self, chunks):
        """
        Write one 1024x1024 8-bit grayscale PNG per texture layer alpha map.

        Each chunk has 64x64 alpha per texture layer (layers 1+). These are
        tiled into a 1024x1024 image per layer index.

        Args:
            chunks: List of 256 chunk dicts, each optionally with
                    'texture_layers' containing per-layer alpha_map data.

        Returns:
            list: List of (layer_index, filename) tuples for layers written.
        """
        # Discover which layer indices have alpha data
        layer_indices = set()
        for chunk in chunks:
            for layer in chunk.get('texture_layers', []):
                if layer.get('alpha_map'):
                    layer_indices.add(layer.get('texture_index', 0))

        # Actually, layer index in the texture_layers list is what matters,
        # not texture_index. Let's track by list position.
        layer_indices = set()
        for chunk in chunks:
            layers = chunk.get('texture_layers', [])
            for li in range(1, len(layers)):
                if layers[li].get('alpha_map'):
                    layer_indices.add(li)

        if not layer_indices:
            return []

        result = []
        for li in sorted(layer_indices):
            img = Image.new('L', (1024, 1024), 0)
            pixels = img.load()

            for chunk_idx, chunk in enumerate(chunks):
                layers = chunk.get('texture_layers', [])
                if li >= len(layers):
                    continue
                alpha = layers[li].get('alpha_map')
                if not alpha:
                    continue

                chunk_row = chunk_idx // 16
                chunk_col = chunk_idx % 16
                base_y = chunk_row * 64
                base_x = chunk_col * 64

                for ar in range(min(64, len(alpha))):
                    row_data = alpha[ar]
                    for ac in range(min(64, len(row_data))):
                        pixels[base_x + ac, base_y + ar] = row_data[ac]

            filename = "alpha_{}.png".format(li)
            img.save(os.path.join(self.tile_dir, filename))
            result.append((li, filename))

        return result

    def write_normals(self, chunks):
        """
        Write a 129x129 RGB PNG from per-chunk normals.

        Outer 9x9 normals per chunk are combined into a 129x129 tile grid.
        R=X+128, G=Y+128, B=Z (maps signed int8 to unsigned byte).
        Informational only; normals are recomputed from heightmap on import.

        Args:
            chunks: List of 256 chunk dicts, each with 'normals' (145 triplets).

        Returns:
            str or None: Filename if written, None if no normal data.
        """
        has_data = any(c.get('normals') for c in chunks)
        if not has_data:
            return None

        img = Image.new('RGB', (129, 129), (128, 128, 127))
        pixels = img.load()

        for chunk_idx, chunk in enumerate(chunks):
            normals = chunk.get('normals', [])
            if not normals:
                continue
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            idx = 0
            for interleaved_row in range(17):
                if interleaved_row % 2 == 0:
                    outer_row_idx = interleaved_row // 2
                    global_row = chunk_row * 8 + outer_row_idx
                    for col_idx in range(9):
                        if idx < len(normals):
                            global_col = chunk_col * 8 + col_idx
                            if global_row < 129 and global_col < 129:
                                n = normals[idx]
                                r = max(0, min(255, n[0] + 128))
                                g = max(0, min(255, n[1] + 128))
                                b = max(0, min(255, n[2]))
                                pixels[global_col, global_row] = (r, g, b)
                        idx += 1
                else:
                    idx += 8

        filename = "normals.png"
        img.save(os.path.join(self.tile_dir, filename))
        return filename

    def write_vertex_colors(self, chunks):
        """
        Write a 129x129 RGBA PNG from per-chunk vertex colors.

        Outer 9x9 vertex colors per chunk are combined into a 129x129 grid.
        Direct RGBA mapping.

        Args:
            chunks: List of 256 chunk dicts, each optionally with
                    'vertex_colors' (145 RGBA tuples).

        Returns:
            str or None: Filename if written, None if no vertex color data.
        """
        has_data = any(c.get('vertex_colors') for c in chunks)
        if not has_data:
            return None

        img = Image.new('RGBA', (129, 129), (127, 127, 127, 255))
        pixels = img.load()

        for chunk_idx, chunk in enumerate(chunks):
            colors = chunk.get('vertex_colors', [])
            if not colors:
                continue
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            idx = 0
            for interleaved_row in range(17):
                if interleaved_row % 2 == 0:
                    outer_row_idx = interleaved_row // 2
                    global_row = chunk_row * 8 + outer_row_idx
                    for col_idx in range(9):
                        if idx < len(colors):
                            global_col = chunk_col * 8 + col_idx
                            if global_row < 129 and global_col < 129:
                                c = colors[idx]
                                r = max(0, min(255, c[0]))
                                g = max(0, min(255, c[1]))
                                b = max(0, min(255, c[2]))
                                a = max(0, min(255, c[3] if len(c) > 3 else 255))
                                pixels[global_col, global_row] = (r, g, b, a)
                        idx += 1
                else:
                    idx += 8

        filename = "vertex_colors.png"
        img.save(os.path.join(self.tile_dir, filename))
        return filename


class TileImageReader(object):
    """
    Reads tile data back from PNG images + meta.json.

    Reconstructs the arrays expected by the importer's _build_adt_tile()
    from the compact PNG tile format.
    """

    def __init__(self, tile_dir):
        """
        Args:
            tile_dir: Directory containing meta.json and PNG files.
        """
        if not _HAS_PIL:
            raise ImportError("Pillow (PIL) is required for image tile format")
        self.tile_dir = tile_dir

    def read_heightmap(self, meta):
        """
        Read a 129x129 heightmap from a 16-bit grayscale PNG.

        Reverses the normalisation using height_min and height_scale from
        meta.json: height = pixel_value / 65535.0 * height_scale + height_min

        Args:
            meta: Parsed meta.json dict with 'height_min', 'height_scale',
                  and 'images.heightmap'.

        Returns:
            list: 129x129 2D list of float heights, or None if no heightmap.
        """
        images = meta.get('images', {})
        filename = images.get('heightmap')
        if not filename:
            return None

        filepath = os.path.join(self.tile_dir, filename)
        if not os.path.isfile(filepath):
            log.warning("Heightmap PNG not found: %s", filepath)
            return None

        height_min = meta.get('height_min', 0.0)
        height_scale = meta.get('height_scale', 1.0)

        img = Image.open(filepath)
        heightmap = [[0.0] * 129 for _ in range(129)]

        for r in range(129):
            for c in range(129):
                pixel = img.getpixel((c, r))
                if isinstance(pixel, tuple):
                    pixel = pixel[0]
                heightmap[r][c] = (pixel / 65535.0) * height_scale + height_min

        return heightmap

    def read_shadow_map(self, meta):
        """
        Read per-chunk 64x64 shadow maps from a 1024x1024 grayscale PNG.

        Args:
            meta: Parsed meta.json dict with 'images.shadow'.

        Returns:
            list: List of 256 shadow maps (each 64x64 2D list of 0/1),
                  indexed by chunk_row*16+chunk_col, or None.
        """
        images = meta.get('images', {})
        filename = images.get('shadow')
        if not filename:
            return None

        filepath = os.path.join(self.tile_dir, filename)
        if not os.path.isfile(filepath):
            return None

        img = Image.open(filepath).convert('L')
        shadows = []

        for chunk_idx in range(256):
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16
            base_y = chunk_row * 64
            base_x = chunk_col * 64

            shadow = []
            for sr in range(64):
                row = []
                for sc in range(64):
                    val = img.getpixel((base_x + sc, base_y + sr))
                    row.append(1 if val > 127 else 0)
                shadow.append(row)
            shadows.append(shadow)

        return shadows

    def read_alpha_maps(self, meta):
        """
        Read per-layer alpha maps from 1024x1024 grayscale PNGs.

        Args:
            meta: Parsed meta.json dict with 'images.alpha_maps'.

        Returns:
            dict: {layer_index: list of 256 alpha maps (each 64x64)},
                  or None if no alpha data.
        """
        images = meta.get('images', {})
        alpha_files = images.get('alpha_maps', [])
        if not alpha_files:
            return None

        result = {}
        for entry in alpha_files:
            li = entry.get('layer_index', 0)
            filename = entry.get('file', '')
            filepath = os.path.join(self.tile_dir, filename)
            if not os.path.isfile(filepath):
                continue

            img = Image.open(filepath).convert('L')
            per_chunk = []

            for chunk_idx in range(256):
                chunk_row = chunk_idx // 16
                chunk_col = chunk_idx % 16
                base_y = chunk_row * 64
                base_x = chunk_col * 64

                alpha = []
                for ar in range(64):
                    row = []
                    for ac in range(64):
                        row.append(img.getpixel((base_x + ac, base_y + ar)))
                    alpha.append(row)
                per_chunk.append(alpha)

            result[li] = per_chunk

        return result if result else None

    def read_vertex_colors(self, meta):
        """
        Read per-chunk vertex colors from a 129x129 RGBA PNG.

        Distributes the 129x129 grid back into per-chunk outer 9x9 arrays.

        Args:
            meta: Parsed meta.json dict with 'images.vertex_colors'.

        Returns:
            list: List of 256 vertex color arrays (each 145 RGBA tuples,
                  with inner vertices interpolated as defaults), or None.
        """
        images = meta.get('images', {})
        filename = images.get('vertex_colors')
        if not filename:
            return None

        filepath = os.path.join(self.tile_dir, filename)
        if not os.path.isfile(filepath):
            return None

        img = Image.open(filepath).convert('RGBA')
        default_color = [127, 127, 127, 255]
        per_chunk = []

        for chunk_idx in range(256):
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16
            colors_145 = []

            for interleaved_row in range(17):
                if interleaved_row % 2 == 0:
                    outer_row_idx = interleaved_row // 2
                    global_row = chunk_row * 8 + outer_row_idx
                    for col_idx in range(9):
                        global_col = chunk_col * 8 + col_idx
                        if global_row < 129 and global_col < 129:
                            px = img.getpixel((global_col, global_row))
                            colors_145.append(list(px))
                        else:
                            colors_145.append(list(default_color))
                else:
                    for _ in range(8):
                        colors_145.append(list(default_color))

            per_chunk.append(colors_145)

        return per_chunk

    def to_tile_json(self):
        """
        Read meta.json and all PNGs, reconstructing a tile dict compatible
        with the importer's _build_adt_tile() input format.

        Returns:
            dict: Tile data dict with 'tile_x', 'tile_y', 'textures',
                  'chunks', etc. matching the monolithic JSON structure.
        """
        meta_path = os.path.join(self.tile_dir, "meta.json")
        meta = load_json(meta_path)

        heightmap = self.read_heightmap(meta)
        shadows = self.read_shadow_map(meta)
        alpha_maps = self.read_alpha_maps(meta)
        vertex_colors = self.read_vertex_colors(meta)

        tile = {
            'tile_x': meta.get('tile_x', 0),
            'tile_y': meta.get('tile_y', 0),
            'textures': meta.get('textures', []),
            'm2_models': meta.get('m2_models', []),
            'wmo_models': meta.get('wmo_models', []),
            'doodad_placements': meta.get('doodad_placements', []),
            'wmo_placements': meta.get('wmo_placements', []),
            'chunks': [],
        }

        # Rebuild per-chunk data
        chunk_metas = meta.get('chunks', [])
        for chunk_idx in range(256):
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            # Get chunk metadata (flags, area_id, etc.)
            cm = chunk_metas[chunk_idx] if chunk_idx < len(chunk_metas) else {}

            chunk = {
                'index_x': cm.get('index_x', chunk_col),
                'index_y': cm.get('index_y', chunk_row),
                'flags': cm.get('flags', 0),
                'area_id': cm.get('area_id', 0),
                'holes': cm.get('holes', 0),
                'position': cm.get('position', [0.0, 0.0, 0.0]),
                'heightmap': [0.0] * 145,
                'normals': [[0, 0, 127]] * 145,
                'texture_layers': cm.get('texture_layers', []),
                'shadow_map': None,
                'vertex_colors': None,
                'sound_emitters': [],
            }

            # Fill heightmap 145-float from 129x129 grid
            if heightmap:
                heights_145 = []
                for interleaved_row in range(17):
                    if interleaved_row % 2 == 0:
                        outer_row_idx = interleaved_row // 2
                        global_row = chunk_row * 8 + outer_row_idx
                        for col_idx in range(9):
                            global_col = chunk_col * 8 + col_idx
                            if global_row < 129 and global_col < 129:
                                heights_145.append(heightmap[global_row][global_col])
                            else:
                                heights_145.append(0.0)
                    else:
                        # Inner vertices: interpolate from surrounding outers
                        inner_row_idx = interleaved_row // 2
                        for col_idx in range(8):
                            gr_top = chunk_row * 8 + inner_row_idx
                            gr_bot = gr_top + 1
                            gc_left = chunk_col * 8 + col_idx
                            gc_right = gc_left + 1
                            if (gr_top < 129 and gr_bot < 129
                                    and gc_left < 129 and gc_right < 129):
                                avg = (heightmap[gr_top][gc_left]
                                       + heightmap[gr_top][gc_right]
                                       + heightmap[gr_bot][gc_left]
                                       + heightmap[gr_bot][gc_right]) / 4.0
                                heights_145.append(avg)
                            else:
                                heights_145.append(0.0)
                chunk['heightmap'] = heights_145

            # Fill shadow map
            if shadows:
                chunk['shadow_map'] = shadows[chunk_idx]

            # Fill alpha maps into texture_layers
            if alpha_maps:
                for li, per_chunk_alphas in alpha_maps.items():
                    if li < len(chunk['texture_layers']):
                        chunk['texture_layers'][li]['alpha_map'] = \
                            per_chunk_alphas[chunk_idx]

            # Fill vertex colors
            if vertex_colors:
                chunk['vertex_colors'] = vertex_colors[chunk_idx]

            tile['chunks'].append(chunk)

        return tile
