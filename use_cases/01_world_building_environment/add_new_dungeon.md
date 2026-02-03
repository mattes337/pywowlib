# Add New Dungeon (Instance)

## Overview

This guide covers the complete process of creating a custom 5-player dungeon
instance for WoW WotLK 3.3.5a using the `pywowlib` world builder toolkit.
Unlike exterior zones (which use ADT terrain tiles), dungeons use **WMO** (World
Map Object) files for their geometry. The dungeon builder provides room
primitives (`BoxRoom`, `CircularRoom`, `Corridor`, `ChamberRoom`, `SpiralRamp`)
that generate actual 3D geometry with collision, materials, lighting, and
portals.

By the end of this guide you will have:

- WMO root file + group files with full geometry, collision BSP, and lighting
- DBC entries in **Map.dbc** (instance_type=1), **AreaTable.dbc**,
  **DungeonEncounter.dbc**, **LFGDungeons.dbc**, **AreaTrigger.dbc**, and
  **LoadingScreens.dbc**
- Spawn coordinate metadata for boss and trash placement
- Eluna Lua boss encounter scripts via **ScriptGenerator**
- Server-side SQL for `instance_template`, `access_requirement`,
  `areatrigger_teleport`, and `lfg_dungeon_template`
- Everything packed into the correct MPQ directory structure

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.8+ | Standard CPython |
| pywowlib | Cloned and importable |
| NumPy | `pip install numpy` |
| Jinja2 | `pip install jinja2` -- required for ScriptGenerator |
| DBC files | Copy of `DBFilesClient/` from 3.3.5a client |
| Server | AzerothCore with Eluna for Lua scripting |

---

## Step-by-Step Walkthrough

### Step 1 -- Plan the Dungeon Layout

Before writing code, sketch the room layout. A typical 5-man dungeon has:

- **Entrance hall** (where players zone in)
- **2-3 trash corridors** connecting rooms
- **3-4 boss rooms** with increasing difficulty
- **Optional secret/bonus room**

For this guide we will build a 4-room dungeon called "Vault of Storms":

```
[Entrance Hall] --corridor--> [Storm Gallery] --corridor-->
[Lightning Chamber (Boss 1)] --corridor-->
[Arcane Sanctum (Boss 2)] --corridor-->
[Eye of the Tempest (Final Boss)]
```

#### ID Allocation

```python
DUNGEON_NAME   = "VaultOfStorms"
MAP_ID         = 810
AREA_ID        = 5100
LOADING_ID     = 210
LFG_DUNGEON_ID = 300
BOSS_ENTRY_1   = 90001
BOSS_ENTRY_2   = 90002
BOSS_ENTRY_3   = 90003
TRIGGER_ID     = 9100

DBC_DIR    = r"C:\WoW335\DBFilesClient"
OUTPUT_DIR = r"C:\WoW335\patch_output"
```

---

### Step 2 -- Define Room Geometry

The dungeon builder provides five room primitive classes:

| Class | Shape | Key Parameters |
|---|---|---|
| `BoxRoom` | Rectangular box | width, length, height |
| `CircularRoom` | Cylinder | radius, height, segments |
| `Corridor` | Narrow rectangular box | width, length, height |
| `ChamberRoom` | Regular polygon (hex, oct) | radius, height, sides |
| `SpiralRamp` | Helical ramp | radius, height, turns, segments |

Each primitive generates:
- **Vertices**: 3D positions
- **Triangles**: Index triplets with inward-facing normals
- **Normals**: Per-vertex normal vectors
- **UVs**: Texture coordinates (1 unit = 1 yard)
- **Face materials**: Per-triangle zone names ('floor', 'wall', 'ceiling')
- **Collision mesh**: Simplified geometry for BSP tree

#### Dungeon Definition

