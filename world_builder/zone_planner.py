"""
Zone Planner - Semantic zone generation layer for WoW WotLK 3.3.5a.

Translates high-level zone descriptions (archetype + landmarks) into
zone_definition dicts consumable by the existing sculpt_for_adt_composer()
pipeline in terrain_sculptor.py.

Usage:
    from world_builder.zone_planner import plan_zone, preview_heightmap

    zone_def = plan_zone(
        name="Ashfall Isle",
        archetype='volcanic_island',
        landmarks=[
            {'type': 'volcano', 'position': 'center', 'rim_height': 150},
            {'type': 'beach', 'position': 'south', 'radius': 0.12},
        ],
    )
    tile_data = sculpt_for_adt_composer(zone_def)
"""

import math
import random

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Elevation band thresholds (yards) for texture rule cascades
ELEV_SHORE = 2.0
ELEV_LOW = 30.0
ELEV_MID = 60.0
ELEV_HIGH = 100.0
ELEV_ALPINE = 130.0

# Slope thresholds (degrees) for texture overrides
SLOPE_GENTLE = 15.0
SLOPE_MODERATE = 30.0
SLOPE_STEEP = 45.0

# Doodad density presets (objects per square yard)
DENSITY_SPARSE = 0.0002
DENSITY_LIGHT = 0.0004
DENSITY_MODERATE = 0.0006
DENSITY_DENSE = 0.0010
DENSITY_THICK = 0.0014

_DENSITY_MAP = {
    'sparse': DENSITY_SPARSE,
    'light': DENSITY_LIGHT,
    'moderate': DENSITY_MODERATE,
    'dense': DENSITY_DENSE,
    'thick': DENSITY_THICK,
}


# ---------------------------------------------------------------------------
# Named Positions (compass directions to normalised coords)
# ---------------------------------------------------------------------------

NAMED_POSITIONS = {
    'center':       (0.5, 0.5),
    'north':        (0.5, 0.15),
    'south':        (0.5, 0.85),
    'east':         (0.85, 0.5),
    'west':         (0.15, 0.5),
    'northeast':    (0.75, 0.25),
    'northwest':    (0.25, 0.25),
    'southeast':    (0.75, 0.75),
    'southwest':    (0.25, 0.75),
    'north_center': (0.5, 0.3),
    'south_center': (0.5, 0.7),
    'east_center':  (0.7, 0.5),
    'west_center':  (0.3, 0.5),
}


# ---------------------------------------------------------------------------
# Texture Palettes (verified BLP paths from listfile.csv)
# ---------------------------------------------------------------------------

