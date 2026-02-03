# Modify Loot Tables

**Complexity:** Intermediate | **Estimated Time:** 15-45 minutes | **Files Modified:** Server-side SQL only (no DBC changes)

## Overview

Loot tables in WoW WotLK 3.3.5a determine what items drop when a creature is killed, a chest is opened, a player is pickpocketed, or a corpse is skinned. The loot system is entirely server-side -- it lives in the AzerothCore `acore_world` database and requires no client-side DBC modifications.

The loot system uses several interconnected tables:

| Table | Purpose | Entry Source |
|---|---|---|
| `creature_loot_template` | Items dropped by creatures on death | `creature_template.lootid` |
| `gameobject_loot_template` | Items contained in chests, crates, fishing pools | `gameobject_template.Data1` (for type=3 chests) |
| `reference_loot_template` | Shared loot pools referenced by other tables | Referenced via negative Item values or Reference column |
| `pickpocketing_loot_template` | Items from pickpocketing humanoid NPCs | `creature_template.pickpocketloot` |
| `skinning_loot_template` | Items from skinning/herbalism/mining corpses | `creature_template.skinloot` |

pywowlib's `SQLGenerator` provides the `add_loot()` and `add_creature_loot()` convenience methods to generate all of these SQL statements.

## Prerequisites

- Python 3.7 or later
- pywowlib repository with `world_builder/` on Python path
- AzerothCore 3.3.5a `acore_world` database
- Custom items already created (see [Add New Item](add_new_item.md))
- Knowledge of creature entry IDs or gameobject entry IDs you want to modify

## Table of Contents

