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
| 1 | [Add New Zone](#1-add-new-zone-exterior) | Full Auto | Mostly | vmap/mmap generators | Yes |
| 2 | [Add New Dungeon](#2-add-new-dungeon-instance) | Full Auto | Mostly | vmap/mmap generators | Yes |
| 3 | [Update Zone Scenery](#3-update-zone-scenery) | AI-Assisted | Mostly | Noggit (visual placement) | No |
| 4 | [Add Custom Music](#4-add-custom-music) | Full Auto | Partial | Audio creation tools | Partial |
| 5 | [Change Loading Screen](#5-change-loading-screen) | Full Auto | Complete | Image editing (optional) | No |
| 6 | [Add New Spell](#6-add-new-spell) | Semi-Auto | Partial | -- | Yes |
| 7 | [Change Spell Data](#7-change-spell-data) | AI-Assisted | Partial | -- | Yes |
| 8 | [Modify Talent Tree](#8-modify-talent-tree) | Semi-Auto | Minimal | -- | Yes |
| 9 | [Change Racial Traits](#9-change-racial-traits) | Semi-Auto | Partial | -- | Yes |
| 10 | [Add New Class](#10-add-new-class) | Not Feasible | Minimal | C++ core rewrite | No |
| 11 | [Add New Item](#11-add-new-item) | Semi-Auto | Partial | 3D modeling (custom models) | Partial |
| 12 | [Create Item Set](#12-create-item-set) | AI-Assisted | Partial | -- | Yes |
| 13 | [Modify Loot Tables](#13-modify-loot-tables) | Full Auto | Complete | -- | -- |
| 14 | [Custom Crafting Recipe](#14-custom-crafting-recipe) | Semi-Auto | Partial | -- | Yes |
| 15 | [Add New Creature](#15-add-new-creature) | Full Auto* | Mostly* | 3D modeling (custom models) | Partial |
| 16 | [Update Boss Mechanics](#16-update-boss-mechanics) | Full Auto | Mostly | C++ scripting (non-Eluna) | No |
| 17 | [Add Vendor/Trainer](#17-add-vendortrainer) | Full Auto | Complete | -- | -- |
| 18 | [Change NPC Pathing](#18-change-npc-pathing) | Full Auto | Complete | -- | -- |
| 19 | [Add New Quest](#19-add-new-quest) | Full Auto | Complete | -- | -- |
| 20 | [Create Quest Chain](#20-create-quest-chain) | Full Auto | Complete | -- | -- |
| 21 | [Add Object Interaction](#21-add-object-interaction) | AI-Assisted | Mostly | 3D modeling (custom models) | Partial |
| 22 | [Custom Teleporter](#22-custom-teleporter) | Full Auto | Complete | -- | -- |
| 23 | [Add Playable Race](#23-add-playable-race) | Not Feasible | Minimal | C++ core, M2 mass editing | No |
| 24 | [Custom UI Frame](#24-custom-ui-frame) | AI-Assisted | None | -- | Yes |
| 25 | [Modify Flight Paths](#25-modify-flight-paths) | Full Auto | Complete | -- | -- |

\* When reusing existing models. Custom models require external 3D tools.

---

## Detailed Assessments

### Category 1: World Building & Environment

#### 1. Add New Zone (Exterior)

**File:** [`01_world_building_environment/add_new_zone.md`](01_world_building_environment/add_new_zone.md)

**Automation: Full Auto** | **pywowlib: Mostly Complete**

The high-level `build_zone()` function orchestrates the entire pipeline: DBC
registration (`Map.dbc`, `AreaTable.dbc`, `WorldMapArea.dbc`, `LoadingScreens.dbc`),
WDT generation, ADT creation with heightmaps and texture splatting, artwork
generation (world maps, loading screens, minimaps), and MPQ packing. The
`TerrainSculptor` can generate procedural terrain with noise, primitives, texture
painting, and doodad scattering.

**What pywowlib covers:**
- `build_zone()` -- full end-to-end pipeline
- `DBCInjector` -- Map, AreaTable, WorldMapArea, WorldMapOverlay, LoadingScreens, ZoneMusic, SoundAmbience, Light
- `TerrainSculptor` -- procedural heightmaps, texture rules, doodad placement
- `create_adt()` / `create_wdt()` -- binary terrain generation
- `artwork_pipeline` -- world maps, loading screens, subzone overlays
- `MPQPacker` -- client patch assembly
- `SQLGenerator.add_zone()` -- server-side zone registration

**Gap: Server-side collision and pathing.**
The WoW server needs `.vmap` and `.mmap` files for line-of-sight and NPC navigation.
These are generated by `vmap4extractor` + `vmap4assembler` + `mmaps_generator` from
the AzerothCore/TrinityCore toolchain, which read the client terrain files and
produce server-side navigation meshes.

**External tools:**
| Tool | Purpose | Integrate into pywowlib? |
|------|---------|--------------------------|
| `vmap4extractor` + `vmap4assembler` | Server collision (LoS) | **Yes** -- call as subprocess after ADT/WMO generation. Add `generate_vmaps(map_name, client_dir, output_dir)` to world_builder |
| `mmaps_generator` | Server NPC pathing (Recast/Detour) | **Yes** -- call as subprocess. Add `generate_mmaps(map_name, vmap_dir, output_dir)` |
| Noggit | Visual terrain editing | **No** -- full GUI application, orthogonal to headless pipeline |

**AI agent opportunity:** An AI agent can fully automate zone creation by:
generating a zone definition from a text description, calling `TerrainSculptor` to
produce terrain, running `build_zone()`, and optionally triggering vmap/mmap
generation.

---

#### 2. Add New Dungeon (Instance)

**File:** [`01_world_building_environment/add_new_dungeon.md`](01_world_building_environment/add_new_dungeon.md)

**Automation: Full Auto** | **pywowlib: Mostly Complete**

`build_dungeon()` generates WMO root + group files from room primitives
(`BoxRoom`, `CircularRoom`, `Corridor`, `SpiralRamp`, `ChamberRoom`), registers
all DBC entries (`Map.dbc` with `instance_type=1`, `AreaTable.dbc`,
`DungeonEncounter.dbc`, `LFGDungeons.dbc`, `AreaTrigger.dbc`, `LoadingScreens.dbc`),
generates spawn coordinates, and packs into MPQ. `ScriptGenerator` produces Eluna
Lua scripts for boss encounters with multi-phase logic, timers, and add spawning.
`SQLGenerator` handles all server-side tables.

**What pywowlib covers:**
- `build_dungeon()` -- WMO geometry + DBC + MPQ pipeline
- Room primitives with materials, portals, lighting, BSP trees
- `ScriptGenerator.add_instance_script()` -- door/gate logic, boss binding
- `ScriptGenerator.add_boss_encounter()` -- multi-phase bosses
- `SpellRegistry` -- boss ability ID management
- `SQLGenerator.add_dungeon()` -- instance_template, access_requirement
- `export_spawn_coordinates()` -- NPC/boss placement

**Gap: Same vmap/mmap gap as zones.** Also, servers using C++ `InstanceScript`
instead of Eluna need manual scripting.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| vmap/mmap generators | Server collision/pathing | **Yes** (same as zones) |
| C++ compiler | Non-Eluna instance scripts | **No** -- different paradigm, out of scope |

**AI agent opportunity:** Dungeon layout design from text descriptions, encounter
scripting from boss ability descriptions, full end-to-end generation.

---

#### 3. Update Zone Scenery

**File:** [`01_world_building_environment/update_zone_scenery.md`](01_world_building_environment/update_zone_scenery.md)

**Automation: AI-Assisted** | **pywowlib: Mostly Complete**

`read_adt()` parses existing terrain into editable Python structures (heightmaps,
textures, splat maps, doodad/WMO instances). Modifications are applied
programmatically and written back with `create_adt()`. `MPQExtractor` reads from
existing archives, `MPQPacker` rebuilds patches. `import_heightmap_from_adt()` and
`import_texture_rules_from_adt()` support reverse-engineering existing terrain.

**What pywowlib covers:**
- `MPQExtractor` -- read existing MPQ archives
- `read_adt()` -- parse ADT into heightmap, textures, splat, doodads, WMOs
- `import_heightmap_from_adt()` / `import_texture_rules_from_adt()` -- extraction
- `TerrainSculptor` primitives -- apply modifications to heightmaps
- `create_adt()` -- write modified terrain back
- `MPQPacker` -- repack into client patch

**Gap: Visual object placement.** Placing doodads (`.m2` trees, rocks) and WMOs
(buildings) at specific world coordinates requires knowing their positions in 3D
space. pywowlib can write placement data (`MDDF`/`MODF` chunks in ADT) but has no
visual preview for choosing positions.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| Noggit | Visual doodad/WMO placement | **No** -- full 3D editor, orthogonal to headless API |

**Integration opportunity:** Add coordinate-based `add_doodad_to_adt(adt_data,
m2_path, position, rotation, scale)` and `add_wmo_to_adt(adt_data, wmo_path,
position, rotation)` convenience functions. The `DoodadScatterEngine` and
`WMOPlacementEngine` in `terrain_sculptor.py` already do this for new terrain but
lack an API for modifying existing ADTs.

**AI agent opportunity:** An AI agent can interpret descriptions like "make Elwynn
Forest darker" by adjusting texture layers, modifying lighting via `register_light()`,
and swapping texture paths in ADT data.

---

#### 4. Add Custom Music

**File:** [`01_world_building_environment/add_custom_music.md`](01_world_building_environment/add_custom_music.md)

**Automation: Full Auto** | **pywowlib: Partial**

`register_zone_music()` creates `ZoneMusic.dbc` entries,
`register_sound_ambience()` creates `SoundAmbience.dbc` entries, and
`update_area_atmosphere()` links them to zones in `AreaTable.dbc`.
`MPQPacker` handles file placement.

**What pywowlib covers:**
- `register_zone_music()` -- ZoneMusic.dbc (8 fields, 32 bytes)
- `register_sound_ambience()` -- SoundAmbience.dbc (3 fields, 12 bytes)
- `update_area_atmosphere()` -- link music/ambience to AreaTable
- `register_light()` -- Light.dbc for atmosphere
- `MPQPacker.add_file()` -- place MP3 files in MPQ

**Gap: `SoundEntries.dbc` has no convenience wrapper.** ZoneMusic and
SoundAmbience reference `SoundEntries.dbc` IDs, but creating new sound entries
requires manually constructing 31-field records via the low-level `DBCInjector`.
Also, `ZoneIntroMusicTable.dbc` for zone entrance stingers has no wrapper.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| Audio creation (Audacity, etc.) | Create MP3 files | **No** -- creative tool, out of scope |
| `SoundEntries.dbc` schema | Register new sound entries | **Yes** -- add `register_sound_entry()` convenience wrapper |
| `ZoneIntroMusicTable.dbc` schema | Zone entrance music stingers | **Yes** -- add `register_zone_intro_music()` |

**AI agent opportunity:** Fully automatable given existing audio files. AI selects
tracks, assigns them to zones, and generates all DBC entries.

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

**Automation: Semi-Auto** | **pywowlib: Partial**

`SpellRegistry` manages spell ID allocation (base 90000+) with name-to-ID
mapping, Lua/JSON export, and import. However, actually writing `Spell.dbc`
records (234+ fields) requires manual byte packing via the low-level
`DBCInjector`.

**What pywowlib covers:**
- `SpellRegistry` -- ID allocation, name tracking, Lua/JSON export
- `DBCInjector` (low-level) -- can read/write any DBC including Spell.dbc
- `SQLGenerator` -- server-side `spell_linked_spell`, `spell_bonus_data`
- `ScriptGenerator` -- Eluna Lua for custom spell handlers

**Gap: No `Spell.dbc` convenience wrapper.** Spell.dbc has 234 fields (936 bytes
per record) covering mechanics, visuals, targeting, costs, cooldowns, and effects.
Constructing records manually is error-prone. Also missing:
- `SpellIcon.dbc` -- spell icon assignment (no schema)
- `SpellVisual.dbc` -- spell visual effects (no schema)
- `SpellVisualKit.dbc` -- visual kit composition (no schema)

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `Spell.dbc` schema | Spell creation | **Yes -- high priority.** Add `register_spell_dbc(dbc_dir, spell_def)` with named fields for the most-used subset (name, school, cast_time, cooldown, range, effects, icon, mana_cost, description) |
| `SpellIcon.dbc` schema | Icon assignment | **Yes** -- small DBC, simple schema |
| `SpellVisual.dbc` schema | Visual effects | **Yes** -- useful but large schema; start with reuse of existing visual IDs |
| Server C++ | Custom spell mechanics | **No** -- requires core modification |

**AI agent opportunity:** An AI agent could design spell parameters (damage, cost,
cooldown, effect type) from a text description, but currently needs manual DBC byte
packing. With a `Spell.dbc` wrapper this becomes fully automatable.

---

#### 7. Change Spell Data

**File:** [`02_combat_classes_spells/change_spell_data.md`](02_combat_classes_spells/change_spell_data.md)

**Automation: AI-Assisted** | **pywowlib: Partial**

Modifying existing spell records (damage, mana cost, cast time, range, cooldown)
is conceptually simple but faces the same `Spell.dbc` schema gap. The low-level
`DBCInjector.get_record_field()` and direct byte manipulation work but require
knowing exact field offsets.

**What pywowlib covers:**
- `DBCInjector` (low-level) -- read existing Spell.dbc, modify fields by offset
- `SQLGenerator` -- `spell_bonus_data`, `spell_custom_attr` for server-side overrides

**Gap:** Same as Add New Spell -- no named-field access to `Spell.dbc`.

**External tools:** Same as #6. A `Spell.dbc` schema wrapper would make this
**Full Auto**.

**AI agent opportunity:** Highly suitable. An AI agent could implement balance
changes ("buff Fireball by 10%") by reading the current value at a known field
offset, computing the new value, and writing it back. With a schema wrapper, this
becomes trivial.

---

#### 8. Modify Talent Tree

**File:** [`02_combat_classes_spells/modify_talent_tree.md`](02_combat_classes_spells/modify_talent_tree.md)

**Automation: Semi-Auto** | **pywowlib: Minimal**

Talent trees involve `Talent.dbc` (position, tier, column, prerequisite arrows,
spell ranks) and `TalentTab.dbc` (tab background texture, class mask, order).
Neither has a convenience wrapper.

**What pywowlib covers:**
- `DBCInjector` (low-level) -- can read/write Talent.dbc and TalentTab.dbc
- `SpellRegistry` -- track talent spell IDs

**Gap:** No `Talent.dbc` schema (20+ fields including rank spell IDs and
prerequisite talent IDs). No `TalentTab.dbc` schema. Talent tree arrow rendering
depends on precise tier/column/prerequisite configuration that the UI interprets
client-side -- misconfigurations cause visual breaks.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `Talent.dbc` schema | Talent position and prerequisites | **Yes** -- add `register_talent()` with tier, column, rank_spells, prereq_talent |
| `TalentTab.dbc` schema | Tab definition | **Yes** -- add `register_talent_tab()` with class_mask, texture, order |
| Spell.dbc schema | Talent effect spells | **Yes** (same as #6) |

**AI agent opportunity:** Talent tree design is highly structured (tier/column grid
with prerequisite arrows). An AI agent could generate valid trees from descriptions,
but the UI fragility makes validation critical. A `validate_talent_tree()` function
would be valuable.

---

#### 9. Change Racial Traits

**File:** [`02_combat_classes_spells/change_racial_traits.md`](02_combat_classes_spells/change_racial_traits.md)

**Automation: Semi-Auto** | **pywowlib: Partial**

Racial traits are spells auto-learned via `SkillLineAbility.dbc`. Changing them
requires modifying `Spell.dbc` (the passive effect) and `SkillLineAbility.dbc`
(the auto-learn trigger).

**What pywowlib covers:**
- `DBCInjector` (low-level) -- read/write both DBCs
- `SpellRegistry` -- track new racial spell IDs
- `SQLGenerator` -- `player_levelstats` for base stat changes

**Gap:** No `SkillLineAbility.dbc` schema. No `Spell.dbc` convenience wrapper.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `SkillLineAbility.dbc` schema | Auto-learn configuration | **Yes** -- add `register_skill_line_ability()` |
| `Spell.dbc` schema | Racial passive spell | **Yes** (same as #6) |

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

**Automation: Semi-Auto** | **pywowlib: Partial**

`SQLGenerator.add_item()` generates complete `item_template` INSERT statements
with all columns (stats, class, subclass, quality, bonding, etc.). Client-side
requires `Item.dbc` (visual/sound link) and `ItemDisplayInfo.dbc` (model/texture
reference).

**What pywowlib covers:**
- `SQLGenerator.add_item()` -- full `item_template` with all stat fields
- `SQLGenerator.add_loot()` -- loot table entries
- `MPQPacker` -- pack custom M2/BLP models
- `blp_converter` -- texture conversion

**Gap:** No `Item.dbc` schema (6 fields: ID, ClassID, SubclassID, SoundOverrideSubclassID,
Material, DisplayInfoID, InventoryType). No `ItemDisplayInfo.dbc` schema (model paths,
texture paths, geoset groups, visual effects).

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `Item.dbc` schema | Client item registration | **Yes** -- add `register_item_dbc()`. Small schema (7 fields, 28 bytes) |
| `ItemDisplayInfo.dbc` schema | Visual/model link | **Yes** -- add `register_item_display()`. Medium schema (26 fields) |
| 3D modeling (Blender + M2 export) | Custom weapon/armor models | **No** -- creative tooling, out of scope |
| Existing display ID reuse | Use retail models | N/A -- no tool needed, just reference existing IDs |

**AI agent opportunity:** Fully automatable for items using existing display IDs
(which covers most cases -- recolored existing models). Custom models remain manual.

---

#### 12. Create Item Set

**File:** [`03_armory_items_loot/create_item_set.md`](03_armory_items_loot/create_item_set.md)

**Automation: AI-Assisted** | **pywowlib: Partial**

Item sets are defined in `ItemSet.dbc` (set name, item IDs, set spell bonuses at
2/3/4/5/6/7/8 piece thresholds). Server reads this DBC for bonus application.

**What pywowlib covers:**
- `SQLGenerator.add_item()` -- items with `itemset` field in `item_template`
- `DBCInjector` (low-level) -- can read/write ItemSet.dbc

**Gap:** No `ItemSet.dbc` convenience wrapper. The schema is moderate complexity:
ID, name (locstring), items[17] (up to 17 item IDs), spells[8] (bonus spell IDs),
thresholds[8] (piece count triggers), required_skill, required_skill_rank.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `ItemSet.dbc` schema | Set bonus definition | **Yes** -- add `register_item_set()` with item_ids, bonus_spells, thresholds |

**AI agent opportunity:** An AI agent could design tier sets with stat-appropriate
bonuses, generate all DBC entries, and create the matching items.

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

**Automation: Semi-Auto** | **pywowlib: Partial**

A crafting recipe is a "spell" (the craft action) linked to a "skill line"
(profession) that produces an "item" (the output). Requires `Spell.dbc` (craft
spell with SPELL_EFFECT_CREATE_ITEM), `SkillLineAbility.dbc` (link to profession),
and `item_template` (reagents and result).

**What pywowlib covers:**
- `SQLGenerator.add_item()` -- crafted item and reagent items
- `SpellRegistry` -- track recipe spell IDs
- `DBCInjector` (low-level) -- can write Spell.dbc and SkillLineAbility.dbc

**Gap:** Same `Spell.dbc` and `SkillLineAbility.dbc` schema gaps as #6 and #9.

**External tools:** Same spell-related schemas. With those wrappers, crafting
recipes become **Full Auto**.

---

### Category 4: Creatures & Encounters

#### 15. Add New Creature

**File:** [`04_creatures_encounters/add_new_creature.md`](04_creatures_encounters/add_new_creature.md)

**Automation: Full Auto\*** | **pywowlib: Mostly Complete**

\*Full Auto when using existing creature models (which is the common case).

`SQLGenerator.add_creature()` generates complete `creature_template` entries.
`SQLGenerator.add_spawn()` handles world placement. `SQLGenerator.add_creature_ai()`
generates SmartAI behaviors.

**What pywowlib covers:**
- `SQLGenerator.add_creature()` -- full creature_template
- `SQLGenerator.add_creatures()` -- batch creation
- `SQLGenerator.add_spawn()` / `add_spawns()` -- world placement
- `SQLGenerator.add_creature_ai()` / `add_smartai()` -- SmartAI behaviors
- `SQLGenerator.add_creature_loot()` -- loot tables
- `MPQPacker` -- pack custom M2/BLP models

**Gap:** No `CreatureDisplayInfo.dbc` schema (for custom models: model ID,
texture paths, extra display effects). No `CreatureModelData.dbc` schema (model
file path, collision, bounding box). Not needed when reusing existing display IDs.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `CreatureDisplayInfo.dbc` schema | Custom creature display | **Yes** -- add `register_creature_display()` |
| `CreatureModelData.dbc` schema | Custom model data | **Yes** -- add `register_creature_model()` |
| 3D modeling (Blender + M2 export) | Custom creature models | **No** -- creative tooling |

**AI agent opportunity:** Fully automatable for creatures using existing models. AI
can select appropriate display IDs, design stats, create AI behaviors, and place
spawns from text descriptions.

---

#### 16. Update Boss Mechanics

**File:** [`04_creatures_encounters/update_boss_mechanics.md`](04_creatures_encounters/update_boss_mechanics.md)

**Automation: Full Auto** | **pywowlib: Mostly Complete**

`ScriptGenerator.add_boss_encounter()` produces complete multi-phase Eluna Lua
scripts with timers, spell rotations, add spawning, void zones, and phase
transitions. `SpellRegistry` manages boss ability IDs. `SQLGenerator` handles
`creature_text` (boss yells), `creature_template`, and SmartAI fallback.

**What pywowlib covers:**
- `ScriptGenerator.add_boss_encounter()` -- multi-phase Eluna Lua
- `ScriptGenerator.add_instance_script()` -- instance-wide logic
- `SpellRegistry` -- boss spell ID management with Lua/JSON export
- `SQLGenerator.add_creature_ai()` -- SmartAI alternative
- `SQLGenerator` -- creature_text, creature_template, spawn placement

**Gap:** C++ `InstanceScript` for non-Eluna servers. This is a fundamentally
different scripting paradigm that requires recompiling the server core.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| C++ compiler | Non-Eluna instance scripts | **No** -- different paradigm |
| Spell.dbc schema | Boss ability spells | **Yes** (same as #6) |

**AI agent opportunity:** Highly suitable. An AI agent can design complete boss
encounters from descriptions ("3-phase fight, enrages at 20%, summons adds in
phase 2"), generate all scripts and SQL.

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

**Automation: AI-Assisted** | **pywowlib: Mostly Complete**

`SQLGenerator.add_gameobject_template()` and `add_gameobject_spawn()` handle the
server-side tables. SmartAI scripting covers interactive behaviors.

**What pywowlib covers:**
- `SQLGenerator.add_gameobject_template()` -- all gameobject types (DOOR, CHEST, QUESTGIVER, GOOBER, etc.)
- `SQLGenerator.add_gameobject_spawn()` -- world placement with quaternion rotation
- `SQLGenerator.add_smartai()` -- interactive behaviors
- `SQLGenerator.add_loot()` -- chest/container loot

**Gap:** No `GameObjectDisplayInfo.dbc` schema for custom gameobject models.
When using existing display IDs (most cases), this is fully covered.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| `GameObjectDisplayInfo.dbc` schema | Custom display models | **Partial** -- add `register_gameobject_display()` for completeness, but existing display IDs cover most needs |

**AI agent opportunity:** Fully automatable with existing display IDs. AI can
design interactive objects, chest puzzles, and quest objectives.

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

**Automation: AI-Assisted** | **pywowlib: None**

WoW AddOns are `.toc` + `.xml` + `.lua` files that use the client's AddOn API.
This is entirely outside pywowlib's domain (pywowlib works with binary formats
and server SQL, not AddOn Lua/XML).

**What pywowlib covers:** Nothing directly. `MPQPacker` can package AddOns into
MPQ for server-wide distribution.

**Gap:** No AddOn scaffolding, template generation, or XML/Lua code generation.

**External tools:**
| Tool | Purpose | Integrate? |
|------|---------|------------|
| Text editor + WoW API reference | AddOn development | N/A |
| AddOn scaffolding generator | Template generation | **Yes -- consider adding.** A `generate_addon_scaffold(name, frames, events)` function could produce TOC + boilerplate Lua + XML. Low effort, moderate value for mod teams |

**AI agent opportunity:** Highly suitable for AI generation. An AI agent can
produce complete AddOns from descriptions, but this is standalone code generation
rather than pywowlib API usage.

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

Based on the assessment above, here are the DBC schemas and features that would
have the highest impact if added to pywowlib, ordered by how many use cases they
unblock:

### High Priority (unblocks 5+ use cases)

| Schema/Feature | Use Cases Unblocked | Effort |
|----------------|---------------------|--------|
| **`Spell.dbc` convenience wrapper** | #6, #7, #9, #14, #16 (boss abilities) | High (234 fields, but can wrap common subset) |
| **`SkillLineAbility.dbc` schema** | #6, #9, #14 | Low (14 fields) |
| **vmap/mmap subprocess integration** | #1, #2 | Medium (subprocess calls, path management) |

### Medium Priority (unblocks 2-3 use cases)

| Schema/Feature | Use Cases Unblocked | Effort |
|----------------|---------------------|--------|
| **`Item.dbc` schema** | #11, #14 | Low (7 fields, 28 bytes) |
| **`ItemDisplayInfo.dbc` schema** | #11 | Medium (26 fields) |
| **`ItemSet.dbc` schema** | #12 | Medium (locstring + arrays) |
| **`SoundEntries.dbc` schema** | #4 | Medium (31 fields) |
| **`CreatureDisplayInfo.dbc` schema** | #15 | Medium |
| **`CreatureModelData.dbc` schema** | #15 | Medium |
| **`Talent.dbc` + `TalentTab.dbc` schemas** | #8 | Medium |

### Low Priority (nice to have)

| Schema/Feature | Use Cases Unblocked | Effort |
|----------------|---------------------|--------|
| `SpellIcon.dbc` schema | #6 | Low |
| `GameObjectDisplayInfo.dbc` schema | #21 | Low |
| `ZoneIntroMusicTable.dbc` schema | #4 | Low |
| AddOn scaffold generator | #24 | Low-Medium |
| `ChrRaces.dbc` + `CharStartOutfit.dbc` schemas | #23 (reskin only) | Medium |
| ADT doodad/WMO insertion API (for existing ADTs) | #3 | Medium |

### Not Worth Integrating

| Tool | Reason |
|------|--------|
| Noggit | Full 3D GUI editor -- orthogonal to headless API |
| C++ server core compilation | Different development paradigm |
| Client binary patching | Reverse engineering, not file generation |
| 3D modeling tools (Blender, etc.) | Creative tooling, out of scope |
| M2 model editing | Per-model manual work, no batch automation path |