TEXTURE_PALETTES = {
    'volcanic_island': {
        'sand': [
            'Tileset\\Durotar\\DurotarShoreSand.blp',
            'Tileset\\Tanaris\\TanarisSandBase01.blp',
        ],
        'grass': [
            'Tileset\\Durotar\\Durotar_DryGrass.blp',
            'Tileset\\Stranglethorn\\StranglethornGrass.blp',
        ],
        'rock': [
            'Tileset\\Durotar\\DurotarRock.blp',
            'Tileset\\Durotar\\DurotarShorERocks.blp',
        ],
        'lava': [
            'Tileset\\Durotar\\DurotarDirt_Dark.blp',
            'Tileset\\Durotar\\DurotarRubble01.blp',
        ],
    },
    'forested_highlands': {
        'mud': [
            'Tileset\\Elwynn\\ElwynnRiverMudBase.blp',
            'Tileset\\Elwynn\\ElwynnDirtMud.blp',
        ],
        'grass': [
            'Tileset\\Elwynn\\ElwynnGrassBase.blp',
            'Tileset\\Elwynn\\ElwynnFlowerBase.blp',
        ],
        'rock': [
            'Tileset\\Elwynn\\ElwynnRockBase.blp',
            'Tileset\\Elwynn\\ElwynnRockGranite.blp',
        ],
        'forest_floor': [
            'Tileset\\Ashenvale\\AshenvaleMossBase.blp',
            'Tileset\\Ashenvale\\AshenvaleRoots.blp',
        ],
        'dirt': [
            'Tileset\\Elwynn\\ElwynnTreeDirtBase.blp',
        ],
    },
    'frozen_peaks': {
        'rock': [
            'Tileset\\Expansion02\\StormPeaks\\SP_RockBaseA.blp',
            'Tileset\\Expansion02\\StormPeaks\\SP_RockBaseB.blp',
        ],
        'snow': [
            'Tileset\\Expansion02\\StormPeaks\\SP_SnowA.blp',
            'Tileset\\Expansion02\\StormPeaks\\SP_HardSnowG.blp',
        ],
        'ice': [
            'Tileset\\Expansion02\\StormPeaks\\SP_IceA.blp',
        ],
    },
    'desert_canyon': {
        'sand': [
            'Tileset\\Tanaris\\TanarisSandBase01.blp',
            'Tileset\\Tanaris\\TanarisSandBase02.blp',
        ],
        'rock': [
            'Tileset\\The Badlands\\BadlandsRock.blp',
            'Tileset\\The Badlands\\BadlandsRockRed.blp',
            'Tileset\\The Badlands\\BadlandsRockHighlight.blp',
        ],
        'dirt': [
            'Tileset\\The Badlands\\BadlandsDirt.blp',
            'Tileset\\The Badlands\\BadlandsDirt05.blp',
            'Tileset\\The Badlands\\BadlandsDirtRedLighter.blp',
        ],
        'grass': [
            'Tileset\\The Badlands\\BadlandsGrass2.blp',
            'Tileset\\Durotar\\Durotar_DryGrass.blp',
        ],
        'sand_waves': [
            'Tileset\\The Badlands\\BadlandsSandWaves.blp',
            'Tileset\\Tanaris\\TanarisSandStones.blp',
        ],
    },
    'tropical_jungle': {
        'grass': [
            'Tileset\\Stranglethorn\\StranglethornGrass.blp',
        ],
        'rock': [
            'Tileset\\Stranglethorn\\StranglethornRock05.blp',
        ],
        'dirt': [
            'Tileset\\Stranglethorn\\StranglethornDirt03.blp',
        ],
        'moss': [
            'Tileset\\Stranglethorn\\StranglethornMossRoot01.blp',
        ],
        'soil': [
            'Tileset\\Expansion02\\SholazarBasin\\SB_SoilA.blp',
            'Tileset\\Expansion02\\SholazarBasin\\SB_SoilB.blp',
        ],
        'sand': [
            'Tileset\\Expansion02\\SholazarBasin\\SB_SandA.blp',
        ],
        'underbrush': [
            'Tileset\\Expansion02\\SholazarBasin\\SB_UnderbrushA.blp',
            'Tileset\\Expansion02\\SholazarBasin\\SB_UnderbrushB.blp',
        ],
        'roots': [
            'Tileset\\Expansion02\\SholazarBasin\\SB_RootsA.blp',
            'Tileset\\Expansion02\\SholazarBasin\\SB_RootsB.blp',
        ],
    },
    'dark_forest': {
        'grass': [
            'Tileset\\Duskwood\\DuskwoodGrassBase.blp',
        ],
        'rock': [
            'Tileset\\Duskwood\\DuskwoodRock.blp',
        ],
        'dirt': [
            'Tileset\\Duskwood\\DuskwoodDirt2.blp',
            'Tileset\\Duskwood\\DuskwoodMulch.blp',
        ],
        'cobblestone': [
            'Tileset\\Duskwood\\DuskwoodCobblestone.blp',
        ],
        'silverpine_grass': [
            'Tileset\\Silverpine\\SilverpineGrass.blp',
            'Tileset\\Silverpine\\SilverpineGrassFlowers.blp',
        ],
        'silverpine_rock': [
            'Tileset\\Silverpine\\SilverpineRock.blp',
            'Tileset\\Silverpine\\SilverpineRockGrass.blp',
        ],
        'silverpine_dirt': [
            'Tileset\\Silverpine\\SilverpineDirt.blp',
        ],
        'shore': [
            'Tileset\\Silverpine\\SilverpineShore.blp',
        ],
        'blight': [
            'Tileset\\Silverpine\\SilverpineBlight.blp',
        ],
    },
    'mushroom_marsh': {
        'slime': [
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshSlime.blp',
        ],
        'rock': [
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshRockBase01.blp',
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshRockBase02.blp',
        ],
        'moss': [
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshMoss01.blp',
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshMoss02.blp',
        ],
        'mossey': [
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshMossey01.blp',
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshMossey02.blp',
        ],
        'grass': [
            'Tileset\\Expansion01\\Zangarmarsh\\ZangarmarshGrass01.blp',
        ],
    },
    'plagued_wasteland': {
        'grass': [
            'Tileset\\Tirisfal\\TirisfallGrass01.blp',
        ],
        'rock_mud': [
            'Tileset\\Tirisfal\\TirisfallRockyMudGrass.blp',
        ],
        'dirt': [
            'Tileset\\Tirisfal\\TirisfallDirtRock07.blp',
        ],
        'blight': [
            'Tileset\\Silverpine\\SilverpineBlight.blp',
        ],
        'plagued_mud': [
            'Tileset\\Wetlands\\WetlandsDirtMoss01.blp',
        ],
        'plagued_grass': [
            'Tileset\\Wetlands\\WetlandsGrassDark01.blp',
        ],
    },
    'rolling_meadow': {
        'grass': [
            'Tileset\\Expansion01\\Nagrand\\NagrandSoftGrass.blp',
            'Tileset\\Expansion01\\Nagrand\\NagrandBaseGrass.blp',
            'Tileset\\Expansion01\\Nagrand\\NagrandBaseGrass02.blp',
        ],
        'grass_highlight': [
            'Tileset\\Expansion01\\Nagrand\\NagrandBaseGrassHighlight.blp',
            'Tileset\\Expansion01\\Nagrand\\NagrandBaseGrassHighlight02.blp',
        ],
        'rock': [
            'Tileset\\Expansion01\\Nagrand\\NagrandRockSolid.blp',
            'Tileset\\Expansion01\\Nagrand\\NagrandRockCracked.blp',
        ],
        'dirt': [
            'Tileset\\Expansion01\\Nagrand\\NagrandBaseDirt.blp',
            'Tileset\\Expansion01\\Nagrand\\NagrandCropCircleDirt.blp',
        ],
        'sand': [
            'Tileset\\Expansion01\\Nagrand\\NagrandSandDetail.blp',
        ],
        'road': [
            'Tileset\\Expansion01\\Nagrand\\NagrandRoad.blp',
        ],
    },
    'corrupted_fel': {
        'rock': [
            'Tileset\\Felwood\\FelwoodRock.blp',
            'Tileset\\Felwood\\FelwoodRock03.blp',
            'Tileset\\Felwood\\FelwoodRockCracked.blp',
            'Tileset\\Felwood\\FelwoodRockSmooth.blp',
        ],
        'dirt': [
            'Tileset\\Felwood\\FelwoodDirt.blp',
        ],
        'roots': [
            'Tileset\\Felwood\\FelwoodRoots.blp',
            'Tileset\\Felwood\\FelwoodRootsCorrupt.blp',
        ],
        'moss': [
            'Tileset\\Felwood\\FelwoodMoss.blp',
            'Tileset\\Felwood\\FelwoodMossOrange.blp',
        ],
        'ferns': [
            'Tileset\\Felwood\\FelwoodFerns.blp',
        ],
        'corrupt': [
            'Tileset\\Felwood\\FelwoodCorrupt.blp',
            'Tileset\\Felwood\\FelwoodCorruptSlime.blp',
            'Tileset\\Felwood\\FelwoodCorruptSlimeSolid.blp',
        ],
        'netherstorm_rock': [
            'Tileset\\Expansion01\\Netherstorm\\NetherstormRock01.blp',
            'Tileset\\Expansion01\\Netherstorm\\NetherstormRock02.blp',
        ],
        'netherstorm_dirt': [
            'Tileset\\Expansion01\\Netherstorm\\NetherstormDirt01.blp',
            'Tileset\\Expansion01\\Netherstorm\\NetherstormDirt02.blp',
        ],
        'netherstorm_lava': [
            'Tileset\\Expansion01\\Netherstorm\\NetherstormRockLava.blp',
        ],
    },
    'nordic_fjord': {
        'soot': [
            'Tileset\\Expansion02\\HowlingFjord\\HF_SootA.blp',
            'Tileset\\Expansion02\\HowlingFjord\\HF_SootB.blp',
        ],
        'smooth_rock': [
            'Tileset\\Expansion02\\HowlingFjord\\HF_SmoothRockA.blp',
        ],
        'embers': [
            'Tileset\\Expansion02\\HowlingFjord\\HF_EmbersA.blp',
        ],
        'dirt': [
            'Tileset\\Expansion02\\HowlingFjord\\HF_DirtD.blp',
            'Tileset\\Expansion02\\HowlingFjord\\HF_DirtF.blp',
        ],
        'pine_needles': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_PineNeedlesA.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_PineNeedlesB.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_PineNeedlesC.blp',
        ],
        'shrubby': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_ShrubbyA.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_ShrubbyB.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_ShrubbyC.blp',
        ],
        'rocky': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_RockyA.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_RockyB.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_RockyC.blp',
        ],
        'stony': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_StonyA.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_StonyB.blp',
        ],
        'mossy_rock': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_MossyRockA.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_MossyRockB.blp',
        ],
        'flower_fields': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_YellowFlowerField.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_WhiteFlowerField.blp',
        ],
        'snow': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_LumpySnowB.blp',
            'Tileset\\Expansion02\\GrizzlyHills\\GH_LumpySnowC.blp',
        ],
        'sawdust': [
            'Tileset\\Expansion02\\GrizzlyHills\\GH_Sawdust1.blp',
        ],
    },
    'frozen_tundra': {
        'ground': [
            'Tileset\\Expansion02\\BoreanTundra\\BT_StonyA.blp',
            'Tileset\\Expansion02\\BoreanTundra\\BT_SnowMossA.blp',
        ],
        'shrub': [
            'Tileset\\Expansion02\\BoreanTundra\\BT_ShrubbyA.blp',
        ],
        'dirt': [
            'Tileset\\Expansion02\\Dragonblight\\DB_DirtC.blp',
        ],
        'snow': [
            'Tileset\\Expansion02\\StormPeaks\\SP_SnowA.blp',
        ],
        'rock': [
            'Tileset\\Expansion02\\StormPeaks\\SP_RockBaseA.blp',
        ],
    },
}


