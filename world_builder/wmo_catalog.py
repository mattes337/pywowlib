"""
WMO Catalog - Semantic building name to WMO file path resolver.

Maps high-level building types (inn, blacksmith, farm, ...) and
architectural styles (human_elwynn, human_duskwood, ...) to verified
WMO file paths that exist in the WoW 3.3.5a client.

Each WMO entry includes a footprint (width, depth) in yards used for
terrain flattening under the building.

Usage:
    from world_builder.wmo_catalog import WMOCatalog

    catalog = WMOCatalog()
    wmo_path, footprint = catalog.resolve('inn', 'human_elwynn')
    resolved = catalog.resolve_all(buildings_list, 'human_elwynn')
"""

import logging
import random

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalog data: STYLE -> TYPE -> [(wmo_path, (width, depth)), ...]
#
# Paths verified against the 3.3.5a listfile.  Footprints are approximate
# bounding-box dimensions in yards.
# ---------------------------------------------------------------------------

WMO_CATALOG = {
    # -----------------------------------------------------------------
    # human_elwynn  (Goldshire / Elwynn Forest style)
    # All paths verified against 3.3.5a client listfile
    # -----------------------------------------------------------------
    'human_elwynn': {
        'inn': [
            ('World\\wmo\\Azeroth\\Buildings\\GoldshireInn\\GoldshireInn.wmo', (30, 25)),
        ],
        'blacksmith': [
            ('World\\wmo\\Azeroth\\Buildings\\GoldshireBlacksmith\\goldshireblacksmith.wmo', (25, 20)),
        ],
        'farm': [
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_human_farm\\Duskwood_human_farm.wmo', (20, 15)),
        ],
        'guard_tower': [
            ('World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower.wmo', (10, 10)),
            ('World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower_intact.wmo', (10, 10)),
        ],
        'house': [
            ('World\\wmo\\Azeroth\\Buildings\\HumanTwoStory\\HumanTwoStory.wmo', (18, 15)),
        ],
        'church': [
            ('World\\wmo\\Azeroth\\Buildings\\Chapel\\Chapel.wmo', (25, 35)),
        ],
        'stable': [
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Stable\\Duskwood_Stable.wmo', (20, 25)),
        ],
        'townhall': [
            ('World\\wmo\\Azeroth\\Buildings\\TownHall\\TownHall.wmo', (30, 30)),
            ('World\\wmo\\Azeroth\\Buildings\\TownHall_NoWall\\TownHall_NoWall.wmo', (28, 28)),
        ],
        'barracks': [
            ('World\\wmo\\Azeroth\\Buildings\\Human_Barracks\\Human_Barracks.wmo', (30, 20)),
        ],
        'lumber_mill': [
            ('World\\wmo\\Azeroth\\Buildings\\LumberMill\\lumbermill.wmo', (25, 20)),
        ],
        'shop': [
            ('World\\wmo\\Azeroth\\Buildings\\HumanTwoStory\\HumanTwoStory_closed.wmo', (18, 15)),
        ],
        'warehouse': [
            ('World\\wmo\\Azeroth\\Buildings\\Human_Barn_Silo\\barn.wmo', (20, 25)),
        ],
    },
    # -----------------------------------------------------------------
    # human_duskwood  (Duskwood / abandoned style)
    # -----------------------------------------------------------------
    'human_duskwood': {
        'inn': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_Inn\\DuskwoodAbandoned_Inn.wmo', (25, 20)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Inn\\Duskwood_Inn.wmo', (25, 20)),
        ],
        'farm': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_human_farm\\DuskwoodAbandoned_human_farm.wmo', (20, 15)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Human_Farm_Burnt\\DuskwoodFarmHouseburnt.wmo', (20, 15)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_human_farm\\Duskwood_human_farm.wmo', (20, 15)),
        ],
        'blacksmith': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_Blacksmith\\DuskwoodAbandoned_Blacksmith.wmo', (25, 20)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Blacksmith\\Duskwood_Blacksmith.wmo', (25, 20)),
        ],
        'guard_tower': [
            ('World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower_destroyed.wmo', (10, 10)),
            ('World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower_damaged.wmo', (10, 10)),
        ],
        'house': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_HumanTwoStory\\DuskwoodAbandoned_HumanTwoStory.wmo', (18, 15)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_HumanTwoStory\\Duskwood_HumanTwoStory.wmo', (18, 15)),
        ],
        'stable': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_Barn\\DuskwoodAbandoned_Barn.wmo', (20, 25)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Barn\\Duskwood_Barn.wmo', (20, 25)),
        ],
        'townhall': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_TownHall_NoWall\\DuskwoodAbandoned_TownHall_NoWall.wmo', (28, 28)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_TownHall\\Duskwood_TownHall.wmo', (30, 30)),
        ],
        'barracks': [
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Barracks\\duskwood_barracks.wmo', (30, 20)),
        ],
        'lumber_mill': [
            ('World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_Lumbermill\\DuskwoodAbandoned_lumbermill.wmo', (25, 20)),
            ('World\\wmo\\Azeroth\\Buildings\\Duskwood_Lumbermill\\Duskwood_lumbermill.wmo', (25, 20)),
        ],
        'church': [
            ('World\\wmo\\Azeroth\\Buildings\\Chapel\\DuskwoodChapel.wmo', (25, 35)),
        ],
    },
    # -----------------------------------------------------------------
    # human_westfall  (Westfall / Moonbrook style)
    # -----------------------------------------------------------------
    'human_westfall': {
        'inn': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_Inn\\Westfall_Inn.wmo', (25, 20)),
            ('World\\wmo\\Azeroth\\Buildings\\Moonbrook_Inn\\Moonbrook_Inn.wmo', (25, 20)),
        ],
        'farm': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_human_farm\\Westfall_human_farm.wmo', (20, 15)),
            ('World\\wmo\\Azeroth\\Buildings\\Moonbrook_human_farm\\Moonbrook_human_farm.wmo', (20, 15)),
        ],
        'blacksmith': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_Blacksmith\\Westfall_Blacksmith.wmo', (25, 20)),
            ('World\\wmo\\Azeroth\\Buildings\\Moonbrook_Blacksmith\\Moonbrook_Blacksmith.wmo', (25, 20)),
        ],
        'guard_tower': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_GuardTower\\Westfall_GuardTower.wmo', (10, 10)),
        ],
        'house': [
            ('World\\wmo\\Azeroth\\Buildings\\Moonbrook_HumanTwoStory\\Moonbrook_HumanTwoStory.wmo', (18, 15)),
        ],
        'barracks': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_Barracks\\westfall_barracks.wmo', (30, 20)),
        ],
        'lumber_mill': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_Lumbermill\\Westfall_lumbermill.wmo', (25, 20)),
        ],
        'townhall': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_TownHall\\Westfall_TownHall.wmo', (30, 30)),
        ],
        'stable': [
            ('World\\wmo\\Azeroth\\Buildings\\Westfall_Barn\\Westfall_Barn.wmo', (20, 25)),
        ],
    },
    # -----------------------------------------------------------------
    # human_redridge  (Redridge style)
    # -----------------------------------------------------------------
    'human_redridge': {
        'inn': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_Inn\\RedRidge_Inn.wmo', (25, 20)),
        ],
        'farm': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_human_farm\\RedRidge_human_farm.wmo', (20, 15)),
        ],
        'blacksmith': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_Blacksmith\\RedRidge_Blacksmith.wmo', (25, 20)),
        ],
        'barracks': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_Barracks\\redridge_barracks.wmo', (30, 20)),
        ],
        'townhall': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_TownHall\\RedRidge_TownHall.wmo', (30, 30)),
        ],
        'church': [
            ('World\\wmo\\Azeroth\\Buildings\\Chapel\\RedridgeChapel.wmo', (25, 35)),
        ],
        'stable': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_Barn\\RedRidge_Barn.wmo', (20, 25)),
        ],
        'lumber_mill': [
            ('World\\wmo\\Azeroth\\Buildings\\RedRidge_Lumbermill\\RedRidge_lumbermill.wmo', (25, 20)),
        ],
    },
    # -----------------------------------------------------------------
    # night_elf
    # -----------------------------------------------------------------
    'night_elf': {
        'house': [
            ('World\\wmo\\Kalimdor\\Buildings\\NightElf2Story\\NightElf2Story.wmo', (18, 15)),
        ],
        'guard_tower': [
            ('World\\wmo\\Kalimdor\\Buildings\\NightElfGuardTower\\NightElfGuardTower.wmo', (8, 8)),
        ],
        'church': [
            ('World\\wmo\\Kalimdor\\Buildings\\NightElfAbbey\\NightElfAbbey.wmo', (25, 30)),
        ],
        'inn': [
            ('World\\wmo\\Kalimdor\\Buildings\\NightElf2Story\\NightElf2Story.wmo', (18, 15)),
        ],
    },
    # -----------------------------------------------------------------
    # orc
    # -----------------------------------------------------------------
    'orc': {
        'barracks': [
            ('World\\wmo\\Kalimdor\\Buildings\\OrcBarracks\\OrcBarracks.wmo', (30, 20)),
        ],
        'guard_tower': [
            ('World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower.wmo', (10, 10)),
        ],
    },
    # -----------------------------------------------------------------
    # northrend  (Vrykul / Howling Fjord style)
    # -----------------------------------------------------------------
    'northrend': {
        'house': [
            ('World\\wmo\\Northrend\\Buildings\\Vrykul\\ND_Vrykul_Dwelling_01\\ND_Vrykul_Dwelling_01.wmo', (20, 18)),
            ('World\\wmo\\Northrend\\Buildings\\Vrykul\\ND_Vrykul_Dwelling_01\\ND_Vrykul_Dwelling_01Snow.wmo', (20, 18)),
        ],
        'guard_tower': [
            ('World\\wmo\\Northrend\\Buildings\\Vrykul\\ND_GondolaTower\\ND_Vrykul_GondolaTower_01.wmo', (10, 10)),
        ],
    },
}

