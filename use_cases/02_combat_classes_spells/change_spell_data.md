# Change Spell Data

**Complexity**: Intermediate |
**DBC Files**: Spell.dbc |
**SQL Tables**: spell_dbc, spell_bonus_data, spell_custom_attr |
**pywowlib Modules**: `world_builder.dbc_injector.DBCInjector`, `world_builder.dbc_injector.modify_spell`

---

## Overview

Modifying existing spells is significantly simpler than creating new ones because the record already exists in both the client DBC and the server database. The task reduces to: read the existing record, patch specific fields at their byte offsets, and write the file back.

This guide covers the most common spell modifications: adjusting damage values, changing mana costs, modifying cast times and cooldowns, altering range, tweaking spell power coefficients, and updating tooltip text. All changes require coordinated edits on both client (Spell.dbc) and server (SQL tables) to keep tooltips and mechanics in sync.

---

## Quick Start: Convenience API

pywowlib provides `modify_spell()` which lets you change any Spell.dbc field by name in a single call, without manual byte-offset calculations:

```python
from world_builder import modify_spell

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"

# Buff Fireball: reduce mana cost and cooldown
modify_spell(DBC_DIR, spell_id=133, ManaCost=200, RecoveryTime=5000)

# Change Frostbolt damage: set BasePoints to 99 (displays 100), DieSides to 51 (100-150)
modify_spell(DBC_DIR, spell_id=116,
             EffectBasePoints0=99,
             EffectDieSides0=51)

# Change tooltip text (locstring fields accept plain strings)
modify_spell(DBC_DIR, spell_id=5143,
             Name_lang="Arcane Storm",
             Description_lang="Launches a barrage of arcane energy, "
                              "hitting the target every second for $d.")

# Change a float field (spell power coefficient)
modify_spell(DBC_DIR, spell_id=116, EffectBonusCoefficient0=0.9)
```

`modify_spell()` accepts the spell ID and any number of keyword arguments. Each keyword must be a valid field name from the `_SPELL_FIELD_MAP` (the same field names listed in the byte offset table in Step 1 below). Locstring fields (`Name_lang`, `Description_lang`, `NameSubtext_lang`, `AuraDescription_lang`) accept plain strings. Float fields (`Speed`, `EffectBonusCoefficient0`, etc.) are handled automatically.

The function raises `ValueError` if the spell ID is not found or if a field name is unrecognized.

The manual byte-offset approach documented below remains available for advanced use and for understanding the binary layout.

---

## Prerequisites

- A working WoW 3.3.5a client with the stock `Spell.dbc` (or a previously modified copy)
- Python 3.6+ with pywowlib available
- Knowledge of the target spell's ID (look it up on wowhead.com or in the DBC itself)
- Access to the AzerothCore world database for server-side changes

---

## Step 1: Understand the Byte Offset Calculation

Every field in Spell.dbc is 4 bytes wide (uint32, int32, or float32). The byte offset for any field is:

```
byte_offset = field_index * 4
```

Refer to the complete field layout in [Add New Spell](./add_new_spell.md) for the full 234-field mapping. The most commonly modified fields and their indices are:

```
Field Index  Byte Offset  Field Name              Type     Description
-----------  -----------  ----------------------  -------  ---------------------------
 28          112          CastingTimeIndex        uint32   SpellCastTimes.dbc FK
 29          116          RecoveryTime            uint32   Cooldown (ms)
 30          120          CategoryRecoveryTime    uint32   Shared cooldown (ms)
 39          156          SpellLevel              uint32   Required level
 41          164          PowerType               uint32   0=mana, 1=rage, 3=energy
 42          168          ManaCost                uint32   Base mana cost
 46          184          RangeIndex              uint32   SpellRange.dbc FK
 47          188          Speed                   float    Projectile speed
 71          284          Effect[0]               uint32   Effect type (slot 1)
 74          296          EffectDieSides[0]       uint32   Random variance (slot 1)
 80          320          EffectBasePoints[0]     int32    Base value (slot 1)
 95          380          EffectAura[0]           uint32   Aura type (slot 1)
 98          392          EffectAuraPeriod[0]     uint32   Tick interval ms (slot 1)
 92          368          EffectRadiusIndex[0]    uint32   AoE radius FK (slot 1)
133          532          SpellIconID             uint32   Icon FK
131          524          SpellVisualID[0]        uint32   Visual FK
136-152      544-608      Name_lang               locstr   Spell name (17 x uint32)
170-186      680-744      Description_lang         locstr   Tooltip (17 x uint32)
206          824          StartRecoveryTime       uint32   GCD (ms)
225          900          SchoolMask              uint32   Damage school bitmask
229          916          EffectBonusCoeff[0]     float    SP coefficient (slot 1)
```