# ---------------------------------------------------------------------------
# Doodad Palettes (verified M2 paths from listfile.csv)
# ---------------------------------------------------------------------------

DOODAD_PALETTES = {
    'volcanic_island': {
        'World\\Kalimdor\\Durotar\\PassiveDoodads\\Trees\\DurotarPalm01_noanim.m2': 0.0008,
        'World\\Kalimdor\\Durotar\\PassiveDoodads\\Trees\\DurotarPalm02_noanim.m2': 0.0008,
    },
    'forested_highlands': {
        'World\\Azeroth\\Elwynn\\PassiveDoodads\\Trees\\ElwynnTreeCanopy01.m2': 0.0012,
        'World\\Azeroth\\Elwynn\\PassiveDoodads\\Trees\\ElwynnTreeCanopy02.m2': 0.0008,
        'World\\Azeroth\\Elwynn\\PassiveDoodads\\Trees\\ElwynnFirTree01.m2': 0.0008,
        'World\\Kalimdor\\Ashenvale\\PassiveDoodads\\AshenvaleTrees\\AshenvaleTree01.m2': 0.0006,
        'World\\Kalimdor\\Ashenvale\\PassiveDoodads\\AshenvaleStumps\\AshenvaleTreeStump03.m2': 0.0003,
    },
    'frozen_peaks': {
        'World\\Expansion02\\Doodads\\StormPeaks\\Trees\\StormPeaks_TreeI.m2': 0.0004,
    },
    'desert_canyon': {
        'World\\Kalimdor\\Durotar\\PassiveDoodads\\Trees\\DurotarPalm01_noanim.m2': 0.0002,
    },
    'tropical_jungle': {
        'World\\Azeroth\\Stranglethorn\\PassiveDoodads\\Trees\\StranglethornTree01\\StranglethornTree01.m2': 0.0010,
        'World\\Azeroth\\Stranglethorn\\PassiveDoodads\\Trees\\StranglethornTree02\\StranglethornTree02.m2': 0.0008,
        'World\\Azeroth\\Stranglethorn\\PassiveDoodads\\Trees\\StranglethornTree04\\StranglethornTree04.m2': 0.0006,
        'World\\Azeroth\\Stranglethorn\\PassiveDoodads\\Trees\\StranglethornRoot01.m2': 0.0005,
        'World\\Azeroth\\Stranglethorn\\PassiveDoodads\\Trees\\StranglethornRoot02.m2': 0.0004,
        'World\\Expansion02\\Doodads\\Scholazar\\Trees\\SholazarPalm_Tree01.m2': 0.0006,
        'World\\Expansion02\\Doodads\\Scholazar\\Trees\\SholazarPalm_Tree02.m2': 0.0005,
        'World\\Expansion02\\Doodads\\Scholazar\\Trees\\SholazarPalm_Tree03.m2': 0.0004,
        'World\\Expansion02\\Doodads\\Scholazar\\Trees\\SholazarBroadleaf_Bush01_Dark.m2': 0.0006,
    },
    'dark_forest': {
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodTreeCanopy01.m2': 0.0012,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodTreeCanopy02.m2': 0.0008,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodTreeCanopy03.m2': 0.0006,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodSpookyTree01.m2': 0.0005,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodSpookyTree02.m2': 0.0004,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodSpookyTree03.m2': 0.0003,
        'World\\Azeroth\\Duskwood\\PassiveDoodads\\Trees\\DuskwoodWhiteTree.m2': 0.0003,
        'World\\Lordaeron\\Silverpine\\PassiveDoodads\\Trees\\SilverPineTree01.m2': 0.0006,
        'World\\Lordaeron\\Silverpine\\PassiveDoodads\\Trees\\SilverPineTree02.m2': 0.0005,
    },
    'mushroom_marsh': {
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreeBlue01.m2': 0.0006,
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreeBlue03.m2': 0.0004,
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreeGreen01.m2': 0.0006,
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreeGreen02.m2': 0.0004,
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreePurple01.m2': 0.0005,
        'World\\Expansion01\\Doodads\\Zangar\\MushroomTrees\\ZangarTreePurple02.m2': 0.0004,
        'World\\Expansion01\\Doodads\\Zangar\\PlantGroups\\ZangarPlantGroup01.m2': 0.0008,
        'World\\Expansion01\\Doodads\\Zangar\\PlantGroups\\ZangarPlantGroup02.m2': 0.0006,
        'World\\Expansion01\\Doodads\\Zangar\\FloatingSpore\\ZangarMarsh_FloatingSpore01.m2': 0.0003,
    },
    'plagued_wasteland': {
        'World\\Lordaeron\\TirisfalGlade\\PassiveDoodads\\Trees\\TirisfallGladeCanopyTree02.m2': 0.0006,
        'World\\Lordaeron\\TirisfalGlade\\PassiveDoodads\\Trees\\TirisfallGladeCanopyTree03.m2': 0.0005,
        'World\\Lordaeron\\TirisfalGlade\\PassiveDoodads\\Trees\\TirisfallGladeCanopyTree04.m2': 0.0004,
        'World\\Lordaeron\\TirisfalGlade\\PassiveDoodads\\Trees\\TirisfallFallenTree01.m2': 0.0003,
        'World\\Lordaeron\\TirisfalGlade\\PassiveDoodads\\Trees\\TirisfallFallenTree02.m2': 0.0003,
    },
    'rolling_meadow': {
        'World\\Expansion01\\Doodads\\Nagrand\\Trees\\NagrandTree01.m2': 0.0006,
        'World\\Expansion01\\Doodads\\Nagrand\\Trees\\NagrandTree02.m2': 0.0005,
        'World\\Expansion01\\Doodads\\Nagrand\\Trees\\NagrandTree03.m2': 0.0005,
        'World\\Expansion01\\Doodads\\Nagrand\\Trees\\NagrandTree04.m2': 0.0004,
        'World\\Expansion01\\Doodads\\Nagrand\\Trees\\NagrandTree05.m2': 0.0003,
        'World\\Expansion01\\Doodads\\Nagrand\\Rocks\\Nagrand_SmallRock_05.m2': 0.0004,
        'World\\Expansion01\\Doodads\\Nagrand\\Rocks\\Nagrand_SmallRock_06.m2': 0.0004,
    },
    'corrupted_fel': {
        'World\\Kalimdor\\Felwood\\PassiveDoodads\\Tree\\FelwoodTreeSub01.m2': 0.0008,
        'World\\Kalimdor\\Felwood\\PassiveDoodads\\Tree\\FelwoodTreeSub02.m2': 0.0006,
        'World\\Kalimdor\\Felwood\\PassiveDoodads\\Tree\\FelwoodTreeSub03.m2': 0.0005,
        'World\\Kalimdor\\Felwood\\PassiveDoodads\\Tree\\FelwoodTreeSub04.m2': 0.0004,
    },
    'nordic_fjord': {
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHills_Tree10.m2': 0.0008,
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHills_Tree11.m2': 0.0007,
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHills_Tree12.m2': 0.0006,
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHillsHuge_Tree.m2': 0.0003,
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHills_TreeTrunk01.m2': 0.0004,
        'World\\Expansion02\\Doodads\\GrizzlyHills\\Trees\\GrizzlyHills_TreeTrunk02.m2': 0.0003,
    },
    'frozen_tundra': {
        'World\\Expansion02\\Doodads\\StormPeaks\\Trees\\StormPeaks_TreeI.m2': 0.0002,
    },
}


