# Plan: LFGDungeons.dbc and DungeonEncounter.dbc Injectors

## Overview

This plan extends the `world_builder/dbc_injector.py` module to support injecting LFG dungeon entries and dungeon encounter boss records into WotLK 3.3.5a DBC files. These injectors enable TODO 1.3: registering the "Vault of Storms" dungeon in the LFG system with 4 boss encounters.

**Target Build:** WotLK 3.3.5a (build 12340)

**Enables TODO:** 1.3 - LFGDungeons entry for Vault of Storms + 4 DungeonEncounter entries for bosses

---

## 1. DBC Field Layouts

### 1.1 LFGDungeons.dbc (BUILD 3.3.3.11685-3.3.5.12340)

**Total Fields:** 49 fields = 196 bytes per record

**Field Layout with Byte Offsets:**

| Index | Field Name             | Type      | Byte Offset | Size | Description |
|-------|------------------------|-----------|-------------|------|-------------|
| 0     | ID                     | uint32    | 0           | 4    | Unique dungeon ID |
| 1-17  | Name_lang              | locstring | 4           | 68   | Dungeon name (17 uint32) |
| 18    | MinLevel               | uint32    | 72          | 4    | Minimum level requirement |
| 19    | MaxLevel               | uint32    | 76          | 4    | Maximum level requirement |
| 20    | Target_level           | uint32    | 80          | 4    | Target/average level |
| 21    | Target_level_min       | uint32    | 84          | 4    | Target min level |
| 22    | Target_level_max       | uint32    | 88          | 4    | Target max level |
| 23    | MapID                  | uint32    | 92          | 4    | FK to Map.dbc |
| 24    | Difficulty             | uint32    | 96          | 4    | 0=normal, 1=heroic |
| 25    | Flags                  | uint32    | 100         | 4    | Dungeon flags |
| 26    | TypeID                 | uint32    | 104         | 4    | 1=dungeon, 2=raid, 4=random, 6=random heroic |
| 27    | Faction                | uint32    | 108         | 4    | -1=both (0xFFFFFFFF), 0=horde, 1=alliance |
| 28    | TextureFilename        | uint32    | 112         | 4    | String offset to texture path |
| 29    | ExpansionLevel         | uint32    | 116         | 4    | 0=classic, 1=tbc, 2=wotlk |
| 30    | Order_index            | uint32    | 120         | 4    | Sort order in LFG UI |
| 31    | Group_ID               | uint32    | 124         | 4    | Dungeon group identifier |
| 32-48 | Description_lang       | locstring | 128         | 68   | Dungeon description (17 uint32) |

**Total Size:** 49 fields × 4 bytes = 196 bytes

**Locstring Notes:**
- 8 locale string offsets (enUS in slot 0) + 8 unused uint32 + 1 mask uint32 = 17 uint32
- Mask value: 0xFFFFFFFF (all locales enabled, but only enUS populated)
- Empty locstrings use offset 0 (null byte in string block)

---

### 1.2 DungeonEncounter.dbc (BUILD 3.3.0.10958-3.3.5.12340)

**Total Fields:** 23 fields = 92 bytes per record

**Field Layout with Byte Offsets:**

| Index | Field Name             | Type      | Byte Offset | Size | Description |
|-------|------------------------|-----------|-------------|------|-------------|
| 0     | ID                     | uint32    | 0           | 4    | Unique encounter ID |
| 1     | MapID                  | uint32    | 4           | 4    | FK to Map.dbc |
| 2     | Difficulty             | uint32    | 8           | 4    | 0=normal, 1=heroic |
| 3     | OrderIndex             | uint32    | 12          | 4    | Boss order (0-based) |
| 4     | Bit                    | uint32    | 16          | 4    | Bitmask position for encounter state |
| 5-21  | Name_lang              | locstring | 20          | 68   | Boss name (17 uint32) |
| 22    | SpellIconID            | uint32    | 88          | 4    | Icon for encounter journal |

**Total Size:** 23 fields × 4 bytes = 92 bytes

**Bit Field Notes:**
- Used by server to track which bosses have been defeated in an instance
- Typically sequential: 0, 1, 2, 3 for a 4-boss dungeon
- Server checks bitmask to determine loot eligibility and lockouts

---

## 2. New Module Constants

Add to `dbc_injector.py` after existing constants:

```python
# ---------------------------------------------------------------------------
# LFGDungeons.dbc field layout (3.3.3.11685 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/LFGDungeons.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1-17  Name_lang                    locstr   17 uint32
# 18     MinLevel                     uint32
# 19     MaxLevel                     uint32
# 20     Target_level                 uint32
# 21     Target_level_min             uint32
# 22     Target_level_max             uint32
# 23     MapID                        uint32   FK to Map.dbc
# 24     Difficulty                   uint32   0=normal, 1=heroic
# 25     Flags                        uint32
# 26     TypeID                       uint32   1=dungeon, 2=raid
# 27     Faction                      uint32   -1=both, 0=horde, 1=alliance
# 28     TextureFilename              string   offset into string block
# 29     ExpansionLevel               uint32   0=classic, 1=tbc, 2=wotlk
# 30     Order_index                  uint32   Sort order in LFG UI
# 31     Group_ID                     uint32   Dungeon group
# 32-48  Description_lang             locstr   17 uint32
# Total: 49 fields = 196 bytes
# ---------------------------------------------------------------------------
_LFGDUNGEONS_FIELD_COUNT = 49
_LFGDUNGEONS_RECORD_SIZE = _LFGDUNGEONS_FIELD_COUNT * 4  # 196

# ---------------------------------------------------------------------------
# DungeonEncounter.dbc field layout (3.3.0.10958 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/DungeonEncounter.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapID                        uint32   FK to Map.dbc
#  2     Difficulty                   uint32   0=normal, 1=heroic
#  3     OrderIndex                   uint32   Boss order (0-based)
#  4     Bit                          uint32   Bitmask position
#  5-21  Name_lang                    locstr   17 uint32
# 22     SpellIconID                  uint32   Icon reference
# Total: 23 fields = 92 bytes
# ---------------------------------------------------------------------------
_DUNGEONENCOUNTER_FIELD_COUNT = 23
_DUNGEONENCOUNTER_RECORD_SIZE = _DUNGEONENCOUNTER_FIELD_COUNT * 4  # 92
```

---

## 3. New Record Builder Functions

### 3.1 `_build_lfgdungeons_record()`

Add after `_build_area_record()`:

```python
def _build_lfgdungeons_record(
    dungeon_id,
    name_offset,
    min_level,
    max_level,
    map_id,
    target_level=None,
    target_level_min=None,
    target_level_max=None,
    difficulty=0,
    flags=0,
    type_id=1,
    faction=0xFFFFFFFF,
    texture_filename_offset=0,
    expansion_level=2,
    order_index=0,
    group_id=0,
    description_offset=0,
):
    """
    Build a raw 196-byte LFGDungeons.dbc record for WotLK 3.3.5.

    Args:
        dungeon_id: Unique LFG dungeon ID (auto if None)
        name_offset: String block offset for dungeon name
        min_level: Minimum player level to queue
        max_level: Maximum player level to queue
        map_id: Map.dbc ID for the dungeon instance
        target_level: Average/target level (defaults to min_level if None)
        target_level_min: Target range min (defaults to min_level if None)
        target_level_max: Target range max (defaults to max_level if None)
        difficulty: 0=normal, 1=heroic
        flags: Dungeon flags (typically 0)
        type_id: 1=dungeon, 2=raid, 4=random, 6=random heroic
        faction: 0xFFFFFFFF=both, 0=horde, 1=alliance
        texture_filename_offset: String offset for icon texture (0=none)
        expansion_level: 0=classic, 1=TBC, 2=WotLK
        order_index: Sort order in LFG UI
        group_id: Dungeon group ID (0=none)
        description_offset: String offset for description (0=empty)

    Returns:
        bytes: 196-byte raw record
    """
    # Default target levels to match min/max if not specified
    if target_level is None:
        target_level = min_level
    if target_level_min is None:
        target_level_min = min_level
    if target_level_max is None:
        target_level_max = max_level

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', dungeon_id)
    # 1-17: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 18: MinLevel
    buf += struct.pack('<I', min_level)
    # 19: MaxLevel
    buf += struct.pack('<I', max_level)
    # 20: Target_level
    buf += struct.pack('<I', target_level)
    # 21: Target_level_min
    buf += struct.pack('<I', target_level_min)
    # 22: Target_level_max
    buf += struct.pack('<I', target_level_max)
    # 23: MapID
    buf += struct.pack('<I', map_id)
    # 24: Difficulty
    buf += struct.pack('<I', difficulty)
    # 25: Flags
    buf += struct.pack('<I', flags)
    # 26: TypeID
    buf += struct.pack('<I', type_id)
    # 27: Faction (signed int, but stored as uint32)
    buf += struct.pack('<I', faction)
    # 28: TextureFilename (string offset)
    buf += struct.pack('<I', texture_filename_offset)
    # 29: ExpansionLevel
    buf += struct.pack('<I', expansion_level)
    # 30: Order_index
    buf += struct.pack('<I', order_index)
    # 31: Group_ID
    buf += struct.pack('<I', group_id)
    # 32-48: Description_lang (locstring, 17 uint32)
    buf += _pack_locstring(description_offset)

    assert len(buf) == _LFGDUNGEONS_RECORD_SIZE, (
        "LFGDungeons record size mismatch: expected {}, got {}".format(
            _LFGDUNGEONS_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

**Design Notes:**
- `faction` uses 0xFFFFFFFF for "both factions" (stored as uint32, represents signed -1)
- Auto-defaults `target_level_*` to `min_level`/`max_level` if not specified
- All string fields use offsets into the string block (0 = empty string)
- Assertion validates exact 196-byte record size

---

### 3.2 `_build_dungeonencounter_record()`

Add after `_build_lfgdungeons_record()`:

```python
def _build_dungeonencounter_record(
    encounter_id,
    map_id,
    name_offset,
    order_index,
    bit,
    difficulty=0,
    spell_icon_id=0,
):
    """
    Build a raw 92-byte DungeonEncounter.dbc record for WotLK 3.3.5.

    Args:
        encounter_id: Unique encounter ID (auto if None)
        map_id: Map.dbc ID for the dungeon instance
        name_offset: String block offset for boss name
        order_index: Boss order in dungeon (0-based)
        bit: Bitmask position for encounter state tracking
        difficulty: 0=normal, 1=heroic
        spell_icon_id: SpellIcon.dbc ID for boss icon (0=default)

    Returns:
        bytes: 92-byte raw record
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', encounter_id)
    # 1: MapID
    buf += struct.pack('<I', map_id)
    # 2: Difficulty
    buf += struct.pack('<I', difficulty)
    # 3: OrderIndex
    buf += struct.pack('<I', order_index)
    # 4: Bit
    buf += struct.pack('<I', bit)
    # 5-21: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 22: SpellIconID
    buf += struct.pack('<I', spell_icon_id)

    assert len(buf) == _DUNGEONENCOUNTER_RECORD_SIZE, (
        "DungeonEncounter record size mismatch: expected {}, got {}".format(
            _DUNGEONENCOUNTER_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

**Design Notes:**
- `bit` is typically sequential (0, 1, 2, 3) for bosses in order
- `order_index` determines display order in encounter journal
- `spell_icon_id=0` uses default icon (fine for testing)

---

## 4. Public API Functions

### 4.1 `register_lfg_dungeon()`

Add to public API section after `register_area()`:

```python
def register_lfg_dungeon(
    dbc_dir,
    dungeon_name,
    min_level,
    max_level,
    map_id,
    dungeon_id=None,
    difficulty=0,
    type_id=1,
    faction=0xFFFFFFFF,
    expansion_level=2,
    description=None,
):
    """
    Register a new dungeon in LFGDungeons.dbc.

    Args:
        dbc_dir: Path to directory containing LFGDungeons.dbc.
        dungeon_name: Display name for the dungeon (e.g. "Vault of Storms").
        min_level: Minimum player level to queue.
        max_level: Maximum player level to queue.
        map_id: Map.dbc ID for the dungeon instance.
        dungeon_id: Specific dungeon ID or None for auto (max_id + 1).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        type_id: 1=dungeon, 2=raid. Default: 1 (dungeon).
        faction: 0xFFFFFFFF=both factions (-1 signed), 0=horde, 1=alliance.
                 Default: 0xFFFFFFFF (both).
        expansion_level: 0=classic, 1=TBC, 2=WotLK. Default: 2 (WotLK).
        description: Optional description text (displayed in LFG UI).

    Returns:
        int: The assigned dungeon ID.

    Example:
        dungeon_id = register_lfg_dungeon(
            dbc_dir="./DBFilesClient",
            dungeon_name="Vault of Storms",
            min_level=52,
            max_level=55,
            map_id=800,
            difficulty=0,
            type_id=1,
            faction=0xFFFFFFFF,
            expansion_level=2,
            description="A storm-wracked dungeon beneath Tel'Abim.",
        )
    """
    filepath = os.path.join(dbc_dir, 'LFGDungeons.dbc')
    dbc = DBCInjector(filepath)

    if dungeon_id is None:
        dungeon_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(dungeon_name)
    desc_offset = dbc.add_string(description) if description else 0

    record = _build_lfgdungeons_record(
        dungeon_id=dungeon_id,
        name_offset=name_offset,
        min_level=min_level,
        max_level=max_level,
        map_id=map_id,
        difficulty=difficulty,
        type_id=type_id,
        faction=faction,
        expansion_level=expansion_level,
        description_offset=desc_offset,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return dungeon_id
```

**Usage Notes:**
- `faction=0xFFFFFFFF` (default) makes dungeon available to both Horde and Alliance
- `type_id=1` marks as dungeon (not raid)
- `difficulty=0` for normal mode (use 1 for heroic)
- Auto-computes `target_level_*` from `min_level`/`max_level`

---

### 4.2 `register_dungeon_encounter()`

Add after `register_lfg_dungeon()`:

```python
def register_dungeon_encounter(
    dbc_dir,
    boss_name,
    map_id,
    order_index,
    bit,
    encounter_id=None,
    difficulty=0,
    spell_icon_id=0,
):
    """
    Register a single boss encounter in DungeonEncounter.dbc.

    Args:
        dbc_dir: Path to directory containing DungeonEncounter.dbc.
        boss_name: Display name for the boss (e.g. "Shade of Zhar'kaan").
        map_id: Map.dbc ID for the dungeon instance.
        order_index: Boss order in dungeon (0-based, e.g. 0=first boss).
        bit: Bitmask position for encounter state tracking (typically 0-based).
        encounter_id: Specific encounter ID or None for auto (max_id + 1).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        spell_icon_id: SpellIcon.dbc ID for boss icon. Default: 0 (generic).

    Returns:
        int: The assigned encounter ID.

    Example:
        encounter_id = register_dungeon_encounter(
            dbc_dir="./DBFilesClient",
            boss_name="Shade of Zhar'kaan",
            map_id=800,
            order_index=0,
            bit=0,
            difficulty=0,
        )
    """
    filepath = os.path.join(dbc_dir, 'DungeonEncounter.dbc')
    dbc = DBCInjector(filepath)

    if encounter_id is None:
        encounter_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(boss_name)

    record = _build_dungeonencounter_record(
        encounter_id=encounter_id,
        map_id=map_id,
        name_offset=name_offset,
        order_index=order_index,
        bit=bit,
        difficulty=difficulty,
        spell_icon_id=spell_icon_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return encounter_id
```

**Usage Notes:**
- `order_index` and `bit` are typically sequential: 0, 1, 2, 3 for a 4-boss dungeon
- `bit` is used by server to track which bosses have been killed (bitmask position)
- `spell_icon_id=0` uses default icon (sufficient for basic functionality)

---

### 4.3 `register_dungeon_encounters()` (Convenience Wrapper)

Add after `register_dungeon_encounter()`:

```python
def register_dungeon_encounters(
    dbc_dir,
    map_id,
    boss_names,
    difficulty=0,
    starting_encounter_id=None,
):
    """
    Register multiple boss encounters for a dungeon (convenience wrapper).

    Automatically assigns sequential order_index and bit values starting from 0.

    Args:
        dbc_dir: Path to directory containing DungeonEncounter.dbc.
        map_id: Map.dbc ID for the dungeon instance.
        boss_names: List of boss names in order (e.g. ["Boss 1", "Boss 2", ...]).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        starting_encounter_id: First encounter ID to use, or None for auto.

    Returns:
        list[int]: List of assigned encounter IDs in order.

    Example:
        encounter_ids = register_dungeon_encounters(
            dbc_dir="./DBFilesClient",
            map_id=800,
            boss_names=[
                "Shade of Zhar'kaan",
                "Overseer V-7",
                "Gorgash Stormfather",
                "Zhar'kaan the Stormheart",
            ],
            difficulty=0,
        )
        # Returns: [auto_id, auto_id+1, auto_id+2, auto_id+3]
    """
    filepath = os.path.join(dbc_dir, 'DungeonEncounter.dbc')
    dbc = DBCInjector(filepath)

    if starting_encounter_id is None:
        starting_encounter_id = dbc.get_max_id() + 1

    encounter_ids = []
    for i, boss_name in enumerate(boss_names):
        encounter_id = starting_encounter_id + i
        name_offset = dbc.add_string(boss_name)

        record = _build_dungeonencounter_record(
            encounter_id=encounter_id,
            map_id=map_id,
            name_offset=name_offset,
            order_index=i,  # Sequential: 0, 1, 2, 3
            bit=i,          # Sequential: 0, 1, 2, 3
            difficulty=difficulty,
            spell_icon_id=0,
        )

        dbc.records.append(record)
        encounter_ids.append(encounter_id)

    dbc.write(filepath)

    return encounter_ids
```

**Design Benefits:**
- Single function call to register all bosses
- Auto-increments `order_index` and `bit` (0, 1, 2, 3, ...)
- Batch writes DBC once at end (efficient)
- Returns list of assigned IDs for reference

---

## 5. Tel'Abim Vault of Storms Usage Example

### 5.1 Scenario: Registering Vault of Storms

**Dungeon Details:**
- **Name:** "Vault of Storms"
- **Location:** Tel'Abim island (custom map)
- **Level Range:** 52-55
- **Type:** Normal dungeon (5-player)
- **Faction:** Both Horde and Alliance
- **Expansion:** WotLK (2)
- **Bosses:**
  1. Shade of Zhar'kaan (first encounter)
  2. Overseer V-7 (mechanical boss)
  3. Gorgash Stormfather (elemental boss)
  4. Zhar'kaan the Stormheart (final boss)

---

### 5.2 Implementation Code

```python
from world_builder.dbc_injector import (
    register_map,
    register_area,
    register_lfg_dungeon,
    register_dungeon_encounters,
)

# Step 1: Register the dungeon map (if not already done)
map_id = register_map(
    dbc_dir="./DBFilesClient",
    map_name="TelAbimVault",
    instance_type=1,  # Party dungeon
)
# Returns: 800 (example)

# Step 2: Register the area
area_id = register_area(
    dbc_dir="./DBFilesClient",
    area_name="Vault of Storms",
    map_id=map_id,
)
# Returns: 5001 (example)

# Step 3: Register the LFG dungeon entry
dungeon_id = register_lfg_dungeon(
    dbc_dir="./DBFilesClient",
    dungeon_name="Vault of Storms",
    min_level=52,
    max_level=55,
    map_id=map_id,
    difficulty=0,       # Normal mode
    type_id=1,          # Dungeon (not raid)
    faction=0xFFFFFFFF, # Both factions
    expansion_level=2,  # WotLK
    description="A storm-wracked dungeon beneath Tel'Abim.",
)
# Returns: 1001 (example)

# Step 4: Register all boss encounters (convenience wrapper)
encounter_ids = register_dungeon_encounters(
    dbc_dir="./DBFilesClient",
    map_id=map_id,
    boss_names=[
        "Shade of Zhar'kaan",
        "Overseer V-7",
        "Gorgash Stormfather",
        "Zhar'kaan the Stormheart",
    ],
    difficulty=0,  # Normal mode
)
# Returns: [2001, 2002, 2003, 2004] (example)

print(f"Registered dungeon ID {dungeon_id} with {len(encounter_ids)} bosses")
# Output: "Registered dungeon ID 1001 with 4 bosses"
```

---

### 5.3 Alternative: Manual Encounter Registration

If you need fine-grained control (e.g., different difficulties per boss):

```python
from world_builder.dbc_injector import register_dungeon_encounter

# Register each boss individually
boss1_id = register_dungeon_encounter(
    dbc_dir="./DBFilesClient",
    boss_name="Shade of Zhar'kaan",
    map_id=800,
    order_index=0,
    bit=0,
    difficulty=0,
)

boss2_id = register_dungeon_encounter(
    dbc_dir="./DBFilesClient",
    boss_name="Overseer V-7",
    map_id=800,
    order_index=1,
    bit=1,
    difficulty=0,
)

boss3_id = register_dungeon_encounter(
    dbc_dir="./DBFilesClient",
    boss_name="Gorgash Stormfather",
    map_id=800,
    order_index=2,
    bit=2,
    difficulty=0,
)

boss4_id = register_dungeon_encounter(
    dbc_dir="./DBFilesClient",
    boss_name="Zhar'kaan the Stormheart",
    map_id=800,
    order_index=3,
    bit=3,
    difficulty=0,
)
```

---

## 6. Integration with `build_zone()`

### 6.1 Optional DBC Registration

Extend the `build_zone()` function in `world_builder/__init__.py` to support optional LFG registration:

```python
def build_zone(
    name,
    output_dir,
    coords,
    heightmap=None,
    texture_paths=None,
    dbc_dir=None,
    instance_type=0,
    lfg_dungeon=None,  # NEW: dict with LFG parameters
    boss_names=None,   # NEW: list of boss names
    **kwargs
):
    """
    Build a complete WoW zone with optional LFG registration.

    New Args:
        lfg_dungeon: Optional dict with LFG dungeon parameters:
            {
                'min_level': int,
                'max_level': int,
                'difficulty': int (0=normal, 1=heroic),
                'type_id': int (1=dungeon, 2=raid),
                'faction': int (0xFFFFFFFF=both),
                'expansion_level': int (0=classic, 1=TBC, 2=WotLK),
                'description': str (optional),
            }
        boss_names: Optional list of boss names (for DungeonEncounter.dbc).
                    If provided, registers encounters with auto-incremented
                    order_index and bit values.

    Example:
        result = build_zone(
            name="TelAbimVault",
            output_dir="./output",
            coords=[(32, 32), (32, 33)],
            dbc_dir="./DBFilesClient",
            instance_type=1,
            lfg_dungeon={
                'min_level': 52,
                'max_level': 55,
                'difficulty': 0,
                'type_id': 1,
                'faction': 0xFFFFFFFF,
                'expansion_level': 2,
                'description': "A storm-wracked dungeon beneath Tel'Abim.",
            },
            boss_names=[
                "Shade of Zhar'kaan",
                "Overseer V-7",
                "Gorgash Stormfather",
                "Zhar'kaan the Stormheart",
            ],
        )
        # result['dungeon_id'] = 1001
        # result['encounter_ids'] = [2001, 2002, 2003, 2004]
    """
    from .dbc_injector import (
        register_map,
        register_area,
        register_lfg_dungeon,
        register_dungeon_encounters,
    )

    # ... existing build_zone logic ...

    result = {
        'map_id': map_id,
        'area_id': area_id,
        # ... existing fields ...
    }

    # NEW: Optional LFG registration
    if lfg_dungeon and dbc_dir:
        dungeon_id = register_lfg_dungeon(
            dbc_dir=dbc_dir,
            dungeon_name=name,
            map_id=map_id,
            **lfg_dungeon,
        )
        result['dungeon_id'] = dungeon_id

        # NEW: Optional boss encounter registration
        if boss_names:
            encounter_ids = register_dungeon_encounters(
                dbc_dir=dbc_dir,
                map_id=map_id,
                boss_names=boss_names,
                difficulty=lfg_dungeon.get('difficulty', 0),
            )
            result['encounter_ids'] = encounter_ids

    return result
```

---

### 6.2 Simplified Tel'Abim Integration

With the `build_zone()` extension, the entire workflow becomes:

```python
from world_builder import build_zone

result = build_zone(
    name="TelAbimVault",
    output_dir="./output/TelAbimVault",
    coords=[(32, 32), (32, 33), (33, 32)],
    dbc_dir="./DBFilesClient",
    instance_type=1,
    lfg_dungeon={
        'min_level': 52,
        'max_level': 55,
        'difficulty': 0,
        'type_id': 1,
        'faction': 0xFFFFFFFF,
        'expansion_level': 2,
        'description': "A storm-wracked dungeon beneath Tel'Abim.",
    },
    boss_names=[
        "Shade of Zhar'kaan",
        "Overseer V-7",
        "Gorgash Stormfather",
        "Zhar'kaan the Stormheart",
    ],
)

# Output:
# {
#     'map_id': 800,
#     'area_id': 5001,
#     'dungeon_id': 1001,
#     'encounter_ids': [2001, 2002, 2003, 2004],
#     'wdt_path': '...',
#     'adt_paths': ['...'],
#     'output_dir': '...',
# }
```

---

## 7. Testing Approach

### 7.1 Unit Tests

Create `tests/test_dbc_dungeon_injector.py`:

```python
import os
import tempfile
import shutil
from world_builder.dbc_injector import (
    DBCInjector,
    register_lfg_dungeon,
    register_dungeon_encounter,
    register_dungeon_encounters,
)

def test_lfgdungeons_record_size():
    """Test LFGDungeons.dbc record structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC
        dbc = DBCInjector()
        dbc.field_count = 49
        dbc.record_size = 196
        dbc_path = os.path.join(tmpdir, 'LFGDungeons.dbc')
        dbc.write(dbc_path)

        # Register dungeon
        dungeon_id = register_lfg_dungeon(
            dbc_dir=tmpdir,
            dungeon_name="Test Dungeon",
            min_level=50,
            max_level=60,
            map_id=999,
        )

        # Verify
        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 1
        assert dbc2.field_count == 49
        assert dbc2.record_size == 196
        assert len(dbc2.records[0]) == 196
        assert dbc2.get_record_field(0, 0) == dungeon_id  # ID
        assert dbc2.get_record_field(0, 23) == 999         # MapID

