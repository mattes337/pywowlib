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
        wmo/root.json
        wmo/group_NNN.json
        tiles/{x}_{y}.json   (if terrain exists)

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
from .intermediate_format import slugify, save_json, FORMAT_VERSION

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

    def __init__(self, game_data_dir, dbc_dir, output_base="exports"):
        """
        Initialize the zone exporter.

        Args:
            game_data_dir: Root of extracted game files (contains World/Maps/...).
            dbc_dir: Path to DBFilesClient directory containing DBC files.
            output_base: Base directory for exports (e.g. "exports").
        """
        self.game_data_dir = game_data_dir
        self.dbc_dir = dbc_dir
        self.output_base = output_base

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

            tile_rel_path = "tiles/{}_{}.json".format(x, y)
            tile_abs_path = os.path.join(output_dir, tile_rel_path)

            try:
                tile_data = self._export_adt_tile(adt_filepath)
                save_json(tile_abs_path, tile_data)
                tiles_list.append({"x": x, "y": y, "file": tile_rel_path})
                log.info("Exported tile (%d, %d)", x, y)
            except Exception as e:
                log.warning("Failed to export tile (%d, %d): %s", x, y, e)

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

    def export_dungeon(self, map_name, map_id, wmo_path=None):
        """
        Export a complete dungeon from binary game files to intermediate JSON.

        Reads DBC metadata, optionally reads WMO geometry, and exports
        any terrain tiles if a WDT exists for this dungeon map.

        Args:
            map_name: Internal map directory name (e.g. "TheDeadmines").
            map_id: Numeric map ID matching Map.dbc.
            wmo_path: Optional path to the WMO root file. If provided,
                      dungeon geometry is exported from the WMO.

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

        # Export WMO geometry if path provided
        if wmo_path and os.path.isfile(wmo_path):
            try:
                dungeon_def = read_dungeon(wmo_path)
                self._export_wmo_data(output_dir, dungeon_def, files_dict)
                log.info("Exported WMO geometry from: %s", wmo_path)
            except Exception as e:
                log.warning("Failed to read WMO %s: %s", wmo_path, e)
        elif wmo_path:
            log.warning("WMO file not found: %s", wmo_path)

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

                for (x, y) in active_coords:
                    adt_filename = "{}_{:d}_{:d}.adt".format(map_name, x, y)
                    adt_filepath = os.path.join(
                        self.game_data_dir, "World", "Maps", map_name,
                        adt_filename
                    )

                    if not os.path.isfile(adt_filepath):
                        continue

                    tile_rel_path = "tiles/{}_{}.json".format(x, y)
                    tile_abs_path = os.path.join(output_dir, tile_rel_path)

                    try:
                        tile_data = self._export_adt_tile(adt_filepath)
                        save_json(tile_abs_path, tile_data)
                        tiles_list.append({
                            "x": x, "y": y, "file": tile_rel_path
                        })
                    except Exception as e:
                        log.warning("Failed to export dungeon tile (%d, %d): %s",
                                    x, y, e)
            except Exception as e:
                log.warning("Failed to read dungeon WDT %s: %s", wdt_path, e)

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
    # ADT tile export
    # ------------------------------------------------------------------

    def _export_adt_tile(self, adt_filepath):
        """
        Export a single ADT tile to a JSON-serializable dict.

        Uses both read_adt() for tile-level data and ADTFile for full
        per-chunk detail (145-float heightmaps, normals, texture layers,
        shadow maps, vertex colors).

        Args:
            adt_filepath: Path to the ADT binary file.

        Returns:
            dict: Complete tile data including chunks with full fidelity.
        """
        # Get tile-level data from read_adt
        adt_data = read_adt(adt_filepath)

        # Also load ADTFile for per-chunk detail
        adt_file = None
        if ADTFile is not None:
            try:
                adt_file = ADTFile(filepath=adt_filepath, highres=True)
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

                        # Normals from MCNR - 145 triplets of int8
                        normals = []
                        try:
                            raw_normals = mcnk.mcnr.normals
                            for i in range(145):
                                normals.append([
                                    raw_normals[i * 3],
                                    raw_normals[i * 3 + 1],
                                    raw_normals[i * 3 + 2],
                                ])
                        except (AttributeError, TypeError):
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
    # WMO export helper
    # ------------------------------------------------------------------

    def _export_wmo_data(self, output_dir, dungeon_def, files_dict):
        """
        Export WMO dungeon data to root.json and group_NNN.json files.

        Splits the dungeon definition returned by read_dungeon() into
        a root JSON file and one JSON file per room group.

        Args:
            output_dir: Base output directory for the dungeon export.
            dungeon_def: Dict returned by read_dungeon().
            files_dict: Files dict to update with WMO file references.
        """
        # Write root.json
        root_data = {
            "name": dungeon_def['name'],
            "materials": dungeon_def['materials'],
            "portals": dungeon_def['portals'],
            "lights": dungeon_def['lights'],
            "doodads": dungeon_def['doodads'],
        }
        root_path = os.path.join(output_dir, "wmo", "root.json")
        save_json(root_path, root_data)
        files_dict["wmo_root"] = "wmo/root.json"

        # Write one group file per room
        group_files = []
        for idx, room in enumerate(dungeon_def.get('rooms', [])):
            group_data = {
                "group_index": idx,
                "type": room.get('type', 'raw_mesh'),
                "name": room.get('name', 'Group_{:03d}'.format(idx)),
                "vertices": room.get('vertices', []),
                "triangles": room.get('triangles', []),
                "normals": room.get('normals', []),
                "uvs": room.get('uvs', []),
                "face_materials": room.get('face_materials', []),
                "bounds": room.get('bounds', {}),
                "center": room.get('center', [0, 0, 0]),
            }

            group_filename = "wmo/group_{:03d}.json".format(idx)
            group_path = os.path.join(output_dir, group_filename)
            save_json(group_path, group_data)
            group_files.append(group_filename)

        files_dict["wmo_groups"] = group_files

        log.info("Exported WMO: root + %d group files", len(group_files))


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def export_zone(game_data_dir, dbc_dir, map_name, map_id, output_base="exports"):
    """
    Export a zone from binary game files to intermediate JSON format.

    Convenience wrapper around ZoneExporter.export_zone().

    Args:
        game_data_dir: Root of extracted game files.
        dbc_dir: Path to DBFilesClient directory.
        map_name: Internal map directory name.
        map_id: Numeric map ID.
        output_base: Base directory for exports.

    Returns:
        str: Path to the generated manifest.json, or None on failure.
    """
    exporter = ZoneExporter(game_data_dir, dbc_dir, output_base)
    return exporter.export_zone(map_name, map_id)


def export_dungeon(game_data_dir, dbc_dir, map_name, map_id,
                   wmo_path=None, output_base="exports"):
    """
    Export a dungeon from binary game files to intermediate JSON format.

    Convenience wrapper around ZoneExporter.export_dungeon().

    Args:
        game_data_dir: Root of extracted game files.
        dbc_dir: Path to DBFilesClient directory.
        map_name: Internal map directory name.
        map_id: Numeric map ID.
        wmo_path: Optional path to WMO root file.
        output_base: Base directory for exports.

    Returns:
        str: Path to the generated manifest.json, or None on failure.
    """
    exporter = ZoneExporter(game_data_dir, dbc_dir, output_base)
    return exporter.export_dungeon(map_name, map_id, wmo_path)