# ---------------------------------------------------------------------------
# Zone Archetypes (12 templates)
# ---------------------------------------------------------------------------

ZONE_ARCHETYPES = {
    'volcanic_island': {
        'description': 'Volcanic island with ocean surrounds (Durotar + Tanaris coast style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'island',
            'center': (0.5, 0.5),
            'radius': 0.45,
            'elevation': (0, 80),
            'falloff': 0.3,
        },
        'global_water': {'elevation': 0.0, 'type': 'ocean'},
        'default_textures': ['sand', 'grass', 'rock'],
        'elevation_range': (0, 150),
    },
    'forested_highlands': {
        'description': 'Rolling forested hills (Elwynn + Ashenvale style)',
        'grid_size': (2, 2),
        'sea_level': 5.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (5, 120),
            'noise_params': {'scale': 40.0, 'octaves': 4, 'persistence': 0.45},
        },
        'global_water': None,
        'default_textures': ['grass', 'rock', 'forest_floor'],
        'elevation_range': (5, 120),
    },
    'frozen_peaks': {
        'description': 'Frozen mountain peaks (Storm Peaks style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 130),
            'noise_params': {'scale': 35.0, 'octaves': 5, 'persistence': 0.5},
        },
        'global_water': None,
        'default_textures': ['rock', 'snow', 'ice'],
        'elevation_range': (0, 130),
    },
    'desert_canyon': {
        'description': 'Arid desert with canyons (Tanaris + Badlands style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 100),
            'noise_params': {'scale': 45.0, 'octaves': 3, 'persistence': 0.4},
        },
        'global_water': None,
        'default_textures': ['sand', 'rock', 'dirt'],
        'elevation_range': (0, 100),
    },
    'tropical_jungle': {
        'description': 'Dense tropical jungle (Stranglethorn + Sholazar Basin style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 80),
            'noise_params': {'scale': 30.0, 'octaves': 4, 'persistence': 0.4},
        },
        'global_water': {'elevation': 0.0, 'type': 'ocean'},
        'default_textures': ['grass', 'moss', 'soil'],
        'elevation_range': (0, 80),
    },
    'dark_forest': {
        'description': 'Gloomy dark forest (Duskwood + Silverpine style)',
        'grid_size': (2, 2),
        'sea_level': 5.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (5, 90),
            'noise_params': {'scale': 35.0, 'octaves': 3, 'persistence': 0.4},
        },
        'global_water': None,
        'default_textures': ['grass', 'dirt', 'rock'],
        'elevation_range': (5, 90),
    },
    'mushroom_marsh': {
        'description': 'Alien mushroom marshland (Zangarmarsh style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 40),
            'noise_params': {'scale': 25.0, 'octaves': 3, 'persistence': 0.35},
        },
        'global_water': {'elevation': 5.0, 'type': 'swamp'},
        'default_textures': ['moss', 'slime', 'rock'],
        'elevation_range': (0, 40),
    },
    'plagued_wasteland': {
        'description': 'Blighted undead wasteland (Tirisfal + W. Plaguelands style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 60),
            'noise_params': {'scale': 35.0, 'octaves': 3, 'persistence': 0.35},
        },
        'global_water': None,
        'default_textures': ['grass', 'blight', 'dirt'],
        'elevation_range': (0, 60),
    },
    'rolling_meadow': {
        'description': 'Gentle rolling grasslands (Nagrand style)',
        'grid_size': (2, 2),
        'sea_level': 5.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (5, 70),
            'noise_params': {'scale': 50.0, 'octaves': 3, 'persistence': 0.3},
        },
        'global_water': None,
        'default_textures': ['grass', 'grass_highlight', 'dirt'],
        'elevation_range': (5, 70),
    },
    'corrupted_fel': {
        'description': 'Fel-corrupted wasteland (Felwood + Netherstorm style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 100),
            'noise_params': {'scale': 30.0, 'octaves': 4, 'persistence': 0.45},
        },
        'global_water': {'elevation': 2.0, 'type': 'lava'},
        'default_textures': ['corrupt', 'rock', 'dirt'],
        'elevation_range': (0, 100),
    },
    'nordic_fjord': {
        'description': 'Forested fjords (Howling Fjord + Grizzly Hills style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 120),
            'noise_params': {'scale': 35.0, 'octaves': 4, 'persistence': 0.45},
        },
        'global_water': {'elevation': 0.0, 'type': 'ocean'},
        'default_textures': ['pine_needles', 'rocky', 'shrubby'],
        'elevation_range': (0, 120),
    },
    'frozen_tundra': {
        'description': 'Flat frozen tundra (Borean Tundra + Dragonblight style)',
        'grid_size': (2, 2),
        'sea_level': 0.0,
        'base_terrain': {
            'terrain_type': 'noise',
            'elevation': (0, 50),
            'noise_params': {'scale': 50.0, 'octaves': 3, 'persistence': 0.3},
        },
        'global_water': {'elevation': 0.0, 'type': 'ocean'},
        'default_textures': ['ground', 'snow', 'rock'],
        'elevation_range': (0, 50),
    },
}


