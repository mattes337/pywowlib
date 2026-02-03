# Custom Teleporter

| Property | Value |
|---|---|
| **Complexity** | Low-Medium |
| **Client-Side Files** | `AreaTrigger.dbc` (for invisible trigger zones only; NPC teleporters need no client patch) |
| **Server-Side Files** | SQL: `creature_template`, `gossip_menu`, `gossip_menu_option`, `smart_scripts`, `areatrigger_teleport` |
| **pywowlib APIs** | `SQLGenerator.add_npcs()`, `SQLGenerator.add_spawns()`, `SQLGenerator.add_smartai()` |
| **DBC APIs** | `dbc_injector.register_area_trigger()` (for invisible trigger zones) |
| **Estimated Time** | 15-30 minutes for NPC teleporter; 20-40 minutes for area trigger teleporter |

## Overview

Teleporters are one of the most popular custom additions to private WoW servers. They
allow players to travel instantly between locations -- to a custom mall, a dungeon
entrance, a PvP arena, or between custom zones.

There are two fundamentally different approaches to building teleporters in WotLK 3.3.5a:

1. **NPC-based teleporter** -- A clickable NPC with a gossip menu listing destinations.
   The player right-clicks the NPC, selects a destination from the menu, and is teleported.
   This is the most common approach and requires **no client-side patch**.

2. **Invisible area trigger** -- An invisible zone in the world that automatically
   teleports the player when they walk into it. This is how Blizzard implements dungeon
   entrances and city portals. This approach requires injecting a record into the
   client-side `AreaTrigger.dbc`.

This guide covers both approaches with complete, working code examples.

---

## Prerequisites

- Completion of the [Add New Quest](add_new_quest.md) guide (for understanding creature
  templates and spawns).
- Python 3.8+ with pywowlib available on the Python path.
- An AzerothCore 3.3.5a server for testing.
- For the area trigger approach: access to the client's `DBFilesClient` directory and the
  ability to create a client-side patch (MPQ).

---

## Approach 1: NPC Teleporter with Gossip Menu

This is the simplest and most common teleporter implementation. It uses the standard
AzerothCore gossip system with no core modifications or client patches.

### How It Works

1. A `creature_template` entry defines the NPC with `npcflag = 1` (UNIT_NPC_FLAG_GOSSIP).
2. A `gossip_menu` entry links the NPC to a text display.
3. Multiple `gossip_menu_option` entries define the destination choices.
4. For each destination, a `smart_scripts` entry handles the teleportation action, OR
   an Eluna Lua script handles the gossip selection event.

There are two scripting approaches for the teleportation logic:

- **SmartAI** -- Uses the `smart_scripts` database table. Works on all AzerothCore
  servers. No code files needed.
- **Eluna Lua** -- Uses a `.lua` script file placed in the server's Lua scripts directory.
  More flexible and readable. Requires AzerothCore compiled with Eluna.

---

### Step 1: Understand the Gossip System

The gossip system is how NPCs display dialog menus to players. It consists of three
tables working together.

#### npc_text Table

Stores the text shown in the gossip window body (above the menu options).

| Column | Type | Description |
|---|---|---|
| `ID` | int | Unique text ID. Referenced by `gossip_menu.TextID`. |
| `text0_0` | string | The text displayed in the gossip window. Supports `$N`, `$C`, `$R`, `$B` formatting codes. |
| `BroadcastTextID0` | int | Broadcast text reference (0 if using inline text). |
| `lang0` | int | Language (0 = universal). |
| `Probability0` | float | Probability of this text being chosen (1.0 = always). |

#### gossip_menu Table

Links a gossip menu ID to a text ID. The NPC's `gossip_menu_id` in `creature_template`
points to this table.

| Column | Type | Description |
|---|---|---|
| `MenuID` | int | Menu identifier. Matches `creature_template.gossip_menu_id`. |
| `TextID` | int | References `npc_text.ID`. |

#### gossip_menu_option Table

Defines the clickable options in the gossip menu. Each row is one menu entry.

| Column | Type | Description |
|---|---|---|
| `MenuID` | int | Parent menu ID. Matches `gossip_menu.MenuID`. |
| `OptionID` | int | Option index within this menu (0, 1, 2, ...). |
| `OptionIcon` | int | Icon shown next to the option text. See icon values below. |
| `OptionText` | string | The text of the menu option (e.g., "Teleport to Stormwind"). |
| `OptionBroadcastTextID` | int | Broadcast text ID (0 for inline text). |
| `OptionType` | int | Option type. `1` = gossip (standard), `3` = vendor, `5` = trainer. |
| `OptionNpcFlag` | int | Required NPC flag for this option to appear. `1` = gossip. |
| `ActionMenuID` | int | Sub-menu ID opened when clicking (0 = no sub-menu). |
| `ActionPoiID` | int | Point of interest ID (0 = none). |
| `BoxCoded` | int | If `1`, the player must type "accept" to confirm. |
| `BoxMoney` | int | Money cost in copper (charged when clicking, 0 = free). |
| `BoxText` | string | Confirmation dialog text (shown in popup if BoxCoded or BoxMoney > 0). |
| `BoxBroadcastTextID` | int | Broadcast text for confirmation dialog. |

#### OptionIcon Values

