# Plan: DBC Zone Display Injectors

## Overview

This plan extends the `world_builder/dbc_injector.py` module to support zone display and loading screens by implementing three additional DBC injectors for WotLK 3.3.5a (build 12340):

1. **WorldMapArea.dbc** - Defines map area display regions (zone boundaries on world map)
2. **WorldMapOverlay.dbc** - Adds overlay textures to world map areas (POIs, sub-zones)
3. **LoadingScreens.dbc** - Controls loading screen images for zones

These injectors enable TODO item **1.3 DBC Patches** from the Tel'Abim zone implementation roadmap.

---

## 1. Project Context

### Existing Infrastructure

The `dbc_injector.py` module already provides:
- `DBCInjector` class for low-level binary DBC read/write
- String block management with automatic deduplication
- Locstring packing (17 uint32: 8 locale slots + 8 unused + 1 mask)
- Two convenience functions: `register_map()` and `register_area()`

### Tel'Abim Zone Requirements (TODO 1.3)

When implementing the Tel'Abim custom zone, the following DBC entries are needed:

**WorldMapArea.dbc entries:**
- Main zone entry: "Tel'Abim" (MapID=800, AreaID=5001)
- Coordinates: locates zone on world map (South Seas region)
- Display settings: proper zoom bounds for map interface

**WorldMapOverlay.dbc entries:**
- Zone boundary overlay texture
- POI markers (towns, landmarks, quest hubs)
- Sub-zone highlights

**LoadingScreens.dbc entry:**
- Custom loading screen: "LoadScreenTelAbim.blp"
- Wide screen support flag
- Links to Map.dbc entry via LoadingScreenID field

---

## 2. DBC Field Layouts (WotLK 3.3.5 Build 12340)

### 2.1 WorldMapArea.dbc

**Source:** `wdbx/dbd/definitions/WorldMapArea.dbd` (BUILD 3.2.0.10192-3.3.5.12340)

**Record Layout:** 11 fields × 4 bytes = **44 bytes per record**

```
Offset  Field                    Type      Description
------  -----------------------  --------  ------------------------------------
0x00    ID                       uint32    Unique WorldMapArea ID
0x04    MapID                    uint32    FK to Map.dbc (continent/instance)
0x08    AreaID                   uint32    FK to AreaTable.dbc (zone ID)
0x0C    AreaName                 uint32    String offset (display name)
0x10    LocLeft                  float     Left boundary (X coordinate)
0x14    LocRight                 float     Right boundary (X coordinate)
0x18    LocTop                   float     Top boundary (Y coordinate)
0x1C    LocBottom                float     Bottom boundary (Y coordinate)
0x20    DisplayMapID             uint32    Map to display on (-1 for self)
0x24    DefaultDungeonFloor      uint32    Default floor for dungeons (0 for zones)
0x28    ParentWorldMapID         uint32    FK to parent WorldMapArea (-1 for top-level)
```

**Field Count:** 11
**Record Size:** 44 bytes
**String Fields:** AreaName (offset 0x0C)

### 2.2 WorldMapOverlay.dbc

**Source:** `wdbx/dbd/definitions/WorldMapOverlay.dbd` (BUILD 3.0.1.8303-3.3.5.12340)

**Record Layout:** 15 fields = **60 bytes per record**

```
Offset  Field                    Type      Description
------  -----------------------  --------  ------------------------------------
0x00    ID                       uint32    Unique WorldMapOverlay ID
0x04    MapAreaID                uint32    FK to WorldMapArea.dbc
0x08    AreaID[0]                uint32    FK to AreaTable (area 1)
0x0C    AreaID[1]                uint32    FK to AreaTable (area 2)
0x10    AreaID[2]                uint32    FK to AreaTable (area 3)
0x14    AreaID[3]                uint32    FK to AreaTable (area 4)
0x18    MapPointX                uint32    X position on map
0x1C    MapPointY                uint32    Y position on map
0x20    TextureName              uint32    String offset (overlay texture path)
0x24    TextureWidth             uint32    Texture width in pixels
0x28    TextureHeight            uint32    Texture height in pixels
0x2C    OffsetX                  uint32    X offset for rendering
0x30    OffsetY                  uint32    Y offset for rendering
0x34    HitRectTop               uint32    Click detection - top edge
0x38    HitRectLeft              uint32    Click detection - left edge
0x3C    HitRectBottom            uint32    Click detection - bottom edge
0x40    HitRectRight             uint32    Click detection - right edge
```

**Field Count:** 15
**Record Size:** 60 bytes
**String Fields:** TextureName (offset 0x20)
**Array Fields:** AreaID[4] (offsets 0x08-0x14)

### 2.3 LoadingScreens.dbc

**Source:** `wdbx/dbd/definitions/LoadingScreens.dbd` (BUILD 3.3.0.10958-3.3.5.12340)

**Record Layout:** 4 fields × 4 bytes = **16 bytes per record**

