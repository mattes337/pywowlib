# Custom Crafting Recipe

**Complexity:** Expert | **Estimated Time:** 60-120 minutes | **Files Modified:** Spell.dbc, SkillLineAbility.dbc, optionally item_template SQL

## Overview

Creating a custom crafting recipe in WoW WotLK 3.3.5a allows players to craft your custom items through professions like Blacksmithing, Tailoring, Leatherworking, Alchemy, or any other trade skill. A complete crafting recipe requires entries across multiple systems:

1. **Spell.dbc** (client-side) -- The "craft" spell that, when cast, creates the output item. This spell uses `SPELL_EFFECT_CREATE_ITEM` (effect type 24) and defines the reagent requirements, cast time, and skill-up thresholds.
2. **SkillLineAbility.dbc** (client-side) -- Links the craft spell to a specific profession skill line (e.g., Blacksmithing = skill 164). This makes the recipe appear in the profession's recipe list.
3. **item_template SQL** (server-side, optional) -- If the recipe is learned from a recipe item (e.g., "Plans: Stormforged Blade"), you need an item with a "learn spell" on-use effect.

### How Crafting Works in WoW

When a player opens their profession window and clicks a recipe:

```
1. Client checks Spell.dbc for the craft spell
2. Client verifies:
   - Player has the required skill level (from SkillLineAbility.dbc)
   - Player has all reagents (from Spell.dbc Reagent/ReagentCount fields)
   - Player meets any other requirements
3. Client sends cast request to server
4. Server verifies all requirements independently
5. Server consumes reagents from player inventory
6. Server creates the output item (from Spell.dbc EffectItemType field)
7. If skill < trivial threshold, server grants a skill point
```

## Prerequisites

- Python 3.7 or later
- pywowlib repository with `world_builder/` on Python path
- Extracted DBC files from `DBFilesClient/` (including Spell.dbc, SkillLineAbility.dbc)
- Custom output item already created (see [Add New Item](add_new_item.md))
- AzerothCore 3.3.5a `acore_world` database
- Knowledge of the target profession's SkillLine ID

## Table of Contents