```python
from world_builder.dungeon_builder import (
    BoxRoom, CircularRoom, Corridor, ChamberRoom, SpiralRamp,
    build_dungeon, export_spawn_coordinates, DungeonAssembler,
)

dungeon_def = {
    'name': DUNGEON_NAME,
    'map_id': MAP_ID,
    'instance_type': 1,        # 1 = party dungeon

    'rooms': [
        # Room 0: Entrance Hall
        {
            'id': 'entrance',
            'name': 'Entrance Hall',
            'type': 'box',
            'width': 30.0,
            'length': 40.0,
            'height': 10.0,
            'center': (0.0, 0.0, 0.0),
            'materials': {
                'floor': 'floor_tile',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            },
            'boss': {'enabled': False},
            'connections': ['storm_gallery'],
        },

        # Room 1: Storm Gallery (trash room)
        {
            'id': 'storm_gallery',
            'name': 'Storm Gallery',
            'type': 'corridor',
            'width': 12.0,
            'length': 60.0,
            'height': 8.0,
            'center': (0.0, 50.0, 0.0),
            'materials': {
                'floor': 'floor_tile',
                'wall': 'stone_light',
                'ceiling': 'stone_dark',
            },
            'boss': {'enabled': False},
            'connections': ['lightning_chamber'],
        },

        # Room 2: Lightning Chamber (Boss 1)
        {
            'id': 'lightning_chamber',
            'name': 'Lightning Chamber',
            'type': 'circular',
            'radius': 25.0,
            'height': 15.0,
            'center': (0.0, 110.0, 0.0),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'stone_light',
                'ceiling': 'stone_dark',
            },
            'boss': {
                'enabled': True,
                'entry_id': BOSS_ENTRY_1,
                'name': 'Stormcaller Vex',
                'spawn_offset': (0.0, 0.0, 0.5),
            },
            'connections': ['arcane_sanctum'],
            'lights': [
                {
                    'type': 'point',
                    'position': (0.0, 0.0, 12.0),
                    'color': (0.6, 0.8, 1.0),
                    'intensity': 1.2,
                    'attenuation_start': 15.0,
                    'attenuation_end': 30.0,
                    'relative': True,
                },
            ],
        },

        # Room 3: Arcane Sanctum (Boss 2)
        {
            'id': 'arcane_sanctum',
            'name': 'Arcane Sanctum',
            'type': 'chamber',
            'radius': 20.0,
            'height': 12.0,
            'sides': 8,           # Octagonal room
            'center': (0.0, 170.0, 5.0),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'energy_glow',
                'ceiling': 'stone_dark',
            },
            'boss': {
                'enabled': True,
                'entry_id': BOSS_ENTRY_2,
                'name': 'Archmage Zephyrus',
                'spawn_offset': (0.0, 0.0, 0.5),
            },
            'connections': ['eye_of_tempest'],
        },

        # Room 4: Eye of the Tempest (Final Boss)
        {
            'id': 'eye_of_tempest',
            'name': 'Eye of the Tempest',
            'type': 'circular',
            'radius': 35.0,
            'height': 20.0,
            'center': (0.0, 240.0, 10.0),
            'materials': {
                'floor': 'volcanic_rock',
                'wall': 'energy_glow',
                'ceiling': 'stone_dark',
            },
            'boss': {
                'enabled': True,
                'entry_id': BOSS_ENTRY_3,
                'name': 'Tempest Lord Kaelthor',
                'spawn_offset': (0.0, 0.0, 0.5),
            },
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\UlduarPillar01.m2',
                    'positions': [
                        (15.0, 0.0, 0.0),
                        (-15.0, 0.0, 0.0),
                        (0.0, 15.0, 0.0),
                        (0.0, -15.0, 0.0),
                    ],
                    'rotation': (0, 0, 0),
                    'scale': 1.5,
                },
            ],
        },
    ],
}
```

---

### Step 3 -- Build the WMO Dungeon

The `build_dungeon()` function orchestrates the entire WMO generation pipeline:

1. Resolves room connections and generates corridor geometry
2. Collects and indexes unique materials
3. Builds the WMO root file (MOHD, MOTX, MOMT, MOGN, MOGI, MOPV, MOPT, MOPR,
   MOLT, MODS, MODN, MODD chunks)
4. Builds one WMO group file per room (MOGP with MOPY, MOVI, MOVT, MONR, MOTV,
   MOBA, MOBN, MOBR sub-chunks)