```
Offset  Field                    Type      Description
------  -----------------------  --------  ------------------------------------
0x00    ID                       uint32    Unique LoadingScreen ID
0x04    Name                     uint32    String offset (internal name)
0x08    FileName                 uint32    String offset (BLP texture path)
0x0C    HasWideScreen            uint32    0=standard, 1=supports widescreen
```

**Field Count:** 4
**Record Size:** 16 bytes
**String Fields:** Name (offset 0x04), FileName (offset 0x08)

---

## 3. Implementation Plan

### 3.1 Code Structure

All code will be added to `D:\Test\wow-pywowlib\world_builder\dbc_injector.py` following the existing pattern.

**Additions:**
1. Field layout constants (3 DBC types)
2. Record builder functions (3 private helpers)
3. Public registration functions (3 API functions)

### 3.2 Field Layout Constants

Add after existing `_AREA_RECORD_SIZE` (line 88):

```python
# ---------------------------------------------------------------------------
# WorldMapArea.dbc field layout (3.2.0.10192 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/WorldMapArea.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapID                        uint32
#  2     AreaID                       uint32
#  3     AreaName                     string   (offset into string block)
#  4     LocLeft                      float
#  5     LocRight                     float
#  6     LocTop                       float
#  7     LocBottom                    float
#  8     DisplayMapID                 uint32
#  9     DefaultDungeonFloor          uint32
# 10     ParentWorldMapID             uint32
# Total: 11 fields = 44 bytes
# ---------------------------------------------------------------------------
_WORLDMAPAREA_FIELD_COUNT = 11
_WORLDMAPAREA_RECORD_SIZE = _WORLDMAPAREA_FIELD_COUNT * 4  # 44

# ---------------------------------------------------------------------------
# WorldMapOverlay.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/WorldMapOverlay.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapAreaID                    uint32
#  2-5   AreaID[4]                   uint32[4]
#  6     MapPointX                    uint32
#  7     MapPointY                    uint32
#  8     TextureName                  string   (offset into string block)
#  9     TextureWidth                 uint32
# 10     TextureHeight                uint32
# 11     OffsetX                      uint32
# 12     OffsetY                      uint32
# 13     HitRectTop                   uint32
# 14     HitRectLeft                  uint32
# 15     HitRectBottom                uint32
# 16     HitRectRight                 uint32
# Total: 15 fields = 60 bytes
# ---------------------------------------------------------------------------
_WORLDMAPOVERLAY_FIELD_COUNT = 15
_WORLDMAPOVERLAY_RECORD_SIZE = _WORLDMAPOVERLAY_FIELD_COUNT * 4  # 60

# ---------------------------------------------------------------------------
# LoadingScreens.dbc field layout (3.3.0.10958 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/LoadingScreens.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     Name                         string   (offset into string block)
#  2     FileName                     string   (offset into string block)
#  3     HasWideScreen                uint32
# Total: 4 fields = 16 bytes
# ---------------------------------------------------------------------------
_LOADINGSCREENS_FIELD_COUNT = 4
_LOADINGSCREENS_RECORD_SIZE = _LOADINGSCREENS_FIELD_COUNT * 4  # 16
```

### 3.3 Record Builder Functions

Add after `_build_area_record()` (before line 386):

