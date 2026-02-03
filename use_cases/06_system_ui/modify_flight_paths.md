# Modify Flight Paths

## Complexity Rating: Moderate

Adding custom flight paths (taxi routes) to WoW WotLK 3.3.5a requires coordinating
three DBC files on the client side and one SQL table on the server side. Unlike many
other DBC modifications, flight paths are relatively self-contained: you do not need
to touch model files, add new textures, or recompile the server core. The main
challenge is getting the waypoint coordinates right so that the flight mount follows
a smooth, natural-looking arc between two points rather than teleporting or clipping
through terrain.

This guide covers the full pipeline from registering taxi nodes, to defining paths and
waypoints, to spawning the flight master NPC that offers the route to players.

---

## Table of Contents

1. [Overview and Architecture](#1-overview-and-architecture)
2. [Prerequisites](#2-prerequisites)
3. [DBC File Reference](#3-dbc-file-reference)
4. [Step 1: Register Taxi Nodes](#4-step-1-register-taxi-nodes)
5. [Step 2: Register a Taxi Path](#5-step-2-register-a-taxi-path)
6. [Step 3: Register Taxi Path Nodes (Waypoints)](#6-step-3-register-taxi-path-nodes-waypoints)
7. [Step 4: Use the Convenience Wrapper](#7-step-4-use-the-convenience-wrapper)
8. [Step 5: Spawn Flight Master NPCs (Server SQL)](#8-step-5-spawn-flight-master-npcs-server-sql)
9. [Designing Smooth Flight Curves](#9-designing-smooth-flight-curves)
10. [Flight Mount Display IDs](#10-flight-mount-display-ids)
11. [Bidirectional Routes](#11-bidirectional-routes)
12. [Complete End-to-End Example](#12-complete-end-to-end-example)
13. [MPQ File Placement](#13-mpq-file-placement)
14. [Common Pitfalls and Troubleshooting](#14-common-pitfalls-and-troubleshooting)
15. [Cross-References](#15-cross-references)

---

## 1. Overview and Architecture

The WoW 3.3.5a flight path system is driven by three DBC files that work together:

```
TaxiNodes.dbc          -- "Where can I fly from/to?"
    |                      Defines each flight point on the map
    |                      (position, display name, mount model).
    v
TaxiPath.dbc           -- "Which two nodes are connected?"
    |                      Defines a directed route from Node A to Node B
    |                      with an associated copper cost.
    v
TaxiPathNode.dbc       -- "What 3D path does the mount follow?"
                           Ordered list of waypoint coordinates that the
                           flight mount traverses between the two nodes.
```

On the server side, a flight master NPC must exist at each taxi node location. This
NPC must have the `UNIT_NPC_FLAG_FLIGHTMASTER` flag (value `8192` / `0x2000`) set in
its `npcflag` column in `creature_template`. Without this flag, the NPC will not
offer the flight map dialog when players interact with it.

The client reads the DBC files from `DBFilesClient\` inside a patch MPQ. The server
reads `creature_template` from its world database (e.g., `acore_world` for
AzerothCore). Both sides must be in agreement for the flight system to work.

---

## 2. Prerequisites

### Files Required

| Item | Location | Purpose |
|------|----------|---------|
| `TaxiNodes.dbc` | Extracted from `DBFilesClient\` | Existing taxi node definitions |
| `TaxiPath.dbc` | Extracted from `DBFilesClient\` | Existing taxi path definitions |
| `TaxiPathNode.dbc` | Extracted from `DBFilesClient\` | Existing waypoint definitions |
| pywowlib | `world_builder/dbc_injector.py` | DBC injection API |

### Software

- **Python 3.5+** with pywowlib on your Python path.
- **MPQ Editor** (Ladik's MPQEditor or equivalent) for extracting base DBC files
  and packing the modified files back into a client patch.
- **AzerothCore / TrinityCore / CMaNGOS** or similar WotLK server for SQL execution.
- A **coordinate tool** for gathering in-game X/Y/Z positions. The `.gps` command
  is available on most private server cores when logged in as a GM.

### Extract the Base DBC Files

Before you can inject new records, you must extract the vanilla DBC files from the
client. Using MPQ Editor or the pywowlib archive reader:

```
1. Open:  <WoW Client>/Data/common.MPQ   (or locale-*.MPQ)
2. Navigate to:  DBFilesClient\
3. Extract:
     TaxiNodes.dbc
     TaxiPath.dbc
     TaxiPathNode.dbc
4. Place them in a working directory, e.g.:  D:\modding\dbc\
```

---

## 3. DBC File Reference

### TaxiNodes.dbc -- 24 fields, 96 bytes per record

This DBC defines every flight point that appears on the taxi map. Each record
represents one green dot (discovered) or gray dot (undiscovered) on the flight
path map.

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `ID` | uint32 | Unique taxi node identifier. Must not collide with existing IDs (retail max is around 500). Custom IDs should start at 1000+. |
| 1 | `ContinentID` | uint32 | Map ID where this flight point is located. FK to `Map.dbc`. Values: `0` = Eastern Kingdoms, `1` = Kalimdor, `530` = Outland, `571` = Northrend. Custom maps use their own ID. |
| 2 | `Pos_X` | float | X coordinate of the flight master NPC in game world units. |
| 3 | `Pos_Y` | float | Y coordinate of the flight master NPC. |
| 4 | `Pos_Z` | float | Z coordinate (altitude) of the flight master NPC. |
| 5-21 | `Name_lang` | locstring (17 uint32) | Localized display name shown on the flight map when hovering over this node. Slot 0 = enUS. Slots 1-15 = other locales (koKR, frFR, deDE, zhCN, zhTW, esES, esMX, ruRU, etc.). Slot 16 = flags mask (`0xFFFFFFFF`). pywowlib sets only enUS (slot 0) and the mask. |
| 22 | `MountCreatureID[0]` | uint32 | Alliance flight mount `CreatureDisplayInfo` ID. This controls which creature model is shown as the taxi mount for Alliance players. Set to `0` for the default gryphon. |
| 23 | `MountCreatureID[1]` | uint32 | Horde flight mount `CreatureDisplayInfo` ID. Controls the Horde taxi mount model. Set to `0` for the default wyvern. |

### TaxiPath.dbc -- 4 fields, 16 bytes per record

Each record defines a one-way directed flight route between two taxi nodes.

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `ID` | uint32 | Unique path identifier. |
| 1 | `FromTaxiNode` | uint32 | Starting TaxiNodes ID (FK to `TaxiNodes.dbc`). |
| 2 | `ToTaxiNode` | uint32 | Destination TaxiNodes ID (FK to `TaxiNodes.dbc`). |
| 3 | `Cost` | uint32 | Flight cost in copper. `100` = 1 silver, `10000` = 1 gold. |

**Important**: Paths are one-directional. To allow flight in both directions, you
must create two path records: one from A to B, and one from B to A.

### TaxiPathNode.dbc -- 12 fields, 48 bytes per record

Each record defines a single waypoint along a flight path. The client interpolates
between consecutive waypoints to create the smooth flight animation.

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `ID` | uint32 | Unique node ID for this waypoint entry. |
| 1 | `PathID` | uint32 | FK to `TaxiPath.dbc`. All waypoints with the same PathID belong to the same route. |
| 2 | `NodeIndex` | uint32 | Sequence number (0-based). The mount flies through waypoints in ascending NodeIndex order. Index 0 is the takeoff point; the highest index is the landing point. |
| 3 | `ContinentID` | uint32 | Map ID for this waypoint. Usually the same as the taxi nodes, but cross-continent flights change this mid-path (e.g., Deeprun Tram). |
| 4 | `Loc_X` | float | X coordinate of this waypoint. |
| 5 | `Loc_Y` | float | Y coordinate of this waypoint. |
| 6 | `Loc_Z` | float | Z coordinate (altitude) of this waypoint. |
| 7 | `Flags` | uint32 | `0` = normal waypoint, `1` = this node is a "taxi path stop" where the player can optionally dismount (used for multi-hop flight chains). |
| 8 | `Delay` | uint32 | Milliseconds to pause at this waypoint before continuing. Used for dramatic pauses or loading transitions. Usually `0`. |
| 9 | `ArrivalEventID` | uint32 | Server-side event or spell ID triggered when the mount arrives at this node. Usually `0`. |
| 10 | `DepartureEventID` | uint32 | Server-side event or spell ID triggered when the mount departs this node. Usually `0`. |

**Note**: The DBC header reports 12 fields because the three `Loc` floats are counted
as individual fields even though they represent a single 3D coordinate.

---

## 4. Step 1: Register Taxi Nodes

Every flight point needs a TaxiNodes.dbc entry. Use `register_taxi_node()` to add a
new flight point:

```python
import os
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import register_taxi_node

# Directory containing your extracted DBC files
dbc_dir = r'D:\modding\dbc'

# Register a custom flight point in Northrend (continent 571)
# Coordinates are obtained in-game via the .gps command
node_id = register_taxi_node(
    dbc_dir=dbc_dir,
    name="Frosthold Summit, Storm Peaks",  # Shown on flight map
    continent_id=571,                       # Northrend
    pos_x=-992.47,                          # X coordinate
    pos_y=-1241.88,                         # Y coordinate
    pos_z=350.22,                           # Z coordinate (altitude)
    # node_id=None means auto-assign (max_id + 1)
    mount_alliance=17759,                   # Custom gryphon display ID
    mount_horde=17699,                      # Custom wyvern display ID
)
print(f"Registered taxi node ID: {node_id}")
```

### What `register_taxi_node()` Does Internally

1. Opens `TaxiNodes.dbc` and reads all existing records.
2. If `node_id` is `None`, scans all records for the highest existing ID and uses
   `max_id + 1`.
3. Adds the name string to the DBC string block (with automatic deduplication).
4. Packs a locstring: the name goes into enUS slot (index 0), all other locale slots
   are set to `0`, and the mask (index 16) is set to `0xFFFFFFFF`.
5. Builds a 96-byte binary record with all 24 fields.
6. Appends the record to the record list and writes the complete DBC back to disk.

### Registering Multiple Nodes

For a flight network, you typically register several nodes:

```python
from world_builder.dbc_injector import register_taxi_node

dbc_dir = r'D:\modding\dbc'

# Departure point
node_a = register_taxi_node(
    dbc_dir=dbc_dir,
    name="Camp Silverbrook, Grizzly Hills",
    continent_id=571,
    pos_x=-3721.11,
    pos_y=-2632.05,
    pos_z=48.93,
    mount_alliance=6851,   # Standard gryphon
    mount_horde=2157,      # Standard wyvern
)

# Arrival point
node_b = register_taxi_node(
    dbc_dir=dbc_dir,
    name="Thorim's Peak, Storm Peaks",
    continent_id=571,
    pos_x=-7294.34,
    pos_y=-376.18,
    pos_z=882.67,
    mount_alliance=6851,
    mount_horde=2157,
)

print(f"Node A: {node_a}")
print(f"Node B: {node_b}")
```

---

## 5. Step 2: Register a Taxi Path

Once you have two taxi nodes, create a directed path between them using
`register_taxi_path()`:

```python
from world_builder.dbc_injector import register_taxi_path

dbc_dir = r'D:\modding\dbc'

# node_a and node_b are the IDs returned by register_taxi_node()
node_a = 1001  # Example: Camp Silverbrook
node_b = 1002  # Example: Thorim's Peak

# Create a one-way path from A to B
# Cost is in copper: 500 copper = 5 silver
path_ab = register_taxi_path(
    dbc_dir=dbc_dir,
    from_node=node_a,
    to_node=node_b,
    cost=500,
    # path_id=None means auto-assign
)
print(f"Path A->B ID: {path_ab}")
```

### Cost Calculation Reference

| Copper | Silver | Gold | Typical Usage |
|--------|--------|------|---------------|
| 100 | 1s | 0g | Very short hop |
| 500 | 5s | 0g | Short zone-internal flight |
| 2000 | 20s | 0g | Medium cross-zone flight |
| 5000 | 50s | 0g | Long cross-zone flight |
| 10000 | 0s | 1g | Very long intercontinental hop |
| 50000 | 0s | 5g | Custom "luxury" flight |

Blizzard's retail flight costs in WotLK typically range from 80 copper to about
2 gold depending on distance. Match the pricing to what feels natural for the
distance your route covers.

---

## 6. Step 3: Register Taxi Path Nodes (Waypoints)

The heart of a flight path is its waypoints. Without waypoints, the client will not
know how to animate the flight. Each waypoint is a 3D coordinate that the mount
visits in sequence.

### Adding Waypoints One at a Time

Use `register_taxi_path_node()` for fine-grained control over individual waypoints:

```python
from world_builder.dbc_injector import register_taxi_path_node

dbc_dir = r'D:\modding\dbc'
path_id = 1501  # The path ID returned by register_taxi_path()

# Waypoint 0: Takeoff point (should match the departure node position)
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=0,          # First waypoint
    continent_id=571,      # Northrend
    loc_x=-3721.11,        # Same as departure taxi node X
    loc_y=-2632.05,        # Same as departure taxi node Y
    loc_z=48.93,           # Ground level at departure
)

# Waypoint 1: Climb to cruising altitude
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=1,
    continent_id=571,
    loc_x=-3900.50,
    loc_y=-2400.00,
    loc_z=250.00,          # Rising to cruising altitude
)

# Waypoint 2: Mid-flight cruising point
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=2,
    continent_id=571,
    loc_x=-5200.00,
    loc_y=-1200.00,
    loc_z=600.00,          # High altitude over mountains
)

# Waypoint 3: Begin descent
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=3,
    continent_id=571,
    loc_x=-6800.00,
    loc_y=-500.00,
    loc_z=950.00,          # Still high, approaching Storm Peaks
)

# Waypoint 4: Landing approach
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=4,
    continent_id=571,
    loc_x=-7200.00,
    loc_y=-380.00,
    loc_z=890.00,          # Descending toward destination
)

# Waypoint 5: Final landing (should match the arrival node position)
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=5,
    continent_id=571,
    loc_x=-7294.34,        # Same as arrival taxi node X
    loc_y=-376.18,         # Same as arrival taxi node Y
    loc_z=882.67,          # Ground level at arrival
)
```

### Special Waypoint Flags

The `flags` parameter controls special behavior:

| Flag Value | Meaning |
|------------|---------|
| `0` | Normal waypoint. The mount flies through this point without stopping. |
| `1` | **Path stop point**. Used in multi-hop chains where the player may choose to dismount at an intermediate node. The server checks this flag when processing multi-segment flights. |

### Delay Parameter

The `delay` parameter causes the mount to hover at a waypoint for the specified
number of milliseconds before continuing. This is rarely used but can create
dramatic flyover effects:

```python
# Hover for 3 seconds over a scenic viewpoint
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=2,
    continent_id=571,
    loc_x=-5500.00,
    loc_y=-800.00,
    loc_z=750.00,
    delay=3000,  # Pause 3 seconds at this waypoint
)
```

### Event Parameters

The `arrival_event_id` and `departure_event_id` fields trigger server-side events
(typically spell IDs) when the mount arrives at or departs from a waypoint. Most
custom paths leave these at `0`:

```python
# Trigger a spell effect on arrival at a waypoint
register_taxi_path_node(
    dbc_dir=dbc_dir,
    path_id=path_id,
    node_index=3,
    continent_id=571,
    loc_x=-6000.00,
    loc_y=-600.00,
    loc_z=700.00,
    arrival_event_id=52438,    # Example: visual aura on arrival
    departure_event_id=0,      # No effect on departure
)
```

---

## 7. Step 4: Use the Convenience Wrapper

For most use cases, `register_flight_path()` is the easiest way to create a complete
flight path. It creates both the TaxiPath entry and all TaxiPathNode entries in a
single call:

```python
from world_builder.dbc_injector import register_flight_path

dbc_dir = r'D:\modding\dbc'

# Define waypoints as a list of dictionaries
waypoints = [
    # Waypoint 0: Takeoff (matches departure node coords)
    {
        'continent_id': 571,
        'x': -3721.11,
        'y': -2632.05,
        'z': 48.93,
    },
    # Waypoint 1: Climb out
    {
        'continent_id': 571,
        'x': -3900.50,
        'y': -2400.00,
        'z': 250.00,
    },
    # Waypoint 2: Cruising altitude
    {
        'continent_id': 571,
        'x': -5200.00,
        'y': -1200.00,
        'z': 600.00,
    },
    # Waypoint 3: Over the peaks
    {
        'continent_id': 571,
        'x': -6800.00,
        'y': -500.00,
        'z': 950.00,
    },
    # Waypoint 4: Descent
    {
        'continent_id': 571,
        'x': -7200.00,
        'y': -380.00,
        'z': 890.00,
    },
    # Waypoint 5: Landing (matches arrival node coords)
    {
        'continent_id': 571,
        'x': -7294.34,
        'y': -376.18,
        'z': 882.67,
    },
]

# Create the complete flight path in one call
result = register_flight_path(
    dbc_dir=dbc_dir,
    from_node=1001,    # Camp Silverbrook taxi node ID
    to_node=1002,      # Thorim's Peak taxi node ID
    waypoints=waypoints,
    cost=2000,         # 20 silver
)

print(f"Created path ID: {result['path_id']}")
print(f"Created waypoint node IDs: {result['node_ids']}")
```

### Return Value

`register_flight_path()` returns a dictionary:

```python
{
    'path_id': 1501,              # Assigned TaxiPath ID
    'node_ids': [5001, 5002, 5003, 5004, 5005, 5006],  # TaxiPathNode IDs
}
```

### Optional Waypoint Fields

Each waypoint dictionary supports these optional keys:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `continent_id` | int | (required) | Map ID for this waypoint |
| `x` | float | (required) | X coordinate |
| `y` | float | (required) | Y coordinate |
| `z` | float | (required) | Z coordinate |
| `flags` | int | `0` | Waypoint flags (see above) |
| `delay` | int | `0` | Pause in milliseconds |
| `arrival_event_id` | int | `0` | Event/spell on arrival |
| `departure_event_id` | int | `0` | Event/spell on departure |

---

## 8. Step 5: Spawn Flight Master NPCs (Server SQL)

The DBC files tell the client where flight points exist and how to animate the
flight. But for a player to actually use a flight point, a flight master NPC must
be spawned at the taxi node's location with the correct NPC flags.

### creature_template Setup

The critical flag is `UNIT_NPC_FLAG_FLIGHTMASTER` = `8192` (`0x2000`). This flag
must be set in the `npcflag` column of `creature_template`.

```sql
-- ============================================================
-- Flight Master NPC template for Camp Silverbrook
-- ============================================================

-- Use a high entry number to avoid conflicts with retail entries
SET @ENTRY_A := 90001;  -- Camp Silverbrook flight master
SET @ENTRY_B := 90002;  -- Thorim's Peak flight master

-- Camp Silverbrook flight master
INSERT INTO `creature_template` (
    `entry`, `name`, `subname`, `minlevel`, `maxlevel`,
    `faction`, `npcflag`, `unit_class`, `unit_flags`,
    `modelid1`, `AIName`, `ScriptName`
) VALUES (
    @ENTRY_A,
    'Brynn Silverbrook',           -- NPC name
    'Flight Master',               -- Subname (shown below name)
    80, 80,                        -- Level 80 (standard for WotLK FPs)
    35,                            -- Faction 35 = friendly to both A/H
                                   -- Use 1802 for Alliance-only,
                                   -- or 1801 for Horde-only
    8192,                          -- npcflag: UNIT_NPC_FLAG_FLIGHTMASTER
    1,                             -- unit_class: 1 = Warrior (standard for FMs)
    768,                           -- unit_flags: UNIT_FLAG_IMMUNE_TO_PC |
                                   -- UNIT_FLAG_IMMUNE_TO_NPC (unkillable)
    28576,                         -- Stormwind pilot model (example)
    '', ''                         -- No SmartAI, no C++ script
);

-- Thorim's Peak flight master
INSERT INTO `creature_template` (
    `entry`, `name`, `subname`, `minlevel`, `maxlevel`,
    `faction`, `npcflag`, `unit_class`, `unit_flags`,
    `modelid1`, `AIName`, `ScriptName`
) VALUES (
    @ENTRY_B,
    'Hjarta Stonewing',
    'Flight Master',
    80, 80,
    35,
    8192,                          -- UNIT_NPC_FLAG_FLIGHTMASTER
    1,
    768,
    26423,                         -- Vrykul model (example)
    '', ''
);
```

### Spawn the NPCs in the World

The NPC must be spawned at the exact coordinates used in TaxiNodes.dbc:

```sql
-- ============================================================
-- Spawn flight masters at their taxi node locations
-- ============================================================

-- Camp Silverbrook flight master
INSERT INTO `creature` (
    `guid`, `id1`, `map`, `position_x`, `position_y`, `position_z`,
    `orientation`, `spawntimesecs`, `MovementType`
) VALUES (
    900001,          -- Unique GUID (use high number)
    @ENTRY_A,        -- creature_template entry
    571,             -- Map: Northrend
    -3721.11,        -- X (must match TaxiNodes.dbc Pos_X!)
    -2632.05,        -- Y (must match TaxiNodes.dbc Pos_Y!)
    48.93,           -- Z (must match TaxiNodes.dbc Pos_Z!)
    3.14159,         -- Orientation (facing direction in radians)
    300,             -- Respawn time in seconds
    0                -- MovementType 0 = stationary
);

-- Thorim's Peak flight master
INSERT INTO `creature` (
    `guid`, `id1`, `map`, `position_x`, `position_y`, `position_z`,
    `orientation`, `spawntimesecs`, `MovementType`
) VALUES (
    900002,
    @ENTRY_B,
    571,
    -7294.34,        -- Must match TaxiNodes.dbc!
    -376.18,
    882.67,
    1.57080,
    300,
    0
);
```

### NPC Flag Combinations

If your flight master also serves other functions, bitwise OR the flags together:

| Flag | Value | Purpose |
|------|-------|---------|
| `UNIT_NPC_FLAG_GOSSIP` | 1 | NPC has gossip dialog |
| `UNIT_NPC_FLAG_QUESTGIVER` | 2 | NPC gives/completes quests |
| `UNIT_NPC_FLAG_VENDOR` | 128 | NPC is a vendor |
| `UNIT_NPC_FLAG_FLIGHTMASTER` | 8192 | NPC is a flight master |
| `UNIT_NPC_FLAG_INNKEEPER` | 65536 | NPC is an innkeeper |
| `UNIT_NPC_FLAG_REPAIR` | 4096 | NPC repairs gear |

Example for a flight master that is also a vendor and quest giver:

```sql
-- npcflag = 8192 + 128 + 2 + 1 = 8323
UPDATE `creature_template` SET `npcflag` = 8323 WHERE `entry` = 90001;
```

### Linking Taxi Node IDs to Flight Masters

The server core matches flight master NPCs to taxi nodes by their position
coordinates. The server looks up the nearest TaxiNodes.dbc entry that matches
the NPC's world position. Therefore, the NPC spawn coordinates **must exactly
match** the `Pos_X`, `Pos_Y`, `Pos_Z` values in the TaxiNodes.dbc record.

If coordinates do not match, the player will see the flight map but the server will
not find the associated taxi node, resulting in "No flight paths available" or the
node simply not appearing.

---

## 9. Designing Smooth Flight Curves

The client interpolates between waypoints using a catmull-rom spline (the same
interpolation method used for creature movement paths). More waypoints produce
smoother curves, but too many can cause unnecessary DBC bloat.

### Guideline: Number of Waypoints by Distance

| Distance (yards) | Recommended Waypoints | Notes |
|-------------------|----------------------|-------|
| < 500 | 3-4 | Short hop within a zone |
| 500 - 2000 | 6-8 | Typical zone-to-zone flight |
| 2000 - 5000 | 10-15 | Cross-continent flight |
| > 5000 | 15-25 | Long intercontinental route |

### Altitude Profile Best Practices

A natural-looking flight follows a bell curve altitude profile:

```
Altitude
   ^
   |          ____
   |         /    \          <-- Cruising altitude
   |        /      \
   |       /        \
   |      /          \
   |     /            \
   |    /              \
   |___/                \___
   |
   +--------------------------> Distance
   Takeoff              Landing
```

**Step-by-step altitude design:**

1. **Takeoff (waypoint 0):** Ground level at the departure taxi node. Match the
   `Pos_Z` from TaxiNodes.dbc exactly.

2. **Climb (waypoints 1-2):** Gradually increase Z over the first 20-30% of the
   total waypoint count. The climb rate should be about 50-100 units of altitude
   per waypoint.

3. **Cruise (waypoints 3-N-2):** Hold a roughly constant altitude. This should be
   high enough to clear all terrain and buildings along the route. Check the actual
   terrain height using `.gps` at several points along the planned route and add
   at least 100 yards of clearance.

4. **Descent (waypoints N-1 to N):** Mirror the climb, gradually decreasing Z back
   to ground level at the arrival node.

### Avoiding Terrain Clipping

The single most common visual bug in custom flights is the mount clipping through
mountains, trees, or buildings. To prevent this:

1. **Survey the route in-game.** Fly along the planned path on a flying mount and
   note the maximum terrain height.
2. **Add clearance.** Set your cruising altitude at least 100 yards above the
   highest obstacle.
3. **Add intermediate waypoints** around tall obstacles. If there is a mountain
   between two waypoints, add a waypoint that curves around or over it.

### Generating Waypoints Programmatically

For long routes, you can generate intermediate waypoints by linear interpolation
between the start and end points, then add altitude:

```python
import math

def generate_arc_waypoints(start, end, continent_id, num_points=8,
                           cruise_altitude_offset=200.0):
    """
    Generate waypoints along a smooth arc between two 3D points.

    Args:
        start: (x, y, z) tuple for the departure point.
        end: (x, y, z) tuple for the arrival point.
        continent_id: Map ID for all waypoints.
        num_points: Total number of waypoints (including start and end).
        cruise_altitude_offset: Extra altitude added at the midpoint.

    Returns:
        List of waypoint dicts compatible with register_flight_path().
    """
    waypoints = []
    for i in range(num_points):
        t = i / (num_points - 1)  # 0.0 to 1.0

        # Linear interpolation for X, Y
        x = start[0] + t * (end[0] - start[0])
        y = start[1] + t * (end[1] - start[1])

        # Parabolic arc for Z (peaks at t=0.5)
        base_z = start[2] + t * (end[2] - start[2])
        arc_offset = cruise_altitude_offset * math.sin(t * math.pi)
        z = base_z + arc_offset

        waypoints.append({
            'continent_id': continent_id,
            'x': x,
            'y': y,
            'z': z,
        })

    return waypoints


# Usage:
start_pos = (-3721.11, -2632.05, 48.93)
end_pos = (-7294.34, -376.18, 882.67)

waypoints = generate_arc_waypoints(
    start=start_pos,
    end=end_pos,
    continent_id=571,
    num_points=10,
    cruise_altitude_offset=300.0,
)

# Feed into register_flight_path()
from world_builder.dbc_injector import register_flight_path

result = register_flight_path(
    dbc_dir=r'D:\modding\dbc',
    from_node=1001,
    to_node=1002,
    waypoints=waypoints,
    cost=2000,
)
```

---

## 10. Flight Mount Display IDs

The `MountCreatureID` fields in TaxiNodes.dbc reference `CreatureDisplayInfo.dbc`
entries that control which 3D model is shown as the flight mount. Here are common
retail display IDs for WotLK 3.3.5a:

### Standard Flight Mounts

| Display ID | Model | Description |
|------------|-------|-------------|
| 6851 | Gryphon | Standard Alliance flight mount (brown gryphon) |
| 2157 | Wyvern | Standard Horde flight mount (tawny wyvern) |
| 17759 | Armored Snowy Gryphon | WotLK Alliance mount |
| 17699 | Armored Blue Wind Rider | WotLK Horde mount |
| 22719 | Dragonhawk | Blood Elf themed mount |
| 22720 | Hippogryph | Night Elf themed mount |

### Expansion-Specific Mounts

| Display ID | Model | Expansion |
|------------|-------|-----------|
| 6851 | Classic Gryphon | Vanilla / Classic |
| 2157 | Classic Wyvern | Vanilla / Classic |
| 18870 | Nether Ray | TBC (Outland) |
| 18871 | Nether Drake | TBC (Outland) |
| 26308 | Frost Wyrm | WotLK (Northrend) |
| 28060 | Proto-Drake | WotLK (Northrend) |

### Per-Zone Custom Mounts

You can create zone-specific mounts by assigning different display IDs to different
taxi nodes. For example, Northrend Storm Peaks nodes might use a frost wyrm model
while Grizzly Hills nodes use a standard gryphon:

```python
# Storm Peaks node uses frost wyrm
register_taxi_node(
    dbc_dir=dbc_dir,
    name="Thorim's Peak, Storm Peaks",
    continent_id=571,
    pos_x=-7294.34, pos_y=-376.18, pos_z=882.67,
    mount_alliance=26308,  # Frost wyrm for Alliance
    mount_horde=26308,     # Frost wyrm for Horde too
)

# Grizzly Hills node uses standard mounts
register_taxi_node(
    dbc_dir=dbc_dir,
    name="Camp Silverbrook, Grizzly Hills",
    continent_id=571,
    pos_x=-3721.11, pos_y=-2632.05, pos_z=48.93,
    mount_alliance=6851,   # Standard gryphon
    mount_horde=2157,      # Standard wyvern
)
```

**Note**: The mount model used during a flight is determined by the **departure node's**
`MountCreatureID`, not the arrival node.

---

## 11. Bidirectional Routes

Flight paths in WoW are unidirectional by design. A path from Node A to Node B does
**not** automatically create a path from Node B to Node A. To allow two-way flight,
you must register two paths with reversed waypoints.

### Creating Bidirectional Routes

```python
from world_builder.dbc_injector import register_flight_path

dbc_dir = r'D:\modding\dbc'

# Forward waypoints: A -> B
waypoints_forward = [
    {'continent_id': 571, 'x': -3721.11, 'y': -2632.05, 'z': 48.93},
    {'continent_id': 571, 'x': -3900.50, 'y': -2400.00, 'z': 250.00},
    {'continent_id': 571, 'x': -5200.00, 'y': -1200.00, 'z': 600.00},
    {'continent_id': 571, 'x': -6800.00, 'y': -500.00,  'z': 950.00},
    {'continent_id': 571, 'x': -7200.00, 'y': -380.00,  'z': 890.00},
    {'continent_id': 571, 'x': -7294.34, 'y': -376.18,  'z': 882.67},
]

# Reverse waypoints: B -> A (simply reversed order)
waypoints_reverse = list(reversed(waypoints_forward))

# Register A -> B
result_ab = register_flight_path(
    dbc_dir=dbc_dir,
    from_node=1001,
    to_node=1002,
    waypoints=waypoints_forward,
    cost=2000,
)

# Register B -> A
result_ba = register_flight_path(
    dbc_dir=dbc_dir,
    from_node=1002,
    to_node=1001,
    waypoints=waypoints_reverse,
    cost=2000,  # Same cost, or different if you prefer
)

print(f"A->B path: {result_ab['path_id']}")
print(f"B->A path: {result_ba['path_id']}")
```

### A Note on Reversed Waypoints

Simply reversing the waypoint list works for straight-line routes, but for routes
that curve around obstacles, you may want to design the reverse path separately
with different intermediate waypoints. The return flight does not need to follow
the same ground track as the outbound flight.

---

## 12. Complete End-to-End Example

This example creates a full custom flight network with three nodes connected in a
triangle:

```python
"""
Complete flight path example: Three-node network in Northrend.

Creates:
  - 3 taxi nodes (Grizzly Hills, Storm Peaks, Icecrown)
  - 6 unidirectional paths (full triangle, both directions)
  - 2 flight master NPCs (SQL output)
"""

import os
import sys
import math
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import register_taxi_node, register_flight_path


# -------------------------------------------------------
# Configuration
# -------------------------------------------------------
DBC_DIR = r'D:\modding\dbc'

# Node definitions: (name, continent, x, y, z, mount_alliance, mount_horde)
NODES = {
    'grizzly': {
        'name': "Camp Silverbrook, Grizzly Hills",
        'continent_id': 571,
        'pos': (-3721.11, -2632.05, 48.93),
        'mount_alliance': 6851,
        'mount_horde': 2157,
    },
    'storm': {
        'name': "Thorim's Peak, Storm Peaks",
        'continent_id': 571,
        'pos': (-7294.34, -376.18, 882.67),
        'mount_alliance': 26308,
        'mount_horde': 26308,
    },
    'icecrown': {
        'name': "Shadow Vault, Icecrown",
        'continent_id': 571,
        'pos': (-8614.21, 883.45, 558.12),
        'mount_alliance': 17759,
        'mount_horde': 17699,
    },
}


def generate_arc_waypoints(start, end, continent_id, num_points=8,
                           altitude_offset=200.0):
    """Generate waypoints along a parabolic arc."""
    waypoints = []
    for i in range(num_points):
        t = i / (num_points - 1)
        x = start[0] + t * (end[0] - start[0])
        y = start[1] + t * (end[1] - start[1])
        base_z = start[2] + t * (end[2] - start[2])
        arc = altitude_offset * math.sin(t * math.pi)
        z = base_z + arc
        waypoints.append({
            'continent_id': continent_id,
            'x': x, 'y': y, 'z': z,
        })
    return waypoints


# -------------------------------------------------------
# Step 1: Register all taxi nodes
# -------------------------------------------------------
node_ids = {}
for key, info in NODES.items():
    nid = register_taxi_node(
        dbc_dir=DBC_DIR,
        name=info['name'],
        continent_id=info['continent_id'],
        pos_x=info['pos'][0],
        pos_y=info['pos'][1],
        pos_z=info['pos'][2],
        mount_alliance=info['mount_alliance'],
        mount_horde=info['mount_horde'],
    )
    node_ids[key] = nid
    print(f"  Node '{key}': ID {nid}")


# -------------------------------------------------------
# Step 2: Create bidirectional paths between all pairs
# -------------------------------------------------------
pairs = [
    ('grizzly', 'storm', 2000),
    ('grizzly', 'icecrown', 3500),
    ('storm', 'icecrown', 1500),
]

for from_key, to_key, cost in pairs:
    from_pos = NODES[from_key]['pos']
    to_pos = NODES[to_key]['pos']
    continent = NODES[from_key]['continent_id']

    # Forward path
    wp_fwd = generate_arc_waypoints(from_pos, to_pos, continent,
                                    num_points=10, altitude_offset=250.0)
    result_fwd = register_flight_path(
        dbc_dir=DBC_DIR,
        from_node=node_ids[from_key],
        to_node=node_ids[to_key],
        waypoints=wp_fwd,
        cost=cost,
    )
    print(f"  Path {from_key}->{to_key}: ID {result_fwd['path_id']}")

    # Reverse path
    wp_rev = generate_arc_waypoints(to_pos, from_pos, continent,
                                    num_points=10, altitude_offset=250.0)
    result_rev = register_flight_path(
        dbc_dir=DBC_DIR,
        from_node=node_ids[to_key],
        to_node=node_ids[from_key],
        waypoints=wp_rev,
        cost=cost,
    )
    print(f"  Path {to_key}->{from_key}: ID {result_rev['path_id']}")


# -------------------------------------------------------
# Step 3: Generate flight master SQL
# -------------------------------------------------------
sql_lines = [
    "-- ================================================================",
    "-- Custom Flight Masters - Auto-generated by pywowlib",
    "-- ================================================================",
    "",
]

fm_entry = 90001
fm_guid = 900001
for key, info in NODES.items():
    name = info['name'].split(',')[0]  # Use location as NPC name
    sql_lines.extend([
        f"-- Flight master at {info['name']}",
        f"INSERT INTO `creature_template` "
        f"(`entry`, `name`, `subname`, `minlevel`, `maxlevel`, "
        f"`faction`, `npcflag`, `unit_class`, `unit_flags`, `modelid1`) "
        f"VALUES ({fm_entry}, '{name} Flight Master', 'Flight Master', "
        f"80, 80, 35, 8192, 1, 768, 28576);",
        "",
        f"INSERT INTO `creature` "
        f"(`guid`, `id1`, `map`, `position_x`, `position_y`, `position_z`, "
        f"`orientation`, `spawntimesecs`, `MovementType`) "
        f"VALUES ({fm_guid}, {fm_entry}, {info['continent_id']}, "
        f"{info['pos'][0]}, {info['pos'][1]}, {info['pos'][2]}, "
        f"0, 300, 0);",
        "",
    ])
    fm_entry += 1
    fm_guid += 1

sql_output = '\n'.join(sql_lines)
sql_path = os.path.join(DBC_DIR, 'flight_masters.sql')
with open(sql_path, 'w') as f:
    f.write(sql_output)

print(f"\nSQL written to: {sql_path}")
print("Done! Modified DBC files are in:", DBC_DIR)
```

---

## 13. MPQ File Placement

After modifying the DBC files, you must pack them into a client-side patch MPQ for
the WoW client to load them. The DBC files go in the `DBFilesClient\` path inside
the MPQ.

### MPQ Internal Paths

```
patch-4.MPQ (or any patch-N.MPQ with N > existing patches)
  |
  +-- DBFilesClient\
        |-- TaxiNodes.dbc
        |-- TaxiPath.dbc
        +-- TaxiPathNode.dbc
```

### Using pywowlib's MPQPacker

```python
from world_builder.mpq_packer import MPQPacker

packer = MPQPacker(output_dir=r'D:\modding\output', patch_name='patch-4.MPQ')

# Add modified DBC files
packer.add_dbc(r'D:\modding\dbc\TaxiNodes.dbc')
packer.add_dbc(r'D:\modding\dbc\TaxiPath.dbc')
packer.add_dbc(r'D:\modding\dbc\TaxiPathNode.dbc')

# Build the patch archive
packer.build()
```

### Manual Placement (Without MPQ Tools)

If you do not have MPQ creation tools available, place the files in a directory
structure that mirrors the MPQ layout:

```
<WoW Client>/Data/patch-4.MPQ/
    DBFilesClient/
        TaxiNodes.dbc
        TaxiPath.dbc
        TaxiPathNode.dbc
```

Then use Ladik's MPQ Editor or a similar tool to create the actual MPQ archive from
this directory tree.

### Client Patch Loading Order

The WoW 3.3.5a client loads patch MPQs in alphabetical/numerical order:
`patch.MPQ`, `patch-2.MPQ`, `patch-3.MPQ`, `patch-4.MPQ`, etc. Higher-numbered
patches override lower-numbered ones. Use `patch-4.MPQ` or higher for custom content
to avoid conflicts with base game patches.

---

## 14. Common Pitfalls and Troubleshooting

### "No direct paths to this destination"

**Cause:** No TaxiPath.dbc entry exists for the selected route.

**Fix:** Verify that `register_taxi_path()` or `register_flight_path()` was called
with the correct `from_node` and `to_node` IDs. Check that both IDs correspond to
valid TaxiNodes.dbc entries.

### Flight master shows no routes at all

**Cause 1:** The NPC's `npcflag` does not include `8192` (UNIT_NPC_FLAG_FLIGHTMASTER).

**Fix:** Run `SELECT npcflag FROM creature_template WHERE entry = <NPC entry>;` and
verify that bit `0x2000` is set. If the current value is, say, `3` (gossip +
questgiver), you need `3 | 8192 = 8195`.

**Cause 2:** The NPC's spawn coordinates do not match TaxiNodes.dbc.

**Fix:** Ensure the `position_x`, `position_y`, `position_z` in the `creature`
table exactly match the `Pos_X`, `Pos_Y`, `Pos_Z` in TaxiNodes.dbc. Even a
difference of 0.01 can cause mismatches on some server cores.

### Flight mount clips through terrain

**Cause:** Waypoint altitude is too low for the terrain between two consecutive
waypoints.

**Fix:** Add more intermediate waypoints with higher Z values. Use the `.gps`
command in-game to check terrain height at several points along the planned route,
then set waypoint Z values at least 100 yards above the maximum terrain height.

### Player takes off but instantly lands

**Cause:** Missing or empty TaxiPathNode records for the given PathID.

**Fix:** Verify that `register_taxi_path_node()` was called for every waypoint, and
that all waypoints reference the correct `path_id`. The path must have at least 2
waypoints (takeoff and landing). Call `register_flight_path()` to ensure both the
path and its nodes are created together.

### Flight takes an excessively long time

**Cause:** Too many waypoints spread across a small distance, or waypoints with
very large delays.

**Fix:** Reduce the number of waypoints. The client flight speed is constant; longer
physical distance between waypoints makes the mount appear to fly faster. For typical
zone-to-zone flights, 6-10 waypoints is sufficient.

### Client crashes on opening flight map

**Cause:** Corrupted DBC file -- usually caused by a record size mismatch or invalid
string block offsets.

**Fix:** Ensure you are using the pywowlib `register_*` functions rather than
manually editing the binary data. These functions validate record sizes via
assertions. If working with raw `DBCInjector`, verify that every record is exactly
96 bytes (TaxiNodes), 16 bytes (TaxiPath), or 48 bytes (TaxiPathNode).

### Duplicate node IDs

**Cause:** Manually specifying a `node_id` that already exists in the DBC.

**Fix:** Let pywowlib auto-assign IDs by passing `node_id=None` (the default).
The library scans all existing records for the maximum ID and uses `max_id + 1`.

---

## 15. Cross-References

| Topic | Guide | Relevance |
|-------|-------|-----------|
| Creating the zone that flight paths connect | `01_world_building_environment/` | You need a zone with Map.dbc and AreaTable.dbc entries before adding flight points to it. |
| NPC creation and creature templates | `04_creatures_encounters/` | Flight masters are NPCs defined in `creature_template` with special flags. |
| SQL generation for NPCs and spawns | `world_builder/sql_generator.py` | Use `SQLGenerator` for bulk creature_template and creature spawn SQL generation. |
| MPQ packing for client distribution | `world_builder/mpq_packer.py` | Use `MPQPacker` to bundle modified DBC files into a client patch. |
| Custom UI for flight path display | `06_system_ui/custom_ui_frame.md` | Advanced: create an addon that displays custom flight path information. |
| DBC injector core API | `world_builder/dbc_injector.py` | Low-level `DBCInjector` class used by all `register_*` functions. |