5. Exports spawn coordinates to JSON
6. Optionally registers in Map.dbc

```python
result = build_dungeon(
    dungeon_def=dungeon_def,
    output_dir=OUTPUT_DIR,
    dbc_dir=DBC_DIR,           # Pass None to skip DBC registration
)

print("WMO files:", result['wmo_files'])
print("Map ID:", result['map_id'])

# Spawn coordinates for SQL insertion
coords = result['coordinate_metadata']
for room_id, room_data in coords['rooms'].items():
    print("Room '{}': center={}".format(room_id, room_data['center']))
    if room_data['boss_spawn']:
        print("  Boss spawn:", room_data['boss_spawn'])
```

#### Generated WMO File Structure

```
World/
  wmo/
    Dungeons/
      VaultOfStorms/
        VaultOfStorms.wmo          # Root file (materials, portals, lights)
        VaultOfStorms_000.wmo      # Group 0: Entrance Hall
        VaultOfStorms_001.wmo      # Group 1: Storm Gallery
        VaultOfStorms_002.wmo      # Group 2: Lightning Chamber
        VaultOfStorms_003.wmo      # Group 3: Arcane Sanctum
        VaultOfStorms_004.wmo      # Group 4: Eye of the Tempest
```

---

### Step 4 -- DBC Registration

#### 4a -- Map.dbc (instance_type=1)

For dungeons, `instance_type` must be 1 (party dungeon) or 2 (raid):

```python
from world_builder.dbc_injector import register_map

map_id = register_map(
    dbc_dir=DBC_DIR,
    map_name=DUNGEON_NAME,
    map_id=MAP_ID,
    instance_type=1,           # 1 = party dungeon
)
```

> **Note**: `build_dungeon()` calls `register_map()` internally when `dbc_dir`
> is provided. Only call it manually if you skipped the `dbc_dir` parameter.

#### 4b -- AreaTable.dbc

```python
from world_builder.dbc_injector import register_area

area_id = register_area(
    dbc_dir=DBC_DIR,
    area_name="Vault of Storms",
    map_id=MAP_ID,
    area_id=AREA_ID,
    parent_area_id=0,
)
```

#### 4c -- DungeonEncounter.dbc

Each boss needs an entry in **DungeonEncounter.dbc** for the encounter journal
and dungeon completion tracking.

##### DungeonEncounter.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique encounter identifier |
| 1 | MapID | uint32 | FK to Map.dbc |
| 2 | Difficulty | uint32 | 0=normal, 1=heroic |
| 3 | OrderIndex | uint32 | Boss order (0-based) |
| 4 | Bit | uint32 | Bitmask position for encounter state |
| 5-21 | Name_lang | locstring | Boss display name |
| 22 | SpellIconID | uint32 | Icon reference (0=default) |

```python
from world_builder.dbc_injector import register_dungeon_encounters

boss_names = [
    "Stormcaller Vex",
    "Archmage Zephyrus",
    "Tempest Lord Kaelthor",
]

encounter_ids = register_dungeon_encounters(
    dbc_dir=DBC_DIR,
    map_id=MAP_ID,
    boss_names=boss_names,
    difficulty=0,              # 0 = normal mode
)

print("Encounter IDs:", encounter_ids)
```

For individual boss registration:

```python
from world_builder.dbc_injector import register_dungeon_encounter

enc_id = register_dungeon_encounter(
    dbc_dir=DBC_DIR,
    boss_name="Stormcaller Vex",
    map_id=MAP_ID,
    order_index=0,             # First boss
    bit=0,                     # Bitmask position 0
    difficulty=0,
)
```

#### 4d -- LFGDungeons.dbc

Registers the dungeon in the Looking For Group (LFG) interface.