1. [Step 1: Understand the Loot Table Schema](#step-1-understand-the-loot-table-schema)
2. [Step 2: creature_loot_template](#step-2-creature_loot_template)
3. [Step 3: gameobject_loot_template](#step-3-gameobject_loot_template)
4. [Step 4: reference_loot_template](#step-4-reference_loot_template)
5. [Step 5: Loot Conditions](#step-5-loot-conditions)
6. [Step 6: Using SQLGenerator for Loot](#step-6-using-sqlgenerator-for-loot)
7. [Step 7: Complete Working Examples](#step-7-complete-working-examples)
8. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
9. [Cross-References](#cross-references)

---

## Step 1: Understand the Loot Table Schema

All loot tables (`creature_loot_template`, `gameobject_loot_template`, `reference_loot_template`, `pickpocketing_loot_template`, `skinning_loot_template`) share the same column structure:

### Column Reference

| Column | Type | Default | Description |
|---|---|---|---|
| `Entry` | int | -- | Loot table entry ID. For creatures, this is `creature_template.lootid`. For gameobjects, this is `gameobject_template.Data1` |
| `Item` | int | -- | Item entry ID to drop. If `Reference > 0`, this is the sub-group ID within the reference table |
| `Reference` | int | 0 | If > 0, this row references `reference_loot_template` with Entry=Reference. The actual item comes from the reference table, not from this row's Item value |
| `Chance` | float | 100.0 | Drop chance percentage (0-100). If 0 within a group, chance is calculated as `100 / group_item_count` |
| `QuestRequired` | int | 0 | If 1, item only drops for players on the relevant quest. If 0, drops for everyone |
| `LootMode` | int | 1 | Bitmask controlling which loot modes this item appears in: 1=Normal, 2=Heroic (10-man), 4=Heroic (25-man) |
| `GroupId` | int | 0 | Loot group ID. Items in the same group compete with each other (only one drops per group). GroupId=0 means the item drops independently |
| `MinCount` | int | 1 | Minimum quantity dropped |
| `MaxCount` | int | 1 | Maximum quantity dropped (actual count is random between Min and Max) |
| `Comment` | string | '' | Documentation comment (not used by the server) |

### How Loot Groups Work

The GroupId system is the most important concept in loot tables:

**GroupId = 0 (Independent / Non-Grouped):**
Each item with `GroupId=0` is rolled independently. If an item has 25% chance and GroupId=0, it has a 25% chance to drop regardless of what other items drop. Multiple GroupId=0 items can drop simultaneously from the same kill.

**GroupId > 0 (Grouped / Mutually Exclusive):**
Items in the same group compete with each other. Exactly ONE item from the group will drop (or none, if all chances fail). This is used for "one of these items drops" scenarios like boss loot tables where a boss drops one of several possible epics.

### Chance Calculation Within Groups

For grouped items (GroupId > 0), the Chance column works differently:

- If **all items in the group have Chance > 0**: Each item's chance is its probability of being selected. The chances should sum to roughly 100. If they sum to less than 100, the remaining percentage results in no item from that group.
- If **any item in the group has Chance = 0**: All Chance=0 items split the remaining probability equally. For example, if one item has Chance=50 and two items have Chance=0, the two Chance=0 items each get (100-50)/2 = 25%.

### Loot Flow Diagram

```
Creature killed
    |
    v
creature_template.lootid = 12345
    |
    v
creature_loot_template WHERE Entry = 12345
    |
    +-- GroupId=0 items: each rolled independently
    |     +-- Item=50001, Chance=5.0   --> 5% chance to drop
    |     +-- Item=50002, Chance=15.0  --> 15% chance to drop
    |
    +-- GroupId=1 items: one winner from this group
    |     +-- Item=60001, Chance=0     --> equal share
    |     +-- Item=60002, Chance=0     --> equal share
    |     +-- Item=60003, Chance=0     --> equal share
    |     (each gets 33.3% chance, exactly 1 drops)
    |
    +-- Reference rows: delegate to reference_loot_template
          +-- Reference=34001, Item=1  --> pick from ref table 34001
```

---

## Step 2: creature_loot_template

### Linking Creatures to Loot Tables

A creature's loot table is determined by the `lootid` column in `creature_template`. By default, `lootid` equals the creature's entry ID, but it can be set to any value to share loot tables between creatures.

```sql
-- Set creature 90100 to use loot table 90100
UPDATE `creature_template` SET `lootid` = 90100 WHERE `entry` = 90100;
```

### Basic Example: Single Item Drop

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90100, map_id=1, zone_id=9001)

# Add a creature with lootid set
gen.add_creatures([{
    'entry': 90100,
    'name': 'Stormforged Sentinel',
    'minlevel': 80,
    'maxlevel': 80,
    'lootid': 90100,    # Points to creature_loot_template.Entry
}])

# Add loot: 15% chance to drop custom sword
gen.add_loot('creature_loot_template', 90100, [
    {
        'item': 90001,       # Item entry ID
        'chance': 15.0,      # 15% drop chance
        'quest_required': 0, # Drops for everyone
        'loot_mode': 1,      # Normal mode
        'group_id': 0,       # Independent drop
        'min': 1,            # Drops 1
        'max': 1,
        'comment': 'Blade of the Stormforged',
    },
])

gen.write_sql('output/sentinel_loot.sql')
```

### Multi-Item Loot Table with Groups

```python
gen = SQLGenerator(start_entry=90200)

# Boss creature
gen.add_creatures([{
    'entry': 90200,
    'name': 'Warlord Thrak',
    'minlevel': 82,
    'maxlevel': 82,
    'rank': 3,              # World boss
    'lootid': 90200,
    'health_modifier': 50.0,
    'damage_modifier': 15.0,
}])

# Complex loot table
gen.add_loot('creature_loot_template', 90200, [
    # Group 0: Independent drops (each rolled separately)
    {
        'item': 90001,       # Custom sword
        'chance': 20.0,
        'group_id': 0,
        'min': 1, 'max': 1,
        'comment': 'Blade of the Stormforged (20%)',
    },
    {
        'item': 90002,       # Custom robe
        'chance': 20.0,
        'group_id': 0,
        'min': 1, 'max': 1,
        'comment': 'Robes of the Arcane Tempest (20%)',
    },

    # Group 1: One token drops (mutually exclusive)
    {
        'item': 90020,       # Set piece: helmet
        'chance': 0,         # Equal chance (auto-calculated)
        'group_id': 1,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Helmet (1 of 5)',
    },
    {
        'item': 90021,       # Set piece: pauldrons
        'chance': 0,
        'group_id': 1,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Pauldrons (1 of 5)',
    },
    {
        'item': 90022,       # Set piece: breastplate
        'chance': 0,
        'group_id': 1,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Breastplate (1 of 5)',
    },
    {
        'item': 90023,       # Set piece: gauntlets
        'chance': 0,
        'group_id': 1,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Gauntlets (1 of 5)',
    },
    {
        'item': 90024,       # Set piece: legplates
        'chance': 0,
        'group_id': 1,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Legplates (1 of 5)',
    },

    # Group 2: Guaranteed gold/reagent drop
    {
        'item': 29434,       # Badge of Justice (or equivalent currency)
        'chance': 100.0,
        'group_id': 0,       # Independent, guaranteed
        'min': 2, 'max': 4,
        'comment': 'Guaranteed 2-4 badges',
    },
])

gen.write_sql('output/warlord_loot.sql')
```

### Using add_creature_loot() for Bulk Generation

The `add_creature_loot()` method accepts a dictionary mapping creature entries to their loot lists:

```python
gen = SQLGenerator(start_entry=90300)

# Define creatures
gen.add_creatures([
    {'entry': 90300, 'name': 'Stormforged Grunt', 'minlevel': 78, 'maxlevel': 80, 'lootid': 90300},
    {'entry': 90301, 'name': 'Stormforged Mage', 'minlevel': 78, 'maxlevel': 80, 'lootid': 90301},
    {'entry': 90302, 'name': 'Stormforged Captain', 'minlevel': 80, 'maxlevel': 80, 'lootid': 90302},
])

# Bulk loot assignment
gen.add_creature_loot({
    90300: [  # Grunt drops
        {'item': 90003, 'chance': 5.0, 'comment': 'Elixir of Temporal Displacement'},
        {'item': 33470, 'chance': 35.0, 'min': 1, 'max': 3, 'comment': 'Frostweave Cloth'},
    ],
    90301: [  # Mage drops
        {'item': 90003, 'chance': 10.0, 'comment': 'Elixir of Temporal Displacement'},
        {'item': 33470, 'chance': 45.0, 'min': 2, 'max': 4, 'comment': 'Frostweave Cloth'},
        {'item': 90002, 'chance': 2.0, 'comment': 'Robes of the Arcane Tempest (rare)'},
    ],
    90302: [  # Captain drops
        {'item': 90001, 'chance': 8.0, 'comment': 'Blade of the Stormforged'},
        {'item': 90003, 'chance': 15.0, 'min': 1, 'max': 2, 'comment': 'Elixir x1-2'},
        {'item': 33470, 'chance': 60.0, 'min': 3, 'max': 6, 'comment': 'Frostweave Cloth x3-6'},
    ],
})

gen.write_sql('output/zone_loot.sql')
```

---

## Step 3: gameobject_loot_template

Gameobject loot works identically to creature loot but is linked through `gameobject_template` instead of `creature_template`.

### Chest Gameobject Setup

For chests (gameobject type 3), the loot table entry is stored in `Data1`:

| Data Field | Purpose |
|---|---|
| `Data0` | Lock ID (lockpicking/key requirement) |
| `Data1` | Loot table entry ID (FK to `gameobject_loot_template.Entry`) |
| `Data2` | Restock time in seconds (0=no restock) |
| `Data3` | Consumable flag (1=despawn after looting) |
| `Data4` | Minimum items to loot from table |
| `Data5` | Maximum items to loot from table |
| `Data6` | Loot event condition |

### Python Code: Chest with Custom Loot

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90400)

# Create a chest gameobject template
gen.add_gameobject_templates([{
    'entry': 90400,
    'type': 3,              # GAMEOBJECT_TYPE_CHEST
    'display_id': 259,      # Standard treasure chest display
    'name': 'Stormforged Cache',
    'size': 1.5,
    'data0': 0,             # No lock (anyone can open)
    'data1': 90400,         # Loot table entry (matches gameobject_loot_template)
    'data2': 300,           # Respawn after 300 seconds (5 min)
    'data3': 1,             # Consumable (despawns when looted)
    'data4': 2,             # Min 2 items from loot table
    'data5': 4,             # Max 4 items from loot table
}])

# Spawn the chest
gen.add_gameobject_spawns([{
    'entry': 90400,
    'position': (-8400.0, 1500.0, 155.0, 2.35),
    'spawntimesecs': 300,
}])

# Define loot for the chest
gen.add_loot('gameobject_loot_template', 90400, [
    {
        'item': 90001,
        'chance': 10.0,
        'group_id': 0,
        'comment': 'Blade of the Stormforged',
    },
    {
        'item': 90003,
        'chance': 40.0,
        'group_id': 0,
        'min': 1, 'max': 3,
        'comment': 'Elixir of Temporal Displacement x1-3',
    },
    {
        'item': 33470,
        'chance': 70.0,
        'group_id': 0,
        'min': 4, 'max': 8,
        'comment': 'Frostweave Cloth x4-8',
    },
    {
        'item': 36693,       # Frost Lotus
        'chance': 15.0,
        'group_id': 0,
        'min': 1, 'max': 2,
        'comment': 'Frost Lotus x1-2',
    },
])

gen.write_sql('output/stormforged_cache.sql')
```

### Locked Chest Example

```python
# Chest that requires lockpicking or a key
gen.add_gameobject_templates([{
    'entry': 90401,
    'type': 3,
    'display_id': 7149,      # Heavy chest display
    'name': 'Sealed Stormforged Reliquary',
    'size': 1.0,
    'data0': 1665,           # Lock ID -- requires Lockpicking 400+ or specific key
    'data1': 90401,
    'data3': 1,
    'data4': 3,
    'data5': 5,
}])
```

---

## Step 4: reference_loot_template

Reference loot templates are shared loot pools that can be included in multiple creature or gameobject loot tables. This avoids duplicating the same loot entries across many creatures.

### How References Work

When a loot table row has `Reference > 0`, the server does NOT drop the item specified in the `Item` column. Instead, it looks up `reference_loot_template WHERE Entry = [Reference value]` and picks items from that reference table.

The `Item` column in the referencing row acts as a sub-ID within the reference table (but in practice, it is typically set to the same value as Reference for clarity, or to 0/1).

### Creating a Reference Loot Table

```python
gen = SQLGenerator(start_entry=90500)

# Define a shared green-quality item pool (reference table)
# Entry 34001 is our reference table ID
gen.add_loot('reference_loot_template', 34001, [
    # These are the actual items in the shared pool
    {
        'item': 90050,
        'chance': 0,         # Equal chance within group
        'group_id': 1,
        'comment': 'Stormforged Bracer',
    },
    {
        'item': 90051,
        'chance': 0,
        'group_id': 1,
        'comment': 'Stormforged Belt',
    },
    {
        'item': 90052,
        'chance': 0,
        'group_id': 1,
        'comment': 'Stormforged Ring',
    },
    {
        'item': 90053,
        'chance': 0,
        'group_id': 1,
        'comment': 'Stormforged Cloak',
    },
])

# Now reference this pool from multiple creatures
# Creature 90300: 15% chance to roll on the shared pool
gen.add_loot('creature_loot_template', 90300, [
    {
        'item': 34001,           # Sub-ID (matches reference Entry for clarity)
        'reference': 34001,      # Points to reference_loot_template.Entry = 34001
        'chance': 15.0,          # 15% chance to roll on the reference table
        'group_id': 0,
        'min': 1, 'max': 1,
        'comment': 'Reference: shared green item pool (15%)',
    },
    # Other direct drops...
    {
        'item': 33470,
        'chance': 40.0,
        'group_id': 0,
        'min': 1, 'max': 3,
        'comment': 'Frostweave Cloth',
    },
])

# Creature 90301: 20% chance to roll on the same shared pool
gen.add_loot('creature_loot_template', 90301, [
    {
        'item': 34001,
        'reference': 34001,
        'chance': 20.0,
        'group_id': 0,
        'min': 1, 'max': 1,
        'comment': 'Reference: shared green item pool (20%)',
    },
])

gen.write_sql('output/reference_loot.sql')
```

### Benefits of Reference Tables

1. **Maintenance**: Change the pool once, all creatures using the reference get the update
2. **Consistency**: Ensures the same items drop across a zone
3. **Organization**: Keeps individual creature loot tables clean

### Nested References

Reference tables can themselves reference other reference tables, though deep nesting is discouraged for performance and clarity:

```
creature_loot_template (Entry=90300)
  --> Reference=34001 (shared green pool)
      --> reference_loot_template (Entry=34001)
          --> Item=90050, Item=90051, Item=90052 (actual items)
```

---

## Step 5: Loot Conditions

Loot conditions allow you to add requirements beyond simple chance rolls. Conditions are stored in the `conditions` table and linked to loot entries.

### Conditions Table Schema

```sql
CREATE TABLE `conditions` (
    `SourceTypeOrReferenceId` int NOT NULL,  -- 1 for creature_loot, 4 for gameobject_loot
    `SourceGroup` int NOT NULL,              -- Loot Entry ID
    `SourceEntry` int NOT NULL,              -- Item ID within the loot table
    `SourceId` int NOT NULL DEFAULT 0,
    `ElseGroup` int NOT NULL DEFAULT 0,
    `ConditionTypeOrReference` int NOT NULL, -- Condition type
    `ConditionTarget` int NOT NULL DEFAULT 0,
    `ConditionValue1` int NOT NULL DEFAULT 0,
    `ConditionValue2` int NOT NULL DEFAULT 0,
    `ConditionValue3` int NOT NULL DEFAULT 0,
    `NegativeCondition` int NOT NULL DEFAULT 0,
    `ErrorType` int NOT NULL DEFAULT 0,
    `ErrorTextId` int NOT NULL DEFAULT 0,
    `ScriptName` varchar(64) DEFAULT '',
    `Comment` varchar(255) DEFAULT ''
);
```

### Common Condition Types

| ConditionTypeOrReference | Name | Value1 | Value2 | Description |
|---|---|---|---|---|
| 5 | CONDITION_QUESTREWARDED | Quest ID | 0 | Player must have completed quest |
| 8 | CONDITION_QUESTTAKEN | Quest ID | 0 | Player must be on quest |
| 15 | CONDITION_CLASS | Class mask | 0 | Player must be specific class |
| 16 | CONDITION_RACE | Race mask | 0 | Player must be specific race |
| 47 | CONDITION_HAS_ITEM | Item ID | Count | Player must have item |

### SourceTypeOrReferenceId Values

| Value | Source | SourceGroup means | SourceEntry means |
|---|---|---|---|
| 1 | creature_loot_template | Loot Entry ID | Item ID |
| 4 | gameobject_loot_template | Loot Entry ID | Item ID |
| 7 | skinning_loot_template | Loot Entry ID | Item ID |
| 8 | pickpocketing_loot_template | Loot Entry ID | Item ID |
| 10 | reference_loot_template | Loot Entry ID | Item ID |

### Example: Quest-Required Drop

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90600)

# Item only drops when player is on quest 90600
gen.add_loot('creature_loot_template', 90300, [
    {
        'item': 90060,       # Quest item
        'chance': 40.0,
        'quest_required': 1, # Only drops for questers
        'group_id': 0,
        'min': 1, 'max': 1,
        'comment': 'Stormforged Core (quest drop)',
    },
])

# You would also need to INSERT the conditions row manually or via
# the SmartAI/conditions builder. The SQL looks like:
#
# INSERT INTO `conditions` (
#     `SourceTypeOrReferenceId`, `SourceGroup`, `SourceEntry`,
#     `ConditionTypeOrReference`, `ConditionValue1`, `Comment`
# ) VALUES
# (1, 90300, 90060, 8, 90600, 'Quest: Stormforged Core - requires quest 90600');
```

---

## Step 6: Using SQLGenerator for Loot

### API Reference

pywowlib provides three loot-related methods on `SQLGenerator`:

#### `add_loot(table, loot_entry, loot_items)`

Low-level method that generates SQL for any loot table.

```python
gen.add_loot(
    table='creature_loot_template',  # or gameobject_loot_template, etc.
    loot_entry=90100,                # Entry column value
    loot_items=[                     # List of loot item dicts
        {
            'item': 90001,           # Item entry ID
            'reference': 0,         # 0 = direct item, >0 = reference table
            'chance': 15.0,         # Drop chance %
            'quest_required': 0,    # 0=everyone, 1=questers only
            'loot_mode': 1,         # 1=Normal mode
            'group_id': 0,          # 0=independent, >0=grouped
            'min': 1,               # Min quantity
            'max': 1,               # Max quantity
            'comment': 'Description',
        },
    ]
)
```

#### `add_creature_loot(loot_map)`

Convenience method for adding loot to multiple creatures at once.

```python
gen.add_creature_loot({
    90100: [  # creature entry -> loot items
        {'item': 90001, 'chance': 15.0, 'comment': 'Sword'},
        {'item': 33470, 'chance': 40.0, 'min': 1, 'max': 3, 'comment': 'Cloth'},
    ],
    90101: [
        {'item': 90002, 'chance': 10.0, 'comment': 'Robe'},
    ],
})
```

#### Supported Loot Table Names

| Table Name String | Target Table |
|---|---|
| `'creature_loot_template'` | Creature death drops |
| `'gameobject_loot_template'` | Chest/container contents |
| `'reference_loot_template'` | Shared reference pools |
| `'pickpocketing_loot_template'` | Pickpocket results |
| `'skinning_loot_template'` | Skinning/mining/herbalism results |

### Default Values

When keys are omitted from the loot item dict, the following defaults apply:

| Key | Default | Notes |
|---|---|---|
| `item` | 0 | Must be set explicitly |
| `reference` | 0 | 0 = direct item drop |
| `chance` | 100.0 | 100% = guaranteed |
| `quest_required` | 0 | 0 = drops for all |
| `loot_mode` | 1 | 1 = normal mode |
| `group_id` | 0 | 0 = independent |
| `min` | 1 | Minimum 1 |
| `max` | 1 | Maximum 1 |
| `comment` | '' | Empty comment |

---

## Step 7: Complete Working Examples

### Example 1: Full Zone Loot System

This example sets up a complete loot system for a custom zone with trash mobs, elites, and a boss.

```python
"""
Complete example: Zone-wide loot system for Stormforged Citadel.

Creates:
- Shared reference loot pools (green items, cloth, reagents)
- Trash mob loot tables
- Elite mob loot tables
- Boss loot table with grouped epic drops
"""
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90700, map_id=1, zone_id=9001)

# ----------------------------------------------------------------
# Shared Reference Pools
# ----------------------------------------------------------------

# Pool 34010: Zone green items (one random piece drops)
gen.add_loot('reference_loot_template', 34010, [
    {'item': 90050, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Bracer'},
    {'item': 90051, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Belt'},
    {'item': 90052, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Ring'},
    {'item': 90053, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Cloak'},
    {'item': 90054, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Boots'},
    {'item': 90055, 'chance': 0, 'group_id': 1, 'comment': 'Stormforged Gloves'},
])

# Pool 34011: Common reagent drops
gen.add_loot('reference_loot_template', 34011, [
    {'item': 33470, 'chance': 60.0, 'group_id': 0, 'min': 1, 'max': 3,
     'comment': 'Frostweave Cloth'},
    {'item': 36693, 'chance': 5.0, 'group_id': 0, 'min': 1, 'max': 1,
     'comment': 'Frost Lotus'},
    {'item': 36783, 'chance': 15.0, 'group_id': 0, 'min': 1, 'max': 2,
     'comment': 'Northrend common gem'},
])

# ----------------------------------------------------------------
# Trash Mob Creatures
# ----------------------------------------------------------------

# Define trash mobs
gen.add_creatures([
    {'entry': 90700, 'name': 'Stormforged Grunt', 'minlevel': 78, 'maxlevel': 80,
     'lootid': 90700, 'type': 7, 'faction': 16},
    {'entry': 90701, 'name': 'Stormforged Invoker', 'minlevel': 79, 'maxlevel': 80,
     'lootid': 90701, 'type': 7, 'faction': 16},
    {'entry': 90702, 'name': 'Stormforged Berserker', 'minlevel': 80, 'maxlevel': 80,
     'lootid': 90702, 'type': 7, 'faction': 16,
     'rank': 1, 'health_modifier': 3.0},  # Elite
])

# Trash mob loot: reference to shared pools + direct drops
gen.add_creature_loot({
    90700: [
        # 10% chance to get a green item from the shared pool
        {'item': 34010, 'reference': 34010, 'chance': 10.0,
         'comment': 'Ref: zone green pool'},
        # Direct cloth/reagent drops
        {'item': 33470, 'chance': 35.0, 'min': 1, 'max': 2,
         'comment': 'Frostweave Cloth x1-2'},
    ],
    90701: [
        {'item': 34010, 'reference': 34010, 'chance': 12.0,
         'comment': 'Ref: zone green pool'},
        {'item': 33470, 'chance': 40.0, 'min': 1, 'max': 3,
         'comment': 'Frostweave Cloth x1-3'},
        {'item': 90003, 'chance': 3.0,
         'comment': 'Elixir of Temporal Displacement'},
    ],
    90702: [
        # Elites have better drop rates
        {'item': 34010, 'reference': 34010, 'chance': 25.0,
         'comment': 'Ref: zone green pool (elite rate)'},
        {'item': 33470, 'chance': 55.0, 'min': 2, 'max': 4,
         'comment': 'Frostweave Cloth x2-4'},
        {'item': 90003, 'chance': 8.0, 'min': 1, 'max': 2,
         'comment': 'Elixir x1-2'},
    ],
})

# ----------------------------------------------------------------
# Boss Creature
# ----------------------------------------------------------------

gen.add_creatures([{
    'entry': 90710,
    'name': 'Overlord Volthar',
    'minlevel': 82,
    'maxlevel': 82,
    'rank': 3,                    # World Boss
    'lootid': 90710,
    'type': 7,
    'faction': 16,
    'health_modifier': 80.0,
    'damage_modifier': 20.0,
    'mechanic_immune_mask': 0x7FFFFFFF,  # Immune to all mechanics
}])

# Boss loot table
gen.add_loot('creature_loot_template', 90710, [
    # Group 1: One epic weapon drops (mutually exclusive)
    {'item': 90001, 'chance': 0, 'group_id': 1,
     'comment': 'Blade of the Stormforged (1 of 3 weapons)'},
    {'item': 90010, 'chance': 0, 'group_id': 1,
     'comment': 'Worldbreaker Maul (1 of 3 weapons)'},
    {'item': 90080, 'chance': 0, 'group_id': 1,
     'comment': 'Stormforged Staff (1 of 3 weapons)'},

    # Group 2: One set piece drops (mutually exclusive)
    {'item': 90020, 'chance': 0, 'group_id': 2,
     'comment': 'Stormforged Helmet'},
    {'item': 90021, 'chance': 0, 'group_id': 2,
     'comment': 'Stormforged Pauldrons'},
    {'item': 90022, 'chance': 0, 'group_id': 2,
     'comment': 'Stormforged Breastplate'},
    {'item': 90023, 'chance': 0, 'group_id': 2,
     'comment': 'Stormforged Gauntlets'},
    {'item': 90024, 'chance': 0, 'group_id': 2,
     'comment': 'Stormforged Legplates'},

    # Group 0: Independent drops (each rolled separately)
    {'item': 90002, 'chance': 30.0, 'group_id': 0,
     'comment': 'Robes of the Arcane Tempest (30%)'},
    {'item': 90003, 'chance': 100.0, 'group_id': 0, 'min': 3, 'max': 5,
     'comment': 'Guaranteed: Elixir x3-5'},

    # Gold drop (using Blizzard's gold item mechanics via mingold/maxgold
    # on creature_template is preferred, but can also be done via loot)
])

gen.write_sql('output/zone_loot_system.sql')

print("[OK] Zone loot system generated")
print("  Reference pools: 34010, 34011")
print("  Trash mobs: 90700-90702")
print("  Boss: 90710")
```

### Example 2: Pickpocketing and Skinning Loot

```python
gen = SQLGenerator(start_entry=90800)

# Humanoid creature with pickpocket and skin loot
gen.add_creatures([{
    'entry': 90800,
    'name': 'Stormforged Sentry',
    'minlevel': 79,
    'maxlevel': 80,
    'type': 7,                # Humanoid (pickpocketable)
    'lootid': 90800,
    'pickpocketloot': 90800,  # FK to pickpocketing_loot_template
    'skinloot': 90800,        # FK to skinning_loot_template (engineering salvage)
}])

# Death loot
gen.add_loot('creature_loot_template', 90800, [
    {'item': 33470, 'chance': 40.0, 'min': 1, 'max': 2, 'comment': 'Cloth'},
])

# Pickpocket loot (rogues only, via pickpocket ability)
gen.add_loot('pickpocketing_loot_template', 90800, [
    {'item': 43575, 'chance': 100.0, 'min': 20, 'max': 80,
     'comment': 'Junk: vendor copper'},
    {'item': 90003, 'chance': 8.0,
     'comment': 'Stolen elixir'},
])

# Skinning loot (if creature has CREATURE_FLAG_EXTRA_ENGINEERING_MINE_LOOT)
gen.add_loot('skinning_loot_template', 90800, [
    {'item': 33568, 'chance': 80.0, 'min': 1, 'max': 3,
     'comment': 'Borean Leather'},
    {'item': 38557, 'chance': 20.0, 'min': 1, 'max': 1,
     'comment': 'Heavy Borean Leather'},
])

gen.write_sql('output/special_loot.sql')
```

---

## Common Pitfalls and Troubleshooting

### Problem: Creature drops nothing

**Cause:** `creature_template.lootid` is 0 or does not match any `creature_loot_template.Entry`.

**Fix:**
- Ensure `lootid` is set in the creature definition when using `add_creatures()`
- Verify the loot entry value matches between creature_template and creature_loot_template
- Use `.reload creature_template` in-game after SQL changes

### Problem: Boss drops all items instead of one from group

**Cause:** All items have `group_id=0` (independent rolls).

**Fix:**
- Set `group_id` to the same non-zero value for items that should be mutually exclusive
- Items in the same group compete; exactly one (at most) will drop

### Problem: Item always drops (should be rare)

**Cause:** `chance` is 100.0 or `group_id` is 0 with high chance.

**Fix:**
- Set `chance` to the desired percentage (e.g., 5.0 for 5%)
- Remember that GroupId=0 items are rolled independently

### Problem: Quest item does not drop

**Cause:** `quest_required` is set but the player does not have the quest, or the conditions table is not configured.

**Fix:**
- Set `quest_required=1` on the loot row
- Ensure the quest exists in `quest_template` and the player has accepted it
- For complex conditions, add entries to the `conditions` table

### Problem: Reference loot table not working

**Cause:** The `Reference` column is 0, or the reference Entry does not match.

**Fix:**
- The `reference` key in the loot dict must be > 0 and must match a `reference_loot_template.Entry`
- The `item` key in a reference row is a sub-group identifier, not the actual dropped item
- Verify the referenced table exists and has items

### Problem: Loot shows up in Normal mode but not Heroic

**Cause:** `loot_mode` is set to 1 (Normal only).

**Fix:**
- Set `loot_mode` appropriately: 1=Normal, 2=Heroic10, 4=Heroic25
- Use bitmask combinations: 3=Normal+Heroic10, 7=All modes

---

## Cross-References

- **[Add New Item](add_new_item.md)** -- Create custom items before adding them to loot tables
- **[Create Item Set](create_item_set.md)** -- Create item sets whose pieces drop from boss loot
- **[Custom Crafting Recipe](custom_crafting_recipe.md)** -- Alternative item acquisition via crafting
- **pywowlib API Reference:**
  - `world_builder.sql_generator.SQLGenerator.add_loot()` -- Generic loot table generation
  - `world_builder.sql_generator.SQLGenerator.add_creature_loot()` -- Bulk creature loot
  - `world_builder.sql_generator._LootHelper` -- Internal loot SQL builder
  - `world_builder.sql_generator.SQLGenerator.add_creatures()` -- Creature creation with `lootid`
  - `world_builder.sql_generator.SQLGenerator.add_gameobject_templates()` -- Chest creation with `data1` (loot entry)
