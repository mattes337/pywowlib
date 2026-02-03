# Add New Quest

| Property | Value |
|---|---|
| **Complexity** | Low |
| **Client-Side Files** | None |
| **Server-Side Files** | SQL: `quest_template`, `quest_template_addon`, `creature_queststarter`, `creature_questender` |
| **pywowlib APIs** | `SQLGenerator.add_quests()`, `SQLGenerator.add_npcs()`, `SQLGenerator.add_spawns()`, `SQLGenerator.add_items()` |
| **Estimated Time** | 15-30 minutes for a basic quest |

## Overview

Adding a new quest to WoW WotLK 3.3.5a is the most common content authoring task a modder
will encounter. Quests are entirely server-side -- no client patch is required unless you
need custom items or models. The quest text, objectives, rewards, and NPC assignments all
live in the AzerothCore `acore_world` database.

This guide walks through every field of the `quest_template` and `quest_template_addon`
tables, explains the quest flag system, covers reward configuration (XP, gold, items,
reputation), and shows how to use the pywowlib `SQLGenerator` Python API to produce
ready-to-import SQL.

By the end of this guide you will have a fully functional "Kill 10 Rats" quest with a
quest-giver NPC, a quest-ender NPC, reward items, gold, and experience.

---

## Prerequisites

- Python 3.8 or later installed.
- The `pywowlib` repository cloned and available on your Python path.
- An AzerothCore server with a running `acore_world` database.
- A text editor or IDE for writing Python scripts.
- A MySQL/MariaDB client for applying the generated SQL.
- Basic familiarity with WoW quest mechanics from a player perspective.

### Entry ID Reservations

Every entity in the AzerothCore database (creatures, items, quests, gameobjects) is
identified by an integer entry ID. To avoid collisions with existing Blizzard content and
other custom content, you must choose a safe starting range. The `SQLGenerator` class
handles auto-allocation from a configurable base entry.

**Recommended custom ranges:**
- `90000-99999` for personal/development content
- `100000-199999` for small mods
- `200000+` for large projects

---

## Step 1: Understand the quest_template Table

The `quest_template` table is the primary table for quest definitions. Every quest in the
game has exactly one row in this table. The pywowlib `QuestBuilder` writes this table
automatically when you call `add_quests()`.

### Complete quest_template Column Reference

#### Identity and Classification

| Column | Type | Default | Description |
|---|---|---|---|
| `ID` | int | Auto | Primary key. Unique quest identifier. pywowlib auto-allocates this from `start_entry`. |
| `QuestType` | int | 2 | Determines quest behavior. See the QuestType values table below. |
| `QuestLevel` | int | 1 | The level displayed in the quest log. Set to `-1` to make the quest scale to the player level. |
| `MinLevel` | int | 0 | Minimum player level required to accept the quest. `0` means no restriction. |
| `QuestSortID` | int | 0 | Zone or category sort. Positive values are zone IDs (from AreaTable.dbc). Negative values are quest category IDs (e.g., `-141` for "Tournament"). |
| `QuestInfoID` | int | 0 | Quest type icon shown in the quest log. See QuestInfoID values below. |
| `SuggestedGroupNum` | int | 0 | Suggested group size. `0` means solo. Values 2-5 show "Suggested Players: N" in the tooltip. |

#### QuestType Values

| Value | Name | Description |
|---|---|---|
| 0 | Normal | Standard quest, no special behavior. |
| 1 | Group | Displayed as a group quest (shares kill credit automatically). |
| 2 | Life | Default type. Standard quest with no special behavior. Most quests use this. |
| 21 | PvP | PvP-related quest. |
| 41 | Raid | Raid quest (shown as "Raid" in quest log). |
| 62 | Spell | Quest triggered by a spell. |
| 81 | Dungeon | Dungeon quest (shown as "Dungeon" in quest log). |
| 82 | World Event | Seasonal/world event quest. |
| 83 | Legendary | Legendary quest chain. |
| 84 | Escort | Escort quest. |
| 85 | Heroic | Heroic dungeon quest. |

#### QuestInfoID Values (Quest Type Icons)