def test_dungeonencounter_record_size():
    """Test DungeonEncounter.dbc record structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC
        dbc = DBCInjector()
        dbc.field_count = 23
        dbc.record_size = 92
        dbc_path = os.path.join(tmpdir, 'DungeonEncounter.dbc')
        dbc.write(dbc_path)

        # Register encounter
        encounter_id = register_dungeon_encounter(
            dbc_dir=tmpdir,
            boss_name="Test Boss",
            map_id=999,
            order_index=0,
            bit=0,
        )

        # Verify
        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 1
        assert dbc2.field_count == 23
        assert dbc2.record_size == 92
        assert len(dbc2.records[0]) == 92
        assert dbc2.get_record_field(0, 0) == encounter_id  # ID
        assert dbc2.get_record_field(0, 1) == 999            # MapID
        assert dbc2.get_record_field(0, 3) == 0              # OrderIndex
        assert dbc2.get_record_field(0, 4) == 0              # Bit

def test_register_dungeon_encounters_batch():
    """Test batch registration of multiple encounters"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC
        dbc = DBCInjector()
        dbc.field_count = 23
        dbc.record_size = 92
        dbc_path = os.path.join(tmpdir, 'DungeonEncounter.dbc')
        dbc.write(dbc_path)

        # Register 4 bosses
        boss_names = ["Boss 1", "Boss 2", "Boss 3", "Boss 4"]
        encounter_ids = register_dungeon_encounters(
            dbc_dir=tmpdir,
            map_id=800,
            boss_names=boss_names,
        )

        # Verify
        assert len(encounter_ids) == 4
        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 4

        for i in range(4):
            assert dbc2.get_record_field(i, 1) == 800  # MapID
            assert dbc2.get_record_field(i, 3) == i    # OrderIndex
            assert dbc2.get_record_field(i, 4) == i    # Bit