# ---------------------------------------------------------------------------
# Area ID Counter
# ---------------------------------------------------------------------------

class _AreaIDCounter:
    """Simple auto-incrementing area ID allocator."""

    def __init__(self, start=5000):
        self._next = start

    def next(self):
        area_id = self._next
        self._next += 1
        return area_id


# ---------------------------------------------------------------------------
# Position Resolver
# ---------------------------------------------------------------------------

def _resolve_position(position):
    """Convert a string name or (x, y) tuple to normalised (cx, cy) coords."""
    if isinstance(position, str):
        pos = NAMED_POSITIONS.get(position.lower().replace(' ', '_'))
        if pos is None:
            raise ValueError(
                "Unknown position name '{}'. Valid names: {}".format(
                    position, ', '.join(sorted(NAMED_POSITIONS.keys()))))
        return pos
    if isinstance(position, (list, tuple)) and len(position) >= 2:
        return (float(position[0]), float(position[1]))
    raise ValueError(
        "Position must be a string name or (x, y) tuple, got: {!r}".format(
            position))


# ---------------------------------------------------------------------------
# Texture helpers
# ---------------------------------------------------------------------------

def _pick_textures(archetype, bands):
    """Pick texture paths from the palette for the given biome bands.

    Args:
        archetype: Archetype key string.
        bands: List of palette band keys (e.g. ['sand', 'grass', 'rock']).

    Returns:
        List of BLP path strings (up to 4, deduped).
    """
    palette = TEXTURE_PALETTES.get(archetype, {})
    textures = []
    seen = set()
    for band in bands:
        paths = palette.get(band, [])
        if paths:
            path = paths[0]
            if path not in seen:
                textures.append(path)
                seen.add(path)
    return textures[:4]