| Value | Icon | Description |
|---|---|---|
| 0 | Chat bubble | Standard gossip option. |
| 1 | Vendor bag | Vendor/shop option. |
| 2 | Taxi | Flight/travel option. Use this for teleport destinations. |
| 3 | Trainer book | Trainer option. |
| 4 | Cogwheel | Interaction/settings. |
| 5 | Cogwheel | Interaction variant. |
| 6 | Money bag | Money-related. |
| 7 | Talk bubble | Speech/chat. |
| 9 | Tabard | Tabard vendor. |
| 10 | Sword | Battle-related. |

---

### Step 2: NPC Teleporter with SmartAI

SmartAI is a database-only scripting system. Teleportation is not directly supported
by SmartAI actions in vanilla AzerothCore, but you can work around this by using
`SMART_ACTION_TELEPORT` (action type 62, available in some AzerothCore forks) or by
casting a teleport spell via `SMART_ACTION_CAST`.

However, the most reliable database-only approach for teleportation uses the
`gossip_menu_option` table with `OptionType = 1` and a C++ `ScriptName` on the creature.
Since this requires core scripting, the practical database-only approach is to use
**Eluna Lua** (see Step 3 below).

For servers with SmartAI teleport action support, here is the pattern:

```python
#!/usr/bin/env python3
"""
NPC Teleporter using SmartAI approach.

NOTE: SMART_ACTION_TELEPORT (action type 62) is available in some AzerothCore
forks. If your server does not support it, use the Eluna Lua approach instead.

This example creates a teleporter NPC with gossip menu options.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator, BaseBuilder


def main():
    gen = SQLGenerator(start_entry=91000, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 1. Create the teleporter NPC
    # ---------------------------------------------------------------
    gen.add_npcs([
        {
            'entry': 91000,
            'name': 'Archmage Teleportus',
            'subname': 'Teleportation Master',
            'minlevel': 80,
            'maxlevel': 80,
            'faction': 35,           # Friendly to all
            'npcflag': 1,            # UNIT_NPC_FLAG_GOSSIP
            'modelid1': 15697,       # Ethereal model
            'type': 7,               # Humanoid
            'health_modifier': 10.0, # Tough (should not die easily)
            'damage_modifier': 0.0,  # Does not attack
            'unit_flags': 2,         # NON_ATTACKABLE
            'flags_extra': 2,        # CREATURE_FLAG_EXTRA_CIVILIAN
            'gossip_menu_id': 91000,
            'gossip_text': (
                'Greetings, traveler. I can transport you to any major '
                'city in the blink of an eye. Where would you like to go?'
            ),

            # Gossip menu options (destinations)
            'gossip_options': [
                {
                    'option_id': 0,
                    'icon': 2,       # Taxi icon
                    'text': 'Teleport me to Stormwind',
                    'type': 1,       # Gossip type
                    'npc_flag': 1,   # Requires gossip flag
                },
                {
                    'option_id': 1,
                    'icon': 2,
                    'text': 'Teleport me to Ironforge',
                    'type': 1,
                    'npc_flag': 1,
                },
                {
                    'option_id': 2,
                    'icon': 2,
                    'text': 'Teleport me to Darnassus',
                    'type': 1,
                    'npc_flag': 1,
                },
                {
                    'option_id': 3,
                    'icon': 2,
                    'text': 'Teleport me to Orgrimmar',
                    'type': 1,
                    'npc_flag': 1,
                },
                {
                    'option_id': 4,
                    'icon': 2,
                    'text': 'Teleport me to Dalaran',
                    'type': 1,
                    'npc_flag': 1,
                },
                {
                    'option_id': 5,
                    'icon': 0,
                    'text': 'Never mind.',
                    'type': 1,
                    'npc_flag': 1,
                },
            ],
        },
    ])

    # ---------------------------------------------------------------
    # 2. Add SmartAI scripts for teleportation
    # ---------------------------------------------------------------
    # SmartAI event 62 = SMART_EVENT_GOSSIP_SELECT
    # SmartAI action 62 = teleport (if supported by your core)
    #
    # event_param1 = MenuID
    # event_param2 = OptionID
    #
    # action_param1 = MapID
    # target_x/y/z/o = destination coordinates

    helper = BaseBuilder(gen)
    smart_cols = [
        'entryorguid', 'source_type', 'id', 'link',
        'event_type', 'event_phase_mask', 'event_chance', 'event_flags',
        'event_param1', 'event_param2', 'event_param3', 'event_param4',
        'event_param5',
        'action_type',
        'action_param1', 'action_param2', 'action_param3',
        'action_param4', 'action_param5', 'action_param6',
        'target_type',
        'target_param1', 'target_param2', 'target_param3', 'target_param4',
        'target_x', 'target_y', 'target_z', 'target_o',
        'comment',
    ]

    # Destination coordinates for each option
    destinations = [
        # (option_id, map_id, x, y, z, o, comment)
        (0, 0, -8833.38, 628.62, 94.0, 0.64, 'Stormwind'),
        (1, 0, -4918.88, -940.41, 501.56, 5.42, 'Ironforge'),
        (2, 1, 9951.52, 2280.32, 1341.39, 1.59, 'Darnassus'),
        (3, 1, 1503.27, -4415.50, 21.55, 0.55, 'Orgrimmar'),
        (4, 571, 5807.77, 588.35, 661.50, 1.66, 'Dalaran'),
    ]

    smart_rows = []
    for script_id, (opt_id, map_id, x, y, z, o, name) in enumerate(destinations):
        smart_rows.append([
            91000,       # entryorguid: NPC entry
            0,           # source_type: SMART_SOURCE_CREATURE
            script_id,   # id: script line number
            0,           # link
            62,          # event_type: SMART_EVENT_GOSSIP_SELECT
            0,           # event_phase_mask
            100,         # event_chance
            0,           # event_flags
            91000,       # event_param1: MenuID
            opt_id,      # event_param2: OptionID
            0, 0, 0,     # event_param3-5
            62,          # action_type: teleport (if supported)
            map_id,      # action_param1: target map
            0, 0, 0, 0, 0,
            1,           # target_type: SMART_TARGET_SELF (acting on invoker)
            0, 0, 0, 0,
            x, y, z, o,  # target coordinates
            'Archmage Teleportus - Gossip Select {} - Teleport to {}'.format(
                opt_id, name),
        ])

    # Close gossip action for "Never mind" option
    smart_rows.append([
        91000, 0, len(destinations), 0,
        62,          # SMART_EVENT_GOSSIP_SELECT
        0, 100, 0,
        91000,       # MenuID
        5,           # OptionID: "Never mind"
        0, 0, 0,
        72,          # action_type: SMART_ACTION_CLOSE_GOSSIP
        0, 0, 0, 0, 0, 0,
        0,           # target_type: none
        0, 0, 0, 0,
        0, 0, 0, 0,
        'Archmage Teleportus - Gossip Select 5 - Close Gossip',
    ])

    sql = helper.format_insert('smart_scripts', smart_cols, smart_rows,
                               comment='-- SmartAI: Archmage Teleportus')
    helper.add_sql('smart_scripts', sql)

    # Set AIName on the creature template to enable SmartAI
    # The NPC was created above; we need to ensure it has ai_name='SmartAI'
    # This is handled by setting 'ai_name': 'SmartAI' in the NPC definition.
    # If not set above, manually update:
    # UPDATE creature_template SET AIName='SmartAI' WHERE entry=91000;

    # ---------------------------------------------------------------
    # 3. Spawn the NPC
    # ---------------------------------------------------------------
    gen.add_spawns([
        {
            'entry': 91000,
            'position': (-8833.0, 630.0, 94.0, 3.14),  # Stormwind
            'spawntimesecs': 60,
            'wander_distance': 0,
            'movement_type': 0,
        },
    ])

    # ---------------------------------------------------------------
    # 4. Write output
    # ---------------------------------------------------------------
    os.makedirs('output', exist_ok=True)
    gen.write_sql(os.path.join('output', 'npc_teleporter_smartai.sql'))
    print("SmartAI NPC teleporter SQL written to output/npc_teleporter_smartai.sql")
    print()
    print("NOTE: If your AzerothCore fork does not support SMART_ACTION_TELEPORT")
    print("(action type 62), use the Eluna Lua approach instead (see Step 3).")


if __name__ == '__main__':
    main()
```