For effect slots 2 and 3, add 1 or 2 to the base index respectively. For example:
- `EffectBasePoints[1]` = field index 81, byte offset 324
- `EffectBasePoints[2]` = field index 82, byte offset 328

---

## Step 2: Read and Inspect an Existing Spell

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"


def find_spell_record(dbc, spell_id):
    """
    Find a spell record by ID. Returns the record index or -1 if not found.

    Args:
        dbc: DBCInjector instance with Spell.dbc loaded.
        spell_id: The spell ID to search for.

    Returns:
        int: Record index (0-based), or -1 if not found.
    """
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == spell_id:
            return i
    return -1


def inspect_spell(dbc, record_index):
    """
    Print key fields from a spell record for debugging.

    Args:
        dbc: DBCInjector instance with Spell.dbc loaded.
        record_index: Index into dbc.records.
    """
    rec = dbc.records[record_index]

    spell_id = struct.unpack_from('<I', rec, 0)[0]
    category = struct.unpack_from('<I', rec, 4)[0]
    attributes = struct.unpack_from('<I', rec, 16)[0]
    cast_time_idx = struct.unpack_from('<I', rec, 112)[0]
    cooldown = struct.unpack_from('<I', rec, 116)[0]
    spell_level = struct.unpack_from('<I', rec, 156)[0]
    power_type = struct.unpack_from('<I', rec, 164)[0]
    mana_cost = struct.unpack_from('<I', rec, 168)[0]
    range_idx = struct.unpack_from('<I', rec, 184)[0]
    speed = struct.unpack_from('<f', rec, 188)[0]

    effect1 = struct.unpack_from('<I', rec, 284)[0]
    die_sides1 = struct.unpack_from('<I', rec, 296)[0]
    base_points1 = struct.unpack_from('<i', rec, 320)[0]
    target_a1 = struct.unpack_from('<I', rec, 344)[0]

    icon_id = struct.unpack_from('<I', rec, 532)[0]
    school_mask = struct.unpack_from('<I', rec, 900)[0]
    gcd = struct.unpack_from('<I', rec, 824)[0]
    bonus_coeff = struct.unpack_from('<f', rec, 916)[0]

    # Read spell name from locstring (field 136 = byte 544, enUS is slot 0)
    name_offset = struct.unpack_from('<I', rec, 544)[0]
    name = dbc.get_string(name_offset)

    # Read description from locstring (field 170 = byte 680, enUS is slot 0)
    desc_offset = struct.unpack_from('<I', rec, 680)[0]
    description = dbc.get_string(desc_offset)

    print("=== Spell {} ===".format(spell_id))
    print("  Name:            {}".format(name))
    print("  Description:     {}".format(description[:80]))
    print("  Category:        {}".format(category))
    print("  Attributes:      0x{:08X}".format(attributes))
    print("  CastTimeIndex:   {}".format(cast_time_idx))
    print("  Cooldown:        {} ms".format(cooldown))
    print("  SpellLevel:      {}".format(spell_level))
    print("  PowerType:       {}".format(power_type))
    print("  ManaCost:        {}".format(mana_cost))
    print("  RangeIndex:      {}".format(range_idx))
    print("  Speed:           {}".format(speed))
    print("  Effect1:         {}".format(effect1))
    print("  DieSides1:       {}".format(die_sides1))
    print("  BasePoints1:     {} (displays {})".format(base_points1, base_points1 + 1))
    print("  TargetA1:        {}".format(target_a1))
    print("  SpellIconID:     {}".format(icon_id))
    print("  SchoolMask:      0x{:02X}".format(school_mask))
    print("  GCD:             {} ms".format(gcd))
    print("  BonusCoeff1:     {}".format(bonus_coeff))