##### LFGDungeons.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique LFG dungeon identifier |
| 1-17 | Name_lang | locstring | Dungeon display name |
| 18 | MinLevel | uint32 | Minimum level to queue |
| 19 | MaxLevel | uint32 | Maximum level to queue |
| 20 | Target_level | uint32 | Average/target level |
| 23 | MapID | uint32 | FK to Map.dbc |
| 24 | Difficulty | uint32 | 0=normal, 1=heroic |
| 26 | TypeID | uint32 | 1=dungeon, 2=raid |
| 27 | Faction | uint32 | 0xFFFFFFFF=both factions |
| 29 | ExpansionLevel | uint32 | 0=Classic, 1=TBC, 2=WotLK |

```python
from world_builder.dbc_injector import register_lfg_dungeon

lfg_id = register_lfg_dungeon(
    dbc_dir=DBC_DIR,
    dungeon_name="Vault of Storms",
    min_level=78,
    max_level=80,
    map_id=MAP_ID,
    dungeon_id=LFG_DUNGEON_ID,
    difficulty=0,
    type_id=1,                 # 1 = dungeon
    faction=0xFFFFFFFF,        # Both factions
    expansion_level=2,         # WotLK
    description="A titan-forged vault crackling with storm energy.",
)
```

#### 4e -- AreaTrigger.dbc

The entrance portal requires an **AreaTrigger** -- an invisible 3D region that
triggers zone-in when a player walks into it.

##### AreaTrigger.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique trigger identifier |
| 1 | ContinentID | uint32 | Map ID where trigger is placed (the OUTSIDE map) |
| 2-4 | Pos X/Y/Z | float | Center position of trigger volume |
| 5 | Radius | float | Sphere radius (0 for box trigger) |
| 6-8 | Box L/W/H | float | Box dimensions (0 for sphere trigger) |
| 9 | Box_yaw | float | Box rotation in radians |

```python
from world_builder.dbc_injector import register_area_trigger

# Place the entrance trigger in the overworld (e.g., Eastern Kingdoms map 0)
trigger_id = register_area_trigger(
    dbc_dir=DBC_DIR,
    continent_id=0,            # Map where the portal physically exists
    pos_x=-8500.0,             # World position of the dungeon portal
    pos_y=400.0,
    pos_z=100.0,
    trigger_id=TRIGGER_ID,
    radius=5.0,                # 5-yard sphere trigger
)
```

#### 4f -- LoadingScreens.dbc

```python
from world_builder.dbc_injector import register_loading_screen

ls_id = register_loading_screen(
    dbc_dir=DBC_DIR,
    name="LoadScreenVaultOfStorms",
    filename="Interface\\Glues\\LoadingScreens\\LoadScreenVaultOfStorms.blp",
    loadingscreen_id=LOADING_ID,
    has_widescreen=1,
)
```

---

### Step 5 -- Export Spawn Coordinates

The `export_spawn_coordinates()` function extracts boss spawn positions from
the dungeon definition:

```python
from world_builder.dungeon_builder import export_spawn_coordinates

coord_meta = export_spawn_coordinates(dungeon_def)

# Result structure:
# {
#   'map_id': 810,
#   'dungeon_name': 'VaultOfStorms',
#   'rooms': {
#     'entrance': {'center': (0,0,0), 'boss_spawn': None, ...},
#     'lightning_chamber': {
#       'center': (0,110,0),
#       'boss_spawn': {'entry_id': 90001, 'position': (0,110,0.5), ...},
#       ...
#     },
#     ...
#   }
# }

for room_id, data in coord_meta['rooms'].items():
    if data['boss_spawn']:
        bs = data['boss_spawn']
        print("Boss entry {} spawns at ({:.1f}, {:.1f}, {:.1f})".format(
            bs['entry_id'], bs['position'][0],
            bs['position'][1], bs['position'][2]))
```

---

### Step 6 -- Boss Encounter Scripting with ScriptGenerator

The **ScriptGenerator** produces complete, deployable Eluna Lua scripts from
structured boss definitions:

