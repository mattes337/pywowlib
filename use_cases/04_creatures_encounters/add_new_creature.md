# Add New Creature

**Complexity**: Medium to Advanced
**Estimated Time**: 30-90 minutes (varies with custom model work)
**Applies To**: WoW WotLK 3.3.5a (build 12340) with AzerothCore

---

## Overview

This guide walks through every step required to add a completely new creature (NPC or mob) to your WoW 3.3.5a private server using the pywowlib `world_builder` toolkit. The process has two main tracks:

1. **Server-side only** (reusing an existing model): Define the creature in the `creature_template` table, place spawns in the `creature` table, and optionally configure cosmetic addons. No client patches required.
2. **Client + Server** (custom model): Register the model in `CreatureModelData.dbc` and `CreatureDisplayInfo.dbc` on the client, place the `.m2` and `.blp` model files inside the client MPQ, then perform the same server-side work.

The pywowlib toolkit provides `SQLGenerator` for all server-side SQL and `DBCInjector` for all client-side DBC modifications.

---

## Prerequisites

- Python 3.8+ with pywowlib installed or accessible on `PYTHONPATH`
- Access to your AzerothCore `acore_world` database (MySQL/MariaDB)
- Extracted WotLK 3.3.5a DBC files (from `Data/enUS/locale-enUS.MPQ` or equivalent)
- For custom models: a `.m2` model file and associated `.blp` textures, plus an MPQ packing tool or custom patch MPQ
- Familiarity with in-game GM commands for testing (`.npc add`, `.reload creature_template`)

---

## Table of Contents

