# Plan: DBC Navigation Injectors for AreaTrigger, TaxiNodes, TaxiPath, TaxiPathNode

**Target:** WoW WotLK 3.3.5a (build 12340)
**Module:** `world_builder/dbc_injector.py`
**Date:** 2026-02-02

---

## 1. Overview

This plan extends the existing `dbc_injector.py` module to support navigation-related DBC tables required for dungeon entrances and flight path systems. These injectors enable the Tel'Abim custom zone to have:

- Dungeon entrance triggers (Vault of Storms at Mount Abari Caldera)
- Flight point system (Mortuga connected to Ratchet and Gadgetzan)

### Related TODO Items

**Enables:**
- **TODO 1.3:** AreaTrigger for Vault of Storms dungeon entrance, TaxiNodes/TaxiPath/TaxiPathNode for Mortuga flight point
- **TODO 3.3:** Flight path verification and testing

---

## 2. DBC Field Layouts

All field layouts are derived from the authoritative `.dbd` definitions in `wdbx/dbd/definitions/` for WotLK 3.3.5a build range (3.0.1.8303-3.3.5.12340).

### 2.1 AreaTrigger.dbc

**Source:** `wdbx/dbd/definitions/AreaTrigger.dbd` (BUILD 3.0.1.8303-3.3.5.12340)

**Purpose:** Defines invisible trigger zones for dungeon entrances, quest triggers, etc.

```
Index  Field           Type     Offset  Size
-----  --------------  -------  ------  ----
  0    ID              uint32      0     4
  1    ContinentID     uint32      4     4   (FK to Map.dbc)
  2    Pos_X           float       8     4
  3    Pos_Y           float      12     4
  4    Pos_Z           float      16     4
  5    Radius          float      20     4   (spherical trigger radius)
  6    Box_length      float      24     4   (box trigger dimension)
  7    Box_width       float      28     4   (box trigger dimension)
  8    Box_height      float      32     4   (box trigger dimension)
  9    Box_yaw         float      36     4   (box rotation in radians)

Total: 10 fields = 40 bytes per record
```

**Notes:**
- Pos[3] is stored as three separate float fields (X, Y, Z)
- For spherical triggers: set Radius > 0, Box dimensions = 0
- For box triggers: set Radius = 0, Box dimensions > 0

### 2.2 TaxiNodes.dbc

**Source:** `wdbx/dbd/definitions/TaxiNodes.dbd` (BUILD 3.0.1.8303-3.3.5.12340)

**Purpose:** Defines flight master locations (flight points).

```
Index   Field                Type       Offset  Size
------  -------------------  ---------  ------  ----
  0     ID                   uint32        0     4
  1     ContinentID          uint32        4     4   (FK to Map.dbc)
  2     Pos_X                float         8     4
  3     Pos_Y                float        12     4
  4     Pos_Z                float        16     4
  5-21  Name_lang            locstring    20    68   (17 uint32)
 22     MountCreatureID[0]   uint32       88     4   (Alliance mount display ID)
 23     MountCreatureID[1]   uint32       92     4   (Horde mount display ID)

Total: 24 fields = 96 bytes per record
```

**Notes:**
- Name_lang is a locstring (17 uint32 = 68 bytes)
- Only enUS slot (offset 20) is populated
- Mask field (offset 84) is set to 0xFFFFFFFF
- MountCreatureID values reference CreatureDisplayInfo.dbc

### 2.3 TaxiPath.dbc

**Source:** `wdbx/dbd/definitions/TaxiPath.dbd` (BUILD 3.0.1.8303-3.3.5.12340)

**Purpose:** Defines flight routes between two taxi nodes.

```
Index  Field           Type     Offset  Size
-----  --------------  -------  ------  ----
  0    ID              uint32      0     4
  1    FromTaxiNode    uint32      4     4   (FK to TaxiNodes.dbc)
  2    ToTaxiNode      uint32      8     4   (FK to TaxiNodes.dbc)
  3    Cost            uint32     12     4   (flight cost in copper)

Total: 4 fields = 16 bytes per record
```

**Notes:**
- Cost is in copper (100 copper = 1 silver, 10000 copper = 1 gold)
- FromTaxiNode and ToTaxiNode must reference valid TaxiNodes entries

### 2.4 TaxiPathNode.dbc

**Source:** `wdbx/dbd/definitions/TaxiPathNode.dbd` (BUILD 3.0.1.8303-3.3.5.12340)

**Purpose:** Defines waypoints along a flight path.

```
Index  Field               Type     Offset  Size
-----  ------------------  -------  ------  ----
  0    ID                  uint32      0     4
  1    PathID              uint32      4     4   (FK to TaxiPath.dbc)
  2    NodeIndex           uint32      8     4   (sequence number, starts at 0)
  3    ContinentID         uint32     12     4   (FK to Map.dbc)
  4    Loc_X               float      16     4
  5    Loc_Y               float      20     4
  6    Loc_Z               float      24     4
  7    Flags               uint32     28     4
  8    Delay               uint32     32     4   (milliseconds to wait at node)
  9    ArrivalEventID      uint32     36     4   (spell or event on arrival)
 10    DepartureEventID    uint32     40     4   (spell or event on departure)

Total: 11 fields (Loc is 3 floats) = 12 uint32-sized values = 48 bytes per record
```

**Notes:**
- NodeIndex must be sequential starting from 0 for each PathID
- Flags: 0 = normal waypoint, other values for special behavior
- Delay: time in milliseconds to pause at this node (usually 0)

---

## 3. Implementation Design

### 3.1 Module Constants

Add to `dbc_injector.py` after existing constants:

```python
# ---------------------------------------------------------------------------
# AreaTrigger.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/AreaTrigger.dbd
# Total: 10 fields = 40 bytes
# ---------------------------------------------------------------------------
_AREATRIGGER_FIELD_COUNT = 10
_AREATRIGGER_RECORD_SIZE = _AREATRIGGER_FIELD_COUNT * 4  # 40

# ---------------------------------------------------------------------------
# TaxiNodes.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiNodes.dbd
# Total: 24 fields (includes locstring) = 96 bytes
# ---------------------------------------------------------------------------
_TAXINODES_FIELD_COUNT = 24
_TAXINODES_RECORD_SIZE = _TAXINODES_FIELD_COUNT * 4  # 96

# ---------------------------------------------------------------------------
# TaxiPath.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiPath.dbd
# Total: 4 fields = 16 bytes
# ---------------------------------------------------------------------------
_TAXIPATH_FIELD_COUNT = 4
_TAXIPATH_RECORD_SIZE = _TAXIPATH_FIELD_COUNT * 4  # 16

# ---------------------------------------------------------------------------
# TaxiPathNode.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiPathNode.dbd
# Total: 12 fields (Loc is 3 floats) = 48 bytes
# ---------------------------------------------------------------------------
_TAXIPATHNODE_FIELD_COUNT = 12
_TAXIPATHNODE_RECORD_SIZE = _TAXIPATHNODE_FIELD_COUNT * 4  # 48
```

### 3.2 Record Builder Functions

Add after `_build_area_record()`:

#### 3.2.1 _build_areatrigger_record()