# Example: inspect Frostbolt (ID 116)
filepath = os.path.join(DBC_DIR, 'Spell.dbc')
dbc = DBCInjector(filepath)

idx = find_spell_record(dbc, 116)
if idx >= 0:
    inspect_spell(dbc, idx)
else:
    print("Spell 116 not found")
```

---

## Step 3: Modify Specific Fields

> **Note**: For most modifications, `modify_spell()` from the Quick Start section above replaces this entire manual workflow. The approach below is kept for reference and for advanced scenarios.

The `DBCInjector` stores records as raw bytes. To modify a field, convert the record to a mutable `bytearray`, patch the bytes with `struct.pack_into`, and store it back.

```python
def modify_spell_field(dbc, record_index, field_index, value, fmt='<I'):
    """
    Modify a single field in a spell record.

    Args:
        dbc: DBCInjector instance with Spell.dbc loaded.
        record_index: Index into dbc.records.
        field_index: DBC field index (0-based).
        value: New value to write.
        fmt: struct format string. '<I' for uint32, '<i' for int32, '<f' for float.
    """
    rec = bytearray(dbc.records[record_index])
    byte_offset = field_index * 4
    struct.pack_into(fmt, rec, byte_offset, value)
    dbc.records[record_index] = bytes(rec)


def modify_spell_string(dbc, record_index, field_index, new_text):
    """
    Modify a locstring field (changes the enUS slot, index 0 of the locstring).

    Args:
        dbc: DBCInjector instance.
        record_index: Index into dbc.records.
        field_index: DBC field index of the FIRST uint32 of the locstring.
        new_text: New string value.
    """
    new_offset = dbc.add_string(new_text)
    modify_spell_field(dbc, record_index, field_index, new_offset)
```

---

## Step 4: Common Modifications with Complete Examples

> **Tip**: All of the modifications below can also be done with a single `modify_spell()` call using the appropriate `_SPELL_FIELD_MAP` field names. For example, instead of the `change_spell_damage()` function, you can write:
> ```python
> from world_builder import modify_spell
> # Change Fireball rank 1 damage to 100-150
> modify_spell(DBC_DIR, 133, EffectBasePoints0=99, EffectDieSides0=51)
> ```

### 4.1 - Change Damage Values

The displayed damage is calculated from `EffectBasePoints` and `EffectDieSides`:
- **Minimum damage** = `EffectBasePoints + 1`
- **Maximum damage** = `EffectBasePoints + EffectDieSides`
- For a **fixed value** (no variance): set `EffectBasePoints = value - 1`, `EffectDieSides = 1`
- For a **range** (e.g., 500-700): set `EffectBasePoints = 499`, `EffectDieSides = 201`

```python
def change_spell_damage(dbc_dir, spell_id, damage_min, damage_max,
                        effect_slot=0):
    """
    Change the damage values for a spell's effect slot.

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: Target spell ID.
        damage_min: New minimum damage.
        damage_max: New maximum damage.
        effect_slot: Effect slot (0, 1, or 2).
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    base_points = damage_min - 1
    die_sides = damage_max - damage_min + 1

    # EffectBasePoints: fields 80, 81, 82 for slots 0, 1, 2
    base_points_field = 80 + effect_slot
    # EffectDieSides: fields 74, 75, 76 for slots 0, 1, 2
    die_sides_field = 74 + effect_slot

    modify_spell_field(dbc, idx, base_points_field, base_points, fmt='<i')
    modify_spell_field(dbc, idx, die_sides_field, die_sides)

    dbc.write(filepath)
    print("Spell {}: damage changed to {}-{}".format(spell_id, damage_min, damage_max))


# Example: Change Fireball (ID 133) rank 1 damage to 100-150
change_spell_damage(DBC_DIR, 133, 100, 150)
```

### 4.2 - Change Mana Cost

```python
def change_spell_mana_cost(dbc_dir, spell_id, new_mana_cost):
    """
    Change the mana cost of a spell.

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: Target spell ID.
        new_mana_cost: New mana cost value.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # ManaCost = field index 42
    modify_spell_field(dbc, idx, 42, new_mana_cost)

    dbc.write(filepath)
    print("Spell {}: mana cost changed to {}".format(spell_id, new_mana_cost))