def test_vault_of_storms_integration():
    """Test complete Vault of Storms registration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup empty DBCs
        for filename, field_count, record_size in [
            ('LFGDungeons.dbc', 49, 196),
            ('DungeonEncounter.dbc', 23, 92),
        ]:
            dbc = DBCInjector()
            dbc.field_count = field_count
            dbc.record_size = record_size
            dbc.write(os.path.join(tmpdir, filename))

        # Register dungeon
        dungeon_id = register_lfg_dungeon(
            dbc_dir=tmpdir,
            dungeon_name="Vault of Storms",
            min_level=52,
            max_level=55,
            map_id=800,
            difficulty=0,
            type_id=1,
            faction=0xFFFFFFFF,
            expansion_level=2,
            description="A storm-wracked dungeon beneath Tel'Abim.",
        )

        # Register bosses
        encounter_ids = register_dungeon_encounters(
            dbc_dir=tmpdir,
            map_id=800,
            boss_names=[
                "Shade of Zhar'kaan",
                "Overseer V-7",
                "Gorgash Stormfather",
                "Zhar'kaan the Stormheart",
            ],
        )

        # Verify dungeon
        lfg_dbc = DBCInjector(os.path.join(tmpdir, 'LFGDungeons.dbc'))
        assert lfg_dbc.record_count == 1
        assert lfg_dbc.get_record_field(0, 18) == 52   # MinLevel
        assert lfg_dbc.get_record_field(0, 19) == 55   # MaxLevel
        assert lfg_dbc.get_record_field(0, 23) == 800  # MapID
        assert lfg_dbc.get_record_field(0, 26) == 1    # TypeID (dungeon)

        # Verify encounters
        enc_dbc = DBCInjector(os.path.join(tmpdir, 'DungeonEncounter.dbc'))
        assert enc_dbc.record_count == 4
        assert len(encounter_ids) == 4
```

---

### 7.2 Manual Validation

1. **Hex Dump Verification:**
   ```bash
   hexdump -C DBFilesClient/LFGDungeons.dbc | head -50
   hexdump -C DBFilesClient/DungeonEncounter.dbc | head -50
   ```
   - Verify header: `WDBC` magic
   - Verify record count
   - Verify field count (49 for LFGDungeons, 23 for DungeonEncounter)
   - Verify record size (196 for LFGDungeons, 92 for DungeonEncounter)

2. **String Block Validation:**
   ```python
   from world_builder.dbc_injector import DBCInjector

   dbc = DBCInjector('DBFilesClient/LFGDungeons.dbc')
   last_record = dbc.records[-1]
   name_offset = struct.unpack_from('<I', last_record, 4)[0]
   print(dbc.get_string(name_offset))  # Should print "Vault of Storms"
   ```

3. **In-Game Testing:**
   - Launch WoW 3.3.5a client with modified DBCs
   - Open Dungeon Finder (LFG tool)
   - Verify "Vault of Storms" appears in dungeon list
   - Verify level range (52-55) and description display correctly
   - Enter instance and check encounter journal (if accessible)

---

### 7.3 Client Crash Prevention

**Common Pitfalls:**
- **Wrong record size:** Client expects exact 196/92 bytes per record
- **Wrong field count:** Header must match actual field count (49/23)
- **Invalid string offsets:** Offsets beyond string block size crash client
- **Missing null terminator:** String block must end with `\x00`

**Validation Checklist:**
- [ ] Header `field_count` matches constant (49 or 23)
- [ ] Header `record_size` matches constant (196 or 92)
- [ ] All records are exactly `record_size` bytes
- [ ] String block starts with `\x00` at offset 0
- [ ] All string offsets point within string block bounds
- [ ] All strings are null-terminated
- [ ] String block size matches actual block length

---

## 8. Code Style Alignment

### 8.1 Follow Existing Patterns

**From `dbc_injector.py`:**
- Use `_build_*_record()` naming for internal record builders
- Use `register_*()` naming for public API functions
- All string arguments to builders must be offsets (not raw strings)
- Use `DBCInjector.add_string()` for string deduplication
- Add field layout comments with byte offsets and counts
- Include assertions for record size validation
- Use `os.path.join()` for path construction
- Return assigned ID from registration functions

**Docstring Format:**
```python
def function_name(param1, param2):
    """
    Brief description (one line).

    Args:
        param1: Description.
        param2: Description.

    Returns:
        type: Description.

    Example:
        result = function_name(...)
    """
```

---

### 8.2 Constants Naming

- `_LFGDUNGEONS_FIELD_COUNT` (uppercase, prefixed with `_`)
- `_LFGDUNGEONS_RECORD_SIZE` (calculated from field count)
- `_DUNGEONENCOUNTER_FIELD_COUNT`
- `_DUNGEONENCOUNTER_RECORD_SIZE`

---

### 8.3 Import Organization

Keep imports minimal and organized:
```python
import struct
import os
# No external dependencies
```

---

## 9. Documentation Updates

### 9.1 Update `ROADMAP.md`

Add new section after "Phase 3: The DBC Injector":

```markdown
### Phase 3.1: LFG Dungeon Injectors

Extends `dbc_injector.py` to support LFGDungeons.dbc and DungeonEncounter.dbc.

**Implemented:**
- `register_lfg_dungeon()` — Register dungeon in LFG system
- `register_dungeon_encounter()` — Register single boss encounter
- `register_dungeon_encounters()` — Batch register multiple bosses

**DBC Schemas:**
- LFGDungeons.dbc: 49 fields, 196 bytes per record
- DungeonEncounter.dbc: 23 fields, 92 bytes per record

**Example Usage:**
```python
# Register dungeon
dungeon_id = register_lfg_dungeon(
    dbc_dir="./DBFilesClient",
    dungeon_name="Vault of Storms",
    min_level=52,
    max_level=55,
    map_id=800,
)

# Register bosses
encounter_ids = register_dungeon_encounters(
    dbc_dir="./DBFilesClient",
    map_id=800,
    boss_names=["Boss 1", "Boss 2", "Boss 3", "Boss 4"],
)
```
```

---

### 9.2 Update Module Docstring

Add to `dbc_injector.py` docstring:

```python
"""
DBC file injector for WoW WotLK 3.3.5a (build 12340).

