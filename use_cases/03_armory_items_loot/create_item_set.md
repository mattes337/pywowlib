# Create Item Set

**Complexity:** Advanced | **Estimated Time:** 45-90 minutes | **Files Modified:** ItemSet.dbc, item_template SQL, optionally Spell.dbc

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

### Python Code: Inject ItemSet.dbc Record

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring

def create_item_set(
    dbc_dir,
    set_id,
    set_name,
    item_ids,
    set_spells=None,
    required_skill=0,
    required_skill_rank=0,
):
    """
    Create a new ItemSet.dbc record for WotLK 3.3.5a.

    Args:
        dbc_dir: Path to directory containing ItemSet.dbc.
        set_id: Unique item set ID.
        set_name: Display name for the set (English).
        item_ids: List of item entry IDs in the set (max 17).
        set_spells: List of dicts with 'spell_id' and 'threshold' keys.
                    Example: [
                        {'spell_id': 70803, 'threshold': 2},
                        {'spell_id': 70804, 'threshold': 4},
                    ]
                    Max 8 set bonus spells.
        required_skill: SkillLine ID required to benefit (0=none).
        required_skill_rank: Minimum skill rank (0=none).

    Returns:
        int: The set_id that was injected.
    """
    filepath = os.path.join(dbc_dir, 'ItemSet.dbc')
    dbc = DBCInjector(filepath)

    if set_spells is None:
        set_spells = []

    # Pad item_ids to exactly 17 entries
    padded_items = list(item_ids)[:17]
    while len(padded_items) < 17:
        padded_items.append(0)

    # Pad set_spells to exactly 8 entries
    padded_spells = list(set_spells)[:8]
    while len(padded_spells) < 8:
        padded_spells.append({'spell_id': 0, 'threshold': 0})

    # Add set name to string block
    name_offset = dbc.add_string(set_name)

    # Build the record
    buf = bytearray()

    # Field 0: ID
    buf += struct.pack('<I', set_id)

    # Fields 1-17: Name_lang (locstring, 17 uint32)
    # enUS at slot 0, mask at slot 16 (within locstring)
    buf += _pack_locstring(name_offset)

    # Fields 18-34: ItemID[17]
    for item_id in padded_items:
        buf += struct.pack('<I', item_id)

    # Fields 35-42: SetSpellID[8]
    for sp in padded_spells:
        buf += struct.pack('<I', sp.get('spell_id', 0))

    # Fields 43-50: SetThreshold[8]
    for sp in padded_spells:
        buf += struct.pack('<I', sp.get('threshold', 0))

    # Field 51: RequiredSkill
    buf += struct.pack('<I', required_skill)

    # Field 52: RequiredSkillRank
    buf += struct.pack('<I', required_skill_rank)

    # Verify size: 53 fields * 4 bytes = 212 bytes
    expected_size = 53 * 4
    assert len(buf) == expected_size, (
        "ItemSet record size mismatch: expected {}, got {}".format(
            expected_size, len(buf))
    )

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return set_id


# Example: Create a 5-piece plate DPS tier set
create_item_set(
    dbc_dir='C:/wow335/DBFilesClient',
    set_id=900,
    set_name='Stormforged Battlegear',
    item_ids=[
        90020,  # Head
        90021,  # Shoulders
        90022,  # Chest
        90023,  # Hands
        90024,  # Legs
    ],
    set_spells=[
        {'spell_id': 70803, 'threshold': 2},  # 2pc bonus
        {'spell_id': 70804, 'threshold': 4},  # 4pc bonus
    ],
)
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

### Creating Custom Set Bonus Spells in Spell.dbc

If you need entirely custom set bonus effects, you must create new Spell.dbc entries. This is advanced and requires understanding the Spell.dbc field layout.

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

#### Python Code: Create a Custom Set Bonus Spell

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring

def create_set_bonus_spell(
    dbc_dir,
    spell_id,
    name,
    description,
    effect_type=6,         # SPELL_EFFECT_APPLY_AURA
    aura_type=13,          # SPELL_AURA_MOD_DAMAGE_PERCENT_DONE
    base_points=9,         # +10% (base_points = actual_value - 1)
    misc_value=127,        # School mask (127 = all schools)
):
    """
    Create a minimal passive set bonus spell in Spell.dbc.

    This creates a spell that applies a passive aura when the set
    bonus condition is met. The spell is flagged as passive so it
    cannot be manually cast.

    WARNING: Spell.dbc has a very large record format (~234 fields).
    This function constructs the full record with zeros for unused
    fields and only populates the critical fields for a passive aura.

    Args:
        dbc_dir: Path to directory containing Spell.dbc.
        spell_id: Unique spell ID.
        name: Spell/bonus name (e.g., "Stormforged 2P Bonus").
        description: Tooltip description (e.g., "Increases damage by $s1%.").
        effect_type: Spell effect type (6=APPLY_AURA for set bonuses).
        aura_type: Aura type to apply.
        base_points: Effect magnitude minus 1 (e.g., 9 for +10%).
        misc_value: Effect misc value (school mask for damage mods).

    Returns:
        int: The spell_id that was injected.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    # Get field count and record size from the loaded DBC
    field_count = dbc.field_count
    record_size = dbc.record_size

    # Add strings
    name_off = dbc.add_string(name)
    desc_off = dbc.add_string(description)

    # Build a zero-filled record and patch specific fields
    buf = bytearray(record_size)

    # We need to know the exact field layout for 3.3.5.
    # Spell.dbc 3.3.3-3.3.5 layout from the .dbd definition:
    # The order of fields is listed in the BUILD 3.3.3.11685-3.3.5.12340 block.
    #
    # Field positions (0-based uint32 index):
    #  0: ID
    #  1: Category
    #  2: DispelType
    #  3: Mechanic
    #  4: Attributes        -- set passive flag here
    #  5: AttributesEx
    #  6: AttributesExB
    #  7: AttributesExC
    #  8: AttributesExD
    #  9: AttributesExE
    # 10: AttributesExF
    # 11: AttributesExG
    # 12-13: ShapeshiftMask[2]
    # 14-15: ShapeshiftExclude[2]
    # 16: Targets
    # 17: TargetCreatureType
    # 18: RequiresSpellFocus
    # 19: FacingCasterFlags
    # 20: CasterAuraState
    # 21: TargetAuraState
    # 22: ExcludeCasterAuraState
    # 23: ExcludeTargetAuraState
    # 24: CasterAuraSpell
    # 25: TargetAuraSpell
    # 26: ExcludeCasterAuraSpell
    # 27: ExcludeTargetAuraSpell
    # 28: CastingTimeIndex  -- 1 = instant
    # 29: RecoveryTime
    # 30: CategoryRecoveryTime
    # 31: InterruptFlags
    # 32: AuraInterruptFlags
    # 33: ChannelInterruptFlags
    # 34: ProcTypeMask
    # 35: ProcChance
    # 36: ProcCharges
    # 37: MaxLevel
    # 38: BaseLevel
    # 39: SpellLevel
    # 40: DurationIndex     -- 21 = infinite
    # 41: PowerType
    # 42: ManaCost
    # 43: ManaCostPerLevel
    # 44: ManaPerSecond
    # 45: ManaPerSecondPerLevel
    # 46: RangeIndex         -- 1 = self
    # 47: Speed (float)
    # 48: ModalNextSpell
    # 49: CumulativeAura
    # 50-51: Totem[2]
    # 52-59: Reagent[8]
    # 60-67: ReagentCount[8]
    # 68: EquippedItemClass
    # 69: EquippedItemSubclass
    # 70: EquippedItemInvTypes
    # 71-73: Effect[3]         -- spell effect types
    # 74-76: EffectDieSides[3]
    # 77-79: EffectBaseDice[3]
    # 80-82: EffectDicePerLevel[3]
    # 83-85: EffectRealPointsPerLevel[3] (float)
    # 86-88: EffectBasePoints[3]
    # 89-91: EffectMechanic[3]
    # 92-94: ImplicitTargetA[3]
    # 95-97: ImplicitTargetB[3]
    # 98-100: EffectRadiusIndex[3]
    # 101-103: EffectAura[3]
    # 104-106: EffectAuraPeriod[3]
    # 107-109: EffectAmplitude[3] (float)
    # 110-112: EffectChainTargets[3]
    # 113-115: EffectItemType[3]
    # 116-118: EffectMiscValue[3]
    # 119-121: EffectMiscValueB[3]
    # 122-124: EffectTriggerSpell[3]
    # 125-127: EffectPointsPerCombo[3] (float)
    # 128-130: EffectSpellClassMaskA[3]
    # 131-133: EffectSpellClassMaskB[3]
    # 134-136: EffectSpellClassMaskC[3]
    # 137-138: SpellVisualID[2]
    # 139: SpellIconID
    # 140: ActiveIconID
    # 141: SpellPriority
    # 142-158: Name_lang        (17 uint32 locstring)
    # 159-175: NameSubtext_lang (17 uint32 locstring)
    # 176-192: Description_lang (17 uint32 locstring)
    # 193-209: AuraDescription_lang (17 uint32 locstring)
    # 210: ManaCostPct
    # 211: StartRecoveryCategory
    # 212: StartRecoveryTime
    # 213: MaxTargetLevel
    # 214: SpellClassSet
    # 215-217: SpellClassMask[3]
    # 218: MaxTargets
    # 219: DefenseType
    # 220: PreventionType
    # 221: StanceBarOrder
    # 222-224: EffectChainAmplitude[3] (float)
    # 225: MinFactionID
    # 226: MinReputation
    # 227: RequiredAuraVision
    # 228-229: RequiredTotemCategoryID[2]
    # 230: RequiredAreasID
    # 231: SchoolMask
    # 232: RuneCostID
    # 233: SpellMissileID

    def set_uint32(field_index, value):
        struct.pack_into('<I', buf, field_index * 4, value)

    def set_int32(field_index, value):
        struct.pack_into('<i', buf, field_index * 4, value)

    def set_float(field_index, value):
        struct.pack_into('<f', buf, field_index * 4, value)

    def set_locstring(start_field, string_offset):
        # 17 uint32: slot 0 = enUS, slot 16 = mask
        set_uint32(start_field, string_offset)
        set_uint32(start_field + 16, 0xFFFFFFFF)

    # Core fields
    set_uint32(0, spell_id)          # ID
    set_uint32(4, 0x00000480)        # Attributes: PASSIVE(0x400) + NOT_CASTABLE(0x80)
    set_uint32(28, 1)                # CastingTimeIndex = 1 (instant)
    set_uint32(35, 101)              # ProcChance (101 = always, for passive)
    set_uint32(40, 21)               # DurationIndex = 21 (infinite)
    set_uint32(46, 1)                # RangeIndex = 1 (self only)

    # EquippedItemClass = -1 (no item requirement)
    set_int32(68, -1)

    # Effect slot 0
    set_uint32(71, effect_type)      # Effect[0] = 6 (APPLY_AURA)
    set_int32(86, base_points)       # EffectBasePoints[0]
    set_uint32(92, 1)                # ImplicitTargetA[0] = 1 (TARGET_UNIT_CASTER)
    set_uint32(101, aura_type)       # EffectAura[0]
    set_int32(116, misc_value)       # EffectMiscValue[0]

    # Visual (use a generic icon)
    set_uint32(139, 1)               # SpellIconID (generic)

    # Name and Description locstrings
    set_locstring(142, name_off)     # Name_lang
    set_locstring(176, desc_off)     # Description_lang

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return spell_id
```

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

This example creates a complete 5-piece plate DPS set with 2-piece and 4-piece bonuses.

```python
"""
Complete example: Create a 5-piece plate DPS item set for WotLK 3.3.5a.