# Example: Change Frostbolt (ID 116) mana cost to 50
change_spell_mana_cost(DBC_DIR, 116, 50)
```

### 4.3 - Change Cast Time

Cast time is controlled by an index into `SpellCastTimes.dbc`, not by a direct millisecond value. The most commonly used indices for WotLK 3.3.5a are:

| CastingTimeIndex | Cast Time     |
|------------------|---------------|
| 1                | Instant       |
| 4                | 1500 ms       |
| 5                | 2000 ms       |
| 14               | 2500 ms       |
| 15               | 3000 ms       |
| 16               | 3500 ms       |
| 136              | 500 ms        |
| 137              | 1000 ms       |

```python
def change_spell_cast_time(dbc_dir, spell_id, cast_time_index):
    """
    Change the cast time of a spell by setting its CastingTimeIndex.

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: Target spell ID.
        cast_time_index: New SpellCastTimes.dbc index.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # CastingTimeIndex = field index 28
    modify_spell_field(dbc, idx, 28, cast_time_index)

    # If changing from instant to cast time, add interrupt flags
    if cast_time_index > 1:
        modify_spell_field(dbc, idx, 31, 0x0F)  # InterruptFlags: all
    else:
        modify_spell_field(dbc, idx, 31, 0)

    dbc.write(filepath)
    print("Spell {}: cast time index changed to {}".format(spell_id, cast_time_index))


# Example: Make Fireball (ID 133) instant cast
change_spell_cast_time(DBC_DIR, 133, 1)
```

### 4.4 - Change Cooldown

```python
def change_spell_cooldown(dbc_dir, spell_id, cooldown_ms,
                          category_cooldown_ms=0):
    """
    Change the cooldown of a spell.

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: Target spell ID.
        cooldown_ms: New cooldown in milliseconds.
        category_cooldown_ms: Shared category cooldown (0 for none).
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # RecoveryTime = field index 29
    modify_spell_field(dbc, idx, 29, cooldown_ms)
    # CategoryRecoveryTime = field index 30
    modify_spell_field(dbc, idx, 30, category_cooldown_ms)

    dbc.write(filepath)
    print("Spell {}: cooldown changed to {} ms".format(spell_id, cooldown_ms))