def _pick_doodads(archetype, density_mult=1.0):
    """Pick doodad dict from the palette with optional density multiplier.

    Returns:
        Dict {m2_path: density}.
    """
    palette = DOODAD_PALETTES.get(archetype, {})
    return {path: density * density_mult for path, density in palette.items()}


# ---------------------------------------------------------------------------
# Landmark Translators
# ---------------------------------------------------------------------------

def _translate_volcano(landmark, archetype, ids):
    """Translate a 'volcano' landmark into 2 subzones (cone + caldera)."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    rim_height = landmark.get('rim_height', 120)
    caldera_depth = landmark.get('caldera_depth', 40)
    base_radius = landmark.get('radius', 0.2)
    caldera_radius = landmark.get('caldera_radius', base_radius * 0.3)
    has_lava = landmark.get('has_lava', False)
    name = landmark.get('name', 'Volcano')

    subzones = []

    # Outer cone
    cone_textures = _pick_textures(archetype, ['rock', 'lava', 'dirt'])
    if not cone_textures:
        cone_textures = _pick_textures(archetype, ['rock', 'grass', 'sand'])
    subzones.append({
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': base_radius,
        'terrain_type': 'volcano',
        'elevation': (0, rim_height),
        'falloff': 0.3,
        'weight': 1.0,
        'terrain_params': {
            'caldera_radius': caldera_radius,
            'caldera_depth': caldera_depth,
        },
        'textures': cone_textures,
        'doodads': {},
        'structures': [],
        'water': [],
    })

    # Caldera (lava lake)
    if has_lava:
        lava_elev = rim_height - caldera_depth
        subzones[-1]['water'].append({
            'type': 'lava',
            'elevation': float(lava_elev),
            'boundary': 'caldera',
        })

    return subzones


def _translate_peak(landmark, archetype, ids):
    """Translate a 'peak' or 'mountain' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    elevation = landmark.get('elevation', 90)
    radius = landmark.get('radius', 0.12)
    name = landmark.get('name', 'Peak')

    textures = _pick_textures(archetype, ['rock', 'snow', 'ice'])
    if not textures:
        textures = _pick_textures(archetype, ['rock', 'grass', 'dirt'])

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'island',
        'elevation': (0, elevation),
        'falloff': 0.25,
        'weight': 1.0,
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [],
    }]


def _translate_village(landmark, archetype, ids):
    """Translate a 'village' or 'town' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.07)
    elevation = landmark.get('elevation', 15)
    name = landmark.get('name', 'Village')

    textures = _pick_textures(archetype, ['dirt', 'cobblestone', 'road', 'grass'])
    if not textures:
        textures = _pick_textures(archetype, ['dirt', 'grass', 'sand'])

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'plateau',
        'elevation': (0, elevation),
        'falloff': 0.15,
        'weight': 1.0,
        'terrain_params': {'edge_steepness': 8.0},
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [],
    }]


def _translate_cave(landmark, archetype, ids):
    """Translate a 'cave' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.05)
    elevation = landmark.get('elevation', 25)
    name = landmark.get('name', 'Cave')

    textures = _pick_textures(archetype, ['rock', 'dirt', 'moss'])
    if not textures:
        textures = _pick_textures(archetype, ['rock', 'grass'])

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'island',
        'elevation': (0, elevation),
        'falloff': 0.2,
        'weight': 1.0,
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [],
    }]


