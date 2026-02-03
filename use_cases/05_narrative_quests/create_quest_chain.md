# Create Quest Chain

| Property | Value |
|---|---|
| **Complexity** | Medium |
| **Client-Side Files** | None |
| **Server-Side Files** | SQL: `quest_template`, `quest_template_addon`, `conditions`, `creature_queststarter`, `creature_questender` |
| **pywowlib APIs** | `SQLGenerator.add_quests()`, `SQLGenerator.add_npcs()`, `SQLGenerator.add_spawns()`, `SQLGenerator.add_items()` |
| **Estimated Time** | 30-60 minutes for a 3-quest chain |

## Overview

A quest chain is a sequence of quests that must be completed in a specific order. Players
cannot accept quest B until they have completed quest A. WoW WotLK 3.3.5a supports three
types of quest chain structures:

1. **Linear chains** -- Quest A leads to Quest B leads to Quest C. This is the most common
   pattern, used for storylines that progress through a zone.

2. **Branching chains** -- After completing Quest A, the player can choose Quest B1 OR
   Quest B2 (but not both). This is used for faction-choice quests and "pick your path"
   storylines.

3. **Prerequisite webs** -- Quest C requires both Quest A AND Quest B to be completed
   (in any order). This is used for "gather allies" style storylines.

All chain logic is controlled by two tables: `quest_template_addon` (for `PrevQuestID`,
`NextQuestID`, and `ExclusiveGroup`) and `conditions` (for complex multi-prerequisite
requirements).

This guide builds a complete 3-quest storyline called "The Shadow in the Mines" as a
worked example, demonstrating linear chaining, breadcrumb quests, and the conditions
table for advanced requirements.

---

## Prerequisites

- Completion of the [Add New Quest](add_new_quest.md) guide.
- Understanding of `quest_template` and `quest_template_addon` table schemas.
- Python 3.8+ with pywowlib available on the Python path.
- An AzerothCore 3.3.5a server for testing.

---

## Step 1: Understand Quest Chaining Fields

Quest chains in AzerothCore are driven by three fields in the `quest_template_addon`
table and one field in `quest_template` itself.

### PrevQuestID (quest_template_addon)

| Column | Type | Description |
|---|---|---|
| `PrevQuestID` | int | The quest that must be completed before this quest becomes available. |

**Behavior rules:**

- **Positive value** (e.g., `90001`): The quest with this ID must be **rewarded** (fully
  completed and turned in) before the current quest appears. This is the standard
  "do quest A first" mechanic.

