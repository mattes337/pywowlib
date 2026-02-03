# Create Item Set

**Complexity:** Advanced | **Estimated Time:** 45-90 minutes | **Files Modified:** ItemSet.dbc, item_template SQL, optionally Spell.dbc | **Key APIs:** `world_builder.dbc_injector.register_item_set`, `world_builder.dbc_injector.register_spell`, `world_builder.sql_generator.SQLGenerator`

## Overview

Item sets in WoW WotLK 3.3.5a are collections of equipment that grant cumulative bonuses when multiple pieces from the set are equipped simultaneously. Classic examples include Tier armor sets (e.g., "Sanctified Ymirjar Lord's Battlegear" granting 2-piece and 4-piece bonuses) and crafted sets (e.g., "Frostweave" granting stat bonuses at 3 pieces).

Creating a custom item set requires:

1. **ItemSet.dbc** (client-side) -- Defines the set name, which items belong to it, and what spells are triggered at each piece-count threshold.
2. **item_template SQL** (server-side) -- Each item in the set must have its `itemset` column set to the corresponding ItemSet.dbc ID.
3. **Spell.dbc** (client-side, optional) -- If your set bonuses grant custom spells/auras, those spells must exist in Spell.dbc. You can also reuse existing spell IDs from Blizzard's data.

The client reads ItemSet.dbc to display the set tooltip (listing all pieces, showing owned/total counts, and displaying bonus text with green/gray coloring). The server reads the `itemset` column on each equipped item to count pieces and apply the corresponding spell auras.

## Prerequisites

- Python 3.7 or later
- pywowlib repository with `world_builder/` on Python path
- Extracted DBC files from `DBFilesClient/`
- Completed items created via the [Add New Item](add_new_item.md) guide
- AzerothCore 3.3.5a `acore_world` database
- Knowledge of which spell IDs to use for set bonuses (see Spell.dbc section)

## Table of Contents