```python
def _build_worldmaparea_record(
    worldmaparea_id,
    map_id,
    area_id,
    area_name_offset,
    loc_left=0.0,
    loc_right=0.0,
    loc_top=0.0,
    loc_bottom=0.0,
    display_map_id=-1,
    default_dungeon_floor=0,
    parent_worldmap_id=-1,
):
    """
    Build a raw 44-byte WorldMapArea.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        worldmaparea_id: Unique ID for this world map area entry.
        map_id: Map ID (FK to Map.dbc).
        area_id: Area ID (FK to AreaTable.dbc).
        area_name_offset: String offset for display name.
        loc_left: Left boundary X coordinate (float).
        loc_right: Right boundary X coordinate (float).
        loc_top: Top boundary Y coordinate (float).
        loc_bottom: Bottom boundary Y coordinate (float).
        display_map_id: Map to display on (-1 = use own map).
        default_dungeon_floor: Default floor level (0 for outdoor zones).
        parent_worldmap_id: Parent map area ID (-1 = top-level).
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', worldmaparea_id)
    # 1: MapID
    buf += struct.pack('<I', map_id)
    # 2: AreaID
    buf += struct.pack('<I', area_id)
    # 3: AreaName (string offset)
    buf += struct.pack('<I', area_name_offset)
    # 4: LocLeft
    buf += struct.pack('<f', loc_left)
    # 5: LocRight
    buf += struct.pack('<f', loc_right)
    # 6: LocTop
    buf += struct.pack('<f', loc_top)
    # 7: LocBottom
    buf += struct.pack('<f', loc_bottom)
    # 8: DisplayMapID (signed -1 stored as uint32 0xFFFFFFFF)
    buf += struct.pack('<i', display_map_id)
    # 9: DefaultDungeonFloor
    buf += struct.pack('<I', default_dungeon_floor)
    # 10: ParentWorldMapID (signed -1 stored as uint32 0xFFFFFFFF)
    buf += struct.pack('<i', parent_worldmap_id)

    assert len(buf) == _WORLDMAPAREA_RECORD_SIZE, (
        "WorldMapArea record size mismatch: expected {}, got {}".format(
            _WORLDMAPAREA_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_worldmapoverlay_record(
    worldmapoverlay_id,
    map_area_id,
    texture_name_offset,
    area_ids=None,
    map_point_x=0,
    map_point_y=0,
    texture_width=0,
    texture_height=0,
    offset_x=0,
    offset_y=0,
    hit_rect_top=0,
    hit_rect_left=0,
    hit_rect_bottom=0,
    hit_rect_right=0,
):
    """
    Build a raw 60-byte WorldMapOverlay.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        worldmapoverlay_id: Unique ID for this overlay entry.
        map_area_id: WorldMapArea ID this overlay belongs to.
        texture_name_offset: String offset for overlay texture path.
        area_ids: List of up to 4 area IDs this overlay covers (or None).
        map_point_x: X position on map.
        map_point_y: Y position on map.
        texture_width: Texture width in pixels.
        texture_height: Texture height in pixels.
        offset_x: X rendering offset.
        offset_y: Y rendering offset.
        hit_rect_top: Click detection - top edge.
        hit_rect_left: Click detection - left edge.
        hit_rect_bottom: Click detection - bottom edge.
        hit_rect_right: Click detection - right edge.
    """
    if area_ids is None:
        area_ids = [0, 0, 0, 0]
    elif len(area_ids) < 4:
        # Pad to 4 elements
        area_ids = list(area_ids) + [0] * (4 - len(area_ids))
    else:
        area_ids = area_ids[:4]

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', worldmapoverlay_id)
    # 1: MapAreaID
    buf += struct.pack('<I', map_area_id)
    # 2-5: AreaID[4]
    buf += struct.pack('<4I', *area_ids)
    # 6: MapPointX
    buf += struct.pack('<I', map_point_x)
    # 7: MapPointY
    buf += struct.pack('<I', map_point_y)
    # 8: TextureName (string offset)
    buf += struct.pack('<I', texture_name_offset)
    # 9: TextureWidth
    buf += struct.pack('<I', texture_width)
    # 10: TextureHeight
    buf += struct.pack('<I', texture_height)
    # 11: OffsetX
    buf += struct.pack('<I', offset_x)
    # 12: OffsetY
    buf += struct.pack('<I', offset_y)
    # 13: HitRectTop
    buf += struct.pack('<I', hit_rect_top)
    # 14: HitRectLeft
    buf += struct.pack('<I', hit_rect_left)
    # 15: HitRectBottom
    buf += struct.pack('<I', hit_rect_bottom)
    # 16: HitRectRight
    buf += struct.pack('<I', hit_rect_right)

    assert len(buf) == _WORLDMAPOVERLAY_RECORD_SIZE, (
        "WorldMapOverlay record size mismatch: expected {}, got {}".format(
            _WORLDMAPOVERLAY_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_loadingscreen_record(
    loadingscreen_id,
    name_offset,
    filename_offset,
    has_widescreen=0,
):
    """
    Build a raw 16-byte LoadingScreens.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        loadingscreen_id: Unique ID for this loading screen.
        name_offset: String offset for internal name.
        filename_offset: String offset for BLP texture path.
        has_widescreen: 0=standard aspect ratio, 1=widescreen support.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', loadingscreen_id)
    # 1: Name (string offset)
    buf += struct.pack('<I', name_offset)
    # 2: FileName (string offset)
    buf += struct.pack('<I', filename_offset)
    # 3: HasWideScreen
    buf += struct.pack('<I', has_widescreen)

    assert len(buf) == _LOADINGSCREENS_RECORD_SIZE, (
        "LoadingScreens record size mismatch: expected {}, got {}".format(
            _LOADINGSCREENS_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)
```

### 3.4 Public API Functions

Add after `register_area()` (after line 463):

