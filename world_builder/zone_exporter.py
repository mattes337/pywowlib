"""
Zone and dungeon exporter for WoW WotLK 3.3.5a (build 12340).

Reads binary game files (WDT, ADT, WMO, DBC) and exports them to an
intermediate JSON format suitable for round-tripping, external editing,
or data analysis.  Each export produces a self-contained directory of
JSON files with a manifest.json at its root.

Exported layout (zone):
    {output_base}/zones/{slug}/
        manifest.json
        map.json
        areas.json
        world_map.json
        atmosphere.json
        tiles/{x}_{y}.json

Exported layout (dungeon):
    {output_base}/dungeons/{slug}/
        manifest.json
        map.json
        areas.json
        dungeon.json
        wmo/{wmo_name}/root.json          (per WMO set)
        wmo/{wmo_name}/group_NNN.json     (per WMO group)
        tiles/{x}_{y}.json                (if terrain exists)

Target build: WotLK 3.3.5a (build 12340)
"""

import os
import struct
import logging
from datetime import datetime, timezone

from .wdt_generator import read_wdt
from .adt_composer import read_adt
from .dungeon_builder import read_dungeon
from .dbc_injector import DBCInjector
from .intermediate_format import (slugify, save_json, load_json,
                                  FORMAT_VERSION,
                                  TileImageWriter, WMOGltfWriter,
                                  MPQChain, blp_to_png)

try:
    from ..adt_file import ADTFile
except (ImportError, SystemError):
    try:
        from adt_file import ADTFile
    except ImportError:
        ADTFile = None

log = logging.getLogger(__name__)