1. [Step 1: Understand ItemSet.dbc Layout](#step-1-understand-itemsetdbc-layout)
2. [Step 2: Plan Your Item Set](#step-2-plan-your-item-set)
3. [Step 3: Create the ItemSet.dbc Entry](#step-3-create-the-itemsetdbc-entry)
4. [Step 4: Link Items to the Set via SQL](#step-4-link-items-to-the-set-via-sql)
5. [Step 5: Set Bonus Spells](#step-5-set-bonus-spells)
6. [Step 6: Complete Working Example](#step-6-complete-working-example)
7. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
8. [Cross-References](#cross-references)

---

## Step 1: Understand ItemSet.dbc Layout

### ItemSet.dbc Field Layout (WotLK 3.3.5a build 12340)

The WotLK 3.3.5a ItemSet.dbc layout covers builds 3.0.1.8303 through 3.3.5.12340 and contains the following fields:

| Field Index | Byte Offset | Field Name | Type | Count | Description |
|---|---|---|---|---|---|
| 0 | 0 | ID | uint32 | 1 | Unique set ID |
| 1-17 | 4-68 | Name_lang | locstring | 17 | Set display name (enUS at index 1, mask at index 17) |
| 18-34 | 72-136 | ItemID[17] | uint32 | 17 | Up to 17 item entry IDs belonging to this set |
| 35-42 | 140-168 | SetSpellID[8] | uint32 | 8 | Up to 8 set bonus spell IDs |
| 43-50 | 172-200 | SetThreshold[8] | uint32 | 8 | Piece count needed to activate each corresponding SetSpellID |
| 51 | 204 | RequiredSkill | uint32 | 1 | Required skill ID (0=none, e.g. 755 for Jewelcrafting) |
| 52 | 208 | RequiredSkillRank | uint32 | 1 | Required skill rank (0=none) |

**Total: 53 fields = 212 bytes per record**

### Field Details

**Name_lang (fields 1-17):** WotLK localized string format. This is 17 uint32 values: 8 locale string offsets (enUS, koKR, frFR, deDE, zhCN, zhTW, esES, esMX), 8 unused locale slots, and 1 flags/mask uint32. For English-only content, set enUS (field index 1) to the string offset and the mask (field index 17) to `0xFFFFFFFF`. All other locale fields should be 0.

**ItemID[17] (fields 18-34):** Array of 17 item entry IDs. Fill in the items that belong to this set. Unused slots must be 0. The order determines how items appear in the set tooltip. Typically ordered: Head, Shoulders, Chest, Hands, Legs (for 5-piece tier sets), or however you prefer.

**SetSpellID[8] (fields 35-42):** Array of 8 spell IDs for set bonuses. Each corresponds to a threshold in SetThreshold. Slot 0 is the first bonus, slot 1 is the second, etc. Spells are applied as passive auras when the threshold is met. Use 0 for unused slots.

**SetThreshold[8] (fields 43-50):** Array of 8 piece-count thresholds. Each value indicates how many items from the set must be equipped to activate the corresponding SetSpellID. For example, `SetThreshold[0]=2` and `SetSpellID[0]=70805` means "When 2 pieces are equipped, apply spell 70805."

### How the Client Displays Set Bonuses

The set tooltip is constructed entirely from the DBC data:

```
Ymirjar Lord's Battlegear (0/5)
  Head of the Ymirjar Lord     -- from ItemID[0], colored gray
  Shoulders of the Ymirjar Lord -- from ItemID[1], colored gray
  Chest of the Ymirjar Lord    -- from ItemID[2], colored gray
  Hands of the Ymirjar Lord    -- from ItemID[3], colored gray
  Legs of the Ymirjar Lord     -- from ItemID[4], colored gray

(2) Set: Your Bloodthirst critical strikes have a 50% chance  -- from SetSpellID[0] description
                                                               -- colored gray (not active)
(4) Set: You gain 10% increased damage               -- from SetSpellID[1] description
                                                       -- colored gray (not active)
```

When pieces are equipped, owned items turn white and activated bonuses turn green.

---

## Step 2: Plan Your Item Set

Before writing any code, plan your set structure:

| Decision | Example | Notes |
|---|---|---|
| Set name | "Stormforged Battlegear" | Displayed in tooltip |
| Number of pieces | 5 | Max 17 items per set |
| Which item slots | Head, Shoulders, Chest, Hands, Legs | Must each have unique entry IDs |
| 2-piece bonus spell | Spell 99901 | Must exist in Spell.dbc |
| 4-piece bonus spell | Spell 99902 | Must exist in Spell.dbc |
| Required skill | 0 (none) | Non-zero limits set to profession users |
| Item entry IDs | 90020-90024 | Must match item_template entries |

### Set Size Guidelines

| Set Size | Typical Use | Thresholds |
|---|---|---|
| 2 pieces | PvP offset, crafted sets | (2) |
| 3 pieces | Crafted armor sets | (2), (3) |
| 5 pieces | Tier raid sets | (2), (4) |
| 8 pieces | Classic dungeon sets | (2), (4), (6), (8) |

---

## Step 3: Create the ItemSet.dbc Entry

### Python Code: Register ItemSet.dbc Record (Recommended)

The `register_item_set()` convenience function handles locstring packing,
record construction, auto-ID assignment, and DBC file I/O in a single call:

```python
from world_builder import register_item_set

# Create a 5-piece plate DPS tier set
set_id = register_item_set(
    dbc_dir='C:/wow335/DBFilesClient',
    name='Stormforged Battlegear',
    item_ids=[
        90020,  # Head
        90021,  # Shoulders
        90022,  # Chest
        90023,  # Hands
        90024,  # Legs
    ],
    bonuses=[
        (2, 70803),  # 2-piece bonus: spell 70803
        (4, 70804),  # 4-piece bonus: spell 70804
    ],
    set_id=900,               # Explicit ID (omit for auto max_id + 1)
)
print("Registered ItemSet.dbc entry:", set_id)
```

**`register_item_set()` Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dbc_dir` | str | (required) | Path to directory containing ItemSet.dbc |
| `name` | str | (required) | Set display name (e.g. "Battlegear of Wrath") |
| `item_ids` | list[int] | (required) | Up to 17 item entry IDs in the set |
| `bonuses` | list[tuple] / None | None | List of `(piece_count, spell_id)` tuples, up to 8 |
| `set_id` | int / None | None | Specific set ID, or None for auto (max_id + 1) |
| `required_skill` | int | 0 | FK to SkillLine.dbc (0=none) |
| `required_skill_rank` | int | 0 | Required skill level (0=none) |

**Returns:** `int` -- the assigned set ID.

**Bonuses format:** Each tuple is `(piece_count, spell_id)`. For example,
`(2, 70803)` means "when 2 set pieces are equipped, apply spell 70803." The
function maps these into the SetSpellID and SetThreshold arrays internally.

### Auto-ID Assignment

When `set_id` is omitted, the function reads the current highest ID from
ItemSet.dbc and assigns `max_id + 1`:

```python
from world_builder import register_item_set

auto_set_id = register_item_set(
    dbc_dir='C:/wow335/DBFilesClient',
    name='Frostweave Regalia',
    item_ids=[90030, 90031, 90032],
    bonuses=[(3, 12345)],     # 3-piece bonus
)
print("Auto-assigned set ID:", auto_set_id)
```

### Low-Level Alternative

If you need finer control over the 212-byte binary record, you can use
`DBCInjector` and `_pack_locstring` directly:

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring

filepath = os.path.join('C:/wow335/DBFilesClient', 'ItemSet.dbc')
dbc = DBCInjector(filepath)

name_offset = dbc.add_string('Stormforged Battlegear')

buf = bytearray()
buf += struct.pack('<I', 900)                    # ID
buf += _pack_locstring(name_offset)              # Name_lang (17 uint32)
items = [90020, 90021, 90022, 90023, 90024] + [0] * 12
buf += struct.pack('<17I', *items)               # ItemID[17]
spells = [70803, 70804] + [0] * 6
buf += struct.pack('<8I', *spells)               # SetSpellID[8]
thresholds = [2, 4] + [0] * 6
buf += struct.pack('<8I', *thresholds)           # SetThreshold[8]
buf += struct.pack('<II', 0, 0)                  # RequiredSkill, RequiredSkillRank

assert len(buf) == 212
dbc.records.append(bytes(buf))
dbc.write(filepath)
```

### Understanding _pack_locstring

The `_pack_locstring` helper function from `dbc_injector.py` creates the 17-uint32 localized string structure used throughout WotLK DBC files. It places the string offset in the enUS slot (index 0 of the 17 values) and sets the mask at the end to `0xFFFFFFFF`:

```python
# From dbc_injector.py -- already available in pywowlib
def _pack_locstring(string_offset):
    values = [0] * 17          # 8 locales + 8 unused + 1 mask
    values[0] = string_offset  # enUS
    values[16] = 0xFFFFFFFF    # mask
    return struct.pack('<17I', *values)
```

You import it directly: `from world_builder.dbc_injector import _pack_locstring`

---

## Step 4: Link Items to the Set via SQL

Each item that belongs to the set must have its `itemset` column in `item_template` set to the ItemSet.dbc ID. This is how the server knows which items are part of which set for piece-count tracking.

### Python Code: Generate Set Items with SQLGenerator

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90020)

# Define all 5 set pieces
set_items = [
    {
        'entry': 90020,
        'name': 'Stormforged Helmet',
        'class': 4, 'subclass': 4,          # Plate
        'displayid': 51000,                   # Reuse existing display
        'quality': 4,                         # Epic
        'inventory_type': 1,                  # Head
        'item_level': 251,
        'required_level': 80,
        'bonding': 1,                         # BoP
        'material': 6,                        # Plate
        'itemset': 900,                       # <<< Links to ItemSet.dbc ID 900
        'stats': [
            {'type': 4, 'value': 107},        # Strength
            {'type': 7, 'value': 98},         # Stamina
            {'type': 32, 'value': 72},        # Crit Rating
            {'type': 31, 'value': 52},        # Hit Rating
        ],
        'armor': 1834,
        'max_durability': 100,
        'socket_color_1': 1,                  # Meta
        'socket_color_2': 2,                  # Red
        'socket_bonus': 3312,                 # +4 Strength
    },
    {
        'entry': 90021,
        'name': 'Stormforged Pauldrons',
        'class': 4, 'subclass': 4,
        'displayid': 51001,
        'quality': 4,
        'inventory_type': 3,                  # Shoulders
        'item_level': 251,
        'required_level': 80,
        'bonding': 1,
        'material': 6,
        'itemset': 900,                       # <<< Same set ID
        'stats': [
            {'type': 4, 'value': 88},
            {'type': 7, 'value': 82},
            {'type': 36, 'value': 56},        # Haste
            {'type': 37, 'value': 48},        # Expertise
        ],
        'armor': 1680,
        'max_durability': 100,
        'socket_color_1': 2,                  # Red
        'socket_bonus': 3312,
    },
    {
        'entry': 90022,
        'name': 'Stormforged Breastplate',
        'class': 4, 'subclass': 4,
        'displayid': 51002,
        'quality': 4,
        'inventory_type': 5,                  # Chest
        'item_level': 251,
        'required_level': 80,
        'bonding': 1,
        'material': 6,
        'itemset': 900,
        'stats': [
            {'type': 4, 'value': 114},
            {'type': 7, 'value': 105},
            {'type': 32, 'value': 76},
            {'type': 44, 'value': 64},        # Armor Pen
        ],
        'armor': 2245,
        'max_durability': 165,
        'socket_color_1': 2,
        'socket_color_2': 4,                  # Yellow
        'socket_bonus': 3370,                 # +6 Strength
    },
    {
        'entry': 90023,
        'name': 'Stormforged Gauntlets',
        'class': 4, 'subclass': 4,
        'displayid': 51003,
        'quality': 4,
        'inventory_type': 10,                 # Hands
        'item_level': 251,
        'required_level': 80,
        'bonding': 1,
        'material': 6,
        'itemset': 900,
        'stats': [
            {'type': 4, 'value': 88},
            {'type': 7, 'value': 82},
            {'type': 37, 'value': 56},
            {'type': 36, 'value': 48},
        ],
        'armor': 1527,
        'max_durability': 55,
        'socket_color_1': 2,
        'socket_bonus': 3312,
    },
    {
        'entry': 90024,
        'name': 'Stormforged Legplates',
        'class': 4, 'subclass': 4,
        'displayid': 51004,
        'quality': 4,
        'inventory_type': 7,                  # Legs
        'item_level': 251,
        'required_level': 80,
        'bonding': 1,
        'material': 6,
        'itemset': 900,
        'stats': [
            {'type': 4, 'value': 107},
            {'type': 7, 'value': 98},
            {'type': 32, 'value': 68},
            {'type': 31, 'value': 56},
        ],
        'armor': 1988,
        'max_durability': 120,
        'socket_color_1': 2,
        'socket_color_2': 4,
        'socket_bonus': 3370,
    },
]

gen.add_items(set_items)
gen.write_sql('output/stormforged_set.sql')

print("Generated SQL for {} set items".format(len(set_items)))
print("All items linked to ItemSet ID 900")
```

### Critical Requirement: itemset Column

The single most important field for set functionality is `itemset` in the item definition dict. When `SQLGenerator.add_items()` processes this, it writes the value into the `itemset` column of the `item_template` SQL. The server uses this column to:

1. Count how many items with the same `itemset` value are equipped
2. Look up the corresponding ItemSet.dbc entry
3. Apply/remove set bonus auras based on the piece count vs. thresholds

If you forget to set `itemset` on even one piece, that piece will not count toward set bonuses when equipped.

---

## Step 5: Set Bonus Spells

### Using Existing Blizzard Spells

The simplest approach is to reuse existing spell IDs from Blizzard's Spell.dbc. Every set bonus in retail WotLK has a corresponding spell that you can look up. Examples:

| Spell ID | Set Bonus Description | Original Set |
|---|---|---|
| 70803 | Increases melee haste by 6% | T10 Warrior DPS 2pc |
| 70804 | Your Bloodthirst and Mortal Strike deal 10% more damage | T10 Warrior DPS 4pc |
| 67383 | Your Holy Light heal has a 40% chance to heal nearby target | T9 Paladin Holy 2pc |
| 67378 | Each time your Sacred Shield absorbs damage, heal target for 100% of absorbed amount | T9 Paladin Holy 4pc |
| 64763 | Reduces Swipe(Bear) mana cost by 10% | T8 Druid Feral 2pc |

To find spell IDs for existing set bonuses, browse ItemSet.dbc records and cross-reference their SetSpellID fields, or look up set bonuses on Wowhead and note the spell IDs from the tooltip URLs.

### Creating Custom Set Bonus Spells with register_spell()

If you need entirely custom set bonus effects, use `register_spell()` to create
new Spell.dbc entries. For a passive set bonus aura, the key parameters are:

- `effect_1=6` (SPELL_EFFECT_APPLY_AURA)
- `effect_1_aura` set to the desired aura type
- `effect_1_target_a=1` (TARGET_UNIT_CASTER)
- `attributes=0x00000480` (PASSIVE + NOT_CASTABLE)
- `duration_index=21` (infinite/permanent)

#### Python Code: Create a Custom Set Bonus Spell (Recommended)

```python
from world_builder import register_spell

# 2-piece bonus: +10% damage done (all schools)
bonus_2pc_spell = register_spell(
    dbc_dir='C:/wow335/DBFilesClient',
    name='Stormforged 2P Bonus',
    description='Increases all damage done by $s1%.',
    attributes=0x00000480,       # PASSIVE + NOT_CASTABLE
    cast_time_index=1,           # Instant
    duration_index=21,           # Infinite (permanent while equipped)
    range_index=1,               # Self only
    effect_1=6,                  # SPELL_EFFECT_APPLY_AURA
    effect_1_aura=13,            # SPELL_AURA_MOD_DAMAGE_PERCENT_DONE
    effect_1_base_points=9,      # +10% (base_points = actual_value - 1)
    effect_1_target_a=1,         # TARGET_UNIT_CASTER
    effect_1_misc_value=127,     # School mask (127 = all schools)
    spell_icon_id=1,             # Generic icon
)

# 4-piece bonus: +6% melee haste
bonus_4pc_spell = register_spell(
    dbc_dir='C:/wow335/DBFilesClient',
    name='Stormforged 4P Bonus',
    description='Increases melee haste by $s1%.',
    attributes=0x00000480,
    cast_time_index=1,
    duration_index=21,
    range_index=1,
    effect_1=6,                  # SPELL_EFFECT_APPLY_AURA
    effect_1_aura=79,            # SPELL_AURA_MOD_MELEE_HASTE
    effect_1_base_points=5,      # +6% (base_points = value - 1)
    effect_1_target_a=1,
    spell_icon_id=1,
)

print("2pc spell:", bonus_2pc_spell)
print("4pc spell:", bonus_4pc_spell)
```

**`register_spell()` Parameters (key fields for set bonuses):**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dbc_dir` | str | (required) | Path to directory containing Spell.dbc |
| `name` | str | (required) | Spell display name (enUS locstring) |
| `spell_id` | int/None | None | Specific ID, or None for auto (max_id + 1) |
| `attributes` | int | 0 | Spell attributes bitmask (0x00000480 for passive set bonuses) |
| `cast_time_index` | int | 1 | FK to SpellCastTimes.dbc (1 = instant) |
| `duration_index` | int | 0 | FK to SpellDuration.dbc (21 = infinite) |
| `range_index` | int | 0 | FK to SpellRange.dbc (1 = self) |
| `effect_1` | int | 0 | Effect type (6 = APPLY_AURA) |
| `effect_1_aura` | int | 0 | Aura type (13=damage%, 79=haste, etc.) |
| `effect_1_base_points` | int | 0 | Effect magnitude minus 1 |
| `effect_1_target_a` | int | 0 | Implicit target (1 = caster) |
| `effect_1_misc_value` | int | 0 | Misc value (school mask for damage mods) |
| `description` | str/None | None | Tooltip description (supports $s1 for effect value) |
| `spell_icon_id` | int | 1 | FK to SpellIcon.dbc |
| `**kwargs` | | | Any additional Spell.dbc field by _SPELL_FIELD_MAP name |

**Returns:** `int` -- the assigned spell ID.

The function supports all three effect slots (`effect_1`/`effect_2`/`effect_3`)
and accepts additional Spell.dbc field overrides via `**kwargs`.

#### Spell.dbc WotLK 3.3.5a Layout Summary

The Spell.dbc for build 3.3.3.11685 through 3.3.5.12340 is one of the largest DBC files, with approximately 234 fields per record. For a set bonus spell, the critical fields are:

| Key Field | Description | Set Bonus Value |
|---|---|---|
| ID | Unique spell ID | Your custom ID (e.g., 99901) |
| Attributes | Spell attribute flags | 0x00000400 (passive) + 0x00000080 (cannot be cast) |
| AttributesEx | Extended attributes | 0 |
| Effect[0] | Spell effect type | 6 (SPELL_EFFECT_APPLY_AURA) for passive auras |
| EffectAura[0] | Aura type | Depends on bonus (e.g., 13=SPELL_AURA_MOD_DAMAGE_PERCENT_DONE) |
| EffectBasePoints[0] | Effect magnitude | e.g., 9 for +10% (base is always value-1) |
| EffectMiscValue[0] | Misc value | School mask for damage bonuses (1=Physical, 127=All) |
| DurationIndex | Duration index | 21 (for -1, infinite/permanent duration) |
| Name_lang | Spell name | Tooltip title |
| Description_lang | Spell description | Tooltip body text (supports $s1 for effect value) |

#### Low-Level Alternative

For full manual control over the ~234-field spell record, you can still use
`DBCInjector` directly. See the [Custom Crafting Recipe](custom_crafting_recipe.md)
guide for an example of low-level Spell.dbc construction.

### Common Aura Types for Set Bonuses

| Aura Type | Constant | Description | EffectMiscValue Usage |
|---|---|---|---|
| 3 | SPELL_AURA_DUMMY | Script-handled bonus | Custom per script |
| 8 | SPELL_AURA_MOD_DAMAGE_DONE | Flat damage increase | School mask (1=Phys, 2=Holy, 127=All) |
| 13 | SPELL_AURA_MOD_DAMAGE_PERCENT_DONE | % damage increase | School mask |
| 22 | SPELL_AURA_MOD_RESISTANCE | Flat resistance/armor increase | School mask |
| 29 | SPELL_AURA_MOD_STAT | Flat stat increase | Stat index (-1=all, 0=Str, 1=Agi, etc.) |
| 42 | SPELL_AURA_PROC_TRIGGER_SPELL | Chance to trigger spell on proc | N/A (use EffectTriggerSpell) |
| 52 | SPELL_AURA_MOD_CRIT_PERCENT | Crit chance % increase | N/A |
| 65 | SPELL_AURA_MOD_POWER_REGEN | Mana regen increase | Power type (0=Mana) |
| 79 | SPELL_AURA_MOD_MELEE_HASTE | Melee haste % increase | N/A |
| 108 | SPELL_AURA_MOD_ATTACKER_SPELL_CRIT_CHANCE | Reduce enemy spell crit chance | School mask |
| 189 | SPELL_AURA_MOD_RATING | Modify combat rating | Rating mask |
| 236 | SPELL_AURA_MOD_HEALING_DONE | Healing done increase | School mask |

---

## Step 6: Complete Working Example

This example creates a complete 5-piece plate DPS set with 2-piece and 4-piece bonuses using the convenience APIs.

```python
"""
Complete example: Create a 5-piece plate DPS item set for WotLK 3.3.5a.

Creates:
1. (Optional) Custom set bonus spells in Spell.dbc via register_spell()
2. ItemSet.dbc entry via register_item_set()
3. item_template SQL for all 5 set pieces with itemset linkage

Prerequisites:
- Extracted DBC files in DBC_DIR
- pywowlib on Python path
"""
import os
from world_builder import register_spell, register_item_set
from world_builder.sql_generator import SQLGenerator

# Configuration
DBC_DIR = 'C:/wow335/DBFilesClient'
SQL_OUTPUT = 'output/stormforged_set.sql'

SET_NAME = 'Stormforged Battlegear'
ITEM_IDS = [90020, 90021, 90022, 90023, 90024]

# ----------------------------------------------------------------
# Step 1: Create set bonus spells via register_spell()
# ----------------------------------------------------------------
# (You can also reuse existing Blizzard spell IDs -- see Step 5)
SPELL_2PC = register_spell(
    dbc_dir=DBC_DIR,
    name='Stormforged 2P Bonus',
    description='Increases melee haste by $s1%.',
    attributes=0x00000480,       # PASSIVE + NOT_CASTABLE
    cast_time_index=1,
    duration_index=21,           # Infinite
    range_index=1,               # Self
    effect_1=6,                  # SPELL_EFFECT_APPLY_AURA
    effect_1_aura=79,            # SPELL_AURA_MOD_MELEE_HASTE
    effect_1_base_points=5,      # +6%
    effect_1_target_a=1,         # TARGET_UNIT_CASTER
    spell_icon_id=1,
)
print("[OK] Spell.dbc: 2pc bonus spell {}".format(SPELL_2PC))

SPELL_4PC = register_spell(
    dbc_dir=DBC_DIR,
    name='Stormforged 4P Bonus',
    description='Your Bloodthirst and Mortal Strike deal $s1% more damage.',
    attributes=0x00000480,
    cast_time_index=1,
    duration_index=21,
    range_index=1,
    effect_1=6,
    effect_1_aura=13,            # SPELL_AURA_MOD_DAMAGE_PERCENT_DONE
    effect_1_base_points=9,      # +10%
    effect_1_target_a=1,
    effect_1_misc_value=1,       # Physical school
    spell_icon_id=1,
)
print("[OK] Spell.dbc: 4pc bonus spell {}".format(SPELL_4PC))

# ----------------------------------------------------------------
# Step 2: Create ItemSet.dbc entry via register_item_set()
# ----------------------------------------------------------------
SET_ID = register_item_set(
    dbc_dir=DBC_DIR,
    name=SET_NAME,
    item_ids=ITEM_IDS,
    bonuses=[
        (2, SPELL_2PC),   # 2-piece bonus
        (4, SPELL_4PC),   # 4-piece bonus
    ],
)
print("[OK] ItemSet.dbc: created set '{}' (ID={})".format(SET_NAME, SET_ID))

# ----------------------------------------------------------------
# Step 3: Generate item_template SQL for all set pieces
# ----------------------------------------------------------------
gen = SQLGenerator(start_entry=90020)

# Base stats template for a T10-equivalent plate DPS set
base_stats = {
    'class': 4,                # Armor
    'subclass': 4,             # Plate
    'quality': 4,              # Epic
    'required_level': 80,
    'bonding': 1,              # BoP
    'material': 6,             # Plate
    'itemset': SET_ID,         # THE CRITICAL LINKAGE
    'allowable_class': 0x021,  # Warrior + Death Knight
    'allowable_race': -1,
}

set_pieces = [
    {
        **base_stats,
        'entry': 90020,
        'name': 'Stormforged Helmet',
        'displayid': 51000,
        'inventory_type': 1,     # Head
        'item_level': 251,
        'stats': [
            {'type': 4, 'value': 107},
            {'type': 7, 'value': 98},
            {'type': 32, 'value': 72},
            {'type': 31, 'value': 52},
        ],
        'armor': 1834,
        'max_durability': 100,
        'socket_color_1': 1,     # Meta
        'socket_color_2': 2,     # Red
        'socket_bonus': 3312,
    },
    {
        **base_stats,
        'entry': 90021,
        'name': 'Stormforged Pauldrons',
        'displayid': 51001,
        'inventory_type': 3,     # Shoulders
        'item_level': 251,
        'stats': [
            {'type': 4, 'value': 88},
            {'type': 7, 'value': 82},
            {'type': 36, 'value': 56},
            {'type': 37, 'value': 48},
        ],
        'armor': 1680,
        'max_durability': 100,
        'socket_color_1': 2,
        'socket_bonus': 3312,
    },
    {
        **base_stats,
        'entry': 90022,
        'name': 'Stormforged Breastplate',
        'displayid': 51002,
        'inventory_type': 5,     # Chest
        'item_level': 251,
        'stats': [
            {'type': 4, 'value': 114},
            {'type': 7, 'value': 105},
            {'type': 32, 'value': 76},
            {'type': 44, 'value': 64},
        ],
        'armor': 2245,
        'max_durability': 165,
        'socket_color_1': 2,
        'socket_color_2': 4,
        'socket_bonus': 3370,
    },
    {
        **base_stats,
        'entry': 90023,
        'name': 'Stormforged Gauntlets',
        'displayid': 51003,
        'inventory_type': 10,    # Hands
        'item_level': 251,
        'stats': [
            {'type': 4, 'value': 88},
            {'type': 7, 'value': 82},
            {'type': 37, 'value': 56},
            {'type': 36, 'value': 48},
        ],
        'armor': 1527,
        'max_durability': 55,
        'socket_color_1': 2,
        'socket_bonus': 3312,
    },
    {
        **base_stats,
        'entry': 90024,
        'name': 'Stormforged Legplates',
        'displayid': 51004,
        'inventory_type': 7,     # Legs
        'item_level': 251,
        'stats': [
            {'type': 4, 'value': 107},
            {'type': 7, 'value': 98},
            {'type': 32, 'value': 68},
            {'type': 31, 'value': 56},
        ],
        'armor': 1988,
        'max_durability': 120,
        'socket_color_1': 2,
        'socket_color_2': 4,
        'socket_bonus': 3370,
    },
]

gen.add_items(set_pieces)

os.makedirs(os.path.dirname(SQL_OUTPUT), exist_ok=True)
gen.write_sql(SQL_OUTPUT)
print("[OK] SQL written to: {}".format(SQL_OUTPUT))
print()
print("Set summary:")
print("  Set Name: {}".format(SET_NAME))
print("  Set ID: {}".format(SET_ID))
print("  Pieces: {} items ({})".format(len(ITEM_IDS), ', '.join(str(i) for i in ITEM_IDS)))
print("  2pc Bonus: Spell {}".format(SPELL_2PC))
print("  4pc Bonus: Spell {}".format(SPELL_4PC))
print()
print("Next steps:")
print("  1. Pack modified ItemSet.dbc and Spell.dbc into patch MPQ")
print("  2. Apply SQL to acore_world database")
print("  3. Restart worldserver and clear client cache")
print("  4. Test: .additem 90020-90024, equip 2 and 4 pieces")
```

---

## Common Pitfalls and Troubleshooting

### Problem: Set tooltip does not appear on items

**Cause:** The `itemset` column in `item_template` is 0 or does not match the ItemSet.dbc ID.

**Fix:**
- Verify every set piece has `'itemset': SET_ID` in its item definition
- Confirm the ItemSet.dbc record ID matches the `itemset` value exactly
- Ensure the modified ItemSet.dbc is in your client MPQ patch

### Problem: Set tooltip shows items but bonuses are missing or show wrong text

**Cause:** The SetSpellID values do not correspond to valid spells, or the spell description is empty.

**Fix:**
- Verify each SetSpellID value exists in Spell.dbc
- The set bonus text shown in the tooltip comes from the `Description_lang` field of the referenced spell in Spell.dbc, NOT from ItemSet.dbc itself
- If using custom spells, ensure their Description_lang locstring is populated

### Problem: Set bonus aura is not applied when equipping the required pieces

**Cause:** Server-side issue. The server reads `itemset` from `item_template` and looks up the set definition. But the set bonus spell application depends on the server's DBC loading.

**Fix:**
- AzerothCore loads some DBC files server-side. Ensure `ItemSet.dbc` is in the server's `dbc/` directory as well as the client's `DBFilesClient/`
- Verify the spell ID exists in the server's `Spell.dbc`
- Check server logs for "Unknown spell" warnings

### Problem: Set pieces counted incorrectly

**Cause:** Multiple items with the same entry ID, or duplicate items in the ItemID array.

**Fix:**
- Each set piece must have a unique `entry`/`ItemID`
- Do not list the same item ID twice in the ItemID[17] array
- The server counts unique item entries, not inventory quantity

### Problem: "Requires [Skill] (0)" showing on set tooltip

**Cause:** `RequiredSkill` is non-zero but `RequiredSkillRank` is 0.

**Fix:**
- If you do not want a skill requirement, set both fields to 0
- If you want a requirement (e.g., Jewelcrafting 400), set both fields appropriately

### Problem: Set can hold only 17 items but I need more

**Limitation:** The WotLK ItemSet.dbc format supports a maximum of 17 items per set. This is a hard limit of the file format.

**Workaround:** If you need more than 17 items (unusual), create two separate sets with different IDs. However, the set bonuses will be tracked independently for each.

---

## Cross-References

- **[Add New Item](add_new_item.md)** -- Create the individual items before linking them to a set
- **[Modify Loot Tables](modify_loot_tables.md)** -- Add your set pieces to boss loot tables
- **[Custom Crafting Recipe](custom_crafting_recipe.md)** -- Make set pieces craftable via professions
- **pywowlib API Reference:**
  - `world_builder.dbc_injector.register_item_set()` -- Convenience wrapper for ItemSet.dbc record creation (auto-ID, 53 fields / 212 bytes)
  - `world_builder.dbc_injector.register_spell()` -- Convenience wrapper for Spell.dbc record creation (auto-ID, named parameters for common fields)
  - `world_builder.dbc_injector.DBCInjector` -- Low-level DBC read/write
  - `world_builder.dbc_injector._pack_locstring()` -- WotLK localized string helper
  - `world_builder.sql_generator.SQLGenerator.add_items()` -- Item SQL generation with `itemset` support
