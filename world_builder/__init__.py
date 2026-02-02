"""
World Builder - Headless World Compiler for WoW WotLK 3.3.5a

Provides a high-level API for programmatically generating WoW map terrain,
registering custom maps in DBC files, packaging everything into MPQ archives,
and generating all supporting assets (artwork, scripts, SQL, dungeons, etc.).

Includes an intermediate JSON format for exporting, editing, and importing
zones and dungeons via ZoneExporter / ZoneImporter.
"""

import os

from .wdt_generator import create_wdt, write_wdt, read_wdt
from .adt_composer import create_adt, write_adt, read_adt
from .dbc_injector import DBCInjector, register_map, register_area
from .mpq_packer import MPQPacker, pack_map, MPQExtractor, extract_map
from .blp_converter import convert_png_to_blp, image_to_blp, batch_convert, validate_blp
from .minimap_pipeline import import_minimap_tiles, generate_test_minimaps
from .terrain_sculptor import (TerrainSculptor, sculpt_zone, sculpt_for_adt_composer,
                               import_heightmap_from_adt, import_texture_rules_from_adt)
from .dungeon_builder import build_dungeon, export_spawn_coordinates, read_dungeon
from .artwork_pipeline import (generate_world_map, generate_subzone_overlays,
                               generate_loading_screen, generate_dungeon_map,
                               generate_zone_artwork_bundle,
                               import_artwork_image)
from .script_generator import ScriptGenerator, import_lua_script
from .spell_registry import SpellRegistry
from .sql_generator import SQLGenerator, import_sql
from .qa_validator import QAValidator
from .qa_report import QAReport
from .intermediate_format import (IDAllocator, create_zone_template,
                                  create_dungeon_template)
from .zone_exporter import ZoneExporter, export_zone, export_dungeon
from .zone_importer import ZoneImporter, import_zone, import_dungeon


def build_zone(name, output_dir, coords=None, heightmap=None, texture_paths=None,
               splat_map=None, area_id=0, dbc_dir=None, mphd_flags=0x80):
    """
    High-level API to build a complete custom zone.

    This is the main entry point for the AI agent to create a new map zone.
    It orchestrates all phases: DBC registration, WDT generation, ADT creation,
    and MPQ packing.

    Args:
        name: Map/zone name (used as directory name and display name).
        output_dir: Where to write output files.
        coords: List of (x, y) tile coordinates to generate. Default: [(32, 32)].
        heightmap: Optional 2D height array for terrain. If None, flat terrain.
        texture_paths: List of texture paths (BLP files).
                       Default: ["Tileset\\Generic\\Black.blp"]
        splat_map: Optional dict of texture_index -> 2D alpha array.
        area_id: Area ID for the zone (0 for auto).
        dbc_dir: Path to DBFilesClient directory for DBC injection.
                 If None, DBC injection is skipped.
        mphd_flags: WDT MPHD flags (default 0x80 for big alpha).

    Returns:
        dict: {
            'map_id': int or None,
            'area_id': int or None,
            'wdt_path': str,
            'adt_paths': list[str],
            'output_dir': str,
        }
    """
    if coords is None:
        coords = [(32, 32)]

    if texture_paths is None:
        texture_paths = ["Tileset\\Generic\\Black.blp"]

    result = {
        'map_id': None,
        'area_id': None,
        'wdt_path': None,
        'adt_paths': [],
        'output_dir': output_dir,
    }

    # Phase 1: Register in DBC (if dbc_dir provided)
    map_id = None
    if dbc_dir:
        map_id = register_map(dbc_dir, name)
        registered_area_id = register_area(dbc_dir, name, map_id, area_id if area_id else None)
        result['map_id'] = map_id
        result['area_id'] = registered_area_id
        if not area_id:
            area_id = registered_area_id

    # Phase 2: Create WDT
    wdt_data = create_wdt(coords, mphd_flags)

    # Phase 3: Create ADTs
    adt_files = {}
    for x, y in coords:
        adt_data = create_adt(
            tile_x=x,
            tile_y=y,
            heightmap=heightmap,
            texture_paths=texture_paths,
            splat_map=splat_map,
            area_id=area_id,
        )
        adt_files[(x, y)] = adt_data

    # Phase 4: Pack into MPQ structure
    packer = MPQPacker(output_dir)
    packer.add_wdt(name, wdt_data)
    for (x, y), data in adt_files.items():
        packer.add_adt(name, x, y, data)

    output_path = packer.build_directory()

    # Collect result paths
    map_dir = os.path.join(output_path, "World", "Maps", name)
    result['wdt_path'] = os.path.join(map_dir, "{}.wdt".format(name))
    result['adt_paths'] = [
        os.path.join(map_dir, "{}_{:d}_{:d}.adt".format(name, x, y))
        for x, y in coords
    ]

    return result