class ZoneExporter(object):
    """
    Exports WoW 3.3.5a zones and dungeons from binary game files to an
    intermediate JSON format.

    Reads WDT, ADT, WMO, and DBC files from extracted game data and
    writes a structured set of JSON files describing the zone or dungeon
    in full fidelity.
    """

    def __init__(self, game_data_dir, dbc_dir, output_base="exports",
                 wow_root=None):
        """
        Initialize the zone exporter.

        Args:
            game_data_dir: Root of extracted game files (contains World/Maps/...).
            dbc_dir: Path to DBFilesClient directory containing DBC files.
            output_base: Base directory for exports (e.g. "exports").
            wow_root: Optional path to WoW installation root (contains Data/
                with MPQ archives).  When set, BLP textures referenced by the
                export are extracted from MPQ archives and saved as PNG images
                alongside the export.
        """
        self.game_data_dir = game_data_dir
        self.dbc_dir = dbc_dir
        self.output_base = output_base
        self.wow_root = wow_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_zone(self, map_name, map_id):
        """
        Export a complete zone from binary game files to intermediate JSON.

        Reads the WDT to discover active tiles, exports all DBC metadata
        (map, areas, world map, atmosphere), then serializes each ADT tile
        to a per-tile JSON file.

        Args:
            map_name: Internal map directory name (e.g. "Azeroth").
            map_id: Numeric map ID matching Map.dbc.

        Returns:
            str: Path to the generated manifest.json, or None on failure.
        """
        slug = slugify(map_name)
        output_dir = os.path.join(self.output_base, "zones", slug)

        # Locate WDT
        wdt_path = os.path.join(
            self.game_data_dir, "World", "Maps", map_name,
            "{}.wdt".format(map_name)
        )

        if not os.path.isfile(wdt_path):
            log.warning("WDT not found: %s", wdt_path)
            return None

        # Read WDT
        try:
            wdt_data = read_wdt(wdt_path)
        except Exception as e:
            log.warning("Failed to read WDT %s: %s", wdt_path, e)
            return None

        active_coords = wdt_data['active_coords']
        mphd_flags = wdt_data['mphd_flags']
        log.info("Zone '%s' (id=%d): %d active tiles, mphd_flags=0x%X",
                 map_name, map_id, len(active_coords), mphd_flags)

        # Export DBC records
        map_record = self._export_map_record(map_id)
        area_records = self._export_area_records(map_id)
        world_map_records = self._export_world_map_records(map_id)
        atmosphere_records = self._export_atmosphere_records(map_id)

        files_dict = {}

        if map_record is not None:
            map_json_path = os.path.join(output_dir, "map.json")
            save_json(map_json_path, map_record)
            files_dict["map"] = "map.json"

        if area_records is not None:
            areas_json_path = os.path.join(output_dir, "areas.json")
            save_json(areas_json_path, area_records)
            files_dict["areas"] = "areas.json"

        if world_map_records is not None:
            wm_json_path = os.path.join(output_dir, "world_map.json")
            save_json(wm_json_path, world_map_records)
            files_dict["world_map"] = "world_map.json"

        if atmosphere_records is not None:
            atmo_json_path = os.path.join(output_dir, "atmosphere.json")
            save_json(atmo_json_path, atmosphere_records)
            files_dict["atmosphere"] = "atmosphere.json"

        # Export each active tile
        tiles_list = []
        for (x, y) in active_coords:
            adt_filename = "{}_{:d}_{:d}.adt".format(map_name, x, y)
            adt_filepath = os.path.join(
                self.game_data_dir, "World", "Maps", map_name, adt_filename
            )

            if not os.path.isfile(adt_filepath):
                log.warning("ADT not found, skipping tile (%d, %d): %s",
                            x, y, adt_filepath)
                continue

            try:
                tile_data = self._export_adt_tile(adt_filepath, mphd_flags)
                tile_rel_path = "tiles/{}_{}".format(x, y)
                tile_abs_dir = os.path.join(output_dir, tile_rel_path)
                self._write_tile_images(tile_abs_dir, tile_data)
                tiles_list.append({"x": x, "y": y, "file": tile_rel_path})
                log.info("Exported tile (%d, %d)", x, y)
            except Exception as e:
                log.warning("Failed to export tile (%d, %d): %s", x, y, e)

        # Extract referenced images from MPQ archives (optional)
        if self.wow_root:
            image_paths = self._collect_zone_image_paths(
                output_dir, map_record, tiles_list)
            self._extract_images(output_dir, image_paths, files_dict)

        # Write manifest
        manifest = {
            "format_version": FORMAT_VERSION,
            "type": "zone",
            "name": map_name,
            "slug": slug,
            "map_id": map_id,
            "mphd_flags": mphd_flags,
            "tile_count": len(tiles_list),
            "tiles": tiles_list,
            "files": files_dict,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        manifest_path = os.path.join(output_dir, "manifest.json")
        save_json(manifest_path, manifest)

        log.info("Zone export complete: %s (%d tiles)", manifest_path,
                 len(tiles_list))
        return manifest_path

    def export_dungeon(self, map_name, map_id, wmo_path=None,
                       wmo_paths=None):
        """
        Export a complete dungeon from binary game files to intermediate JSON.

        Reads DBC metadata, optionally reads WMO geometry, and exports
        any terrain tiles if a WDT exists for this dungeon map.

        Args:
            map_name: Internal map directory name (e.g. "TheDeadmines").
            map_id: Numeric map ID matching Map.dbc.
            wmo_path: Optional path to a single WMO root file.
            wmo_paths: Optional list of paths to multiple WMO root files.
                       Overrides wmo_path if both provided.

        Returns:
            str: Path to the generated manifest.json, or None on failure.
        """
        slug = slugify(map_name)
        output_dir = os.path.join(self.output_base, "dungeons", slug)

        # Export DBC records
        map_record = self._export_map_record(map_id)
        area_records = self._export_area_records(map_id)
        dungeon_records = self._export_dungeon_records(map_id)

        files_dict = {}

        if map_record is not None:
            map_json_path = os.path.join(output_dir, "map.json")
            save_json(map_json_path, map_record)
            files_dict["map"] = "map.json"

        if area_records is not None:
            areas_json_path = os.path.join(output_dir, "areas.json")
            save_json(areas_json_path, area_records)
            files_dict["areas"] = "areas.json"

        if dungeon_records is not None:
            dung_json_path = os.path.join(output_dir, "dungeon.json")
            save_json(dung_json_path, dungeon_records)
            files_dict["dungeon"] = "dungeon.json"

        # Build list of WMO paths to export
        all_wmo_paths = []
        if wmo_paths:
            all_wmo_paths = list(wmo_paths)
        elif wmo_path:
            all_wmo_paths = [wmo_path]

        # Export WMO geometry for each WMO root file
        for wp in all_wmo_paths:
            if not os.path.isfile(wp):
                log.warning("WMO file not found: %s", wp)
                continue
            try:
                dungeon_def = read_dungeon(wp)
                self._export_wmo_data(output_dir, dungeon_def, files_dict)
                log.info("Exported WMO geometry from: %s", wp)
            except Exception as e:
                log.warning("Failed to read WMO %s: %s", wp, e)

        # Export terrain tiles if WDT exists
        tiles_list = []
        wdt_path = os.path.join(
            self.game_data_dir, "World", "Maps", map_name,
            "{}.wdt".format(map_name)
        )

        if os.path.isfile(wdt_path):
            try:
                wdt_data = read_wdt(wdt_path)
                active_coords = wdt_data['active_coords']
                dungeon_mphd_flags = wdt_data['mphd_flags']

                for (x, y) in active_coords:
                    adt_filename = "{}_{:d}_{:d}.adt".format(map_name, x, y)
                    adt_filepath = os.path.join(
                        self.game_data_dir, "World", "Maps", map_name,
                        adt_filename
                    )

                    if not os.path.isfile(adt_filepath):
                        continue

                    try:
                        tile_data = self._export_adt_tile(
                            adt_filepath, dungeon_mphd_flags)
                        tile_rel_path = "tiles/{}_{}".format(x, y)
                        tile_abs_dir = os.path.join(
                            output_dir, tile_rel_path)
                        self._write_tile_images(tile_abs_dir, tile_data)
                        tiles_list.append({
                            "x": x, "y": y, "file": tile_rel_path
                        })
                    except Exception as e:
                        log.warning("Failed to export dungeon tile (%d, %d): %s",
                                    x, y, e)
            except Exception as e:
                log.warning("Failed to read dungeon WDT %s: %s", wdt_path, e)

        # Extract referenced images from MPQ archives (optional)
        if self.wow_root:
            image_paths = self._collect_zone_image_paths(
                output_dir, map_record, tiles_list)
            self._extract_images(output_dir, image_paths, files_dict)

        # Write manifest
        manifest = {
            "format_version": FORMAT_VERSION,
            "type": "dungeon",
            "name": map_name,
            "slug": slug,
            "map_id": map_id,
            "tile_count": len(tiles_list),
            "tiles": tiles_list,
            "files": files_dict,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        manifest_path = os.path.join(output_dir, "manifest.json")
        save_json(manifest_path, manifest)

        log.info("Dungeon export complete: %s", manifest_path)
        return manifest_path

    # ------------------------------------------------------------------
    # DBC export helpers
    # ------------------------------------------------------------------

    def _export_map_record(self, map_id):
        """
        Read Map.dbc and extract the record matching the given map_id.

        Map.dbc has 66 fields (264 bytes per record). The record is
        decoded into a dict with human-readable field names.

        Args:
            map_id: The Map ID to look up (field 0).

        Returns:
            dict: Map record with decoded fields, or None if not found.
        """
        dbc_path = os.path.join(self.dbc_dir, "Map.dbc")
        if not os.path.isfile(dbc_path):
            log.warning("Map.dbc not found: %s", dbc_path)
            return None

        try:
            dbc = DBCInjector(dbc_path)
        except Exception as e:
            log.warning("Failed to read Map.dbc: %s", e)
            return None

        for rec_idx in range(dbc.record_count):
            rec_id = dbc.get_record_field(rec_idx, 0, '<I')
            if rec_id != map_id:
                continue

            directory_offset = dbc.get_record_field(rec_idx, 1, '<I')
            instance_type = dbc.get_record_field(rec_idx, 2, '<I')
            flags = dbc.get_record_field(rec_idx, 3, '<I')
            pvp = dbc.get_record_field(rec_idx, 4, '<I')
            name_offset = dbc.get_record_field(rec_idx, 5, '<I')
            area_table_id = dbc.get_record_field(rec_idx, 22, '<I')
            desc0_offset = dbc.get_record_field(rec_idx, 23, '<I')
            desc1_offset = dbc.get_record_field(rec_idx, 40, '<I')
            loading_screen_id = dbc.get_record_field(rec_idx, 57, '<I')
            minimap_icon_scale = dbc.get_record_field(rec_idx, 58, '<f')
            corpse_map_id = dbc.get_record_field(rec_idx, 59, '<I')
            corpse_x = dbc.get_record_field(rec_idx, 60, '<f')
            corpse_y = dbc.get_record_field(rec_idx, 61, '<f')
            time_of_day_override = dbc.get_record_field(rec_idx, 62, '<i')
            expansion_id = dbc.get_record_field(rec_idx, 63, '<I')
            raid_offset = dbc.get_record_field(rec_idx, 64, '<I')
            max_players = dbc.get_record_field(rec_idx, 65, '<I')

            return {
                "id": map_id,
                "directory": dbc.get_string(directory_offset),
                "instance_type": instance_type,
                "flags": flags,
                "pvp": pvp,
                "name": dbc.get_string(name_offset),
                "area_table_id": area_table_id,
                "description0": dbc.get_string(desc0_offset),
                "description1": dbc.get_string(desc1_offset),
                "loading_screen_id": loading_screen_id,
                "minimap_icon_scale": minimap_icon_scale,
                "corpse_map_id": corpse_map_id,
                "corpse": [corpse_x, corpse_y],
                "time_of_day_override": time_of_day_override,
                "expansion_id": expansion_id,
                "raid_offset": raid_offset,
                "max_players": max_players,
            }

        log.warning("Map ID %d not found in Map.dbc", map_id)
        return None

    def _export_area_records(self, map_id):
        """
        Read AreaTable.dbc and extract all records where ContinentID == map_id.

        AreaTable.dbc has 36 fields (144 bytes per record).

        Args:
            map_id: The Map ID to filter by (ContinentID, field 1).

        Returns:
            dict: Contains "areas" list with decoded area records,
                  or None if the DBC is missing.
        """
        dbc_path = os.path.join(self.dbc_dir, "AreaTable.dbc")
        if not os.path.isfile(dbc_path):
            log.warning("AreaTable.dbc not found: %s", dbc_path)
            return None

        try:
            dbc = DBCInjector(dbc_path)
        except Exception as e:
            log.warning("Failed to read AreaTable.dbc: %s", e)
            return None

        # Build an ID -> name lookup for parent area resolution
        id_to_name = {}
        for rec_idx in range(dbc.record_count):
            rec_id = dbc.get_record_field(rec_idx, 0, '<I')
            name_offset = dbc.get_record_field(rec_idx, 11, '<I')
            id_to_name[rec_id] = dbc.get_string(name_offset)

        areas = []
        for rec_idx in range(dbc.record_count):
            continent_id = dbc.get_record_field(rec_idx, 1, '<I')
            if continent_id != map_id:
                continue

            rec_id = dbc.get_record_field(rec_idx, 0, '<I')
            parent_area_id = dbc.get_record_field(rec_idx, 2, '<I')
            area_bit = dbc.get_record_field(rec_idx, 3, '<I')
            flags = dbc.get_record_field(rec_idx, 4, '<I')
            sound_provider_pref = dbc.get_record_field(rec_idx, 5, '<I')
            sound_provider_pref_uw = dbc.get_record_field(rec_idx, 6, '<I')
            ambience_id = dbc.get_record_field(rec_idx, 7, '<I')
            zone_music = dbc.get_record_field(rec_idx, 8, '<I')
            intro_sound = dbc.get_record_field(rec_idx, 9, '<I')
            exploration_level = dbc.get_record_field(rec_idx, 10, '<I')
            name_offset = dbc.get_record_field(rec_idx, 11, '<I')
            faction_group_mask = dbc.get_record_field(rec_idx, 28, '<I')
            liquid_type_ids = [
                dbc.get_record_field(rec_idx, 29, '<I'),
                dbc.get_record_field(rec_idx, 30, '<I'),
                dbc.get_record_field(rec_idx, 31, '<I'),
                dbc.get_record_field(rec_idx, 32, '<I'),
            ]
            min_elevation = dbc.get_record_field(rec_idx, 33, '<f')
            ambient_multiplier = dbc.get_record_field(rec_idx, 34, '<f')
            light_id = dbc.get_record_field(rec_idx, 35, '<I')

            parent_area_name = id_to_name.get(parent_area_id, "")

            areas.append({
                "original_id": rec_id,
                "continent_id": continent_id,
                "parent_area_id": parent_area_id,
                "parent_area_name": parent_area_name,
                "original_area_bit": area_bit,
                "flags": flags,
                "sound_provider_pref": sound_provider_pref,
                "sound_provider_pref_underwater": sound_provider_pref_uw,
                "ambience_id": ambience_id,
                "zone_music": zone_music,
                "intro_sound": intro_sound,
                "exploration_level": exploration_level,
                "name": dbc.get_string(name_offset),
                "faction_group_mask": faction_group_mask,
                "liquid_type_ids": liquid_type_ids,
                "min_elevation": min_elevation,
                "ambient_multiplier": ambient_multiplier,
                "light_id": light_id,
            })

        log.info("Found %d area records for map_id %d", len(areas), map_id)
        return {"areas": areas}

    def _export_world_map_records(self, map_id):
        """
        Read WorldMapArea.dbc and WorldMapOverlay.dbc for the given map.

        WorldMapArea.dbc has 11 fields (44 bytes per record).
        WorldMapOverlay.dbc has 17 fields (68 bytes per record).

        Args:
            map_id: The Map ID to filter by (field 1 in WorldMapArea).

        Returns:
            dict: Contains "world_map_areas" and "world_map_overlays" lists,
                  or None if the DBC is missing.
        """
        wma_path = os.path.join(self.dbc_dir, "WorldMapArea.dbc")
        if not os.path.isfile(wma_path):
            log.warning("WorldMapArea.dbc not found: %s", wma_path)
            return None

        try:
            wma_dbc = DBCInjector(wma_path)
        except Exception as e:
            log.warning("Failed to read WorldMapArea.dbc: %s", e)
            return None

        # Collect matching WorldMapArea records
        world_map_areas = []
        wma_ids = set()

        for rec_idx in range(wma_dbc.record_count):
            rec_map_id = wma_dbc.get_record_field(rec_idx, 1, '<I')
            if rec_map_id != map_id:
                continue

            rec_id = wma_dbc.get_record_field(rec_idx, 0, '<I')
            area_id = wma_dbc.get_record_field(rec_idx, 2, '<I')
            area_name_offset = wma_dbc.get_record_field(rec_idx, 3, '<I')
            loc_left = wma_dbc.get_record_field(rec_idx, 4, '<f')
            loc_right = wma_dbc.get_record_field(rec_idx, 5, '<f')
            loc_top = wma_dbc.get_record_field(rec_idx, 6, '<f')
            loc_bottom = wma_dbc.get_record_field(rec_idx, 7, '<f')
            display_map_id = wma_dbc.get_record_field(rec_idx, 8, '<i')
            default_dungeon_floor = wma_dbc.get_record_field(rec_idx, 9, '<I')
            parent_worldmap_id = wma_dbc.get_record_field(rec_idx, 10, '<i')

            wma_ids.add(rec_id)
            world_map_areas.append({
                "id": rec_id,
                "map_id": rec_map_id,
                "area_id": area_id,
                "area_name": wma_dbc.get_string(area_name_offset),
                "loc_left": loc_left,
                "loc_right": loc_right,
                "loc_top": loc_top,
                "loc_bottom": loc_bottom,
                "display_map_id": display_map_id,
                "default_dungeon_floor": default_dungeon_floor,
                "parent_worldmap_id": parent_worldmap_id,
            })

        # Read WorldMapOverlay.dbc
        world_map_overlays = []
        wmo_path = os.path.join(self.dbc_dir, "WorldMapOverlay.dbc")
        if os.path.isfile(wmo_path):
            try:
                wmo_dbc = DBCInjector(wmo_path)

                for rec_idx in range(wmo_dbc.record_count):
                    map_area_id = wmo_dbc.get_record_field(rec_idx, 1, '<I')
                    if map_area_id not in wma_ids:
                        continue

                    rec_id = wmo_dbc.get_record_field(rec_idx, 0, '<I')
                    area_ids = [
                        wmo_dbc.get_record_field(rec_idx, 2, '<I'),
                        wmo_dbc.get_record_field(rec_idx, 3, '<I'),
                        wmo_dbc.get_record_field(rec_idx, 4, '<I'),
                        wmo_dbc.get_record_field(rec_idx, 5, '<I'),
                    ]
                    map_point_x = wmo_dbc.get_record_field(rec_idx, 6, '<I')
                    map_point_y = wmo_dbc.get_record_field(rec_idx, 7, '<I')
                    texture_name_offset = wmo_dbc.get_record_field(rec_idx, 8, '<I')
                    texture_width = wmo_dbc.get_record_field(rec_idx, 9, '<I')
                    texture_height = wmo_dbc.get_record_field(rec_idx, 10, '<I')
                    offset_x = wmo_dbc.get_record_field(rec_idx, 11, '<I')
                    offset_y = wmo_dbc.get_record_field(rec_idx, 12, '<I')
                    hit_rect_top = wmo_dbc.get_record_field(rec_idx, 13, '<I')
                    hit_rect_left = wmo_dbc.get_record_field(rec_idx, 14, '<I')
                    hit_rect_bottom = wmo_dbc.get_record_field(rec_idx, 15, '<I')
                    hit_rect_right = wmo_dbc.get_record_field(rec_idx, 16, '<I')

                    world_map_overlays.append({
                        "id": rec_id,
                        "map_area_id": map_area_id,
                        "area_ids": area_ids,
                        "map_point_x": map_point_x,
                        "map_point_y": map_point_y,
                        "texture_name": wmo_dbc.get_string(texture_name_offset),
                        "texture_width": texture_width,
                        "texture_height": texture_height,
                        "offset_x": offset_x,
                        "offset_y": offset_y,
                        "hit_rect_top": hit_rect_top,
                        "hit_rect_left": hit_rect_left,
                        "hit_rect_bottom": hit_rect_bottom,
                        "hit_rect_right": hit_rect_right,
                    })
            except Exception as e:
                log.warning("Failed to read WorldMapOverlay.dbc: %s", e)

        log.info("Found %d world map areas, %d overlays for map_id %d",
                 len(world_map_areas), len(world_map_overlays), map_id)

        return {
            "world_map_areas": world_map_areas,
            "world_map_overlays": world_map_overlays,
        }

    def _export_atmosphere_records(self, map_id):
        """
        Read Light.dbc, ZoneMusic.dbc, and SoundAmbience.dbc for the given map.

        Light.dbc has 15 fields (60 bytes per record).
        ZoneMusic.dbc has 8 fields (32 bytes per record).
        SoundAmbience.dbc has 3 fields (12 bytes per record).

        Args:
            map_id: The Map ID to filter lights by (ContinentID, field 1).

        Returns:
            dict: Contains "lights", "zone_music", and "sound_ambience" lists,
                  or None if Light.dbc is missing.
        """
        # Collect referenced music and ambience IDs from area records
        area_data = self._export_area_records(map_id)
        referenced_music_ids = set()
        referenced_ambience_ids = set()
        if area_data and "areas" in area_data:
            for area in area_data["areas"]:
                if area.get("zone_music"):
                    referenced_music_ids.add(area["zone_music"])
                if area.get("ambience_id"):
                    referenced_ambience_ids.add(area["ambience_id"])

        # Read Light.dbc
        lights = []
        light_path = os.path.join(self.dbc_dir, "Light.dbc")
        if os.path.isfile(light_path):
            try:
                light_dbc = DBCInjector(light_path)

                for rec_idx in range(light_dbc.record_count):
                    continent_id = light_dbc.get_record_field(rec_idx, 1, '<I')
                    if continent_id != map_id:
                        continue

                    rec_id = light_dbc.get_record_field(rec_idx, 0, '<I')
                    game_coords = [
                        light_dbc.get_record_field(rec_idx, 2, '<f'),
                        light_dbc.get_record_field(rec_idx, 3, '<f'),
                        light_dbc.get_record_field(rec_idx, 4, '<f'),
                    ]
                    falloff_start = light_dbc.get_record_field(rec_idx, 5, '<f')
                    falloff_end = light_dbc.get_record_field(rec_idx, 6, '<f')
                    light_params = [
                        light_dbc.get_record_field(rec_idx, 7 + i, '<I')
                        for i in range(8)
                    ]

                    lights.append({
                        "id": rec_id,
                        "continent_id": continent_id,
                        "game_coords": game_coords,
                        "falloff_start": falloff_start,
                        "falloff_end": falloff_end,
                        "light_params_ids": light_params,
                    })
            except Exception as e:
                log.warning("Failed to read Light.dbc: %s", e)
        else:
            log.warning("Light.dbc not found: %s", light_path)

        # Read ZoneMusic.dbc
        zone_music = []
        zm_path = os.path.join(self.dbc_dir, "ZoneMusic.dbc")
        if os.path.isfile(zm_path) and referenced_music_ids:
            try:
                zm_dbc = DBCInjector(zm_path)

                for rec_idx in range(zm_dbc.record_count):
                    rec_id = zm_dbc.get_record_field(rec_idx, 0, '<I')
                    if rec_id not in referenced_music_ids:
                        continue

                    set_name_offset = zm_dbc.get_record_field(rec_idx, 1, '<I')
                    silence_min = [
                        zm_dbc.get_record_field(rec_idx, 2, '<I'),
                        zm_dbc.get_record_field(rec_idx, 3, '<I'),
                    ]
                    silence_max = [
                        zm_dbc.get_record_field(rec_idx, 4, '<I'),
                        zm_dbc.get_record_field(rec_idx, 5, '<I'),
                    ]
                    sounds = [
                        zm_dbc.get_record_field(rec_idx, 6, '<I'),
                        zm_dbc.get_record_field(rec_idx, 7, '<I'),
                    ]

                    zone_music.append({
                        "id": rec_id,
                        "set_name": zm_dbc.get_string(set_name_offset),
                        "silence_interval_min": silence_min,
                        "silence_interval_max": silence_max,
                        "sounds": sounds,
                    })
            except Exception as e:
                log.warning("Failed to read ZoneMusic.dbc: %s", e)

        # Read SoundAmbience.dbc
        sound_ambience = []
        sa_path = os.path.join(self.dbc_dir, "SoundAmbience.dbc")
        if os.path.isfile(sa_path) and referenced_ambience_ids:
            try:
                sa_dbc = DBCInjector(sa_path)

                for rec_idx in range(sa_dbc.record_count):
                    rec_id = sa_dbc.get_record_field(rec_idx, 0, '<I')
                    if rec_id not in referenced_ambience_ids:
                        continue

                    day_ambience = sa_dbc.get_record_field(rec_idx, 1, '<I')
                    night_ambience = sa_dbc.get_record_field(rec_idx, 2, '<I')

                    sound_ambience.append({
                        "id": rec_id,
                        "day_ambience_id": day_ambience,
                        "night_ambience_id": night_ambience,
                    })
            except Exception as e:
                log.warning("Failed to read SoundAmbience.dbc: %s", e)

        log.info("Found %d lights, %d zone music, %d sound ambience for map_id %d",
                 len(lights), len(zone_music), len(sound_ambience), map_id)

        return {
            "lights": lights,
            "zone_music": zone_music,
            "sound_ambience": sound_ambience,
        }

    def _export_dungeon_records(self, map_id):
        """
        Read LFGDungeons.dbc, DungeonEncounter.dbc, LoadingScreens.dbc,
        and AreaTrigger.dbc for the given dungeon map.

        Args:
            map_id: The Map ID to filter by.

        Returns:
            dict: Contains "lfg_dungeon", "encounters", "loading_screen",
                  and "area_triggers" lists, or None on failure.
        """
        result = {
            "lfg_dungeon": [],
            "encounters": [],
            "loading_screen": None,
            "area_triggers": [],
        }

        # Read LFGDungeons.dbc (49 fields, 196 bytes)
        lfg_path = os.path.join(self.dbc_dir, "LFGDungeons.dbc")
        if os.path.isfile(lfg_path):
            try:
                lfg_dbc = DBCInjector(lfg_path)

                for rec_idx in range(lfg_dbc.record_count):
                    lfg_map_id = lfg_dbc.get_record_field(rec_idx, 23, '<I')
                    if lfg_map_id != map_id:
                        continue

                    rec_id = lfg_dbc.get_record_field(rec_idx, 0, '<I')
                    name_offset = lfg_dbc.get_record_field(rec_idx, 1, '<I')
                    min_level = lfg_dbc.get_record_field(rec_idx, 18, '<I')
                    max_level = lfg_dbc.get_record_field(rec_idx, 19, '<I')
                    target_level = lfg_dbc.get_record_field(rec_idx, 20, '<I')
                    min_gear_level = lfg_dbc.get_record_field(rec_idx, 21, '<I')
                    max_gear_level = lfg_dbc.get_record_field(rec_idx, 22, '<I')
                    difficulty = lfg_dbc.get_record_field(rec_idx, 24, '<I')
                    flags = lfg_dbc.get_record_field(rec_idx, 25, '<I')
                    type_id = lfg_dbc.get_record_field(rec_idx, 26, '<I')
                    faction = lfg_dbc.get_record_field(rec_idx, 27, '<I')
                    texture_offset = lfg_dbc.get_record_field(rec_idx, 28, '<I')
                    expansion_level = lfg_dbc.get_record_field(rec_idx, 29, '<I')
                    order_index = lfg_dbc.get_record_field(rec_idx, 30, '<I')
                    group_id = lfg_dbc.get_record_field(rec_idx, 31, '<I')
                    desc_offset = lfg_dbc.get_record_field(rec_idx, 32, '<I')

                    result["lfg_dungeon"].append({
                        "id": rec_id,
                        "name": lfg_dbc.get_string(name_offset),
                        "min_level": min_level,
                        "max_level": max_level,
                        "target_level": target_level,
                        "min_gear_level": min_gear_level,
                        "max_gear_level": max_gear_level,
                        "map_id": lfg_map_id,
                        "difficulty": difficulty,
                        "flags": flags,
                        "type_id": type_id,
                        "faction": faction,
                        "texture_filename": lfg_dbc.get_string(texture_offset),
                        "expansion_level": expansion_level,
                        "order_index": order_index,
                        "group_id": group_id,
                        "description": lfg_dbc.get_string(desc_offset),
                    })
            except Exception as e:
                log.warning("Failed to read LFGDungeons.dbc: %s", e)

        # Read DungeonEncounter.dbc (23 fields, 92 bytes)
        enc_path = os.path.join(self.dbc_dir, "DungeonEncounter.dbc")
        if os.path.isfile(enc_path):
            try:
                enc_dbc = DBCInjector(enc_path)

                for rec_idx in range(enc_dbc.record_count):
                    enc_map_id = enc_dbc.get_record_field(rec_idx, 1, '<I')
                    if enc_map_id != map_id:
                        continue

                    rec_id = enc_dbc.get_record_field(rec_idx, 0, '<I')
                    difficulty = enc_dbc.get_record_field(rec_idx, 2, '<I')
                    order_index = enc_dbc.get_record_field(rec_idx, 3, '<I')
                    bit = enc_dbc.get_record_field(rec_idx, 4, '<I')
                    name_offset = enc_dbc.get_record_field(rec_idx, 5, '<I')
                    spell_icon_id = enc_dbc.get_record_field(rec_idx, 22, '<I')

                    result["encounters"].append({
                        "id": rec_id,
                        "map_id": enc_map_id,
                        "difficulty": difficulty,
                        "order_index": order_index,
                        "bit": bit,
                        "name": enc_dbc.get_string(name_offset),
                        "spell_icon_id": spell_icon_id,
                    })
            except Exception as e:
                log.warning("Failed to read DungeonEncounter.dbc: %s", e)

        # Read LoadingScreens.dbc (4 fields, 16 bytes)
        # Get the loading screen ID from the map record
        map_record = self._export_map_record(map_id)
        if map_record and map_record.get("loading_screen_id"):
            ls_id = map_record["loading_screen_id"]
            ls_path = os.path.join(self.dbc_dir, "LoadingScreens.dbc")
            if os.path.isfile(ls_path):
                try:
                    ls_dbc = DBCInjector(ls_path)

                    for rec_idx in range(ls_dbc.record_count):
                        rec_id = ls_dbc.get_record_field(rec_idx, 0, '<I')
                        if rec_id != ls_id:
                            continue

                        name_offset = ls_dbc.get_record_field(rec_idx, 1, '<I')
                        filename_offset = ls_dbc.get_record_field(rec_idx, 2, '<I')
                        has_widescreen = ls_dbc.get_record_field(rec_idx, 3, '<I')

                        result["loading_screen"] = {
                            "id": rec_id,
                            "name": ls_dbc.get_string(name_offset),
                            "filename": ls_dbc.get_string(filename_offset),
                            "has_widescreen": has_widescreen,
                        }
                        break
                except Exception as e:
                    log.warning("Failed to read LoadingScreens.dbc: %s", e)

        # Read AreaTrigger.dbc (10 fields, 40 bytes)
        at_path = os.path.join(self.dbc_dir, "AreaTrigger.dbc")
        if os.path.isfile(at_path):
            try:
                at_dbc = DBCInjector(at_path)

                for rec_idx in range(at_dbc.record_count):
                    continent_id = at_dbc.get_record_field(rec_idx, 1, '<I')
                    if continent_id != map_id:
                        continue

                    rec_id = at_dbc.get_record_field(rec_idx, 0, '<I')
                    pos_x = at_dbc.get_record_field(rec_idx, 2, '<f')
                    pos_y = at_dbc.get_record_field(rec_idx, 3, '<f')
                    pos_z = at_dbc.get_record_field(rec_idx, 4, '<f')
                    radius = at_dbc.get_record_field(rec_idx, 5, '<f')
                    box_length = at_dbc.get_record_field(rec_idx, 6, '<f')
                    box_width = at_dbc.get_record_field(rec_idx, 7, '<f')
                    box_height = at_dbc.get_record_field(rec_idx, 8, '<f')
                    box_yaw = at_dbc.get_record_field(rec_idx, 9, '<f')

                    result["area_triggers"].append({
                        "id": rec_id,
                        "continent_id": continent_id,
                        "position": [pos_x, pos_y, pos_z],
                        "radius": radius,
                        "box_length": box_length,
                        "box_width": box_width,
                        "box_height": box_height,
                        "box_yaw": box_yaw,
                    })
            except Exception as e:
                log.warning("Failed to read AreaTrigger.dbc: %s", e)

        log.info(
            "Dungeon records for map_id %d: %d lfg, %d encounters, "
            "%d area triggers",
            map_id, len(result["lfg_dungeon"]),
            len(result["encounters"]), len(result["area_triggers"])
        )

        return result

    # ------------------------------------------------------------------
    # Image extraction from MPQ archives
    # ------------------------------------------------------------------

    def _collect_zone_image_paths(self, output_dir, map_record, tiles_list):
        """Collect all referenced BLP paths grouped by category.

        Scans exported tile meta.json files and DBC records to build a
        dict of ``{category: [(mpq_path, local_rel_path), ...]}``.

        Args:
            output_dir: Export output directory.
            map_record: Decoded Map.dbc record dict (or None).
            tiles_list: List of tile dicts with x, y, file keys.

        Returns:
            dict: Mapping of category name to list of (mpq_path, local_path)
                tuples.
        """
        result = {
            "textures": [],
            "loading_screen": [],
            "world_map": [],
            "overlays": [],
            "minimap": [],
        }

        # --- Ground textures from tile meta.json ---
        seen_textures = set()
        for tile_ref in tiles_list:
            meta_path = os.path.join(
                output_dir, tile_ref["file"], "meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                meta = load_json(meta_path)
            except Exception:
                continue
            for tex_path in meta.get("textures", []):
                tex_lower = tex_path.lower()
                if tex_lower in seen_textures:
                    continue
                seen_textures.add(tex_lower)
                # Local path: keep subfolder structure, normalise to forward slash
                tex_rel = tex_path.replace('\\', '/').replace('.blp', '.png')
                local = "images/textures/{}".format(tex_rel)
                result["textures"].append((tex_path, local))

        # --- Loading screen from LoadingScreens.dbc ---
        if map_record and map_record.get("loading_screen_id"):
            ls_id = map_record["loading_screen_id"]
            ls_path = os.path.join(self.dbc_dir, "LoadingScreens.dbc")
            if os.path.isfile(ls_path):
                try:
                    ls_dbc = DBCInjector(ls_path)
                    for rec_idx in range(ls_dbc.record_count):
                        rec_id = ls_dbc.get_record_field(rec_idx, 0, '<I')
                        if rec_id != ls_id:
                            continue
                        fn_offset = ls_dbc.get_record_field(rec_idx, 2, '<I')
                        has_wide = ls_dbc.get_record_field(rec_idx, 3, '<I')
                        blp_path = ls_dbc.get_string(fn_offset)
                        if blp_path:
                            # Normal loading screen
                            mpq_path = blp_path
                            if not mpq_path.lower().endswith('.blp'):
                                mpq_path += '.blp'
                            result["loading_screen"].append(
                                (mpq_path, "images/loading_screen.png"))
                            # Widescreen variant
                            if has_wide:
                                wide_mpq = mpq_path.replace(
                                    '.blp', 'Wide.blp').replace(
                                    '.BLP', 'Wide.BLP')
                                result["loading_screen"].append(
                                    (wide_mpq,
                                     "images/loading_screen_wide.png"))
                        break
                except Exception as e:
                    log.warning("Failed reading LoadingScreens.dbc for "
                                "image paths: %s", e)

        # --- World map tiles from WorldMapArea.dbc ---
        wma_path = os.path.join(self.dbc_dir, "WorldMapArea.dbc")
        if os.path.isfile(wma_path) and map_record:
            try:
                wma_dbc = DBCInjector(wma_path)
                map_id = map_record["id"]
                for rec_idx in range(wma_dbc.record_count):
                    rec_map_id = wma_dbc.get_record_field(rec_idx, 1, '<I')
                    if rec_map_id != map_id:
                        continue
                    name_offset = wma_dbc.get_record_field(rec_idx, 3, '<I')
                    area_name = wma_dbc.get_string(name_offset)
                    if not area_name:
                        continue
                    # World map tiles follow convention: {Name}{1-12}.blp
                    for i in range(1, 13):
                        mpq_path = "Interface\\WorldMap\\{}\\{}{}.blp".format(
                            area_name, area_name, i)
                        local = "images/world_map/{}.png".format(i)
                        result["world_map"].append((mpq_path, local))
            except Exception as e:
                log.warning("Failed reading WorldMapArea.dbc for image "
                            "paths: %s", e)

        # --- World map overlays from world_map.json ---
        wm_json_path = os.path.join(output_dir, "world_map.json")
        if os.path.isfile(wm_json_path):
            try:
                wm_data = load_json(wm_json_path)
                for overlay in wm_data.get("world_map_overlays", []):
                    tex_name = overlay.get("texture_name", "")
                    if not tex_name:
                        continue
                    mpq_path = tex_name
                    if not mpq_path.lower().endswith('.blp'):
                        mpq_path += '.blp'
                    # Use last path component as local filename
                    base = tex_name.replace('\\', '/').split('/')[-1]
                    base = base.replace('.blp', '').replace('.BLP', '')
                    local = "images/overlays/{}.png".format(base)
                    result["overlays"].append((mpq_path, local))
            except Exception as e:
                log.warning("Failed reading world_map.json for overlay "
                            "image paths: %s", e)

        # --- Minimap tiles from md5translate.trs ---
        if map_record:
            map_dir_name = map_record.get("directory", "")
            if map_dir_name:
                self._collect_minimap_paths(
                    result, map_dir_name, tiles_list)

        return result

    def _collect_minimap_paths(self, result, map_dir_name, tiles_list):
        """Parse md5translate.trs from MPQ and collect minimap tile paths.

        Args:
            result: Image paths dict to append minimap entries to.
            map_dir_name: Map directory name (e.g. "PVPZone05").
            tiles_list: List of active tile dicts with x, y keys.
        """
        if not self.wow_root:
            return

        try:
            chain = MPQChain(self.wow_root)
        except Exception as e:
            log.warning("Failed to open MPQ chain for minimap lookup: %s", e)
            return

        try:
            trs_data = chain.read_file("textures\\Minimap\\md5translate.trs")
            if not trs_data:
                log.debug("md5translate.trs not found in MPQ archives")
                return

            # Build set of active tile coords for quick lookup
            active_coords = set()
            for tile_ref in tiles_list:
                active_coords.add((tile_ref["x"], tile_ref["y"]))

            # Parse TRS: each line is "MapDir\mapXX_YY.blp\thash.blp"
            # Also contains "dir: MapDir" lines which we skip.
            trs_text = trs_data.decode('utf-8', errors='replace')
            map_prefix = "{}\\".format(map_dir_name).lower()

            for line in trs_text.splitlines():
                line = line.strip()
                if not line or line.startswith('dir:'):
                    continue
                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                entry_path = parts[0].strip()
                hash_filename = parts[1].strip()

                if not entry_path.lower().startswith(map_prefix):
                    continue

                # Extract coords from filename like "map25_23.blp"
                filename = entry_path.split('\\')[-1]
                name_lower = filename.lower()
                if not name_lower.startswith('map') or not name_lower.endswith('.blp'):
                    continue
                coord_part = name_lower[3:-4]  # strip "map" and ".blp"
                if '_' not in coord_part:
                    continue
                try:
                    cx_str, cy_str = coord_part.split('_', 1)
                    cx, cy = int(cx_str), int(cy_str)
                except (ValueError, IndexError):
                    continue

                if (cx, cy) not in active_coords:
                    continue

                # hash_filename is already like "abc123.blp"
                mpq_path = "textures\\Minimap\\{}".format(hash_filename)
                local = "images/minimap/{}_{}.png".format(cx, cy)
                result["minimap"].append((mpq_path, local))
        finally:
            chain.close()

    def _extract_images(self, output_dir, image_paths, files_dict):
        """Extract BLP images from MPQ archives and convert to PNG.

        Args:
            output_dir: Export output directory.
            image_paths: Dict from _collect_zone_image_paths().
            files_dict: Manifest files dict to update with image references.
        """
        # Count total images to extract
        total = sum(len(paths) for paths in image_paths.values())
        if total == 0:
            log.info("No image paths collected, skipping extraction")
            return

        log.info("Extracting %d images from MPQ archives...", total)

        try:
            chain = MPQChain(self.wow_root)
        except Exception as e:
            log.warning("Failed to open MPQ chain for image extraction: %s",
                        e)
            return

        images_manifest = {}
        extracted = 0
        missing = 0

        try:
            for category, paths in image_paths.items():
                if not paths:
                    continue

                category_files = []
                for mpq_path, local_path in paths:
                    blp_data = chain.read_file(mpq_path)
                    if blp_data is None:
                        log.debug("Image not found in MPQ: %s", mpq_path)
                        missing += 1
                        continue

                    out_path = os.path.join(output_dir, local_path)
                    try:
                        # Loading screens are stored as square BLP
                        # textures but displayed at 4:3 (normal) or
                        # 16:10 (widescreen).  The game maps the
                        # texture width to screen width and scales
                        # height down to the correct aspect ratio.
                        display_size = None
                        if category == "loading_screen":
                            blp_w = struct.unpack_from('<I', blp_data, 12)[0]
                            is_wide = "wide" in local_path.lower()
                            if is_wide:
                                display_size = (blp_w, blp_w * 10 // 16)
                            else:
                                display_size = (blp_w, blp_w * 3 // 4)
                        blp_to_png(blp_data, out_path,
                                   display_size=display_size)
                        category_files.append(local_path)
                        extracted += 1
                    except Exception as e:
                        log.warning("Failed to convert %s: %s", mpq_path, e)
                        missing += 1

                # Build manifest entry per category
                if category_files:
                    if category == "loading_screen":
                        # Loading screens are individual named files
                        for f in category_files:
                            if "wide" in f:
                                images_manifest["loading_screen_wide"] = f
                            else:
                                images_manifest["loading_screen"] = f
                    else:
                        images_manifest[category] = category_files
        finally:
            chain.close()

        if images_manifest:
            files_dict["images"] = images_manifest

        log.info("Image extraction complete: %d extracted, %d missing",
                 extracted, missing)

    # ------------------------------------------------------------------
    # ADT tile export
    # ------------------------------------------------------------------

    def _export_adt_tile(self, adt_filepath, mphd_flags=0):
        """
        Export a single ADT tile to a JSON-serializable dict.

        Uses both read_adt() for tile-level data and ADTFile for full
        per-chunk detail (145-float heightmaps, normals, texture layers,
        shadow maps, vertex colors).

        Args:
            adt_filepath: Path to the ADT binary file.
            mphd_flags: MPHD flags from the WDT. Bit 0x4 indicates
                highres alpha maps.

        Returns:
            dict: Complete tile data including chunks with full fidelity.
        """
        # Derive highres from WDT MPHD flags (bit 0x4)
        highres = bool(mphd_flags & 0x4)

        # Get tile-level data from read_adt
        adt_data = read_adt(adt_filepath, highres=highres)

        # Also load ADTFile for per-chunk detail
        adt_file = None
        if ADTFile is not None:
            try:
                adt_file = ADTFile(filepath=adt_filepath, highres=highres)
            except Exception as e:
                log.warning("Failed to load ADTFile for %s: %s",
                            adt_filepath, e)

        tile = {
            "tile_x": adt_data['tile_x'],
            "tile_y": adt_data['tile_y'],
            "textures": adt_data['texture_paths'],
            "m2_models": adt_data['m2_filenames'],
            "wmo_models": adt_data['wmo_filenames'],
            "doodad_placements": [],
            "wmo_placements": [],
            "chunks": [],
        }

        # Convert doodad instances - remap name_id to model_index
        for inst in adt_data['doodad_instances']:
            tile["doodad_placements"].append({
                "model_index": inst['name_id'],
                "unique_id": inst['unique_id'],
                "position": list(inst['position']),
                "rotation": list(inst['rotation']),
                "scale": inst['scale'],
                "flags": inst['flags'],
            })

        # Convert WMO instances
        for inst in adt_data['wmo_instances']:
            tile["wmo_placements"].append({
                "model_index": inst['name_id'],
                "unique_id": inst['unique_id'],
                "position": list(inst['position']),
                "rotation": list(inst['rotation']),
                "extents_min": list(inst['extents_min']),
                "extents_max": list(inst['extents_max']),
                "flags": inst['flags'],
                "doodad_set": inst['doodad_set'],
                "name_set": inst['name_set'],
                "scale": inst['scale'],
            })

        # Export per-chunk data
        for row in range(16):
            for col in range(16):
                chunk_meta = adt_data['chunks'][row][col]

                # Full 145-float heightmap and normals from ADTFile
                heightmap_145 = [0.0] * 145
                normals = [[0, 0, 127]] * 145
                texture_layers = []
                shadow_map = None
                vertex_colors = None

                if adt_file is not None:
                    try:
                        mcnk = adt_file.mcnk[row][col]

                        # Full 145-float heightmap from MCVT
                        heightmap_145 = list(mcnk.mcvt.height)

                        # Normals from MCNR - 145 tuples of (x, y, z) int8
                        try:
                            normals = [list(n) for n in mcnk.mcnr.normals]
                        except (AttributeError, TypeError, IndexError):
                            normals = [[0, 0, 127]] * 145

                        # Texture layers from MCLY + alpha maps from MCAL
                        for layer_idx in range(mcnk.n_layers):
                            layer_data = {
                                "texture_index": 0,
                                "flags": 0,
                                "effect_id": 0,
                                "alpha_map": None,
                            }

                            if layer_idx < len(mcnk.mcly.layers):
                                layer_data["texture_index"] = mcnk.mcly.layers[layer_idx].texture_id
                                layer_data["flags"] = mcnk.mcly.layers[layer_idx].flags
                                layer_data["effect_id"] = mcnk.mcly.layers[layer_idx].effect_id

                            # Alpha map: layer 0 has none, layers 1+ have 64x64
                            if layer_idx > 0 and layer_idx - 1 < len(mcnk.mcal.layers):
                                alpha = mcnk.mcal.layers[layer_idx - 1].alpha_map
                                if alpha:
                                    layer_data["alpha_map"] = [
                                        list(alpha_row) for alpha_row in alpha
                                    ]

                            texture_layers.append(layer_data)

                        # Shadow map from MCSH (64x64 bitmap, optional)
                        try:
                            if (hasattr(mcnk, 'mcsh') and mcnk.mcsh
                                    and hasattr(mcnk.mcsh, 'shadow_map')):
                                sm = mcnk.mcsh.shadow_map
                                if sm:
                                    shadow_map = [list(sr) for sr in sm]
                        except (AttributeError, TypeError):
                            shadow_map = None

                        # Vertex colors from MCCV (optional, 145 RGBA tuples)
                        try:
                            if (hasattr(mcnk, 'mccv') and mcnk.mccv
                                    and hasattr(mcnk.mccv, 'colors')):
                                colors = mcnk.mccv.colors
                                if colors:
                                    vertex_colors = [list(c) for c in colors]
                        except (AttributeError, TypeError):
                            vertex_colors = None

                    except Exception as e:
                        log.warning(
                            "Failed to read ADTFile chunk (%d, %d): %s",
                            row, col, e
                        )

                chunk = {
                    "index_x": chunk_meta.get('index_x', col),
                    "index_y": chunk_meta.get('index_y', row),
                    "flags": chunk_meta.get('flags', 0),
                    "area_id": chunk_meta.get('area_id', 0),
                    "holes": chunk_meta.get('holes_low_res', 0),
                    "position": list(chunk_meta.get('position', (0.0, 0.0, 0.0))),
                    "heightmap": heightmap_145,
                    "normals": normals,
                    "texture_layers": texture_layers,
                    "shadow_map": shadow_map,
                    "vertex_colors": vertex_colors,
                    "sound_emitters": [],
                }
                tile["chunks"].append(chunk)

        return tile

    # ------------------------------------------------------------------
    # Image tile export
    # ------------------------------------------------------------------

    def _write_tile_images(self, tile_dir, tile_data):
        """
        Write tile data as a directory of PNG images + meta.json.

        Uses TileImageWriter to convert heavy per-chunk arrays into
        compact PNG files.

        Args:
            tile_dir: Directory to write PNG files and meta.json into.
            tile_data: Dict returned by _export_adt_tile().
        """
        writer = TileImageWriter(tile_dir)
        chunks = tile_data.get('chunks', [])

        # Write images
        hm_file, height_min, height_scale = writer.write_heightmap(chunks)
        shadow_file = writer.write_shadow_map(chunks)
        alpha_results = writer.write_alpha_maps(chunks)
        normals_file = writer.write_normals(chunks)
        vc_file = writer.write_vertex_colors(chunks)

        # Build images manifest
        images = {}
        if hm_file:
            images['heightmap'] = hm_file
        if shadow_file:
            images['shadow'] = shadow_file
        if normals_file:
            images['normals'] = normals_file
        if vc_file:
            images['vertex_colors'] = vc_file
        if alpha_results:
            images['alpha_maps'] = [
                {'layer_index': li, 'file': fn}
                for li, fn in alpha_results
            ]

        # Build chunk metadata (small: flags, area_id, texture_layers, etc.)
        chunk_metas = []
        for chunk in chunks:
            cm = {
                'index_x': chunk.get('index_x', 0),
                'index_y': chunk.get('index_y', 0),
                'flags': chunk.get('flags', 0),
                'area_id': chunk.get('area_id', 0),
                'holes': chunk.get('holes', 0),
                'position': chunk.get('position', [0.0, 0.0, 0.0]),
                'texture_layers': [],
            }
            for layer in chunk.get('texture_layers', []):
                cm['texture_layers'].append({
                    'texture_index': layer.get('texture_index', 0),
                    'flags': layer.get('flags', 0),
                    'effect_id': layer.get('effect_id', 0),
                })
            chunk_metas.append(cm)

        # Write meta.json
        meta = {
            'tile_x': tile_data.get('tile_x', 0),
            'tile_y': tile_data.get('tile_y', 0),
            'textures': tile_data.get('textures', []),
            'm2_models': tile_data.get('m2_models', []),
            'wmo_models': tile_data.get('wmo_models', []),
            'doodad_placements': tile_data.get('doodad_placements', []),
            'wmo_placements': tile_data.get('wmo_placements', []),
            'images': images,
            'chunks': chunk_metas,
        }
        if hm_file:
            meta['height_min'] = height_min
            meta['height_scale'] = height_scale

        save_json(os.path.join(tile_dir, "meta.json"), meta)

    # ------------------------------------------------------------------
    # WMO export helper
    # ------------------------------------------------------------------

    def _export_wmo_data(self, output_dir, dungeon_def, files_dict):
        """
        Export WMO dungeon data as glTF 2.0 binary (.glb) + sidecar JSON.

        Writes geometry (vertices, triangles, normals, UVs, face materials)
        into a single .glb file per WMO set.  WoW-specific metadata
        (portals, lights, doodads, per-group bounds/center/mogp_flags)
        goes into a sidecar .json file.

        Args:
            output_dir: Base output directory for the dungeon export.
            dungeon_def: Dict returned by read_dungeon().
            files_dict: Files dict to update with WMO file references.
        """
        wmo_name = dungeon_def['name']

        # --- Write .glb geometry ---
        glb_rel = "wmo/{}.glb".format(wmo_name)
        glb_path = os.path.join(output_dir, glb_rel)

        writer = WMOGltfWriter(glb_path)
        writer.write(dungeon_def['materials'], dungeon_def.get('rooms', []))

        # --- Write sidecar .json metadata ---
        groups_meta = []
        for idx, room in enumerate(dungeon_def.get('rooms', [])):
            groups_meta.append({
                "group_index": idx,
                "name": room.get('name', 'Group_{:03d}'.format(idx)),
                "bounds": room.get('bounds', {}),
                "center": room.get('center', [0, 0, 0]),
                "mogp_flags": room.get('mogp_flags', 0),
            })

        sidecar_data = {
            "name": wmo_name,
            "materials": dungeon_def['materials'],
            "portals": dungeon_def['portals'],
            "lights": dungeon_def['lights'],
            "doodads": dungeon_def['doodads'],
            "groups": groups_meta,
        }

        meta_rel = "wmo/{}.json".format(wmo_name)
        meta_path = os.path.join(output_dir, meta_rel)
        save_json(meta_path, sidecar_data)

        # Initialise wmo_sets list in files_dict if needed
        if "wmo_sets" not in files_dict:
            files_dict["wmo_sets"] = []

        files_dict["wmo_sets"].append({
            "name": wmo_name,
            "geometry": glb_rel,
            "metadata": meta_rel,
        })

        log.info("Exported WMO '%s': .glb + sidecar .json (%d groups)",
                 wmo_name, len(groups_meta))


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def export_zone(game_data_dir, dbc_dir, map_name, map_id,
                output_base="exports", wow_root=None):
    """
    Export a zone from binary game files to intermediate format.

    Convenience wrapper around ZoneExporter.export_zone().

    Args:
        game_data_dir: Root of extracted game files.
        dbc_dir: Path to DBFilesClient directory.
        map_name: Internal map directory name.
        map_id: Numeric map ID.
        output_base: Base directory for exports.
        wow_root: Optional WoW installation root for image extraction.

    Returns:
        str: Path to the generated manifest.json, or None on failure.
    """
    exporter = ZoneExporter(game_data_dir, dbc_dir, output_base,
                            wow_root=wow_root)
    return exporter.export_zone(map_name, map_id)


def export_dungeon(game_data_dir, dbc_dir, map_name, map_id,
                   wmo_path=None, wmo_paths=None, output_base="exports",
                   wow_root=None):
    """
    Export a dungeon from binary game files to intermediate format.

    Convenience wrapper around ZoneExporter.export_dungeon().

    Args:
        game_data_dir: Root of extracted game files.
        dbc_dir: Path to DBFilesClient directory.
        map_name: Internal map directory name.
        map_id: Numeric map ID.
        wmo_path: Optional path to a single WMO root file.
        wmo_paths: Optional list of paths to multiple WMO root files.
        output_base: Base directory for exports.
        wow_root: Optional WoW installation root for image extraction.

    Returns:
        str: Path to the generated manifest.json, or None on failure.
    """
    exporter = ZoneExporter(game_data_dir, dbc_dir, output_base,
                            wow_root=wow_root)
    return exporter.export_dungeon(map_name, map_id, wmo_path, wmo_paths)