| Value | Icon Label | When to Use |
|---|---|---|
| 0 | (none) | Generic quest, no special icon. |
| 1 | Group | Group quests. |
| 21 | Life | Standard life/normal quests. |
| 41 | PvP | PvP quests (Battlegrounds, world PvP). |
| 62 | Raid | Raid-level content. |
| 81 | Dungeon | Dungeon quests. |
| 82 | World Event | Seasonal events (Brewfest, Hallow's End). |
| 83 | Legendary | Legendary quest chains (Atiesh, Shadowmourne). |
| 84 | Escort | Escort quests. |
| 85 | Heroic | Heroic dungeon quests. |
| 88 | Raid (10) | 10-player raid quests. |
| 89 | Raid (25) | 25-player raid quests. |

#### Faction Requirements

| Column | Type | Default | Description |
|---|---|---|---|
| `RequiredFactionId1` | int | 0 | First required reputation faction ID (from Faction.dbc). |
| `RequiredFactionId2` | int | 0 | Second required reputation faction ID. |
| `RequiredFactionValue1` | int | 0 | Minimum reputation value for faction 1. Values are raw reputation: Neutral=0, Friendly=3000, Honored=9000, Revered=21000, Exalted=42000. |
| `RequiredFactionValue2` | int | 0 | Minimum reputation value for faction 2. |

#### Reward Configuration

| Column | Type | Default | Description |
|---|---|---|---|
| `RewardNextQuest` | int | 0 | Quest ID offered immediately after completing this quest. The "next quest" popup. |
| `RewardXPDifficulty` | int | 0 | XP reward difficulty index (0-10). The actual XP amount depends on quest level and this index, using a lookup table in the core. Index 0 = no XP, higher values = more XP. Typical values: 1-3 for low-level quests, 5-7 for max-level quests. |
| `RewardMoney` | int | 0 | Money reward in copper. 1 gold = 10000 copper, 1 silver = 100 copper. At max level (80), if `RewardMoney` is negative, it represents money required to complete the quest. |
| `RewardBonusMoney` | int | 0 | Extra gold given at max level instead of XP (also in copper). When a level 80 character completes a quest designed for lower levels, they receive this bonus gold. |
| `RewardDisplaySpell` | int | 0 | Spell ID shown in the reward window (visual only, not actually cast). |
| `RewardSpell` | int | 0 | Spell ID actually cast on the player upon quest completion. Used for learning new abilities, applying buffs, or triggering events. |
| `RewardHonor` | int | 0 | Honor points rewarded. |
| `RewardKillHonor` | int | 0 | Additional honor value (multiplied by honor rate). |
| `StartItem` | int | 0 | Item entry provided to the player when accepting the quest (e.g., a quest-specific tool or container). Automatically removed if the quest is abandoned. |
| `RewardTitle` | int | 0 | Title ID (from CharTitles.dbc) awarded on completion. For example, "the Kingslayer" or "Jenkins". |
| `RewardTalents` | int | 0 | Number of bonus talent points awarded (used in WotLK for certain quest chains). |
| `RewardArenaPoints` | int | 0 | Arena points awarded on completion. |

#### Reward Items (Up to 4 guaranteed rewards)

These are items the player always receives upon completing the quest.

| Column | Type | Default | Description |
|---|---|---|---|
| `RewardItem1` | int | 0 | Entry ID of the first guaranteed reward item. |
| `RewardAmount1` | int | 0 | Quantity of the first reward item. |
| `RewardItem2` | int | 0 | Entry ID of the second guaranteed reward item. |
| `RewardAmount2` | int | 0 | Quantity of the second reward item. |
| `RewardItem3` | int | 0 | Entry ID of the third guaranteed reward item. |
| `RewardAmount3` | int | 0 | Quantity of the third reward item. |
| `RewardItem4` | int | 0 | Entry ID of the fourth guaranteed reward item. |
| `RewardAmount4` | int | 0 | Quantity of the fourth reward item. |

#### Reward Choice Items (Up to 6 -- player picks one)

These items appear in the "Choose one of these rewards" section.

| Column | Type | Default | Description |
|---|---|---|---|
| `RewardChoiceItemID1` | int | 0 | Entry ID of choice item 1. |
| `RewardChoiceItemQuantity1` | int | 0 | Quantity of choice item 1. |
| `RewardChoiceItemID2` | int | 0 | Entry ID of choice item 2. |
| `RewardChoiceItemQuantity2` | int | 0 | Quantity of choice item 2. |
| `RewardChoiceItemID3` | int | 0 | Entry ID of choice item 3. |
| `RewardChoiceItemQuantity3` | int | 0 | Quantity of choice item 3. |
| `RewardChoiceItemID4` | int | 0 | Entry ID of choice item 4. |
| `RewardChoiceItemQuantity4` | int | 0 | Quantity of choice item 4. |
| `RewardChoiceItemID5` | int | 0 | Entry ID of choice item 5. |
| `RewardChoiceItemQuantity5` | int | 0 | Quantity of choice item 5. |
| `RewardChoiceItemID6` | int | 0 | Entry ID of choice item 6. |
| `RewardChoiceItemQuantity6` | int | 0 | Quantity of choice item 6. |

#### Reward Factions (Up to 5 reputation rewards)

| Column | Type | Default | Description |
|---|---|---|---|
| `RewardFactionID1` | int | 0 | Faction ID for reputation reward 1. |
| `RewardFactionValue1` | int | 0 | Reputation value change for faction 1. Can be negative for reputation loss. |
| `RewardFactionOverride1` | int | 0 | Override value (raw reputation, bypasses rate multipliers). |
| `RewardFactionID2`-`RewardFactionOverride5` | int | 0 | Same as above for factions 2-5. |

#### Objectives -- Required Kills / Interactions

| Column | Type | Default | Description |
|---|---|---|---|
| `RequiredNpcOrGo1` | int | 0 | Entry ID of the creature or gameobject the player must interact with. **Positive values** = creature entry. **Negative values** = gameobject entry (e.g., `-90005` means gameobject entry 90005). |
| `RequiredNpcOrGoCount1` | int | 0 | Number of times the player must kill/interact with the target. |
| `RequiredNpcOrGo2` | int | 0 | Second objective target. |
| `RequiredNpcOrGoCount2` | int | 0 | Count for second objective. |
| `RequiredNpcOrGo3` | int | 0 | Third objective target. |
| `RequiredNpcOrGoCount3` | int | 0 | Count for third objective. |
| `RequiredNpcOrGo4` | int | 0 | Fourth objective target. |
| `RequiredNpcOrGoCount4` | int | 0 | Count for fourth objective. |

#### Objectives -- Required Items

| Column | Type | Default | Description |
|---|---|---|---|
| `RequiredItemId1` | int | 0 | Entry ID of a required item the player must collect. |
| `RequiredItemCount1` | int | 0 | Number of that item required. |
| `RequiredItemId2`-`RequiredItemCount6` | int | 0 | Additional required items (up to 6 slots). |

#### Item Drops (Source hints)

| Column | Type | Default | Description |
|---|---|---|---|
| `ItemDrop1` | int | 0 | Item entry ID that may drop from quest targets. Purely informational -- actual drops are controlled by `creature_loot_template`. |
| `ItemDropQuantity1` | int | 0 | Expected quantity per drop. |
| `ItemDrop2`-`ItemDropQuantity4` | int | 0 | Additional drop hints (up to 4). |

#### Quest Flags

| Column | Type | Default | Description |
|---|---|---|---|
| `Flags` | int | 0 | Bitmask controlling quest behavior. Multiple flags can be combined with bitwise OR. See the Flags reference below. |
| `RequiredPlayerKills` | int | 0 | Number of player kills required (PvP quests only). |
| `TimeAllowed` | int | 0 | Time limit in seconds. `0` means no time limit. When set, a timer appears in the quest tracker. |
| `AllowableRaces` | int | 0 | Bitmask of races allowed to accept the quest. `0` means all races. See race mask values below. |

#### Text Fields

| Column | Type | Default | Description |
|---|---|---|---|
| `LogTitle` | string | '' | The quest name shown in the quest log and on the minimap. This is the single most visible string for your quest. |
| `LogDescription` | string | '' | The description shown in the quest log panel. This is the "fluff text" that tells the story. Supports `$N` (player name), `$C` (player class), `$R` (player race), `$B` (line break). |
| `QuestDescription` | string | '' | The objectives text shown at the top of the quest tracker. Should be a concise summary like "Kill 10 Tunnel Rats in the Deadmines." |
| `AreaDescription` | string | '' | Area description hint for the map tooltip. |
| `QuestCompletionLog` | string | '' | Text shown when all objectives are complete and the player returns to the quest ender. |

#### Objective Text Overrides

| Column | Type | Default | Description |
|---|---|---|---|
| `ObjectiveText1` | string | '' | Custom text for objective 1. Overrides the auto-generated "0/10 Rat killed" text. For example: "Tunnel Rats exterminated". |
| `ObjectiveText2` | string | '' | Custom text for objective 2. |
| `ObjectiveText3` | string | '' | Custom text for objective 3. |
| `ObjectiveText4` | string | '' | Custom text for objective 4. |

#### Point of Interest

| Column | Type | Default | Description |
|---|---|---|---|
| `POIContinent` | int | 0 | Map ID where the quest objective marker appears. |
| `POIx` | float | 0 | X coordinate of the quest objective marker on the map. |
| `POIy` | float | 0 | Y coordinate of the quest objective marker. |
| `POIPriority` | int | 0 | Priority for displaying overlapping markers. |

---

## Step 2: Understand the Quest Flag System

Quest flags are stored as a bitmask in the `Flags` column. You combine multiple flags
using the bitwise OR operator (`|`).

### Quest Flags Reference

| Flag Value | Hex | Constant Name | Description |
|---|---|---|---|
| 1 | 0x00000001 | QUEST_FLAGS_STAY_ALIVE | Player must stay alive during the quest (fail on death). |
| 2 | 0x00000002 | QUEST_FLAGS_PARTY_ACCEPT | All party members receive the quest automatically when one member accepts. |
| 4 | 0x00000004 | QUEST_FLAGS_EXPLORATION | Exploration quest (objectives complete by visiting areas). |
| 8 | 0x00000008 | QUEST_FLAGS_SHARABLE | Quest can be shared with party members. |
| 16 | 0x00000010 | QUEST_FLAGS_HAS_CONDITION | Quest has additional conditions (checked via `conditions` table). |
| 32 | 0x00000020 | QUEST_FLAGS_HIDE_REWARD_POI | Do not show the reward location on the minimap. |
| 64 | 0x00000040 | QUEST_FLAGS_RAID | Quest is a raid quest. |
| 128 | 0x00000080 | QUEST_FLAGS_TBC | TBC-era quest (shown only to TBC+ clients). |
| 256 | 0x00000100 | QUEST_FLAGS_NO_MONEY_FROM_XP | Do not give bonus gold in place of XP at max level. |
| 512 | 0x00000200 | QUEST_FLAGS_HIDDEN_REWARDS | Rewards are hidden until quest completion (shows "?" in reward panel). |
| 1024 | 0x00000400 | QUEST_FLAGS_TRACKING | Auto-complete quest (used for "discovery" quests). |
| 2048 | 0x00000800 | QUEST_FLAGS_DEPRECATE_REPUTATION | Do not apply reputation rewards. |
| 4096 | 0x00001000 | QUEST_FLAGS_DAILY | Quest is a daily quest. Can be completed once per day. Resets at the daily reset time. |
| 8192 | 0x00002000 | QUEST_FLAGS_FLAGS_PVP | Quest enables PvP flag on accept. |
| 32768 | 0x00008000 | QUEST_FLAGS_WEEKLY | Quest is a weekly quest. Resets on weekly reset. |
| 65536 | 0x00010000 | QUEST_FLAGS_AUTOCOMPLETE | Quest autocompletes (no need to return to quest ender). |
| 131072 | 0x00020000 | QUEST_FLAGS_DISPLAY_ITEM_IN_TRACKER | Show the required item icon in the quest tracker. |
| 524288 | 0x00080000 | QUEST_FLAGS_OBJ_TEXT | Use ObjectiveText fields instead of auto-generated text. |
| 1048576 | 0x00100000 | QUEST_FLAGS_AUTO_ACCEPT | Quest is auto-accepted when the player meets the NPC (no accept dialog). |

### Flag Usage Examples

```python
# A daily quest that can be shared with party members
flags = 4096 | 8   # QUEST_FLAGS_DAILY | QUEST_FLAGS_SHARABLE
# flags = 4104

# A raid quest with hidden rewards
flags = 64 | 512   # QUEST_FLAGS_RAID | QUEST_FLAGS_HIDDEN_REWARDS
# flags = 576

# An auto-accept daily with custom objective text
flags = 4096 | 1048576 | 524288
# QUEST_FLAGS_DAILY | QUEST_FLAGS_AUTO_ACCEPT | QUEST_FLAGS_OBJ_TEXT
# flags = 1572864
```

---

## Step 3: Understand the quest_template_addon Table

The `quest_template_addon` table holds secondary quest data that controls chaining,
class/skill restrictions, and special behaviors. Every quest should have a corresponding
row in this table, even if all values are defaults.

### Complete quest_template_addon Column Reference

| Column | Type | Default | Description |
|---|---|---|---|
| `ID` | int | -- | Quest ID. Must match the `ID` in `quest_template`. |
| `MaxLevel` | int | 0 | Maximum player level to accept the quest. `0` means no maximum. Useful for starter zone quests that should not appear for high-level characters. |
| `AllowableClasses` | int | 0 | Bitmask of classes allowed to accept the quest. `0` means all classes. See class mask values below. |
| `SourceSpellID` | int | 0 | Spell ID that the quest provides as a source (the spell starts the quest). |
| `PrevQuestID` | int | 0 | Quest ID that must be completed before this quest becomes available. See the quest chaining section in [Create Quest Chain](create_quest_chain.md). |
| `NextQuestID` | int | 0 | Quest ID that should be made available after this quest is completed. This is a server-side link -- use `RewardNextQuest` in `quest_template` for the popup dialog. |
| `ExclusiveGroup` | int | 0 | Used for branching quest chains. Quests with the same `ExclusiveGroup` value are mutually exclusive -- completing one makes the others unavailable. See [Create Quest Chain](create_quest_chain.md). |
| `RewardMailTemplateID` | int | 0 | Mail template ID sent to the player after quest completion. |
| `RewardMailDelay` | int | 0 | Delay in seconds before sending the reward mail. |
| `RequiredSkillID` | int | 0 | Skill ID required to accept the quest (e.g., Mining=186, Herbalism=182). |
| `RequiredSkillPoints` | int | 0 | Minimum skill level in the required skill. |
| `RequiredMinRepFaction` | int | 0 | Faction ID that the player must have minimum reputation with. |
| `RequiredMaxRepFaction` | int | 0 | Faction ID that the player must be below a maximum reputation with. |
| `RequiredMinRepValue` | int | 0 | Minimum reputation value required. |
| `RequiredMaxRepValue` | int | 0 | Maximum reputation value allowed. |
| `ProvidedItemCount` | int | 0 | Number of `StartItem` provided (used when the quest gives an item on accept). |
| `SpecialFlags` | int | 0 | Bitmask for special behaviors. See SpecialFlags reference below. |

### SpecialFlags Values

| Value | Name | Description |
|---|---|---|
| 0 | NONE | No special behavior. |
| 1 | REPEATABLE | Quest can be repeated (used with `QUEST_FLAGS_DAILY` or `QUEST_FLAGS_WEEKLY`). Required for daily/weekly quests. |
| 2 | EXPLORATION_OR_EVENT | Quest objectives are completed by exploration or scripted events, not kill/collect. |
| 4 | AUTO_ACCEPT | Quest is automatically accepted (alternative to `QUEST_FLAGS_AUTO_ACCEPT`). |
| 8 | DF_OR_MONTHLY | Dungeon Finder quest or monthly quest. |

### Class Mask Values

| Value | Class |
|---|---|
| 1 | Warrior |
| 2 | Paladin |
| 4 | Hunter |
| 8 | Rogue |
| 16 | Priest |
| 32 | Death Knight |
| 64 | Shaman |
| 128 | Mage |
| 256 | Warlock |
| 512 | (unused) |
| 1024 | Druid |

Example: `AllowableClasses = 1 | 2 | 32` (Warrior, Paladin, Death Knight only) = `35`.

### Race Mask Values

| Value | Race |
|---|---|
| 1 | Human |
| 2 | Orc |
| 4 | Dwarf |
| 8 | Night Elf |
| 16 | Undead |
| 32 | Tauren |
| 64 | Gnome |
| 128 | Troll |
| 512 | Blood Elf |
| 1024 | Draenei |

Alliance mask: `1 | 4 | 8 | 64 | 1024` = `1101`.
Horde mask: `2 | 16 | 32 | 128 | 512` = `690`.

---

## Step 4: Understand NPC Assignment Tables

Quests are connected to NPCs through two link tables. Without these entries, no NPC in
the game will offer or accept your quest.

### creature_queststarter

| Column | Type | Description |
|---|---|---|
| `id` | int | Creature template entry ID (the NPC that offers the quest). Must match an entry in `creature_template`. |
| `quest` | int | Quest ID. Must match an `ID` in `quest_template`. |

A single NPC can offer multiple quests by having multiple rows with the same `id` but
different `quest` values.

### creature_questender

| Column | Type | Description |
|---|---|---|
| `id` | int | Creature template entry ID (the NPC that completes the quest). |
| `quest` | int | Quest ID to complete. |

**Important:** The quest giver and quest ender can be the same NPC or different NPCs.
For "Kill 10 Rats" style quests, the same NPC typically gives and completes the quest.
For breadcrumb or travel quests, the ender is usually a different NPC in a different zone.

---

## Step 5: Set Up the Python Script

Create a new Python file for your quest generation script. The `SQLGenerator` class
manages all entry ID allocation and cross-reference validation.

```python
#!/usr/bin/env python3
"""Generate a complete 'Kill 10 Rats' quest with NPCs and reward items."""

import os
import sys

# Add the pywowlib root to the Python path if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator
```

---

## Step 6: Complete Code Example -- "Kill 10 Rats" Quest

The following script creates a fully functional quest with:
- A quest-giver NPC ("Farmer Dalton")
- A quest-ender NPC (the same NPC)
- Kill objective (10 rats)
- Rat creature spawns
- A reward item ("Rat-Catcher's Gloves")
- Gold and XP rewards

```python
#!/usr/bin/env python3
"""
Complete example: Generate a 'Kill 10 Rats' quest.

Creates all required SQL:
  - creature_template (NPC + Rats)
  - item_template (reward item)
  - quest_template + quest_template_addon
  - creature_queststarter + creature_questender
  - creature (spawn positions)

Output: output/kill_rats_quest.sql
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator


def main():
    # ---------------------------------------------------------------
    # 1. Initialize the SQL generator
    # ---------------------------------------------------------------
    # start_entry=90000 means all auto-allocated IDs begin at 90000.
    # map_id=0 is Eastern Kingdoms, zone_id=12 is Elwynn Forest.
    gen = SQLGenerator(start_entry=90000, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 2. Create the reward item
    # ---------------------------------------------------------------
    # The reward item must be created BEFORE the quest so that the
    # cross-reference validator can verify it exists.
    reward_item_ids = gen.add_items([
        {
            'entry': 90000,
            'name': "Rat-Catcher's Gloves",
            'class': 4,              # Armor
            'subclass': 1,           # Cloth
            'inventory_type': 10,    # Hands
            'quality': 2,            # Uncommon (green)
            'item_level': 15,
            'required_level': 5,
            'displayid': 28467,      # Existing glove model
            'bonding': 1,            # Bind on Pickup
            'sell_price': 250,       # 2 silver 50 copper
            'armor': 18,
            'description': 'These gloves have seen their share of vermin.',
            'stats': [
                {'type': 7, 'value': 4},   # Stamina +4
                {'type': 3, 'value': 3},   # Agility +3
            ],
        },
    ])
    reward_item_entry = reward_item_ids[0]  # 90000

    # ---------------------------------------------------------------
    # 3. Create the quest-giver NPC
    # ---------------------------------------------------------------
    # npcflag=2 means this NPC is a quest giver. The client shows
    # the yellow "!" icon above the NPC.
    npc_ids = gen.add_npcs([
        {
            'entry': 90001,
            'name': 'Farmer Dalton',
            'subname': 'Rat Problems',
            'minlevel': 10,
            'maxlevel': 10,
            'faction': 12,           # Stormwind (Alliance-friendly)
            'npcflag': 2,            # UNIT_NPC_FLAG_QUESTGIVER
            'modelid1': 3262,        # Human male farmer model
            'type': 7,               # Humanoid
            'health_modifier': 1.0,
            'damage_modifier': 1.0,
            'gossip_menu_id': 90001,
            'gossip_text': (
                'These blasted rats are eating through my grain stores! '
                'If you could thin their numbers, I would be most grateful.'
            ),
        },
    ])
    npc_entry = npc_ids[0]  # 90001

    # ---------------------------------------------------------------
    # 4. Create the rat creature
    # ---------------------------------------------------------------
    rat_ids = gen.add_creatures([
        {
            'entry': 90002,
            'name': 'Grain-Fed Rat',
            'minlevel': 5,
            'maxlevel': 7,
            'faction': 14,           # Monster (hostile to all players)
            'type': 1,               # Beast
            'family': 0,             # None
            'modelid1': 1141,        # Rat model
            'health_modifier': 0.5,
            'damage_modifier': 0.5,
            'experience_modifier': 1.0,
            'scale': 1.2,            # Slightly larger than normal
            'ai_name': 'SmartAI',
            'movement_type': 1,      # Random movement within wander range
            'mingold': 5,            # Drops 5 copper minimum
            'maxgold': 15,           # Drops 15 copper maximum
        },
    ])
    rat_entry = rat_ids[0]  # 90002

    # ---------------------------------------------------------------
    # 5. Create the quest
    # ---------------------------------------------------------------
    quest_ids = gen.add_quests([
        {
            'entry': 90003,
            'title': 'A Rat Problem',
            'quest_type': 2,             # Life (standard quest)
            'quest_level': 8,            # Displayed level
            'min_level': 5,              # Minimum level to accept
            'quest_sort': 12,            # Elwynn Forest zone ID
            'quest_info': 0,             # No special icon
            'suggested_group': 0,        # Solo quest

            # Flags: sharable quest
            'flags': 8,                  # QUEST_FLAGS_SHARABLE

            # Objectives
            'required_npc_or_go': [
                (rat_entry, 10),          # Kill 10 Grain-Fed Rats
            ],
            'objective_text': [
                'Grain-Fed Rats slain',   # Custom objective text
            ],

            # Rewards
            'reward_xp_difficulty': 3,    # Moderate XP
            'reward_money': 350,          # 3 silver 50 copper
            'reward_item': [
                (reward_item_entry, 1),   # 1x Rat-Catcher's Gloves
            ],
            'reward_faction': [
                {'id': 72, 'value': 250, 'override': 0},  # +250 Stormwind rep
            ],

            # NPC assignment
            'quest_giver_entry': npc_entry,   # Farmer Dalton gives the quest
            'quest_ender_entry': npc_entry,   # Farmer Dalton completes it too

            # Text
            'log_description': (
                'These rats have been getting into my grain stores and '
                'breeding like... well, like rats! If you could kill ten '
                'of those oversized vermin, I would be forever in your debt.'
                '$B$B'
                'They tend to lurk around the barn and the fields to the south.'
            ),
            'quest_description': (
                'Kill 10 Grain-Fed Rats around Farmer Dalton\'s farm.'
            ),
            'quest_completion_log': (
                'Return to Farmer Dalton when you have dealt with the rats.'
            ),
        },
    ])
    quest_entry = quest_ids[0]  # 90003

    # ---------------------------------------------------------------
    # 6. Spawn the NPC and rats
    # ---------------------------------------------------------------
    # Spawn the quest-giver NPC at a fixed location
    gen.add_spawns([
        {
            'entry': npc_entry,
            'position': (-9460.0, 62.0, 56.0, 3.14),  # Elwynn Forest coords
            'spawntimesecs': 60,     # 1 minute respawn
            'wander_distance': 0,    # Stands still
            'movement_type': 0,      # Idle
        },
    ])

    # Spawn 15 rats in the area (more than the 10 required so players
    # do not have to wait too long for respawns)
    rat_spawns = []
    import random
    random.seed(42)  # Deterministic for reproducibility
    for i in range(15):
        rat_spawns.append({
            'entry': rat_entry,
            'position': (
                -9460.0 + random.uniform(-30, 30),  # X spread
                62.0 + random.uniform(-30, 30),      # Y spread
                56.0,                                 # Z (ground level)
                random.uniform(0, 6.28),              # Random facing
            ),
            'spawntimesecs': 120,     # 2 minute respawn
            'wander_distance': 5.0,   # Wander within 5 yards
            'movement_type': 1,       # Random movement
        })
    gen.add_spawns(rat_spawns)

    # ---------------------------------------------------------------
    # 7. Validate and write output
    # ---------------------------------------------------------------
    # Run cross-reference validation
    result = gen.validate()

    if result['errors']:
        print("ERRORS found during validation:")
        for err in result['errors']:
            print("  [ERROR] {}".format(err))
        sys.exit(1)

    if result['warnings']:
        print("Warnings:")
        for warn in result['warnings']:
            print("  [WARN] {}".format(warn))

    # Write the SQL file
    os.makedirs('output', exist_ok=True)
    output_path = os.path.join('output', 'kill_rats_quest.sql')
    gen.write_sql(output_path)

    print("Quest SQL written to: {}".format(os.path.abspath(output_path)))
    print("Entry IDs used: {} - {}".format(
        gen.start_entry, gen.current_entry - 1))


if __name__ == '__main__':
    main()
```

---

## Step 7: Apply the Generated SQL

After running the script, you will have an `output/kill_rats_quest.sql` file. Apply it
to your AzerothCore database:

```bash
# Using MySQL command line
mysql -u root -p acore_world < output/kill_rats_quest.sql

# Or using the AzerothCore world server console
# .reload quest_template
# .reload creature_template
```

After applying the SQL, either restart the world server or use the `.reload` commands
shown above. Then use the `.npc add 90001` GM command in-game to verify the NPC appears,
or travel to the spawn coordinates.

---

## Step 8: In-Game Verification

Use these GM commands to verify your quest works correctly:

```
.npc info                    -- Target the NPC and verify its entry/flags
.quest add 90003             -- Force-add the quest to your quest log
.quest complete 90003        -- Auto-complete the quest objectives
.quest reward 90003          -- Trigger the reward dialog
.lookup quest rat            -- Search for your quest by name
```

### Verification Checklist

1. The quest-giver NPC shows a yellow `!` icon above its head.
2. Right-clicking the NPC opens the quest accept dialog with correct text.
3. After accepting, the quest tracker shows "0/10 Grain-Fed Rats slain".
4. Killing the rats increments the counter.
5. At 10/10, the quest tracker shows the quest as complete.
6. Returning to the NPC shows a yellow `?` icon.
7. Completing the quest awards the gloves, gold, XP, and reputation.

---

## Common Pitfalls and Troubleshooting

### Quest does not appear on the NPC

| Symptom | Cause | Fix |
|---|---|---|
| NPC has no `!` icon | Missing `creature_queststarter` row | Ensure `quest_giver_entry` is set in the quest definition. |
| NPC has no `!` icon | NPC `npcflag` does not include `2` | Set `npcflag: 2` (UNIT_NPC_FLAG_QUESTGIVER) on the creature. |
| Quest shows but cannot accept | `MinLevel` too high | Lower the `min_level` value or level up your test character. |
| Quest shows but greyed out | `AllowableRaces` or `AllowableClasses` excludes your character | Set to `0` for no restrictions during testing. |

### Kill credit does not count

| Symptom | Cause | Fix |
|---|---|---|
| Kills do not increment counter | Wrong `RequiredNpcOrGo` entry | Verify the entry matches the creature's `entry` in `creature_template`. |
| Counter stuck at 0 | Creature uses `KillCredit1` | The actual creature killed must match or have a KillCredit pointing to the required entry. |
| Negative entry confusion | Trying to use gameobject entry | Gameobject entries must be negative in `RequiredNpcOrGo` (e.g., `-90005`). |

### Rewards not working

| Symptom | Cause | Fix |
|---|---|---|
| No XP rewarded | `RewardXPDifficulty` is 0 | Set to a value between 1-10. |
| No gold rewarded | `RewardMoney` is 0 | Set to the desired copper amount (1 gold = 10000). |
| Reward item missing | Item entry does not exist | Create the item with `add_items()` before referencing it in the quest. |
| "Choose one" section empty | Used `reward_item` instead of `reward_choice_item` | Use `reward_choice_item` for player-selected rewards. |

### Quest text formatting

| Code | Replacement | Example |
|---|---|---|
| `$N` | Player name | "Thank you, $N!" |
| `$C` | Player class | "As a $C, you should know..." |
| `$R` | Player race | "For the glory of the $R people!" |
| `$B` | Line break | "First line.$B$BThird line." |
| `$G male:female;` | Gender-specific text | "Good $G sir:madam;!" |

---

## Cross-References

- **[Create Quest Chain](create_quest_chain.md)** -- Learn how to link multiple quests
  into a sequential chain using `PrevQuestID` and `NextQuestID`.
- **[Add Object Interaction](add_object_interaction.md)** -- Create gameobjects that
  serve as quest objectives using negative `RequiredNpcOrGo` values.
- **[Custom Teleporter](custom_teleporter.md)** -- Build NPC teleporters that could be
  unlocked by quest completion.

---

## Appendix: pywowlib API Quick Reference

### SQLGenerator Constructor

```python
gen = SQLGenerator(
    start_entry=90000,   # Base entry ID for auto-allocation
    map_id=0,            # Default map for spawns (0 = Eastern Kingdoms)
    zone_id=12,          # Default zone for quest sort
)
```

### Quest Definition Dict Keys

```python
quest_def = {
    # Identity (entry is auto-allocated if omitted)
    'entry': 90003,

    # Classification
    'title': 'Quest Name',
    'quest_type': 2,
    'quest_level': 10,
    'min_level': 5,
    'quest_sort': 12,
    'quest_info': 0,
    'suggested_group': 0,
    'flags': 0,
    'time_allowed': 0,
    'allowable_races': 0,

    # Objectives
    'required_npc_or_go': [(creature_entry, count), ...],
    'required_item': [(item_entry, count), ...],
    'objective_text': ['Custom text 1', 'Custom text 2', ...],

    # Rewards
    'reward_xp_difficulty': 3,
    'reward_money': 10000,
    'reward_bonus_money': 0,
    'reward_honor': 0,
    'reward_item': [(item_entry, count), ...],
    'reward_choice_item': [(item_entry, count), ...],
    'reward_faction': [{'id': 72, 'value': 250, 'override': 0}, ...],
    'reward_title': 0,
    'reward_talents': 0,
    'reward_arena_points': 0,
    'reward_display_spell': 0,
    'reward_spell': 0,
    'start_item': 0,

    # NPC links
    'quest_giver_entry': 90001,
    'quest_ender_entry': 90001,

    # Chaining (see create_quest_chain.md)
    'prev_quest_id': 0,
    'next_quest_id': 0,
    'exclusive_group': 0,
    'reward_next_quest': 0,

    # Addon fields
    'max_level': 0,
    'allowable_classes': 0,
    'special_flags': 0,
    'source_spell_id': 0,
    'required_skill_id': 0,
    'required_skill_points': 0,
    'required_min_rep_faction': 0,
    'required_min_rep_value': 0,
    'required_max_rep_faction': 0,
    'required_max_rep_value': 0,
    'provided_item_count': 0,
    'reward_mail_template_id': 0,
    'reward_mail_delay': 0,

    # Text
    'log_description': 'Quest log text...',
    'quest_description': 'Objective summary...',
    'quest_completion_log': 'Completion text...',
    'area_description': '',

    # POI
    'poi_continent': 0,
    'poi_x': 0,
    'poi_y': 0,
    'poi_priority': 0,
}
```

### Validation

```python
result = gen.validate()
# Returns: {'valid': bool, 'errors': [...], 'warnings': [...]}
```

The validator checks:
- Quest items exist in `item_template`
- Quest givers/enders exist in `creature_template`
- Required NPCs/GOs exist
- Quest chain references exist
- All spawns reference valid creatures