1. [Step 1: Understand the Crafting Data Model](#step-1-understand-the-crafting-data-model)
2. [Step 2: Create the Craft Spell in Spell.dbc](#step-2-create-the-craft-spell-in-spelldbc)
3. [Step 3: Link to Profession via SkillLineAbility.dbc](#step-3-link-to-profession-via-skilllineabilitydbc)
4. [Step 4: Create a Recipe Item (Optional)](#step-4-create-a-recipe-item-optional)
5. [Step 5: Complete Working Example](#step-5-complete-working-example)
6. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
7. [Reference Tables](#reference-tables)
8. [Cross-References](#cross-references)

---

## Step 1: Understand the Crafting Data Model

### Data Flow

```
SkillLineAbility.dbc          Spell.dbc (Craft Spell)
  |                              |
  +-- SkillLine = 164           +-- Effect[0] = CREATE_ITEM (24)
  |   (Blacksmithing)           +-- EffectItemType[0] = 90001 (output item)
  |                              +-- Reagent[0..7] = material item IDs
  +-- Spell = 99001             +-- ReagentCount[0..7] = material quantities
  |   (FK to Spell.dbc)         +-- CastingTimeIndex = cast time ref
  |                              +-- Name_lang = "Stormforged Blade"
  +-- MinSkillLineRank = 450    +-- Description_lang = "..."
  |   (required skill level)
  +-- TrivialSkillLineRankHigh = 475   (gray threshold)
  +-- TrivialSkillLineRankLow = 460    (yellow threshold)
  +-- AcquireMethod = 0 (trainer) or 1 (auto-learn)
```

### Key Relationships

| Source | Field | Target | Purpose |
|---|---|---|---|
| SkillLineAbility.Spell | Spell ID | Spell.dbc.ID | Links profession to craft spell |
| Spell.EffectItemType[0] | Item ID | item_template.entry | Output item created by crafting |
| Spell.Reagent[0..7] | Item IDs | item_template.entry | Required materials |
| Recipe item spellid_1 | Spell ID | Spell.dbc.ID | Learn-spell trigger |

### Profession SkillLine IDs (WotLK 3.3.5a)

| SkillLine ID | Profession | Max Skill (WotLK) |
|---|---|---|
| 164 | Blacksmithing | 450 |
| 165 | Leatherworking | 450 |
| 171 | Alchemy | 450 |
| 182 | Herbalism | 450 |
| 185 | Cooking | 450 |
| 186 | Mining | 450 |
| 197 | Tailoring | 450 |
| 202 | Engineering | 450 |
| 333 | Enchanting | 450 |
| 356 | Fishing | 450 |
| 393 | Skinning | 450 |
| 755 | Jewelcrafting | 450 |
| 773 | Inscription | 450 |
| 129 | First Aid | 450 |
| 762 | Riding | 300 |

---

## Step 2: Create the Craft Spell in Spell.dbc

### Spell.dbc Layout for Crafting Spells

The Spell.dbc for WotLK 3.3.5a (builds 3.3.3.11685 - 3.3.5.12340) has approximately 234 uint32/float fields. For a crafting spell, the critical fields are listed below. Fields not mentioned should be set to 0.

#### Critical Crafting Spell Fields

| Field Index | Field Name | Type | Crafting Value | Description |
|---|---|---|---|---|
| 0 | ID | uint32 | Your spell ID | Unique spell identifier |
| 4 | Attributes | uint32 | 0x00010000 | SPELL_ATTR0_TRADESPELL flag |
| 5 | AttributesEx | uint32 | 0 | Extended attributes |
| 6 | AttributesExB | uint32 | 0x20000000 | SPELL_ATTR2_NOT_IN_COMBAT_LOG |
| 28 | CastingTimeIndex | uint32 | See table | FK to SpellCastTimes.dbc |
| 40 | DurationIndex | uint32 | 0 | 0 = instant result |
| 41 | PowerType | uint32 | 0 | 0 = Mana (most craft spells cost 0 mana) |
| 42 | ManaCost | uint32 | 0 | Mana cost (usually 0 for crafting) |
| 46 | RangeIndex | uint32 | 1 | 1 = Self (0 yards) |
| 52-59 | Reagent[8] | uint32[8] | Material item IDs | Up to 8 different reagent types |
| 60-67 | ReagentCount[8] | uint32[8] | Quantities | Count for each reagent |
| 68 | EquippedItemClass | int32 | -1 | -1 = no equipped item requirement |
| 71 | Effect[0] | uint32 | 24 | SPELL_EFFECT_CREATE_ITEM |
| 86 | EffectBasePoints[0] | int32 | 0 | Base points (0 for create item) |
| 92 | ImplicitTargetA[0] | uint32 | 1 | TARGET_UNIT_CASTER |
| 113 | EffectItemType[0] | uint32 | Output item ID | The item created by this spell |
| 139 | SpellIconID | uint32 | Icon ID | FK to SpellIcon.dbc for recipe list icon |
| 142-158 | Name_lang | locstring | Spell name | Recipe name shown in profession window |
| 159-175 | NameSubtext_lang | locstring | Rank text | Optional: "Rank 2", etc. |
| 176-192 | Description_lang | locstring | Description | "Creates a Stormforged Blade." |

### SpellCastTimes.dbc Common Values

| CastingTimeIndex | Cast Time | Common Use |
|---|---|---|
| 1 | 0 ms (instant) | Enchanting, some special recipes |
| 8 | 2000 ms (2 sec) | Simple recipes |
| 16 | 3000 ms (3 sec) | Standard craft time |
| 51 | 5000 ms (5 sec) | Complex recipes |
| 121 | 10000 ms (10 sec) | Very complex recipes (Arcanite Bar, etc.) |
| 167 | 25000 ms (25 sec) | Extremely long crafts (Mooncloth, etc.) |

### Spell Effect Constants

| Constant | Value | Purpose |
|---|---|---|
| SPELL_EFFECT_CREATE_ITEM | 24 | Creates an item in caster's inventory |
| SPELL_EFFECT_CREATE_ITEM_2 | 157 | Creates item with random properties |
| SPELL_EFFECT_LEARN_SPELL | 36 | Teaches another spell (for recipe items) |
| SPELL_EFFECT_TRADE_SKILL | 95 | Opens trade skill window (special) |

### Python Code: Create a Craft Spell

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring

def create_craft_spell(
    dbc_dir,
    spell_id,
    name,
    output_item_id,
    reagents,
    description='',
    casting_time_index=16,     # 3 second cast
    spell_icon_id=1,
    output_quantity=1,
):
    """
    Create a crafting spell in Spell.dbc for WotLK 3.3.5a.

    The spell uses SPELL_EFFECT_CREATE_ITEM to produce an output item
    from reagent materials.

    Args:
        dbc_dir: Path to directory containing Spell.dbc.
        spell_id: Unique spell ID for this recipe.
        name: Recipe name shown in profession window.
        output_item_id: Item entry ID to create when cast.
        reagents: List of (item_id, count) tuples. Max 8 reagent types.
                  Example: [(36916, 12), (35623, 4)] for
                  12x Saronite Bar + 4x Eternal Earth.
        description: Tooltip description (e.g., "Creates a Stormforged Blade.").
        casting_time_index: FK to SpellCastTimes.dbc (16=3sec default).
        spell_icon_id: SpellIcon.dbc ID for the recipe icon.
        output_quantity: Number of items created per craft (usually 1).

    Returns:
        int: The spell_id that was injected.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    # Validate reagents
    if len(reagents) > 8:
        raise ValueError("Maximum 8 reagent types per spell, got {}".format(
            len(reagents)))

    # Pad reagents to exactly 8
    padded_reagents = list(reagents)[:8]
    while len(padded_reagents) < 8:
        padded_reagents.append((0, 0))

    # Get record size from loaded DBC
    record_size = dbc.record_size

    # Add strings to string block
    name_off = dbc.add_string(name)
    desc_off = dbc.add_string(description)

    # Build zero-filled record and patch critical fields
    buf = bytearray(record_size)

    def set_u32(field_idx, val):
        struct.pack_into('<I', buf, field_idx * 4, val)

    def set_i32(field_idx, val):
        struct.pack_into('<i', buf, field_idx * 4, val)

    def set_float(field_idx, val):
        struct.pack_into('<f', buf, field_idx * 4, val)

    def set_locstring(start_idx, string_off):
        set_u32(start_idx, string_off)     # enUS slot
        set_u32(start_idx + 16, 0xFFFFFFFF) # mask

    # -- Core identity --
    set_u32(0, spell_id)                   # ID

    # -- Attributes --
    # SPELL_ATTR0_TRADESPELL = 0x00010000
    # Additional: SPELL_ATTR0_IS_ABILITY = 0x00000010 (optional)
    set_u32(4, 0x00010010)                 # Attributes

    # SPELL_ATTR2_NOT_IN_COMBAT_LOG = 0x20000000
    set_u32(6, 0x20000000)                 # AttributesExB

    # -- Cast configuration --
    set_u32(28, casting_time_index)        # CastingTimeIndex
    set_u32(35, 101)                       # ProcChance
    set_u32(40, 0)                         # DurationIndex (0=instant result)
    set_u32(41, 0)                         # PowerType (0=Mana)
    set_u32(42, 0)                         # ManaCost (0)
    set_u32(46, 1)                         # RangeIndex (1=Self)

    # -- Reagents --
    # Reagent[8]: fields 52-59
    for i, (item_id, _count) in enumerate(padded_reagents):
        set_u32(52 + i, item_id)

    # ReagentCount[8]: fields 60-67
    for i, (_item_id, count) in enumerate(padded_reagents):
        set_u32(60 + i, count)

    # -- Equipped item requirement --
    set_i32(68, -1)                        # EquippedItemClass = -1 (none)

    # -- Effect 0: CREATE_ITEM --
    set_u32(71, 24)                        # Effect[0] = SPELL_EFFECT_CREATE_ITEM
    set_u32(74, 1)                         # EffectDieSides[0] = 1
    set_i32(86, output_quantity - 1)       # EffectBasePoints[0] (quantity - 1)
    set_u32(92, 1)                         # ImplicitTargetA[0] = TARGET_UNIT_CASTER
    set_u32(113, output_item_id)           # EffectItemType[0] = output item

    # -- Visuals --
    set_u32(139, spell_icon_id)            # SpellIconID

    # -- Name and Description --
    set_locstring(142, name_off)           # Name_lang
    set_locstring(176, desc_off)           # Description_lang

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return spell_id


# Example: Blacksmithing recipe for custom sword
create_craft_spell(
    dbc_dir='C:/wow335/DBFilesClient',
    spell_id=99001,
    name='Stormforged Blade',
    output_item_id=90001,
    reagents=[
        (36916, 12),     # 12x Saronite Bar
        (35623, 4),      # 4x Eternal Earth
        (36860, 2),      # 2x Eternal Fire
        (37663, 1),      # 1x Titanium Bar
    ],
    description='Teaches you how to craft a Stormforged Blade.',
    casting_time_index=51,  # 5 seconds
    spell_icon_id=135,      # Sword icon
)
```

### Important Notes on Spell Field Layout

The field indices used above correspond to the **3.3.3.11685 through 3.3.5.12340** layout from the Spell.dbd definition file. This layout is specific to this build range. Key differences from the earlier 3.0.x builds:

- Fields 11: AttributesExG (added in 3.3.x, field 10 is AttributesExF)
- Fields 12-13: ShapeshiftMask is 2 uint32 values
- Fields 14-15: ShapeshiftExclude is 2 uint32 values
- Field 77-79: EffectBaseDice[3] exists (between DieSides and DicePerLevel)
- Fields 142-158: Name_lang starts at index 142 (after SpellPriority at 141)

If your Spell.dbc was extracted from a different sub-build, the field indices may shift. Always verify by reading a known spell and checking its field values.

---

## Step 3: Link to Profession via SkillLineAbility.dbc

### SkillLineAbility.dbc Field Layout (WotLK 3.3.5a)

The WotLK 3.3.5a SkillLineAbility.dbc (builds 3.0.8.9328 and 3.0.1.8788-3.3.5.12340) has the following layout:

| Field Index | Byte Offset | Field Name | Type | Description |
|---|---|---|---|---|
| 0 | 0 | ID | uint32 | Unique entry ID |
| 1 | 4 | SkillLine | uint32 | FK to SkillLine.dbc (profession ID, e.g. 164=Blacksmithing) |
| 2 | 8 | Spell | uint32 | FK to Spell.dbc (the craft spell ID) |
| 3 | 12 | RaceMask | uint32 | Race restriction bitmask (0=all races) |
| 4 | 16 | ClassMask | uint32 | Class restriction bitmask (0=all classes) |
| 5 | 20 | ExcludeRace | uint32 | Excluded race bitmask (0=none excluded) |
| 6 | 24 | ExcludeClass | uint32 | Excluded class bitmask (0=none excluded) |
| 7 | 28 | MinSkillLineRank | uint32 | Minimum profession skill level to learn/craft |
| 8 | 32 | SupercededBySpell | uint32 | Spell ID that replaces this one at higher rank (0=none) |
| 9 | 36 | AcquireMethod | uint32 | How the recipe is learned (see table) |
| 10 | 40 | TrivialSkillLineRankHigh | uint32 | Skill level where recipe turns gray (no more skill-ups) |
| 11 | 44 | TrivialSkillLineRankLow | uint32 | Skill level where recipe turns yellow (reduced skill-up chance) |
| 12-13 | 48-52 | CharacterPoints[2] | uint32[2] | Character points required (usually 0, 0) |

**Total: 14 fields = 56 bytes per record**

### AcquireMethod Values

| Value | Name | Description |
|---|---|---|
| 0 | SKILL_LINE_ABILITY_LEARNED_ON_GET_PROFESSION | Available as soon as profession is trained at the minimum skill level |
| 1 | SKILL_LINE_ABILITY_LEARNED_ON_SKILL_VALUE | Auto-learned when reaching MinSkillLineRank |
| 2 | SKILL_LINE_ABILITY_LEARNED_ON_SKILL_LEARN | Learned from trainer or recipe item |

### Skill-Up Color Thresholds

The recipe color in the profession window indicates skill-up probability:

| Color | Condition | Skill-Up Chance |
|---|---|---|
| Orange | Skill < MinSkillLineRank (impossible to see) | 100% guaranteed |
| Orange | Skill < TrivialSkillLineRankLow | 100% guaranteed |
| Yellow | TrivialSkillLineRankLow <= Skill < midpoint | High chance |
| Green | midpoint <= Skill < TrivialSkillLineRankHigh | Low chance |
| Gray | Skill >= TrivialSkillLineRankHigh | 0% (no skill-up) |

The "midpoint" is calculated as: `(TrivialSkillLineRankLow + TrivialSkillLineRankHigh) / 2`

### Python Code: Link Spell to Profession

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector

def create_skill_line_ability(
    dbc_dir,
    skill_line_id,
    spell_id,
    min_skill_rank,
    trivial_high,
    trivial_low=None,
    acquire_method=0,
    race_mask=0,
    class_mask=0,
    superceded_by=0,
    sla_id=None,
):
    """
    Create a new SkillLineAbility.dbc record linking a spell to a profession.

    Args:
        dbc_dir: Path to directory containing SkillLineAbility.dbc.
        skill_line_id: SkillLine.dbc ID for the profession
                       (e.g., 164=Blacksmithing, 197=Tailoring).
        spell_id: Spell.dbc ID for the craft spell.
        min_skill_rank: Minimum profession skill to learn/use this recipe.
        trivial_high: Skill level where recipe turns gray (no more skill-ups).
        trivial_low: Skill level where recipe turns yellow. If None,
                     defaults to min_skill_rank + 10.
        acquire_method: How recipe is learned:
                        0=Available on train, 1=Auto at skill level,
                        2=From trainer/recipe.
        race_mask: Race restriction (0=all).
        class_mask: Class restriction (0=all).
        superceded_by: Spell ID of higher-rank version (0=none).
        sla_id: Explicit entry ID (None=auto from max_id+1).

    Returns:
        int: The SkillLineAbility entry ID.
    """
    filepath = os.path.join(dbc_dir, 'SkillLineAbility.dbc')
    dbc = DBCInjector(filepath)

    if sla_id is None:
        sla_id = dbc.get_max_id() + 1

    if trivial_low is None:
        trivial_low = min_skill_rank + 10

    # Build 56-byte record (14 fields)
    buf = bytearray()

    buf += struct.pack('<I', sla_id)          # 0: ID
    buf += struct.pack('<I', skill_line_id)   # 1: SkillLine
    buf += struct.pack('<I', spell_id)        # 2: Spell
    buf += struct.pack('<I', race_mask)       # 3: RaceMask
    buf += struct.pack('<I', class_mask)      # 4: ClassMask
    buf += struct.pack('<I', 0)               # 5: ExcludeRace
    buf += struct.pack('<I', 0)               # 6: ExcludeClass
    buf += struct.pack('<I', min_skill_rank)  # 7: MinSkillLineRank
    buf += struct.pack('<I', superceded_by)   # 8: SupercededBySpell
    buf += struct.pack('<I', acquire_method)  # 9: AcquireMethod
    buf += struct.pack('<I', trivial_high)    # 10: TrivialSkillLineRankHigh
    buf += struct.pack('<I', trivial_low)     # 11: TrivialSkillLineRankLow
    buf += struct.pack('<II', 0, 0)           # 12-13: CharacterPoints[2]

    expected_size = 14 * 4  # 56 bytes
    assert len(buf) == expected_size, (
        "SkillLineAbility record size mismatch: expected {}, got {}".format(
            expected_size, len(buf))
    )

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return sla_id


# Example: Add Blacksmithing recipe
# Requires 440 Blacksmithing, yellow at 450, gray at 460
create_skill_line_ability(
    dbc_dir='C:/wow335/DBFilesClient',
    skill_line_id=164,       # Blacksmithing
    spell_id=99001,          # Our custom craft spell
    min_skill_rank=440,      # Requires 440 skill
    trivial_low=450,         # Turns yellow at 450
    trivial_high=460,        # Turns gray at 460
    acquire_method=0,        # Available when trained at skill level
)
```

### Typical Skill Threshold Patterns

| Recipe Tier | MinSkill | Yellow | Green | Gray | Example |
|---|---|---|---|---|---|
| Beginner (1-75) | 1 | 25 | 37 | 50 | Rough Stone Statue |
| Journeyman (75-150) | 100 | 130 | 145 | 160 | Heavy Grinding Stone |
| Expert (150-225) | 200 | 220 | 235 | 250 | Mithril Filigree |
| Artisan (225-300) | 260 | 280 | 295 | 310 | Thorium Bracers |
| Master (300-375) | 350 | 365 | 377 | 390 | Felsteel Longblade |
| Grand Master (375-450) | 440 | 450 | 455 | 460 | Titansteel Bonecrusher |

---

## Step 4: Create a Recipe Item (Optional)

If you want the recipe to be learned from a physical item (a "Plans:", "Pattern:", "Recipe:", etc. item that drops or is purchased), you need to create an item with a "learn spell" on-use effect.

### Recipe Item Spell Trigger

The recipe item uses spell trigger type 6 (SPELL_TRIGGER_LEARN_SPELL_ID) to teach the craft spell when right-clicked.

However, there is a two-step process:

1. **Recipe Item** has `spellid_1` = a "learn" spell
2. **Learn Spell** uses `SPELL_EFFECT_LEARN_SPELL` (effect 36) targeting the actual craft spell

In practice, for AzerothCore, you can simplify this: set `spellid_1` to the craft spell ID and `spelltrigger_1` to 6 (learn spell). The server will teach the spell directly.

### Python Code: Create Recipe Item

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90900)

gen.add_items([{
    'entry': 90900,
    'name': 'Plans: Stormforged Blade',
    'class': 9,              # Recipe
    'subclass': 4,           # Blacksmithing recipe
    'displayid': 6625,       # Standard plans icon/display
    'quality': 4,            # Epic (rare recipe)
    'inventory_type': 0,     # Non-equippable
    'item_level': 80,
    'required_level': 78,
    'bonding': 1,            # BoP (or 2 for BoE tradeable recipes)
    'stackable': 1,
    'max_count': 1,

    # Skill requirement to use the recipe item
    'required_skill': 164,       # Blacksmithing
    'required_skill_rank': 440,  # Need 440 skill to learn

    # Class restriction (if desired)
    'allowable_class': -1,   # All classes can learn
    'allowable_race': -1,

    # On-use: Learn the craft spell
    'spells': [
        {
            'id': 99001,         # The craft spell ID
            'trigger': 6,        # SPELL_TRIGGER_LEARN_SPELL_ID
            'charges': -1,       # Consumed on use (single-use recipe)
            'cooldown': -1,
            'category': 0,
            'category_cooldown': -1,
        },
    ],

    'description': 'Teaches you how to forge a Stormforged Blade.',
    'buy_price': 500000,     # 50 gold to buy from vendor
    'sell_price': 125000,
}])

gen.write_sql('output/recipe_item.sql')
```

### Recipe Item Subclass Reference

| Subclass | Recipe Type | Profession |
|---|---|---|
| 0 | Book | Generic recipe book |
| 1 | Leatherworking Pattern | Leatherworking |
| 2 | Tailoring Pattern | Tailoring |
| 3 | Engineering Schematic | Engineering |
| 4 | Blacksmithing Plans | Blacksmithing |
| 5 | Cooking Recipe | Cooking |
| 6 | Alchemy Recipe | Alchemy |
| 7 | First Aid Manual | First Aid |
| 8 | Enchanting Formula | Enchanting |
| 9 | Fishing Manual | Fishing |
| 10 | Jewelcrafting Design | Jewelcrafting |
| 11 | Inscription Technique | Inscription |

---

## Step 5: Complete Working Example

This example creates a complete Blacksmithing recipe chain: craft spell, profession linkage, recipe item, and the output item.

```python
"""
Complete example: Blacksmithing recipe for a custom epic 1H sword.

Creates:
1. Craft spell in Spell.dbc (SPELL_EFFECT_CREATE_ITEM)
2. SkillLineAbility.dbc entry linking spell to Blacksmithing
3. Recipe item (Plans: Stormforged Blade)
4. Output item SQL (if not already created)

Prerequisites:
- Output item (entry 90001) must exist in Item.dbc + item_template
  (see add_new_item.md)
- Extracted Spell.dbc and SkillLineAbility.dbc in DBC_DIR
"""
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring
from world_builder.sql_generator import SQLGenerator

# Configuration
DBC_DIR = 'C:/wow335/DBFilesClient'
SQL_OUTPUT = 'output/blacksmithing_recipe.sql'

CRAFT_SPELL_ID = 99001
OUTPUT_ITEM_ID = 90001    # Must already exist (see add_new_item.md)
RECIPE_ITEM_ID = 90900

# Reagent materials (existing Blizzard item IDs)
REAGENTS = [
    (36916, 12),   # 12x Saronite Bar
    (35623, 4),    # 4x Eternal Earth
    (36860, 2),    # 2x Eternal Fire
    (37663, 1),    # 1x Titanium Bar
]

# ================================================================
# Step 1: Create Craft Spell in Spell.dbc
# ================================================================
spell_path = os.path.join(DBC_DIR, 'Spell.dbc')
spell_dbc = DBCInjector(spell_path)

record_size = spell_dbc.record_size
print("Spell.dbc record size: {} bytes ({} fields)".format(
    record_size, record_size // 4))

# Add strings
spell_name_off = spell_dbc.add_string('Stormforged Blade')
spell_desc_off = spell_dbc.add_string(
    'Creates a Stormforged Blade from Saronite, Eternal Earth, '
    'Eternal Fire, and Titanium.'
)

# Build record
spell_buf = bytearray(record_size)

def sp_u32(idx, val):
    struct.pack_into('<I', spell_buf, idx * 4, val)

def sp_i32(idx, val):
    struct.pack_into('<i', spell_buf, idx * 4, val)

def sp_loc(start, off):
    sp_u32(start, off)
    sp_u32(start + 16, 0xFFFFFFFF)

# Identity
sp_u32(0, CRAFT_SPELL_ID)

# Attributes (trade spell, cannot be used in combat)
sp_u32(4, 0x00010010)    # TRADESPELL + IS_ABILITY
sp_u32(6, 0x20000000)    # NOT_IN_COMBAT_LOG

# Cast time: 5 seconds
sp_u32(28, 51)           # CastingTimeIndex = 51 (5000ms)

# Proc
sp_u32(35, 101)

# Duration: instant result
sp_u32(40, 0)

# No mana cost
sp_u32(41, 0)            # PowerType = Mana
sp_u32(42, 0)            # ManaCost = 0

# Self-only range
sp_u32(46, 1)            # RangeIndex = 1

# Reagents
for i, (item_id, count) in enumerate(REAGENTS):
    sp_u32(52 + i, item_id)     # Reagent[i]
    sp_u32(60 + i, count)       # ReagentCount[i]

# No equipped item requirement
sp_i32(68, -1)

# Effect 0: Create Item
sp_u32(71, 24)                  # Effect[0] = SPELL_EFFECT_CREATE_ITEM
sp_u32(74, 1)                  # EffectDieSides[0] = 1
sp_i32(86, 0)                  # EffectBasePoints[0] = 0 (creates 1 item)
sp_u32(92, 1)                  # ImplicitTargetA[0] = CASTER
sp_u32(113, OUTPUT_ITEM_ID)    # EffectItemType[0] = output item

# Icon (use a sword icon)
sp_u32(139, 135)               # SpellIconID

# Text
sp_loc(142, spell_name_off)    # Name_lang
sp_loc(176, spell_desc_off)    # Description_lang

spell_dbc.records.append(bytes(spell_buf))
spell_dbc.write(spell_path)
print("[OK] Spell.dbc: added craft spell {} ('{}')".format(
    CRAFT_SPELL_ID, 'Stormforged Blade'))

# ================================================================
# Step 2: Link to Blacksmithing via SkillLineAbility.dbc
# ================================================================
sla_path = os.path.join(DBC_DIR, 'SkillLineAbility.dbc')
sla_dbc = DBCInjector(sla_path)

sla_id = sla_dbc.get_max_id() + 1

sla_buf = bytearray()
sla_buf += struct.pack('<I', sla_id)       # ID
sla_buf += struct.pack('<I', 164)          # SkillLine = Blacksmithing
sla_buf += struct.pack('<I', CRAFT_SPELL_ID)  # Spell
sla_buf += struct.pack('<I', 0)            # RaceMask (all)
sla_buf += struct.pack('<I', 0)            # ClassMask (all)
sla_buf += struct.pack('<I', 0)            # ExcludeRace
sla_buf += struct.pack('<I', 0)            # ExcludeClass
sla_buf += struct.pack('<I', 440)          # MinSkillLineRank = 440
sla_buf += struct.pack('<I', 0)            # SupercededBySpell
sla_buf += struct.pack('<I', 0)            # AcquireMethod = on train
sla_buf += struct.pack('<I', 460)          # TrivialSkillLineRankHigh (gray)
sla_buf += struct.pack('<I', 450)          # TrivialSkillLineRankLow (yellow)
sla_buf += struct.pack('<II', 0, 0)        # CharacterPoints[2]

assert len(sla_buf) == 56, "Expected 56, got {}".format(len(sla_buf))

sla_dbc.records.append(bytes(sla_buf))
sla_dbc.write(sla_path)
print("[OK] SkillLineAbility.dbc: linked spell {} to Blacksmithing (ID={})".format(
    CRAFT_SPELL_ID, sla_id))

# ================================================================
# Step 3: Generate Recipe Item SQL
# ================================================================
gen = SQLGenerator(start_entry=90900)

gen.add_items([{
    'entry': RECIPE_ITEM_ID,
    'name': 'Plans: Stormforged Blade',
    'class': 9,               # Recipe
    'subclass': 4,            # Blacksmithing Plans
    'displayid': 6625,        # Plans display
    'quality': 4,             # Epic
    'inventory_type': 0,      # Non-equippable
    'item_level': 80,
    'required_level': 78,
    'bonding': 1,             # BoP

    'required_skill': 164,    # Blacksmithing
    'required_skill_rank': 440,

    'spells': [{
        'id': CRAFT_SPELL_ID,
        'trigger': 6,         # Learn Spell
        'charges': -1,
        'cooldown': -1,
        'category': 0,
        'category_cooldown': -1,
    }],

    'description': 'Teaches you how to forge a Stormforged Blade.',
    'buy_price': 500000,
    'sell_price': 125000,
    'stackable': 1,
    'max_count': 1,
}])

os.makedirs(os.path.dirname(SQL_OUTPUT), exist_ok=True)
gen.write_sql(SQL_OUTPUT)
print("[OK] SQL written to: {}".format(SQL_OUTPUT))

print()
print("Recipe summary:")
print("  Craft Spell: {} (Stormforged Blade)".format(CRAFT_SPELL_ID))
print("  Profession: Blacksmithing (440)")
print("  Output Item: {} (Blade of the Stormforged)".format(OUTPUT_ITEM_ID))
print("  Reagents:")
for item_id, count in REAGENTS:
    print("    {}x Item #{}".format(count, item_id))
print("  Recipe Item: {} (Plans: Stormforged Blade)".format(RECIPE_ITEM_ID))
print("  Skill thresholds: Orange <440, Yellow 450, Gray 460")
print()
print("Next steps:")
print("  1. Pack modified Spell.dbc and SkillLineAbility.dbc into patch MPQ")
print("  2. Apply recipe SQL to acore_world database")
print("  3. (Optional) Add recipe item to vendor or loot table")
print("  4. Restart worldserver and clear client cache (Cache/WDB/*)")
print("  5. Test: Learn Blacksmithing 440+, open profession, verify recipe")
```

---

## Common Pitfalls and Troubleshooting

### Problem: Recipe does not appear in profession window

**Cause:** SkillLineAbility.dbc entry is missing, has wrong SkillLine, or wrong Spell ID.

**Fix:**
- Verify `SkillLineAbility.Spell` matches your craft `Spell.dbc.ID` exactly
- Verify `SkillLineAbility.SkillLine` matches the correct profession ID (e.g., 164 for BS)
- Verify `MinSkillLineRank` is <= the player's current skill level
- Ensure the modified SkillLineAbility.dbc is in your client MPQ patch
- Clear the client cache (`Cache/WDB/` folder)

### Problem: Recipe appears but says "Requires [X] (0)" or wrong profession

**Cause:** Wrong SkillLine ID in SkillLineAbility.dbc.

**Fix:**
- Double-check the SkillLine ID against the reference table above
- Common mistake: using the "spell" ID instead of the "skill line" ID

### Problem: Craft succeeds but no item is created

**Cause:** `EffectItemType[0]` in Spell.dbc does not point to a valid item, or `Effect[0]` is not set to 24 (CREATE_ITEM).

**Fix:**
- Verify `EffectItemType[0]` (field index 113) equals the output item's entry ID
- Verify `Effect[0]` (field index 71) is set to 24
- Ensure the output item exists in both `Item.dbc` and `item_template` SQL
- Check that `ImplicitTargetA[0]` is 1 (TARGET_UNIT_CASTER)

### Problem: Reagents are not consumed / wrong reagents required

**Cause:** Reagent fields (52-59) and ReagentCount fields (60-67) are not aligned correctly.

**Fix:**
- `Reagent[i]` and `ReagentCount[i]` must be at matching indices (both at index 0, both at index 1, etc.)
- Ensure reagent item IDs exist in the game database
- Maximum 8 different reagent types per spell

### Problem: Client crashes when opening profession window

**Cause:** Corrupted Spell.dbc entry (wrong record size, string offset out of bounds, or incorrect field count).

**Fix:**
- Verify your spell record is exactly `record_size` bytes (use the value from the loaded DBC)
- Always use `dbc.add_string()` for strings; never construct offsets manually
- Ensure you are not overwriting existing spell records (use a unique ID above existing ranges)

### Problem: Recipe item does not teach the spell

**Cause:** The spell trigger type is wrong, or the spell ID does not match.

**Fix:**
- Recipe item must have `'trigger': 6` (SPELL_TRIGGER_LEARN_SPELL_ID) in the spells list
- The `'id'` in the spell definition must match the craft spell's Spell.dbc ID
- The item must have `required_skill` and `required_skill_rank` set correctly

### Problem: Craft creates wrong quantity

**Cause:** `EffectBasePoints[0]` is set incorrectly. For CREATE_ITEM, the quantity created is `EffectBasePoints + EffectDieSides * random(1, EffectDieSides)`.

**Fix:**
- For creating exactly 1 item: `EffectBasePoints=0`, `EffectDieSides=1`
- For creating exactly N items: `EffectBasePoints=N-1`, `EffectDieSides=1`
- For creating 1-3 random items: `EffectBasePoints=0`, `EffectDieSides=3`

### Problem: Skill does not increase when crafting

**Cause:** Player's skill is already at or above `TrivialSkillLineRankHigh` (gray threshold), or the thresholds are set incorrectly.

**Fix:**
- `TrivialSkillLineRankLow` should be HIGHER than `MinSkillLineRank`
- `TrivialSkillLineRankHigh` should be HIGHER than `TrivialSkillLineRankLow`
- If all three are the same value, the recipe is always gray and never grants skill points

---

## Reference Tables

### Spell Attributes Flags for Crafting

| Flag | Value | Description |
|---|---|---|
| SPELL_ATTR0_IS_ABILITY | 0x00000010 | Spell is treated as an ability |
| SPELL_ATTR0_TRADESPELL | 0x00010000 | Trade/profession spell |
| SPELL_ATTR0_PASSIVE | 0x00000400 | Passive spell (not for crafting) |
| SPELL_ATTR2_NOT_IN_COMBAT_LOG | 0x20000000 | Does not appear in combat log |

### Common Reagent Item IDs (WotLK)

| Item ID | Name | Source |
|---|---|---|
| 36916 | Saronite Bar | Mining/Smelting |
| 37663 | Titanium Bar | Mining/Smelting |
| 36913 | Saronite Ore | Mining |
| 36910 | Titanium Ore | Mining |
| 35623 | Eternal Earth | Drop/Transmute |
| 36860 | Eternal Fire | Drop/Transmute |
| 35627 | Eternal Shadow | Drop/Transmute |
| 35625 | Eternal Life | Herbalism |
| 35622 | Eternal Air | Drop/Transmute |
| 33470 | Frostweave Cloth | Humanoid drops |
| 41594 | Ebonweave | Tailoring cooldown |
| 41595 | Moonshroud | Tailoring cooldown |
| 41593 | Spellweave | Tailoring cooldown |
| 38425 | Heavy Borean Leather | Leatherworking |
| 44128 | Arctic Fur | Skinning (rare) |
| 36783 | Northrend Jewelcrafting gems | Prospecting |

### Spell Effect Types Reference

| Value | Constant | Usage |
|---|---|---|
| 24 | SPELL_EFFECT_CREATE_ITEM | Standard item creation |
| 36 | SPELL_EFFECT_LEARN_SPELL | Teaches another spell |
| 53 | SPELL_EFFECT_ENCHANT_ITEM_PERMANENT | Permanent enchant |
| 54 | SPELL_EFFECT_ENCHANT_ITEM_TEMPORARY | Temporary enchant |
| 95 | SPELL_EFFECT_TRADE_SKILL | Opens tradeskill window |
| 157 | SPELL_EFFECT_CREATE_ITEM_2 | Item with random suffix |

---

## Cross-References

- **[Add New Item](add_new_item.md)** -- Create the output item before creating a recipe for it
- **[Create Item Set](create_item_set.md)** -- If crafted items are part of a set
- **[Modify Loot Tables](modify_loot_tables.md)** -- Add recipe items to boss/chest loot tables
- **pywowlib API Reference:**
  - `world_builder.dbc_injector.DBCInjector` -- Low-level DBC read/write for Spell.dbc and SkillLineAbility.dbc
  - `world_builder.dbc_injector._pack_locstring()` -- WotLK localized string helper
  - `world_builder.sql_generator.SQLGenerator.add_items()` -- Recipe item SQL generation