```python
def _build_areatrigger_record(
    trigger_id,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    radius=0.0,
    box_length=0.0,
    box_width=0.0,
    box_height=0.0,
    box_yaw=0.0,
):
    """
    Build a raw 40-byte AreaTrigger.dbc record for WotLK 3.3.5.

    Args:
        trigger_id: Unique ID for this area trigger.
        continent_id: Map ID (FK to Map.dbc).
        pos_x, pos_y, pos_z: Center position of trigger.
        radius: Spherical trigger radius (set > 0 for sphere, 0 for box).
        box_length: Box trigger length (Y-axis aligned).
        box_width: Box trigger width (X-axis aligned).
        box_height: Box trigger height (Z-axis aligned).
        box_yaw: Box rotation in radians (rotation around Z-axis).

    Returns:
        bytes: 40-byte AreaTrigger.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', trigger_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: Pos (X, Y, Z)
    buf += struct.pack('<fff', pos_x, pos_y, pos_z)
    # 5: Radius
    buf += struct.pack('<f', radius)
    # 6-9: Box dimensions and rotation
    buf += struct.pack('<ffff', box_length, box_width, box_height, box_yaw)

    assert len(buf) == _AREATRIGGER_RECORD_SIZE, (
        "AreaTrigger record size mismatch: expected {}, got {}".format(
            _AREATRIGGER_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

#### 3.2.2 _build_taxinode_record()

```python
def _build_taxinode_record(
    node_id,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    name_offset,
    mount_alliance=0,
    mount_horde=0,
):
    """
    Build a raw 96-byte TaxiNodes.dbc record for WotLK 3.3.5.

    Args:
        node_id: Unique ID for this taxi node.
        continent_id: Map ID (FK to Map.dbc).
        pos_x, pos_y, pos_z: Flight master position.
        name_offset: String block offset for node name (locstring enUS slot).
        mount_alliance: Alliance mount CreatureDisplayInfo ID.
        mount_horde: Horde mount CreatureDisplayInfo ID.

    Returns:
        bytes: 96-byte TaxiNodes.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', node_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: Pos (X, Y, Z)
    buf += struct.pack('<fff', pos_x, pos_y, pos_z)
    # 5-21: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 22-23: MountCreatureID[2] (Alliance, Horde)
    buf += struct.pack('<II', mount_alliance, mount_horde)

    assert len(buf) == _TAXINODES_RECORD_SIZE, (
        "TaxiNodes record size mismatch: expected {}, got {}".format(
            _TAXINODES_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

#### 3.2.3 _build_taxipath_record()

```python
def _build_taxipath_record(
    path_id,
    from_node,
    to_node,
    cost,
):
    """
    Build a raw 16-byte TaxiPath.dbc record for WotLK 3.3.5.

    Args:
        path_id: Unique ID for this taxi path.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        cost: Flight cost in copper.

    Returns:
        bytes: 16-byte TaxiPath.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', path_id)
    # 1: FromTaxiNode
    buf += struct.pack('<I', from_node)
    # 2: ToTaxiNode
    buf += struct.pack('<I', to_node)
    # 3: Cost
    buf += struct.pack('<I', cost)

    assert len(buf) == _TAXIPATH_RECORD_SIZE, (
        "TaxiPath record size mismatch: expected {}, got {}".format(
            _TAXIPATH_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

#### 3.2.4 _build_taxipathnode_record()

```python
def _build_taxipathnode_record(
    node_id,
    path_id,
    node_index,
    continent_id,
    loc_x,
    loc_y,
    loc_z,
    flags=0,
    delay=0,
    arrival_event_id=0,
    departure_event_id=0,
):
    """
    Build a raw 48-byte TaxiPathNode.dbc record for WotLK 3.3.5.

    Args:
        node_id: Unique ID for this path node.
        path_id: TaxiPath ID this node belongs to.
        node_index: Sequence number in path (starts at 0).
        continent_id: Map ID (FK to Map.dbc).
        loc_x, loc_y, loc_z: Waypoint position.
        flags: Special behavior flags (0 = normal).
        delay: Milliseconds to wait at this node.
        arrival_event_id: Spell/event triggered on arrival.
        departure_event_id: Spell/event triggered on departure.

    Returns:
        bytes: 48-byte TaxiPathNode.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', node_id)
    # 1: PathID
    buf += struct.pack('<I', path_id)
    # 2: NodeIndex
    buf += struct.pack('<I', node_index)
    # 3: ContinentID
    buf += struct.pack('<I', continent_id)
    # 4-6: Loc (X, Y, Z)
    buf += struct.pack('<fff', loc_x, loc_y, loc_z)
    # 7: Flags
    buf += struct.pack('<I', flags)
    # 8: Delay
    buf += struct.pack('<I', delay)
    # 9: ArrivalEventID
    buf += struct.pack('<I', arrival_event_id)
    # 10: DepartureEventID
    buf += struct.pack('<I', departure_event_id)

    assert len(buf) == _TAXIPATHNODE_RECORD_SIZE, (
        "TaxiPathNode record size mismatch: expected {}, got {}".format(
            _TAXIPATHNODE_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

### 3.3 Public API Functions

Add after `register_area()`:

#### 3.3.1 register_area_trigger()

```python
def register_area_trigger(
    dbc_dir,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    trigger_id=None,
    radius=5.0,
    box_length=0.0,
    box_width=0.0,
    box_height=0.0,
    box_yaw=0.0,
):
    """
    Register a new area trigger in AreaTrigger.dbc.

    Area triggers are invisible zones that can trigger dungeon entrances,
    quest events, or other gameplay mechanics.

    Args:
        dbc_dir: Path to directory containing AreaTrigger.dbc.
        continent_id: Map ID where trigger is located (FK to Map.dbc).
        pos_x, pos_y, pos_z: Center position of trigger.
        trigger_id: Specific trigger ID or None for auto (max_id + 1).
        radius: Spherical trigger radius in yards (default 5.0).
                Set to 0.0 to use box trigger instead.
        box_length: Box trigger length (Y-axis) in yards.
        box_width: Box trigger width (X-axis) in yards.
        box_height: Box trigger height (Z-axis) in yards.
        box_yaw: Box rotation in radians.

    Returns:
        int: The assigned area trigger ID.

    Example:
        # Spherical trigger for dungeon entrance (5-yard radius)
        trigger_id = register_area_trigger(
            dbc_dir="./DBFilesClient",
            continent_id=800,
            pos_x=-3000.0,
            pos_y=2500.0,
            pos_z=150.0,
            radius=5.0,
        )

        # Box trigger (10x10x5 yards)
        trigger_id = register_area_trigger(
            dbc_dir="./DBFilesClient",
            continent_id=800,
            pos_x=-3000.0,
            pos_y=2500.0,
            pos_z=150.0,
            radius=0.0,
            box_length=10.0,
            box_width=10.0,
            box_height=5.0,
        )
    """
    filepath = os.path.join(dbc_dir, 'AreaTrigger.dbc')
    dbc = DBCInjector(filepath)

    if trigger_id is None:
        trigger_id = dbc.get_max_id() + 1

    record = _build_areatrigger_record(
        trigger_id=trigger_id,
        continent_id=continent_id,
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        radius=radius,
        box_length=box_length,
        box_width=box_width,
        box_height=box_height,
        box_yaw=box_yaw,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return trigger_id
```

#### 3.3.2 register_taxi_node()

```python
def register_taxi_node(
    dbc_dir,
    name,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    node_id=None,
    mount_alliance=0,
    mount_horde=0,
):
    """
    Register a new taxi node (flight master location) in TaxiNodes.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiNodes.dbc.
        name: Display name for this flight point.
        continent_id: Map ID where node is located (FK to Map.dbc).
        pos_x, pos_y, pos_z: Flight master position.
        node_id: Specific node ID or None for auto (max_id + 1).
        mount_alliance: Alliance mount CreatureDisplayInfo ID (0 for default).
        mount_horde: Horde mount CreatureDisplayInfo ID (0 for default).

    Returns:
        int: The assigned taxi node ID.

    Example:
        node_id = register_taxi_node(
            dbc_dir="./DBFilesClient",
            name="Mortuga, Tel'Abim",
            continent_id=800,
            pos_x=-2800.0,
            pos_y=2200.0,
            pos_z=120.0,
        )
    """
    filepath = os.path.join(dbc_dir, 'TaxiNodes.dbc')
    dbc = DBCInjector(filepath)

    if node_id is None:
        node_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(name)

    record = _build_taxinode_record(
        node_id=node_id,
        continent_id=continent_id,
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        name_offset=name_offset,
        mount_alliance=mount_alliance,
        mount_horde=mount_horde,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return node_id
```

#### 3.3.3 register_taxi_path()

```python
def register_taxi_path(
    dbc_dir,
    from_node,
    to_node,
    cost,
    path_id=None,
):
    """
    Register a new taxi path (flight route) in TaxiPath.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiPath.dbc.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        cost: Flight cost in copper (e.g., 100 = 1 silver).
        path_id: Specific path ID or None for auto (max_id + 1).

    Returns:
        int: The assigned taxi path ID.

    Example:
        path_id = register_taxi_path(
            dbc_dir="./DBFilesClient",
            from_node=500,  # Mortuga
            to_node=79,     # Ratchet
            cost=5000,      # 50 silver
        )
    """
    filepath = os.path.join(dbc_dir, 'TaxiPath.dbc')
    dbc = DBCInjector(filepath)

    if path_id is None:
        path_id = dbc.get_max_id() + 1

    record = _build_taxipath_record(
        path_id=path_id,
        from_node=from_node,
        to_node=to_node,
        cost=cost,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return path_id
```

#### 3.3.4 register_taxi_path_node()

```python
def register_taxi_path_node(
    dbc_dir,
    path_id,
    node_index,
    continent_id,
    loc_x,
    loc_y,
    loc_z,
    node_id=None,
    flags=0,
    delay=0,
    arrival_event_id=0,
    departure_event_id=0,
):
    """
    Register a new taxi path waypoint in TaxiPathNode.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiPathNode.dbc.
        path_id: TaxiPath ID this node belongs to.
        node_index: Sequence number in path (starts at 0).
        continent_id: Map ID for this waypoint.
        loc_x, loc_y, loc_z: Waypoint position.
        node_id: Specific node ID or None for auto (max_id + 1).
        flags: Special behavior flags (0 = normal).
        delay: Milliseconds to wait at this waypoint.
        arrival_event_id: Spell/event on arrival (0 = none).
        departure_event_id: Spell/event on departure (0 = none).

    Returns:
        int: The assigned taxi path node ID.

    Example:
        # First waypoint (departure)
        register_taxi_path_node(
            dbc_dir="./DBFilesClient",
            path_id=1000,
            node_index=0,
            continent_id=800,
            loc_x=-2800.0,
            loc_y=2200.0,
            loc_z=150.0,
        )

        # Mid-flight waypoint
        register_taxi_path_node(
            dbc_dir="./DBFilesClient",
            path_id=1000,
            node_index=1,
            continent_id=800,
            loc_x=-2500.0,
            loc_y=2000.0,
            loc_z=200.0,
        )
    """
    filepath = os.path.join(dbc_dir, 'TaxiPathNode.dbc')
    dbc = DBCInjector(filepath)

    if node_id is None:
        node_id = dbc.get_max_id() + 1

    record = _build_taxipathnode_record(
        node_id=node_id,
        path_id=path_id,
        node_index=node_index,
        continent_id=continent_id,
        loc_x=loc_x,
        loc_y=loc_y,
        loc_z=loc_z,
        flags=flags,
        delay=delay,
        arrival_event_id=arrival_event_id,
        departure_event_id=departure_event_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return node_id
```

#### 3.3.5 register_flight_path() - Convenience Wrapper

```python
def register_flight_path(
    dbc_dir,
    from_node,
    to_node,
    waypoints,
    cost,
    path_id=None,
):
    """
    Register a complete flight path with all waypoints in one call.

    This is a convenience function that creates both the TaxiPath entry
    and all TaxiPathNode entries in a single operation.

    Args:
        dbc_dir: Path to directory containing DBC files.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        waypoints: List of waypoint dicts with keys:
                   - 'continent_id': Map ID
                   - 'x', 'y', 'z': Position coordinates
                   - 'flags': Optional (default 0)
                   - 'delay': Optional in milliseconds (default 0)
                   - 'arrival_event_id': Optional (default 0)
                   - 'departure_event_id': Optional (default 0)
        cost: Flight cost in copper.
        path_id: Specific path ID or None for auto (max_id + 1).

    Returns:
        dict: {
            'path_id': int,
            'node_ids': list[int],  # List of created TaxiPathNode IDs
        }

    Example:
        # Create flight path from Mortuga to Ratchet with 5 waypoints
        result = register_flight_path(
            dbc_dir="./DBFilesClient",
            from_node=500,  # Mortuga
            to_node=79,     # Ratchet
            waypoints=[
                {'continent_id': 800, 'x': -2800.0, 'y': 2200.0, 'z': 150.0},
                {'continent_id': 800, 'x': -2500.0, 'y': 2000.0, 'z': 200.0},
                {'continent_id': 1, 'x': -1000.0, 'y': 1500.0, 'z': 180.0},
                {'continent_id': 1, 'x': -500.0, 'y': 1000.0, 'z': 160.0},
                {'continent_id': 1, 'x': -958.0, 'y': -3754.0, 'z': 120.0},
            ],
            cost=5000,  # 50 silver
        )
    """
    # Create the TaxiPath entry
    assigned_path_id = register_taxi_path(
        dbc_dir=dbc_dir,
        from_node=from_node,
        to_node=to_node,
        cost=cost,
        path_id=path_id,
    )

    # Create all waypoint nodes
    node_ids = []
    for i, waypoint in enumerate(waypoints):
        node_id = register_taxi_path_node(
            dbc_dir=dbc_dir,
            path_id=assigned_path_id,
            node_index=i,
            continent_id=waypoint['continent_id'],
            loc_x=waypoint['x'],
            loc_y=waypoint['y'],
            loc_z=waypoint['z'],
            flags=waypoint.get('flags', 0),
            delay=waypoint.get('delay', 0),
            arrival_event_id=waypoint.get('arrival_event_id', 0),
            departure_event_id=waypoint.get('departure_event_id', 0),
        )
        node_ids.append(node_id)

    return {
        'path_id': assigned_path_id,
        'node_ids': node_ids,
    }
```

---

## 4. Tel'Abim Integration Examples

### 4.1 Vault of Storms Dungeon Entrance

**Location:** Mount Abari Caldera (northern Tel'Abim)
**Type:** Spherical area trigger (5-yard radius)

```python
from world_builder import build_zone
from world_builder.dbc_injector import register_area_trigger

# Assume Tel'Abim map_id = 800 (assigned by build_zone)
map_id = 800

# Register entrance trigger at cave entrance coordinates
trigger_id = register_area_trigger(
    dbc_dir="./DBFilesClient",
    continent_id=map_id,
    pos_x=-3000.0,      # Cave entrance X
    pos_y=2500.0,       # Cave entrance Y
    pos_z=150.0,        # Cave entrance Z
    radius=5.0,         # 5-yard spherical trigger
)

# Note: Server-side configuration needed in `areatrigger_teleport` table:
# INSERT INTO areatrigger_teleport VALUES
# (trigger_id, 'Vault of Storms Entrance', 801, -50.0, -100.0, 20.0, 0.0);
```

### 4.2 Mortuga Flight Point Network

**Mortuga Location:** Eastern Tel'Abim port town
**Connections:** Ratchet (Barrens), Gadgetzan (Tanaris)

```python
from world_builder.dbc_injector import (
    register_taxi_node,
    register_flight_path,
)

# Step 1: Register Mortuga taxi node
mortuga_node_id = register_taxi_node(
    dbc_dir="./DBFilesClient",
    name="Mortuga, Tel'Abim",
    continent_id=800,       # Tel'Abim map_id
    pos_x=-2800.0,          # Mortuga flight master X
    pos_y=2200.0,           # Mortuga flight master Y
    pos_z=120.0,            # Mortuga flight master Z
)

# Step 2: Create flight path from Mortuga to Ratchet
# Ratchet node_id = 79 (existing Kalimdor taxi node)
ratchet_path = register_flight_path(
    dbc_dir="./DBFilesClient",
    from_node=mortuga_node_id,
    to_node=79,             # Ratchet
    waypoints=[
        # Departure from Mortuga
        {'continent_id': 800, 'x': -2800.0, 'y': 2200.0, 'z': 150.0},
        # Over ocean (high altitude for cross-map transition)
        {'continent_id': 800, 'x': -2500.0, 'y': 2000.0, 'z': 200.0},
        {'continent_id': 800, 'x': -2000.0, 'y': 1500.0, 'z': 220.0},
        # Transition to Kalimdor (continent_id changes to 1)
        {'continent_id': 1, 'x': -1000.0, 'y': 1000.0, 'z': 200.0},
        {'continent_id': 1, 'x': -500.0, 'y': 0.0, 'z': 180.0},
        # Arrival at Ratchet
        {'continent_id': 1, 'x': -958.0, 'y': -3754.0, 'z': 120.0},
    ],
    cost=5000,  # 50 silver
)

# Step 3: Create return flight path (Ratchet to Mortuga)
mortuga_return_path = register_flight_path(
    dbc_dir="./DBFilesClient",
    from_node=79,           # Ratchet
    to_node=mortuga_node_id,
    waypoints=[
        # Departure from Ratchet
        {'continent_id': 1, 'x': -958.0, 'y': -3754.0, 'z': 150.0},
        {'continent_id': 1, 'x': -500.0, 'y': 0.0, 'z': 180.0},
        {'continent_id': 1, 'x': -1000.0, 'y': 1000.0, 'z': 200.0},
        # Transition to Tel'Abim
        {'continent_id': 800, 'x': -2000.0, 'y': 1500.0, 'z': 220.0},
        {'continent_id': 800, 'x': -2500.0, 'y': 2000.0, 'z': 200.0},
        # Arrival at Mortuga
        {'continent_id': 800, 'x': -2800.0, 'y': 2200.0, 'z': 120.0},
    ],
    cost=5000,  # 50 silver
)

# Step 4: Create flight path to Gadgetzan
# Gadgetzan node_id = 39 (existing Tanaris taxi node)
gadgetzan_path = register_flight_path(
    dbc_dir="./DBFilesClient",
    from_node=mortuga_node_id,
    to_node=39,             # Gadgetzan
    waypoints=[
        # Departure from Mortuga
        {'continent_id': 800, 'x': -2800.0, 'y': 2200.0, 'z': 150.0},
        # Over ocean
        {'continent_id': 800, 'x': -3000.0, 'y': 1800.0, 'z': 200.0},
        # Transition to Kalimdor
        {'continent_id': 1, 'x': -2000.0, 'y': 500.0, 'z': 220.0},
        {'continent_id': 1, 'x': -1500.0, 'y': -500.0, 'z': 200.0},
        # Arrival at Gadgetzan
        {'continent_id': 1, 'x': -7180.0, 'y': -3785.0, 'z': 100.0},
    ],
    cost=7500,  # 75 silver (longer route)
)

# Step 5: Create return path (Gadgetzan to Mortuga)
# ... (similar to Ratchet return, reversed waypoints)
```

### 4.3 Integration with build_zone()

**Future Enhancement:** Extend `build_zone()` to accept navigation parameters:

```python
from world_builder import build_zone

result = build_zone(
    name="TelAbim",
    output_dir="./output",
    coords=[(32, 32), (32, 33), (33, 32)],
    heightmap=None,
    dbc_dir="./DBFilesClient",
    # NEW: Navigation parameters
    area_triggers=[
        {
            'pos': (-3000.0, 2500.0, 150.0),
            'radius': 5.0,
            'type': 'dungeon_entrance',
            'target_map': 801,  # Vault of Storms instance
        },
    ],
    flight_points=[
        {
            'name': "Mortuga, Tel'Abim",
            'pos': (-2800.0, 2200.0, 120.0),
            'connections': [
                {'to_node': 79, 'cost': 5000},    # Ratchet
                {'to_node': 39, 'cost': 7500},    # Gadgetzan
            ],
        },
    ],
)
```

**Note:** This is a future enhancement and not part of the current implementation scope.

---

## 5. Testing Strategy

### 5.1 Unit Tests

Create `world_builder/test_dbc_navigation.py`:

```python
import os
import tempfile
import struct
from world_builder.dbc_injector import (
    DBCInjector,
    register_area_trigger,
    register_taxi_node,
    register_taxi_path,
    register_taxi_path_node,
    register_flight_path,
)

def test_area_trigger_creation():
    """Test AreaTrigger.dbc record creation and injection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty AreaTrigger.dbc
        dbc_path = os.path.join(tmpdir, 'AreaTrigger.dbc')
        dbc = DBCInjector()
        dbc.field_count = 10
        dbc.record_size = 40
        dbc.write(dbc_path)

        # Register a trigger
        trigger_id = register_area_trigger(
            dbc_dir=tmpdir,
            continent_id=800,
            pos_x=-3000.0,
            pos_y=2500.0,
            pos_z=150.0,
            radius=5.0,
        )

        # Verify record was written
        dbc = DBCInjector(dbc_path)
        assert dbc.record_count == 1
        assert dbc.record_size == 40

        # Verify field values
        rec = dbc.records[0]
        assert struct.unpack_from('<I', rec, 0)[0] == trigger_id  # ID
        assert struct.unpack_from('<I', rec, 4)[0] == 800         # ContinentID
        assert abs(struct.unpack_from('<f', rec, 8)[0] - (-3000.0)) < 0.01  # X
        assert abs(struct.unpack_from('<f', rec, 12)[0] - 2500.0) < 0.01    # Y
        assert abs(struct.unpack_from('<f', rec, 16)[0] - 150.0) < 0.01     # Z
        assert abs(struct.unpack_from('<f', rec, 20)[0] - 5.0) < 0.01       # Radius

def test_taxi_node_creation():
    """Test TaxiNodes.dbc record creation with locstring."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty TaxiNodes.dbc
        dbc_path = os.path.join(tmpdir, 'TaxiNodes.dbc')
        dbc = DBCInjector()
        dbc.field_count = 24
        dbc.record_size = 96
        dbc.write(dbc_path)

        # Register a node
        node_id = register_taxi_node(
            dbc_dir=tmpdir,
            name="Mortuga, Tel'Abim",
            continent_id=800,
            pos_x=-2800.0,
            pos_y=2200.0,
            pos_z=120.0,
        )

        # Verify record
        dbc = DBCInjector(dbc_path)
        assert dbc.record_count == 1
        assert dbc.record_size == 96

        # Verify string was added
        rec = dbc.records[0]
        name_offset = struct.unpack_from('<I', rec, 20)[0]  # First locstring slot
        assert dbc.get_string(name_offset) == "Mortuga, Tel'Abim"

def test_flight_path_creation():
    """Test complete flight path creation with waypoints."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC files
        for dbc_name in ['TaxiPath.dbc', 'TaxiPathNode.dbc']:
            dbc_path = os.path.join(tmpdir, dbc_name)
            dbc = DBCInjector()
            if dbc_name == 'TaxiPath.dbc':
                dbc.field_count = 4
                dbc.record_size = 16
            else:
                dbc.field_count = 12
                dbc.record_size = 48
            dbc.write(dbc_path)

        # Register complete flight path
        result = register_flight_path(
            dbc_dir=tmpdir,
            from_node=500,
            to_node=79,
            waypoints=[
                {'continent_id': 800, 'x': -2800.0, 'y': 2200.0, 'z': 150.0},
                {'continent_id': 800, 'x': -2500.0, 'y': 2000.0, 'z': 200.0},
                {'continent_id': 1, 'x': -958.0, 'y': -3754.0, 'z': 120.0},
            ],
            cost=5000,
        )

        # Verify TaxiPath record
        path_dbc = DBCInjector(os.path.join(tmpdir, 'TaxiPath.dbc'))
        assert path_dbc.record_count == 1
        path_rec = path_dbc.records[0]
        assert struct.unpack_from('<I', path_rec, 4)[0] == 500   # FromNode
        assert struct.unpack_from('<I', path_rec, 8)[0] == 79    # ToNode
        assert struct.unpack_from('<I', path_rec, 12)[0] == 5000 # Cost

        # Verify TaxiPathNode records
        node_dbc = DBCInjector(os.path.join(tmpdir, 'TaxiPathNode.dbc'))
        assert node_dbc.record_count == 3  # 3 waypoints

        # Verify node indices are sequential
        for i in range(3):
            rec = node_dbc.records[i]
            path_id = struct.unpack_from('<I', rec, 4)[0]
            node_index = struct.unpack_from('<I', rec, 8)[0]
            assert path_id == result['path_id']
            assert node_index == i

def test_box_area_trigger():
    """Test box-shaped area trigger creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbc_path = os.path.join(tmpdir, 'AreaTrigger.dbc')
        dbc = DBCInjector()
        dbc.field_count = 10
        dbc.record_size = 40
        dbc.write(dbc_path)

        # Register box trigger
        trigger_id = register_area_trigger(
            dbc_dir=tmpdir,
            continent_id=800,
            pos_x=-3000.0,
            pos_y=2500.0,
            pos_z=150.0,
            radius=0.0,           # No sphere
            box_length=10.0,
            box_width=10.0,
            box_height=5.0,
            box_yaw=1.57,         # 90 degrees in radians
        )

        # Verify box dimensions
        dbc = DBCInjector(dbc_path)
        rec = dbc.records[0]
        assert abs(struct.unpack_from('<f', rec, 20)[0] - 0.0) < 0.01    # Radius = 0
        assert abs(struct.unpack_from('<f', rec, 24)[0] - 10.0) < 0.01   # Length
        assert abs(struct.unpack_from('<f', rec, 28)[0] - 10.0) < 0.01   # Width
        assert abs(struct.unpack_from('<f', rec, 32)[0] - 5.0) < 0.01    # Height
        assert abs(struct.unpack_from('<f', rec, 36)[0] - 1.57) < 0.01   # Yaw
```

### 5.2 Integration Tests

**Test File:** `world_builder/test_telabim_navigation.py`

```python
def test_telabim_full_navigation_setup():
    """End-to-end test: Create Tel'Abim with full navigation system."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup: Create all required DBC files
        for dbc_name in ['Map.dbc', 'AreaTable.dbc', 'AreaTrigger.dbc',
                         'TaxiNodes.dbc', 'TaxiPath.dbc', 'TaxiPathNode.dbc']:
            setup_empty_dbc(os.path.join(tmpdir, dbc_name))

        # Build Tel'Abim zone
        from world_builder import build_zone
        result = build_zone(
            name="TelAbim",
            output_dir=tmpdir,
            coords=[(32, 32)],
            dbc_dir=tmpdir,
        )

        map_id = result['map_id']

        # Add dungeon entrance trigger
        trigger_id = register_area_trigger(
            dbc_dir=tmpdir,
            continent_id=map_id,
            pos_x=-3000.0,
            pos_y=2500.0,
            pos_z=150.0,
            radius=5.0,
        )

        # Add Mortuga flight point
        mortuga_id = register_taxi_node(
            dbc_dir=tmpdir,
            name="Mortuga",
            continent_id=map_id,
            pos_x=-2800.0,
            pos_y=2200.0,
            pos_z=120.0,
        )

        # Add flight path to Ratchet
        flight_result = register_flight_path(
            dbc_dir=tmpdir,
            from_node=mortuga_id,
            to_node=79,  # Ratchet
            waypoints=[
                {'continent_id': map_id, 'x': -2800.0, 'y': 2200.0, 'z': 150.0},
                {'continent_id': 1, 'x': -958.0, 'y': -3754.0, 'z': 120.0},
            ],
            cost=5000,
        )

        # Verify all components exist
        assert trigger_id > 0
        assert mortuga_id > 0
        assert flight_result['path_id'] > 0
        assert len(flight_result['node_ids']) == 2
```

### 5.3 Client Validation Tests

**Manual Testing Steps:**

1. **DBC File Integrity:**
   - Use WoW.tools DBD Explorer to verify record structure
   - Check for correct field alignment and string offsets
   - Validate locstring mask is 0xFFFFFFFF

2. **Area Trigger Testing:**
   ```sql
   -- Server-side: Add trigger teleport
   INSERT INTO areatrigger_teleport VALUES
   (trigger_id, 'Vault of Storms Entrance', 801, -50.0, -100.0, 20.0, 0.0);
   ```
   - Walk player character to trigger coordinates
   - Verify teleport initiates correctly
   - Check client does not crash on trigger activation

3. **Flight Path Testing:**
   ```sql
   -- Server-side: Verify flight master gossip
   SELECT * FROM npc_vendor WHERE entry = <mortuga_flight_master_npc_id>;
   ```
   - Interact with Mortuga flight master NPC
   - Verify "Mortuga, Tel'Abim" appears in flight map UI
   - Verify Ratchet/Gadgetzan connections are listed
   - Purchase flight and verify smooth waypoint traversal
   - Check for correct continent transitions (Tel'Abim -> Kalimdor)

4. **Edge Cases:**
   - Test flight paths with >10 waypoints (performance check)
   - Test area triggers with overlapping radii
   - Test taxi nodes at extreme coordinates (>10000 yards)

---

## 6. Code Style Compliance

Following existing `dbc_injector.py` patterns:

### 6.1 Naming Conventions

- **Constants:** `_UPPERCASE_WITH_UNDERSCORES` (module-level)
- **Functions:** `lowercase_with_underscores`
- **Private functions:** `_leading_underscore` (record builders)
- **Public API:** No leading underscore (convenience functions)

### 6.2 Docstring Style

```python
def function_name(arg1, arg2):
    """
    Brief one-line description.

    Longer description if needed, explaining purpose and usage patterns.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2.

    Returns:
        type: Description of return value.

    Example:
        code_example()
    """
```

### 6.3 Type Safety

- Use `struct.pack` format strings consistently: `'<I'` (uint32), `'<f'` (float)
- Validate record sizes with assertions
- Check string offsets before use

### 6.4 Error Handling

```python
# Validate file exists before read
if not os.path.exists(filepath):
    raise FileNotFoundError("DBC file not found: {}".format(filepath))

# Validate record size matches expected
assert len(buf) == _EXPECTED_SIZE, (
    "Record size mismatch: expected {}, got {}".format(_EXPECTED_SIZE, len(buf))
)
```

---

## 7. Implementation Checklist

### Phase 1: Core Record Builders
- [ ] Add module constants for all 4 DBC tables
- [ ] Implement `_build_areatrigger_record()`
- [ ] Implement `_build_taxinode_record()`
- [ ] Implement `_build_taxipath_record()`
- [ ] Implement `_build_taxipathnode_record()`
- [ ] Add unit tests for each builder function

### Phase 2: Public API Functions
- [ ] Implement `register_area_trigger()`
- [ ] Implement `register_taxi_node()`
- [ ] Implement `register_taxi_path()`
- [ ] Implement `register_taxi_path_node()`
- [ ] Implement `register_flight_path()` convenience wrapper
- [ ] Add docstrings with usage examples

### Phase 3: Integration
- [ ] Update `world_builder/__init__.py` exports
- [ ] Create Tel'Abim integration examples
- [ ] Add integration tests

### Phase 4: Testing & Validation
- [ ] Run unit tests for all functions
- [ ] Test with real WotLK 3.3.5a client DBCs
- [ ] Validate record structures with WoW.tools
- [ ] Manual client testing (area triggers, flight paths)

### Phase 5: Documentation
- [ ] Add usage examples to module docstring
- [ ] Update ROADMAP.md with completed items
- [ ] Document known limitations and edge cases

---

## 8. Known Limitations

1. **Server-Side Dependencies:**
   - AreaTrigger entries require corresponding `areatrigger_teleport` SQL records
   - TaxiNodes require NPC flight master creatures with correct gossip scripts
   - Client DBC changes alone are insufficient for full functionality

2. **Mount Display IDs:**
   - `TaxiNodes.MountCreatureID` fields use default values (0)
   - Custom mounts require additional CreatureDisplayInfo.dbc modifications
   - Default mounts work for standard Alliance/Horde races

3. **Cross-Continent Flight Paths:**
   - Waypoint transitions between continents require careful coordinate mapping
   - Client may have loading screen artifacts during continent changes
   - Testing needed for Tel'Abim (custom map) to Kalimdor transitions

4. **AreaTrigger Events:**
   - `ArrivalEventID` and `DepartureEventID` in TaxiPathNode are not implemented
   - Server-side spell/event system required for these features

5. **Flight Path Validation:**
   - No automatic validation of waypoint distances or flight times
   - Server may reject paths that are too long or have invalid geometry
   - Manual testing required for each created path

---

## 9. Future Enhancements

1. **Automatic Waypoint Generation:**
   - Calculate waypoints between two nodes using A* pathfinding
   - Respect terrain elevation and collision geometry
   - Generate smooth Bezier curves for natural flight paths

2. **build_zone() Integration:**
   - Add `area_triggers` parameter to `build_zone()`
   - Add `flight_points` parameter for automatic flight network creation
   - Validate trigger positions are within tile coordinates

3. **DBC Validation Tools:**
   - Verify foreign key references (Map.dbc, TaxiNodes.dbc)
   - Check for duplicate IDs across DBC files
   - Validate locstring encoding and mask values

4. **Flight Path Optimization:**
   - Minimize waypoint count while maintaining smooth paths
   - Auto-calculate flight costs based on distance
   - Generate bidirectional paths automatically

5. **Area Trigger Templates:**
   - Predefined templates for common trigger types (dungeon, quest, zone boundary)
   - Auto-sizing based on object dimensions
   - Integration with server-side teleport configuration

---

## 10. References

**DBC Definitions:**
- `wdbx/dbd/definitions/AreaTrigger.dbd`
- `wdbx/dbd/definitions/TaxiNodes.dbd`
- `wdbx/dbd/definitions/TaxiPath.dbd`
- `wdbx/dbd/definitions/TaxiPathNode.dbd`

**Existing Code:**
- `world_builder/dbc_injector.py` - Implementation reference
- `world_builder/__init__.py` - Integration API

**WotLK Documentation:**
- WoW.tools DBD Explorer: https://wow.tools/dbc/
- TrinityCore Wiki: https://trinitycore.atlassian.net/wiki/
- AzerothCore DBC Documentation: https://www.azerothcore.org/wiki/dbc

**Build Target:**
- WoW WotLK 3.3.5a (build 12340)
- DBD schema version: 3.0.1.8303-3.3.5.12340

---

## Appendix A: Field Offset Quick Reference

### AreaTrigger.dbc (40 bytes)
```
Offset  Field           Type    Size
------  --------------  ------  ----
0       ID              uint32  4
4       ContinentID     uint32  4
8       Pos_X           float   4
12      Pos_Y           float   4
16      Pos_Z           float   4
20      Radius          float   4
24      Box_length      float   4
28      Box_width       float   4
32      Box_height      float   4
36      Box_yaw         float   4
```

### TaxiNodes.dbc (96 bytes)
```
Offset  Field               Type       Size
------  ------------------  ---------  ----
0       ID                  uint32     4
4       ContinentID         uint32     4
8       Pos_X               float      4
12      Pos_Y               float      4
16      Pos_Z               float      4
20      Name_lang[0]        uint32     4   (enUS string offset)
24      Name_lang[1-7]      uint32[7]  28  (unused locale slots)
52      Name_lang[8-15]     uint32[8]  32  (unused slots)
84      Name_lang[16]       uint32     4   (mask = 0xFFFFFFFF)
88      MountCreatureID[0]  uint32     4   (Alliance)
92      MountCreatureID[1]  uint32     4   (Horde)
```

### TaxiPath.dbc (16 bytes)
```
Offset  Field           Type    Size
------  --------------  ------  ----
0       ID              uint32  4
4       FromTaxiNode    uint32  4
8       ToTaxiNode      uint32  4
12      Cost            uint32  4
```

### TaxiPathNode.dbc (48 bytes)
```
Offset  Field               Type    Size
------  ------------------  ------  ----
0       ID                  uint32  4
4       PathID              uint32  4
8       NodeIndex           uint32  4
12      ContinentID         uint32  4
16      Loc_X               float   4
20      Loc_Y               float   4
24      Loc_Z               float   4
28      Flags               uint32  4
32      Delay               uint32  4
36      ArrivalEventID      uint32  4
40      DepartureEventID    uint32  4
```

---

**Plan Status:** Ready for implementation
**Estimated Effort:** 8-12 hours (implementation + testing)
**Dependencies:** Existing `dbc_injector.py`, `DBCInjector` class
**Blockers:** None
