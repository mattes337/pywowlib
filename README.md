# pywowlib

A Python library for reading, writing, and generating World of Warcraft file formats, with a high-level **world builder** toolkit for programmatic WoW WotLK 3.3.5a content creation.

## Overview

pywowlib has two layers:

1. **File format library** -- low-level readers/writers for M2, WMO, ADT, WDT, BLP, DBC/DB2, MPQ, and CASC archives across multiple WoW versions.
2. **World builder toolkit** (`world_builder`) -- a headless content pipeline targeting WotLK 3.3.5a (build 12340) that generates terrain, DBC records, SQL, Lua scripts, artwork, dungeons, and MPQ patches from Python code.

The world builder is designed for AI-agent-driven content generation: an agent can create complete zones, dungeons, spells, items, creatures, quests, and UI addons from text descriptions with no manual binary editing.

## World Builder

The `world_builder` module provides end-to-end APIs for WoW 3.3.5a modding:

### Terrain & Maps

```python
from world_builder import build_zone, build_dungeon, create_adt, read_adt
from world_builder import add_doodad_to_adt, add_wmo_to_adt

# Create a complete zone (DBC + WDT + ADT + MPQ)
result = build_zone("MyZone", output_dir="./output", dbc_dir="./dbc")

# Insert objects into existing terrain
with open("Azeroth_32_48.adt", "rb") as f:
    adt = f.read()
adt = add_doodad_to_adt(adt, "World\\Azeroth\\Elwynn\\Tree01.m2", position=(-8900, -120, 85))
adt = add_wmo_to_adt(adt, "World\\wmo\\Building.wmo", position=(-8800, -100, 80))
```

### DBC Registration

High-level wrappers for all commonly-modded DBC files with named parameters:

```python
from world_builder import (
    register_map, register_area, register_spell, modify_spell,
    register_spell_icon, register_skill_line_ability,
    register_item, register_item_set, register_sound_entry,
    register_creature_display, register_creature_model,
    register_talent, register_talent_tab,
    register_gameobject_display, register_zone_intro_music,
)

# Create a spell (234-field Spell.dbc record via named params)
spell_id = register_spell(dbc_dir, name="Mega Fireball", school_mask=0x04, ManaCost=300)

# Modify existing spells by field name
modify_spell(dbc_dir, spell_id=133, ManaCost=200, CooldownTime=5000)

# Create item sets, talents, creatures, sounds, etc.
set_id = register_item_set(dbc_dir, name="Battlegear of Valor", item_ids=[...], bonuses=[...])
talent_id = register_talent(dbc_dir, tab_id=tab, tier=0, column=1, spell_ranks=[...])
```

The low-level `DBCInjector` class is also available for reading/writing any DBC file by field offset.

### Server-Side SQL

```python
from world_builder import SQLGenerator

sql = SQLGenerator()
sql.add_creature(entry=100000, name="Dragon", level=80, hp=500000)
sql.add_quest(entry=50000, title="Slay the Dragon", objectives="Kill 1 Dragon")
sql.add_item(entry=60000, name="Dragonslayer Sword", quality=4)
sql.add_npc(entry=100001, name="Quest Giver", gossip_menu_id=1)
sql.add_loot("creature_loot_template", loot_entry=100000, loot_items=[(60000, 25.0)])
sql.write_sql("output/world.sql")
```

### Scripting & Encounters

```python
from world_builder import ScriptGenerator, SpellRegistry

scripts = ScriptGenerator()
scripts.add_boss_encounter(
    boss_entry=100000, boss_name="Nightmare Dragon",
    phases=[...],  # Multi-phase Eluna Lua with timers, adds, spell rotations
)
scripts.write_scripts("output/scripts/")
```

### Artwork & Assets

```python
from world_builder import (
    generate_loading_screen, generate_world_map,
    convert_png_to_blp, MPQPacker, MPQExtractor,
)

generate_loading_screen("output/loading.blp", theme="volcanic")
convert_png_to_blp("custom.png", "output/custom.blp", compression="DXT1")

packer = MPQPacker("output/")
packer.add_wdt("MyZone", wdt_data)
packer.build_directory()
```

### VMap/MMap Generation

Subprocess wrappers for AzerothCore/TrinityCore map extraction tools:

```python
from world_builder import generate_vmaps, generate_mmaps, generate_server_data

# Generate all server collision/pathing data
generate_server_data(client_dir=r"G:\WoW", output_dir="./server_data")
```

Tools must be built from source -- a Dockerfile is provided at `tools/extractors/Dockerfile`.

### AddOn Scaffolding

```python
from world_builder import generate_addon

generate_addon(
    name="MyAddon",
    output_dir="./Interface/AddOns/MyAddon",
    title="My Custom Addon",
    frames=[{"name": "MainFrame", "width": 300, "height": 200, "movable": True}],
    events=["PLAYER_LOGIN"],
    slash_commands={"myaddon": "Toggle main frame"},
    saved_variables=["MyAddonDB"],
)
```

### Terrain Sculpting

```python
from world_builder import TerrainSculptor

sculptor = TerrainSculptor()
sculptor.add_noise(scale=0.01, amplitude=30)
sculptor.add_plateau(center=(64, 64), radius=20, height=50)
sculptor.add_texture_rule("Tileset\\Grass.blp", min_height=0, max_height=40)
heightmap, textures = sculptor.generate(128, 128)
```

## Supported File Formats

| Format | Description | 3.3.5a | Other Versions | Notes |
|--------|------------|--------|----------------|-------|
| M2 | Model | Read/Write | 1.12.1 - 9.0.0 | Full support for WotLK |
| Skin | M2 LoD | Read/Write | 3.3.5a - 9.0.0 | |
| Anim | Animation Sequence | Read/Write | 3.3.5a - 9.0.0 | |
| Skel | Skeleton Data | N/A | 7.3.5 - 9.0.0 | |
| WMO | World Map Object | Read/Write | 1.12.1 - 9.0.0 | Generation via `build_dungeon()` |
| ADT | Terrain Tile | Read/Write | 1.12.1 - 3.3.5a | Generation, sculpting, doodad/WMO insertion |
| WDT | World Layout | Read/Write | 3.3.5a | Generation via `create_wdt()` |
| BLP | Images | Read + Convert | 1.12.1 - 9.0.0 | PNG-to-BLP with DXT1/DXT3/DXT5 |
| DBC/DB2 | Client Database | Read/Write | 1.12.1 - 3.3.5a | 15+ convenience wrappers for WotLK |
| MPQ | Archive | Read/Write | 1.12.1 - 5.4.8 | Pack and extract via StormLib |
| CASC | Archive | Read-only | 6.2.4 - 9.0.0 | Via pyCASCLib |

## Use Case Guides

Detailed step-by-step guides with code examples are available in [`use_cases/`](use_cases/INDEX.md):

| Category | Guides |
|----------|--------|
| World Building | Add Zone, Add Dungeon, Update Scenery, Custom Music, Loading Screens |
| Combat & Spells | Add Spell, Change Spell Data, Modify Talents, Racial Traits |
| Items & Loot | Add Item, Create Item Set, Loot Tables, Crafting Recipes |
| Creatures | Add Creature, Boss Mechanics, Vendors/Trainers, NPC Pathing |
| Narrative | Add Quest, Quest Chains, Object Interaction, Teleporters |
| System & UI | Custom UI Frames, Flight Paths |

## Requirements

- Python 3.8+
- NumPy (for terrain sculpting)
- Pillow (for BLP/image conversion)
- A WoW 3.3.5a client (for DBC/MPQ source files)
- An AzerothCore or TrinityCore server (for SQL deployment)

## Installation

```bash
git clone https://github.com/mattes337/pywowlib.git
cd pywowlib
pip install numpy Pillow
```

Add to your Python path or import directly:

```python
from world_builder import build_zone, register_spell, SQLGenerator
```

## Contributing

Pull requests are welcome. See the [use case coverage index](use_cases/INDEX.md) for remaining gaps.

## License

MIT License. See source files for details.

## Legal

World of Warcraft is a registered trademark of Blizzard Entertainment and/or other respective owners. This software is not created by Blizzard Entertainment or its affiliates and is for purely educational and research purposes. It is your sole responsibility to follow copyright law, the game's ToS, and EULA. The creators hold no responsibility for the consequences of use of this software.