def _translate_lake(landmark, archetype, ids):
    """Translate a 'lake' landmark into 1 subzone with water."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.08)
    depth = landmark.get('depth', 8)
    water_type = landmark.get('water_type', 'lake')
    name = landmark.get('name', 'Lake')

    textures = _pick_textures(archetype, ['sand', 'mud', 'grass'])
    if not textures:
        textures = _pick_textures(archetype, ['sand', 'grass', 'dirt'])

    water_elevation = -depth + 2.0  # slightly above bottom

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'valley',
        'elevation': (0, depth),
        'falloff': 0.3,
        'weight': 1.0,
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [{
            'type': water_type,
            'elevation': float(water_elevation),
            'boundary': 'inherit',
        }],
    }]


def _translate_pond(landmark, archetype, ids):
    """Translate a 'pond' landmark into 1 subzone with shallow water."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.04)
    depth = landmark.get('depth', 3)
    name = landmark.get('name', 'Pond')

    textures = _pick_textures(archetype, ['sand', 'mud', 'grass'])
    if not textures:
        textures = _pick_textures(archetype, ['sand', 'grass', 'dirt'])

    water_elevation = -depth + 1.0

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'valley',
        'elevation': (0, depth),
        'falloff': 0.25,
        'weight': 1.0,
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [{
            'type': 'lake',
            'elevation': float(water_elevation),
            'boundary': 'inherit',
        }],
    }]


def _translate_forest(landmark, archetype, ids):
    """Translate a 'forest' landmark into 1 subzone with dense doodads."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.15)
    name = landmark.get('name', 'Forest')
    density_key = landmark.get('density', 'dense')
    density_mult = _DENSITY_MAP.get(density_key, DENSITY_DENSE) / DENSITY_MODERATE

    textures = _pick_textures(archetype, ['forest_floor', 'grass', 'moss', 'roots'])
    if not textures:
        textures = _pick_textures(archetype, ['grass', 'dirt', 'rock'])

    doodads = _pick_doodads(archetype, density_mult)

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'noise',
        'elevation': (5, 50),
        'noise_params': {'scale': 25.0, 'octaves': 3, 'persistence': 0.35},
        'falloff': 0.3,
        'weight': 0.5,
        'textures': textures,
        'doodads': doodads,
        'doodad_filters': {
            'slope': {'max': 30.0},
            'elevation': {'min': 3.0},
        },
        'structures': [],
        'water': [],
    }]


def _translate_beach(landmark, archetype, ids):
    """Translate a 'beach' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.12)
    name = landmark.get('name', 'Beach')

    textures = _pick_textures(archetype, ['sand', 'sand_waves'])
    if not textures:
        textures = _pick_textures(archetype, ['sand', 'grass', 'dirt'])

    # Palm tree doodads for beaches
    beach_doodads = {}
    palette = DOODAD_PALETTES.get(archetype, {})
    for path, density in palette.items():
        if 'palm' in path.lower():
            beach_doodads[path] = density * 1.5
    if not beach_doodads:
        # Use first two doodads at low density
        for i, (path, density) in enumerate(palette.items()):
            if i >= 2:
                break
            beach_doodads[path] = density * 0.3

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'island',
        'elevation': (0, 3),
        'falloff': 0.4,
        'weight': 1.0,
        'textures': textures,
        'doodads': beach_doodads,
        'doodad_filters': {
            'slope': {'max': 15.0},
        },
        'structures': [],
        'water': [],
    }]