---

### Step 3: NPC Teleporter with Eluna Lua

Eluna Lua is the recommended approach for NPC teleporters because it is universally
supported on AzerothCore servers compiled with Eluna, and the teleportation API is
straightforward and well-documented.

#### Step 3a: Generate the SQL for the NPC

The SQL generation is the same as the SmartAI approach above, but we do NOT add SmartAI
scripts. Instead, we set `script_name` to empty and rely on Eluna to handle the gossip
events.

```python
#!/usr/bin/env python3
"""
NPC Teleporter SQL generation for use with Eluna Lua.

This script generates the SQL for the NPC and gossip menu.
The teleportation logic is handled by a separate Lua script.

Output: output/npc_teleporter_eluna.sql
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator


# ---------------------------------------------------------------
# Define teleport destinations
# ---------------------------------------------------------------
DESTINATIONS = [
    {'name': 'Stormwind',   'map': 0,   'x': -8833.38, 'y': 628.62,   'z': 94.0,    'o': 0.64},
    {'name': 'Ironforge',   'map': 0,   'x': -4918.88, 'y': -940.41,  'z': 501.56,  'o': 5.42},
    {'name': 'Darnassus',   'map': 1,   'x': 9951.52,  'y': 2280.32,  'z': 1341.39, 'o': 1.59},
    {'name': 'Exodar',      'map': 530, 'x': -3965.70, 'y': -11653.6, 'z': -138.84, 'o': 0.85},
    {'name': 'Orgrimmar',   'map': 1,   'x': 1503.27,  'y': -4415.50, 'z': 21.55,   'o': 0.55},
    {'name': 'Thunder Bluff','map': 1,  'x': -1274.45, 'y': 71.85,    'z': 128.16,  'o': 0.56},
    {'name': 'Undercity',   'map': 0,   'x': 1586.48,  'y': 239.56,   'z': -52.15,  'o': 0.05},
    {'name': 'Silvermoon',  'map': 530, 'x': 9473.03,  'y': -7279.67, 'z': 14.29,   'o': 0.09},
    {'name': 'Shattrath',   'map': 530, 'x': -1838.16, 'y': 5301.88,  'z': -12.43,  'o': 5.95},
    {'name': 'Dalaran',     'map': 571, 'x': 5807.77,  'y': 588.35,   'z': 661.50,  'o': 1.66},
]

NPC_ENTRY = 91100


def main():
    gen = SQLGenerator(start_entry=91100, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 1. Create NPC with gossip menu
    # ---------------------------------------------------------------
    gossip_options = []
    for i, dest in enumerate(DESTINATIONS):
        gossip_options.append({
            'option_id': i,
            'icon': 2,       # Taxi icon
            'text': 'Teleport to {}'.format(dest['name']),
            'type': 1,
            'npc_flag': 1,
        })
    # Add "close" option
    gossip_options.append({
        'option_id': len(DESTINATIONS),
        'icon': 0,
        'text': 'I have changed my mind.',
        'type': 1,
        'npc_flag': 1,
    })

    gen.add_npcs([
        {
            'entry': NPC_ENTRY,
            'name': 'Arcane Wayfinder',
            'subname': 'Teleportation Services',
            'minlevel': 80,
            'maxlevel': 80,
            'faction': 35,
            'npcflag': 1,            # GOSSIP only
            'modelid1': 24369,       # Blood elf female model
            'type': 7,
            'health_modifier': 10.0,
            'damage_modifier': 0.0,
            'unit_flags': 2,         # NON_ATTACKABLE
            'flags_extra': 2,        # CIVILIAN
            'gossip_menu_id': NPC_ENTRY,
            'gossip_text': (
                'The ley lines are at my command. I can send you to any '
                'major city across Azeroth and beyond. Simply tell me '
                'your destination.'
            ),
            'gossip_options': gossip_options,
        },
    ])

    # ---------------------------------------------------------------
    # 2. Spawn the NPC
    # ---------------------------------------------------------------
    gen.add_spawns([
        {
            'entry': NPC_ENTRY,
            'position': (-8833.0, 632.0, 94.0, 3.14),
            'spawntimesecs': 60,
        },
    ])

    # ---------------------------------------------------------------
    # 3. Write SQL
    # ---------------------------------------------------------------
    os.makedirs('output', exist_ok=True)
    gen.write_sql(os.path.join('output', 'npc_teleporter_eluna.sql'))
    print("NPC teleporter SQL written to output/npc_teleporter_eluna.sql")
    print()
    print("IMPORTANT: You must also deploy the Eluna Lua script.")
    print("Copy the generated Lua file to your server's lua_scripts/ directory.")

    # ---------------------------------------------------------------
    # 4. Generate the Eluna Lua script
    # ---------------------------------------------------------------
    lua_script = generate_eluna_script(NPC_ENTRY, DESTINATIONS)
    lua_path = os.path.join('output', 'teleporter_npc.lua')
    with open(lua_path, 'w', encoding='utf-8') as f:
        f.write(lua_script)
    print("Eluna Lua script written to: {}".format(os.path.abspath(lua_path)))


def generate_eluna_script(npc_entry, destinations):
    """Generate a complete Eluna Lua teleporter script."""
    lines = []
    lines.append('--[[ ')
    lines.append('    Teleporter NPC - Eluna Lua Script')
    lines.append('    NPC Entry: {}'.format(npc_entry))
    lines.append('    Generated by pywowlib SQLGenerator')
    lines.append('')
    lines.append('    Installation:')
    lines.append('      1. Apply the SQL file to your acore_world database.')
    lines.append('      2. Copy this .lua file to your server lua_scripts/ directory.')
    lines.append('      3. Restart the world server (or use .reload eluna).')
    lines.append(']]--')
    lines.append('')
    lines.append('local NPC_ENTRY = {}'.format(npc_entry))
    lines.append('local GOSSIP_MENU_ID = {}'.format(npc_entry))
    lines.append('')

    # Destination table
    lines.append('-- Teleport destinations: {optionId, mapId, x, y, z, o, name}')
    lines.append('local DESTINATIONS = {')
    for i, dest in enumerate(destinations):
        lines.append('    [{id}] = {{map = {map}, x = {x}, y = {y}, z = {z}, '
                      'o = {o}, name = "{name}"}},'.format(
            id=i,
            map=dest['map'],
            x=dest['x'],
            y=dest['y'],
            z=dest['z'],
            o=dest['o'],
            name=dest['name'],
        ))
    lines.append('}')
    lines.append('')

    # Gossip Hello handler
    lines.append('-- OnGossipHello: Show the teleport menu')
    lines.append('local function OnGossipHello(event, player, creature)')
    lines.append('    -- The gossip menu is defined in the database (gossip_menu_option).')
    lines.append('    -- We just need to send it to the player.')
    lines.append('    player:GossipSetText("Where would you like to go?")')
    lines.append('')
    lines.append('    for optionId, dest in pairs(DESTINATIONS) do')
    lines.append('        player:GossipMenuAddItem(2, "Teleport to " .. dest.name, 0, optionId)')
    lines.append('    end')
    lines.append('')
    lines.append('    -- Add close option')
    lines.append('    player:GossipMenuAddItem(0, "I have changed my mind.", 0, {})'.format(
        len(destinations)))
    lines.append('')
    lines.append('    player:GossipSendMenu(GOSSIP_MENU_ID, creature)')
    lines.append('end')
    lines.append('')

    # Gossip Select handler
    lines.append('-- OnGossipSelect: Handle destination selection')
    lines.append('local function OnGossipSelect(event, player, creature, sender, intid, code)')
    lines.append('    player:GossipComplete()')
    lines.append('')
    lines.append('    local dest = DESTINATIONS[intid]')
    lines.append('    if dest then')
    lines.append('        player:Teleport(dest.map, dest.x, dest.y, dest.z, dest.o)')
    lines.append('        player:SendBroadcastMessage("Teleporting to " .. dest.name .. "...")')
    lines.append('    end')
    lines.append('end')
    lines.append('')

    # Register events
    lines.append('-- Register the gossip handlers')
    lines.append('RegisterCreatureGossipEvent(NPC_ENTRY, 1, OnGossipHello)')
    lines.append('RegisterCreatureGossipEvent(NPC_ENTRY, 2, OnGossipSelect)')
    lines.append('')
    lines.append('print("[Teleporter] NPC teleporter loaded for entry " .. NPC_ENTRY)')

    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    main()
```