```python
def register_world_map_area(
    dbc_dir,
    area_name,
    map_id,
    area_id,
    worldmaparea_id=None,
    loc_left=0.0,
    loc_right=0.0,
    loc_top=0.0,
    loc_bottom=0.0,
    display_map_id=-1,
    parent_worldmap_id=-1,
):
    """
    Register a new world map area in WorldMapArea.dbc.

    This defines how a zone appears on the world map interface, including
    its position, boundaries, and display settings.

    Args:
        dbc_dir: Path to directory containing WorldMapArea.dbc.
        area_name: Display name for the map area.
        map_id: Map ID (FK to Map.dbc).
        area_id: Area ID (FK to AreaTable.dbc).
        worldmaparea_id: Specific WorldMapArea ID or None for auto (max_id + 1).
        loc_left: Left boundary X coordinate (float).
        loc_right: Right boundary X coordinate (float).
        loc_top: Top boundary Y coordinate (float).
        loc_bottom: Bottom boundary Y coordinate (float).
        display_map_id: Map to display on (-1 = use own map).
        parent_worldmap_id: Parent map area ID (-1 = top-level).

    Returns:
        int: The assigned WorldMapArea ID.

    Example:
        # Tel'Abim zone in South Seas region
        wma_id = register_world_map_area(
            dbc_dir="./DBFilesClient",
            area_name="Tel'Abim",
            map_id=800,
            area_id=5001,
            loc_left=-2000.0,
            loc_right=2000.0,
            loc_top=-2000.0,
            loc_bottom=2000.0,
        )
    """
    filepath = os.path.join(dbc_dir, 'WorldMapArea.dbc')
    dbc = DBCInjector(filepath)

    if worldmaparea_id is None:
        worldmaparea_id = dbc.get_max_id() + 1

    area_name_offset = dbc.add_string(area_name)

    record = _build_worldmaparea_record(
        worldmaparea_id=worldmaparea_id,
        map_id=map_id,
        area_id=area_id,
        area_name_offset=area_name_offset,
        loc_left=loc_left,
        loc_right=loc_right,
        loc_top=loc_top,
        loc_bottom=loc_bottom,
        display_map_id=display_map_id,
        default_dungeon_floor=0,
        parent_worldmap_id=parent_worldmap_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return worldmaparea_id


def register_world_map_overlay(
    dbc_dir,
    map_area_id,
    texture_name,
    worldmapoverlay_id=None,
    area_ids=None,
    texture_width=512,
    texture_height=512,
    map_point_x=0,
    map_point_y=0,
    offset_x=0,
    offset_y=0,
    hit_rect_top=0,
    hit_rect_left=0,
    hit_rect_bottom=512,
    hit_rect_right=512,
):
    """
    Register a new world map overlay in WorldMapOverlay.dbc.

    Overlays add visual elements to the world map (POIs, zone boundaries,
    sub-region highlights, etc.).

    Args:
        dbc_dir: Path to directory containing WorldMapOverlay.dbc.
        map_area_id: WorldMapArea ID this overlay belongs to.
        texture_name: BLP texture path (e.g. "Interface\\WorldMap\\TelAbim\\TelAbim1").
        worldmapoverlay_id: Specific overlay ID or None for auto (max_id + 1).
        area_ids: List of up to 4 area IDs this overlay covers (or None).
        texture_width: Texture width in pixels (default 512).
        texture_height: Texture height in pixels (default 512).
        map_point_x: X position on map.
        map_point_y: Y position on map.
        offset_x: X rendering offset.
        offset_y: Y rendering offset.
        hit_rect_top: Click detection - top edge.
        hit_rect_left: Click detection - left edge.
        hit_rect_bottom: Click detection - bottom edge.
        hit_rect_right: Click detection - right edge.

    Returns:
        int: The assigned WorldMapOverlay ID.

    Example:
        # Tel'Abim zone boundary overlay
        wmo_id = register_world_map_overlay(
            dbc_dir="./DBFilesClient",
            map_area_id=5001,
            texture_name="Interface\\WorldMap\\TelAbim\\TelAbim1",
            area_ids=[5001],
            texture_width=512,
            texture_height=512,
        )
    """
    filepath = os.path.join(dbc_dir, 'WorldMapOverlay.dbc')
    dbc = DBCInjector(filepath)

    if worldmapoverlay_id is None:
        worldmapoverlay_id = dbc.get_max_id() + 1

    texture_name_offset = dbc.add_string(texture_name)

    record = _build_worldmapoverlay_record(
        worldmapoverlay_id=worldmapoverlay_id,
        map_area_id=map_area_id,
        texture_name_offset=texture_name_offset,
        area_ids=area_ids,
        map_point_x=map_point_x,
        map_point_y=map_point_y,
        texture_width=texture_width,
        texture_height=texture_height,
        offset_x=offset_x,
        offset_y=offset_y,
        hit_rect_top=hit_rect_top,
        hit_rect_left=hit_rect_left,
        hit_rect_bottom=hit_rect_bottom,
        hit_rect_right=hit_rect_right,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return worldmapoverlay_id


def register_loading_screen(
    dbc_dir,
    name,
    filename,
    loadingscreen_id=None,
    has_widescreen=1,
):
    """
    Register a new loading screen in LoadingScreens.dbc.

    Loading screens are displayed when entering a zone or instance.

    Args:
        dbc_dir: Path to directory containing LoadingScreens.dbc.
        name: Internal name (e.g. "LoadScreenTelAbim").
        filename: BLP texture path (e.g. "Interface\\Glues\\LoadingScreens\\LoadScreenTelAbim.blp").
        loadingscreen_id: Specific ID or None for auto (max_id + 1).
        has_widescreen: 0=standard aspect ratio only, 1=widescreen support (default 1).

    Returns:
        int: The assigned LoadingScreen ID.

    Example:
        # Tel'Abim loading screen
        ls_id = register_loading_screen(
            dbc_dir="./DBFilesClient",
            name="LoadScreenTelAbim",
            filename="Interface\\Glues\\LoadingScreens\\LoadScreenTelAbim.blp",
            has_widescreen=1,
        )
    """
    filepath = os.path.join(dbc_dir, 'LoadingScreens.dbc')
    dbc = DBCInjector(filepath)

    if loadingscreen_id is None:
        loadingscreen_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(name)
    filename_offset = dbc.add_string(filename)

    record = _build_loadingscreen_record(
        loadingscreen_id=loadingscreen_id,
        name_offset=name_offset,
        filename_offset=filename_offset,
        has_widescreen=has_widescreen,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return loadingscreen_id
```