# Example: Set Pyroblast (ID 11366) cooldown to 8 seconds
change_spell_cooldown(DBC_DIR, 11366, 8000)
```

### 4.5 - Change Spell Range

Range is controlled by an index into `SpellRange.dbc`. Common values:

| RangeIndex | Min Range | Max Range | Description       |
|------------|-----------|-----------|-------------------|
| 1          | 0         | 0         | Self only         |
| 2          | 0         | 5         | Melee             |
| 3          | 0         | 20        | Short             |
| 4          | 0         | 30        | Medium            |
| 5          | 0         | 40        | Long              |
| 6          | 0         | 100       | Vision            |
| 7          | 0         | 10        | Short melee       |
| 13         | 0         | 50000     | Unlimited         |

```python
def change_spell_range(dbc_dir, spell_id, range_index):
    """
    Change the range of a spell.

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: Target spell ID.
        range_index: New SpellRange.dbc index.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # RangeIndex = field index 46
    modify_spell_field(dbc, idx, 46, range_index)

    dbc.write(filepath)
    print("Spell {}: range index changed to {}".format(spell_id, range_index))


# Example: Make Frostbolt (ID 116) have 40-yard range
change_spell_range(DBC_DIR, 116, 5)
```

### 4.6 - Change Tooltip Text

```python
def change_spell_name(dbc_dir, spell_id, new_name):
    """Change the display name of a spell."""
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # Name_lang starts at field 136 (enUS = slot 0 = field 136)
    modify_spell_string(dbc, idx, 136, new_name)

    dbc.write(filepath)
    print("Spell {}: name changed to '{}'".format(spell_id, new_name))


def change_spell_description(dbc_dir, spell_id, new_description):
    """Change the tooltip description of a spell."""
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    idx = find_spell_record(dbc, spell_id)
    if idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    # Description_lang starts at field 170 (enUS = slot 0 = field 170)
    modify_spell_string(dbc, idx, 170, new_description)

    dbc.write(filepath)
    print("Spell {}: description updated".format(spell_id, ))


# Example: Rename and redescribe Arcane Missiles
change_spell_name(DBC_DIR, 5143, "Arcane Storm")
change_spell_description(
    DBC_DIR, 5143,
    "Launches a barrage of arcane energy, hitting the target "
    "every second for $d, causing $s1 Arcane damage each hit."
)
```

---

## Step 5: Batch Modification

For simple batch changes, you can call `modify_spell()` in a loop:

```python
from world_builder import modify_spell

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"

# Rebalance frost spell mana costs
for spell_id, new_cost in [(116, 20), (205, 35), (120, 50)]:
    modify_spell(DBC_DIR, spell_id, ManaCost=new_cost)
```

Note that each `modify_spell()` call opens and writes the DBC file separately. For large batch operations where performance matters, the manual single-load approach below is more efficient -- it loads the DBC once, patches all records in memory, and writes once:

```python
def batch_modify_spells(dbc_dir, modifications):
    """
    Apply multiple spell modifications in a single DBC read/write cycle.

    Args:
        dbc_dir: Path to DBFilesClient.
        modifications: List of dicts, each with:
            - 'spell_id': Target spell ID
            - 'changes': Dict of {field_name: new_value}, where field_name is one of:
              'damage_min', 'damage_max', 'mana_cost', 'cast_time_index',
              'cooldown', 'range_index', 'school_mask', 'gcd', 'spell_level'
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    # Map of field name -> (field_index, format)
    field_map = {
        'cast_time_index':  (28,  '<I'),
        'cooldown':         (29,  '<I'),
        'category_cooldown':(30,  '<I'),
        'spell_level':      (39,  '<I'),
        'power_type':       (41,  '<I'),
        'mana_cost':        (42,  '<I'),
        'range_index':      (46,  '<I'),
        'speed':            (47,  '<f'),
        'school_mask':      (225, '<I'),
        'gcd':              (206, '<I'),
        'bonus_coeff':      (229, '<f'),
    }

    modified_count = 0
    for mod in modifications:
        spell_id = mod['spell_id']
        changes = mod['changes']

        idx = find_spell_record(dbc, spell_id)
        if idx < 0:
            print("WARNING: Spell {} not found, skipping".format(spell_id))
            continue

        rec = bytearray(dbc.records[idx])

        for field_name, value in changes.items():
            if field_name == 'damage_min':
                damage_max = changes.get('damage_max', value)
                base_points = value - 1
                die_sides = damage_max - value + 1
                struct.pack_into('<i', rec, 80 * 4, base_points)
                struct.pack_into('<I', rec, 74 * 4, die_sides)
            elif field_name == 'damage_max':
                pass  # handled with damage_min
            elif field_name in field_map:
                fi, fmt = field_map[field_name]
                struct.pack_into(fmt, rec, fi * 4, value)
            else:
                print("WARNING: Unknown field '{}' for spell {}".format(
                    field_name, spell_id))

        dbc.records[idx] = bytes(rec)
        modified_count += 1

    dbc.write(filepath)
    print("Modified {} spells in Spell.dbc".format(modified_count))