#### Step 3b: The Generated Lua Script

The Python script above generates a Lua file like this:

```lua
--[[
    Teleporter NPC - Eluna Lua Script
    NPC Entry: 91100
    Generated by pywowlib SQLGenerator

    Installation:
      1. Apply the SQL file to your acore_world database.
      2. Copy this .lua file to your server lua_scripts/ directory.
      3. Restart the world server (or use .reload eluna).
]]--

local NPC_ENTRY = 91100
local GOSSIP_MENU_ID = 91100

-- Teleport destinations: {optionId, mapId, x, y, z, o, name}
local DESTINATIONS = {
    [0] = {map = 0, x = -8833.38, y = 628.62, z = 94.0, o = 0.64, name = "Stormwind"},
    [1] = {map = 0, x = -4918.88, y = -940.41, z = 501.56, o = 5.42, name = "Ironforge"},
    [2] = {map = 1, x = 9951.52, y = 2280.32, z = 1341.39, o = 1.59, name = "Darnassus"},
    [3] = {map = 530, x = -3965.7, y = -11653.6, z = -138.84, o = 0.85, name = "Exodar"},
    [4] = {map = 1, x = 1503.27, y = -4415.5, z = 21.55, o = 0.55, name = "Orgrimmar"},
    [5] = {map = 1, x = -1274.45, y = 71.85, z = 128.16, o = 0.56, name = "Thunder Bluff"},
    [6] = {map = 0, x = 1586.48, y = 239.56, z = -52.15, o = 0.05, name = "Undercity"},
    [7] = {map = 530, x = 9473.03, y = -7279.67, z = 14.29, o = 0.09, name = "Silvermoon"},
    [8] = {map = 530, x = -1838.16, y = 5301.88, z = -12.43, o = 5.95, name = "Shattrath"},
    [9] = {map = 571, x = 5807.77, y = 588.35, z = 661.5, o = 1.66, name = "Dalaran"},
}

-- OnGossipHello: Show the teleport menu
local function OnGossipHello(event, player, creature)
    player:GossipSetText("Where would you like to go?")

    for optionId, dest in pairs(DESTINATIONS) do
        player:GossipMenuAddItem(2, "Teleport to " .. dest.name, 0, optionId)
    end

    player:GossipMenuAddItem(0, "I have changed my mind.", 0, 10)

    player:GossipSendMenu(GOSSIP_MENU_ID, creature)
end

-- OnGossipSelect: Handle destination selection
local function OnGossipSelect(event, player, creature, sender, intid, code)
    player:GossipComplete()

    local dest = DESTINATIONS[intid]
    if dest then
        player:Teleport(dest.map, dest.x, dest.y, dest.z, dest.o)
        player:SendBroadcastMessage("Teleporting to " .. dest.name .. "...")
    end
end

-- Register the gossip handlers
RegisterCreatureGossipEvent(NPC_ENTRY, 1, OnGossipHello)
RegisterCreatureGossipEvent(NPC_ENTRY, 2, OnGossipSelect)

print("[Teleporter] NPC teleporter loaded for entry " .. NPC_ENTRY)
```