### 3.5 Integration with build_zone()

Update `world_builder/__init__.py` to support the new DBC injectors.

**Modifications to `build_zone()` function:**

1. **Import additions** (line 12):
```python
from .dbc_injector import (
    DBCInjector,
    register_map,
    register_area,
    register_world_map_area,
    register_world_map_overlay,
    register_loading_screen,
)
```

2. **New parameters** (add to function signature after `dbc_dir`, around line 17):
```python
def build_zone(name, output_dir, coords=None, heightmap=None, texture_paths=None,
               splat_map=None, area_id=0, dbc_dir=None, mphd_flags=0x80,
               # NEW PARAMETERS:
               world_map_area_bounds=None,
               world_map_overlay_texture=None,
               loading_screen_path=None):
    """
    High-level API to build a complete custom zone.

    ...existing docstring...

    New Args:
        world_map_area_bounds: Optional dict with 'left', 'right', 'top', 'bottom'
                              float coordinates for WorldMapArea.dbc.
                              If None, no WorldMapArea entry is created.
        world_map_overlay_texture: Optional texture path for WorldMapOverlay.dbc.
                                   If None, no overlay is created.
        loading_screen_path: Optional BLP path for LoadingScreens.dbc.
                            If None, no loading screen entry is created.

    Returns:
        dict: {
            ...existing fields...
            'worldmaparea_id': int or None,
            'worldmapoverlay_id': int or None,
            'loadingscreen_id': int or None,
        }
    """
```

3. **Result dict extension** (line 53):
```python
    result = {
        'map_id': None,
        'area_id': None,
        'worldmaparea_id': None,      # NEW
        'worldmapoverlay_id': None,   # NEW
        'loadingscreen_id': None,     # NEW
        'wdt_path': None,
        'adt_paths': [],
        'output_dir': output_dir,
    }
```

4. **DBC injection logic extension** (after line 69, before "# Phase 2"):
```python
    # Phase 1b: Register world map area (if bounds provided)
    worldmaparea_id = None
    if dbc_dir and world_map_area_bounds:
        worldmaparea_id = register_world_map_area(
            dbc_dir=dbc_dir,
            area_name=name,
            map_id=map_id,
            area_id=area_id,
            loc_left=world_map_area_bounds.get('left', 0.0),
            loc_right=world_map_area_bounds.get('right', 0.0),
            loc_top=world_map_area_bounds.get('top', 0.0),
            loc_bottom=world_map_area_bounds.get('bottom', 0.0),
        )
        result['worldmaparea_id'] = worldmaparea_id

    # Phase 1c: Register world map overlay (if texture provided)
    if dbc_dir and world_map_overlay_texture and worldmaparea_id:
        worldmapoverlay_id = register_world_map_overlay(
            dbc_dir=dbc_dir,
            map_area_id=worldmaparea_id,
            texture_name=world_map_overlay_texture,
            area_ids=[area_id],
        )
        result['worldmapoverlay_id'] = worldmapoverlay_id

    # Phase 1d: Register loading screen (if path provided)
    if dbc_dir and loading_screen_path and map_id:
        loadingscreen_id = register_loading_screen(
            dbc_dir=dbc_dir,
            name="LoadScreen{}".format(name),
            filename=loading_screen_path,
        )
        result['loadingscreen_id'] = loadingscreen_id

        # Update Map.dbc to link loading screen
        map_dbc_path = os.path.join(dbc_dir, 'Map.dbc')
        map_dbc = DBCInjector(map_dbc_path)

        # Find the map record we just created (last record)
        if map_dbc.records:
            last_record = bytearray(map_dbc.records[-1])
            # LoadingScreenID is at field 57 (byte offset 228)
            struct.pack_into('<I', last_record, 228, loadingscreen_id)
            map_dbc.records[-1] = bytes(last_record)
            map_dbc.write(map_dbc_path)
```

---

## 4. Tel'Abim Zone Usage Example

Complete example showing how Tel'Abim would use these new injectors:

```python
from world_builder import build_zone

result = build_zone(
    name="TelAbim",
    output_dir="./output",
    coords=[(32, 32), (32, 33), (33, 32), (33, 33)],  # 2x2 tile grid
    heightmap=None,  # Flat terrain for now
    texture_paths=["Tileset\\Northrend\\BoreanTundra\\BoreanTundraGrass01.blp"],
    dbc_dir="C:\\Games\\WoW_3.3.5a\\Data\\DBFilesClient",

    # NEW: World map configuration
    world_map_area_bounds={
        'left': -2500.0,
        'right': 2500.0,
        'top': -2500.0,
        'bottom': 2500.0,
    },

    # NEW: World map overlay texture
    world_map_overlay_texture="Interface\\WorldMap\\TelAbim\\TelAbim1",

    # NEW: Loading screen
    loading_screen_path="Interface\\Glues\\LoadingScreens\\LoadScreenTelAbim.blp",
)

print("Generated Tel'Abim zone:")
print(f"  Map ID: {result['map_id']}")
print(f"  Area ID: {result['area_id']}")
print(f"  WorldMapArea ID: {result['worldmaparea_id']}")
print(f"  WorldMapOverlay ID: {result['worldmapoverlay_id']}")
print(f"  LoadingScreen ID: {result['loadingscreen_id']}")
```

**Expected DBC Entries:**

**Map.dbc:**
- ID: 800
- Directory: "TelAbim"
- MapName: "Tel'Abim"
- LoadingScreenID: 301 (linked)

**AreaTable.dbc:**
- ID: 5001
- ContinentID: 800
- AreaName: "Tel'Abim"

**WorldMapArea.dbc:**
- ID: 5001
- MapID: 800
- AreaID: 5001
- AreaName: "Tel'Abim"
- LocLeft: -2500.0, LocRight: 2500.0
- LocTop: -2500.0, LocBottom: 2500.0

**WorldMapOverlay.dbc:**
- ID: 5001
- MapAreaID: 5001
- AreaID[0]: 5001
- TextureName: "Interface\\WorldMap\\TelAbim\\TelAbim1"

**LoadingScreens.dbc:**
- ID: 301
- Name: "LoadScreenTelAbim"
- FileName: "Interface\\Glues\\LoadingScreens\\LoadScreenTelAbim.blp"
- HasWideScreen: 1

---

## 5. Testing Approach

### 5.1 Unit Testing

Create `tests/test_dbc_zone_display.py`:

```python
import os
import tempfile
import struct
from world_builder.dbc_injector import (
    DBCInjector,
    register_world_map_area,
    register_world_map_overlay,
    register_loading_screen,
    _build_worldmaparea_record,
    _build_worldmapoverlay_record,
    _build_loadingscreen_record,
)


def test_worldmaparea_record_size():
    """Verify WorldMapArea record is exactly 44 bytes."""
    record = _build_worldmaparea_record(
        worldmaparea_id=1,
        map_id=800,
        area_id=5001,
        area_name_offset=10,
    )
    assert len(record) == 44


def test_worldmaparea_field_values():
    """Verify WorldMapArea field packing."""
    record = _build_worldmaparea_record(
        worldmaparea_id=999,
        map_id=800,
        area_id=5001,
        area_name_offset=100,
        loc_left=-1000.0,
        loc_right=1000.0,
        loc_top=-500.0,
        loc_bottom=500.0,
        display_map_id=-1,
        parent_worldmap_id=-1,
    )

    assert struct.unpack_from('<I', record, 0)[0] == 999  # ID
    assert struct.unpack_from('<I', record, 4)[0] == 800  # MapID
    assert struct.unpack_from('<I', record, 8)[0] == 5001  # AreaID
    assert struct.unpack_from('<I', record, 12)[0] == 100  # AreaName offset
    assert abs(struct.unpack_from('<f', record, 16)[0] - (-1000.0)) < 0.01  # LocLeft
    assert abs(struct.unpack_from('<f', record, 20)[0] - 1000.0) < 0.01  # LocRight


def test_worldmapoverlay_record_size():
    """Verify WorldMapOverlay record is exactly 60 bytes."""
    record = _build_worldmapoverlay_record(
        worldmapoverlay_id=1,
        map_area_id=5001,
        texture_name_offset=10,
    )
    assert len(record) == 60


def test_worldmapoverlay_area_array():
    """Verify WorldMapOverlay AreaID array packing."""
    record = _build_worldmapoverlay_record(
        worldmapoverlay_id=1,
        map_area_id=5001,
        texture_name_offset=10,
        area_ids=[5001, 5002],
    )

    # AreaID[0] at offset 8
    assert struct.unpack_from('<I', record, 8)[0] == 5001
    # AreaID[1] at offset 12
    assert struct.unpack_from('<I', record, 12)[0] == 5002
    # AreaID[2] at offset 16 (should be 0 - padded)
    assert struct.unpack_from('<I', record, 16)[0] == 0


def test_loadingscreen_record_size():
    """Verify LoadingScreens record is exactly 16 bytes."""
    record = _build_loadingscreen_record(
        loadingscreen_id=1,
        name_offset=10,
        filename_offset=50,
    )
    assert len(record) == 16


def test_loadingscreen_field_values():
    """Verify LoadingScreens field packing."""
    record = _build_loadingscreen_record(
        loadingscreen_id=301,
        name_offset=100,
        filename_offset=200,
        has_widescreen=1,
    )

    assert struct.unpack_from('<I', record, 0)[0] == 301  # ID
    assert struct.unpack_from('<I', record, 4)[0] == 100  # Name offset
    assert struct.unpack_from('<I', record, 8)[0] == 200  # FileName offset
    assert struct.unpack_from('<I', record, 12)[0] == 1  # HasWideScreen


def test_register_world_map_area():
    """Integration test: create and read WorldMapArea.dbc."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC
        dbc = DBCInjector()
        dbc.field_count = 11
        dbc.record_size = 44
        dbc_path = os.path.join(tmpdir, 'WorldMapArea.dbc')
        dbc.write(dbc_path)

        # Register entry
        wma_id = register_world_map_area(
            dbc_dir=tmpdir,
            area_name="Test Zone",
            map_id=800,
            area_id=5001,
            loc_left=-1000.0,
            loc_right=1000.0,
        )

        # Verify
        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 1
        assert dbc2.field_count == 11
        assert dbc2.record_size == 44
        assert dbc2.get_record_field(0, 0) == wma_id
        assert dbc2.get_record_field(0, 1) == 800  # MapID
        assert dbc2.get_string(dbc2.get_record_field(0, 3)) == "Test Zone"


def test_register_world_map_overlay():
    """Integration test: create and read WorldMapOverlay.dbc."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbc = DBCInjector()
        dbc.field_count = 15
        dbc.record_size = 60
        dbc_path = os.path.join(tmpdir, 'WorldMapOverlay.dbc')
        dbc.write(dbc_path)

        wmo_id = register_world_map_overlay(
            dbc_dir=tmpdir,
            map_area_id=5001,
            texture_name="Interface\\WorldMap\\Test\\Test1",
            area_ids=[5001],
        )

        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 1
        assert dbc2.get_record_field(0, 1) == 5001  # MapAreaID
        texture = dbc2.get_string(dbc2.get_record_field(0, 8))
        assert texture == "Interface\\WorldMap\\Test\\Test1"


def test_register_loading_screen():
    """Integration test: create and read LoadingScreens.dbc."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbc = DBCInjector()
        dbc.field_count = 4
        dbc.record_size = 16
        dbc_path = os.path.join(tmpdir, 'LoadingScreens.dbc')
        dbc.write(dbc_path)

        ls_id = register_loading_screen(
            dbc_dir=tmpdir,
            name="LoadScreenTest",
            filename="Interface\\Glues\\LoadingScreens\\LoadScreenTest.blp",
        )

        dbc2 = DBCInjector(dbc_path)
        assert dbc2.record_count == 1
        assert dbc2.get_string(dbc2.get_record_field(0, 1)) == "LoadScreenTest"
        filename = dbc2.get_string(dbc2.get_record_field(0, 2))
        assert filename == "Interface\\Glues\\LoadingScreens\\LoadScreenTest.blp"
```

### 5.2 Integration Testing

Create `tests/test_build_zone_extended.py`:

```python
import os
import tempfile
from world_builder import build_zone
from world_builder.dbc_injector import DBCInjector


def test_build_zone_with_world_map():
    """Test build_zone() with all new DBC injectors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty DBC files
        for dbc_name, field_count, record_size in [
            ('Map.dbc', 66, 264),
            ('AreaTable.dbc', 36, 144),
            ('WorldMapArea.dbc', 11, 44),
            ('WorldMapOverlay.dbc', 15, 60),
            ('LoadingScreens.dbc', 4, 16),
        ]:
            dbc = DBCInjector()
            dbc.field_count = field_count
            dbc.record_size = record_size
            dbc.write(os.path.join(tmpdir, dbc_name))

        # Build zone with all features
        result = build_zone(
            name="TestZone",
            output_dir=os.path.join(tmpdir, 'output'),
            coords=[(32, 32)],
            dbc_dir=tmpdir,
            world_map_area_bounds={
                'left': -1000.0,
                'right': 1000.0,
                'top': -1000.0,
                'bottom': 1000.0,
            },
            world_map_overlay_texture="Interface\\WorldMap\\Test\\Test1",
            loading_screen_path="Interface\\Glues\\LoadingScreens\\Test.blp",
        )

        # Verify all IDs were assigned
        assert result['map_id'] is not None
        assert result['area_id'] is not None
        assert result['worldmaparea_id'] is not None
        assert result['worldmapoverlay_id'] is not None
        assert result['loadingscreen_id'] is not None

        # Verify DBC entries
        wma_dbc = DBCInjector(os.path.join(tmpdir, 'WorldMapArea.dbc'))
        assert wma_dbc.record_count == 1

        wmo_dbc = DBCInjector(os.path.join(tmpdir, 'WorldMapOverlay.dbc'))
        assert wmo_dbc.record_count == 1

        ls_dbc = DBCInjector(os.path.join(tmpdir, 'LoadingScreens.dbc'))
        assert ls_dbc.record_count == 1
```