def _translate_cliff(landmark, archetype, ids):
    """Translate a 'cliff' or 'ridge' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.1)
    height = landmark.get('elevation', 60)
    name = landmark.get('name', 'Cliff')

    # Determine ridge start/end from position + direction
    direction = landmark.get('direction', 'north_south')
    if direction == 'east_west':
        start = (cx - radius, cy)
        end = (cx + radius, cy)
    else:
        start = (cx, cy - radius)
        end = (cx, cy + radius)

    textures = _pick_textures(archetype, ['rock', 'rocky', 'stony'])
    if not textures:
        textures = _pick_textures(archetype, ['rock', 'dirt', 'grass'])

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'ridge',
        'elevation': (0, height),
        'falloff': 0.15,
        'weight': 1.0,
        'terrain_params': {
            'start': start,
            'end': end,
            'width': landmark.get('width', 0.04),
        },
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [],
    }]


def _translate_ruins(landmark, archetype, ids):
    """Translate a 'ruins' landmark into 1 subzone."""
    cx, cy = _resolve_position(landmark.get('position', 'center'))
    radius = landmark.get('radius', 0.06)
    elevation = landmark.get('elevation', 10)
    name = landmark.get('name', 'Ruins')

    textures = _pick_textures(archetype, ['dirt', 'cobblestone', 'rock'])
    if not textures:
        textures = _pick_textures(archetype, ['dirt', 'rock', 'grass'])

    return [{
        'name': name,
        'area_id': ids.next(),
        'center': (cx, cy),
        'radius': radius,
        'terrain_type': 'plateau',
        'elevation': (0, elevation),
        'falloff': 0.2,
        'weight': 1.0,
        'terrain_params': {'edge_steepness': 4.0},
        'textures': textures,
        'doodads': {},
        'structures': [],
        'water': [],
    }]


# Landmark type dispatch table
_LANDMARK_TRANSLATORS = {
    'volcano': _translate_volcano,
    'peak': _translate_peak,
    'mountain': _translate_peak,
    'village': _translate_village,
    'town': _translate_village,
    'cave': _translate_cave,
    'lake': _translate_lake,
    'pond': _translate_pond,
    'forest': _translate_forest,
    'beach': _translate_beach,
    'cliff': _translate_cliff,
    'ridge': _translate_cliff,
    'ruins': _translate_ruins,
}


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def plan_zone(name, archetype='forested_highlands', landmarks=None,
              grid_size=None, sea_level=None, seed=None,
              base_coords=None, area_id_start=5000):
    """Assemble a complete zone_definition dict from high-level parameters.

    Args:
        name: Zone display name.
        archetype: One of the 12 archetype keys (e.g. 'volcanic_island').
        landmarks: List of landmark dicts, each with at least 'type' and
            'position' keys. See LANDMARK_TRANSLATORS for supported types.
        grid_size: (width, height) in ADT tiles. Overrides archetype default.
        sea_level: Sea level height. Overrides archetype default.
        seed: Random seed for reproducible generation.
        base_coords: (x, y) starting tile coords. Default (32, 32).
        area_id_start: Starting area ID for auto-allocation.

    Returns:
        dict: zone_definition ready for sculpt_for_adt_composer().
    """
    if archetype not in ZONE_ARCHETYPES:
        raise ValueError(
            "Unknown archetype '{}'. Valid archetypes: {}".format(
                archetype, ', '.join(sorted(ZONE_ARCHETYPES.keys()))))

    template = ZONE_ARCHETYPES[archetype]
    ids = _AreaIDCounter(area_id_start)

    if grid_size is None:
        grid_size = template['grid_size']
    if sea_level is None:
        sea_level = template['sea_level']
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    if base_coords is None:
        base_coords = (32, 32)
    if landmarks is None:
        landmarks = []

    # Build base terrain subzone from archetype
    base = template['base_terrain']
    default_tex_bands = template.get('default_textures', ['grass', 'rock', 'dirt'])
    base_textures = _pick_textures(archetype, default_tex_bands)
    base_doodads = _pick_doodads(archetype, 1.0)

    subzones = []

    # Base terrain subzone (covers entire zone)
    base_subzone = {
        'name': name,
        'area_id': ids.next(),
        'center': base.get('center', (0.5, 0.5)),
        'radius': base.get('radius', 0.5),
        'terrain_type': base['terrain_type'],
        'elevation': base.get('elevation', (0, 50)),
        'falloff': base.get('falloff', 0.3),
        'weight': 1.0,
        'textures': base_textures,
        'doodads': base_doodads,
        'doodad_filters': {
            'slope': {'max': 35.0},
            'elevation': {'min': sea_level + 2.0},
        },
        'structures': [],
        'water': [],
    }
    if 'noise_params' in base:
        base_subzone['noise_params'] = base['noise_params']
    if 'terrain_params' in base:
        base_subzone['terrain_params'] = base['terrain_params']

    subzones.append(base_subzone)

    # Translate landmarks into subzones
    for landmark in landmarks:
        ltype = landmark.get('type', '').lower()
        translator = _LANDMARK_TRANSLATORS.get(ltype)
        if translator is None:
            raise ValueError(
                "Unknown landmark type '{}'. Valid types: {}".format(
                    ltype, ', '.join(sorted(set(_LANDMARK_TRANSLATORS.keys())))))
        translated = translator(landmark, archetype, ids)
        subzones.extend(translated)

    # Assemble zone_definition
    zone_def = {
        'name': name,
        'grid_size': tuple(grid_size),
        'base_coords': tuple(base_coords),
        'sea_level': float(sea_level),
        'seed': int(seed),
        'subzones': subzones,
        'texture_palette': TEXTURE_PALETTES.get(archetype, {}),
        'doodad_palette': DOODAD_PALETTES.get(archetype, {}),
    }

    # Global water from archetype
    global_water = template.get('global_water')
    if global_water is not None:
        zone_def['global_water'] = dict(global_water)

    return zone_def


# ---------------------------------------------------------------------------
# Preview / Discovery Helpers
# ---------------------------------------------------------------------------

def preview_heightmap(zone_def):
    """Lightweight stats-only preview of a zone definition.

    Computes per-subzone and global elevation/slope statistics
    without generating full heightmaps.

    Args:
        zone_def: Zone definition dict (from plan_zone()).

    Returns:
        dict with keys:
            'global': {'min_elevation', 'max_elevation', 'sea_level',
                       'grid_size', 'n_subzones'}
            'subzones': list of {'name', 'terrain_type', 'center',
                                 'radius', 'elevation_range'}
    """
    subzones = zone_def.get('subzones', [])

    global_min = float('inf')
    global_max = float('-inf')

    subzone_stats = []
    for sz in subzones:
        elev = sz.get('elevation', (0, 50))
        if isinstance(elev, (list, tuple)):
            e_min, e_max = elev[0], elev[1]
        else:
            e_min, e_max = 0, float(elev)

        global_min = min(global_min, e_min)
        global_max = max(global_max, e_max)

        subzone_stats.append({
            'name': sz.get('name', 'unnamed'),
            'terrain_type': sz.get('terrain_type', 'noise'),
            'center': sz.get('center', (0.5, 0.5)),
            'radius': sz.get('radius', 0.2),
            'elevation_range': (e_min, e_max),
        })

    if global_min == float('inf'):
        global_min = 0.0
    if global_max == float('-inf'):
        global_max = 0.0

    return {
        'global': {
            'min_elevation': global_min,
            'max_elevation': global_max,
            'sea_level': zone_def.get('sea_level', 0.0),
            'grid_size': zone_def.get('grid_size', (1, 1)),
            'n_subzones': len(subzones),
        },
        'subzones': subzone_stats,
    }


def list_archetypes():
    """Return a dict mapping archetype keys to descriptions.

    Returns:
        dict: {archetype_key: description_string}
    """
    return {key: val['description'] for key, val in ZONE_ARCHETYPES.items()}


def list_landmark_types():
    """Return a sorted list of supported landmark type strings.

    Returns:
        list: Sorted unique landmark type names.
    """
    return sorted(set(_LANDMARK_TRANSLATORS.keys()))