### Eluna Gossip Event IDs

| Event ID | Name | Description |
|---|---|---|
| 1 | GOSSIP_EVENT_ON_HELLO | Player right-clicks the NPC. Build and send the gossip menu. |
| 2 | GOSSIP_EVENT_ON_SELECT | Player clicks a menu option. `intid` is the option index. |

### Key Eluna API Functions

| Function | Description |
|---|---|
| `player:GossipSetText(text)` | Set the gossip window header text. |
| `player:GossipMenuAddItem(icon, text, sender, intid)` | Add a menu option. `sender` is usually 0. `intid` identifies the option. |
| `player:GossipSendMenu(menuId, creature)` | Display the menu to the player. |
| `player:GossipComplete()` | Close the gossip window. Always call before teleporting. |
| `player:Teleport(map, x, y, z, o)` | Teleport the player to the specified coordinates. |
| `player:SendBroadcastMessage(text)` | Show a system message to the player. |
| `RegisterCreatureGossipEvent(entry, eventId, handler)` | Register a gossip event handler for a creature entry. |

---

## Approach 2: Invisible Area Trigger Teleporter

Area triggers are invisible zones in the game world that fire events when a player walks
into them. Blizzard uses them for dungeon entrances, zone transitions, and tavern rest
areas.

Creating a custom area trigger requires two things:
1. A client-side `AreaTrigger.dbc` record (defines the trigger zone geometry and position).
2. A server-side `areatrigger_teleport` SQL entry (defines the teleport destination).

### Step 4: Understand AreaTrigger.dbc

The `AreaTrigger.dbc` file defines invisible trigger zones in the game world. Each record
specifies a position and either a spherical radius or a rectangular box as the trigger
volume.