```python
from world_builder.script_generator import ScriptGenerator
from world_builder.spell_registry import SpellRegistry

spell_reg = SpellRegistry()
gen = ScriptGenerator(spell_registry=spell_reg)

# Instance management script
instance_def = {
    'script_name': 'instance_vault_of_storms',
    'map_id': MAP_ID,
    'bosses': [
        {'entry': BOSS_ENTRY_1, 'name': 'stormcaller_vex',
         'data_index': 0, 'doors': []},
        {'entry': BOSS_ENTRY_2, 'name': 'archmage_zephyrus',
         'data_index': 1, 'doors': []},
        {'entry': BOSS_ENTRY_3, 'name': 'tempest_lord_kaelthor',
         'data_index': 2, 'doors': []},
    ],
    'encounter_count': 3,
}

gen.add_instance_script(instance_def)

# Boss 1: Stormcaller Vex (2-phase fight)
boss1_def = {
    'script_name': 'stormcaller_vex',
    'name': 'Stormcaller Vex',
    'entry': BOSS_ENTRY_1,
    'data_index': 0,
    'phases': [
        {
            'name': 'Phase 1 - Storm Surge',
            'hp_threshold': 100,
            'abilities': [
                {
                    'name': 'Lightning Bolt',
                    'spell': 'lightning_bolt',
                    'target': 'random',
                    'timer_min': 5000,
                    'timer_max': 8000,
                    'repeat_min': 5000,
                    'repeat_max': 8000,
                },
                {
                    'name': 'Chain Lightning',
                    'spell': 'chain_lightning',
                    'target': 'victim',
                    'timer_min': 10000,
                    'timer_max': 15000,
                    'repeat_min': 10000,
                    'repeat_max': 15000,
                },
            ],
        },
        {
            'name': 'Phase 2 - Overcharge',
            'hp_threshold': 40,
            'abilities': [
                {
                    'name': 'Storm Surge',
                    'spell': 'storm_surge',
                    'target': 'self',
                    'timer_min': 3000,
                    'timer_max': 3000,
                    'repeat_min': 15000,
                    'repeat_max': 20000,
                },
            ],
        },
    ],
    'yells': {
        'aggro': "You dare disturb the storm!",
        'phase2': "FEEL THE FURY OF THE TEMPEST!",
        'death': "The storm... subsides...",
    },
}

gen.add_boss_encounter(boss1_def)

# Write all scripts to disk
script_files = gen.write_scripts(
    os.path.join(OUTPUT_DIR, "scripts", "eluna")
)

for path in script_files:
    print("Written:", path)
```

#### Generated Script Files

```
scripts/eluna/
  instance_vault_of_storms.lua    # Instance state management
  boss_stormcaller_vex.lua        # Boss 1 encounter
  spell_constants.lua             # Auto-generated spell ID constants
  spell_config.json               # Spell configuration data
```

---

### Step 7 -- Server-Side SQL

#### `instance_template`

```sql
-- Register the dungeon instance
DELETE FROM `instance_template` WHERE `map` = 810;
INSERT INTO `instance_template` (`map`, `parent`, `script`, `allowMount`,
    `InsideResistance`, `DifficultyID1`, `DifficultyID2`, `DifficultyID3`)
VALUES
(810, 0, 'instance_vault_of_storms', 0, 0, 0, 0, 0);
```

#### `access_requirement`

```sql
-- Level 78+ required to enter
DELETE FROM `access_requirement` WHERE `mapId` = 810;
INSERT INTO `access_requirement` (`mapId`, `difficulty`, `level_min`, `level_max`,
    `item_level`, `item`, `item2`, `quest_done_A`, `quest_done_H`,
    `completed_achievement`, `quest_failed_text`, `comment`)
VALUES
(810, 0, 78, 0, 0, 0, 0, 0, 0, 0, '', 'Vault of Storms - Level 78 required');
```

#### `areatrigger_teleport`

```sql
-- Link the AreaTrigger.dbc entry to dungeon teleportation
DELETE FROM `areatrigger_teleport` WHERE `ID` = 9100;
INSERT INTO `areatrigger_teleport` (`ID`, `target_map`, `target_position_x`,
    `target_position_y`, `target_position_z`, `target_orientation`, `name`)
VALUES
(9100, 810, 0.0, -18.0, 1.0, 0.0, 'Vault of Storms - Entrance');
```

#### `lfg_dungeon_template`