# Example: Rebalance several frost spells
batch_modify_spells(DBC_DIR, [
    {
        'spell_id': 116,   # Frostbolt Rank 1
        'changes': {
            'damage_min': 25,
            'damage_max': 30,
            'mana_cost': 20,
            'cast_time_index': 4,  # 1.5s
        }
    },
    {
        'spell_id': 205,   # Frostbolt Rank 2
        'changes': {
            'damage_min': 45,
            'damage_max': 55,
            'mana_cost': 35,
        }
    },
    {
        'spell_id': 120,   # Cone of Cold Rank 1
        'changes': {
            'damage_min': 80,
            'damage_max': 100,
            'cooldown': 8000,  # 8 seconds instead of 10
        }
    },
])
```

---

## Step 6: Server-Side SQL Updates

Every client DBC change must be mirrored on the server. For existing spells, the server typically reads from its own pre-loaded DBC data, but you can override specific fields using SQL tables.

### 6.1 - Override via spell_dbc

For AzerothCore, the `spell_dbc` table overrides specific spell fields:

```sql
-- Override Frostbolt (116) damage on server side to match client changes
-- Note: For stock spells, you may need to update the server DBC extract instead
-- The spell_dbc table is primarily for CUSTOM spells (90000+ range).
-- For stock spells, patch the server's Spell.dbc directly or use spell_bonus_data.
```

### 6.2 - spell_bonus_data for Scaling

The most common server-side change for existing spells is adjusting the spell power coefficient:

```sql
-- Change Frostbolt spell power coefficient
DELETE FROM `spell_bonus_data` WHERE `entry` = 116;
INSERT INTO `spell_bonus_data` (`entry`, `direct_bonus`, `dot_bonus`,
    `ap_bonus`, `ap_dot_bonus`, `comments`)
VALUES (116, 0.8143, 0, 0, 0, 'Frostbolt - buffed SP coefficient from 81.43%');

-- Change Fireball DoT coefficient
DELETE FROM `spell_bonus_data` WHERE `entry` = 133;
INSERT INTO `spell_bonus_data` (`entry`, `direct_bonus`, `dot_bonus`,
    `ap_bonus`, `ap_dot_bonus`, `comments`)
VALUES (133, 1.0, 0.0, 0, 0, 'Fireball - 100% SP coefficient on direct');
```

### 6.3 - spell_custom_attr for Behavior Flags

```sql
-- Add custom attributes to a spell
-- These flags control special server-side behavior
DELETE FROM `spell_custom_attr` WHERE `entry` = 116;
INSERT INTO `spell_custom_attr` (`entry`, `attributes`)
VALUES (116, 0x00000000);

-- Useful attribute flags:
--   0x00000001 = SPELL_ATTR0_CU_ENCHANT_PROC
--   0x00000002 = SPELL_ATTR0_CU_CONE_BACK
--   0x00000004 = SPELL_ATTR0_CU_CONE_LINE
--   0x00000008 = SPELL_ATTR0_CU_SHARE_DAMAGE (splits damage between targets)
--   0x00000010 = SPELL_ATTR0_CU_NO_INITIAL_THREAT
--   0x00000100 = SPELL_ATTR0_CU_AURA_CC (treated as CC for diminishing returns)
--   0x00001000 = SPELL_ATTR0_CU_NO_PVP_FLAG (does not flag for PvP)
--   0x00010000 = SPELL_ATTR0_CU_DIRECT_DAMAGE (force direct damage type)
--   0x00020000 = SPELL_ATTR0_CU_CHARGE (charge spell behavior)
--   0x00040000 = SPELL_ATTR0_CU_PICKPOCKET (pickpocket spell)
--   0x00200000 = SPELL_ATTR0_CU_NEGATIVE_EFF0 (force negative effect 0)
--   0x00400000 = SPELL_ATTR0_CU_NEGATIVE_EFF1 (force negative effect 1)
--   0x00800000 = SPELL_ATTR0_CU_NEGATIVE_EFF2 (force negative effect 2)
--   0x01000000 = SPELL_ATTR0_CU_IGNORE_ARMOR (bypasses armor)
```

---

## Step 7: Reading All Fields Generically with get_record_field

The `DBCInjector` class provides a generic `get_record_field` method that reads any field from any record by index:

```python
# Read field 42 (ManaCost) from the 100th record as uint32
mana_cost = dbc.get_record_field(100, 42, '<I')

# Read field 80 (EffectBasePoints[0]) as signed int32
base_points = dbc.get_record_field(100, 80, '<i')

# Read field 47 (Speed) as float
speed = dbc.get_record_field(100, 47, '<f')