#### AreaTrigger.dbc Field Layout (WotLK 3.3.5)

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | `ID` | uint32 | Unique trigger identifier. |
| 1 | `ContinentID` | uint32 | Map ID where the trigger is located (FK to Map.dbc). |
| 2 | `Pos_X` | float | X coordinate of the trigger center. |
| 3 | `Pos_Y` | float | Y coordinate of the trigger center. |
| 4 | `Pos_Z` | float | Z coordinate of the trigger center. |
| 5 | `Radius` | float | Spherical trigger radius in yards. Set to `0` to use box trigger. |
| 6 | `Box_length` | float | Box trigger length (Y-axis) in yards. |
| 7 | `Box_width` | float | Box trigger width (X-axis) in yards. |
| 8 | `Box_height` | float | Box trigger height (Z-axis) in yards. |
| 9 | `Box_yaw` | float | Box rotation in radians. |

**Total:** 10 fields, 40 bytes per record.

#### Sphere vs Box Triggers

- **Sphere trigger** (`radius > 0`): The trigger fires when the player enters a sphere
  centered at `(Pos_X, Pos_Y, Pos_Z)` with the given radius. Simple and effective for
  most teleporters.

- **Box trigger** (`radius = 0`, box dimensions > 0): The trigger fires when the player
  enters a rectangular box centered at the position. Useful for doorways, corridors, and
  other non-spherical trigger zones.

**Choosing trigger size:**
- For doorway-style triggers: Box with length=3, width=5, height=5
- For portal-style triggers: Sphere with radius=3 to 5 yards
- For zone-boundary triggers: Sphere with radius=10 to 20 yards
- Too small = players can walk past; too large = accidental teleports

---

### Step 5: Register an Area Trigger with pywowlib

The `dbc_injector.register_area_trigger()` function injects a new record into
`AreaTrigger.dbc`.

#### API Reference

```python
from world_builder.dbc_injector import register_area_trigger

trigger_id = register_area_trigger(
    dbc_dir,           # Path to directory containing AreaTrigger.dbc
    continent_id,      # Map ID where the trigger is placed
    pos_x,             # X coordinate
    pos_y,             # Y coordinate
    pos_z,             # Z coordinate
    trigger_id=None,   # Specific ID or None for auto (max_id + 1)
    radius=5.0,        # Sphere radius (set to 0 for box trigger)
    box_length=0.0,    # Box Y-axis size
    box_width=0.0,     # Box X-axis size
    box_height=0.0,    # Box Z-axis size
    box_yaw=0.0,       # Box rotation in radians
)
```

**Returns:** The assigned trigger ID (int).

---

### Step 6: Understand the areatrigger_teleport Table

The `areatrigger_teleport` table maps an area trigger ID to a teleport destination. When
the server detects a player entering the trigger volume, it looks up this table and
teleports the player.

#### areatrigger_teleport Schema

| Column | Type | Description |
|---|---|---|
| `ID` | int | Area trigger ID. Must match a record in `AreaTrigger.dbc`. |
| `Name` | string | Descriptive name for the teleport (for admin reference). |
| `target_map` | int | Destination map ID. |
| `target_position_x` | float | Destination X coordinate. |
| `target_position_y` | float | Destination Y coordinate. |
| `target_position_z` | float | Destination Z coordinate. |
| `target_orientation` | float | Destination facing direction in radians. |

---

### Step 7: Complete Code Example -- Area Trigger Teleporter

This example creates an invisible trigger zone at a mine entrance that teleports players
to a custom dungeon instance.

```python
#!/usr/bin/env python3
"""
Complete example: Area trigger teleporter.

Creates:
  - AreaTrigger.dbc record (client-side, invisible trigger zone)
  - areatrigger_teleport SQL (server-side, destination mapping)

This example teleports players who walk into a specific location to
a dungeon entrance.

Output:
  - Patched AreaTrigger.dbc (in the specified DBC directory)
  - output/area_trigger_teleport.sql (server-side SQL)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator, BaseBuilder
from world_builder.dbc_injector import register_area_trigger


# Configuration
DBC_DIR = 'path/to/your/DBFilesClient'  # Update this path!

# Trigger position (mine entrance in Elwynn Forest)
TRIGGER_MAP = 0              # Eastern Kingdoms
TRIGGER_X = -9315.0
TRIGGER_Y = -108.0
TRIGGER_Z = 63.0
TRIGGER_RADIUS = 4.0         # 4 yard sphere

# Destination (custom dungeon entrance)
DEST_MAP = 35                # Example: custom instance map
DEST_X = 0.0
DEST_Y = 0.0
DEST_Z = 0.0
DEST_O = 0.0


def main():
    # ---------------------------------------------------------------
    # 1. Register the area trigger in AreaTrigger.dbc
    # ---------------------------------------------------------------
    # NOTE: This modifies the DBC file directly. You must rebuild your
    # client patch MPQ after running this.
    if os.path.isdir(DBC_DIR):
        trigger_id = register_area_trigger(
            dbc_dir=DBC_DIR,
            continent_id=TRIGGER_MAP,
            pos_x=TRIGGER_X,
            pos_y=TRIGGER_Y,
            pos_z=TRIGGER_Z,
            trigger_id=None,         # Auto-assign next available ID
            radius=TRIGGER_RADIUS,
        )
        print("Registered AreaTrigger ID: {}".format(trigger_id))
        print("  Position: ({}, {}, {}) on map {}".format(
            TRIGGER_X, TRIGGER_Y, TRIGGER_Z, TRIGGER_MAP))
        print("  Radius: {} yards".format(TRIGGER_RADIUS))
    else:
        # For demonstration, use a placeholder ID
        trigger_id = 10000
        print("WARNING: DBC directory not found at '{}'".format(DBC_DIR))
        print("Using placeholder trigger ID: {}".format(trigger_id))
        print("Update DBC_DIR in the script and re-run to patch the DBC.")

    # ---------------------------------------------------------------
    # 2. Create the areatrigger_teleport SQL
    # ---------------------------------------------------------------
    gen = SQLGenerator(start_entry=91200, map_id=TRIGGER_MAP, zone_id=12)

    helper = BaseBuilder(gen)
    at_cols = [
        'ID', 'Name',
        'target_map', 'target_position_x', 'target_position_y',
        'target_position_z', 'target_orientation',
    ]
    at_row = [
        trigger_id,
        'Custom Dungeon Entrance - Fargodeep Mine',
        DEST_MAP,
        DEST_X,
        DEST_Y,
        DEST_Z,
        DEST_O,
    ]
    sql = helper.format_insert(
        'areatrigger_teleport', at_cols, [at_row],
        comment='-- AreaTrigger Teleport: Mine entrance -> Custom Dungeon')
    helper.add_sql('areatrigger_teleport', sql)

    # ---------------------------------------------------------------
    # 3. Write SQL output
    # ---------------------------------------------------------------
    os.makedirs('output', exist_ok=True)
    gen.write_sql(os.path.join('output', 'area_trigger_teleport.sql'))
    print()
    print("areatrigger_teleport SQL written to output/area_trigger_teleport.sql")
    print()
    print("Deployment steps:")
    print("  1. Rebuild your client patch MPQ with the updated AreaTrigger.dbc")
    print("  2. Apply the SQL to your acore_world database")
    print("  3. Restart the world server")
    print("  4. Walk to ({}, {}, {}) on map {} to test".format(
        TRIGGER_X, TRIGGER_Y, TRIGGER_Z, TRIGGER_MAP))


if __name__ == '__main__':
    main()
```