```sql
-- Make dungeon available in the Dungeon Finder
DELETE FROM `lfg_dungeon_template` WHERE `dungeonId` = 300;
INSERT INTO `lfg_dungeon_template` (`dungeonId`, `name`, `position_x`,
    `position_y`, `position_z`, `orientation`)
VALUES
(300, 'Vault of Storms', 0.0, -18.0, 1.0, 0.0);
```

#### Boss creature templates

```sql
-- Boss 1: Stormcaller Vex
DELETE FROM `creature_template` WHERE `entry` = 90001;
INSERT INTO `creature_template` (`entry`, `name`, `subname`,
    `minlevel`, `maxlevel`, `faction`, `npcflag`, `unit_class`,
    `rank`, `type`, `ScriptName`,
    `HealthModifier`, `ManaModifier`, `ArmorModifier`, `DamageModifier`,
    `mingold`, `maxgold`, `mechanic_immune_mask`, `flags_extra`)
VALUES
(90001, 'Stormcaller Vex', 'Storm Herald',
 80, 80, 14, 0, 2,
 3, 4, '',
 25.0, 10.0, 1.0, 8.0,
 50000, 100000, 617299839, 1);

-- Boss 2: Archmage Zephyrus
DELETE FROM `creature_template` WHERE `entry` = 90002;
INSERT INTO `creature_template` (`entry`, `name`, `subname`,
    `minlevel`, `maxlevel`, `faction`, `npcflag`, `unit_class`,
    `rank`, `type`, `ScriptName`,
    `HealthModifier`, `ManaModifier`, `ArmorModifier`, `DamageModifier`,
    `mingold`, `maxgold`, `mechanic_immune_mask`, `flags_extra`)
VALUES
(90002, 'Archmage Zephyrus', 'Keeper of Arcane Secrets',
 80, 80, 14, 0, 2,
 3, 4, '',
 30.0, 15.0, 1.0, 9.0,
 75000, 150000, 617299839, 1);

-- Boss 3: Tempest Lord Kaelthor
DELETE FROM `creature_template` WHERE `entry` = 90003;
INSERT INTO `creature_template` (`entry`, `name`, `subname`,
    `minlevel`, `maxlevel`, `faction`, `npcflag`, `unit_class`,
    `rank`, `type`, `ScriptName`,
    `HealthModifier`, `ManaModifier`, `ArmorModifier`, `DamageModifier`,
    `mingold`, `maxgold`, `mechanic_immune_mask`, `flags_extra`)
VALUES
(90003, 'Tempest Lord Kaelthor', 'Lord of the Vault',
 80, 80, 14, 0, 2,
 3, 4, '',
 40.0, 20.0, 1.0, 10.0,
 100000, 200000, 617299839, 1);
```

#### Boss spawn positions (from coordinate metadata)

```sql
-- Spawn bosses using coordinates from export_spawn_coordinates()
DELETE FROM `creature` WHERE `id1` IN (90001, 90002, 90003);
INSERT INTO `creature` (`guid`, `id1`, `map`, `position_x`, `position_y`,
    `position_z`, `orientation`, `spawntimesecs`, `curhealth`)
VALUES
(900001, 90001, 810, 0.0, 110.0, 0.5, 0.0, 7200, 0),
(900002, 90002, 810, 0.0, 170.0, 5.5, 0.0, 7200, 0),
(900003, 90003, 810, 0.0, 240.0, 10.5, 0.0, 7200, 0);
```

---

### Step 8 -- MPQ Packing

```python
from world_builder.mpq_packer import MPQPacker

packer = MPQPacker(OUTPUT_DIR)

# Add WMO files
for wmo_path in result['wmo_files']:
    # Compute MPQ-internal path
    rel = os.path.relpath(wmo_path, OUTPUT_DIR)
    mpq_path = rel.replace(os.sep, "\\")
    with open(wmo_path, 'rb') as f:
        packer.add_file(mpq_path, f.read())

# Add modified DBC files
for dbc_name in ['Map', 'AreaTable', 'DungeonEncounter', 'LFGDungeons',
                  'AreaTrigger', 'LoadingScreens']:
    dbc_path = os.path.join(DBC_DIR, '{}.dbc'.format(dbc_name))
    if os.path.isfile(dbc_path):
        with open(dbc_path, 'rb') as f:
            packer.add_dbc(dbc_name, f.read())

output = packer.build_directory()
print("Packed to:", output)
```

