# Use Cases Index

Automation and coverage assessment for every WoW 3.3.5a modding use case against
the current `pywowlib` `world_builder` module.

## Legend

**Automation Level**

| Symbol | Meaning |
|--------|---------|
| **Full Auto** | End-to-end scriptable with no human intervention beyond providing input parameters |
| **AI-Assisted** | An AI agent can orchestrate all steps, making design decisions where needed |
| **Semi-Auto** | Some steps are automated, others require manual input or external assets |
| **Manual** | Requires significant human work outside pywowlib |
| **Not Feasible** | Cannot be automated due to engine/core limitations |

**pywowlib Coverage**

| Symbol | Meaning |
|--------|---------|
| **Complete** | All required operations have dedicated convenience APIs |
| **Mostly** | 80%+ of steps covered; minor gaps fillable with low-level `DBCInjector` |
| **Partial** | Key DBC schemas or generation steps are missing convenience wrappers |
| **Minimal** | Only generic low-level infrastructure available |
| **None** | Outside pywowlib's domain entirely |

---

## Summary Table

| # | Use Case | Automation | pywowlib Coverage | External Tools Required | Integration Candidate |
|---|----------|-----------|-------------------|------------------------|-----------------------|
| 1 | [Add New Zone](#1-add-new-zone-exterior) | Full Auto | Complete | -- | -- |
| 2 | [Add New Dungeon](#2-add-new-dungeon-instance) | Full Auto | Complete | -- | -- |
| 3 | [Update Zone Scenery](#3-update-zone-scenery) | AI-Assisted | Complete | Noggit (visual placement) | No |
| 4 | [Add Custom Music](#4-add-custom-music) | Full Auto | Complete | Audio creation tools | -- |
| 5 | [Change Loading Screen](#5-change-loading-screen) | Full Auto | Complete | Image editing (optional) | No |
| 6 | [Add New Spell](#6-add-new-spell) | Full Auto | Complete | -- | -- |
| 7 | [Change Spell Data](#7-change-spell-data) | Full Auto | Complete | -- | -- |
| 8 | [Modify Talent Tree](#8-modify-talent-tree) | Full Auto | Complete | -- | -- |
| 9 | [Change Racial Traits](#9-change-racial-traits) | Full Auto | Complete | -- | -- |
| 10 | [Add New Class](#10-add-new-class) | Not Feasible | Minimal | C++ core rewrite | No |
| 11 | [Add New Item](#11-add-new-item) | Full Auto | Mostly | 3D modeling (custom models) | -- |
| 12 | [Create Item Set](#12-create-item-set) | Full Auto | Complete | -- | -- |
| 13 | [Modify Loot Tables](#13-modify-loot-tables) | Full Auto | Complete | -- | -- |
| 14 | [Custom Crafting Recipe](#14-custom-crafting-recipe) | Full Auto | Complete | -- | -- |
| 15 | [Add New Creature](#15-add-new-creature) | Full Auto | Complete | 3D modeling (custom models) | -- |
| 16 | [Update Boss Mechanics](#16-update-boss-mechanics) | Full Auto | Complete | C++ scripting (non-Eluna) | No |
| 17 | [Add Vendor/Trainer](#17-add-vendortrainer) | Full Auto | Complete | -- | -- |
| 18 | [Change NPC Pathing](#18-change-npc-pathing) | Full Auto | Complete | -- | -- |
| 19 | [Add New Quest](#19-add-new-quest) | Full Auto | Complete | -- | -- |
| 20 | [Create Quest Chain](#20-create-quest-chain) | Full Auto | Complete | -- | -- |
| 21 | [Add Object Interaction](#21-add-object-interaction) | Full Auto | Complete | 3D modeling (custom models) | -- |
| 22 | [Custom Teleporter](#22-custom-teleporter) | Full Auto | Complete | -- | -- |
| 23 | [Add Playable Race](#23-add-playable-race) | Not Feasible | Minimal | C++ core, M2 mass editing | No |
| 24 | [Custom UI Frame](#24-custom-ui-frame) | Full Auto | Complete | -- | -- |
| 25 | [Modify Flight Paths](#25-modify-flight-paths) | Full Auto | Complete | -- | -- |

\* When reusing existing models. Custom models require external 3D tools.

---

## Detailed Assessments

### Category 1: World Building & Environment

#### 1. Add New Zone (Exterior)

**File:** [`01_world_building_environment/add_new_zone.md`](01_world_building_environment/add_new_zone.md)

**Automation: Full Auto** | **pywowlib: Complete**

The high-level `build_zone()` function orchestrates the entire pipeline: DBC
registration (`Map.dbc`, `AreaTable.dbc`, `WorldMapArea.dbc`, `LoadingScreens.dbc`),
WDT generation, ADT creation with heightmaps and texture splatting, artwork
generation (world maps, loading screens, minimaps), and MPQ packing. The
`TerrainSculptor` can generate procedural terrain with noise, primitives, texture
painting, and doodad scattering. `generate_vmaps()` / `generate_mmaps()` handle
server-side collision and pathing generation via subprocess integration.

**What pywowlib covers:**
- `build_zone()` -- full end-to-end pipeline
- `DBCInjector` -- Map, AreaTable, WorldMapArea, WorldMapOverlay, LoadingScreens, ZoneMusic, SoundAmbience, Light
- `TerrainSculptor` -- procedural heightmaps, texture rules, doodad placement
- `create_adt()` / `create_wdt()` -- binary terrain generation
- `artwork_pipeline` -- world maps, loading screens, subzone overlays
- `MPQPacker` -- client patch assembly
- `SQLGenerator.add_zone()` -- server-side zone registration
- `generate_vmaps()` / `generate_mmaps()` / `generate_server_data()` -- server collision and pathing via subprocess

**Note:** The vmap/mmap tools (`vmap4_extractor`, `vmap4_assembler`, `mmaps_generator`)
must be built from AzerothCore/TrinityCore source. A Docker build is provided in
`tools/extractors/Dockerfile` for building these tools from a local AC repo.

**External tools:**
| Tool | Purpose | Integrate into pywowlib? |
|------|---------|--------------------------|
| `vmap4_extractor` + `vmap4_assembler` | Server collision (LoS) | **Done** -- `generate_vmaps()` wraps as subprocess |
| `mmaps_generator` | Server NPC pathing (Recast/Detour) | **Done** -- `generate_mmaps()` wraps as subprocess |
| Noggit | Visual terrain editing | **No** -- full GUI application, orthogonal to headless pipeline |

**AI agent opportunity:** An AI agent can fully automate zone creation by:
generating a zone definition from a text description, calling `TerrainSculptor` to
produce terrain, running `build_zone()`, and triggering vmap/mmap generation via
`generate_server_data()`.

---

#### 2. Add New Dungeon (Instance)

**File:** [`01_world_building_environment/add_new_dungeon.md`](01_world_building_environment/add_new_dungeon.md)

**Automation: Full Auto** | **pywowlib: Complete**

`build_dungeon()` generates WMO root + group files from room primitives
(`BoxRoom`, `CircularRoom`, `Corridor`, `SpiralRamp`, `ChamberRoom`), registers
all DBC entries (`Map.dbc` with `instance_type=1`, `AreaTable.dbc`,
`DungeonEncounter.dbc`, `LFGDungeons.dbc`, `AreaTrigger.dbc`, `LoadingScreens.dbc`),
generates spawn coordinates, and packs into MPQ. `ScriptGenerator` produces Eluna
Lua scripts for boss encounters with multi-phase logic, timers, and add spawning.
`SQLGenerator` handles all server-side tables. Server collision/pathing is handled
by `generate_vmaps()` / `generate_mmaps()`.

**What pywowlib covers:**
- `build_dungeon()` -- WMO geometry + DBC + MPQ pipeline
- Room primitives with materials, portals, lighting, BSP trees
- `ScriptGenerator.add_instance_script()` -- door/gate logic, boss binding
- `ScriptGenerator.add_boss_encounter()` -- multi-phase bosses
- `SpellRegistry` -- boss ability ID management
- `SQLGenerator.add_dungeon()` -- instance_template, access_requirement
- `export_spawn_coordinates()` -- NPC/boss placement
- `generate_vmaps()` / `generate_mmaps()` -- server collision and pathing via subprocess

**Note:** Servers using C++ `InstanceScript` instead of Eluna need manual scripting.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| vmap/mmap generators | Server collision/pathing | **Done** -- subprocess wrappers in `vmap_generator.py` |
| C++ compiler | Non-Eluna instance scripts | **No** -- different paradigm, out of scope |

**AI agent opportunity:** Dungeon layout design from text descriptions, encounter
scripting from boss ability descriptions, full end-to-end generation.

---

#### 3. Update Zone Scenery

**File:** [`01_world_building_environment/update_zone_scenery.md`](01_world_building_environment/update_zone_scenery.md)

**Automation: AI-Assisted** | **pywowlib: Complete**

`read_adt()` parses existing terrain into editable Python structures (heightmaps,
textures, splat maps, doodad/WMO instances). Modifications are applied
programmatically and written back with `create_adt()`. `add_doodad_to_adt()` and
`add_wmo_to_adt()` insert objects into existing ADT binary data with full chunk
rebuilding (MMDX/MMID/MDDF for doodads, MWMO/MWID/MODF for WMOs). `MPQExtractor`
reads from existing archives, `MPQPacker` rebuilds patches.

**What pywowlib covers:**
- `MPQExtractor` -- read existing MPQ archives
- `read_adt()` -- parse ADT into heightmap, textures, splat, doodads, WMOs
- `import_heightmap_from_adt()` / `import_texture_rules_from_adt()` -- extraction
- `TerrainSculptor` primitives -- apply modifications to heightmaps
- `create_adt()` -- write modified terrain back
- `add_doodad_to_adt()` -- insert M2 doodads into existing ADT (modifies MMDX/MMID/MDDF, rebuilds MHDR/MCIN)
- `add_wmo_to_adt()` -- insert WMO buildings into existing ADT (modifies MWMO/MWID/MODF, rebuilds MHDR/MCIN)
- `MPQPacker` -- repack into client patch

**Note:** Visual object placement still requires knowing 3D coordinates. pywowlib
provides the API for coordinate-based insertion but has no visual preview.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| Noggit | Visual doodad/WMO placement | **No** -- full 3D editor, orthogonal to headless API |

**AI agent opportunity:** An AI agent can interpret descriptions like "make Elwynn
Forest darker" by adjusting texture layers, modifying lighting via `register_light()`,
swapping texture paths, and inserting/removing doodads and WMOs via the new ADT APIs.

---

#### 4. Add Custom Music

**File:** [`01_world_building_environment/add_custom_music.md`](01_world_building_environment/add_custom_music.md)

**Automation: Full Auto** | **pywowlib: Complete**

`register_zone_music()` creates `ZoneMusic.dbc` entries,
`register_sound_ambience()` creates `SoundAmbience.dbc` entries, and
`update_area_atmosphere()` links them to zones in `AreaTable.dbc`.
`register_sound_entry()` creates `SoundEntries.dbc` records (30 fields, 120 bytes)
with up to 10 sound files per entry. `register_zone_intro_music()` creates
`ZoneIntroMusicTable.dbc` entries for zone entrance stingers. `MPQPacker` handles
file placement.

**What pywowlib covers:**
- `register_zone_music()` -- ZoneMusic.dbc (8 fields, 32 bytes)
- `register_sound_ambience()` -- SoundAmbience.dbc (3 fields, 12 bytes)
- `register_sound_entry()` -- SoundEntries.dbc (30 fields, 120 bytes)
- `register_zone_intro_music()` -- ZoneIntroMusicTable.dbc (5 fields, 20 bytes)
- `update_area_atmosphere()` -- link music/ambience to AreaTable
- `register_light()` -- Light.dbc for atmosphere
- `MPQPacker.add_file()` -- place MP3 files in MPQ

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| Audio creation (Audacity, etc.) | Create MP3 files | **No** -- creative tool, out of scope |

**AI agent opportunity:** Fully automatable given existing audio files. AI selects
tracks, assigns them to zones, and generates all DBC entries including sound entries
and zone intro stingers.

---

#### 5. Change Loading Screen

**File:** [`01_world_building_environment/change_loading_screen.md`](01_world_building_environment/change_loading_screen.md)

**Automation: Full Auto** | **pywowlib: Complete**

Every step has a dedicated API. Procedural generation covers four themes
(tropical, volcanic, underground, titan). Custom images are converted via
`convert_png_to_blp()` with DXT1/DXT3/DXT5 compression.

**What pywowlib covers:**
- `generate_loading_screen()` -- procedural artwork (4 themes)
- `convert_png_to_blp()` / `image_to_blp()` -- BLP conversion
- `validate_blp()` -- format validation
- `register_loading_screen()` -- LoadingScreens.dbc entry
- `DBCInjector` -- link to Map.dbc field 57 (LoadingScreenID)
- `MPQPacker` -- file placement
- `generate_zone_artwork_bundle()` -- batch generation

**External tools:** Image editing software for custom artwork is optional;
pywowlib's procedural generator covers the common cases.

**AI agent opportunity:** Fully automatable. AI can generate or select loading
screens, convert formats, register DBC entries, and pack MPQ in one pass.

---

### Category 2: Combat, Classes & Spells

#### 6. Add New Spell

**File:** [`02_combat_classes_spells/add_new_spell.md`](02_combat_classes_spells/add_new_spell.md)

**Automation: Full Auto** | **pywowlib: Complete**

`register_spell()` creates complete `Spell.dbc` records (234 fields, 936 bytes)
with named parameters for all commonly-used fields: name, description, school,
cast time, cooldown, range, effects, mana cost, icon, and more. Dict-based field
mapping handles the full 234-field layout. `register_spell_icon()` creates
`SpellIcon.dbc` entries for icon texture assignment. `SpellRegistry` manages ID
allocation with Lua/JSON export.

**What pywowlib covers:**
- `register_spell()` -- Spell.dbc (234 fields, 936 bytes) with named parameters
- `modify_spell()` -- modify existing spell records by field name
- `register_spell_icon()` -- SpellIcon.dbc (2 fields, 8 bytes)
- `SpellRegistry` -- ID allocation, name tracking, Lua/JSON export
- `DBCInjector` (low-level) -- can read/write any DBC including Spell.dbc
- `SQLGenerator` -- server-side `spell_linked_spell`, `spell_bonus_data`
- `ScriptGenerator` -- Eluna Lua for custom spell handlers

**Remaining gaps:**
- `SpellVisual.dbc` -- spell visual effects (no schema; reuse existing visual IDs)
- `SpellVisualKit.dbc` -- visual kit composition (no schema)

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `SpellVisual.dbc` schema | Visual effects | Low priority -- reuse existing visual IDs for now |
| Server C++ | Custom spell mechanics | **No** -- requires core modification |

**AI agent opportunity:** Fully automatable. An AI agent can design spell parameters
(damage, cost, cooldown, effect type) from a text description and generate all DBC
entries via `register_spell()` and `register_spell_icon()`.

---

#### 7. Change Spell Data

**File:** [`02_combat_classes_spells/change_spell_data.md`](02_combat_classes_spells/change_spell_data.md)

**Automation: Full Auto** | **pywowlib: Complete**

`modify_spell()` modifies existing spell records using named fields (e.g.,
`modify_spell(dbc_dir, 133, ManaCost=200, CooldownTime=5000)`). The full
234-field map provides named access to every field in the WotLK 3.3.5 Spell.dbc
layout.

**What pywowlib covers:**
- `modify_spell()` -- modify any spell field by name (ManaCost, CooldownTime, Duration, Range, etc.)
- `register_spell()` -- create new spells with named parameters
- `DBCInjector` (low-level) -- read existing Spell.dbc, modify fields by offset
- `SQLGenerator` -- `spell_bonus_data`, `spell_custom_attr` for server-side overrides

**External tools:** None.

**AI agent opportunity:** Fully automatable. An AI agent can implement balance
changes ("buff Fireball by 10%") by reading the current ManaCost/damage values
and writing updated values via `modify_spell()`.

---

#### 8. Modify Talent Tree

**File:** [`02_combat_classes_spells/modify_talent_tree.md`](02_combat_classes_spells/modify_talent_tree.md)

**Automation: Full Auto** | **pywowlib: Complete**

`register_talent()` creates `Talent.dbc` records (23 fields, 92 bytes) with tier,
column, spell rank IDs, and prerequisite talent linking. `register_talent_tab()`
creates `TalentTab.dbc` records (24 fields, 96 bytes) with class mask, background
texture, and tab ordering. Combined with `register_spell()` for talent effect
spells, complete talent trees can be generated programmatically.

**What pywowlib covers:**
- `register_talent()` -- Talent.dbc (23 fields, 92 bytes) with tier, column, rank spells, prerequisites
- `register_talent_tab()` -- TalentTab.dbc (24 fields, 96 bytes) with class mask, texture, order
- `register_spell()` -- talent effect spells (Spell.dbc)
- `SpellRegistry` -- track talent spell IDs

**Note:** Talent tree arrow rendering depends on precise tier/column/prerequisite
configuration. Misconfigurations cause visual breaks in the client UI.

**External tools:** None.

**AI agent opportunity:** Talent tree design is highly structured (tier/column grid
with prerequisite arrows). An AI agent can generate valid trees from descriptions,
creating all talent, tab, and spell entries. A `validate_talent_tree()` function
would be a valuable future addition.

---

#### 9. Change Racial Traits

**File:** [`02_combat_classes_spells/change_racial_traits.md`](02_combat_classes_spells/change_racial_traits.md)

**Automation: Full Auto** | **pywowlib: Complete**

Racial traits are spells auto-learned via `SkillLineAbility.dbc`. `register_spell()`
creates the racial passive spell, and `register_skill_line_ability()` links it to
a skill line for auto-learning at the appropriate level/race.

**What pywowlib covers:**
- `register_spell()` -- racial passive spells (Spell.dbc, 234 fields)
- `modify_spell()` -- modify existing racial spells
- `register_skill_line_ability()` -- SkillLineAbility.dbc (14 fields, 56 bytes) auto-learn configuration
- `SpellRegistry` -- track new racial spell IDs
- `SQLGenerator` -- `player_levelstats` for base stat changes

**External tools:** None.

---

#### 10. Add New Class

**File:** [`02_combat_classes_spells/add_new_class.md`](02_combat_classes_spells/add_new_class.md)

**Automation: Not Feasible** | **pywowlib: Minimal**

The 3.3.5a client has a **hardcoded class limit** in the binary. Adding a class
beyond the existing 10 (Warrior through Death Knight) requires patching the client
executable and modifying the C++ server core. The plan correctly marks this as
"Impossible" and recommends replacing an existing class instead.

**What pywowlib covers:**
- `DBCInjector` (low-level) -- could write ChrClasses.dbc, CharBaseInfo.dbc
- `SQLGenerator` -- player_levelstats, playercreateinfo

**Gap:** Fundamental engine limitation. `ChrClasses.dbc`, `CharBaseInfo.dbc`,
`CharStartOutfit.dbc` schemas are not implemented, but even with them the
hardcoded limit blocks new classes.

**External tools:** Client binary patching, C++ core rewrite. **Not worth
integrating** -- the recommendation is to reskin/replace an existing class.

---

### Category 3: The Armory (Items & Loot)

#### 11. Add New Item

**File:** [`03_armory_items_loot/add_new_item.md`](03_armory_items_loot/add_new_item.md)

**Automation: Full Auto** | **pywowlib: Mostly Complete**

`register_item()` creates `Item.dbc` records (8 fields, 32 bytes) with class,
subclass, material, display info, and inventory type. `SQLGenerator.add_item()`
generates complete `item_template` INSERT statements with all stat columns.

**What pywowlib covers:**
- `register_item()` -- Item.dbc (8 fields, 32 bytes) client-side item registration
- `SQLGenerator.add_item()` -- full `item_template` with all stat fields
- `SQLGenerator.add_loot()` -- loot table entries
- `MPQPacker` -- pack custom M2/BLP models
- `blp_converter` -- texture conversion

**Remaining gap:** No `ItemDisplayInfo.dbc` schema (model paths, texture paths,
geoset groups, visual effects). Not needed when reusing existing display IDs
(which covers the vast majority of use cases).

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `ItemDisplayInfo.dbc` schema | Visual/model link | Low priority -- existing display IDs cover most needs |
| 3D modeling (Blender + M2 export) | Custom weapon/armor models | **No** -- creative tooling, out of scope |

**AI agent opportunity:** Fully automatable for items using existing display IDs
(which covers most cases -- recolored existing models). Custom models remain manual.

---

#### 12. Create Item Set

**File:** [`03_armory_items_loot/create_item_set.md`](03_armory_items_loot/create_item_set.md)

**Automation: Full Auto** | **pywowlib: Complete**

`register_item_set()` creates `ItemSet.dbc` records (53 fields, 212 bytes) with
set name, up to 17 item IDs, up to 8 set bonus spells with piece-count thresholds,
and optional skill requirements. Combined with `register_item()` and
`SQLGenerator.add_item()`, complete tier sets can be generated end-to-end.

**What pywowlib covers:**
- `register_item_set()` -- ItemSet.dbc (53 fields, 212 bytes) with item IDs, bonus spells, thresholds
- `register_item()` -- Item.dbc for individual set pieces
- `SQLGenerator.add_item()` -- items with `itemset` field in `item_template`

**External tools:** None.

**AI agent opportunity:** Fully automatable. An AI agent can design tier sets with
stat-appropriate bonuses, generate all DBC and SQL entries for both the set and
its individual items.

---

#### 13. Modify Loot Tables

**File:** [`03_armory_items_loot/modify_loot_tables.md`](03_armory_items_loot/modify_loot_tables.md)

**Automation: Full Auto** | **pywowlib: Complete**

Pure server-side SQL. `SQLGenerator.add_loot()` handles `creature_loot_template`,
`gameobject_loot_template`, `reference_loot_template`, etc.
`SQLGenerator.add_pools()` handles spawn pooling for randomized loot.

**What pywowlib covers:**
- `SQLGenerator.add_loot(table, loot_entry, loot_items)` -- all loot tables
- `SQLGenerator.add_creature_loot(loot_map)` -- batch creature loot
- `SQLGenerator.add_pools()` -- loot/spawn pooling
- `SQLGenerator.write_sql()` / `write_sql_split()` -- output

**External tools:** None.

**AI agent opportunity:** Fully automatable. AI can balance drop rates, distribute
loot across tiers, and generate all SQL.

---

#### 14. Custom Crafting Recipe

**File:** [`03_armory_items_loot/custom_crafting_recipe.md`](03_armory_items_loot/custom_crafting_recipe.md)

**Automation: Full Auto** | **pywowlib: Complete**

A crafting recipe is a "spell" (the craft action) linked to a "skill line"
(profession) that produces an "item" (the output). `register_spell()` creates the
craft spell with SPELL_EFFECT_CREATE_ITEM, `register_skill_line_ability()` links
it to the profession skill line, and `SQLGenerator.add_item()` creates the crafted
item and reagents.

**What pywowlib covers:**
- `register_spell()` -- Spell.dbc craft spell (234 fields, 936 bytes)
- `register_skill_line_ability()` -- SkillLineAbility.dbc profession link (14 fields, 56 bytes)
- `register_item()` -- Item.dbc for crafted item client-side entry
- `SQLGenerator.add_item()` -- crafted item and reagent items
- `SpellRegistry` -- track recipe spell IDs

**External tools:** None.

---

### Category 4: Creatures & Encounters

#### 15. Add New Creature

**File:** [`04_creatures_encounters/add_new_creature.md`](04_creatures_encounters/add_new_creature.md)

**Automation: Full Auto** | **pywowlib: Complete**

`SQLGenerator.add_creature()` generates complete `creature_template` entries.
`register_creature_display()` creates `CreatureDisplayInfo.dbc` records (16 fields,
64 bytes) for custom model display configuration. `register_creature_model()` creates
`CreatureModelData.dbc` records (28 fields, 112 bytes) for model file paths, collision,
and bounding boxes.

**What pywowlib covers:**
- `register_creature_display()` -- CreatureDisplayInfo.dbc (16 fields, 64 bytes)
- `register_creature_model()` -- CreatureModelData.dbc (28 fields, 112 bytes)
- `SQLGenerator.add_creature()` -- full creature_template
- `SQLGenerator.add_creatures()` -- batch creation
- `SQLGenerator.add_spawn()` / `add_spawns()` -- world placement
- `SQLGenerator.add_creature_ai()` / `add_smartai()` -- SmartAI behaviors
- `SQLGenerator.add_creature_loot()` -- loot tables
- `MPQPacker` -- pack custom M2/BLP models

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| 3D modeling (Blender + M2 export) | Custom creature models | **No** -- creative tooling |

**AI agent opportunity:** Fully automatable. AI can select or create display
configurations, design stats, create AI behaviors, and place spawns from text
descriptions.

---

#### 16. Update Boss Mechanics

**File:** [`04_creatures_encounters/update_boss_mechanics.md`](04_creatures_encounters/update_boss_mechanics.md)

**Automation: Full Auto** | **pywowlib: Complete**

`ScriptGenerator.add_boss_encounter()` produces complete multi-phase Eluna Lua
scripts with timers, spell rotations, add spawning, void zones, and phase
transitions. `register_spell()` creates boss ability spells in `Spell.dbc`.
`SpellRegistry` manages boss ability IDs. `SQLGenerator` handles `creature_text`
(boss yells), `creature_template`, and SmartAI fallback.

**What pywowlib covers:**
- `ScriptGenerator.add_boss_encounter()` -- multi-phase Eluna Lua
- `ScriptGenerator.add_instance_script()` -- instance-wide logic
- `register_spell()` -- boss ability spells (Spell.dbc)
- `SpellRegistry` -- boss spell ID management with Lua/JSON export
- `SQLGenerator.add_creature_ai()` -- SmartAI alternative
- `SQLGenerator` -- creature_text, creature_template, spawn placement

**Note:** C++ `InstanceScript` for non-Eluna servers requires manual scripting
and recompiling the server core.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| C++ compiler | Non-Eluna instance scripts | **No** -- different paradigm |

**AI agent opportunity:** Fully automatable. An AI agent can design complete boss
encounters from descriptions ("3-phase fight, enrages at 20%, summons adds in
phase 2"), generate all scripts, spells, and SQL.

---

#### 17. Add Vendor/Trainer

**File:** [`04_creatures_encounters/add_vendor_trainer.md`](04_creatures_encounters/add_vendor_trainer.md)

**Automation: Full Auto** | **pywowlib: Complete**

Pure SQL operation. `SQLGenerator.add_npc()` handles NPCs with vendor inventory
(`npc_vendor`), trainer spells (`npc_trainer`), gossip menus, and cosmetic
addons.

**What pywowlib covers:**
- `SQLGenerator.add_npc()` -- NPC with flags, gossip, vendor/trainer data
- `SQLGenerator.add_npcs()` -- batch creation
- `SQLGenerator.add_spawn()` -- world placement
- Gossip menu system -- `npc_text`, `gossip_menu`, `gossip_menu_option`

**External tools:** None.

**AI agent opportunity:** Fully automatable. AI can design vendor inventories
appropriate to zone level/theme, create trainers with class-appropriate spells.

---

#### 18. Change NPC Pathing

**File:** [`04_creatures_encounters/change_npc_pathing.md`](04_creatures_encounters/change_npc_pathing.md)

**Automation: Full Auto** | **pywowlib: Complete**

Pure SQL operation. `SQLGenerator` generates `waypoint_data` (positions, delays,
actions) and `creature_addon` (path_id linkage).

**What pywowlib covers:**
- `SQLGenerator` -- waypoint_data, creature_addon with path_id
- SmartAI -- `SMART_EVENT_WAYPOINT_REACHED` for scripted events at waypoints

**External tools:** GM commands (`.wp add`, `.wp show`) are useful for in-game
testing but not required for generation.

**AI agent opportunity:** Fully automatable. AI can generate patrol routes along
roads, walls, or between points of interest.

---

### Category 5: Narrative & Quests

#### 19. Add New Quest

**File:** [`05_narrative_quests/add_new_quest.md`](05_narrative_quests/add_new_quest.md)

**Automation: Full Auto** | **pywowlib: Complete**

`SQLGenerator.add_quest()` produces complete `quest_template` and
`quest_template_addon` INSERT statements with all columns documented
(objectives, rewards, requirements, text, flags).

**What pywowlib covers:**
- `SQLGenerator.add_quest()` -- full quest_template (50+ columns)
- `SQLGenerator.add_quests()` -- batch creation
- `SQLGenerator.add_npc()` -- quest givers/enders
- `SQLGenerator.add_spawn()` -- NPC/creature placement for objectives
- `SQLGenerator.add_creature_loot()` -- quest item drops

**External tools:** None.

**AI agent opportunity:** Highly suitable. AI can write quest narratives, design
objectives, balance rewards for level range, and generate all SQL.

---

#### 20. Create Quest Chain

**File:** [`05_narrative_quests/create_quest_chain.md`](05_narrative_quests/create_quest_chain.md)

**Automation: Full Auto** | **pywowlib: Complete**

Quest chains use `PrevQuestID`, `NextQuestID`, `RewardNextQuest`, and
`ExclusiveGroup` fields in `quest_template`, plus the `conditions` table for
complex prerequisites.

**What pywowlib covers:**
- `SQLGenerator.add_quest()` -- chaining fields (PrevQuestID, NextQuestID)
- `SQLGenerator` (`BaseBuilder`) -- raw INSERT for `conditions` table
- Breadcrumb quests, branching paths, converging chains

**External tools:** None.

**AI agent opportunity:** Fully automatable. AI can design branching storylines
with prerequisite logic, reputation gates, and class-specific paths.

---

#### 21. Add Object Interaction

**File:** [`05_narrative_quests/add_object_interaction.md`](05_narrative_quests/add_object_interaction.md)

**Automation: Full Auto** | **pywowlib: Complete**

`SQLGenerator.add_gameobject_template()` and `add_gameobject_spawn()` handle the
server-side tables. `register_gameobject_display()` creates `GameObjectDisplayInfo.dbc`
records (19 fields, 76 bytes) for custom gameobject models. SmartAI scripting
covers interactive behaviors.

**What pywowlib covers:**
- `register_gameobject_display()` -- GameObjectDisplayInfo.dbc (19 fields, 76 bytes)
- `SQLGenerator.add_gameobject_template()` -- all gameobject types (DOOR, CHEST, QUESTGIVER, GOOBER, etc.)
- `SQLGenerator.add_gameobject_spawn()` -- world placement with quaternion rotation
- `SQLGenerator.add_smartai()` -- interactive behaviors
- `SQLGenerator.add_loot()` -- chest/container loot

**External tools:** None (custom 3D models still require external modeling tools).

**AI agent opportunity:** Fully automatable. AI can design interactive objects,
chest puzzles, and quest objectives with full DBC and SQL generation.

---

#### 22. Custom Teleporter

**File:** [`05_narrative_quests/custom_teleporter.md`](05_narrative_quests/custom_teleporter.md)

**Automation: Full Auto** | **pywowlib: Complete**

Two approaches, both fully covered: NPC-based (gossip menu + SQL/Lua) and
AreaTrigger-based (DBC + SQL).

**What pywowlib covers:**
- `register_area_trigger()` -- AreaTrigger.dbc (sphere and box triggers)
- `SQLGenerator.add_npc()` -- teleporter NPC with gossip
- `ScriptGenerator` -- Eluna Lua for gossip-based teleportation
- `SQLGenerator` -- `areatrigger_teleport`, `access_requirement`

**External tools:** None.

**AI agent opportunity:** Fully automatable. AI can design teleport networks,
generate all NPC/trigger/script data.

---

### Category 6: System & UI

#### 23. Add Playable Race

**File:** [`06_system_ui/add_playable_race.md`](06_system_ui/add_playable_race.md)

**Automation: Not Feasible** | **pywowlib: Minimal**

Adding a playable race requires modifications across multiple layers that go
far beyond file generation: `ChrRaces.dbc` (69 fields), `CharBaseInfo.dbc`
(byte-packed), `CharStartOutfit.dbc` (296-byte records), C++ core changes
(race bitmask in `SharedDefines.h`, `Player.cpp` validation), and refitting
every helmet model in the game (3000+ `.m2` files) to the new head geometry.

**What pywowlib covers:**
- `DBCInjector` (low-level) -- can write ChrRaces.dbc, CharBaseInfo.dbc, CharStartOutfit.dbc
- `SQLGenerator` -- playercreateinfo, player_levelstats

**Gap:** No DBC schemas for ChrRaces, CharBaseInfo, or CharStartOutfit.
Fundamental requirement for C++ core changes. Mass M2 model editing for helmet
geometry is not supported.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| C++ compiler | Core race support | **No** -- fundamental engine change |
| M2 editor (WoW Model Viewer, 010 Editor) | Helmet refitting | **No** -- requires per-model manual work |
| Client binary patcher | Race count limit | **No** -- reverse engineering |

**Recommendation:** Reskin an existing race instead (e.g., Blood Elf -> High Elf).
This avoids C++ changes and helmet refitting entirely. pywowlib could support
this with `ChrRaces.dbc` and `CharStartOutfit.dbc` schemas.

---

#### 24. Custom UI Frame

**File:** [`06_system_ui/custom_ui_frame.md`](06_system_ui/custom_ui_frame.md)

**Automation: Full Auto** | **pywowlib: Complete**

`generate_addon()` produces complete WoW AddOn scaffolds: `.toc` file (Interface:
30300 for WotLK 3.3.5), `.lua` with event handling, slash commands, and saved
variables support, and optional `.xml` with frame definitions including backdrop
and movable support. `MPQPacker` can package AddOns into MPQ for server-wide
distribution.

**What pywowlib covers:**
- `generate_addon()` -- complete AddOn scaffold (TOC + Lua + optional XML)
  - TOC with Interface version, title, notes, dependencies, saved variables
  - Lua with event registration, slash commands, saved variable persistence
  - XML with frame definitions, backdrop, movable/resizable support
- `MPQPacker` -- package AddOns into MPQ for distribution

**External tools:** None for scaffolding. WoW API reference needed for custom
AddOn logic beyond the generated boilerplate.

**AI agent opportunity:** Fully automatable. An AI agent can produce complete
AddOns from descriptions, generating all TOC/Lua/XML files via `generate_addon()`.

---

#### 25. Modify Flight Paths

**File:** [`06_system_ui/modify_flight_paths.md`](06_system_ui/modify_flight_paths.md)

**Automation: Full Auto** | **pywowlib: Complete**

Every step has a dedicated high-level API. `register_taxi_node()` creates nodes,
`register_flight_path()` creates paths with auto-generated waypoints, and
`SQLGenerator` handles flight master NPC spawns.

**What pywowlib covers:**
- `register_taxi_node()` -- TaxiNodes.dbc with mount display IDs
- `register_taxi_path()` -- TaxiPath.dbc with cost
- `register_taxi_path_node()` -- TaxiPathNode.dbc with position/delay
- `register_flight_path()` -- convenience wrapper (creates path + all waypoints)
- `SQLGenerator.add_npc()` -- flight master NPC (npcflag 8192)
- `SQLGenerator.add_spawn()` -- NPC world placement

**External tools:** None.

**AI agent opportunity:** Fully automatable. AI can design flight networks,
generate parabolic arc waypoints for smooth flight curves, and create all NPCs.

---

## Integration Priority Recommendations

Most high-impact schemas and features have been implemented. Below is the updated
status of each originally-identified gap.

### Implemented (all use cases unblocked)

| Schema/Feature | Use Cases | Status |
|----------------|-----------|--------|
| **`Spell.dbc` convenience wrapper** (234 fields, 936 bytes) | #6, #7, #9, #14, #16 | `register_spell()`, `modify_spell()` |
| **`SkillLineAbility.dbc` schema** (14 fields, 56 bytes) | #6, #9, #14 | `register_skill_line_ability()` |
| **vmap/mmap subprocess integration** | #1, #2 | `generate_vmaps()`, `generate_mmaps()`, `generate_server_data()` |
| **`Item.dbc` schema** (8 fields, 32 bytes) | #11, #14 | `register_item()` |
| **`ItemSet.dbc` schema** (53 fields, 212 bytes) | #12 | `register_item_set()` |
| **`SoundEntries.dbc` schema** (30 fields, 120 bytes) | #4 | `register_sound_entry()` |
| **`CreatureDisplayInfo.dbc` schema** (16 fields, 64 bytes) | #15 | `register_creature_display()` |
| **`CreatureModelData.dbc` schema** (28 fields, 112 bytes) | #15 | `register_creature_model()` |
| **`Talent.dbc` schema** (23 fields, 92 bytes) | #8 | `register_talent()` |
| **`TalentTab.dbc` schema** (24 fields, 96 bytes) | #8 | `register_talent_tab()` |
| **`SpellIcon.dbc` schema** (2 fields, 8 bytes) | #6 | `register_spell_icon()` |
| **`GameObjectDisplayInfo.dbc` schema** (19 fields, 76 bytes) | #21 | `register_gameobject_display()` |
| **`ZoneIntroMusicTable.dbc` schema** (5 fields, 20 bytes) | #4 | `register_zone_intro_music()` |
| **AddOn scaffold generator** | #24 | `generate_addon()` |
| **ADT doodad/WMO insertion API** | #3 | `add_doodad_to_adt()`, `add_wmo_to_adt()` |

### Remaining Gaps (nice to have)

| Schema/Feature | Use Cases | Effort | Notes |
|----------------|-----------|--------|-------|
| `ItemDisplayInfo.dbc` schema (26 fields) | #11 | Medium | Not needed when reusing existing display IDs |
| `SpellVisual.dbc` / `SpellVisualKit.dbc` | #6 | Medium-High | Reuse existing visual IDs for now |
| `ChrRaces.dbc` + `CharStartOutfit.dbc` | #23 (reskin only) | Medium | Only useful for race reskins; new races need C++ core changes |

### Not Worth Integrating

| Tool | Reason |
|------|--------|
| Noggit | Full 3D GUI editor -- orthogonal to headless API |
| C++ server core compilation | Different development paradigm |
| Client binary patching | Reverse engineering, not file generation |
| 3D modeling tools (Blender, etc.) | Creative tooling, out of scope |
| M2 model editing | Per-model manual work, no batch automation path |

---

## Converter Tools

The `tools/` directory provides bidirectional binary-to-JSON converters for all major WoW
3.3.5a file formats. These support data inspection, manual JSON editing, and round-trip
reconstruction -- useful for debugging, auditing, and understanding game data before
programmatic modification via the world builder APIs.

| Tool | Format | Capabilities |
|------|--------|-------------|
| `dbc_converter.py` | DBC | DBD schema-aware named fields for 236/247 WotLK tables; generic fallback for the rest |
| `adt_converter.py` | ADT | Full chunk-level terrain data: heightmaps, textures, alpha maps, doodad/WMO placements |
| `wdt_converter.py` | WDT | Active tile grid with ASCII visualization; reads via `wdt_generator.read_wdt()` |
| `wdl_converter.py` | WDL | Low-res flight-view heightmaps with outer 17x17 and inner 16x16 grids per tile |
| `wmo_converter.py` | WMO | Auto-detects root vs. group files; materials, portals, doodad sets, BSP trees, geometry |

All converters support `--dir` for batch conversion and produce lossless round-trip output
(binary → JSON → binary produces identical files).

**Typical workflow:**

1. Extract binary files from MPQ archives using `MPQExtractor` or external tools
2. Batch-convert to JSON for inspection: `python tools/dbc_converter.py dbc2json --dir ./dbc_files -o ./json`
3. Review/edit JSON as needed
4. Convert back to binary: `python tools/dbc_converter.py json2dbc edited.json -o output.dbc`
5. Pack modified files into MPQ patches via `MPQPacker`

These tools complement every use case above by enabling data-driven debugging -- for example,
inspecting existing `Spell.dbc` records before using `modify_spell()`, or reviewing ADT
terrain data before inserting doodads via `add_doodad_to_adt()`.