# Style fallback chain: style -> parent style
_STYLE_FALLBACKS = {
    'human_duskwood': 'human_elwynn',
    'human_westfall': 'human_elwynn',
    'human_redridge': 'human_elwynn',
}


class WMOCatalog:
    """Resolves semantic building references to WMO file paths."""

    def __init__(self, catalog=None):
        """Initialise with optional custom catalog dict.

        Args:
            catalog: Override catalog dict (style -> type -> entries).
                     Uses the built-in WMO_CATALOG if None.
        """
        self._catalog = catalog or WMO_CATALOG

    def resolve(self, building_type, style, variant=None, seed=None):
        """Look up a WMO path + footprint for a building type and style.

        Fallback chain:
            1. Exact match: catalog[style][type]
            2. Variant filter: entries matching variant keyword in path
            3. Parent race style: e.g. human_duskwood -> human_elwynn
            4. Any style containing the type

        Args:
            building_type: 'inn', 'blacksmith', 'farm', etc.
            style: 'human_elwynn', 'human_duskwood', etc.
            variant: Optional variant like 'abandoned', 'destroyed', 'burnt'.
            seed: Random seed for deterministic selection among multiple options.

        Returns:
            (wmo_path, footprint) tuple, or None if not found.
        """
        rng = random.Random(seed) if seed is not None else random.Random()

        # Step 1: Exact style + type
        entries = self._get_entries(style, building_type)

        # Step 2: Variant filter
        if entries and variant:
            variant_lower = variant.lower()
            filtered = [e for e in entries if variant_lower in e[0].lower()]
            if filtered:
                entries = filtered

        # Step 3: Parent style fallback
        if not entries:
            parent = _STYLE_FALLBACKS.get(style)
            if parent:
                entries = self._get_entries(parent, building_type)

        # Step 4: Any style with this type
        if not entries:
            for s in self._catalog:
                entries = self._get_entries(s, building_type)
                if entries:
                    break

        if not entries:
            return None

        return rng.choice(entries)

    def _get_entries(self, style, building_type):
        """Get catalog entries for a style + type, or empty list."""
        style_data = self._catalog.get(style, {})
        return style_data.get(building_type, [])

    def list_styles(self):
        """Return all available building styles.

        Returns:
            list[str]: Sorted list of style keys.
        """
        return sorted(self._catalog.keys())

    def list_types(self, style=None):
        """Return available building types, optionally filtered by style.

        Args:
            style: If provided, only types for this style. Otherwise all types.

        Returns:
            list[str]: Sorted unique building type names.
        """
        if style:
            return sorted(self._catalog.get(style, {}).keys())
        all_types = set()
        for style_data in self._catalog.values():
            all_types.update(style_data.keys())
        return sorted(all_types)

    def resolve_all(self, buildings, default_style):
        """Resolve a list of building specs to WMO placements.

        Each input building dict should have 'type', 'position',
        and optionally 'rotation', 'variant', 'style'.

        Unresolvable buildings are logged as warnings and skipped.

        Args:
            buildings: List of building dicts from ZoneSpec.
            default_style: Fallback style from ZoneSpec.style.building_style.

        Returns:
            List of resolved building dicts with 'wmo_path' and 'footprint'.
        """
        resolved = []
        for i, bld in enumerate(buildings):
            btype = bld.get('type', '')
            bstyle = bld.get('style', default_style)
            variant = bld.get('variant')
            seed = bld.get('seed')

            result = self.resolve(btype, bstyle, variant=variant, seed=seed)
            if result is None:
                log.warning(
                    "Could not resolve building %d: type='%s' style='%s' - skipping",
                    i, btype, bstyle)
                continue

            wmo_path, footprint = result
            resolved.append({
                'type': btype,
                'position': bld.get('position', [0.5, 0.5]),
                'rotation': bld.get('rotation', 0),
                'name': bld.get('name', ''),
                'wmo_path': wmo_path,
                'footprint': footprint,
            })

        return resolved