Creates:
1. ItemSet.dbc entry with set name, items, and bonus spells
2. item_template SQL for all 5 set pieces with itemset linkage
3. (Optional) Custom set bonus spells in Spell.dbc

For this example we reuse existing Blizzard spell IDs for simplicity.
"""
import struct
import os
from world_builder.dbc_injector import DBCInjector, _pack_locstring
from world_builder.sql_generator import SQLGenerator

# Configuration
DBC_DIR = 'C:/wow335/DBFilesClient'
SQL_OUTPUT = 'output/stormforged_set.sql'

SET_ID = 900
SET_NAME = 'Stormforged Battlegear'
ITEM_IDS = [90020, 90021, 90022, 90023, 90024]

# Reuse existing Blizzard spell IDs for set bonuses
# (alternatively, create custom spells -- see Step 5)
SPELL_2PC = 70803   # Example: +6% melee haste
SPELL_4PC = 70804   # Example: +10% Bloodthirst/Mortal Strike damage

# ----------------------------------------------------------------
# Step 1: Create ItemSet.dbc entry
# ----------------------------------------------------------------
itemset_path = os.path.join(DBC_DIR, 'ItemSet.dbc')
dbc = DBCInjector(itemset_path)

name_offset = dbc.add_string(SET_NAME)

buf = bytearray()

# Field 0: ID
buf += struct.pack('<I', SET_ID)

# Fields 1-17: Name_lang (17 uint32)
buf += _pack_locstring(name_offset)

# Fields 18-34: ItemID[17] -- our 5 items + 12 zeros
for item_id in ITEM_IDS:
    buf += struct.pack('<I', item_id)
for _ in range(17 - len(ITEM_IDS)):
    buf += struct.pack('<I', 0)

# Fields 35-42: SetSpellID[8]
buf += struct.pack('<I', SPELL_2PC)    # Slot 0: 2-piece bonus
buf += struct.pack('<I', SPELL_4PC)    # Slot 1: 4-piece bonus
for _ in range(6):                     # Remaining 6 slots empty
    buf += struct.pack('<I', 0)

# Fields 43-50: SetThreshold[8]
buf += struct.pack('<I', 2)            # Slot 0: need 2 pieces
buf += struct.pack('<I', 4)            # Slot 1: need 4 pieces
for _ in range(6):
    buf += struct.pack('<I', 0)

# Fields 51-52: RequiredSkill, RequiredSkillRank
buf += struct.pack('<II', 0, 0)

assert len(buf) == 212, "Expected 212, got {}".format(len(buf))

dbc.records.append(bytes(buf))
dbc.write(itemset_path)
print("[OK] ItemSet.dbc: created set '{}' (ID={})".format(SET_NAME, SET_ID))

# ----------------------------------------------------------------
# Step 2: Generate item_template SQL for all set pieces
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
print("  1. Pack modified ItemSet.dbc into patch MPQ")
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
  - `world_builder.dbc_injector.DBCInjector` -- Low-level DBC read/write
  - `world_builder.dbc_injector._pack_locstring()` -- WotLK localized string helper
  - `world_builder.sql_generator.SQLGenerator.add_items()` -- Item SQL generation with `itemset` support