---

### Step 8: Box Trigger Example

For a doorway-style trigger (rectangular instead of spherical):

```python
# Register a box-shaped area trigger for a doorway
trigger_id = register_area_trigger(
    dbc_dir=DBC_DIR,
    continent_id=0,              # Eastern Kingdoms
    pos_x=-9315.0,
    pos_y=-108.0,
    pos_z=63.0,
    radius=0.0,                  # Set to 0 to use box trigger
    box_length=3.0,              # 3 yards deep (Y-axis, through the door)
    box_width=5.0,               # 5 yards wide (X-axis, door width)
    box_height=5.0,              # 5 yards tall (Z-axis, door height)
    box_yaw=1.57,                # Rotated 90 degrees (facing north)
)
```

**Box orientation:** The `box_yaw` value is in radians:
- `0.0` = aligned with world X/Y axes
- `1.57` (pi/2) = rotated 90 degrees
- `3.14` (pi) = rotated 180 degrees

---

## Approach 3: Combining Both -- NPC at Trigger Location

A common pattern is to place an NPC near an area trigger. The NPC provides information
and optional teleportation, while the area trigger handles walk-through teleportation for
players who already know where they are going.

```python
# 1. Create and spawn the informational NPC
gen.add_npcs([{
    'entry': 91300,
    'name': 'Mine Entrance Guard',
    'subname': '',
    'minlevel': 15,
    'maxlevel': 15,
    'faction': 12,
    'npcflag': 1,        # GOSSIP
    'modelid1': 3468,
    'gossip_menu_id': 91300,
    'gossip_text': (
        'The mine ahead leads to the corrupted depths. '
        'Proceed with caution, adventurer.'
    ),
}])

gen.add_spawns([{
    'entry': 91300,
    'position': (TRIGGER_X - 5, TRIGGER_Y, TRIGGER_Z, 0.0),
    'spawntimesecs': 60,
}])

# 2. Register the area trigger 3 yards past the NPC
trigger_id = register_area_trigger(
    dbc_dir=DBC_DIR,
    continent_id=0,
    pos_x=TRIGGER_X,
    pos_y=TRIGGER_Y,
    pos_z=TRIGGER_Z,
    radius=3.0,
)

# 3. Create the areatrigger_teleport entry
# (same as Step 7 above)
```

---

## Step 9: Advanced -- Conditional Teleportation

You can restrict area trigger teleportation using the `conditions` table or the
`access_requirement` table.

### Using access_requirement (for dungeon entrances)

The `access_requirement` table controls who can enter an instance through an area trigger.

| Column | Type | Description |
|---|---|---|
| `mapId` | int | The destination map ID. |
| `difficulty` | int | `0` = normal, `1` = heroic. |
| `level_min` | int | Minimum character level. |
| `level_max` | int | Maximum character level (0 = no max). |
| `item` | int | Required item entry (key item). |
| `item2` | int | Alternate required item. |
| `quest_done_A` | int | Required completed quest (Alliance). |
| `quest_done_H` | int | Required completed quest (Horde). |
| `completed_achievement` | int | Required achievement ID. |
| `quest_failed_text` | string | Error message shown when requirement not met. |
| `comment` | string | Admin comment. |

```python
# Require level 15 and completion of quest 90109 to enter
helper = BaseBuilder(gen)
acc_cols = [
    'mapId', 'difficulty', 'level_min', 'level_max',
    'item', 'item2', 'quest_done_A', 'quest_done_H',
    'completed_achievement', 'quest_failed_text', 'comment',
]
acc_row = [
    35,          # Destination map ID
    0,           # Normal difficulty
    15,          # Minimum level 15
    0,           # No maximum level
    0,           # No required item
    0,           # No alternate item
    90109,       # Alliance: must complete "Report to Captain Halford"
    90109,       # Horde: same quest (or set a different Horde equivalent)
    0,           # No required achievement
    'You must complete the Shadow in the Mines quest chain to enter.',
    'Custom Dungeon - Level 15, Quest 90109 required',
]
sql = helper.format_insert('access_requirement', acc_cols, [acc_row],
                           comment='-- Access Requirement: Custom Dungeon')
helper.add_sql('access_requirement', sql)
```

