# Add Vendor/Trainer

**Complexity**: Low to Medium
**Estimated Time**: 15-45 minutes
**Applies To**: WoW WotLK 3.3.5a (build 12340) with AzerothCore

---

## Overview

Vendors and trainers are specialized NPCs that provide essential player services. A **vendor** sells items (gear, consumables, reagents, recipes), while a **trainer** teaches spells and skills (class abilities, profession recipes, riding skills). A single NPC can serve both roles simultaneously.

This guide covers the complete process of creating vendor and trainer NPCs using pywowlib's `SQLGenerator`. The toolkit provides the `NPCBuilder` (accessed via `SQLGenerator.add_npcs()`) which handles:

- `creature_template` with appropriate `npcflag` values
- `npc_vendor` entries for items sold
- `gossip_menu` and `gossip_menu_option` for dialogue
- `npc_text` for the NPC's greeting text

Trainer data (`npc_trainer`) is covered separately since it requires manual SQL, but this guide provides complete examples for that as well.

---

## Prerequisites

- Python 3.8+ with pywowlib installed
- Access to your AzerothCore `acore_world` database
- Item entry IDs for vendor inventory (either existing items or custom items created with `SQLGenerator.add_items()`)
- Spell IDs for trainer recipes (look up in `Spell.dbc` or wowhead)
- Familiarity with creature creation (see [add_new_creature.md](add_new_creature.md))

---

## Table of Contents