Provides low-level binary read/write of DBC files and convenience functions
for injecting custom Map, AreaTable, LFGDungeons, and DungeonEncounter entries.
Works directly with raw bytes so it does not depend on the DBD definition
infrastructure.

Supported DBC files:
- Map.dbc: World map entries (66 fields, 264 bytes)
- AreaTable.dbc: Zone/area entries (36 fields, 144 bytes)
- LFGDungeons.dbc: LFG dungeon entries (49 fields, 196 bytes)
- DungeonEncounter.dbc: Boss encounter entries (23 fields, 92 bytes)

...
"""
```

---

## 10. Implementation Checklist

### 10.1 Code Changes

- [ ] Add `_LFGDUNGEONS_FIELD_COUNT` and `_LFGDUNGEONS_RECORD_SIZE` constants
- [ ] Add `_DUNGEONENCOUNTER_FIELD_COUNT` and `_DUNGEONENCOUNTER_RECORD_SIZE` constants
- [ ] Implement `_build_lfgdungeons_record()` with 196-byte layout
- [ ] Implement `_build_dungeonencounter_record()` with 92-byte layout
- [ ] Implement `register_lfg_dungeon()` public API
- [ ] Implement `register_dungeon_encounter()` public API
- [ ] Implement `register_dungeon_encounters()` convenience wrapper
- [ ] Update module docstring to mention new DBC support
- [ ] Add field layout comments for both DBCs

---

### 10.2 Testing

- [ ] Write `test_lfgdungeons_record_size()` unit test
- [ ] Write `test_dungeonencounter_record_size()` unit test
- [ ] Write `test_register_dungeon_encounters_batch()` unit test
- [ ] Write `test_vault_of_storms_integration()` end-to-end test
- [ ] Run manual hex dump validation
- [ ] Test in-game with WoW 3.3.5a client

---

### 10.3 Documentation

- [ ] Update `ROADMAP.md` with Phase 3.1 section
- [ ] Add Tel'Abim usage example to module docstring
- [ ] Document faction field behavior (0xFFFFFFFF = both)
- [ ] Document bit field usage for encounter tracking

---

### 10.4 Integration (Optional)

- [ ] Extend `build_zone()` with `lfg_dungeon` parameter
- [ ] Extend `build_zone()` with `boss_names` parameter
- [ ] Update `build_zone()` docstring with new parameters
- [ ] Add `dungeon_id` and `encounter_ids` to return dict

---

## 11. Future Enhancements

### 11.1 Heroic Mode Support

Add convenience function for registering both normal and heroic versions:

```python
def register_lfg_dungeon_with_heroic(
    dbc_dir,
    dungeon_name,
    min_level,
    max_level,
    map_id,
    boss_names,
    **kwargs
):
    """Register both normal and heroic versions of a dungeon."""
    # Normal mode
    normal_id = register_lfg_dungeon(
        dbc_dir, dungeon_name, min_level, max_level, map_id,
        difficulty=0, **kwargs
    )
    normal_encounters = register_dungeon_encounters(
        dbc_dir, map_id, boss_names, difficulty=0
    )

    # Heroic mode
    heroic_name = f"{dungeon_name} (Heroic)"
    heroic_id = register_lfg_dungeon(
        dbc_dir, heroic_name, min_level + 5, max_level + 5, map_id,
        difficulty=1, **kwargs
    )
    heroic_encounters = register_dungeon_encounters(
        dbc_dir, map_id, boss_names, difficulty=1
    )

    return {
        'normal': {'dungeon_id': normal_id, 'encounter_ids': normal_encounters},
        'heroic': {'dungeon_id': heroic_id, 'encounter_ids': heroic_encounters},
    }
```

---

### 11.2 Validation Functions

```python
def validate_lfgdungeons_dbc(dbc_path):
    """Validate LFGDungeons.dbc structure and return diagnostics."""
    dbc = DBCInjector(dbc_path)
    issues = []

    if dbc.field_count != 49:
        issues.append(f"Wrong field count: {dbc.field_count}, expected 49")
    if dbc.record_size != 196:
        issues.append(f"Wrong record size: {dbc.record_size}, expected 196")

    for i, rec in enumerate(dbc.records):
        if len(rec) != 196:
            issues.append(f"Record {i}: wrong size {len(rec)}, expected 196")

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'record_count': dbc.record_count,
    }
```

---

### 11.3 Extended Metadata

Support additional LFGDungeons fields for future expansion:
- `texture_filename`: Icon texture path
- `order_index`: Custom sort order in UI
- `group_id`: Dungeon group categorization

---

## 12. Reference Materials

### 12.1 WoW Client Constants

**Difficulty Values:**
- 0 = Normal (5-player)
- 1 = Heroic (5-player)
- 2 = Normal (10-player raid, WotLK)
- 3 = Heroic (25-player raid, WotLK)

**Type ID Values:**
- 1 = Dungeon (5-player)
- 2 = Raid (10/25-player)
- 4 = Random Dungeon
- 6 = Random Heroic Dungeon

**Faction Values:**
- 0xFFFFFFFF (-1 signed) = Both factions
- 0 = Horde only
- 1 = Alliance only

**Expansion Level Values:**
- 0 = Classic (1-60)
- 1 = The Burning Crusade (61-70)
- 2 = Wrath of the Lich King (71-80)

---

### 12.2 File Locations

**DBC Files (Client):**
- `World\DBFilesClient\LFGDungeons.dbc`
- `World\DBFilesClient\DungeonEncounter.dbc`

**DBD Definitions (Reference):**
- `wdbx/dbd/definitions/LFGDungeons.dbd`
- `wdbx/dbd/definitions/DungeonEncounter.dbd`

---

### 12.3 External Resources

- **WoW.tools:** https://wow.tools/dbc/?dbc=lfgdungeons&build=3.3.5.12340
- **WoWDev Wiki:** https://wowdev.wiki/DB/LFGDungeons
- **TrinityCore DBC Docs:** https://github.com/TrinityCore/TrinityCore/tree/3.3.5/sql/base/dbc

---

## Summary

This plan provides a complete implementation roadmap for LFGDungeons.dbc and DungeonEncounter.dbc injectors following the existing `dbc_injector.py` patterns. The implementation:

1. **Adds two new DBC types** with correct WotLK 3.3.5a field layouts
2. **Provides three public API functions** for flexible usage
3. **Includes convenience wrapper** for batch boss registration
4. **Enables TODO 1.3** for Vault of Storms dungeon registration
5. **Maintains code consistency** with existing module style
6. **Includes comprehensive testing** approach
7. **Documents integration** with `build_zone()` workflow

**Next Steps:**
1. Implement constants and record builder functions
2. Implement public API functions
3. Write unit tests
4. Test with real WoW 3.3.5a client
5. Document in ROADMAP.md
6. Optional: Integrate with `build_zone()`