### Using conditions for NPC gossip options

You can conditionally show or hide teleport destinations in the NPC gossip menu.

```python
# Only show "Teleport to Dalaran" option if player is level 68+
cond_cols = [
    'SourceTypeOrReferenceId', 'SourceGroup', 'SourceEntry', 'SourceId',
    'ElseGroup', 'ConditionTypeOrReference', 'ConditionTarget',
    'ConditionValue1', 'ConditionValue2', 'ConditionValue3',
    'NegativeCondition', 'ErrorType', 'ErrorTextId',
    'ScriptName', 'Comment',
]
cond_row = [
    15,          # CONDITION_SOURCE_TYPE_GOSSIP_MENU_OPTION
    91000,       # SourceGroup: MenuID
    4,           # SourceEntry: OptionID (Dalaran = option 4)
    0,           # SourceId
    0,           # ElseGroup
    28,          # CONDITION_LEVEL
    0,           # ConditionTarget: player
    68,          # ConditionValue1: level
    3,           # ConditionValue2: comparison (3 = higher or equal)
    0,           # ConditionValue3
    0,           # NegativeCondition
    0,           # ErrorType
    0,           # ErrorTextId
    '',          # ScriptName
    'Dalaran teleport requires level 68+',
]
sql = helper.format_insert('conditions', cond_cols, [cond_row],
                           comment='-- Condition: Dalaran teleport level req')
helper.add_sql('conditions', sql)
```

---

## Common Pitfalls and Troubleshooting

### NPC Teleporter Issues

| Symptom | Cause | Fix |
|---|---|---|
| NPC shows no menu options | `npcflag` missing gossip bit | Set `npcflag: 1` (UNIT_NPC_FLAG_GOSSIP). |
| Menu shows but clicking does nothing | SmartAI not enabled or script missing | Set `ai_name: 'SmartAI'` on creature, or deploy Eluna Lua script. |
| "Script not found" error | Wrong `ScriptName` or Eluna not loaded | Verify Lua file is in `lua_scripts/` and Eluna is compiled in. |
| Gossip menu text is empty | `gossip_menu_id` mismatch | `creature_template.gossip_menu_id` must match `gossip_menu.MenuID` and `npc_text.ID`. |
| Teleport goes to wrong location | Coordinates wrong | Use `.gps` in-game at the desired destination to get exact coordinates. |

### Area Trigger Issues

| Symptom | Cause | Fix |
|---|---|---|
| Walking through does nothing | DBC not patched | Rebuild your client MPQ with the modified `AreaTrigger.dbc`. |
| Walking through does nothing | `areatrigger_teleport` missing | Apply the SQL to the database. |
| Trigger ID collision | Conflicting with existing trigger | Use `get_max_id() + 1` or choose an ID above 10000. |
| Trigger fires too easily | Radius too large | Reduce the radius to 3-5 yards. |
| Players walk past without triggering | Radius too small | Increase the radius or use a box trigger for doorways. |
| Client crashes near trigger | Corrupted DBC | Regenerate from a clean copy of `AreaTrigger.dbc`. |

### General Issues

| Symptom | Cause | Fix |
|---|---|---|
| "Transfer Aborted" message | Invalid destination map | Verify the destination map exists (`instance_template` or Map.dbc). |
| "Transfer Aborted: Instance not found" | Missing `instance_template` row | Create the instance template entry for the destination map. |
| Player teleports but falls through world | Z coordinate wrong | Use `.gps` at the destination. Ensure the map/ADT data exists. |
| Teleporter works once then stops | NPC died | Set `unit_flags: 2` (NON_ATTACKABLE) and high health modifier. |

---

## Deployment Checklist

### NPC Teleporter (No Client Patch)

- [ ] SQL file applied to `acore_world` database.
- [ ] Creature template created with correct `npcflag` and `gossip_menu_id`.
- [ ] Gossip menu, text, and options created.
- [ ] SmartAI scripts added (or Eluna Lua script deployed).
- [ ] NPC spawned at desired location.
- [ ] World server restarted or `.reload creature_template` used.
- [ ] Tested all destinations in-game.

### Area Trigger Teleporter (Requires Client Patch)

- [ ] `AreaTrigger.dbc` patched with new trigger record.
- [ ] Client patch MPQ rebuilt and distributed to players.
- [ ] `areatrigger_teleport` SQL applied to database.
- [ ] Destination map exists (in Map.dbc and/or `instance_template`).
- [ ] Optional: `access_requirement` added for restricted access.
- [ ] World server restarted.
- [ ] Tested by walking through the trigger zone.

---

## Cross-References

- **[Add New Quest](add_new_quest.md)** -- Create quest-giver NPCs with gossip menus
  using the same NPC creation patterns.
- **[Create Quest Chain](create_quest_chain.md)** -- Unlock teleporter destinations
  based on quest completion using the `conditions` table.
- **[Add Object Interaction](add_object_interaction.md)** -- Gameobjects can also serve
  as teleporters using Type 6 (TRAP) with teleport spells, or as clickable portals
  using Type 10 (GOOBER) with SmartAI.
