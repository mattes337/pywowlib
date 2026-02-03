# Change NPC Pathing

**Complexity**: Low to Medium
**Estimated Time**: 15-30 minutes
**Applies To**: WoW WotLK 3.3.5a (build 12340) with AzerothCore

---

## Overview

NPC pathing controls how creatures move through the game world. By default, creatures are either stationary (idle), wander randomly within a radius, or follow a scripted waypoint path. This guide covers all three movement modes and focuses on the most powerful option: **waypoint pathing**, which makes NPCs patrol predefined routes with optional stops, emotes, and speed changes.

Waypoint pathing involves three interconnected database tables:

1. **`creature_template.MovementType`** -- Declares the movement strategy (idle, random, or waypoint)
2. **`creature_addon.path_id`** -- Links a specific creature spawn to a waypoint path
3. **`waypoint_data`** -- Defines the ordered list of coordinates that form the patrol route

The pywowlib `SQLGenerator` handles `creature_template` and `creature_addon` through its Python API. Waypoint data requires manual SQL since it is specific to individual spawn GUIDs rather than creature templates.

---

## Prerequisites

- Python 3.8+ with pywowlib installed
- Access to your AzerothCore `acore_world` database
- In-game GM access for coordinate gathering (`.gps` command)
- A creature already defined in `creature_template` (see [add_new_creature.md](add_new_creature.md))

---

## Table of Contents