1. [Understanding NPC Flags](#step-1-understanding-npc-flags)
2. [Creating a Basic Vendor](#step-2-creating-a-basic-vendor)
3. [npc_vendor Table Reference](#step-3-npc_vendor-table-reference)
4. [Creating a Trainer](#step-4-creating-a-trainer)
5. [npc_trainer Table Reference](#step-5-npc_trainer-table-reference)
6. [Adding Gossip Dialogue](#step-6-adding-gossip-dialogue)
7. [gossip_menu and gossip_menu_option Reference](#step-7-gossip_menu-and-gossip_menu_option-reference)
8. [Combined Vendor + Trainer NPC](#step-8-combined-vendor--trainer-npc)
9. [Spawning the NPC](#step-9-spawning-the-npc)
10. [Complete Working Example](#step-10-complete-working-example)
11. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
12. [Cross-References](#cross-references)

---

## Step 1: Understanding NPC Flags

The `npcflag` field in `creature_template` determines what interactions players have with the NPC. It is a bitmask -- combine multiple flags by adding their values.

### 1.1 Vendor and Trainer Flags

| Flag Value | Name | Description |
|-----------|------|-------------|
| 1 | GOSSIP | NPC has a gossip/dialogue window |
| 2 | QUESTGIVER | NPC offers or accepts quests |
| 16 | TRAINER | NPC trains spells/skills (general) |
| 32 | TRAINER_CLASS | NPC is a class-specific trainer |
| 64 | TRAINER_PROFESSION | NPC is a profession trainer |
| 128 | VENDOR | NPC sells items |
| 256 | VENDOR_AMMO | NPC sells ammunition |
| 512 | VENDOR_FOOD | NPC sells food/drink |
| 1024 | VENDOR_POISON | NPC sells poisons (rogue) |
| 2048 | VENDOR_REAGENT | NPC sells class reagents |
| 4096 | REPAIR | NPC repairs equipment |

### 1.2 Common Flag Combinations

| NPC Type | npcflag Value | Flags Combined |
|----------|--------------|----------------|
| Basic vendor | 129 | GOSSIP(1) + VENDOR(128) |
| Vendor + repair | 4225 | GOSSIP(1) + VENDOR(128) + REPAIR(4096) |
| Food vendor | 641 | GOSSIP(1) + VENDOR(128) + VENDOR_FOOD(512) |
| Class trainer | 49 | GOSSIP(1) + TRAINER(16) + TRAINER_CLASS(32) |
| Profession trainer | 81 | GOSSIP(1) + TRAINER(16) + TRAINER_PROFESSION(64) |
| Vendor + class trainer | 177 | GOSSIP(1) + TRAINER(16) + TRAINER_CLASS(32) + VENDOR(128) |
| Vendor + quest giver | 131 | GOSSIP(1) + QUESTGIVER(2) + VENDOR(128) |

### 1.3 Calculating npcflag

```python
# Python helper to build npcflag
NPCFLAG_GOSSIP = 1
NPCFLAG_QUESTGIVER = 2
NPCFLAG_TRAINER = 16
NPCFLAG_TRAINER_CLASS = 32
NPCFLAG_TRAINER_PROFESSION = 64
NPCFLAG_VENDOR = 128
NPCFLAG_VENDOR_AMMO = 256
NPCFLAG_VENDOR_FOOD = 512
NPCFLAG_VENDOR_POISON = 1024
NPCFLAG_VENDOR_REAGENT = 2048
NPCFLAG_REPAIR = 4096

# Example: Vendor + Repair + Gossip
my_npcflag = NPCFLAG_GOSSIP | NPCFLAG_VENDOR | NPCFLAG_REPAIR
print(f"npcflag = {my_npcflag}")  # 4225
```

---

## Step 2: Creating a Basic Vendor

The `NPCBuilder` (via `SQLGenerator.add_npcs()`) creates the `creature_template` and `npc_vendor` entries in a single call.

### 2.1 Simple Vendor Using add_npcs()

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=91000, map_id=0, zone_id=1519)

# Create a vendor NPC
gen.add_npcs([
    {
        'entry': 91000,
        'name': 'Alarion Stormforge',
        'subname': 'Armor Vendor',
        'modelid1': 15880,              # Human male display ID
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,                  # Friendly to all players
        'npcflag': 129,                 # GOSSIP(1) + VENDOR(128)
        'speed_walk': 1.0,
        'speed_run': 1.14286,
        'rank': 0,                      # Normal (not elite)
        'type': 7,                      # Humanoid
        'health_modifier': 1.0,
        'damage_modifier': 1.0,
        'regen_health': 1,
        'movement_type': 0,             # Stationary
        'flags_extra': 2,               # CIVILIAN (does not aggro)

        # Gossip text shown when player right-clicks
        'gossip_menu_id': 91000,
        'gossip_text': 'Greetings, traveler! I have fine storm-forged armor for sale. Browse my wares!',

        # Items for sale
        'vendor_items': [
            # Simple format: just item entry IDs
            2589,                        # Linen Cloth
            2592,                        # Wool Cloth
            4306,                        # Silk Cloth

            # Detailed format: dict with stock limits
            {
                'item': 49426,           # Emblem of Frost
                'maxcount': 10,          # Limited stock: 10 available
                'incrtime': 3600,        # Restock every hour (3600 seconds)
                'extended_cost': 0,
            },
            {
                'item': 44731,           # Bouquet of Ebon Roses
                'maxcount': 0,           # Unlimited stock
                'incrtime': 0,
                'extended_cost': 0,
            },
        ],
    },
])

gen.write_sql('./output/sql/vendor_alarion.sql')
```

### 2.2 How Vendor Items Work

When `vendor_items` contains a plain integer, the `NPCBuilder` treats it as an item entry with unlimited stock:

```python
'vendor_items': [2589, 2592, 4306],
# Equivalent to:
'vendor_items': [
    {'item': 2589, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},
    {'item': 2592, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},
    {'item': 4306, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},
],
```

---

## Step 3: npc_vendor Table Reference

The `npc_vendor` table links item entries to a vendor creature.

### 3.1 Column Reference

| Column | Type | Description |
|--------|------|-------------|
| `entry` | int | creature_template.entry of the vendor NPC |
| `slot` | int | Display slot order (0-based, auto-assigned by NPCBuilder) |
| `item` | int | item_template.entry of the item being sold |
| `maxcount` | int | Maximum stock (0 = unlimited, >0 = limited supply) |
| `incrtime` | int | Restock interval in seconds (only applies when maxcount > 0) |
| `ExtendedCost` | int | FK to npc_vendor_extended_cost for token-based prices (0 = gold only) |

### 3.2 Stock Behavior

- **Unlimited stock** (`maxcount=0`, `incrtime=0`): Item is always available. This is the default.
- **Limited stock** (`maxcount=5`, `incrtime=3600`): Only 5 items available at a time, restocking 1 per hour.
- **Extended cost** (`ExtendedCost=2425`): Player pays with tokens/currency instead of or in addition to gold. The `ExtendedCost` value references a row in `npc_vendor_extended_cost` that defines the currency type and amount.

### 3.3 Manual SQL for npc_vendor

If you need to add items to a vendor without using `add_npcs()`:

```sql
-- Add items to vendor NPC entry 91000
DELETE FROM `npc_vendor` WHERE `entry` = 91000;
INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`) VALUES
(91000, 0, 2589,  0, 0, 0),    -- Linen Cloth (unlimited)
(91000, 1, 2592,  0, 0, 0),    -- Wool Cloth (unlimited)
(91000, 2, 4306,  0, 0, 0),    -- Silk Cloth (unlimited)
(91000, 3, 49426, 10, 3600, 0),-- Emblem of Frost (limited: 10, restock 1/hr)
(91000, 4, 44731, 0, 0, 0);    -- Bouquet of Ebon Roses (unlimited)
```

### 3.4 Token-Based Pricing (Extended Cost)

For items that cost badges, emblems, arena points, or honor:

```sql
-- Example: Item costs 25 Emblem of Frost (currency 2)
-- First, find or create an ExtendedCost entry
-- ExtendedCost ID 2425 = 25 Emblem of Frost (check your DB)

INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`) VALUES
(91000, 5, 51320, 0, 0, 2425);  -- Tier 10 Helm, costs 25 Emblems
```

---

## Step 4: Creating a Trainer

Trainers teach spells and skills to players. The trainer data is stored in the `npc_trainer` table (called `trainer` in some AzerothCore versions).

### 4.1 Trainer Types

| trainer_type | Name | Description |
|-------------|------|-------------|
| 0 | TYPE_CLASS | Class trainer (Warrior, Mage, etc.) |
| 1 | TYPE_MOUNTS | Mount trainer (riding skill) |
| 2 | TYPE_TRADESKILL | Profession trainer (Blacksmithing, etc.) |
| 3 | TYPE_PETS | Pet trainer (Hunter pet skills) |

### 4.2 Class Trainer creature_template

```python
gen.add_npcs([
    {
        'entry': 91100,
        'name': 'Theron Lightblade',
        'subname': 'Warrior Trainer',
        'modelid1': 15880,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,                  # Friendly
        'npcflag': 49,                  # GOSSIP(1) + TRAINER(16) + TRAINER_CLASS(32)
        'rank': 0,
        'type': 7,                      # Humanoid
        'trainer_type': 0,              # CLASS trainer
        'trainer_class': 1,             # Warrior class (1=Warrior, 2=Paladin, etc.)
        'trainer_race': 0,              # 0 = all races
        'health_modifier': 1.0,
        'flags_extra': 2,               # CIVILIAN

        'gossip_menu_id': 91100,
        'gossip_text': 'Ready to learn the ways of the warrior? Let me show you what I know.',
    },
])
```

### 4.3 Profession Trainer creature_template

```python
gen.add_npcs([
    {
        'entry': 91200,
        'name': 'Bronwyn Ironhand',
        'subname': 'Blacksmithing Trainer',
        'modelid1': 17519,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        'npcflag': 81,                  # GOSSIP(1) + TRAINER(16) + TRAINER_PROFESSION(64)
        'rank': 0,
        'type': 7,
        'trainer_type': 2,              # TRADESKILL trainer
        'trainer_spell': 2018,          # Blacksmithing skill spell
        'trainer_class': 0,             # 0 = any class
        'health_modifier': 1.0,
        'flags_extra': 2,

        'gossip_menu_id': 91200,
        'gossip_text': 'The forge awaits, friend. What would you like to learn?',
    },
])
```

### 4.4 Class ID Reference

| ID | Class |
|----|-------|
| 1 | Warrior |
| 2 | Paladin |
| 3 | Hunter |
| 4 | Rogue |
| 5 | Priest |
| 6 | Death Knight |
| 7 | Shaman |
| 8 | Mage |
| 9 | Warlock |
| 11 | Druid |

---

## Step 5: npc_trainer Table Reference

The `npc_trainer` table defines which spells a trainer NPC can teach.

### 5.1 Column Reference

| Column | Type | Description |
|--------|------|-------------|
| `ID` | int | Trainer NPC entry (creature_template.entry) |
| `SpellID` | int | Spell that the trainer teaches (FK to Spell.dbc) |
| `MoneyCost` | int | Cost in copper to learn (e.g. 100000 = 10 gold) |
| `ReqSkillLine` | int | Required skill line (e.g. 164 = Blacksmithing) |
| `ReqSkillRank` | int | Minimum skill level required to learn |
| `ReqLevel` | int | Minimum player level required |

### 5.2 Manual SQL for Trainer Spells

The `npc_trainer` table requires manual SQL since the `NPCBuilder` does not generate it automatically:

```sql
-- Warrior trainer: Teach combat abilities
DELETE FROM `npc_trainer` WHERE `ID` = 91100;
INSERT INTO `npc_trainer` (`ID`, `SpellID`, `MoneyCost`, `ReqSkillLine`, `ReqSkillRank`, `ReqLevel`) VALUES
-- Basic warrior abilities
(91100, 78,     100,    0, 0, 1),   -- Heroic Strike (Rank 1) - 1 copper
(91100, 772,    600,    0, 0, 4),   -- Rend (Rank 1)
(91100, 6343,   1800,   0, 0, 6),   -- Thunder Clap (Rank 1)
(91100, 100,    3000,   0, 0, 8),   -- Charge (Rank 1)
(91100, 1715,   5000,   0, 0, 10),  -- Hamstring
(91100, 7384,   10000,  0, 0, 12),  -- Overpower
(91100, 6572,   20000,  0, 0, 16),  -- Revenge (Rank 1)
(91100, 1680,   50000,  0, 0, 36),  -- Whirlwind
(91100, 20230, 100000,  0, 0, 40),  -- Retaliation
-- Level 80 abilities
(91100, 47450, 500000,  0, 0, 75),  -- Heroic Strike (Rank 13)
(91100, 47465, 500000,  0, 0, 75),  -- Rend (Rank 10)
(91100, 47502, 500000,  0, 0, 78);  -- Thunder Clap (Rank 9)
```

### 5.3 Blacksmithing Trainer Example

```sql
-- Blacksmithing trainer: Teach profession recipes
DELETE FROM `npc_trainer` WHERE `ID` = 91200;
INSERT INTO `npc_trainer` (`ID`, `SpellID`, `MoneyCost`, `ReqSkillLine`, `ReqSkillRank`, `ReqLevel`) VALUES
-- Apprentice Blacksmithing (skill 1-75)
(91200, 2018,   100,    0,   0,  5),  -- Blacksmithing (Apprentice)
(91200, 2738,   200,    164, 1,  5),  -- Copper Chain Vest
(91200, 2737,   500,    164, 15, 5),  -- Copper Bracers
(91200, 2739,   1000,   164, 30, 5),  -- Copper Chain Belt
-- Journeyman (skill 75-150)
(91200, 3100,   5000,   164, 50, 10), -- Blacksmithing (Journeyman)
(91200, 2741,   2000,   164, 75, 10), -- Bronze Mace
(91200, 2742,   3000,   164, 90, 10), -- Bronze Axe
-- Expert (skill 150-225)
(91200, 3538,   50000,  164, 125, 20),-- Blacksmithing (Expert)
(91200, 9920,   10000,  164, 150, 20),-- Heavy Grinding Stone
-- Artisan (skill 225-300)
(91200, 9785,  250000,  164, 200, 35),-- Blacksmithing (Artisan)
-- Master (skill 300-375)
(91200, 29844, 500000,  164, 275, 55),-- Blacksmithing (Master)
-- Grand Master (skill 375-450)
(91200, 51300, 1000000, 164, 350, 65);-- Blacksmithing (Grand Master)
```

### 5.4 Common Skill Line IDs

| SkillLine ID | Profession |
|-------------|------------|
| 164 | Blacksmithing |
| 165 | Leatherworking |
| 171 | Alchemy |
| 182 | Herbalism |
| 185 | Cooking |
| 186 | Mining |
| 197 | Tailoring |
| 202 | Engineering |
| 333 | Enchanting |
| 393 | Skinning |
| 755 | Jewelcrafting |
| 762 | Riding |
| 773 | Inscription |

---

## Step 6: Adding Gossip Dialogue

Gossip menus provide interactive dialogue when a player right-clicks an NPC. The `NPCBuilder` handles basic gossip (a greeting text), but you can also add multi-option gossip menus.

### 6.1 Basic Gossip (Built-in to NPCBuilder)

```python
gen.add_npcs([
    {
        'entry': 91000,
        'name': 'Alarion Stormforge',
        # ... other fields ...

        'gossip_menu_id': 91000,
        'gossip_text': 'Welcome! Browse my wares.',
    },
])
```

This generates:
- `npc_text` entry with the greeting text
- `gossip_menu` link between the menu ID and text ID

### 6.2 Multi-Option Gossip Menus

For NPCs with dialogue options (e.g. "I want to browse your goods", "Tell me about the vault"), use the `gossip_options` field:

```python
gen.add_npcs([
    {
        'entry': 91000,
        'name': 'Alarion Stormforge',
        'subname': 'Armor Vendor',
        'modelid1': 15880,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        'npcflag': 131,                  # GOSSIP + QUESTGIVER + VENDOR
        'type': 7,
        'flags_extra': 2,

        'gossip_menu_id': 91000,
        'gossip_text': 'Greetings, hero. How may I assist you today?',

        'gossip_options': [
            {
                'option_id': 0,
                'icon': 1,               # Chat icon (see icon table below)
                'text': 'I want to browse your goods.',
                'type': 3,               # GOSSIP_OPTION_VENDOR
                'npc_flag': 128,         # Requires VENDOR flag
            },
            {
                'option_id': 1,
                'icon': 0,               # Chat bubble icon
                'text': 'Tell me about the Vault of Storms.',
                'type': 0,               # GOSSIP_OPTION_GOSSIP (open submenu)
                'action_menu_id': 91001, # Opens gossip menu 91001
            },
            {
                'option_id': 2,
                'icon': 3,               # Trainer icon
                'text': 'I want to train.',
                'type': 5,               # GOSSIP_OPTION_TRAINER
                'npc_flag': 16,          # Requires TRAINER flag
            },
        ],

        'vendor_items': [2589, 2592, 4306],
    },
])
```

### 6.3 Gossip Option Icon Values

| Icon Value | Icon | Typical Use |
|-----------|------|-------------|
| 0 | Chat bubble | General dialogue |
| 1 | Vendor bag | Shopping |
| 2 | Taxi/flight | Flight master |
| 3 | Trainer book | Training |
| 4 | Cogwheel | Engineering/special |
| 5 | Cogwheel (alt) | Alternate engineering |
| 6 | Gold coins | Banking |
| 7 | Chat bubble (alt) | Alternate dialogue |
| 8 | Tabard | Tabard designer |
| 9 | Crossed swords | Battlemaster |
| 10 | Small dot | Misc |

### 6.4 Gossip Option Type Values

| Type Value | Constant | Description |
|-----------|----------|-------------|
| 0 | GOSSIP_OPTION_GOSSIP | Open another gossip menu |
| 1 | GOSSIP_OPTION_VENDOR_EXTENDED | Vendor with extended cost |
| 2 | GOSSIP_OPTION_TAXIVENDOR | Flight master |
| 3 | GOSSIP_OPTION_VENDOR | Open vendor window |
| 4 | GOSSIP_OPTION_LEARNDUALSPEC | Dual spec trainer |
| 5 | GOSSIP_OPTION_TRAINER | Open trainer window |
| 6 | GOSSIP_OPTION_SPIRITGUIDE | Spirit healer |
| 7 | GOSSIP_OPTION_INNKEEPER | Set hearthstone |
| 8 | GOSSIP_OPTION_BANKER | Open bank |
| 9 | GOSSIP_OPTION_PETITIONER | Guild/arena petition |
| 10 | GOSSIP_OPTION_TABARDDESIGNER | Design tabard |
| 11 | GOSSIP_OPTION_BATTLEFIELD | Battleground queue |
| 12 | GOSSIP_OPTION_AUCTIONEER | Auction house |
| 13 | GOSSIP_OPTION_STABLEPET | Stable pets |
| 14 | GOSSIP_OPTION_ARMORER | Repair equipment |

---

## Step 7: gossip_menu and gossip_menu_option Reference

### 7.1 gossip_menu Table

Links a menu ID to the text displayed in the gossip window.

| Column | Type | Description |
|--------|------|-------------|
| `MenuID` | int | Unique gossip menu ID (same as creature_template.gossip_menu_id) |
| `TextID` | int | FK to npc_text.ID for the greeting text |

### 7.2 npc_text Table

Contains the NPC's greeting text and its variations.

| Column | Type | Description |
|--------|------|-------------|
| `ID` | int | Unique text ID |
| `text0_0` | text | Male NPC text |
| `text0_1` | text | Female NPC text (use same as text0_0 if gender-neutral) |
| `BroadcastTextID0` | int | BroadcastText reference (0 for custom) |
| `lang0` | int | Language (0 = Universal) |
| `Probability0` | float | Selection probability (1.0 if single entry) |

### 7.3 gossip_menu_option Table

Defines clickable options in the gossip window.

| Column | Type | Description |
|--------|------|-------------|
| `MenuID` | int | FK to gossip_menu.MenuID |
| `OptionID` | int | Option order (0-based) |
| `OptionIcon` | int | Icon displayed (see icon table above) |
| `OptionText` | text | Text shown for this option |
| `OptionBroadcastTextID` | int | BroadcastText reference (0 for custom) |
| `OptionType` | int | Action type (see type table above) |
| `OptionNpcFlag` | int | Required NPC flag for this option to appear |
| `ActionMenuID` | int | Submenu to open (for GOSSIP_OPTION_GOSSIP type) |
| `ActionPoiID` | int | Point of interest ID (0 if none) |
| `BoxCoded` | int | 1 = requires confirmation dialog |
| `BoxMoney` | int | Money required for confirmation (copper) |
| `BoxText` | text | Confirmation dialog text |
| `BoxBroadcastTextID` | int | BroadcastText for confirmation |

### 7.4 Manual SQL for Gossip

```sql
-- NPC greeting text
DELETE FROM `npc_text` WHERE `ID` = 91000;
INSERT INTO `npc_text` (`ID`, `text0_0`, `BroadcastTextID0`, `lang0`, `Probability0`) VALUES
(91000, 'Greetings, hero. How may I assist you today?', 0, 0, 1.0);

-- Link gossip menu to text
DELETE FROM `gossip_menu` WHERE `MenuID` = 91000;
INSERT INTO `gossip_menu` (`MenuID`, `TextID`) VALUES
(91000, 91000);

-- Gossip options
DELETE FROM `gossip_menu_option` WHERE `MenuID` = 91000;
INSERT INTO `gossip_menu_option` (`MenuID`, `OptionID`, `OptionIcon`, `OptionText`,
    `OptionBroadcastTextID`, `OptionType`, `OptionNpcFlag`,
    `ActionMenuID`, `ActionPoiID`, `BoxCoded`, `BoxMoney`,
    `BoxText`, `BoxBroadcastTextID`) VALUES
(91000, 0, 1, 'I want to browse your goods.', 0, 3, 128, 0, 0, 0, 0, '', 0),
(91000, 1, 0, 'Tell me about the Vault of Storms.', 0, 0, 0, 91001, 0, 0, 0, '', 0),
(91000, 2, 3, 'Train me.', 0, 5, 16, 0, 0, 0, 0, '', 0);
```

---

## Step 8: Combined Vendor + Trainer NPC

A single NPC can be both a vendor and a trainer. This is common for profession trainers who also sell recipe materials.

### 8.1 Python Code

```python
gen.add_npcs([
    {
        'entry': 91300,
        'name': 'Kayla Ironsong',
        'subname': 'Blacksmithing Trainer & Supplies',
        'modelid1': 17519,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        # Combine: GOSSIP(1) + TRAINER(16) + TRAINER_PROFESSION(64) + VENDOR(128)
        'npcflag': 209,
        'rank': 0,
        'type': 7,
        'trainer_type': 2,              # Tradeskill
        'trainer_spell': 2018,          # Blacksmithing
        'trainer_class': 0,
        'health_modifier': 1.0,
        'flags_extra': 2,

        'gossip_menu_id': 91300,
        'gossip_text': 'The forge is hot and ready. Need training, or supplies?',

        'gossip_options': [
            {
                'option_id': 0,
                'icon': 3,
                'text': 'Train me in Blacksmithing.',
                'type': 5,              # GOSSIP_OPTION_TRAINER
                'npc_flag': 16,
            },
            {
                'option_id': 1,
                'icon': 1,
                'text': 'Show me your supplies.',
                'type': 3,              # GOSSIP_OPTION_VENDOR
                'npc_flag': 128,
            },
        ],

        'vendor_items': [
            {'item': 2901, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},  -- Mining Pick
            {'item': 5956, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},  -- Blacksmith Hammer
            {'item': 2880, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},  -- Weak Flux
            {'item': 3466, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},  -- Strong Flux
            {'item': 18567, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0}, -- Elemental Flux
        ],
    },
])

# Don't forget to add npc_trainer entries separately (manual SQL)
```

Then add trainer spells with manual SQL as shown in Step 5.

---

## Step 9: Spawning the NPC

After creating the vendor/trainer template, spawn it in the game world using `add_spawns()`:

```python
gen.add_spawns([
    {
        'entry': 91000,                  # Vendor entry
        'map': 0,                        # Eastern Kingdoms
        'zone': 1519,                    # Stormwind City
        'position': (-8830.50, 640.12, 94.20, 3.85),
        'spawntimesecs': 120,            # 2 min respawn
        'movement_type': 0,             # Stationary
    },
])
```

### 9.1 Placement Tips

- **Vendors** should be placed near related content: armor vendors near blacksmiths, food vendors near inns.
- **Trainers** are typically indoors in class/profession halls.
- Use `.gps` in-game for exact coordinates.
- Set `movement_type` to 0 (Idle) for vendors and trainers -- they should not wander away from their shop.
- Consider adding a `creature_addon` with an emote for flavor (e.g. `emote: 233` for mining, `emote: 373` for smithing).

### 9.2 Spawn with Cosmetic Addon

```python
gen.add_spawns([
    {
        'entry': 91200,                  # Blacksmithing trainer
        'map': 0,
        'zone': 1519,
        'position': (-8830.50, 640.12, 94.20, 3.85),
        'spawntimesecs': 120,
        'movement_type': 0,
        'addon': {
            'emote': 373,                # Smithing animation
        },
    },
])
```

---

## Step 10: Complete Working Example

Below is a complete, self-contained script that creates a vendor NPC, a trainer NPC, and a combined vendor+trainer NPC, with spawns and gossip:

```python
"""
Complete example: Create vendor and trainer NPCs.
Generates all creature_template, npc_vendor, gossip, and spawn SQL.
Trainer spells (npc_trainer) require manual SQL appended afterward.
"""

from world_builder.sql_generator import SQLGenerator

# ---------------------------------------------------------------
# 1. Initialize generator
# ---------------------------------------------------------------
gen = SQLGenerator(start_entry=91000, map_id=0, zone_id=1519)

# ---------------------------------------------------------------
# 2. Create a pure vendor NPC
# ---------------------------------------------------------------
gen.add_npcs([
    {
        'entry': 91000,
        'name': 'Alarion Stormforge',
        'subname': 'Storm-Forged Armor',
        'modelid1': 15880,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        'npcflag': 4225,                  # GOSSIP + VENDOR + REPAIR
        'rank': 0,
        'type': 7,
        'health_modifier': 1.0,
        'flags_extra': 2,
        'gossip_menu_id': 91000,
        'gossip_text': 'Finest storm-forged armor in all the land!',
        'vendor_items': [
            {'item': 43852, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},
            {'item': 43853, 'maxcount': 0, 'incrtime': 0, 'extended_cost': 0},
            {'item': 44731, 'maxcount': 5, 'incrtime': 7200, 'extended_cost': 0},
        ],
    },
])

# ---------------------------------------------------------------
# 3. Create a class trainer NPC
# ---------------------------------------------------------------
gen.add_npcs([
    {
        'entry': 91100,
        'name': 'Theron Lightblade',
        'subname': 'Warrior Trainer',
        'modelid1': 15880,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        'npcflag': 49,                    # GOSSIP + TRAINER + TRAINER_CLASS
        'rank': 0,
        'type': 7,
        'trainer_type': 0,
        'trainer_class': 1,               # Warrior
        'health_modifier': 1.0,
        'flags_extra': 2,
        'gossip_menu_id': 91100,
        'gossip_text': 'A warrior must always be ready. Let us train.',
    },
])

# ---------------------------------------------------------------
# 4. Create a profession trainer + vendor combo
# ---------------------------------------------------------------
gen.add_npcs([
    {
        'entry': 91200,
        'name': 'Bronwyn Ironhand',
        'subname': 'Blacksmithing Trainer & Supplies',
        'modelid1': 17519,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 35,
        'npcflag': 209,                   # GOSSIP + TRAINER + PROF + VENDOR
        'rank': 0,
        'type': 7,
        'trainer_type': 2,
        'trainer_spell': 2018,
        'health_modifier': 1.0,
        'flags_extra': 2,
        'gossip_menu_id': 91200,
        'gossip_text': 'Need training or supplies? You came to the right place.',
        'gossip_options': [
            {
                'option_id': 0,
                'icon': 3,
                'text': 'Train me in Blacksmithing.',
                'type': 5,
                'npc_flag': 16,
            },
            {
                'option_id': 1,
                'icon': 1,
                'text': 'Let me see your supplies.',
                'type': 3,
                'npc_flag': 128,
            },
        ],
        'vendor_items': [2901, 5956, 2880, 3466, 18567],
    },
])

# ---------------------------------------------------------------
# 5. Spawn all NPCs
# ---------------------------------------------------------------
gen.add_spawns([
    # Vendor
    {
        'entry': 91000,
        'position': (-8830.50, 640.12, 94.20, 3.85),
        'spawntimesecs': 120,
        'movement_type': 0,
    },
    # Warrior trainer
    {
        'entry': 91100,
        'position': (-8835.00, 645.00, 94.20, 4.00),
        'spawntimesecs': 120,
        'movement_type': 0,
    },
    # Blacksmith trainer + vendor (with smithing emote)
    {
        'entry': 91200,
        'position': (-8825.00, 635.00, 94.20, 3.70),
        'spawntimesecs': 120,
        'movement_type': 0,
        'addon': {
            'emote': 373,                 # Smithing animation
        },
    },
])

# ---------------------------------------------------------------
# 6. Write SQL
# ---------------------------------------------------------------
gen.write_sql('./output/sql/vendors_trainers.sql')
print("SQL written to ./output/sql/vendors_trainers.sql")

# ---------------------------------------------------------------
# 7. Validate
# ---------------------------------------------------------------
validation = gen.validate()
if validation['valid']:
    print("Validation passed!")
else:
    for err in validation['errors']:
        print(f"ERROR: {err}")
for warn in validation['warnings']:
    print(f"WARNING: {warn}")
```

After running this script, manually append `npc_trainer` SQL to the output file (or apply it separately):

```sql
-- Append to vendors_trainers.sql or apply separately

-- Warrior trainer spells
DELETE FROM `npc_trainer` WHERE `ID` = 91100;
INSERT INTO `npc_trainer` (`ID`, `SpellID`, `MoneyCost`, `ReqSkillLine`, `ReqSkillRank`, `ReqLevel`) VALUES
(91100, 78,     100,    0, 0, 1),
(91100, 772,    600,    0, 0, 4),
(91100, 6343,   1800,   0, 0, 6),
(91100, 100,    3000,   0, 0, 8),
(91100, 47450,  500000, 0, 0, 75),
(91100, 47465,  500000, 0, 0, 75);

-- Blacksmithing trainer spells
DELETE FROM `npc_trainer` WHERE `ID` = 91200;
INSERT INTO `npc_trainer` (`ID`, `SpellID`, `MoneyCost`, `ReqSkillLine`, `ReqSkillRank`, `ReqLevel`) VALUES
(91200, 2018,   100,    0,   0,  5),
(91200, 2738,   200,    164, 1,  5),
(91200, 2737,   500,    164, 15, 5),
(91200, 3100,   5000,   164, 50, 10),
(91200, 3538,   50000,  164, 125, 20),
(91200, 9785,   250000, 164, 200, 35),
(91200, 29844,  500000, 164, 275, 55),
(91200, 51300, 1000000, 164, 350, 65);
```

### Applying and Testing

```bash
# Apply SQL
mysql -u root -p acore_world < ./output/sql/vendors_trainers.sql

# In-game testing
.reload creature_template 91000
.reload creature_template 91100
.reload creature_template 91200
.npc add 91000    -- Spawn vendor for testing
```

---

## Common Pitfalls and Troubleshooting

### NPC does not show vendor window

- **Cause**: `npcflag` does not include the VENDOR flag (128).
- **Fix**: Verify `npcflag` includes 128. Use `npcflag = existing_flags | 128`.

### NPC does not show trainer window

- **Cause**: `npcflag` does not include TRAINER (16), or `trainer_type`/`trainer_class` are wrong.
- **Fix**: Set `npcflag` to include 16 (and 32 for class, 64 for profession). Set `trainer_type` appropriately: 0 for class, 2 for profession. Set `trainer_class` to the correct class ID (1-11) for class trainers.

### Trainer shows "No trainer spells available"

- **Cause**: No `npc_trainer` rows exist for this NPC entry, or the player does not meet requirements.
- **Fix**: Add `npc_trainer` rows with `ID` matching the creature entry. Check that `ReqLevel` and `ReqSkillRank` are not set higher than the player's level/skill.

### Vendor has no items listed

- **Cause**: No `npc_vendor` rows exist for this NPC entry.
- **Fix**: Verify `npc_vendor.entry` matches the creature's entry ID. Check that the items in `npc_vendor.item` exist in `item_template`.

### Gossip options do not appear

- **Cause**: `npcflag` does not include GOSSIP (1), or the `gossip_menu_id` is 0.
- **Fix**: Set `npcflag` to include 1. Set `gossip_menu_id` to a non-zero value. Verify `gossip_menu` and `gossip_menu_option` rows exist.

### NPC shows "wrong" trainer window (e.g. Mage spells for a Warrior trainer)

- **Cause**: `trainer_class` is set to the wrong class ID.
- **Fix**: Set `trainer_class` to the correct value (e.g. 1 for Warrior, 8 for Mage).

### Limited-stock vendor items never restock

- **Cause**: `incrtime` is 0 or `maxcount` is 0.
- **Fix**: Both `maxcount` and `incrtime` must be greater than 0 for limited stock to work. Set `maxcount` to the maximum available and `incrtime` to the restock interval in seconds.

### Gossip option triggers wrong action

- **Cause**: `OptionType` does not match the intended action.
- **Fix**: Use the correct `OptionType` value (3 for vendor, 5 for trainer, 0 for submenu). Verify `OptionNpcFlag` matches a flag present in the creature's `npcflag`.

---

## Cross-References

- **[Add New Creature](add_new_creature.md)** -- Prerequisite: creating the base creature_template entry
- **[Update Boss Mechanics](update_boss_mechanics.md)** -- For NPCs that also serve as boss encounters
- **[Change NPC Pathing](change_npc_pathing.md)** -- For wandering vendor NPCs (rare, but possible)
- **SQLGenerator NPCBuilder API** -- `world_builder/sql_generator.py` NPCBuilder class for complete API reference
