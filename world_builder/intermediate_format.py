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