1. [Movement Types Overview](#step-1-movement-types-overview)
2. [Random Movement (Wander)](#step-2-random-movement-wander)
3. [Waypoint Pathing Basics](#step-3-waypoint-pathing-basics)
4. [waypoint_data Table Reference](#step-4-waypoint_data-table-reference)
5. [Linking Waypoints via creature_addon](#step-5-linking-waypoints-via-creature_addon)
6. [Waypoint Actions and Delays](#step-6-waypoint-actions-and-delays)
7. [Using GM Commands for Waypoints](#step-7-using-gm-commands-for-waypoints)
8. [Creating Waypoint Paths with Python + SQL](#step-8-creating-waypoint-paths-with-python--sql)
9. [Complete Working Example](#step-9-complete-working-example)
10. [Advanced Pathing Techniques](#step-10-advanced-pathing-techniques)
11. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
12. [Cross-References](#cross-references)

---

## Step 1: Movement Types Overview

The `creature_template.MovementType` field (also called `MovementType` in the `creature` spawn table) determines how a creature moves:

| MovementType | Name | Description |
|-------------|------|-------------|
| 0 | Idle | Creature stands still at its spawn point. Does not move unless scripted. |
| 1 | Random | Creature wanders randomly within a radius defined by `creature.wander_distance`. |
| 2 | Waypoint | Creature follows a predefined path of waypoints from `waypoint_data`. |

### 1.1 Where MovementType Is Set

MovementType appears in two places:

- **`creature_template.MovementType`** -- Default movement for all spawns of this creature type. Used as a fallback if the spawn row does not override it.
- **`creature.MovementType`** -- Per-spawn override. Takes priority over the template value. This allows different spawns of the same creature to have different movement behavior.

### 1.2 Decision Guide

| Use Case | MovementType | Additional Configuration |
|----------|-------------|-------------------------|
| Guard standing at a door | 0 (Idle) | None |
| Animal grazing in a field | 1 (Random) | Set `wander_distance` to 5-15 yards |
| Soldier patrolling a wall | 2 (Waypoint) | Create waypoint_data + creature_addon |
| Shopkeeper at a counter | 0 (Idle) | Optional: emote in creature_addon |
| Flight master | 0 (Idle) | None |
| Roaming elite rare mob | 2 (Waypoint) | Long patrol route with waypoint_data |

---

## Step 2: Random Movement (Wander)

Random movement is the simplest form of creature mobility. The creature picks random points within a specified radius and walks to them.

### 2.1 Configuration Fields

| Field | Location | Description |
|-------|----------|-------------|
| `movement_type` | creature_template or creature spawn | Set to 1 for random movement |
| `wander_distance` | creature spawn only | Radius in yards from spawn point |

### 2.2 Python Code

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=91500, map_id=0, zone_id=1)

# Create the creature template (default idle)
gen.add_creatures([
    {
        'entry': 91500,
        'name': 'Grazing Plainstrider',
        'modelid1': 2536,               # Plainstrider display
        'minlevel': 10,
        'maxlevel': 12,
        'faction': 7,                    # Neutral creature
        'type': 1,                       # Beast
        'movement_type': 1,             # Default: random wander
    },
])

# Spawn with specific wander radius
gen.add_spawns([
    {
        'entry': 91500,
        'position': (-300.0, -500.0, 50.0, 0.0),
        'spawntimesecs': 120,
        'wander_distance': 10.0,         # Wander 10 yards from spawn
        'movement_type': 1,             # Random wander
    },
])

gen.write_sql('./output/sql/creature_wandering.sql')
```

### 2.3 Important Notes on Random Movement

- `wander_distance` must be greater than 0 when `movement_type` is 1. A value of 0 with type 1 will cause the creature to stand still.
- The creature walks (does not run) between random points.
- The creature picks a new random point when it reaches the current destination.
- There is no delay at each point -- the creature moves continuously.
- If you need the creature to pause, use waypoint pathing instead.

---

## Step 3: Waypoint Pathing Basics

Waypoint pathing makes a creature follow a predefined route -- a sequence of (x, y, z) coordinates that the creature walks or runs through in order. When the creature reaches the last waypoint, it loops back to the first.

### 3.1 How Waypoint Pathing Works

The flow is:

```
creature_template (entry)
    MovementType = 2  (or creature spawn overrides to 2)
         |
         v
creature spawn (guid)
         |
         v
creature_addon (guid)
    path_id = <waypoint path ID>
         |
         v
waypoint_data (id = path_id)
    point 1: (x1, y1, z1)
    point 2: (x2, y2, z2)
    point 3: (x3, y3, z3)
    ...
```

### 3.2 Linking Chain

1. `creature_template.MovementType = 2` (or `creature.MovementType = 2` for per-spawn)
2. `creature_addon.guid = <spawn GUID>` and `creature_addon.path_id = <path ID>`
3. `waypoint_data.id = <path ID>` with ordered waypoints

### 3.3 Path ID Convention

The `path_id` in `creature_addon` is typically set to the creature's spawn GUID multiplied by 10:

```
path_id = guid * 10
```

This is a convention (not a hard requirement) that avoids ID collisions. You can use any unique positive integer.

---

## Step 4: waypoint_data Table Reference

The `waypoint_data` table defines the individual waypoints that form a patrol path.

### 4.1 Column Reference

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Path ID. Must match `creature_addon.path_id`. All waypoints with the same `id` belong to the same path. |
| `point` | int | Waypoint sequence number (1-based). Creature visits points in ascending order. |
| `position_x` | float | X coordinate of this waypoint |
| `position_y` | float | Y coordinate of this waypoint |
| `position_z` | float | Z coordinate of this waypoint |
| `orientation` | float | Facing direction at this point (radians, 0-6.28). 0 = default (face direction of travel). |
| `delay` | int | Time in milliseconds to pause at this waypoint (0 = no pause) |
| `move_type` | int | Movement speed: 0 = Walk, 1 = Run, 2 = Fly |
| `action` | int | Action ID to execute at this waypoint (FK to waypoint actions, 0 = none) |
| `action_chance` | int | Percentage chance (0-100) that the action executes (default 100) |
| `wpguid` | int | Internal GUID (usually 0, auto-assigned by server) |

### 4.2 Movement Types (move_type)

| Value | Name | Description |
|-------|------|-------------|
| 0 | Walk | Normal walking speed |
| 1 | Run | Running speed |
| 2 | Fly | Flying movement (for flying creatures only) |

### 4.3 Orientation Values

Orientation is measured in radians:

| Radians | Approximate Direction |
|---------|----------------------|
| 0.0 | North (+Y) |
| 1.57 | West (-X) |
| 3.14 | South (-Y) |
| 4.71 | East (+X) |

Set orientation to 0 to have the creature face its direction of travel (most natural for patrol routes).

---

## Step 5: Linking Waypoints via creature_addon

The `creature_addon` table links a specific creature spawn (by GUID) to a waypoint path. The `SQLGenerator.add_spawns()` method supports this through the `addon` dict parameter.

### 5.1 creature_addon Fields for Pathing

| Field | Dict Key | Type | Description |
|-------|----------|------|-------------|
| guid | (auto) | int | Creature spawn GUID (auto-assigned by SpawnBuilder) |
| path_id | `path_id` | int | FK to waypoint_data.id |

### 5.2 Python Code -- Spawn with Path Link

```python
gen.add_spawns([
    {
        'entry': 91500,
        'position': (-300.0, -500.0, 50.0, 0.0),   # Starting position
        'spawntimesecs': 120,
        'movement_type': 2,                          # Waypoint movement
        'addon': {
            'path_id': 915000,                       # Link to waypoint_data.id
        },
    },
])
```

### 5.3 Important: Starting Position

When using waypoint pathing, the creature's spawn position (in the `creature` table) should match or be very close to waypoint 1 in `waypoint_data`. If the spawn position is far from the first waypoint, the creature will "teleport" to waypoint 1 on spawn, which looks unnatural.

---

## Step 6: Waypoint Actions and Delays

Waypoints can include delays (pauses) and actions (emotes, text, spell casts) that execute when the creature arrives at a specific point.

### 6.1 Delays

The `delay` column specifies how long (in milliseconds) the creature pauses at each waypoint:

```sql
-- Patrol with a 5-second pause at waypoint 3 (guard stopping to look around)
(915000, 3, -305.0, -510.0, 50.0, 0, 5000, 0, 0, 100, 0),
```

Common delay values:

| Delay (ms) | Duration | Use Case |
|-----------|----------|----------|
| 0 | No pause | Continuous patrol |
| 1000 | 1 second | Brief glance |
| 3000 | 3 seconds | Short pause (looking around) |
| 5000 | 5 seconds | Guard checkpoint pause |
| 10000 | 10 seconds | Extended stop (e.g. inspecting something) |
| 30000 | 30 seconds | Long stationary period |
| 60000 | 1 minute | Rest stop |

### 6.2 Actions (waypoint_scripts)

The `action` column references a `waypoint_scripts` table that can trigger events at specific waypoints. However, this feature has limited support in AzerothCore. For most use cases, combine SmartAI with `SMART_EVENT_WAYPOINT_REACHED` instead.

### 6.3 SmartAI Waypoint Events

For creatures using both SmartAI and waypoint movement, you can trigger actions at specific waypoints:

```python
gen.add_smartai({
    91500: {
        'name': 'Patrol Guard',
        'abilities': [
            {
                'event': 'waypoint_reached',    # Not directly supported
                # Use raw SmartAI event type 40 (WAYPOINT_REACHED)
                # This requires manual SQL; shown below
            },
        ],
    },
})
```

Manual SmartAI SQL for waypoint events:

```sql
-- SmartAI: Emote at waypoint 3, yell at waypoint 5
INSERT INTO `smart_scripts` (`entryorguid`, `source_type`, `id`, `link`,
    `event_type`, `event_phase_mask`, `event_chance`, `event_flags`,
    `event_param1`, `event_param2`, `event_param3`, `event_param4`, `event_param5`,
    `action_type`,
    `action_param1`, `action_param2`, `action_param3`,
    `action_param4`, `action_param5`, `action_param6`,
    `target_type`,
    `target_param1`, `target_param2`, `target_param3`, `target_param4`,
    `target_x`, `target_y`, `target_z`, `target_o`,
    `comment`) VALUES
-- At waypoint 3: Salute emote
(91500, 0, 0, 0, 40, 0, 100, 0,
 3, 915000, 0, 0, 0,              -- event_param1=point, event_param2=pathid
 5, 66, 0, 0, 0, 0, 0,            -- action: SET_EMOTE, emote 66 (Salute)
 1, 0, 0, 0, 0, 0, 0, 0, 0,
 'Patrol Guard - WP 3 - Salute'),
-- At waypoint 5: Say text
(91500, 0, 1, 0, 40, 0, 100, 0,
 5, 915000, 0, 0, 0,              -- event_param1=point, event_param2=pathid
 1, 0, 0, 0, 0, 0, 0,             -- action: TALK, GroupID 0
 1, 0, 0, 0, 0, 0, 0, 0, 0,
 'Patrol Guard - WP 5 - Yell');
```

---

## Step 7: Using GM Commands for Waypoints

AzerothCore provides in-game GM commands for creating and managing waypoint paths. This is often easier than writing SQL by hand for coordinate gathering.

### 7.1 Core Waypoint GM Commands

| Command | Description |
|---------|-------------|
| `.wp add <path_id>` | Add a new waypoint at your current position to the specified path |
| `.wp show on <path_id>` | Display all waypoints for a path as visual markers |
| `.wp show off <path_id>` | Hide waypoint visual markers |
| `.wp modify <field> <value>` | Modify the selected waypoint (after clicking a marker) |
| `.wp reload <path_id>` | Reload waypoint data from the database |

### 7.2 Creating a Path In-Game (Step by Step)

1. Stand at the creature's spawn point
2. Note the spawn GUID (target the creature and use `.npc info`)
3. Walk to each patrol point and run `.wp add <path_id>` at each location
4. After adding all points, run `.wp show on <path_id>` to verify
5. Link the path to the creature by updating `creature_addon`:

```sql
-- Link creature spawn GUID 12345 to waypoint path 123450
DELETE FROM `creature_addon` WHERE `guid` = 12345;
INSERT INTO `creature_addon` (`guid`, `path_id`, `mount`, `bytes1`, `bytes2`, `emote`, `isLarge`, `auras`) VALUES
(12345, 123450, 0, 0, 0, 0, 0, '');

-- Set movement type to waypoint
UPDATE `creature` SET `MovementType` = 2 WHERE `guid` = 12345;
```

6. Reload: `.reload creature 12345`

### 7.3 Modifying Waypoints In-Game

```
.wp show on 123450           -- Show visual markers
-- Click on a waypoint marker to select it --
.wp modify delay 5000        -- Add 5 second pause
.wp modify move_type 1       -- Change to running
.wp reload 123450            -- Apply changes
```

### 7.4 Exporting Waypoint Data

After creating waypoints in-game, you can export them from the database:

```sql
SELECT id, point, position_x, position_y, position_z, orientation, delay, move_type
FROM waypoint_data
WHERE id = 123450
ORDER BY point;
```

---

## Step 8: Creating Waypoint Paths with Python + SQL

For reproducible, scripted patrol routes, define waypoints in Python and generate the SQL.

### 8.1 Defining Waypoints in Python

```python
# Define a patrol route as a list of waypoint tuples
# Format: (x, y, z, orientation, delay_ms, move_type)
patrol_route = [
    (-300.0, -500.0, 50.0, 0, 0, 0),      # WP 1: Start (walk)
    (-310.0, -505.0, 50.0, 0, 0, 0),      # WP 2: Continue walking
    (-320.0, -510.0, 50.0, 0, 5000, 0),   # WP 3: Pause 5 seconds
    (-330.0, -515.0, 50.0, 0, 0, 1),      # WP 4: Start running
    (-340.0, -520.0, 50.0, 0, 0, 1),      # WP 5: Continue running
    (-350.0, -515.0, 50.0, 0, 3000, 1),   # WP 6: Pause 3 seconds
    (-340.0, -510.0, 50.0, 0, 0, 0),      # WP 7: Walk back
    (-330.0, -505.0, 50.0, 0, 0, 0),      # WP 8: Continue
    (-320.0, -500.0, 50.0, 0, 0, 0),      # WP 9: Continue
    (-310.0, -498.0, 50.0, 0, 0, 0),      # WP 10: Return to start area
]
```

### 8.2 Generating waypoint_data SQL

```python
def generate_waypoint_sql(path_id, waypoints):
    """
    Generate waypoint_data SQL from a list of waypoint tuples.

    Args:
        path_id: Unique waypoint path ID.
        waypoints: List of tuples: (x, y, z, orientation, delay_ms, move_type)

    Returns:
        str: SQL INSERT statement.
    """
    lines = []
    lines.append(f'-- Waypoint path {path_id}')
    lines.append(f'DELETE FROM `waypoint_data` WHERE `id` = {path_id};')
    lines.append(
        'INSERT INTO `waypoint_data` '
        '(`id`, `point`, `position_x`, `position_y`, `position_z`, '
        '`orientation`, `delay`, `move_type`, `action`, `action_chance`, `wpguid`) VALUES'
    )

    rows = []
    for i, wp in enumerate(waypoints):
        x, y, z, orient, delay, move_type = wp
        point = i + 1  # 1-based
        rows.append(
            f'({path_id}, {point}, {x}, {y}, {z}, {orient}, {delay}, '
            f'{move_type}, 0, 100, 0)'
        )

    lines.append(',\n'.join(rows) + ';')
    return '\n'.join(lines)


# Generate the SQL
path_id = 915000
waypoint_sql = generate_waypoint_sql(path_id, patrol_route)
print(waypoint_sql)
```

### 8.3 Output SQL

```sql
-- Waypoint path 915000
DELETE FROM `waypoint_data` WHERE `id` = 915000;
INSERT INTO `waypoint_data` (`id`, `point`, `position_x`, `position_y`, `position_z`,
    `orientation`, `delay`, `move_type`, `action`, `action_chance`, `wpguid`) VALUES
(915000, 1, -300.0, -500.0, 50.0, 0, 0, 0, 0, 100, 0),
(915000, 2, -310.0, -505.0, 50.0, 0, 0, 0, 0, 100, 0),
(915000, 3, -320.0, -510.0, 50.0, 0, 5000, 0, 0, 100, 0),
(915000, 4, -330.0, -515.0, 50.0, 0, 0, 1, 0, 100, 0),
(915000, 5, -340.0, -520.0, 50.0, 0, 0, 1, 0, 100, 0),
(915000, 6, -350.0, -515.0, 50.0, 0, 3000, 1, 0, 100, 0),
(915000, 7, -340.0, -510.0, 50.0, 0, 0, 0, 0, 100, 0),
(915000, 8, -330.0, -505.0, 50.0, 0, 0, 0, 0, 100, 0),
(915000, 9, -320.0, -500.0, 50.0, 0, 0, 0, 0, 100, 0),
(915000, 10, -310.0, -498.0, 50.0, 0, 0, 0, 0, 100, 0);
```

---

## Step 9: Complete Working Example

This complete example creates a patrolling guard NPC with a 10-point waypoint route, pauses at key points, and includes SmartAI for combat behavior:

```python
"""
Complete example: Patrol guard with waypoint movement.
Creates creature_template, spawn, creature_addon with path linkage,
waypoint_data, and SmartAI combat behavior.
"""

from world_builder.sql_generator import SQLGenerator

# ---------------------------------------------------------------
# 1. Initialize generator
# ---------------------------------------------------------------
gen = SQLGenerator(start_entry=91500, map_id=0, zone_id=1519)

# ---------------------------------------------------------------
# 2. Create the guard creature template
# ---------------------------------------------------------------
gen.add_creatures([
    {
        'entry': 91500,
        'name': 'Stormwind Patrol Guard',
        'subname': '',
        'modelid1': 15880,               # Human male
        'minlevel': 75,
        'maxlevel': 75,
        'faction': 84,                   # Stormwind (hostile to Horde)
        'npcflag': 0,
        'rank': 0,                       # Normal
        'type': 7,                       # Humanoid
        'health_modifier': 2.0,
        'damage_modifier': 1.5,
        'ai_name': 'SmartAI',
        'movement_type': 2,             # Waypoint (template default)
        'regen_health': 1,
    },
])

# ---------------------------------------------------------------
# 3. Define the spawn with creature_addon path linkage
# ---------------------------------------------------------------
path_id = 915000  # Convention: GUID * 10

guids = gen.add_spawns([
    {
        'entry': 91500,
        # Spawn position should match waypoint 1
        'position': (-8930.0, -130.0, 83.5, 0.0),
        'spawntimesecs': 120,
        'movement_type': 2,             # Waypoint
        'addon': {
            'path_id': path_id,         # Link to waypoint_data
            'mount': 0,
            'bytes1': 0,
            'bytes2': 0,
            'emote': 0,
            'auras': '',
        },
    },
])
spawn_guid = guids[0]
print(f"Spawn GUID: {spawn_guid}, Path ID: {path_id}")

# ---------------------------------------------------------------
# 4. Add SmartAI combat behavior
# ---------------------------------------------------------------
gen.add_smartai({
    91500: {
        'name': 'Stormwind Patrol Guard',
        'abilities': [
            {
                'event': 'combat',
                'spell_id': 15496,       # Cleave
                'target': 'victim',
                'min_repeat': 5000,
                'max_repeat': 8000,
                'comment': 'Patrol Guard - IC - Cleave',
            },
            {
                'event': 'combat',
                'spell_id': 12169,       # Shield Block
                'target': 'self',
                'min_repeat': 10000,
                'max_repeat': 15000,
                'comment': 'Patrol Guard - IC - Shield Block',
            },
            {
                'event': 'health_pct',
                'health_pct': 15,
                'action_type': 47,       # SMART_ACTION_FLEE
                'action_params': [],
                'target': 'self',
                'event_flags': 1,        # NOT_REPEATABLE
                'comment': 'Patrol Guard - 15% HP - Flee for assist',
            },
        ],
    },
})

# ---------------------------------------------------------------
# 5. Write the creature/spawn SQL
# ---------------------------------------------------------------
gen.write_sql('./output/sql/patrol_guard.sql')

# ---------------------------------------------------------------
# 6. Generate and append waypoint SQL
# ---------------------------------------------------------------
patrol_route = [
    # (x, y, z, orientation, delay_ms, move_type)
    (-8930.0, -130.0, 83.5, 0, 0, 0),       # WP 1: Start
    (-8940.0, -135.0, 83.5, 0, 0, 0),       # WP 2: Walk south
    (-8950.0, -140.0, 83.5, 0, 5000, 0),    # WP 3: Checkpoint - 5s pause
    (-8960.0, -135.0, 83.5, 0, 0, 0),       # WP 4: Turn west
    (-8970.0, -130.0, 83.5, 0, 0, 1),       # WP 5: Start running
    (-8975.0, -120.0, 83.5, 0, 3000, 1),    # WP 6: Checkpoint - 3s pause
    (-8970.0, -115.0, 83.5, 0, 0, 0),       # WP 7: Walk back
    (-8960.0, -120.0, 83.5, 0, 0, 0),       # WP 8: Continue
    (-8950.0, -125.0, 83.5, 0, 5000, 0),    # WP 9: Checkpoint - 5s pause
    (-8940.0, -128.0, 83.5, 0, 0, 0),       # WP 10: Return to start
]

def generate_waypoint_sql(pid, waypoints):
    """Generate waypoint_data INSERT SQL."""
    lines = []
    lines.append('')
    lines.append(f'-- ============================================')
    lines.append(f'-- WAYPOINT_DATA (path {pid})')
    lines.append(f'-- ============================================')
    lines.append(f'DELETE FROM `waypoint_data` WHERE `id` = {pid};')
    lines.append(
        'INSERT INTO `waypoint_data` '
        '(`id`, `point`, `position_x`, `position_y`, `position_z`, '
        '`orientation`, `delay`, `move_type`, `action`, `action_chance`, `wpguid`) VALUES'
    )
    rows = []
    for i, wp in enumerate(waypoints):
        x, y, z, orient, delay, move_type = wp
        rows.append(
            f'({pid}, {i+1}, {x}, {y}, {z}, {orient}, {delay}, '
            f'{move_type}, 0, 100, 0)'
        )
    lines.append(',\n'.join(rows) + ';')
    return '\n'.join(lines)

waypoint_sql = generate_waypoint_sql(path_id, patrol_route)

# Append waypoint SQL to the output file
with open('./output/sql/patrol_guard.sql', 'a', encoding='utf-8') as f:
    f.write('\n')
    f.write(waypoint_sql)
    f.write('\n')

print("Complete SQL written to ./output/sql/patrol_guard.sql")
print(f"Path has {len(patrol_route)} waypoints")
```

### Applying and Testing

```bash
# Apply SQL
mysql -u root -p acore_world < ./output/sql/patrol_guard.sql

# In-game testing
.reload creature_template 91500
.wp show on 915000              -- Visualize the path
.wp reload 915000               -- Reload waypoint data
```

---

## Step 10: Advanced Pathing Techniques

### 10.1 Circular Routes

For creatures that patrol a closed loop, make sure the last waypoint is near the first:

```python
circular_route = [
    (-100, -200, 50, 0, 0, 0),   # Start
    (-110, -210, 50, 0, 0, 0),   # East
    (-120, -200, 50, 0, 0, 0),   # South
    (-110, -190, 50, 0, 0, 0),   # West
    # Returns to start automatically (loops back to WP 1)
]
```

### 10.2 Back-and-Forth Routes

For NPCs that patrol back and forth (e.g. a sentry walking between two posts), include the return trip as explicit waypoints:

```python
back_and_forth = [
    (-100, -200, 50, 0, 5000, 0),   # Post A (5s pause)
    (-110, -205, 50, 0, 0, 0),
    (-120, -210, 50, 0, 0, 0),
    (-130, -215, 50, 0, 5000, 0),   # Post B (5s pause)
    (-120, -210, 50, 0, 0, 0),       # Walk back
    (-110, -205, 50, 0, 0, 0),
    # Loops to WP 1 (Post A)
]
```

### 10.3 Mixed Speed Routes

Use different `move_type` values for dramatic effect:

```python
mixed_speed = [
    (-100, -200, 50, 0, 0, 0),      # Walk normally
    (-110, -205, 50, 0, 0, 0),      # Walk
    (-120, -210, 50, 0, 0, 1),      # Start RUNNING (something alarmed them)
    (-130, -215, 50, 0, 0, 1),      # Keep running
    (-140, -220, 50, 0, 3000, 0),   # Arrive, pause, walk again
    (-130, -215, 50, 0, 0, 0),      # Walk back casually
]
```

### 10.4 Flying Creature Paths

For creatures that fly (e.g. drake patrols), set `inhabit_type` to include the flying flag (4) and use `move_type` 2:

```python
# creature_template
gen.add_creatures([{
    'entry': 91600,
    'name': 'Storm Drake Patrol',
    'modelid1': 28213,           # Proto-Drake
    'inhabit_type': 4,           # Flying only
    'movement_type': 2,         # Waypoint
    # ... other fields ...
}])

# Flying waypoints use move_type=2 and varying Z coordinates
flying_route = [
    (-100, -200, 100, 0, 0, 2),   # High altitude start
    (-150, -250, 120, 0, 0, 2),   # Climb
    (-200, -300, 150, 0, 0, 2),   # Peak
    (-250, -250, 130, 0, 0, 2),   # Descend
    (-200, -200, 110, 0, 0, 2),   # Loop back
]
```

### 10.5 Multiple Creatures on the Same Path

You can have multiple creature spawns follow the same waypoint path. Each spawn references the same `path_id` in its `creature_addon`. They will all follow the identical route but may be at different positions along it depending on their spawn timing.

### 10.6 Disabling Pathing Temporarily

To temporarily stop a creature from patrolling (e.g. for an event), update the spawn's `MovementType`:

```sql
-- Stop patrolling
UPDATE `creature` SET `MovementType` = 0 WHERE `guid` = 12345;

-- Resume patrolling
UPDATE `creature` SET `MovementType` = 2 WHERE `guid` = 12345;
```

---

## Common Pitfalls and Troubleshooting

### Creature does not move at all

- **Cause 1**: `MovementType` is 0 (Idle) in both `creature_template` and the `creature` spawn row.
- **Fix**: Set `MovementType` to 1 (Random) or 2 (Waypoint) in the `creature` spawn row.

- **Cause 2**: For waypoint movement, `creature_addon.path_id` is 0 or does not match any `waypoint_data.id`.
- **Fix**: Verify the `path_id` in `creature_addon` matches the `id` in `waypoint_data`.

### Creature walks to first waypoint then stops

- **Cause**: Only one waypoint exists in `waypoint_data` for this path.
- **Fix**: Add at least 2 waypoints. The creature needs a destination to walk toward.

### Creature teleports to waypoint 1 on spawn

- **Cause**: The spawn position in `creature` table is far from waypoint 1.
- **Fix**: Set the spawn position to match waypoint 1 exactly (or very close to it).

### Creature walks through walls or under the ground

- **Cause**: Waypoint Z coordinates are incorrect, or waypoints are placed through walls/terrain.
- **Fix**: Use `.gps` in-game at each patrol point to get accurate Z coordinates. Ensure all waypoints are on walkable terrain. Add intermediate waypoints around corners and obstacles.

### Random wander creature does not move

- **Cause**: `wander_distance` is 0.
- **Fix**: Set `wander_distance` to a positive value (e.g. 5.0 to 15.0).

### Waypoint path does not loop

- **Cause**: This is not actually an error -- AzerothCore loops waypoint paths automatically (after reaching the last point, the creature returns to point 1).
- **Note**: If you want the creature to pause at the end before restarting, add a `delay` to the last waypoint.

### Creature ignores delay at waypoints

- **Cause**: The `delay` column value is in milliseconds, not seconds.
- **Fix**: Use 5000 for 5 seconds, 10000 for 10 seconds, etc.

### "creature_addon" not found error

- **Cause**: The `guid` in `creature_addon` does not match any existing `creature.guid`.
- **Fix**: Verify the GUID exists in the `creature` table. If using `SQLGenerator`, the GUID is auto-assigned starting from 1 -- use the return value of `add_spawns()` to get the actual GUID.

### Path works in-game but not after server restart

- **Cause**: Waypoint data was added with GM commands but not saved to the database properly.
- **Fix**: Verify the data exists in `waypoint_data` table. GM-created waypoints should be automatically saved, but verify with a SQL query.

---

## Cross-References

- **[Add New Creature](add_new_creature.md)** -- Prerequisite: creating the creature_template before adding pathing
- **[Update Boss Mechanics](update_boss_mechanics.md)** -- For scripted boss movement during encounters
- **[Add Vendor/Trainer](add_vendor_trainer.md)** -- Vendors/trainers are typically stationary (MovementType 0), but can patrol
- **SQLGenerator SpawnBuilder API** -- `world_builder/sql_generator.py` SpawnBuilder class for spawn and creature_addon creation
- **SmartAI Waypoint Events** -- `SMART_EVENT_WAYPOINT_REACHED` (event type 40) for triggering actions at waypoints