### 5.3 Manual Testing (Client Validation)

**Prerequisites:**
- WoW WotLK 3.3.5a client installed
- DBFilesClient directory writable
- Backup existing DBC files first

**Steps:**

1. **Backup DBCs:**
   ```bash
   cp DBFilesClient/WorldMapArea.dbc DBFilesClient/WorldMapArea.dbc.backup
   cp DBFilesClient/WorldMapOverlay.dbc DBFilesClient/WorldMapOverlay.dbc.backup
   cp DBFilesClient/LoadingScreens.dbc DBFilesClient/LoadingScreens.dbc.backup
   ```

2. **Generate test entries:**
   ```python
   from world_builder.dbc_injector import (
       register_world_map_area,
       register_world_map_overlay,
       register_loading_screen,
   )

   dbc_dir = "C:\\Games\\WoW_3.3.5a\\Data\\DBFilesClient"

   # Use existing map/area IDs for testing
   wma_id = register_world_map_area(
       dbc_dir=dbc_dir,
       area_name="Test Zone Display",
       map_id=0,  # Eastern Kingdoms
       area_id=1,  # Dun Morogh (existing area)
       loc_left=-6000.0,
       loc_right=-5000.0,
       loc_top=-3000.0,
       loc_bottom=-2000.0,
   )
   print(f"Created WorldMapArea ID: {wma_id}")
   ```

3. **Launch client and verify:**
   - Open world map (M key)
   - Check if test zone appears in correct location
   - Verify no client crashes during map view

4. **Restore backups:**
   ```bash
   cp DBFilesClient/*.dbc.backup DBFilesClient/
   ```

---

## 6. Implementation Checklist

- [ ] Add field layout constants to `dbc_injector.py`
- [ ] Implement `_build_worldmaparea_record()`
- [ ] Implement `_build_worldmapoverlay_record()`
- [ ] Implement `_build_loadingscreen_record()`
- [ ] Implement `register_world_map_area()`
- [ ] Implement `register_world_map_overlay()`
- [ ] Implement `register_loading_screen()`
- [ ] Update `world_builder/__init__.py` imports
- [ ] Extend `build_zone()` function signature
- [ ] Add WorldMapArea injection logic to `build_zone()`
- [ ] Add WorldMapOverlay injection logic to `build_zone()`
- [ ] Add LoadingScreens injection logic to `build_zone()`
- [ ] Link LoadingScreen to Map.dbc entry
- [ ] Create unit test file `tests/test_dbc_zone_display.py`
- [ ] Implement record size tests
- [ ] Implement field packing tests
- [ ] Implement registration function tests
- [ ] Create integration test file `tests/test_build_zone_extended.py`
- [ ] Run full test suite
- [ ] Perform manual client validation
- [ ] Update documentation

---

## 7. Known Limitations and Future Work

### Current Limitations

1. **No multi-floor support:** DefaultDungeonFloor is hardcoded to 0 (outdoor zones only).
2. **No localization:** Only enUS locale is populated in string fields.
3. **No Map.dbc update hook:** LoadingScreenID is set after Map entry creation, requiring file re-write.
4. **Fixed overlay dimensions:** Default 512x512, no auto-detection from BLP files.

### Future Enhancements

1. **BLP integration:** Auto-detect overlay texture dimensions from BLP files.
2. **Multi-zone overlays:** Support multiple overlays per WorldMapArea.
3. **Hierarchical zones:** Support for sub-zones and continent-level maps.
4. **Validation layer:** Check FK constraints (MapID exists in Map.dbc, etc.).
5. **Batch operations:** Register multiple zones in single DBC write transaction.

---

## 8. References

### File Paths

- DBC Injector: `D:\Test\wow-pywowlib\world_builder\dbc_injector.py`
- Main API: `D:\Test\wow-pywowlib\world_builder\__init__.py`
- DBD Definitions: `D:\Test\wow-pywowlib\wdbx\dbd\definitions\`

### External Documentation

- WoW.tools DBC browser: https://wow.tools/dbc/
- WoWDev Wiki (archived): https://wowdev.wiki/
- WDBX Editor source: https://github.com/WoW-Tools/WDBXEditor

### Build Version

- Target: WoW WotLK 3.3.5a (build 12340)
- DBC layouts validated against DBD definitions in repository

---

## Conclusion

This plan provides a complete implementation roadmap for the three DBC injectors, following the existing code patterns in `dbc_injector.py`. The design prioritizes:

- **Binary correctness:** Exact field layouts from authoritative DBD definitions
- **Code consistency:** Same structure as existing `register_map()` and `register_area()`
- **Client compatibility:** Tested against WotLK 3.3.5a build 12340
- **Integration simplicity:** Extends `build_zone()` with optional parameters

Implementation can proceed incrementally: record builders → registration functions → `build_zone()` integration → testing.