1. [Decide: Existing Model vs. Custom Model](#step-1-decide-existing-model-vs-custom-model)
2. [Client-Side: Register a Custom Model in DBC Files](#step-2-client-side-register-a-custom-model-in-dbc-files)
3. [Client-Side: Place Model Files in the MPQ](#step-3-client-side-place-model-files-in-the-mpq)
4. [Server-Side: Create creature_template with SQLGenerator](#step-4-server-side-create-creature_template-with-sqlgenerator)
5. [Server-Side: Add Creature Spawns](#step-5-server-side-add-creature-spawns)
6. [Server-Side: Configure creature_addon](#step-6-server-side-configure-creature_addon)
7. [Server-Side: Assign SmartAI Behavior (Optional)](#step-7-server-side-assign-smartai-behavior-optional)
8. [Complete Working Example](#step-8-complete-working-example)
9. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
10. [Cross-References](#cross-references)

---

## Step 1: Decide -- Existing Model vs. Custom Model

Before writing any code, determine which visual model your creature will use.

### Option A: Reuse an Existing Model (No Client Patches)

WoW 3.3.5a ships with thousands of creature models. You can reuse any of them by referencing their `displayid` in `creature_template.modelid1`. Look up existing display IDs using:

- The `creature_template` table in your database (find a creature that looks similar)
- The WoWHead classic database or community DBC viewers
- In-game with `.lookup creature <name>` and then `.npc info` on the target

Common display IDs for reference:

| Display ID | Creature | Notes |
|-----------|----------|-------|
| 15880 | Human Male (generic NPC) | Good for quest givers |
| 17519 | Blood Elf Female (generic) | Good for vendors |
| 24191 | Vrykul Warrior | Large humanoid |
| 26693 | Lich King (Arthas) | Boss-tier |
| 28213 | Proto-Drake | Flying mount/creature |

If you choose this option, skip directly to [Step 4](#step-4-server-side-create-creature_template-with-sqlgenerator).

### Option B: Use a Custom Model (Client + Server)

If you have a custom `.m2` model created in a tool like WoW Model Viewer, Blender with WoW export plugins, or another modding tool, you need to:

1. Register the model path in `CreatureModelData.dbc`
2. Register the display appearance in `CreatureDisplayInfo.dbc`
3. Place the model/texture files in a client-side patch MPQ

Proceed to [Step 2](#step-2-client-side-register-a-custom-model-in-dbc-files).

---

## Step 2: Client-Side -- Register a Custom Model in DBC Files

This step uses the `DBCInjector` class to modify two DBC files that must be distributed to all game clients.

### 2.1 CreatureModelData.dbc

This DBC maps model IDs to `.m2` file paths. Each creature display references a model data entry.

**DBC Layout (WotLK 3.3.5a):**

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | ID | uint32 | Unique model data ID |
| 1 | Flags | uint32 | Model flags (typically 0) |
| 2 | ModelName | string | Path to .m2 file (string block offset) |
| 3 | SizeClass | uint32 | Size class (0=small, 1=medium, 2=large) |
| 4 | ModelScale | float | Base model scale (1.0 = normal) |
| 5 | BloodID | uint32 | Blood splash effect ID |
| 6 | FootprintTextureID | uint32 | Footprint texture ID |
| 7 | FootprintTextureLength | float | Footprint texture length |
| 8 | FootprintTextureWidth | float | Footprint texture width |
| 9 | FootprintParticleScale | float | Footprint particle scale |
| 10 | FoleyMaterialID | uint32 | Footstep sound material |
| 11 | FootstepShakeSize | uint32 | Camera shake on footstep |
| 12 | DeathThudShakeSize | uint32 | Camera shake on death |
| 13 | SoundID | uint32 | Sound ID reference |
| 14 | CollisionWidth | float | Collision box width |
| 15 | CollisionHeight | float | Collision box height |
| 16 | MountHeight | float | Mount point height |
| 17 | GeoBoxMinX | float | Bounding box min X |
| 18 | GeoBoxMinY | float | Bounding box min Y |
| 19 | GeoBoxMinZ | float | Bounding box min Z |
| 20 | GeoBoxMaxX | float | Bounding box max X |
| 21 | GeoBoxMaxY | float | Bounding box max Y |
| 22 | GeoBoxMaxZ | float | Bounding box max Z |
| 23 | WorldEffectScale | float | Particle/effect scale |
| 24 | AttachedEffectScale | float | Attached effect scale |
| 25 | MissileCollisionRadius | float | Projectile collision radius |
| 26 | MissileCollisionPush | float | Projectile collision push |
| 27 | MissileCollisionRaise | float | Projectile collision raise |

**Record Size**: 28 fields = 112 bytes

**Python code to inject a CreatureModelData record:**

```python
import struct
from world_builder.dbc_injector import DBCInjector

def register_creature_model_data(
    dbc_dir,
    model_path,          # e.g. "Creature\\CustomBeast\\CustomBeast.m2"
    model_id=None,
    model_scale=1.0,
    size_class=1,        # 0=small, 1=medium, 2=large
    collision_width=0.5,
    collision_height=2.0,
    mount_height=0.0,
):
    """
    Register a new model in CreatureModelData.dbc.

    Args:
        dbc_dir: Path to directory containing CreatureModelData.dbc.
        model_path: MPQ-internal path to the .m2 file.
        model_id: Specific ID or None for auto (max_id + 1).
        model_scale: Base display scale (1.0 = normal size).
        size_class: 0=small, 1=medium, 2=large.
        collision_width: Width of collision cylinder.
        collision_height: Height of collision cylinder.
        mount_height: Height offset for mounting (0 if not mountable).

    Returns:
        int: The assigned model data ID.
    """
    import os
    filepath = os.path.join(dbc_dir, 'CreatureModelData.dbc')
    dbc = DBCInjector(filepath)

    if model_id is None:
        model_id = dbc.get_max_id() + 1

    # Add model path string to string block
    model_path_offset = dbc.add_string(model_path)

    # Build the 112-byte record (28 uint32/float fields)
    buf = bytearray()
    buf += struct.pack('<I', model_id)              # 0: ID
    buf += struct.pack('<I', 0)                     # 1: Flags
    buf += struct.pack('<I', model_path_offset)     # 2: ModelName (string offset)
    buf += struct.pack('<I', size_class)            # 3: SizeClass
    buf += struct.pack('<f', model_scale)           # 4: ModelScale
    buf += struct.pack('<I', 0)                     # 5: BloodID
    buf += struct.pack('<I', 0)                     # 6: FootprintTextureID
    buf += struct.pack('<f', 0.0)                   # 7: FootprintTextureLength
    buf += struct.pack('<f', 0.0)                   # 8: FootprintTextureWidth
    buf += struct.pack('<f', 0.0)                   # 9: FootprintParticleScale
    buf += struct.pack('<I', 0)                     # 10: FoleyMaterialID
    buf += struct.pack('<I', 0)                     # 11: FootstepShakeSize
    buf += struct.pack('<I', 0)                     # 12: DeathThudShakeSize
    buf += struct.pack('<I', 0)                     # 13: SoundID
    buf += struct.pack('<f', collision_width)        # 14: CollisionWidth
    buf += struct.pack('<f', collision_height)       # 15: CollisionHeight
    buf += struct.pack('<f', mount_height)           # 16: MountHeight
    # Bounding box (reasonable defaults for a medium creature)
    buf += struct.pack('<f', -1.0)                  # 17: GeoBoxMinX
    buf += struct.pack('<f', -1.0)                  # 18: GeoBoxMinY
    buf += struct.pack('<f', 0.0)                   # 19: GeoBoxMinZ
    buf += struct.pack('<f', 1.0)                   # 20: GeoBoxMaxX
    buf += struct.pack('<f', 1.0)                   # 21: GeoBoxMaxY
    buf += struct.pack('<f', 2.0)                   # 22: GeoBoxMaxZ
    buf += struct.pack('<f', 1.0)                   # 23: WorldEffectScale
    buf += struct.pack('<f', 1.0)                   # 24: AttachedEffectScale
    buf += struct.pack('<f', 0.0)                   # 25: MissileCollisionRadius
    buf += struct.pack('<f', 0.0)                   # 26: MissileCollisionPush
    buf += struct.pack('<f', 0.0)                   # 27: MissileCollisionRaise

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return model_id
```

### 2.2 CreatureDisplayInfo.dbc

This DBC defines the visual appearance of a creature: which model to use, what textures to apply, what scale, opacity, and sound configuration.

**DBC Layout (WotLK 3.3.5a):**

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | ID | uint32 | Unique display ID (this is what creature_template references) |
| 1 | ModelID | uint32 | FK to CreatureModelData.dbc |
| 2 | SoundID | uint32 | CreatureSoundData.dbc reference |
| 3 | ExtendedDisplayInfoID | uint32 | CreatureDisplayInfoExtra.dbc (armor appearance) |
| 4 | CreatureModelScale | float | Scale multiplier (stacks with model base scale) |
| 5 | CreatureModelAlpha | uint32 | Opacity: 255 = fully opaque, 0 = invisible |
| 6 | TextureVariation1 | string | Primary texture override (string offset) |
| 7 | TextureVariation2 | string | Secondary texture override (string offset) |
| 8 | TextureVariation3 | string | Tertiary texture override (string offset) |
| 9 | PortraitTextureName | string | Portrait icon texture (string offset) |
| 10 | BloodLevel | uint32 | Blood splatter intensity |
| 11 | BloodID | uint32 | UnitBloodLevels.dbc reference |
| 12 | NPCSoundID | uint32 | NPC ambient sound reference |
| 13 | ParticleColorID | uint32 | Particle color override |

**Record Size**: 14 fields = 56 bytes

**Python code to inject a CreatureDisplayInfo record:**

```python
def register_creature_display_info(
    dbc_dir,
    model_id,               # FK to CreatureModelData.dbc
    display_id=None,
    scale=1.0,
    opacity=255,
    sound_id=0,
    extended_display_info=0,
    texture1='',
    texture2='',
    texture3='',
    portrait_texture='',
    blood_level=0,
    blood_id=0,
    npc_sound_id=0,
    particle_color_id=0,
):
    """
    Register a new creature display in CreatureDisplayInfo.dbc.

    Args:
        dbc_dir: Path to directory containing CreatureDisplayInfo.dbc.
        model_id: CreatureModelData.dbc ID for the 3D model.
        display_id: Specific ID or None for auto (max_id + 1).
        scale: Display scale multiplier (1.0 = use model default).
        opacity: Alpha transparency (255 = opaque, 0 = invisible).
        sound_id: CreatureSoundData reference (0 = silent).
        extended_display_info: CreatureDisplayInfoExtra reference (0 = none).
        texture1: Primary texture variation filename (empty = use model default).
        texture2: Secondary texture variation.
        texture3: Tertiary texture variation.
        portrait_texture: Unit portrait texture path.
        blood_level: Blood splatter intensity.
        blood_id: UnitBloodLevels.dbc reference.
        npc_sound_id: Ambient NPC sound.
        particle_color_id: Particle color override.

    Returns:
        int: The assigned display ID.
    """
    import os
    filepath = os.path.join(dbc_dir, 'CreatureDisplayInfo.dbc')
    dbc = DBCInjector(filepath)

    if display_id is None:
        display_id = dbc.get_max_id() + 1

    # Add texture strings to string block
    tex1_offset = dbc.add_string(texture1) if texture1 else 0
    tex2_offset = dbc.add_string(texture2) if texture2 else 0
    tex3_offset = dbc.add_string(texture3) if texture3 else 0
    portrait_offset = dbc.add_string(portrait_texture) if portrait_texture else 0

    # Build the 56-byte record (14 fields)
    buf = bytearray()
    buf += struct.pack('<I', display_id)              # 0: ID
    buf += struct.pack('<I', model_id)                # 1: ModelID
    buf += struct.pack('<I', sound_id)                # 2: SoundID
    buf += struct.pack('<I', extended_display_info)    # 3: ExtendedDisplayInfoID
    buf += struct.pack('<f', scale)                    # 4: CreatureModelScale
    buf += struct.pack('<I', opacity)                  # 5: CreatureModelAlpha
    buf += struct.pack('<I', tex1_offset)              # 6: TextureVariation1
    buf += struct.pack('<I', tex2_offset)              # 7: TextureVariation2
    buf += struct.pack('<I', tex3_offset)              # 8: TextureVariation3
    buf += struct.pack('<I', portrait_offset)          # 9: PortraitTextureName
    buf += struct.pack('<I', blood_level)              # 10: BloodLevel
    buf += struct.pack('<I', blood_id)                 # 11: BloodID
    buf += struct.pack('<I', npc_sound_id)             # 12: NPCSoundID
    buf += struct.pack('<I', particle_color_id)        # 13: ParticleColorID

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return display_id
```

### 2.3 Putting It Together -- Register Both DBC Entries

```python
# Register the 3D model file path
model_id = register_creature_model_data(
    dbc_dir='./output/dbc/',
    model_path='Creature\\StormElemental\\StormElemental.m2',
    model_scale=1.5,        # 50% larger than default
    size_class=2,            # Large creature
    collision_width=1.0,
    collision_height=3.0,
)
print(f"Assigned ModelData ID: {model_id}")

# Register the display appearance using that model
display_id = register_creature_display_info(
    dbc_dir='./output/dbc/',
    model_id=model_id,
    scale=1.0,
    opacity=255,
    texture1='StormElementalSkin01',
)
print(f"Assigned Display ID: {display_id}")

# Use this display_id as 'modelid1' in creature_template (Step 4)
```

---

## Step 3: Client-Side -- Place Model Files in the MPQ

Your custom `.m2` model and its associated `.blp` textures must be accessible to the WoW client. The standard approach is to place them in a client-side patch MPQ.

### 3.1 Required Files

For a creature model named `StormElemental`, you typically need:

```
Creature\StormElemental\
    StormElemental.m2           -- The 3D model geometry
    StormElemental.skin         -- LOD/mesh data (sometimes embedded in .m2)
    StormElemental00.skin       -- Skin file (view 0)
    StormElementalSkin01.blp    -- Primary diffuse texture
    StormElementalSkin01_e.blp  -- Emissive texture (optional)
    StormElementalSkin01_s.blp  -- Specular texture (optional)
```

### 3.2 MPQ Placement

The file path you registered in `CreatureModelData.dbc` must match the MPQ-internal path exactly. The model path `Creature\\StormElemental\\StormElemental.m2` means the file must be at that exact path inside the MPQ archive.

**Using pywowlib's MPQ packer:**

```python
from world_builder.mpq_packer import MPQPacker

packer = MPQPacker()
packer.add_file(
    source='./assets/StormElemental/StormElemental.m2',
    mpq_path='Creature\\StormElemental\\StormElemental.m2',
)
packer.add_file(
    source='./assets/StormElemental/StormElementalSkin01.blp',
    mpq_path='Creature\\StormElemental\\StormElementalSkin01.blp',
)
# Add the modified DBC files
packer.add_file(
    source='./output/dbc/CreatureModelData.dbc',
    mpq_path='DBFilesClient\\CreatureModelData.dbc',
)
packer.add_file(
    source='./output/dbc/CreatureDisplayInfo.dbc',
    mpq_path='DBFilesClient\\CreatureDisplayInfo.dbc',
)
packer.write('patch-4.MPQ')
```

Distribute this patch MPQ to all game clients by placing it in the `Data/` folder. The filename must sort alphabetically after the base game MPQs (hence `patch-4.MPQ` or `patch-Z.MPQ`).

### 3.3 Important Notes

- The `.m2` file must be compiled for WoW build 12340. Models from later expansions will not load.
- Texture paths referenced inside the `.m2` file are relative to the MPQ root. Verify they match your MPQ structure.
- If you see a "T-pose" or invisible creature in-game, the model path in `CreatureModelData.dbc` does not match the actual file location inside the MPQ.

---

## Step 4: Server-Side -- Create creature_template with SQLGenerator

The `creature_template` table is the heart of every NPC definition. The `SQLGenerator.add_creatures()` method accepts a list of creature definition dictionaries.

### 4.1 creature_template Column Reference

Below is every column in `creature_template` that the `CreatureBuilder` supports, with the dict key you pass to `add_creatures()`:

| Dict Key | SQL Column | Type | Default | Description |
|----------|-----------|------|---------|-------------|
| `entry` | entry | int | auto | Unique creature ID (auto-allocated from `start_entry` if omitted) |
| `name` | name | str | '' | Display name shown on mouseover |
| `subname` | subname | str | '' | Title shown below the name (e.g. "Armor Vendor") |
| `modelid1` | modelid1 | int | 0 | Primary display ID (FK to CreatureDisplayInfo.dbc) |
| `modelid2` | modelid2 | int | 0 | Alternate display (random selection) |
| `modelid3` | modelid3 | int | 0 | Alternate display |
| `modelid4` | modelid4 | int | 0 | Alternate display |
| `minlevel` | minlevel | int | 1 | Minimum creature level |
| `maxlevel` | maxlevel | int | 1 | Maximum creature level (random between min-max) |
| `faction` | faction | int | 0 | Faction template ID (determines friendliness) |
| `npcflag` | npcflag | int | 0 | NPC interaction flags (see below) |
| `speed_walk` | speed_walk | float | 1.0 | Walking speed multiplier |
| `speed_run` | speed_run | float | 1.14286 | Running speed multiplier |
| `scale` | scale | float | 1.0 | Size multiplier (0 = use DBC scale) |
| `rank` | rank | int | 0 | 0=Normal, 1=Elite, 2=Rare Elite, 3=Boss, 4=Rare |
| `type` | type | int | 0 | Creature type (see below) |
| `type_flags` | type_flags | int | 0 | Creature type flags |
| `family` | family | int | 0 | Creature family (for hunter pets) |
| `unit_class` | unit_class | int | 0 | 1=Warrior, 2=Paladin, 4=Rogue, 8=Mage |
| `unit_flags` | unit_flags | int | 0 | Unit flags bitmask |
| `unit_flags2` | unit_flags2 | int | 0 | Extended unit flags |
| `dynamicflags` | dynamicflags | int | 0 | Dynamic flags |
| `health_modifier` | HealthModifier | float | 1.0 | HP multiplier relative to base |
| `mana_modifier` | ManaModifier | float | 1.0 | Mana multiplier relative to base |
| `armor_modifier` | ArmorModifier | float | 1.0 | Armor multiplier relative to base |
| `damage_modifier` | DamageModifier | float | 1.0 | Damage multiplier relative to base |
| `experience_modifier` | ExperienceModifier | float | 1.0 | XP given multiplier |
| `base_attack_time` | BaseAttackTime | int | 2000 | Melee swing timer (ms) |
| `range_attack_time` | RangeAttackTime | int | 0 | Ranged attack timer (ms) |
| `lootid` | lootid | int | 0 | FK to creature_loot_template |
| `pickpocketloot` | pickpocketloot | int | 0 | FK to pickpocketing_loot_template |
| `skinloot` | skinloot | int | 0 | FK to skinning_loot_template |
| `mingold` | mingold | int | 0 | Min copper dropped |
| `maxgold` | maxgold | int | 0 | Max copper dropped |
| `ai_name` | AIName | str | '' | AI engine ('SmartAI', 'EventAI', etc.) |
| `movement_type` | MovementType | int | 0 | 0=Idle, 1=Random, 2=Waypoint |
| `inhabit_type` | InhabitType | int | 3 | 1=Ground, 2=Water, 4=Flying (bitmask) |
| `hover_height` | HoverHeight | float | 1.0 | Hover height for flying creatures |
| `regen_health` | RegenHealth | int | 1 | 1=regenerate HP out of combat |
| `mechanic_immune_mask` | mechanic_immune_mask | int | 0 | Bitmask of immune mechanics |
| `flags_extra` | flags_extra | int | 0 | Extra flags (see below) |
| `script_name` | ScriptName | str | '' | C++ or Eluna script name |
| `gossip_menu_id` | gossip_menu_id | int | 0 | Gossip menu ID |
| `resistance1`-`resistance6` | resistance1-6 | int | 0 | Resistances (Holy, Fire, Nature, Frost, Shadow, Arcane) |
| `spell1`-`spell8` | spell1-8 | int | 0 | Spells usable via pet bar or script |
| `trainer_type` | trainer_type | int | 0 | Trainer type |
| `trainer_spell` | trainer_spell | int | 0 | Trainer ability spell |
| `trainer_class` | trainer_class | int | 0 | Required class for trainer |
| `trainer_race` | trainer_race | int | 0 | Required race for trainer |

### 4.2 NPC Flag Values

The `npcflag` field is a bitmask. Combine flags by adding (OR-ing) values:

| Value | Flag | Description |
|-------|------|-------------|
| 1 | GOSSIP | Has gossip dialogue |
| 2 | QUESTGIVER | Offers/turns in quests |
| 4 | TRAINER (unused) | Deprecated |
| 16 | TRAINER | Class/profession trainer |
| 32 | TRAINER_CLASS | Class trainer |
| 64 | TRAINER_PROFESSION | Profession trainer |
| 128 | VENDOR | Sells items |
| 256 | VENDOR_AMMO | Sells ammunition |
| 512 | VENDOR_FOOD | Sells food |
| 1024 | VENDOR_POISON | Sells poisons |
| 2048 | VENDOR_REAGENT | Sells reagents |
| 4096 | REPAIR | Repairs items |
| 8192 | FLIGHTMASTER | Flight master |
| 16384 | SPIRIT_HEALER | Spirit healer |
| 32768 | SPIRIT_GUIDE | Battleground spirit guide |
| 65536 | INNKEEPER | Innkeeper (set hearthstone) |
| 131072 | BANKER | Banking services |
| 262144 | PETITIONER | Guild/arena charter |
| 524288 | TABARD_DESIGNER | Tabard vendor |
| 1048576 | BATTLEMASTER | Battleground queue |
| 2097152 | AUCTIONEER | Auction house |
| 4194304 | STABLEMASTER | Hunter pet stable |
| 8388608 | GUILD_BANKER | Guild bank |

### 4.3 Creature Type Values

| Value | Type |
|-------|------|
| 0 | None |
| 1 | Beast |
| 2 | Dragonkin |
| 3 | Demon |
| 4 | Elemental |
| 5 | Giant |
| 6 | Undead |
| 7 | Humanoid |
| 8 | Critter |
| 9 | Mechanical |
| 10 | Not specified |
| 11 | Totem |
| 12 | Non-combat Pet |
| 13 | Gas Cloud |

### 4.4 Common Faction Template IDs

| Faction ID | Name | Reaction |
|-----------|------|----------|
| 7 | Creature | Neutral to all |
| 14 | Booty Bay | Neutral goblin |
| 35 | Undercity | Hostile to Alliance |
| 84 | Stormwind | Hostile to Horde |
| 16 | Monster | Hostile to all players |
| 21 | Monster (Predator) | Hostile to all, aggros |
| 35 | Friendly | Friendly to all |
| 1720 | Argent Crusade | Friendly to all |

### 4.5 Python Code -- Creating a Creature Template

```python
from world_builder.sql_generator import SQLGenerator

# Initialize generator with a base entry ID range
gen = SQLGenerator(start_entry=90500, map_id=0, zone_id=1)

# Define the creature
creatures = [
    {
        'entry': 90500,                    # Explicit entry ID
        'name': 'Stormbound Sentinel',
        'subname': 'Guardian of the Vault',
        'modelid1': 26693,                 # Reuse an existing display ID
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 16,                     # Hostile to all players
        'npcflag': 0,                      # No special NPC functions
        'speed_walk': 1.0,
        'speed_run': 1.14286,
        'scale': 1.2,                      # 20% larger
        'rank': 1,                         # Elite
        'type': 4,                         # Elemental
        'health_modifier': 5.0,            # 5x base HP
        'mana_modifier': 2.0,
        'damage_modifier': 3.0,
        'armor_modifier': 1.5,
        'experience_modifier': 2.0,        # Double XP
        'base_attack_time': 2000,          # 2 second swing
        'mingold': 5000,                   # 50 silver min
        'maxgold': 15000,                  # 1 gold 50 silver max
        'ai_name': 'SmartAI',             # Use SmartAI for scripting
        'movement_type': 1,                # Random movement
        'inhabit_type': 1,                 # Ground only
        'regen_health': 1,
        'lootid': 90500,                   # Same as entry for simplicity
        'flags_extra': 0,
    },
]

# Generate the SQL
entry_ids = gen.add_creatures(creatures)
print(f"Created creature entries: {entry_ids}")
```

### 4.6 Generated SQL Output

The above code produces SQL like:

```sql
-- Creature: Stormbound Sentinel (90500)
INSERT INTO `creature_template` (`entry`, `difficulty_entry_1`, `difficulty_entry_2`,
    `difficulty_entry_3`, `KillCredit1`, `KillCredit2`,
    `modelid1`, `modelid2`, `modelid3`, `modelid4`,
    `name`, `subname`, `IconName`,
    `gossip_menu_id`, `minlevel`, `maxlevel`,
    `exp`, `faction`, `npcflag`,
    `speed_walk`, `speed_run`, `scale`,
    `rank`, `dmgschool`,
    `BaseAttackTime`, `RangeAttackTime`,
    `BaseVariance`, `RangeVariance`,
    `unit_class`, `unit_flags`, `unit_flags2`, `dynamicflags`,
    `family`,
    `trainer_type`, `trainer_spell`, `trainer_class`, `trainer_race`,
    `type`, `type_flags`,
    `lootid`, `pickpocketloot`, `skinloot`,
    `resistance1`, `resistance2`, `resistance3`,
    `resistance4`, `resistance5`, `resistance6`,
    `spell1`, `spell2`, `spell3`, `spell4`,
    `spell5`, `spell6`, `spell7`, `spell8`,
    `PetSpellDataId`, `VehicleId`,
    `mingold`, `maxgold`,
    `AIName`, `MovementType`,
    `InhabitType`, `HoverHeight`,
    `HealthModifier`, `ManaModifier`,
    `ArmorModifier`, `DamageModifier`, `ExperienceModifier`,
    `RacialLeader`, `movementId`,
    `RegenHealth`, `mechanic_immune_mask`,
    `flags_extra`, `ScriptName`) VALUES
(90500, 0, 0, 0, 0, 0, 26693, 0, 0, 0,
 'Stormbound Sentinel', 'Guardian of the Vault', '',
 0, 80, 80, 0, 16, 0,
 1.0, 1.14286, 1.2,
 1, 0, 2000, 0, 1.0, 1.0,
 0, 0, 0, 0, 0,
 0, 0, 0, 0, 4, 0,
 90500, 0, 0,
 0, 0, 0, 0, 0, 0,
 0, 0, 0, 0, 0, 0, 0, 0,
 0, 0, 5000, 15000,
 'SmartAI', 1, 1, 1.0,
 5.0, 2.0, 1.5, 3.0, 2.0,
 0, 0, 1, 0, 0, '');
```

---

## Step 5: Server-Side -- Add Creature Spawns

After defining the creature template, you must spawn instances of it in the game world. Each spawn is a row in the `creature` table.

### 5.1 Spawn Definition Fields

| Dict Key | SQL Column | Type | Default | Description |
|----------|-----------|------|---------|-------------|
| `entry` | id | int | required | FK to creature_template.entry |
| `map` | map | int | gen.map_id | Map ID (0=Eastern Kingdoms, 1=Kalimdor, 530=Outland, 571=Northrend) |
| `zone` | zoneId | int | gen.zone_id | Zone ID |
| `area` | areaId | int | zone | Area ID within zone |
| `position` | position_x/y/z, orientation | tuple | (0,0,0,0) | (x, y, z, orientation) -- orientation in radians, 0=North |
| `spawntimesecs` | spawntimesecs | int | 120 | Respawn time in seconds |
| `wander_distance` | wander_distance | float | 0 | Random movement radius in yards |
| `movement_type` | MovementType | int | 0 | 0=Idle, 1=Random, 2=Waypoint |
| `spawn_mask` | spawnMask | int | 1 | Difficulty mask |
| `phase_mask` | phaseMask | int | 1 | Phase mask |
| `equipment_id` | equipment_id | int | 0 | Equipment template ID |
| `model_id` | modelid | int | 0 | Override model (0 = use template) |
| `addon` | (separate table) | dict | None | creature_addon configuration |

### 5.2 Getting Coordinates In-Game

Use the `.gps` GM command in-game to get your current coordinates:

```
.gps
```

This returns something like:

```
Map: 0 (Eastern Kingdoms)
Zone: 1519 (Stormwind City)
Area: 1519
Position: X: -8949.95 Y: -132.493 Z: 83.5312
Orientation: 0.7854
```

Use these coordinates in your spawn definitions.

### 5.3 Python Code -- Adding Spawns

```python
# Add spawns for the creature we defined above
spawns = [
    {
        'entry': 90500,
        'map': 0,                          # Eastern Kingdoms
        'zone': 1519,                      # Stormwind City
        'position': (-8949.95, -132.49, 83.53, 0.78),
        'spawntimesecs': 300,              # 5 minute respawn
        'wander_distance': 5.0,            # Wander 5 yards from spawn
        'movement_type': 1,                # Random movement
    },
    {
        'entry': 90500,
        'map': 0,
        'zone': 1519,
        'position': (-8935.12, -145.73, 83.53, 2.35),
        'spawntimesecs': 300,
        'wander_distance': 3.0,
        'movement_type': 1,
    },
    {
        'entry': 90500,
        'map': 0,
        'zone': 1519,
        'position': (-8960.00, -120.00, 83.53, 5.50),
        'spawntimesecs': 300,
        'wander_distance': 0.0,            # Stationary
        'movement_type': 0,                # Idle -- stands still
    },
]

guids = gen.add_spawns(spawns)
print(f"Assigned spawn GUIDs: {guids}")
```

---

## Step 6: Server-Side -- Configure creature_addon

The `creature_addon` table provides per-spawn cosmetic data: emotes, auras, mounted appearance, and waypoint path linkage.

### 6.1 creature_addon Fields

| Dict Key | SQL Column | Type | Default | Description |
|----------|-----------|------|---------|-------------|
| `path_id` | path_id | int | 0 | FK to waypoint_data.id (see change_npc_pathing.md) |
| `mount` | mount | int | 0 | Mount display ID (creature appears mounted) |
| `bytes1` | bytes1 | int | 0 | Stand state: 0=Stand, 1=Sit, 2=SitChair, 3=Sleep, 5=Kneel, 6=Dead, 7=SitGround, 8=Hover |
| `bytes2` | bytes2 | int | 0 | Pet/sheath state bitmask |
| `emote` | emote | int | 0 | Persistent emote ID (creature plays this emote continuously) |
| `is_large` | isLarge | int | 0 | Large creature flag |
| `auras` | auras | str | '' | Space-separated list of aura spell IDs applied on spawn |

### 6.2 Common Emote IDs

| Emote ID | Name | Description |
|----------|------|-------------|
| 0 | NONE | No emote |
| 1 | ONESHOT_TALK | Talk animation (one shot) |
| 10 | STATE_DANCE | Continuous dancing |
| 26 | STATE_STANDSTATE_CUSTOM | Custom stand state |
| 69 | STATE_USESTANDING | Using something while standing |
| 133 | STATE_DANCE_SPECIAL | Special dance loop |
| 173 | STATE_WORK_CHOPWOOD | Chopping wood |
| 233 | STATE_WORK_MINING | Mining ore |
| 234 | STATE_WORK_NOSHEATHE_MINING | Mining (no weapon sheath) |
| 373 | STATE_WORK_SMITH | Smithing animation |

### 6.3 Python Code -- Spawn with Addon

```python
# Spawn with creature_addon: creature kneeling with a visual aura
spawns_with_addon = [
    {
        'entry': 90500,
        'map': 0,
        'zone': 1519,
        'position': (-8940.00, -128.00, 83.53, 1.57),
        'spawntimesecs': 300,
        'movement_type': 0,
        'addon': {
            'path_id': 0,             # No patrol path
            'mount': 0,               # Not mounted
            'bytes1': 8,              # Hover
            'bytes2': 0,
            'emote': 0,               # No persistent emote
            'auras': '35240',         # Aura spell ID (e.g. lightning visual)
        },
    },
    {
        'entry': 90500,
        'map': 0,
        'zone': 1519,
        'position': (-8955.00, -115.00, 83.53, 3.14),
        'spawntimesecs': 300,
        'movement_type': 0,
        'addon': {
            'path_id': 0,
            'mount': 0,
            'bytes1': 5,              # Kneeling
            'bytes2': 0,
            'emote': 233,             # Mining emote
            'auras': '',              # No auras
        },
    },
]

guids = gen.add_spawns(spawns_with_addon)
```

### 6.4 Multiple Auras

To apply multiple auras, separate spell IDs with spaces in the `auras` string:

```python
'auras': '35240 36460 43422',   # Three simultaneous visual auras
```

---

## Step 7: Server-Side -- Assign SmartAI Behavior (Optional)

For creatures that need combat abilities beyond basic melee, the SmartAI system provides a SQL-only scripting framework. Set `ai_name` to `'SmartAI'` in the creature template, then define abilities via the `smart_scripts` table.

### 7.1 SmartAI Quick Reference

The `SmartAIBuilder.add_creature_ai()` method accepts a creature entry and an AI definition dict:

```python
gen.add_smartai({
    90500: {
        'name': 'Stormbound Sentinel',
        'abilities': [
            {
                'event': 'combat',          # Repeating in-combat timer
                'spell_id': 61546,          # Chain Lightning
                'target': 'random',         # Random player target
                'min_repeat': 8000,         # Cast every 8-12 seconds
                'max_repeat': 12000,
                'comment': 'Stormbound Sentinel - In Combat - Cast Chain Lightning',
            },
            {
                'event': 'combat',
                'spell_id': 32736,          # Mortal Strike
                'target': 'victim',         # Current tank
                'min_repeat': 6000,
                'max_repeat': 10000,
                'comment': 'Stormbound Sentinel - In Combat - Cast Mortal Strike',
            },
            {
                'event': 'health_pct',      # Trigger at health threshold
                'health_pct': 30,           # Below 30% HP
                'spell_id': 8599,           # Enrage
                'target': 'self',
                'event_flags': 1,           # NOT_REPEATABLE
                'comment': 'Stormbound Sentinel - Below 30% HP - Cast Enrage',
            },
            {
                'event': 'aggro',           # On pull
                'action_type': 1,           # SMART_ACTION_TALK
                'action_params': [0],       # creature_text GroupID 0
                'target': 'self',
                'comment': 'Stormbound Sentinel - On Aggro - Say Text',
            },
            {
                'event': 'death',
                'action_type': 1,           # SMART_ACTION_TALK
                'action_params': [1],       # creature_text GroupID 1
                'target': 'self',
                'comment': 'Stormbound Sentinel - On Death - Say Text',
            },
        ],
    },
})
```

For a comprehensive guide on SmartAI scripting for boss encounters, see [update_boss_mechanics.md](update_boss_mechanics.md).

---

## Step 8: Complete Working Example

Below is a complete, self-contained script that creates a creature with spawns, addons, SmartAI, and writes the SQL to a file:

```python
"""
Complete example: Add a new creature to WoW 3.3.5a
Generates all server-side SQL needed for a hostile elite elemental NPC.
"""

from world_builder.sql_generator import SQLGenerator

# ---------------------------------------------------------------
# 1. Initialize the SQL generator
# ---------------------------------------------------------------
gen = SQLGenerator(start_entry=90500, map_id=0, zone_id=1519)

# ---------------------------------------------------------------
# 2. Define the creature template
# ---------------------------------------------------------------
gen.add_creatures([
    {
        'entry': 90500,
        'name': 'Stormbound Sentinel',
        'subname': 'Guardian of the Vault',
        'modelid1': 26693,            # Existing display ID (reuse)
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 16,                # Hostile to all players
        'npcflag': 0,
        'speed_walk': 1.0,
        'speed_run': 1.14286,
        'scale': 1.2,
        'rank': 1,                    # Elite
        'type': 4,                    # Elemental
        'health_modifier': 5.0,
        'mana_modifier': 2.0,
        'damage_modifier': 3.0,
        'armor_modifier': 1.5,
        'experience_modifier': 2.0,
        'base_attack_time': 2000,
        'mingold': 5000,
        'maxgold': 15000,
        'ai_name': 'SmartAI',
        'movement_type': 0,
        'inhabit_type': 1,
        'regen_health': 1,
        'lootid': 90500,
        'flags_extra': 0,
    },
])

# ---------------------------------------------------------------
# 3. Spawn creatures in the game world
# ---------------------------------------------------------------
gen.add_spawns([
    # Spawn 1: Stationary guard
    {
        'entry': 90500,
        'position': (-8949.95, -132.49, 83.53, 0.78),
        'spawntimesecs': 300,
        'movement_type': 0,           # Idle
    },
    # Spawn 2: Patrolling (random wander)
    {
        'entry': 90500,
        'position': (-8935.12, -145.73, 83.53, 2.35),
        'spawntimesecs': 300,
        'wander_distance': 8.0,
        'movement_type': 1,           # Random wander
    },
    # Spawn 3: Kneeling with a lightning aura
    {
        'entry': 90500,
        'position': (-8960.00, -120.00, 83.53, 5.50),
        'spawntimesecs': 300,
        'movement_type': 0,
        'addon': {
            'bytes1': 5,              # Kneeling
            'auras': '35240',         # Lightning visual
        },
    },
])

# ---------------------------------------------------------------
# 4. Add SmartAI combat behavior
# ---------------------------------------------------------------
gen.add_smartai({
    90500: {
        'name': 'Stormbound Sentinel',
        'abilities': [
            {
                'event': 'combat',
                'spell_id': 61546,    # Chain Lightning
                'target': 'random',
                'min_repeat': 8000,
                'max_repeat': 12000,
                'comment': 'Stormbound Sentinel - In Combat - Cast Chain Lightning',
            },
            {
                'event': 'combat',
                'spell_id': 32736,    # Mortal Strike
                'target': 'victim',
                'min_repeat': 6000,
                'max_repeat': 10000,
                'comment': 'Stormbound Sentinel - In Combat - Cast Mortal Strike',
            },
            {
                'event': 'health_pct',
                'health_pct': 30,
                'spell_id': 8599,     # Enrage
                'target': 'self',
                'event_flags': 1,     # NOT_REPEATABLE
                'comment': 'Stormbound Sentinel - Below 30% HP - Cast Enrage',
            },
        ],
    },
})

# ---------------------------------------------------------------
# 5. Write the SQL file
# ---------------------------------------------------------------
gen.write_sql('./output/sql/creature_stormbound_sentinel.sql')
print("SQL written to ./output/sql/creature_stormbound_sentinel.sql")

# ---------------------------------------------------------------
# 6. Validate cross-references
# ---------------------------------------------------------------
validation = gen.validate()
if validation['valid']:
    print("Validation passed!")
else:
    for error in validation['errors']:
        print(f"ERROR: {error}")
for warning in validation['warnings']:
    print(f"WARNING: {warning}")
```

### Applying the SQL

```bash
# Apply to your AzerothCore database
mysql -u root -p acore_world < ./output/sql/creature_stormbound_sentinel.sql

# Reload in-game (GM commands)
.reload creature_template 90500
.npc add 90500
```

---

## Common Pitfalls and Troubleshooting

### Creature is invisible in-game

- **Cause**: `modelid1` is 0 or references a non-existent display ID.
- **Fix**: Set `modelid1` to a valid `CreatureDisplayInfo.dbc` ID. For custom models, verify both `CreatureModelData.dbc` and `CreatureDisplayInfo.dbc` entries exist and the `.m2` file is in the client MPQ.

### Creature does not attack players

- **Cause**: Wrong `faction` value. Friendly factions (e.g. 35) will not aggro.
- **Fix**: Use faction 16 (Monster, hostile to all) or 21 (Monster Predator, aggressive).

### Creature has very low HP or damage

- **Cause**: `health_modifier` / `damage_modifier` not set. The default is 1.0 which uses base values for the creature's level and class.
- **Fix**: Increase the modifiers. For an elite mob, `health_modifier: 3.0` to `10.0` is typical. For bosses, values of `50.0+` are common.

### SmartAI scripts do not execute

- **Cause**: `ai_name` not set to `'SmartAI'` in the creature template, or the `smart_scripts` rows reference the wrong `entryorguid`.
- **Fix**: Verify `creature_template.AIName = 'SmartAI'` and that `smart_scripts.entryorguid` matches the creature entry.

### Creature spawns at wrong location or underground

- **Cause**: Incorrect `position_z` coordinate. WoW's Z axis is vertical.
- **Fix**: Use `.gps` in-game at the desired location to get exact coordinates. If the creature spawns underground, increase Z by 1-2 yards.

### "Duplicate entry" error when applying SQL

- **Cause**: The creature entry ID already exists in `creature_template`.
- **Fix**: Use a unique entry ID in the custom range (90000+). Run `SELECT entry FROM creature_template WHERE entry = 90500;` to verify the ID is available.

### creature_addon auras do not display

- **Cause**: The aura spell ID does not exist or the spell has no visual effect.
- **Fix**: Verify the spell ID exists in `Spell.dbc`. Use spells with known visual effects (e.g. 35240 for lightning, 36032 for a fire visual).

---

## Cross-References

- **[Update Boss Mechanics](update_boss_mechanics.md)** -- For complex Eluna Lua boss scripts with multi-phase encounters, timer-based abilities, and phase transitions
- **[Add Vendor/Trainer](add_vendor_trainer.md)** -- For creatures that sell items or teach spells/skills
- **[Change NPC Pathing](change_npc_pathing.md)** -- For setting up waypoint patrol routes and linking them via creature_addon
- **SQLGenerator API** -- `world_builder/sql_generator.py` for complete API reference
- **DBCInjector API** -- `world_builder/dbc_injector.py` for low-level DBC manipulation