- **Negative value** (e.g., `-90001`): The quest with this absolute ID must be **active**
  (accepted and in the player's quest log) for the current quest to be available. This is
  used for quests that chain while a parent quest is still in progress -- for example,
  bonus objectives that appear only while on a main quest.

- **Zero** (default): No prerequisite. The quest is always available (subject to level and
  other requirements).

### NextQuestID (quest_template_addon)

| Column | Type | Description |
|---|---|---|
| `NextQuestID` | int | The quest that becomes available after this quest is completed. |

**Behavior rules:**

- **Positive value**: After completing this quest, the referenced quest becomes available
  on its designated quest giver. This is the server-side chain link.

- **Negative value**: This quest becomes unavailable once the referenced quest is accepted.
  This is used for breadcrumb quests -- a quest that directs you to another quest giver,
  and should disappear once you have found the destination quest on your own.

- **Zero** (default): No automatic follow-up.

### RewardNextQuest (quest_template)

| Column | Type | Description |
|---|---|---|
| `RewardNextQuest` | int | Quest ID to immediately offer upon completion of the current quest. |

This is different from `NextQuestID`. While `NextQuestID` simply makes the next quest
available on its NPC, `RewardNextQuest` causes the quest accept dialog for the next quest
to pop up immediately when the player turns in the current quest. This creates a seamless
"one quest flows into the next" experience without the player needing to close a window
and click the NPC again.

**When to use each:**

| Scenario | Use |
|---|---|
| Same NPC, immediate continuation | `RewardNextQuest` in `quest_template` |
| Same or different NPC, available when ready | `NextQuestID` in `quest_template_addon` |
| Different NPC, player must travel | `NextQuestID` only (no popup) |

### ExclusiveGroup (quest_template_addon)

| Column | Type | Description |
|---|---|---|
| `ExclusiveGroup` | int | Groups mutually exclusive quests together. |

**Behavior rules:**

- **Positive value**: All quests with the same `ExclusiveGroup` value are mutually
  exclusive. Once one quest in the group is accepted, the others become unavailable.
  Once one is completed, the others are permanently locked out.

- **Negative value**: All quests with the same `ExclusiveGroup` (absolute value) must ALL
  be completed before the chain can progress. This creates an "AND" requirement --
  "complete quest A AND quest B before quest C becomes available."

- **Zero** (default): No exclusivity grouping.

**Example -- branching path:**
```
Quest A (PrevQuestID=0)
   |
   +-- Quest B1 (PrevQuestID=A, ExclusiveGroup=1)  -- Player picks this OR
   +-- Quest B2 (PrevQuestID=A, ExclusiveGroup=1)  -- Player picks this
   |
   +-- Quest C  (PrevQuestID=B1 or B2 via conditions)
```

**Example -- convergence (all required):**
```
Quest A1 (ExclusiveGroup=-1)  -- Must complete BOTH
Quest A2 (ExclusiveGroup=-1)  -- Must complete BOTH
   |
   +-- Quest B (PrevQuestID=A1, requires A2 via conditions)
```

---

## Step 2: Understand the conditions Table

For complex prerequisite logic that goes beyond simple linear chaining, AzerothCore uses
the `conditions` table. This is a general-purpose condition system used by quests, gossip
menus, loot, and many other systems.

### conditions Table Schema

| Column | Type | Description |
|---|---|---|
| `SourceTypeOrReferenceId` | int | What system is being conditioned. For quest availability: `19` (CONDITION_SOURCE_TYPE_QUEST_AVAILABLE). For gossip menu options: `15`. |
| `SourceGroup` | int | Context-dependent. For quest availability: `0`. For gossip menu: `MenuID`. |
| `SourceEntry` | int | The entity being conditioned. For quest availability: the quest ID. |
| `SourceId` | int | Usually `0`. |
| `ElseGroup` | int | OR-group index. Conditions within the same `ElseGroup` are combined with AND. Different `ElseGroup` values create OR branches. |
| `ConditionTypeOrReference` | int | The type of condition to check. See condition types below. |
| `ConditionTarget` | int | Usually `0` (the player). |
| `ConditionValue1` | int | First condition parameter (meaning depends on type). |
| `ConditionValue2` | int | Second condition parameter. |
| `ConditionValue3` | int | Third condition parameter. |
| `NegativeCondition` | int | `0` = normal, `1` = inverted (NOT). |
| `ErrorType` | int | Error message type shown when condition fails. `0` = no message. |
| `ErrorTextId` | int | Broadcast text ID for custom error message. |
| `ScriptName` | string | Script hook name (rarely used). |
| `Comment` | string | Human-readable comment describing this condition. |

### SourceTypeOrReferenceId Values (Common)

| Value | Name | SourceGroup | SourceEntry | Use Case |
|---|---|---|---|---|
| 15 | CONDITION_SOURCE_TYPE_GOSSIP_MENU_OPTION | MenuID | OptionIndex | Control when gossip options appear. |
| 19 | CONDITION_SOURCE_TYPE_QUEST_AVAILABLE | 0 | Quest ID | Control when a quest is available to accept. |
| 20 | CONDITION_SOURCE_TYPE_VEHICLE_SPELL | 0 | Spell ID | Vehicle spell availability. |
| 26 | CONDITION_SOURCE_TYPE_QUEST_SHOW_MARK | 0 | Quest ID | Control when the `!` or `?` icon shows on the NPC. |

### ConditionTypeOrReference Values (Common)

| Value | Name | Value1 | Value2 | Value3 | Description |
|---|---|---|---|---|---|
| 5 | CONDITION_REPUTATION_RANK | Faction ID | Rank mask | 0 | Player has reputation rank. Rank mask: 1=Hated, 2=Hostile, 4=Unfriendly, 8=Neutral, 16=Friendly, 32=Honored, 64=Revered, 128=Exalted. |
| 8 | CONDITION_QUESTREWARDED | Quest ID | 0 | 0 | Player has completed (been rewarded for) the specified quest. |
| 9 | CONDITION_QUESTTAKEN | Quest ID | 0 | 0 | Player currently has the quest in their quest log. |
| 12 | CONDITION_ACTIVE_EVENT | Event ID | 0 | 0 | A world event is currently active. |
| 14 | CONDITION_QUEST_NONE | Quest ID | 0 | 0 | Player has NOT taken or completed this quest. |
| 15 | CONDITION_CLASS | Class mask | 0 | 0 | Player is one of the specified classes. |
| 16 | CONDITION_RACE | Race mask | 0 | 0 | Player is one of the specified races. |
| 17 | CONDITION_ACHIEVEMENT | Achievement ID | 0 | 0 | Player has earned the achievement. |
| 23 | CONDITION_ITEM_WITH_BANK | Item entry | Count | 0 | Player has at least N of the item (includes bank). |
| 28 | CONDITION_LEVEL | Level | Comparison | 0 | Player level check. Comparison: 0=equal, 1=higher, 2=lower, 3=higher or equal, 4=lower or equal. |
| 47 | CONDITION_QUESTSTATE | Quest ID | State mask | 0 | Quest is in a specific state. State mask: 1=Not taken, 2=Complete, 4=Available, 8=Failed, 16=Rewarded, 32=In progress. |

### ElseGroup Logic

Conditions are evaluated using AND/OR logic:
- All conditions within the **same ElseGroup** are combined with **AND** (all must be true).
- Different **ElseGroup** values are combined with **OR** (any group can be true).

```
ElseGroup=0: ConditionA AND ConditionB
   OR
ElseGroup=1: ConditionC AND ConditionD
```

This means the overall condition passes if `(A AND B) OR (C AND D)`.

---

## Step 3: Understand SpecialFlags for Auto-Accept and Auto-Complete

The `SpecialFlags` field in `quest_template_addon` controls special quest behaviors that
are particularly useful in quest chains.

| Flag | Value | Name | Use in Chains |
|---|---|---|---|
| REPEATABLE | 1 | Quest can be repeated | Daily/weekly quests at the end of a chain. |
| EXPLORATION_OR_EVENT | 2 | Objectives from exploration/events | Discovery quests that complete by entering an area. |
| AUTO_ACCEPT | 4 | Auto-accept on NPC interaction | Seamless chain links -- quest auto-accepts when you talk to the NPC. |
| DF_OR_MONTHLY | 8 | Dungeon Finder or monthly quest | Used for dungeon finder daily quests. |

**Auto-accept chain pattern:** When `SpecialFlags = 4`, the quest is automatically
accepted when the player interacts with the quest giver. Combined with `RewardNextQuest`,
this creates a seamless experience where turning in quest A automatically starts quest B
without any extra clicks.

---

## Step 4: Understand Breadcrumb Quests

A breadcrumb quest is a quest that directs the player to a new area or NPC but should
disappear once the player reaches the destination and picks up the "real" quest on their
own.

**Implementation:**

1. The breadcrumb quest has `NextQuestID` set to a **negative** value of the destination
   quest. For example, if the destination quest is `90010`, set `NextQuestID = -90010`.
2. The destination quest has `PrevQuestID = 0` (it is available independently).
3. When the player accepts the destination quest directly, the breadcrumb quest is
   automatically removed from their quest log.

**Example flow:**

```
NPC in Goldshire offers: "Go talk to Marshal Dughan in town" (breadcrumb)
   |
   v
Player can EITHER:
  (a) Follow the breadcrumb, complete it, and then get the real quest
  (b) Walk to Marshal Dughan directly and accept the real quest
      -> The breadcrumb auto-abandons
```

**Python implementation:**

```python
# Breadcrumb quest
breadcrumb = {
    'entry': 90010,
    'title': 'Trouble in the Mines',
    'next_quest_id': -90011,    # Negative = breadcrumb behavior
    'quest_giver_entry': 90001,
    'quest_ender_entry': 90002, # Different NPC at the destination
    # ... other fields ...
}

# Destination quest (available independently)
destination = {
    'entry': 90011,
    'title': 'Into the Depths',
    'prev_quest_id': 0,         # No hard prerequisite
    'quest_giver_entry': 90002,
    # ... other fields ...
}
```

---

## Step 5: Design the Quest Chain

Before writing code, plan the chain structure on paper. For this guide, we will build
"The Shadow in the Mines" -- a 3-quest storyline in Elwynn Forest.

### Chain Structure

```
Quest 1: "Strange Noises"
   NPC: Miner Grumbold (at mine entrance)
   Objective: Investigate 3 strange mushrooms in the mine (gameobject interaction)
   Reward: 5 silver, XP
   |
   v (RewardNextQuest -> immediate popup)
Quest 2: "The Source of Corruption"
   NPC: Miner Grumbold (same NPC, immediate follow-up)
   Objective: Kill 8 Corrupted Spiders deep in the mine
   Reward: 15 silver, XP, choice of 2 items
   |
   v (NextQuestID -> available on different NPC)
Quest 3: "Report to Captain Halford"
   NPC: Captain Halford (in town)
   Objective: Deliver Grumbold's Report (start item)
   Reward: 25 silver, XP, guaranteed reward item, +350 Stormwind reputation
```

### Entry ID Plan

| Entity | Entry | Type |
|---|---|---|
| Miner Grumbold (NPC) | 90100 | creature_template |
| Captain Halford (NPC) | 90101 | creature_template |
| Corrupted Spider | 90102 | creature_template |
| Grumbold's Report (item) | 90103 | item_template |
| Miner's Pickaxe (choice reward) | 90104 | item_template |
| Spider-Silk Cloak (choice reward) | 90105 | item_template |
| Halford's Commendation (reward) | 90106 | item_template |
| Quest 1: Strange Noises | 90107 | quest_template |
| Quest 2: The Source of Corruption | 90108 | quest_template |
| Quest 3: Report to Captain Halford | 90109 | quest_template |

---

## Step 6: Complete Code Example -- 3-Quest Storyline

```python
#!/usr/bin/env python3
"""
Complete example: Generate a 3-quest chain -- "The Shadow in the Mines".

Demonstrates:
  - Linear quest chaining with PrevQuestID/NextQuestID
  - RewardNextQuest for immediate follow-up popup
  - Start items (quest items provided on accept)
  - Reward choice items (pick one of N)
  - Guaranteed reward items
  - Reputation rewards
  - Cross-reference validation

Output: output/shadow_mines_chain.sql
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator


def main():
    # ---------------------------------------------------------------
    # 1. Initialize
    # ---------------------------------------------------------------
    gen = SQLGenerator(start_entry=90100, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 2. Create items
    # ---------------------------------------------------------------
    # Start item for Quest 3 (delivery quest)
    gen.add_items([
        {
            'entry': 90103,
            'name': "Grumbold's Report",
            'class': 12,             # Quest item
            'subclass': 0,
            'quality': 1,            # Common (white)
            'bonding': 4,            # Quest Item binding
            'max_count': 1,
            'stackable': 1,
            'description': 'A hastily scrawled report about corruption in the mines.',
            'flags': 0,
            'start_quest': 0,        # Not a quest-starting item
        },
    ])

    # Choice rewards for Quest 2
    gen.add_items([
        {
            'entry': 90104,
            'name': "Miner's Pickaxe",
            'class': 2,              # Weapon
            'subclass': 0,           # One-Handed Axe
            'inventory_type': 13,    # One-Hand
            'quality': 2,            # Uncommon (green)
            'item_level': 15,
            'required_level': 8,
            'displayid': 14028,
            'bonding': 1,
            'sell_price': 500,
            'dmg_min1': 8.0,
            'dmg_max1': 16.0,
            'delay': 2200,
            'stats': [
                {'type': 7, 'value': 3},   # Stamina +3
            ],
        },
        {
            'entry': 90105,
            'name': 'Spider-Silk Cloak',
            'class': 4,              # Armor
            'subclass': 1,           # Cloth
            'inventory_type': 16,    # Cloak
            'quality': 2,            # Uncommon (green)
            'item_level': 15,
            'required_level': 8,
            'displayid': 25041,
            'bonding': 1,
            'sell_price': 450,
            'armor': 12,
            'stats': [
                {'type': 5, 'value': 3},   # Intellect +3
                {'type': 6, 'value': 2},   # Spirit +2
            ],
        },
    ])

    # Guaranteed reward for Quest 3
    gen.add_items([
        {
            'entry': 90106,
            'name': "Halford's Commendation",
            'class': 12,             # Quest item (trinket-style token)
            'subclass': 0,
            'quality': 2,            # Uncommon
            'item_level': 15,
            'required_level': 8,
            'bonding': 1,
            'description': 'A commendation for service to Stormwind.',
        },
    ])

    # ---------------------------------------------------------------
    # 3. Create NPCs
    # ---------------------------------------------------------------
    gen.add_npcs([
        {
            'entry': 90100,
            'name': 'Miner Grumbold',
            'subname': 'Fargodeep Mine',
            'minlevel': 12,
            'maxlevel': 12,
            'faction': 12,           # Stormwind
            'npcflag': 2,            # Quest giver
            'modelid1': 3253,        # Dwarf male model
            'type': 7,               # Humanoid
            'health_modifier': 1.0,
            'gossip_menu_id': 90100,
            'gossip_text': (
                'Something foul is creeping through these tunnels. '
                'I can feel it in my bones... and smell it on the air.'
            ),
        },
        {
            'entry': 90101,
            'name': 'Captain Halford',
            'subname': 'Stormwind Guard',
            'minlevel': 15,
            'maxlevel': 15,
            'faction': 12,           # Stormwind
            'npcflag': 2,            # Quest giver
            'modelid1': 3468,        # Human male guard model
            'type': 7,               # Humanoid
            'health_modifier': 1.5,
            'gossip_menu_id': 90101,
            'gossip_text': (
                'At ease, citizen. What business brings you to the garrison?'
            ),
        },
    ])

    # ---------------------------------------------------------------
    # 4. Create hostile creatures
    # ---------------------------------------------------------------
    gen.add_creatures([
        {
            'entry': 90102,
            'name': 'Corrupted Spider',
            'minlevel': 8,
            'maxlevel': 10,
            'faction': 14,           # Monster (hostile)
            'type': 1,               # Beast
            'modelid1': 2036,        # Spider model
            'health_modifier': 0.8,
            'damage_modifier': 0.7,
            'experience_modifier': 1.0,
            'scale': 1.3,
            'ai_name': 'SmartAI',
            'movement_type': 1,
            'mingold': 8,
            'maxgold': 20,
        },
    ])

    # ---------------------------------------------------------------
    # 5. Create the quest chain
    # ---------------------------------------------------------------
    # QUEST 1: Strange Noises (first in chain)
    gen.add_quests([
        {
            'entry': 90107,
            'title': 'Strange Noises',
            'quest_type': 2,
            'quest_level': 9,
            'min_level': 6,
            'quest_sort': 12,            # Elwynn Forest
            'flags': 8,                  # Sharable

            # No kill objectives -- this quest uses exploration/event completion.
            # In practice, you would use gameobject interaction for the mushrooms.
            # For simplicity, we use SpecialFlags=2 (exploration/event).
            'required_npc_or_go': [],

            # Rewards
            'reward_xp_difficulty': 2,
            'reward_money': 500,         # 5 silver

            # THIS IS THE KEY CHAIN LINK:
            # When the player completes Quest 1, Quest 2 immediately pops up.
            'reward_next_quest': 90108,

            # NPC assignment
            'quest_giver_entry': 90100,  # Miner Grumbold
            'quest_ender_entry': 90100,  # Same NPC

            # Addon fields for chaining
            'prev_quest_id': 0,          # No prerequisite (first quest)
            'next_quest_id': 90108,      # Quest 2 becomes available
            'special_flags': 2,          # Exploration/event objectives

            # Text
            'log_description': (
                'I have been hearing strange noises echoing from deep within '
                'the mine. Unnatural sounds, like nothing I have heard in '
                'thirty years of mining.$B$B'
                'Worse still, I have spotted strange glowing mushrooms '
                'growing in the deeper tunnels. They were not there last week.'
                '$B$B'
                'Could you head in and investigate? Check the mushroom '
                'clusters in the three deepest chambers.'
            ),
            'quest_description': (
                'Investigate 3 strange mushroom clusters in Fargodeep Mine.'
            ),
            'quest_completion_log': (
                'Return to Miner Grumbold with your findings.'
            ),
        },
    ])

    # QUEST 2: The Source of Corruption (middle of chain)
    gen.add_quests([
        {
            'entry': 90108,
            'title': 'The Source of Corruption',
            'quest_type': 2,
            'quest_level': 10,
            'min_level': 7,
            'quest_sort': 12,

            'flags': 8,                  # Sharable

            # Kill objective: 8 Corrupted Spiders
            'required_npc_or_go': [
                (90102, 8),              # 8 Corrupted Spiders
            ],
            'objective_text': [
                'Corrupted Spiders slain',
            ],

            # Rewards -- player chooses one item
            'reward_xp_difficulty': 4,
            'reward_money': 1500,        # 15 silver
            'reward_choice_item': [
                (90104, 1),              # Miner's Pickaxe
                (90105, 1),              # Spider-Silk Cloak
            ],

            # Chain links
            'quest_giver_entry': 90100,  # Miner Grumbold
            'quest_ender_entry': 90100,  # Same NPC

            # CHAIN FIELDS:
            'prev_quest_id': 90107,      # Must complete "Strange Noises" first
            'next_quest_id': 90109,      # "Report to Captain Halford" becomes available

            # Text
            'log_description': (
                'Those mushrooms... they are some kind of fungal corruption. '
                'And the spiders -- they are feeding on the stuff! Their eyes '
                'glow with an unnatural purple light.$B$B'
                'We need to thin their numbers before they spread further. '
                'Kill the corrupted ones deeper in the mine. I will prepare '
                'a report for the Stormwind Guard in the meantime.'
            ),
            'quest_description': (
                'Kill 8 Corrupted Spiders in the depths of Fargodeep Mine.'
            ),
            'quest_completion_log': (
                'Return to Miner Grumbold after clearing the corrupted spiders.'
            ),
        },
    ])

    # QUEST 3: Report to Captain Halford (final quest, different NPC)
    gen.add_quests([
        {
            'entry': 90109,
            'title': 'Report to Captain Halford',
            'quest_type': 2,
            'quest_level': 10,
            'min_level': 7,
            'quest_sort': 12,

            'flags': 0,                  # Not sharable (delivery quest)

            # Start item -- provided when the player accepts the quest
            'start_item': 90103,         # Grumbold's Report
            'provided_item_count': 1,

            # Delivery quest: no kill/collect objectives.
            # The player just needs to go talk to Captain Halford.

            # Rewards
            'reward_xp_difficulty': 5,
            'reward_money': 2500,        # 25 silver
            'reward_item': [
                (90106, 1),              # Halford's Commendation
            ],
            'reward_faction': [
                {'id': 72, 'value': 350, 'override': 0},  # +350 Stormwind
            ],

            # Chain fields
            'quest_giver_entry': 90100,  # Miner Grumbold gives this quest
            'quest_ender_entry': 90101,  # Captain Halford completes it

            # CHAIN FIELDS:
            'prev_quest_id': 90108,      # Must complete "Source of Corruption"
            'next_quest_id': 0,          # End of chain

            # Text
            'log_description': (
                'This is worse than I thought, $N. Those spiders are just '
                'the beginning -- the corruption runs deep. I have written '
                'everything down in this report.$B$B'
                'Take it to Captain Halford at the Stormwind garrison in '
                'Goldshire. He needs to know what is happening down here '
                'before it spreads to the surface.'
            ),
            'quest_description': (
                'Deliver Grumbold\'s Report to Captain Halford in Goldshire.'
            ),
            'quest_completion_log': (
                'Speak with Captain Halford to deliver the report.'
            ),
        },
    ])

    # ---------------------------------------------------------------
    # 6. Spawn entities
    # ---------------------------------------------------------------
    # Miner Grumbold at the mine entrance
    gen.add_spawns([
        {
            'entry': 90100,
            'position': (-9320.0, -110.0, 62.0, 1.57),
            'spawntimesecs': 60,
            'wander_distance': 0,
            'movement_type': 0,
        },
    ])

    # Captain Halford in Goldshire
    gen.add_spawns([
        {
            'entry': 90101,
            'position': (-9460.0, 60.0, 56.0, 0.5),
            'spawntimesecs': 60,
            'wander_distance': 0,
            'movement_type': 0,
        },
    ])

    # Corrupted Spiders in the mine (12 spawns for 8-kill objective)
    import random
    random.seed(123)
    spider_spawns = []
    for i in range(12):
        spider_spawns.append({
            'entry': 90102,
            'position': (
                -9320.0 + random.uniform(-40, 40),
                -110.0 + random.uniform(-40, 40),
                62.0 + random.uniform(-5, 0),
                random.uniform(0, 6.28),
            ),
            'spawntimesecs': 180,
            'wander_distance': 8.0,
            'movement_type': 1,
        })
    gen.add_spawns(spider_spawns)

    # ---------------------------------------------------------------
    # 7. Validate and write
    # ---------------------------------------------------------------
    result = gen.validate()

    if result['errors']:
        print("ERRORS:")
        for err in result['errors']:
            print("  [ERROR] {}".format(err))
        sys.exit(1)

    if result['warnings']:
        print("Warnings:")
        for warn in result['warnings']:
            print("  [WARN] {}".format(warn))

    os.makedirs('output', exist_ok=True)
    output_path = os.path.join('output', 'shadow_mines_chain.sql')
    gen.write_sql(output_path)

    print("Quest chain SQL written to: {}".format(os.path.abspath(output_path)))
    print("Entry IDs used: {} - {}".format(
        gen.start_entry, gen.current_entry - 1))
    print()
    print("Chain structure:")
    print("  Quest 1: Strange Noises (90107)")
    print("    -> immediate popup ->")
    print("  Quest 2: The Source of Corruption (90108)")
    print("    -> available on NPC ->")
    print("  Quest 3: Report to Captain Halford (90109)")


if __name__ == '__main__':
    main()
```

---

## Step 7: Advanced -- Adding conditions Table Entries

The pywowlib `SQLGenerator` does not have a dedicated `add_conditions()` convenience
method, but you can add raw SQL through the builder system. For complex quest chains that
require multiple prerequisites, you can write conditions SQL manually.

### Example: Quest C requires BOTH Quest A and Quest B

Suppose you want Quest 90110 to appear only after both Quest 90107 AND Quest 90108 are
completed. The `PrevQuestID` field can only reference a single quest, so you need the
`conditions` table.

```python
from world_builder.sql_generator import BaseBuilder

# After creating your SQLGenerator instance as `gen`:
helper = BaseBuilder(gen)

# Add condition: Quest 90110 requires Quest 90107 to be rewarded
cond_cols = [
    'SourceTypeOrReferenceId', 'SourceGroup', 'SourceEntry', 'SourceId',
    'ElseGroup', 'ConditionTypeOrReference', 'ConditionTarget',
    'ConditionValue1', 'ConditionValue2', 'ConditionValue3',
    'NegativeCondition', 'ErrorType', 'ErrorTextId',
    'ScriptName', 'Comment',
]

cond_rows = [
    # Condition 1: Player has been rewarded for Quest 90107
    [
        19,        # CONDITION_SOURCE_TYPE_QUEST_AVAILABLE
        0,         # SourceGroup (0 for quest availability)
        90110,     # SourceEntry: the quest being conditioned
        0,         # SourceId
        0,         # ElseGroup: group 0 (AND with other group-0 conditions)
        8,         # CONDITION_QUESTREWARDED
        0,         # ConditionTarget: player
        90107,     # ConditionValue1: quest that must be rewarded
        0,         # ConditionValue2
        0,         # ConditionValue3
        0,         # NegativeCondition: not inverted
        0,         # ErrorType
        0,         # ErrorTextId
        '',        # ScriptName
        'Quest 90110 requires Quest 90107 (Strange Noises) completed',
    ],
    # Condition 2: Player has been rewarded for Quest 90108
    [
        19,        # CONDITION_SOURCE_TYPE_QUEST_AVAILABLE
        0,
        90110,     # Same quest being conditioned
        0,
        0,         # ElseGroup: ALSO group 0 -> AND with condition 1
        8,         # CONDITION_QUESTREWARDED
        0,
        90108,     # Quest that must be rewarded
        0,
        0,
        0,
        0,
        0,
        '',
        'Quest 90110 requires Quest 90108 (Source of Corruption) completed',
    ],
]

sql = helper.format_insert('conditions', cond_cols, cond_rows,
                           comment='-- Conditions: Quest 90110 prerequisites')
helper.add_sql('conditions', sql)
```

### Example: Reputation-gated quest

```python
# Quest 90111 requires Honored reputation with Stormwind (faction 72)
cond_rows = [
    [
        19,        # CONDITION_SOURCE_TYPE_QUEST_AVAILABLE
        0, 90111, 0,
        0,         # ElseGroup
        5,         # CONDITION_REPUTATION_RANK
        0,         # ConditionTarget: player
        72,        # ConditionValue1: Stormwind faction ID
        32,        # ConditionValue2: rank mask (32 = Honored)
        0,
        0, 0, 0, '',
        'Quest 90111 requires Honored with Stormwind',
    ],
]
```

### Example: Class-specific quest with OR logic

```python
# Quest 90112 available to Warriors (class 1) OR Paladins (class 2)
cond_rows = [
    # ElseGroup 0: Player is a Warrior
    [
        19, 0, 90112, 0,
        0,         # ElseGroup 0
        15,        # CONDITION_CLASS
        0,
        1,         # Warrior class mask
        0, 0, 0, 0, 0, '',
        'Quest 90112 available to Warriors',
    ],
    # ElseGroup 1: Player is a Paladin
    [
        19, 0, 90112, 0,
        1,         # ElseGroup 1 (OR with group 0)
        15,        # CONDITION_CLASS
        0,
        2,         # Paladin class mask
        0, 0, 0, 0, 0, '',
        'Quest 90112 available to Paladins',
    ],
]
```

---

## Step 8: Advanced Chain Patterns

### Pattern 1: Branching Path (Choose One)

The player completes Quest A, then chooses between Quest B1 and Quest B2.

```python
# Quest B1 and B2 share the same ExclusiveGroup
quest_b1 = {
    'entry': 90120,
    'title': 'The Path of Light',
    'prev_quest_id': 90119,      # Must complete Quest A
    'exclusive_group': 1,        # Same group as B2
    # ... other fields ...
}

quest_b2 = {
    'entry': 90121,
    'title': 'The Path of Shadow',
    'prev_quest_id': 90119,      # Must complete Quest A
    'exclusive_group': 1,        # Same group as B1
    # ... other fields ...
}

# Once the player accepts B1, B2 becomes unavailable (and vice versa).
```

### Pattern 2: Converging Path (Complete All)

Multiple quests must all be completed before the next quest appears.

```python
# Quest A1 and A2 must BOTH be completed before Quest B appears.
quest_a1 = {
    'entry': 90130,
    'title': 'Gather the Ore',
    'exclusive_group': -1,       # Negative = ALL in group required
    'next_quest_id': 90132,
    # ... other fields ...
}

quest_a2 = {
    'entry': 90131,
    'title': 'Collect the Timber',
    'exclusive_group': -1,       # Same negative group
    'next_quest_id': 90132,
    # ... other fields ...
}

quest_b = {
    'entry': 90132,
    'title': 'Build the Watchtower',
    'prev_quest_id': 90130,      # References one of the prerequisite quests
    # The ExclusiveGroup=-1 on A1 and A2 ensures BOTH must be done.
    # Additionally, use the conditions table to enforce A2 completion.
}
```

### Pattern 3: Daily Quest at End of Chain

```python
quest_daily = {
    'entry': 90140,
    'title': 'Daily Spider Cleanup',
    'prev_quest_id': 90109,      # Must complete the full chain first
    'flags': 4096 | 8,           # DAILY | SHARABLE
    'special_flags': 1,          # REPEATABLE
    'required_npc_or_go': [
        (90102, 5),              # Kill 5 Corrupted Spiders
    ],
    'reward_money': 5000,        # 50 silver
    'reward_xp_difficulty': 3,
    # ... other fields ...
}
```

### Pattern 4: Breadcrumb with Auto-Abandon

```python
breadcrumb = {
    'entry': 90150,
    'title': 'Rumors of Corruption',
    'next_quest_id': -90107,     # Negative = auto-abandon if player gets 90107
    'quest_giver_entry': 90200,  # Some NPC in Stormwind
    'quest_ender_entry': 90100,  # Miner Grumbold
    'log_description': (
        'I have heard reports of strange activity in the Fargodeep Mine. '
        'You should speak with Miner Grumbold at the mine entrance.'
    ),
    'quest_description': (
        'Speak with Miner Grumbold at the Fargodeep Mine.'
    ),
}
```

---

## Step 9: Testing the Quest Chain

After applying the generated SQL to your database, test the chain thoroughly.

### Test Sequence

1. **Log in as a character that meets all level requirements.**

2. **Verify Quest 1 is available:**
   ```
   .quest add 90107
   ```
   Or find Miner Grumbold and check for the yellow `!` icon.

3. **Complete Quest 1:**
   ```
   .quest complete 90107
   ```
   Turn it in and verify Quest 2 pops up immediately (via `RewardNextQuest`).

4. **Verify Quest 2 cannot be accessed without Quest 1:**
   ```
   .quest remove 90107
   .quest remove 90108
   ```
   Reset both quests, then try to accept Quest 2 directly -- it should not appear.

5. **Complete the full chain:**
   ```
   .quest add 90107
   .quest complete 90107
   .quest reward 90107
   .quest complete 90108
   .quest reward 90108
   .quest complete 90109
   .quest reward 90109
   ```

6. **Verify rewards at each step** (items in inventory, gold, reputation).

### GM Commands Quick Reference

| Command | Description |
|---|---|
| `.quest add <id>` | Add quest to log |
| `.quest complete <id>` | Mark objectives complete |
| `.quest reward <id>` | Trigger reward (must be at quest ender) |
| `.quest remove <id>` | Remove quest from log |
| `.quest status <id>` | Show quest state |
| `.lookup quest <name>` | Find quest by name |

---

## Common Pitfalls and Troubleshooting

### Chain does not progress

| Symptom | Cause | Fix |
|---|---|---|
| Quest 2 never appears | `PrevQuestID` wrong | Verify Quest 2's `prev_quest_id` matches Quest 1's entry. |
| Quest 2 never appears | Quest 1 not "rewarded" | The player must turn in Quest 1 (not just complete objectives). Use `.quest reward`. |
| Popup does not show | `RewardNextQuest` missing | Set `reward_next_quest` in `quest_template` for same-NPC chains. |
| All quests available at once | `PrevQuestID` = 0 | Set proper prerequisites for each quest. |

### Branching issues

| Symptom | Cause | Fix |
|---|---|---|
| Both branches available after picking one | `ExclusiveGroup` = 0 | Set the same positive `ExclusiveGroup` value on all branch quests. |
| Neither branch available | `ExclusiveGroup` logic inverted | Use positive values for "pick one" and negative for "complete all." |

### Conditions not working

| Symptom | Cause | Fix |
|---|---|---|
| Quest always available despite conditions | Wrong `SourceTypeOrReferenceId` | Must be `19` for quest availability. |
| Condition blocks all characters | Wrong `ElseGroup` logic | Same ElseGroup = AND. Different ElseGroup = OR. |
| Reputation check fails | Wrong rank mask | Rank masks are bitmasks: Friendly=16, Honored=32. Use OR for "Honored or higher" = `32|64|128`. |

### Breadcrumb issues

| Symptom | Cause | Fix |
|---|---|---|
| Breadcrumb does not auto-abandon | `NextQuestID` not negative | Must be negative (e.g., `-90011`). |
| Destination quest disappears | Destination quest has `PrevQuestID` = breadcrumb | Set destination's `PrevQuestID = 0` so it is independently available. |

---

## Cross-References

- **[Add New Quest](add_new_quest.md)** -- Detailed reference for all `quest_template`
  and `quest_template_addon` fields.
- **[Add Object Interaction](add_object_interaction.md)** -- Create gameobjects as quest
  objectives (the mushroom clusters in Quest 1 could use this).
- **[Custom Teleporter](custom_teleporter.md)** -- Build teleportation NPCs that could
  be unlocked by quest chain completion via conditions.
