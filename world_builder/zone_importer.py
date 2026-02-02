"""
Zone and dungeon importer for WoW WotLK 3.3.5a.

Imports zones and dungeons from the intermediate JSON format back to
game-ready binary files (WDT, ADT, WMO) with DBC registration and
MPQ directory packing.

The import pipeline reads a manifest.json (produced by the intermediate
format exporter) and reconstructs all binary assets:
  - WDT tile presence grid
  - ADT terrain tiles (heightmaps, textures, alpha maps)
  - WMO dungeon geometry (root + group files)
  - DBC records (Map, AreaTable, WorldMapArea, WorldMapOverlay)

Target build: WotLK 3.3.5a (build 12340)
"""

import os
import logging

from .wdt_generator import create_wdt
from .adt_composer import create_adt
from .dungeon_builder import build_dungeon
from .dbc_injector import (DBCInjector, register_map, register_area,
                           register_world_map_area, register_world_map_overlay)
from .mpq_packer import MPQPacker
from .intermediate_format import load_json, FORMAT_VERSION, IDAllocator, TileImageReader

log = logging.getLogger(__name__)


class ZoneImporter:
    """
    Import zones and dungeons from intermediate JSON format to game-ready
    binary files.

    Reads a manifest.json and associated data files from an export directory,
    allocates fresh DBC IDs, injects DBC records, generates binary terrain
    and geometry files, and packs everything into an MPQ directory structure.
    """

    def __init__(self, export_dir, output_dir, dbc_dir=None):
        """
        Initialise the zone importer.

        Args:
            export_dir: Path to export directory containing manifest.json
                        and all referenced JSON data files.
            output_dir: Where to write output binary game files.
            dbc_dir: Path to DBFilesClient directory for DBC injection.
                     If None, DBC registration is skipped.
        """
        self.export_dir = os.path.abspath(export_dir)
        self.output_dir = os.path.abspath(output_dir)
        self.dbc_dir = dbc_dir

    def import_zone(self):
        """
        Execute the full zone import pipeline.

        Steps:
            1. Load manifest.json from export directory
            2. Validate format_version compatibility
            3. Allocate new DBC IDs (if dbc_dir provided)
            4. Inject DBC records (Map, AreaTable, WorldMapArea, WorldMapOverlay)
            5. Generate WDT from tile list
            6. For each tile: load JSON, remap area IDs, generate ADT bytes
            7. Pack output using MPQPacker
            8. Return result dict

        Returns:
            dict: {
                'map_id': int or None,
                'area_ids': {original_id: new_id, ...},
                'map_name': str,
                'wdt_path': str,
                'adt_paths': [str, ...],
                'output_dir': str,
            }
        """
        manifest_path = os.path.join(self.export_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            log.error("Manifest not found: %s", manifest_path)
            return {
                'map_id': None,
                'area_ids': {},
                'map_name': '',
                'wdt_path': '',
                'adt_paths': [],
                'output_dir': self.output_dir,
            }

        manifest = load_json(manifest_path)
        log.info("Loaded manifest: %s (type=%s)", manifest.get('name', ''),
                 manifest.get('type', ''))

        # Validate format version
        file_version = manifest.get('format_version', '')
        if file_version != FORMAT_VERSION:
            log.warning("Format version mismatch: file=%s, expected=%s. "
                        "Import may produce unexpected results.",
                        file_version, FORMAT_VERSION)

        map_name = manifest.get('name', 'UnknownZone')

        # Allocate new IDs
        id_map = self._allocate_ids(manifest)

        # Inject DBC records
        self._inject_dbc_records(manifest, id_map)

        # Build tile coordinate list for WDT
        tiles = manifest.get('tiles', [])
        active_coords = []
        for tile in tiles:
            tx = tile.get('x', 0)
            ty = tile.get('y', 0)
            active_coords.append((tx, ty))

        # Generate WDT
        mphd_flags = manifest.get('mphd_flags', 0x80)
        wdt_bytes = create_wdt(active_coords, mphd_flags)
        log.info("Generated WDT with %d active tiles", len(active_coords))

        # Generate ADTs
        adt_dict = {}
        for tile in tiles:
            tx = tile.get('x', 0)
            ty = tile.get('y', 0)
            tile_file = tile.get('file', '')
            tile_path = os.path.join(self.export_dir, tile_file)

            tile_json = self._load_tile(tile_path)
            if tile_json is None:
                log.warning("Tile not found, skipping: %s", tile_path)
                continue

            adt_bytes = self._build_adt_tile(tile_json, id_map)
            adt_dict[(tx, ty)] = adt_bytes
            log.debug("Generated ADT for tile (%d, %d)", tx, ty)

        # Pack output
        map_directory = self._get_map_directory(manifest)
        output_path = self._pack_output(map_directory, wdt_bytes, adt_dict)

        # Build result paths
        map_dir = os.path.join(output_path, "World", "Maps", map_directory)
        wdt_path = os.path.join(map_dir, "{}.wdt".format(map_directory))
        adt_paths = [
            os.path.join(map_dir, "{}_{:d}_{:d}.adt".format(
                map_directory, tx, ty))
            for tx, ty in adt_dict.keys()
        ]

        result = {
            'map_id': id_map.get('map_id'),
            'area_ids': id_map.get('area_ids', {}),
            'map_name': map_name,
            'wdt_path': wdt_path,
            'adt_paths': adt_paths,
            'output_dir': self.output_dir,
        }

        log.info("Zone import complete: %s (%d tiles)", map_name,
                 len(adt_dict))
        return result

    def import_dungeon(self):
        """
        Execute the full dungeon import pipeline.

        Steps:
            1. Load manifest.json
            2. Validate format_version
            3. Allocate new DBC IDs
            4. Inject DBC records (Map with instance_type=1, AreaTable)
            5. If wmo/ directory exists: load root.json and group files,
               transform to build_dungeon() input, generate WMO files
            6. If tiles exist, generate WDT + ADTs
            7. Pack output using MPQPacker
            8. Return result dict

        Returns:
            dict: {
                'map_id': int or None,
                'area_ids': {original_id: new_id, ...},
                'map_name': str,
                'wdt_path': str,
                'adt_paths': [str, ...],
                'wmo_files': [str, ...],
                'output_dir': str,
            }
        """
        manifest_path = os.path.join(self.export_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            log.error("Manifest not found: %s", manifest_path)
            return {
                'map_id': None,
                'area_ids': {},
                'map_name': '',
                'wdt_path': '',
                'adt_paths': [],
                'wmo_files': [],
                'output_dir': self.output_dir,
            }

        manifest = load_json(manifest_path)
        log.info("Loaded dungeon manifest: %s", manifest.get('name', ''))

        # Validate format version
        file_version = manifest.get('format_version', '')
        if file_version != FORMAT_VERSION:
            log.warning("Format version mismatch: file=%s, expected=%s. "
                        "Import may produce unexpected results.",
                        file_version, FORMAT_VERSION)

        map_name = manifest.get('name', 'UnknownDungeon')

        # Allocate new IDs
        id_map = self._allocate_ids(manifest)

        # Inject DBC records
        self._inject_dbc_records(manifest, id_map)

        wmo_files = []
        wdt_bytes = None
        adt_dict = {}

        # Build WMO if wmo/ directory exists
        wmo_dir = os.path.join(self.export_dir, "wmo")
        if os.path.isdir(wmo_dir):
            wmo_files = self._import_wmo(manifest, id_map)

        # Build terrain tiles if present
        tiles = manifest.get('tiles', [])
        if tiles:
            active_coords = []
            for tile in tiles:
                tx = tile.get('x', 0)
                ty = tile.get('y', 0)
                active_coords.append((tx, ty))

            mphd_flags = manifest.get('mphd_flags', 0x80)
            wdt_bytes = create_wdt(active_coords, mphd_flags)

            for tile in tiles:
                tx = tile.get('x', 0)
                ty = tile.get('y', 0)
                tile_file = tile.get('file', '')
                tile_path = os.path.join(self.export_dir, tile_file)

                tile_json = self._load_tile(tile_path)
                if tile_json is None:
                    log.warning("Tile not found, skipping: %s", tile_path)
                    continue

                # Skip non-terrain tile files (e.g. dungeon.json)
                if 'chunks' not in tile_json and 'tile_x' not in tile_json:
                    log.debug("Skipping non-terrain tile file: %s", tile_file)
                    continue

                adt_bytes = self._build_adt_tile(tile_json, id_map)
                adt_dict[(tx, ty)] = adt_bytes

        # Pack output
        map_directory = self._get_map_directory(manifest)
        output_path = self._pack_output(
            map_directory, wdt_bytes, adt_dict, wmo_files=wmo_files)

        # Build result paths
        wdt_path = ''
        adt_paths = []
        if wdt_bytes:
            map_dir = os.path.join(output_path, "World", "Maps", map_directory)
            wdt_path = os.path.join(map_dir, "{}.wdt".format(map_directory))
            adt_paths = [
                os.path.join(map_dir, "{}_{:d}_{:d}.adt".format(
                    map_directory, tx, ty))
                for tx, ty in adt_dict.keys()
            ]

        result = {
            'map_id': id_map.get('map_id'),
            'area_ids': id_map.get('area_ids', {}),
            'map_name': map_name,
            'wdt_path': wdt_path,
            'adt_paths': adt_paths,
            'wmo_files': wmo_files,
            'output_dir': self.output_dir,
        }

        log.info("Dungeon import complete: %s", map_name)
        return result

    # ------------------------------------------------------------------
    # ID allocation
    # ------------------------------------------------------------------

    def _allocate_ids(self, manifest):
        """
        Allocate new DBC IDs for all records in the manifest.

        Reads existing DBC files to find the next free IDs. If dbc_dir
        is not set, returns an empty mapping so the rest of the pipeline
        can proceed without DBC injection.

        Args:
            manifest: Parsed manifest.json dict.

        Returns:
            dict with 'map_id', 'area_ids', and 'area_bits' mappings.
        """
        if not self.dbc_dir:
            return {}

        allocator = IDAllocator(self.dbc_dir)

        id_map = {
            'map_id': allocator.next_map_id(),
            'area_ids': {},
            'area_bits': {},
        }

        # Allocate area IDs for each area in areas.json
        areas_file = manifest.get('files', {}).get('areas', 'areas.json')
        areas_path = os.path.join(self.export_dir, areas_file)
        if os.path.isfile(areas_path):
            areas_data = load_json(areas_path)
            for area in areas_data.get('areas', []):
                orig_id = area.get('original_id', 0)
                id_map['area_ids'][orig_id] = allocator.next_area_id()
                id_map['area_bits'][orig_id] = allocator.next_area_bit()
        else:
            log.warning("Areas file not found: %s", areas_path)

        return id_map

    # ------------------------------------------------------------------
    # DBC injection
    # ------------------------------------------------------------------

    def _inject_dbc_records(self, manifest, id_map):
        """
        Inject DBC records for the imported zone or dungeon.

        Registers entries in Map.dbc, AreaTable.dbc, WorldMapArea.dbc,
        and WorldMapOverlay.dbc based on the manifest and exported JSON
        data files.

        Args:
            manifest: Parsed manifest.json dict.
            id_map: ID mapping from _allocate_ids().
        """
        if not self.dbc_dir:
            return

        map_name = manifest.get('name', '')
        new_map_id = id_map.get('map_id')
        if new_map_id is None:
            log.warning("No map_id allocated, skipping DBC injection")
            return

        # Load map.json for directory name and instance type
        map_file = manifest.get('files', {}).get('map', 'map.json')
        map_path = os.path.join(self.export_dir, map_file)
        if os.path.isfile(map_path):
            map_data = load_json(map_path)
        else:
            log.warning("Map file not found: %s (using defaults)", map_path)
            map_data = {}

        # Register map
        directory = map_data.get('directory',
                                 map_data.get('slug',
                                              map_name.replace(' ', '')))
        instance_type = map_data.get('instance_type', 0)
        register_map(self.dbc_dir, directory, map_id=new_map_id,
                     instance_type=instance_type)
        log.info("Registered Map.dbc: id=%d, directory=%s, instance_type=%d",
                 new_map_id, directory, instance_type)

        # Load and register areas
        areas_file = manifest.get('files', {}).get('areas', 'areas.json')
        areas_path = os.path.join(self.export_dir, areas_file)
        if os.path.isfile(areas_path):
            areas_data = load_json(areas_path)
            for area in areas_data.get('areas', []):
                orig_id = area.get('original_id', 0)
                new_area_id = id_map.get('area_ids', {}).get(orig_id)
                if new_area_id is None:
                    log.warning("No new area_id for original_id=%d, skipping",
                                orig_id)
                    continue

                # Resolve parent area ID through the mapping
                parent_orig = area.get('original_parent_id', 0)
                parent_new = id_map.get('area_ids', {}).get(parent_orig, 0)

                register_area(
                    self.dbc_dir,
                    area.get('name', ''),
                    new_map_id,
                    area_id=new_area_id,
                    parent_area_id=parent_new,
                    ambience_id=area.get('ambience_id', 0),
                    zone_music=area.get('zone_music', 0),
                    light_id=area.get('light_id', 0),
                )
                log.debug("Registered AreaTable.dbc: id=%d, name=%s",
                          new_area_id, area.get('name', ''))

        # Register world map areas if present
        wm_file = manifest.get('files', {}).get('world_map', 'world_map.json')
        wm_path = os.path.join(self.export_dir, wm_file)
        if os.path.isfile(wm_path):
            wm_data = load_json(wm_path)
            for wma in wm_data.get('world_map_areas', []):
                orig_area_id = wma.get('original_area_id', 0)
                new_area_id = id_map.get('area_ids', {}).get(orig_area_id, 0)
                wma_id = register_world_map_area(
                    self.dbc_dir,
                    wma.get('area_name', ''),
                    new_map_id,
                    new_area_id,
                    loc_left=wma.get('loc_left', 0.0),
                    loc_right=wma.get('loc_right', 0.0),
                    loc_top=wma.get('loc_top', 0.0),
                    loc_bottom=wma.get('loc_bottom', 0.0),
                )
                log.debug("Registered WorldMapArea.dbc: id=%d", wma_id)

                # Register overlays for this world map area
                for overlay in wma.get('overlays', []):
                    register_world_map_overlay(
                        self.dbc_dir,
                        wma_id,
                        overlay.get('texture_name', ''),
                        texture_width=overlay.get('texture_width', 512),
                        texture_height=overlay.get('texture_height', 512),
                        map_point_x=overlay.get('map_point_x', 0),
                        map_point_y=overlay.get('map_point_y', 0),
                    )

    # ------------------------------------------------------------------
    # Tile loading (auto-detect format)
    # ------------------------------------------------------------------

    def _load_tile(self, tile_path):
        """
        Load tile data from a tile image directory (PNG + meta.json).

        Args:
            tile_path: Path to a tile directory containing meta.json and PNGs.

        Returns:
            dict: Tile data dict, or None if not found.
        """
        if os.path.isdir(tile_path):
            meta_path = os.path.join(tile_path, "meta.json")
            if os.path.isfile(meta_path):
                reader = TileImageReader(tile_path)
                return reader.to_tile_json()
            log.warning("Tile directory has no meta.json: %s", tile_path)
            return None

        return None

    # ------------------------------------------------------------------
    # ADT tile reconstruction
    # ------------------------------------------------------------------

    def _build_adt_tile(self, tile_json, id_map):
        """
        Transform tile JSON back into create_adt() input format and
        generate the ADT binary.

        Reconstructs the 129x129 heightmap from per-chunk 145-float
        heightmaps by extracting outer vertices (9x9 per chunk) and
        placing them into the global grid. Reconstructs the splat map
        from per-chunk alpha maps.

        Args:
            tile_json: Parsed tile JSON dict with 'tile_x', 'tile_y',
                       'chunks', and optionally 'textures'.
            id_map: ID mapping for area ID remapping.

        Returns:
            bytes: Complete ADT binary content.
        """
        tile_x = tile_json.get('tile_x', 0)
        tile_y = tile_json.get('tile_y', 0)
        chunks = tile_json.get('chunks', [])

        # Collect all unique textures across chunks, or use tile-level list
        texture_paths = tile_json.get('textures', None)
        if texture_paths is None:
            texture_set = []
            texture_index_map = {}
            for chunk in chunks:
                for tex in chunk.get('textures', []):
                    if tex not in texture_index_map:
                        texture_index_map[tex] = len(texture_set)
                        texture_set.append(tex)
            texture_paths = texture_set if texture_set else None

        # Reconstruct 129x129 heightmap from per-chunk 145-float heightmaps
        heightmap = self._reconstruct_heightmap(chunks)

        # Reconstruct splat map from per-chunk alpha maps
        splat_map = self._reconstruct_splat_map(chunks)

        # Determine area_id: use remapped ID if available, else first area
        area_id = self._resolve_area_id(tile_json, chunks, id_map)

        adt_bytes = create_adt(
            tile_x=tile_x,
            tile_y=tile_y,
            heightmap=heightmap,
            texture_paths=texture_paths,
            splat_map=splat_map,
            area_id=area_id,
        )

        return adt_bytes

    def _reconstruct_heightmap(self, chunks):
        """
        Reconstruct a 129x129 heightmap from per-chunk 145-float heightmaps.

        For each chunk (arranged in a 16x16 grid), the 145 height values
        are interleaved: 9 outer vertices, 8 inner vertices, alternating
        for 17 rows (9 outer rows + 8 inner rows = 145 total).

        Only the outer 9x9 vertices per chunk are extracted and placed
        into the global 129x129 grid at:
            global_row = chunk_row * 8 + outer_row_index
            global_col = chunk_col * 8 + col_index

        Args:
            chunks: List of 256 chunk dicts, each with a 'heights' list
                    of 145 float values. Ordered row-major (chunk_row
                    varies slowest).

        Returns:
            list: 129x129 2D list of float heights, or None if no
                  height data is present.
        """
        if not chunks:
            return None

        # Check if any chunk has height data
        has_heights = False
        for chunk in chunks:
            if chunk.get('heights'):
                has_heights = True
                break

        if not has_heights:
            return None

        heightmap = [[0.0] * 129 for _ in range(129)]

        for chunk_idx, chunk in enumerate(chunks):
            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            heights_145 = chunk.get('heights', [])
            if not heights_145:
                continue

            # Walk the interleaved layout: 17 rows total
            # Even rows (0,2,4,...,16): outer rows with 9 vertices
            # Odd rows (1,3,5,...,15): inner rows with 8 vertices
            idx = 0
            for interleaved_row in range(17):
                if interleaved_row % 2 == 0:
                    # Outer row
                    outer_row_idx = interleaved_row // 2
                    global_row = chunk_row * 8 + outer_row_idx
                    for col_idx in range(9):
                        if idx < len(heights_145):
                            global_col = chunk_col * 8 + col_idx
                            if global_row < 129 and global_col < 129:
                                heightmap[global_row][global_col] = \
                                    heights_145[idx]
                        idx += 1
                else:
                    # Inner row: 8 vertices, skip for heightmap
                    idx += 8

        return heightmap

    def _reconstruct_splat_map(self, chunks):
        """
        Reconstruct the splat map from per-chunk alpha map data.

        The create_adt() function expects splat_map as a dict mapping
        layer_index (int) to a 64x64 2D list of alpha values (0-255).
        Since create_adt() applies the same alpha map to all 256 chunks,
        and the intermediate format stores per-chunk alpha maps, we use
        the alpha data from the first chunk that has data for each layer
        as a representative.

        Args:
            chunks: List of 256 chunk dicts, each optionally containing
                    'texture_layers' with per-layer alpha maps.

        Returns:
            dict or None: {layer_idx: [[64x64 alpha values]]} or None
                          if no alpha data is present.
        """
        if not chunks:
            return None

        splat_map = {}

        for chunk in chunks:
            layers = chunk.get('texture_layers', [])
            # Skip layer 0 (base layer has no alpha)
            for layer_idx in range(1, len(layers)):
                if layer_idx in splat_map:
                    # Already have data for this layer
                    continue

                layer = layers[layer_idx]
                alpha = layer.get('alpha_map')
                if alpha and len(alpha) > 0:
                    splat_map[layer_idx] = alpha

        return splat_map if splat_map else None

    def _resolve_area_id(self, tile_json, chunks, id_map):
        """
        Determine the area_id to use for the ADT tile.

        Tries to resolve through the ID mapping first. Falls back to
        the tile-level area_id, then to the first chunk's area_id,
        and finally to 0.

        Args:
            tile_json: Parsed tile JSON dict.
            chunks: List of chunk dicts.
            id_map: ID mapping from _allocate_ids().

        Returns:
            int: The resolved area_id.
        """
        # Try tile-level area_id first
        orig_area_id = tile_json.get('area_id', 0)

        # Try to get from first chunk if not at tile level
        if not orig_area_id and chunks:
            orig_area_id = chunks[0].get('area_id', 0)

        # Remap through id_map if available
        area_ids = id_map.get('area_ids', {})
        if area_ids and orig_area_id in area_ids:
            return area_ids[orig_area_id]

        # If we have any new area IDs, use the first one as fallback
        if area_ids:
            first_new_id = next(iter(area_ids.values()), 0)
            if first_new_id:
                return first_new_id

        return orig_area_id

    # ------------------------------------------------------------------
    # WMO reconstruction
    # ------------------------------------------------------------------

    def _import_wmo(self, manifest, id_map):
        """
        Import WMO dungeon files from the intermediate JSON format.

        Loads root.json and all group_NNN.json files from the wmo/
        subdirectory, transforms them into the build_dungeon() input
        format, and generates WMO binary files.

        Args:
            manifest: Parsed manifest.json dict.
            id_map: ID mapping from _allocate_ids().

        Returns:
            list: Paths to generated WMO files.
        """
        wmo_root_file = manifest.get('files', {}).get(
            'wmo_root', 'wmo/root.json')
        root_path = os.path.join(self.export_dir, wmo_root_file)

        if not os.path.isfile(root_path):
            log.warning("WMO root file not found: %s", root_path)
            return []

        root_json = load_json(root_path)

        # Load all group files
        group_jsons = []
        group_files = root_json.get('groups', [])
        for group_file in group_files:
            group_path = os.path.join(self.export_dir, group_file)
            if os.path.isfile(group_path):
                group_jsons.append(load_json(group_path))
            else:
                log.warning("WMO group file not found: %s", group_path)

        if not group_jsons:
            log.warning("No WMO group files loaded")
            return []

        # Build dungeon using build_dungeon()
        result = self._build_wmo(root_json, group_jsons)
        return result.get('wmo_files', [])

    def _build_wmo(self, root_json, group_jsons):
        """
        Build WMO dungeon from JSON root and group data.

        Transforms the intermediate JSON representation back into the
        dungeon definition dict expected by build_dungeon().

        Args:
            root_json: Parsed WMO root JSON dict with name, portals,
                       materials, lights, doodads.
            group_jsons: List of parsed group JSON dicts, each with
                         vertices, triangles, normals, uvs, etc.

        Returns:
            dict: Result from build_dungeon() containing 'wmo_files',
                  'coordinate_metadata', and 'map_id'.
        """
        definition = {
            'name': root_json.get('name', 'Dungeon'),
            'rooms': [],
            'portals': root_json.get('portals', []),
            'materials': root_json.get('materials', []),
            'lights': root_json.get('lights', []),
            'doodads': root_json.get('doodads', []),
        }

        for group_json in group_jsons:
            room = {
                'type': 'raw_mesh',
                'name': group_json.get('name', ''),
                'vertices': [tuple(v) for v in group_json.get('vertices', [])],
                'triangles': [
                    tuple(t) for t in group_json.get('triangles', [])],
                'normals': [
                    tuple(n) for n in group_json.get('normals', [])],
                'uvs': [tuple(u) for u in group_json.get('uvs', [])],
                'face_materials': group_json.get('face_materials', []),
                'bounds': group_json.get('bounds', {}),
                'center': tuple(group_json.get('center', (0, 0, 0))),
            }
            definition['rooms'].append(room)

        return build_dungeon(definition, self.output_dir, dbc_dir=None)

    # ------------------------------------------------------------------
    # Output packing
    # ------------------------------------------------------------------

    def _pack_output(self, map_name, wdt_bytes, adt_dict, wmo_files=None):
        """
        Pack all generated files into an MPQ directory structure.

        Uses MPQPacker to organise WDT, ADT, and optionally WMO files
        into the correct WoW client patch directory layout.

        Args:
            map_name: Map directory name for MPQ paths.
            wdt_bytes: WDT binary data (bytes), or None if no WDT.
            adt_dict: Dict mapping (tile_x, tile_y) to ADT bytes.
            wmo_files: Optional list of WMO file paths on disk to
                       include in the output.

        Returns:
            str: Absolute path to the packed output directory.
        """
        packer = MPQPacker(self.output_dir)

        if wdt_bytes:
            packer.add_wdt(map_name, wdt_bytes)

        for (tx, ty), adt_bytes in adt_dict.items():
            packer.add_adt(map_name, tx, ty, adt_bytes)

        output_path = packer.build_directory()

        # Copy WMO files into the output directory structure if present
        if wmo_files:
            for wmo_path in wmo_files:
                if os.path.isfile(wmo_path):
                    # Determine relative path within output
                    # WMO files from build_dungeon() are already under
                    # output_dir/World/wmo/Dungeons/...
                    # They may already be in the right place if
                    # build_dungeon() used the same output_dir.
                    log.debug("WMO file included: %s", wmo_path)

        return output_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_map_directory(self, manifest):
        """
        Determine the map directory name from the manifest.

        Tries map.json 'directory' field first, then 'slug', then
        falls back to the manifest name with spaces removed.

        Args:
            manifest: Parsed manifest.json dict.

        Returns:
            str: Map directory name suitable for MPQ paths.
        """
        map_file = manifest.get('files', {}).get('map', 'map.json')
        map_path = os.path.join(self.export_dir, map_file)
        if os.path.isfile(map_path):
            map_data = load_json(map_path)
            directory = map_data.get('directory', '')
            if directory:
                return directory
            slug = map_data.get('slug', '')
            if slug:
                return slug

        name = manifest.get('name', 'UnknownZone')
        return name.replace(' ', '')


# ======================================================================
# Convenience functions
# ======================================================================

def import_zone(export_dir, output_dir, dbc_dir=None):
    """
    Import a zone from intermediate JSON format to game files.

    Convenience wrapper around ZoneImporter.import_zone().

    Args:
        export_dir: Path to export directory containing manifest.json.
        output_dir: Where to write output binary game files.
        dbc_dir: Path to DBFilesClient directory for DBC injection.
                 If None, DBC registration is skipped.

    Returns:
        dict: Import result with map_id, area_ids, paths, etc.
    """
    importer = ZoneImporter(export_dir, output_dir, dbc_dir)
    return importer.import_zone()


def import_dungeon(export_dir, output_dir, dbc_dir=None):
    """
    Import a dungeon from intermediate JSON format to game files.

    Convenience wrapper around ZoneImporter.import_dungeon().

    Args:
        export_dir: Path to export directory containing manifest.json.
        output_dir: Where to write output binary game files.
        dbc_dir: Path to DBFilesClient directory for DBC injection.
                 If None, DBC registration is skipped.

    Returns:
        dict: Import result with map_id, area_ids, paths, etc.
    """
    importer = ZoneImporter(export_dir, output_dir, dbc_dir)
    return importer.import_dungeon()