---

### Step 9 -- Reading Existing Dungeons

To inspect or modify an existing WMO dungeon:

```python
from world_builder.dungeon_builder import read_dungeon

dungeon_data = read_dungeon(
    wmo_filepath=r"C:\extracted\World\wmo\Dungeons\UtgardeKeep\UtgardeKeep.wmo",
    version=17,
)

print("Dungeon:", dungeon_data['name'])
print("Rooms:", len(dungeon_data['rooms']))
print("Portals:", len(dungeon_data['portals']))
print("Materials:", len(dungeon_data['materials']))
print("Lights:", len(dungeon_data['lights']))
print("Doodads:", len(dungeon_data['doodads']))

# Each room has type='raw_mesh' with full geometry data
for room in dungeon_data['rooms']:
    verts = room.get('vertices', [])
    tris = room.get('triangles', [])
    print("  Room: {} verts, {} tris".format(len(verts), len(tris)))
```

---

## Material Presets

The dungeon builder includes predefined material presets that map to WoW BLP
textures:

| Preset Name | Texture Path | Shader | Use Case |
|---|---|---|---|
| `titan_metal` | `Ulduar_Metal_Floor.blp` | Diffuse | Boss room floors |
| `stone_dark` | `UtgardeWall01.blp` | Diffuse | Generic walls/ceilings |
| `stone_light` | `UtgardeWall02.blp` | Diffuse | Lit corridors |
| `volcanic_rock` | `ObsidianWall01.blp` | Diffuse | Fire/lava themed rooms |
| `energy_glow` | `T_VFX_ArcaneBlue02.blp` | Specular | Arcane accent surfaces |
| `floor_tile` | `UtgardeFloor01.blp` | Diffuse | Standard floors |

---

## Common Pitfalls and Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| Players fall through floor | Missing collision BSP data | Ensure `generate_collision_mesh()` is producing valid geometry |
| Invisible walls | Wrong triangle winding | Room primitives use inward-facing normals; custom geometry must match |
| Cannot enter dungeon | Missing AreaTrigger or areatrigger_teleport | Verify both DBC entry and SQL teleport target |
| LFG button grayed out | Wrong LFGDungeons.dbc level range | Check min/max level fields match player level |
| Boss not spawning | Wrong map ID in creature spawn | Verify `creature.map` matches `Map.dbc` ID |
| No encounter tracking | Missing DungeonEncounter.dbc | Register all bosses with `register_dungeon_encounters()` |
| Black textures | Missing BLP files in MPQ | Ensure material preset textures exist in the client MPQ chain |

---

## Validation Steps

1. **WMO validation**: Open the generated `.wmo` files in a WMO viewer
   (e.g., WoW Model Viewer or Blender with WoW addon) to visually inspect
   geometry.

2. **DBC validation**: Use a DBC editor to verify Map.dbc has instance_type=1,
   DungeonEncounter records exist with correct MapID, and AreaTrigger has
   valid coordinates.

3. **Server-side**: Start the server and verify `.tele VaultOfStorms` works.
   Check the LFG interface shows the dungeon.

4. **In-game testing**: Enter the dungeon and verify:
   - Geometry renders correctly (no holes, no z-fighting)
   - Collision works (cannot walk through walls)
   - Bosses spawn at correct positions
   - Encounter scripts fire (boss abilities, phase transitions)
   - Dungeon completion tracking updates

---

## Cross-References

- [Add New Zone](add_new_zone.md) -- Create the overworld zone containing the
  dungeon entrance portal
- [Add Custom Music](add_custom_music.md) -- Add ambient sounds and music to
  dungeon rooms
- [Change Loading Screen](change_loading_screen.md) -- Create a themed loading
  screen for the dungeon
- [Update Zone Scenery](update_zone_scenery.md) -- Techniques for modifying
  existing terrain (applicable to dungeon entrance areas)