# Iterate all spells and find those with mana cost > 1000
filepath = os.path.join(DBC_DIR, 'Spell.dbc')
dbc = DBCInjector(filepath)

expensive_spells = []
for i in range(len(dbc.records)):
    spell_id = dbc.get_record_field(i, 0)
    mana = dbc.get_record_field(i, 42)
    if mana > 1000:
        name_offset = dbc.get_record_field(i, 136)
        name = dbc.get_string(name_offset)
        expensive_spells.append((spell_id, name, mana))

print("Spells with mana cost > 1000:")
for sid, name, mana in expensive_spells[:20]:
    print("  {} - {} (cost: {})".format(sid, name, mana))
```

---

## Step 8: Using find_max_field for Safe Modifications

When adding values that reference other tables (like SpellIcon IDs), use `find_max_field` to determine the current maximum:

```python
filepath = os.path.join(DBC_DIR, 'Spell.dbc')
dbc = DBCInjector(filepath)

# Find the highest SpellIconID currently used across all spells
max_icon_id = dbc.find_max_field(133)  # SpellIconID is field 133
print("Max SpellIconID in use: {}".format(max_icon_id))

# Find the highest spell ID
max_spell_id = dbc.get_max_id()
print("Max spell ID: {}".format(max_spell_id))

# Find the highest mana cost
max_mana = dbc.find_max_field(42)
print("Max mana cost: {}".format(max_mana))
```

---

## Client-Server Synchronization Checklist

When modifying any spell field, check whether both sides need updating:

| Field             | Client (DBC) | Server (SQL/DBC) | Sync Required? |
|-------------------|:------------:|:----------------:|:--------------:|
| ManaCost          | Tooltip      | Enforced         | YES            |
| CastingTimeIndex  | Cast bar     | Validated        | YES            |
| RecoveryTime      | Cooldown UI  | Enforced         | YES            |
| RangeIndex        | Tooltip      | Range check      | YES            |
| EffectBasePoints  | Tooltip $s1  | Damage calc      | YES            |
| EffectDieSides    | Tooltip      | Damage calc      | YES            |
| SchoolMask        | Text color   | Resist calc      | YES            |
| SpellIconID       | Icon display | Not used         | NO             |
| SpellVisualID     | VFX          | Not used         | NO             |
| Name_lang         | Tooltip      | Combat log       | OPTIONAL       |
| Description_lang  | Tooltip      | Not used         | NO             |
| Speed             | Missile VFX  | Travel time      | YES            |
| BonusCoefficient  | Not used     | SP scaling       | NO (server)    |

Fields marked "NO" are purely client-side or purely server-side and do not need synchronization. Fields marked "YES" must match between client and server for correct behavior.

---

## Common Pitfalls and Troubleshooting

### Changed damage in DBC but damage in-game did not change
- **Cause**: The server uses its own DBC extract, not the client's copy. Your change only affected the client tooltip.
- **Fix**: Also update the server's Spell.dbc (in the server's `dbc` directory) or use `spell_dbc` overrides for custom spells.

### Cast time shows correctly in tooltip but server uses old cast time
- **Cause**: Server has its own CastingTimeIndex interpretation. If you changed the DBC but not the server copy, they diverge.
- **Fix**: Copy the modified Spell.dbc to the server's DBC directory and restart.

### String block grows too large
- **Cause**: Each `add_string` call appends to the string block. Repeated modifications with new strings will grow the file.
- **Fix**: The `DBCInjector` deduplicates strings automatically. If adding the same string twice, it returns the existing offset. Do not worry about growth unless you are adding thousands of unique strings.

### Modified spell crashes the client
- **Cause**: Record size mismatch. If the modified record is not exactly 936 bytes, the DBC file becomes corrupt.
- **Fix**: Use `modify_spell_field` which modifies in-place without changing record size. Never append or remove bytes from an existing record.

---

## Cross-References

- [Add New Spell](./add_new_spell.md) - Creating spells from scratch
- [Modify Talent Tree](./modify_talent_tree.md) - Assigning modified spells to talents
- [Change Racial Traits](./change_racial_traits.md) - Modifying racial passive spells
- [Add New Class](./add_new_class.md) - Modifying entire class spell kits
