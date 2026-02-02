# DBC Atmosphere Injectors: ZoneMusic, SoundAmbience, Light

**Target:** WoW WotLK 3.3.5a (build 12340)
**Module:** `world_builder/dbc_injector.py`
**Status:** Planning
**Related TODO:** Item 1.3 (ZoneMusic assignment, SoundAmbience per subzone, Light for zone lighting)

---

## 1. Overview

This plan extends `world_builder/dbc_injector.py` with three new DBC injectors to enable atmospheric customization of custom zones:

1. **ZoneMusic.dbc** - Assigns background music tracks (day/night) to zones
2. **SoundAmbience.dbc** - Defines ambient sound layers (jungle birds, wind, volcanic rumble, etc.) for subzones
3. **Light.dbc** - Controls zone lighting, sky colors, fog, and time-of-day effects

These DBCs are referenced by existing AreaTable.dbc fields (`ZoneMusic`, `AmbienceID`, `LightID`), so this implementation completes the atmospheric pipeline started with `register_area()`.

---

## 2. Field Layouts & Binary Structure

All layouts are for WotLK 3.3.5 (build 3.0.1.8303-3.3.5.12340) per the authoritative DBD definitions.

### 2.1 ZoneMusic.dbc

**Build Range:** 3.0.1.8303 - 3.3.5.12340
**Record Size:** 32 bytes (8 fields × 4 bytes)
**Field Count:** 8

| Byte Offset | Field                  | Type       | Description                                    |
|-------------|------------------------|------------|------------------------------------------------|
| 0-3         | ID                     | uint32     | Primary key, unique ZoneMusic ID               |
| 4-7         | SetName                | uint32     | String offset, internal name (e.g. "ZoneMusicJungle") |
| 8-11        | SilenceIntervalMin[0]  | uint32     | Min silence between tracks (ms), day           |
| 12-15       | SilenceIntervalMin[1]  | uint32     | Min silence between tracks (ms), night         |
| 16-19       | SilenceIntervalMax[0]  | uint32     | Max silence between tracks (ms), day           |
| 20-23       | SilenceIntervalMax[1]  | uint32     | Max silence between tracks (ms), night         |
| 24-27       | Sounds[0]              | uint32     | FK to SoundEntries.dbc, day music track ID     |
| 28-31       | Sounds[1]              | uint32     | FK to SoundEntries.dbc, night music track ID   |

**Notes:**
- SetName is descriptive only; not shown in-game
- Silence intervals control how often music repeats (e.g., 120000-180000 = 2-3 minutes)
- Sounds[0] and Sounds[1] can reference the same track if day/night distinction isn't needed
- Referenced by AreaTable.dbc field `ZoneMusic` (byte offset 32)

### 2.2 SoundAmbience.dbc

**Build Range:** 3.0.1.8303 - 3.3.5.12340
**Record Size:** 12 bytes (3 fields × 4 bytes)
**Field Count:** 3

| Byte Offset | Field          | Type   | Description                                     |
|-------------|----------------|--------|-------------------------------------------------|
| 0-3         | ID             | uint32 | Primary key, unique SoundAmbience ID            |
| 4-7         | AmbienceID[0]  | uint32 | FK to SoundEntries.dbc, day ambience sound ID   |
| 8-11        | AmbienceID[1]  | uint32 | FK to SoundEntries.dbc, night ambience sound ID |

**Notes:**
- Each SoundAmbience references TWO ambient sound tracks (day/night)
- Ambient sounds are continuous loops (bird chirps, wind, water, cave drips, etc.)
- Referenced by AreaTable.dbc field `AmbienceID` (byte offset 28)
- Multiple subzones can share the same SoundAmbience ID for consistency

### 2.3 Light.dbc

**Build Range:** 3.0.1.8622 - 3.3.5.12340
**Record Size:** 60 bytes (15 fields × 4 bytes)
**Field Count:** 15

| Byte Offset | Field              | Type    | Description                                           |
|-------------|--------------------|---------|-------------------------------------------------------|
| 0-3         | ID                 | uint32  | Primary key, unique Light ID                          |
| 4-7         | ContinentID        | uint32  | FK to Map.dbc, which map this light applies to        |
| 8-11        | GameCoords[0]      | float   | X position of light source center (in-game coords)    |
| 12-15       | GameCoords[1]      | float   | Y position of light source center                     |
| 16-19       | GameCoords[2]      | float   | Z position of light source center                     |
| 20-23       | GameFalloffStart   | float   | Inner radius where light is full strength (yards)     |
| 24-27       | GameFalloffEnd     | float   | Outer radius where light fades to zero (yards)        |
| 28-31       | LightParamsID[0]   | uint32  | FK to LightParams.dbc, time band 0 (midnight)         |
| 32-35       | LightParamsID[1]   | uint32  | FK to LightParams.dbc, time band 1 (dawn)             |
| 36-39       | LightParamsID[2]   | uint32  | FK to LightParams.dbc, time band 2 (morning)          |
| 40-43       | LightParamsID[3]   | uint32  | FK to LightParams.dbc, time band 3 (noon)             |
| 44-47       | LightParamsID[4]   | uint32  | FK to LightParams.dbc, time band 4 (afternoon)        |
| 48-51       | LightParamsID[5]   | uint32  | FK to LightParams.dbc, time band 5 (dusk)             |
| 52-55       | LightParamsID[6]   | uint32  | FK to LightParams.dbc, time band 6 (evening)          |
| 56-59       | LightParamsID[7]   | uint32  | FK to LightParams.dbc, time band 7 (night)            |

**Notes:**
- GameCoords: Use in-game coordinate system (center of the zone, typically 0,0 for global light)
- GameFalloffStart=0 + GameFalloffEnd=1.0 = global zone light (no distance attenuation)
- GameFalloffStart=500 + GameFalloffEnd=1000 = localized light (e.g., volcanic glow near caldera)
- LightParamsID[0-7]: References to LightParams.dbc (defines RGB values for sky, fog, water, etc.)
- **Critical dependency:** Light.dbc REQUIRES LightParams.dbc entries to exist
- Strategy for Tel'Abim: Reuse existing LightParams from similar zones (Stranglethorn, Tanaris) to avoid needing to create custom LightParams records
- Referenced by AreaTable.dbc field `LightID` (byte offset 140)

### 2.4 LightParams.dbc (Dependency Context)

**Build Range:** 3.0.1.8622 - 3.3.5.12340
**Record Size:** ~100 bytes (contains RGB color arrays for sky, fog, water, sun, clouds)
**Field Count:** ~20 fields

**Structure (simplified):**
- ID (uint32)
- HighlightSky (uint32) - Boolean flag
- LightSkyboxID (uint32) - FK to LightSkybox.dbc (skybox model)
- CloudTypeID (uint32) - Cloud texture reference
- Glow, WaterShallowAlpha, WaterDeepAlpha, OceanShallowAlpha, OceanDeepAlpha (floats)
- Flags (uint32)

**Implementation Note:**
LightParams.dbc is NOT implemented in this plan. Instead, `register_light()` will accept `light_params_ids` as a parameter (array of 8 uint32 IDs) that reference EXISTING LightParams entries from retail WoW. This is the standard practice for custom zones:

- **Tropical daylight:** Reuse LightParams from Stranglethorn Vale (zone ID 33)
- **Volcanic orange glow:** Reuse LightParams from Burning Steppes (zone ID 46) or Molten Core
- **Cave lighting:** Reuse LightParams from Deepholm or any cave zone

To find suitable LightParams IDs, users can inspect existing Light.dbc entries:
```python
# Example: Extract LightParams from Stranglethorn Vale
dbc = DBCInjector('Light.dbc')
for i, rec in enumerate(dbc.records):
    continent_id = struct.unpack_from('<I', rec, 4)[0]
    if continent_id == 0:  # Eastern Kingdoms
        x, y, z = struct.unpack_from('<fff', rec, 8)
        if -13000 < x < -10000 and 200 < y < 2000:  # STV coordinate range
            light_params = struct.unpack_from('<8I', rec, 28)
            print(f"STV Light ID {i}: LightParams = {light_params}")
```

---

## 3. Existing Code Analysis

### 3.1 Current `register_area()` Signature

```python
def register_area(dbc_dir, area_name, map_id, area_id=None, parent_area_id=0):
    """
    Register a new area in AreaTable.dbc.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_name: Display name for the area.
        map_id: Map ID this area belongs to (ContinentID).
        area_id: Specific area ID or None for auto (max_id + 1).
        parent_area_id: Parent area (0 for top-level zone).

    Returns:
        int: The assigned area ID.
    """
```

**Limitations:**
- Hardcodes `ambience_id=0`, `zone_music=0`, `light_id=0` in `_build_area_record()`
- No way to set atmospheric fields after initial area creation
- Users must manually edit DBC binary to inject music/ambience/light

### 3.2 Proposed Enhancements

#### Option A: Extend `register_area()` with optional parameters

```python
def register_area(
    dbc_dir, area_name, map_id,
    area_id=None,
    parent_area_id=0,
    ambience_id=0,        # NEW
    zone_music=0,         # NEW
    light_id=0,           # NEW
):
    """Register a new area with optional atmospheric parameters."""
    # ... existing code ...
    record = _build_area_record(
        area_id=area_id,
        continent_id=map_id,
        parent_area_id=parent_area_id,
        area_bit=area_bit,
        area_name_offset=name_offset,
        ambience_id=ambience_id,      # Pass through
        zone_music=zone_music,         # Pass through
        light_id=light_id,             # Pass through
    )
```

**Pros:** Backward compatible, single function call
**Cons:** Still requires creating ZoneMusic/SoundAmbience/Light records separately

#### Option B: Separate update function

```python
def update_area_atmosphere(dbc_dir, area_id, ambience_id=None, zone_music=None, light_id=None):
    """
    Update atmospheric fields for an existing AreaTable record.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_id: Area ID to update.
        ambience_id: SoundAmbience ID (None = no change).
        zone_music: ZoneMusic ID (None = no change).
        light_id: Light ID (None = no change).
    """
    filepath = os.path.join(dbc_dir, 'AreaTable.dbc')
    dbc = DBCInjector(filepath)

    # Find record with matching ID
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == area_id:
            # Unpack full record
            buf = bytearray(rec)

            # Update fields (byte offsets from AreaTable layout)
            if ambience_id is not None:
                struct.pack_into('<I', buf, 28, ambience_id)  # AmbienceID at offset 28
            if zone_music is not None:
                struct.pack_into('<I', buf, 32, zone_music)   # ZoneMusic at offset 32
            if light_id is not None:
                struct.pack_into('<I', buf, 140, light_id)    # LightID at offset 140

            # Replace record
            dbc.records[i] = bytes(buf)
            dbc.write(filepath)
            return

    raise ValueError(f"Area ID {area_id} not found in AreaTable.dbc")
```

**Pros:** Explicit separation of concerns, supports post-creation updates
**Cons:** Requires two function calls (register + update)

**Recommendation:** Implement BOTH approaches:
- Extend `register_area()` with optional parameters (Option A) for new areas
- Add `update_area_atmosphere()` (Option B) for updating existing areas

---

## 4. New Functions

### 4.1 `register_zone_music()`

```python
def register_zone_music(
    dbc_dir,
    set_name,
    day_sound_id,
    night_sound_id=None,
    silence_min_day=120000,
    silence_max_day=180000,
    silence_min_night=None,
    silence_max_night=None,
    zone_music_id=None,
):
    """
    Register a new ZoneMusic entry.

    Args:
        dbc_dir: Path to directory containing ZoneMusic.dbc.
        set_name: Internal name (e.g. "ZoneMusicTelAbim").
        day_sound_id: SoundEntries ID for daytime music track.
        night_sound_id: SoundEntries ID for nighttime music (None = use day_sound_id).
        silence_min_day: Minimum silence between tracks, day (milliseconds, default 2 min).
        silence_max_day: Maximum silence between tracks, day (milliseconds, default 3 min).
        silence_min_night: Min silence, night (None = use silence_min_day).
        silence_max_night: Max silence, night (None = use silence_max_day).
        zone_music_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned ZoneMusic ID.
    """
    # Default night to day values
    if night_sound_id is None:
        night_sound_id = day_sound_id
    if silence_min_night is None:
        silence_min_night = silence_min_day
    if silence_max_night is None:
        silence_max_night = silence_max_day

    filepath = os.path.join(dbc_dir, 'ZoneMusic.dbc')
    dbc = DBCInjector(filepath)

    if zone_music_id is None:
        zone_music_id = dbc.get_max_id() + 1

    set_name_offset = dbc.add_string(set_name)

    record = _build_zone_music_record(
        zone_music_id=zone_music_id,
        set_name_offset=set_name_offset,
        silence_min=[silence_min_day, silence_min_night],
        silence_max=[silence_max_day, silence_max_night],
        sounds=[day_sound_id, night_sound_id],
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return zone_music_id
```

### 4.2 `register_sound_ambience()`

```python
def register_sound_ambience(
    dbc_dir,
    day_ambience_id,
    night_ambience_id=None,
    ambience_id=None,
):
    """
    Register a new SoundAmbience entry.

    Args:
        dbc_dir: Path to directory containing SoundAmbience.dbc.
        day_ambience_id: SoundEntries ID for daytime ambient sound loop.
        night_ambience_id: SoundEntries ID for nighttime ambient loop (None = use day_ambience_id).
        ambience_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned SoundAmbience ID.
    """
    if night_ambience_id is None:
        night_ambience_id = day_ambience_id

    filepath = os.path.join(dbc_dir, 'SoundAmbience.dbc')
    dbc = DBCInjector(filepath)

    if ambience_id is None:
        ambience_id = dbc.get_max_id() + 1

    record = _build_sound_ambience_record(
        ambience_id=ambience_id,
        day_ambience_id=day_ambience_id,
        night_ambience_id=night_ambience_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return ambience_id
```

### 4.3 `register_light()`

```python
def register_light(
    dbc_dir,
    map_id,
    light_params_ids,
    position=(0.0, 0.0, 0.0),
    falloff_start=0.0,
    falloff_end=1.0,
    light_id=None,
):
    """
    Register a new Light entry.

    Args:
        dbc_dir: Path to directory containing Light.dbc.
        map_id: Map ID (ContinentID) this light applies to.
        light_params_ids: List of 8 LightParams IDs (one per time-of-day band).
                          Reuse existing IDs from similar retail zones.
                          Example: [130, 131, 132, 133, 134, 135, 136, 137]
        position: (x, y, z) tuple for light source center in game coordinates.
                  Use (0, 0, 0) for global zone light.
        falloff_start: Inner radius (yards) where light is full strength.
                       Use 0.0 for global zone light.
        falloff_end: Outer radius (yards) where light fades to zero.
                     Use 1.0 for global zone light (no attenuation).
        light_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned Light ID.

    Raises:
        ValueError: If light_params_ids is not a list of exactly 8 integers.

    Example:
        # Tropical zone with STV-style lighting
        light_id = register_light(
            dbc_dir='./DBFilesClient',
            map_id=800,
            light_params_ids=[130, 131, 132, 133, 134, 135, 136, 137],  # Reused from STV
            position=(0.0, 0.0, 0.0),
            falloff_start=0.0,
            falloff_end=1.0,
        )
    """
    if not isinstance(light_params_ids, (list, tuple)) or len(light_params_ids) != 8:
        raise ValueError("light_params_ids must be a list of exactly 8 integers")

    filepath = os.path.join(dbc_dir, 'Light.dbc')
    dbc = DBCInjector(filepath)

    if light_id is None:
        light_id = dbc.get_max_id() + 1

    record = _build_light_record(
        light_id=light_id,
        continent_id=map_id,
        game_coords=position,
        falloff_start=falloff_start,
        falloff_end=falloff_end,
        light_params_ids=light_params_ids,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return light_id
```

---

## 5. Record Builder Functions

### 5.1 `_build_zone_music_record()`

```python
def _build_zone_music_record(
    zone_music_id,
    set_name_offset,
    silence_min,
    silence_max,
    sounds,
):
    """
    Build a raw 32-byte ZoneMusic.dbc record for WotLK 3.3.5.

    Args:
        zone_music_id: ZoneMusic ID (uint32).
        set_name_offset: String offset for SetName field.
        silence_min: [day, night] min silence intervals (uint32 x2).
        silence_max: [day, night] max silence intervals (uint32 x2).
        sounds: [day, night] SoundEntries IDs (uint32 x2).

    Returns:
        bytes: 32-byte binary record.
    """
    _ZONE_MUSIC_RECORD_SIZE = 32
    _ZONE_MUSIC_FIELD_COUNT = 8

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', zone_music_id)
    # 1: SetName (string offset)
    buf += struct.pack('<I', set_name_offset)
    # 2-3: SilenceIntervalMin[2] (day, night)
    buf += struct.pack('<2I', silence_min[0], silence_min[1])
    # 4-5: SilenceIntervalMax[2] (day, night)
    buf += struct.pack('<2I', silence_max[0], silence_max[1])
    # 6-7: Sounds[2] (day, night)
    buf += struct.pack('<2I', sounds[0], sounds[1])

    assert len(buf) == _ZONE_MUSIC_RECORD_SIZE, (
        f"ZoneMusic record size mismatch: expected {_ZONE_MUSIC_RECORD_SIZE}, got {len(buf)}"
    )
    return bytes(buf)
```

### 5.2 `_build_sound_ambience_record()`

```python
def _build_sound_ambience_record(
    ambience_id,
    day_ambience_id,
    night_ambience_id,
):
    """
    Build a raw 12-byte SoundAmbience.dbc record for WotLK 3.3.5.

    Args:
        ambience_id: SoundAmbience ID (uint32).
        day_ambience_id: SoundEntries ID for day ambience (uint32).
        night_ambience_id: SoundEntries ID for night ambience (uint32).

    Returns:
        bytes: 12-byte binary record.
    """
    _SOUND_AMBIENCE_RECORD_SIZE = 12
    _SOUND_AMBIENCE_FIELD_COUNT = 3

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', ambience_id)
    # 1-2: AmbienceID[2] (day, night)
    buf += struct.pack('<2I', day_ambience_id, night_ambience_id)

    assert len(buf) == _SOUND_AMBIENCE_RECORD_SIZE, (
        f"SoundAmbience record size mismatch: expected {_SOUND_AMBIENCE_RECORD_SIZE}, got {len(buf)}"
    )
    return bytes(buf)
```

### 5.3 `_build_light_record()`

```python
def _build_light_record(
    light_id,
    continent_id,
    game_coords,
    falloff_start,
    falloff_end,
    light_params_ids,
):
    """
    Build a raw 60-byte Light.dbc record for WotLK 3.3.5.

    Args:
        light_id: Light ID (uint32).
        continent_id: Map ID (uint32).
        game_coords: (x, y, z) tuple of floats.
        falloff_start: Inner falloff radius (float).
        falloff_end: Outer falloff radius (float).
        light_params_ids: List of 8 LightParams IDs (uint32 x8).

    Returns:
        bytes: 60-byte binary record.
    """
    _LIGHT_RECORD_SIZE = 60
    _LIGHT_FIELD_COUNT = 15

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', light_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: GameCoords[3] (x, y, z)
    buf += struct.pack('<3f', game_coords[0], game_coords[1], game_coords[2])
    # 5: GameFalloffStart
    buf += struct.pack('<f', falloff_start)
    # 6: GameFalloffEnd
    buf += struct.pack('<f', falloff_end)
    # 7-14: LightParamsID[8]
    buf += struct.pack('<8I', *light_params_ids)

    assert len(buf) == _LIGHT_RECORD_SIZE, (
        f"Light record size mismatch: expected {_LIGHT_RECORD_SIZE}, got {len(buf)}"
    )
    return bytes(buf)
```

---

## 6. Integration with AreaTable.dbc

### 6.1 AreaTable.dbc Field Offsets

From existing `_build_area_record()` in `dbc_injector.py`:

| Field Index | Byte Offset | Field Name              | Current Default |
|-------------|-------------|-------------------------|-----------------|
| 7           | 28          | AmbienceID              | 0               |
| 8           | 32          | ZoneMusic               | 0               |
| 35          | 140         | LightID                 | 0               |

### 6.2 Enhanced `_build_area_record()` Signature

Update the existing function to accept atmospheric parameters:

```python
def _build_area_record(
    area_id,
    continent_id,
    parent_area_id,
    area_bit,
    area_name_offset,
    flags=0,
    sound_provider_pref=0,
    sound_provider_pref_uw=0,
    ambience_id=0,           # CHANGED: was hardcoded to 0
    zone_music=0,            # CHANGED: was hardcoded to 0
    intro_sound=0,
    exploration_level=0,
    faction_group_mask=0,
    liquid_type_ids=None,
    min_elevation=0.0,
    ambient_multiplier=0.0,
    light_id=0,              # CHANGED: was hardcoded to 0
):
    """Build a raw 144-byte AreaTable.dbc record for WotLK 3.3.5."""
    # ... existing implementation ...
    # Just pass through the new parameters instead of hardcoding to 0
```

### 6.3 Enhanced `register_area()` Signature

```python
def register_area(
    dbc_dir,
    area_name,
    map_id,
    area_id=None,
    parent_area_id=0,
    ambience_id=0,        # NEW
    zone_music=0,         # NEW
    light_id=0,           # NEW
):
    """
    Register a new area in AreaTable.dbc with optional atmospheric parameters.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_name: Display name for the area.
        map_id: Map ID this area belongs to (ContinentID).
        area_id: Specific area ID or None for auto (max_id + 1).
        parent_area_id: Parent area (0 for top-level zone).
        ambience_id: SoundAmbience ID (0 = no ambience).
        zone_music: ZoneMusic ID (0 = no music).
        light_id: Light ID (0 = default lighting).

    Returns:
        int: The assigned area ID.
    """
    filepath = os.path.join(dbc_dir, 'AreaTable.dbc')
    dbc = DBCInjector(filepath)

    if area_id is None:
        area_id = dbc.get_max_id() + 1

    area_bit = dbc.find_max_field(3) + 1
    name_offset = dbc.add_string(area_name)

    record = _build_area_record(
        area_id=area_id,
        continent_id=map_id,
        parent_area_id=parent_area_id,
        area_bit=area_bit,
        area_name_offset=name_offset,
        ambience_id=ambience_id,      # Pass through
        zone_music=zone_music,         # Pass through
        light_id=light_id,             # Pass through
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return area_id
```

### 6.4 New `update_area_atmosphere()` Function

```python
def update_area_atmosphere(dbc_dir, area_id, ambience_id=None, zone_music=None, light_id=None):
    """
    Update atmospheric fields for an existing AreaTable record.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_id: Area ID to update.
        ambience_id: SoundAmbience ID (None = no change).
        zone_music: ZoneMusic ID (None = no change).
        light_id: Light ID (None = no change).

    Raises:
        ValueError: If area_id is not found in AreaTable.dbc.

    Example:
        # Update previously created area with atmospheric settings
        update_area_atmosphere(
            dbc_dir='./DBFilesClient',
            area_id=5001,
            ambience_id=300,
            zone_music=200,
            light_id=400,
        )
    """
    filepath = os.path.join(dbc_dir, 'AreaTable.dbc')
    dbc = DBCInjector(filepath)

    # Find record with matching ID
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == area_id:
            # Unpack full record
            buf = bytearray(rec)

            # Update fields at their byte offsets
            if ambience_id is not None:
                struct.pack_into('<I', buf, 28, ambience_id)   # AmbienceID field index 7
            if zone_music is not None:
                struct.pack_into('<I', buf, 32, zone_music)    # ZoneMusic field index 8
            if light_id is not None:
                struct.pack_into('<I', buf, 140, light_id)     # LightID field index 35

            # Replace record
            dbc.records[i] = bytes(buf)
            dbc.write(filepath)
            return

    raise ValueError(f"Area ID {area_id} not found in AreaTable.dbc")
```

---

## 7. Tel'Abim Use Case

Demonstrating the complete atmospheric pipeline for a custom tropical island zone.

### 7.1 Zone Structure

- **Main Zone:** Tel'Abim (parent area)
- **Subzones:** Jungle Basin, Volcanic Caldera, Cave Network, Harbor Town

### 7.2 Atmospheric Requirements

| Zone/Subzone       | Music                     | Ambient Sound                | Lighting                          |
|--------------------|---------------------------|------------------------------|-----------------------------------|
| Tel'Abim (parent)  | Tropical (STV-style)      | Jungle birds + wind          | Bright tropical daylight          |
| Jungle Basin       | (inherits parent music)   | Dense jungle (birds, insects)| (inherits parent light)           |
| Volcanic Caldera   | (inherits parent music)   | Rumbling + lava bubbles      | Orange volcanic glow (localized)  |
| Cave Network       | (inherits parent music)   | Cave drips + distant echoes  | (inherits parent light)           |
| Harbor Town        | (inherits parent music)   | Seagulls + ocean waves       | (inherits parent light)           |

### 7.3 Implementation Example

```python
from world_builder import build_zone
from world_builder.dbc_injector import (
    register_zone_music,
    register_sound_ambience,
    register_light,
    register_area,
    update_area_atmosphere,
)

# Step 1: Create Map and WDT/ADT terrain (existing functionality)
result = build_zone(
    name="TelAbim",
    output_dir="./output",
    coords=[(32, 32), (32, 33), (33, 32), (33, 33)],  # 4-tile island
    heightmap=None,  # Will generate flat terrain for now
    texture_paths=["Tileset\\Jungle\\JungleGrass01.blp"],
    dbc_dir="./DBFilesClient",
)

map_id = result['map_id']        # e.g., 800
parent_area_id = result['area_id']  # e.g., 5001

# Step 2: Register ZoneMusic (reuse Stranglethorn Vale sound IDs)
# Sound IDs extracted from STV's ZoneMusic entry: day=3751, night=3752
zone_music_id = register_zone_music(
    dbc_dir='./DBFilesClient',
    set_name='ZoneMusicTelAbim',
    day_sound_id=3751,      # STV daytime music
    night_sound_id=3752,    # STV nighttime music
    silence_min_day=120000,  # 2 minutes
    silence_max_day=180000,  # 3 minutes
)
print(f"Registered ZoneMusic ID: {zone_music_id}")  # e.g., 200

# Step 3: Register SoundAmbience entries (reuse existing ambient loops)
# Ambient sound IDs from retail zones:
# - Jungle: 5252 (STV jungle ambience)
# - Volcanic: 5300 (Burning Steppes fire/lava)
# - Cave: 5310 (Deepholm cave drips)
# - Harbor: 5280 (Booty Bay ocean waves)

ambience_jungle = register_sound_ambience(
    dbc_dir='./DBFilesClient',
    day_ambience_id=5252,    # Jungle birds
    night_ambience_id=5252,  # Same for night
)
print(f"Registered Jungle Ambience ID: {ambience_jungle}")  # e.g., 300

ambience_volcanic = register_sound_ambience(
    dbc_dir='./DBFilesClient',
    day_ambience_id=5300,    # Lava rumble
    night_ambience_id=5300,
)
print(f"Registered Volcanic Ambience ID: {ambience_volcanic}")  # e.g., 301

ambience_cave = register_sound_ambience(
    dbc_dir='./DBFilesClient',
    day_ambience_id=5310,    # Cave drips
    night_ambience_id=5310,
)
print(f"Registered Cave Ambience ID: {ambience_cave}")  # e.g., 302

ambience_harbor = register_sound_ambience(
    dbc_dir='./DBFilesClient',
    day_ambience_id=5280,    # Ocean waves
    night_ambience_id=5280,
)
print(f"Registered Harbor Ambience ID: {ambience_harbor}")  # e.g., 303

# Step 4: Register Light entries
# LightParams IDs extracted from Stranglethorn Vale and Burning Steppes
# STV tropical light: [130, 131, 132, 133, 134, 135, 136, 137]
# Burning Steppes volcanic: [200, 201, 202, 203, 204, 205, 206, 207]

# Global zone light (tropical daylight)
light_global = register_light(
    dbc_dir='./DBFilesClient',
    map_id=map_id,
    light_params_ids=[130, 131, 132, 133, 134, 135, 136, 137],  # STV params
    position=(0.0, 0.0, 0.0),
    falloff_start=0.0,
    falloff_end=1.0,
)
print(f"Registered Global Light ID: {light_global}")  # e.g., 400

# Localized volcanic glow (centered at caldera coordinates)
light_volcanic = register_light(
    dbc_dir='./DBFilesClient',
    map_id=map_id,
    light_params_ids=[200, 201, 202, 203, 204, 205, 206, 207],  # Burning Steppes params
    position=(16724.0, -2000.0, 50.0),  # Caldera center coordinates
    falloff_start=500.0,   # Full strength within 500 yards
    falloff_end=1000.0,    # Fades out by 1000 yards
)
print(f"Registered Volcanic Light ID: {light_volcanic}")  # e.g., 401

# Step 5: Update parent area with atmospheric settings
update_area_atmosphere(
    dbc_dir='./DBFilesClient',
    area_id=parent_area_id,
    ambience_id=ambience_jungle,  # Default jungle ambience
    zone_music=zone_music_id,
    light_id=light_global,
)
print(f"Updated parent area {parent_area_id} with atmospheric settings")

# Step 6: Create subzones with specific atmospheric overrides
area_jungle = register_area(
    dbc_dir='./DBFilesClient',
    area_name='Jungle Basin',
    map_id=map_id,
    parent_area_id=parent_area_id,
    ambience_id=ambience_jungle,   # Jungle sounds
    zone_music=0,                  # Inherit parent music
    light_id=0,                    # Inherit parent light
)
print(f"Registered Jungle Basin subzone: {area_jungle}")

area_volcanic = register_area(
    dbc_dir='./DBFilesClient',
    area_name='Volcanic Caldera',
    map_id=map_id,
    parent_area_id=parent_area_id,
    ambience_id=ambience_volcanic,  # Volcanic sounds
    zone_music=0,                   # Inherit parent music
    light_id=light_volcanic,        # Use volcanic lighting
)
print(f"Registered Volcanic Caldera subzone: {area_volcanic}")

area_cave = register_area(
    dbc_dir='./DBFilesClient',
    area_name='Cave Network',
    map_id=map_id,
    parent_area_id=parent_area_id,
    ambience_id=ambience_cave,      # Cave sounds
    zone_music=0,                   # Inherit parent music
    light_id=0,                     # Inherit parent light (or create darker cave light)
)
print(f"Registered Cave Network subzone: {area_cave}")

area_harbor = register_area(
    dbc_dir='./DBFilesClient',
    area_name='Harbor Town',
    map_id=map_id,
    parent_area_id=parent_area_id,
    ambience_id=ambience_harbor,    # Harbor sounds
    zone_music=0,                   # Inherit parent music
    light_id=0,                     # Inherit parent light
)
print(f"Registered Harbor Town subzone: {area_harbor}")

print("\nTel'Abim atmospheric setup complete!")
print("- Zone music: Tropical (STV-style)")
print("- Subzone ambiences: Jungle, Volcanic, Cave, Harbor")
print("- Lighting: Bright tropical daylight + localized volcanic glow")
```

### 7.4 Expected DBC Modifications

After running the above script:

**ZoneMusic.dbc** (1 new entry):
- ID 200: "ZoneMusicTelAbim", sounds=[3751, 3752], silence=[120000-180000]

**SoundAmbience.dbc** (4 new entries):
- ID 300: Jungle (day=5252, night=5252)
- ID 301: Volcanic (day=5300, night=5300)
- ID 302: Cave (day=5310, night=5310)
- ID 303: Harbor (day=5280, night=5280)

**Light.dbc** (2 new entries):
- ID 400: Global tropical light (STV LightParams)
- ID 401: Volcanic glow (Burning Steppes LightParams, localized falloff)

**AreaTable.dbc** (5 entries: 1 parent + 4 subzones):
- ID 5001 (Tel'Abim): ZoneMusic=200, AmbienceID=300, LightID=400
- ID 5002 (Jungle Basin): ZoneMusic=0, AmbienceID=300, LightID=0
- ID 5003 (Volcanic Caldera): ZoneMusic=0, AmbienceID=301, LightID=401
- ID 5004 (Cave Network): ZoneMusic=0, AmbienceID=302, LightID=0
- ID 5005 (Harbor Town): ZoneMusic=0, AmbienceID=303, LightID=0

---

## 8. Finding Existing Resource IDs

Users need to identify suitable SoundEntries and LightParams IDs from retail WoW. Here's how:

### 8.1 SoundEntries IDs (for Music and Ambience)

**Tool:** WoW.tools DBCViewer or MyDBCEditor

**Steps:**
1. Open `SoundEntries.dbc` in a DBC viewer
2. Search for zone names or keywords:
   - "Stranglethorn" → Music IDs 3751 (day), 3752 (night)
   - "Jungle" → Ambience ID 5252
   - "Lava" → Ambience ID 5300
   - "Cave" → Ambience ID 5310
   - "Ocean" → Ambience ID 5280
3. Note the ID field for use in `register_zone_music()` and `register_sound_ambience()`

**Python Extraction:**
```python
from world_builder.dbc_injector import DBCInjector

dbc = DBCInjector('DBFilesClient/SoundEntries.dbc')
for i, rec in enumerate(dbc.records):
    sound_id = struct.unpack_from('<I', rec, 0)[0]
    name_offset = struct.unpack_from('<I', rec, 4)[0]
    name = dbc.get_string(name_offset)
    if 'Stranglethorn' in name or 'Jungle' in name:
        print(f"SoundEntries ID {sound_id}: {name}")
```

### 8.2 LightParams IDs (for Lighting)

**Tool:** Extract from existing Light.dbc entries

**Python Extraction:**
```python
from world_builder.dbc_injector import DBCInjector
import struct

dbc = DBCInjector('DBFilesClient/Light.dbc')
for i, rec in enumerate(dbc.records):
    light_id = struct.unpack_from('<I', rec, 0)[0]
    continent_id = struct.unpack_from('<I', rec, 4)[0]
    x, y, z = struct.unpack_from('<fff', rec, 8)
    light_params = struct.unpack_from('<8I', rec, 28)

    # Filter for Stranglethorn Vale (ContinentID=0, Eastern Kingdoms)
    if continent_id == 0 and -13000 < x < -10000 and 200 < y < 2000:
        print(f"Light ID {light_id}: STV region, LightParams = {light_params}")
```

**Common LightParams Ranges:**
- STV (tropical): [130-137]
- Tanaris (desert): [150-157]
- Burning Steppes (volcanic): [200-207]
- Winterspring (snow): [220-227]

---

## 9. Testing Strategy

### 9.1 Unit Tests

Create `tests/test_dbc_atmosphere.py`:

```python
import unittest
import tempfile
import os
import struct
from world_builder.dbc_injector import (
    DBCInjector,
    register_zone_music,
    register_sound_ambience,
    register_light,
    update_area_atmosphere,
)

class TestZoneMusicInjector(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dbc_path = os.path.join(self.test_dir, 'ZoneMusic.dbc')

        # Create empty ZoneMusic.dbc
        dbc = DBCInjector()
        dbc.field_count = 8
        dbc.record_size = 32
        dbc.write(self.dbc_path)

    def test_register_zone_music(self):
        zone_music_id = register_zone_music(
            dbc_dir=self.test_dir,
            set_name='TestMusic',
            day_sound_id=1000,
            night_sound_id=1001,
            silence_min_day=60000,
            silence_max_day=120000,
        )

        # Verify record was added
        dbc = DBCInjector(self.dbc_path)
        self.assertEqual(len(dbc.records), 1)
        self.assertEqual(dbc.record_size, 32)

        # Verify field values
        rec = dbc.records[0]
        self.assertEqual(struct.unpack_from('<I', rec, 0)[0], zone_music_id)
        self.assertEqual(struct.unpack_from('<2I', rec, 8), (60000, 60000))  # silence_min
        self.assertEqual(struct.unpack_from('<2I', rec, 16), (120000, 120000))  # silence_max
        self.assertEqual(struct.unpack_from('<2I', rec, 24), (1000, 1001))  # sounds

    def test_night_defaults_to_day(self):
        zone_music_id = register_zone_music(
            dbc_dir=self.test_dir,
            set_name='TestMusic',
            day_sound_id=1000,
            # night_sound_id omitted
        )

        dbc = DBCInjector(self.dbc_path)
        rec = dbc.records[0]
        sounds = struct.unpack_from('<2I', rec, 24)
        self.assertEqual(sounds, (1000, 1000))  # night should default to day

class TestSoundAmbienceInjector(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dbc_path = os.path.join(self.test_dir, 'SoundAmbience.dbc')

        # Create empty SoundAmbience.dbc
        dbc = DBCInjector()
        dbc.field_count = 3
        dbc.record_size = 12
        dbc.write(self.dbc_path)

    def test_register_sound_ambience(self):
        ambience_id = register_sound_ambience(
            dbc_dir=self.test_dir,
            day_ambience_id=2000,
            night_ambience_id=2001,
        )

        dbc = DBCInjector(self.dbc_path)
        self.assertEqual(len(dbc.records), 1)
        self.assertEqual(dbc.record_size, 12)

        rec = dbc.records[0]
        self.assertEqual(struct.unpack_from('<I', rec, 0)[0], ambience_id)
        self.assertEqual(struct.unpack_from('<2I', rec, 4), (2000, 2001))

class TestLightInjector(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dbc_path = os.path.join(self.test_dir, 'Light.dbc')

        # Create empty Light.dbc
        dbc = DBCInjector()
        dbc.field_count = 15
        dbc.record_size = 60
        dbc.write(self.dbc_path)

    def test_register_light(self):
        light_params = [100, 101, 102, 103, 104, 105, 106, 107]
        light_id = register_light(
            dbc_dir=self.test_dir,
            map_id=800,
            light_params_ids=light_params,
            position=(1000.0, 2000.0, 50.0),
            falloff_start=500.0,
            falloff_end=1000.0,
        )

        dbc = DBCInjector(self.dbc_path)
        self.assertEqual(len(dbc.records), 1)
        self.assertEqual(dbc.record_size, 60)

        rec = dbc.records[0]
        self.assertEqual(struct.unpack_from('<I', rec, 0)[0], light_id)
        self.assertEqual(struct.unpack_from('<I', rec, 4)[0], 800)  # continent_id
        self.assertEqual(struct.unpack_from('<3f', rec, 8), (1000.0, 2000.0, 50.0))
        self.assertEqual(struct.unpack_from('<f', rec, 20)[0], 500.0)  # falloff_start
        self.assertEqual(struct.unpack_from('<f', rec, 24)[0], 1000.0)  # falloff_end
        self.assertEqual(struct.unpack_from('<8I', rec, 28), tuple(light_params))

    def test_invalid_light_params_count(self):
        with self.assertRaises(ValueError):
            register_light(
                dbc_dir=self.test_dir,
                map_id=800,
                light_params_ids=[100, 101],  # Only 2, should be 8
            )

class TestUpdateAreaAtmosphere(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dbc_path = os.path.join(self.test_dir, 'AreaTable.dbc')

        # Create AreaTable.dbc with one test record
        from world_builder.dbc_injector import _build_area_record
        dbc = DBCInjector()
        dbc.field_count = 36
        dbc.record_size = 144

        # Add a test area with ID 5001
        rec = _build_area_record(
            area_id=5001,
            continent_id=800,
            parent_area_id=0,
            area_bit=1,
            area_name_offset=dbc.add_string('Test Area'),
            ambience_id=0,
            zone_music=0,
            light_id=0,
        )
        dbc.records.append(rec)
        dbc.write(self.dbc_path)

    def test_update_atmosphere(self):
        update_area_atmosphere(
            dbc_dir=self.test_dir,
            area_id=5001,
            ambience_id=300,
            zone_music=200,
            light_id=400,
        )

        dbc = DBCInjector(self.dbc_path)
        rec = dbc.records[0]

        self.assertEqual(struct.unpack_from('<I', rec, 28)[0], 300)   # AmbienceID
        self.assertEqual(struct.unpack_from('<I', rec, 32)[0], 200)   # ZoneMusic
        self.assertEqual(struct.unpack_from('<I', rec, 140)[0], 400)  # LightID

    def test_update_partial(self):
        # Only update one field
        update_area_atmosphere(
            dbc_dir=self.test_dir,
            area_id=5001,
            zone_music=200,
        )

        dbc = DBCInjector(self.dbc_path)
        rec = dbc.records[0]

        self.assertEqual(struct.unpack_from('<I', rec, 28)[0], 0)     # AmbienceID unchanged
        self.assertEqual(struct.unpack_from('<I', rec, 32)[0], 200)   # ZoneMusic updated
        self.assertEqual(struct.unpack_from('<I', rec, 140)[0], 0)    # LightID unchanged

    def test_area_not_found(self):
        with self.assertRaises(ValueError):
            update_area_atmosphere(
                dbc_dir=self.test_dir,
                area_id=9999,  # Doesn't exist
                zone_music=200,
            )

if __name__ == '__main__':
    unittest.main()
```

### 9.2 Integration Test

Create `tests/test_telabim_atmosphere.py`:

```python
import unittest
import tempfile
import os
from world_builder import build_zone
from world_builder.dbc_injector import (
    register_zone_music,
    register_sound_ambience,
    register_light,
    register_area,
    update_area_atmosphere,
    DBCInjector,
)

class TestTelAbimAtmosphere(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dbc_dir = os.path.join(self.test_dir, 'DBFilesClient')
        os.makedirs(self.dbc_dir)

        # Create empty DBC files
        for dbc_name, field_count, record_size in [
            ('Map.dbc', 66, 264),
            ('AreaTable.dbc', 36, 144),
            ('ZoneMusic.dbc', 8, 32),
            ('SoundAmbience.dbc', 3, 12),
            ('Light.dbc', 15, 60),
        ]:
            dbc = DBCInjector()
            dbc.field_count = field_count
            dbc.record_size = record_size
            dbc.write(os.path.join(self.dbc_dir, dbc_name))

    def test_full_telabim_pipeline(self):
        # Step 1: Build zone
        result = build_zone(
            name='TelAbim',
            output_dir=self.test_dir,
            coords=[(32, 32)],
            texture_paths=['Test.blp'],
            dbc_dir=self.dbc_dir,
        )

        map_id = result['map_id']
        parent_area_id = result['area_id']

        # Step 2: Register atmospheric resources
        zone_music_id = register_zone_music(
            dbc_dir=self.dbc_dir,
            set_name='ZoneMusicTelAbim',
            day_sound_id=3751,
            night_sound_id=3752,
        )

        ambience_jungle = register_sound_ambience(
            dbc_dir=self.dbc_dir,
            day_ambience_id=5252,
        )

        light_global = register_light(
            dbc_dir=self.dbc_dir,
            map_id=map_id,
            light_params_ids=[130, 131, 132, 133, 134, 135, 136, 137],
        )

        # Step 3: Update parent area
        update_area_atmosphere(
            dbc_dir=self.dbc_dir,
            area_id=parent_area_id,
            ambience_id=ambience_jungle,
            zone_music=zone_music_id,
            light_id=light_global,
        )

        # Step 4: Create subzone
        area_jungle = register_area(
            dbc_dir=self.dbc_dir,
            area_name='Jungle Basin',
            map_id=map_id,
            parent_area_id=parent_area_id,
            ambience_id=ambience_jungle,
        )

        # Verify all DBCs were modified
        zone_music_dbc = DBCInjector(os.path.join(self.dbc_dir, 'ZoneMusic.dbc'))
        self.assertGreater(len(zone_music_dbc.records), 0)

        ambience_dbc = DBCInjector(os.path.join(self.dbc_dir, 'SoundAmbience.dbc'))
        self.assertGreater(len(ambience_dbc.records), 0)

        light_dbc = DBCInjector(os.path.join(self.dbc_dir, 'Light.dbc'))
        self.assertGreater(len(light_dbc.records), 0)

        area_dbc = DBCInjector(os.path.join(self.dbc_dir, 'AreaTable.dbc'))
        self.assertGreaterEqual(len(area_dbc.records), 2)  # Parent + subzone

if __name__ == '__main__':
    unittest.main()
```

### 9.3 In-Game Validation Checklist

After implementing and running the Tel'Abim example:

1. **Music Test**
   - [ ] Enter zone, hear tropical music start within 2-3 minutes
   - [ ] Wait through silence interval, verify music repeats
   - [ ] Test day/night transition (if different tracks configured)

2. **Ambience Test**
   - [ ] Walk through Jungle Basin, hear bird/insect sounds
   - [ ] Enter Volcanic Caldera, hear rumbling/lava bubbles
   - [ ] Enter Cave Network, hear dripping water
   - [ ] Enter Harbor Town, hear ocean waves

3. **Lighting Test**
   - [ ] Zone has bright tropical daylight (STV-style)
   - [ ] Approach Volcanic Caldera, see orange glow intensify
   - [ ] Walk away from caldera, see glow fade out (falloff test)
   - [ ] Test time-of-day transitions (sunrise, noon, sunset, night)

4. **Subzone Inheritance Test**
   - [ ] Music plays consistently across all subzones (inherited from parent)
   - [ ] Ambience changes when crossing subzone boundaries
   - [ ] Lighting transitions smoothly (global + localized blend)

---

## 10. Error Handling

### 10.1 Validation Checks

Add to each register function:

```python
# In register_light()
if not isinstance(light_params_ids, (list, tuple)) or len(light_params_ids) != 8:
    raise ValueError("light_params_ids must be a list of exactly 8 integers")

if falloff_start < 0 or falloff_end < 0:
    raise ValueError("Falloff values must be non-negative")

if falloff_start > falloff_end:
    raise ValueError("falloff_start must be <= falloff_end")

# In register_zone_music()
if silence_min_day < 0 or silence_max_day < 0:
    raise ValueError("Silence intervals must be non-negative")

if silence_min_day > silence_max_day:
    raise ValueError("silence_min must be <= silence_max")

# In register_sound_ambience()
if day_ambience_id < 0 or night_ambience_id < 0:
    raise ValueError("Ambience IDs must be non-negative")
```

### 10.2 DBC Corruption Prevention

```python
# Add to DBCInjector.write()
def write(self, filepath):
    """Write the DBC file back to disk with validation."""
    self.record_count = len(self.records)
    self.string_block_size = len(self.string_block)

    # Validate record sizes
    for i, rec in enumerate(self.records):
        if len(rec) != self.record_size:
            raise ValueError(
                f"Record {i} size mismatch: expected {self.record_size}, got {len(rec)}"
            )

    # Create backup before overwriting
    if os.path.exists(filepath):
        backup_path = filepath + '.bak'
        import shutil
        shutil.copy2(filepath, backup_path)

    # ... existing write logic ...
```

---

## 11. Documentation Updates

### 11.1 Update ROADMAP.md

Add new section after Phase 3:

```markdown
### Phase 3b: Atmospheric DBC Injectors — DONE

Custom zones need music, ambient sounds, and lighting to feel alive. This phase implements three additional DBC injectors:

**ZoneMusic.dbc:** Assigns background music tracks (day/night) to zones.
**SoundAmbience.dbc:** Defines ambient sound layers (birds, wind, lava, etc.) for subzones.
**Light.dbc:** Controls zone lighting, sky colors, fog, and time-of-day effects.

**Implemented in:** `world_builder/dbc_injector.py`
* `register_zone_music()` — inject ZoneMusic entries
* `register_sound_ambience()` — inject SoundAmbience entries
* `register_light()` — inject Light entries (reuses existing LightParams)
* `update_area_atmosphere()` — update existing AreaTable records with atmospheric IDs
* Enhanced `register_area()` with optional `ambience_id`, `zone_music`, `light_id` parameters

**Usage:** See Tel'Abim example in `plans/plan-dbc-atmosphere.md`
```

### 11.2 Update world_builder/__init__.py Docstring

```python
"""
World Builder for WoW WotLK 3.3.5a - Headless World Compiler

This module provides a complete pipeline for creating custom WoW zones:
1. Terrain generation (WDT/ADT files)
2. DBC registration (Map, AreaTable, ZoneMusic, SoundAmbience, Light)
3. MPQ packaging

Example usage:
    from world_builder import build_zone
    from world_builder.dbc_injector import register_zone_music, register_light

    # Build terrain and register map/area
    result = build_zone(
        name='TelAbim',
        coords=[(32, 32)],
        texture_paths=['Tileset\\Jungle\\JungleGrass01.blp'],
        dbc_dir='./DBFilesClient',
    )

    # Add atmospheric settings
    zone_music_id = register_zone_music(
        dbc_dir='./DBFilesClient',
        set_name='ZoneMusicTelAbim',
        day_sound_id=3751,  # Reuse STV music
    )

    light_id = register_light(
        dbc_dir='./DBFilesClient',
        map_id=result['map_id'],
        light_params_ids=[130, 131, 132, 133, 134, 135, 136, 137],  # STV lighting
    )

See plans/plan-dbc-atmosphere.md for detailed documentation.
"""
```

---

## 12. Implementation Checklist

### Phase 1: Core Functions
- [ ] Implement `_build_zone_music_record()`
- [ ] Implement `_build_sound_ambience_record()`
- [ ] Implement `_build_light_record()`
- [ ] Implement `register_zone_music()`
- [ ] Implement `register_sound_ambience()`
- [ ] Implement `register_light()`

### Phase 2: AreaTable Integration
- [ ] Update `_build_area_record()` to accept atmospheric parameters
- [ ] Update `register_area()` signature with optional parameters
- [ ] Implement `update_area_atmosphere()`

### Phase 3: Testing
- [ ] Write unit tests for ZoneMusic injector
- [ ] Write unit tests for SoundAmbience injector
- [ ] Write unit tests for Light injector
- [ ] Write unit tests for `update_area_atmosphere()`
- [ ] Write integration test for Tel'Abim pipeline
- [ ] Manual in-game validation (music, ambience, lighting)

### Phase 4: Documentation
- [ ] Update ROADMAP.md with Phase 3b section
- [ ] Update `world_builder/__init__.py` docstring
- [ ] Add inline code comments for field layouts
- [ ] Create example scripts in `examples/` directory

### Phase 5: Error Handling
- [ ] Add validation checks to all register functions
- [ ] Add DBC corruption prevention to `DBCInjector.write()`
- [ ] Add helpful error messages for common mistakes

---

## 13. Known Limitations

1. **LightParams.dbc Not Implemented**
   - Users must reuse existing LightParams IDs from retail zones
   - Custom sky colors/fog requires manual LightParams.dbc editing
   - Future enhancement: Add `register_light_params()` function

2. **No SoundEntries.dbc Support**
   - Users must reference existing SoundEntries IDs
   - Custom music/ambience requires external tools (Audacity + WoW audio tools)
   - Out of scope for this plan (audio file management is complex)

3. **No AreaTable Deletion**
   - No function to remove existing areas
   - Manual DBC editing required for cleanup
   - Could add `delete_area()` function in future

4. **No ZoneMusic/SoundAmbience/Light Deletion**
   - No cleanup functions implemented
   - Could add `delete_zone_music()`, etc. in future

5. **No Validation of Foreign Keys**
   - Functions don't verify that SoundEntries IDs or LightParams IDs actually exist
   - Invalid IDs will cause client crashes
   - User responsibility to provide valid IDs

---

## 14. Future Enhancements

1. **LightParams.dbc Injector**
   - `register_light_params()` function
   - RGB color specification for sky, fog, water, sun
   - Simplify custom lighting creation

2. **ID Discovery Utilities**
   - `find_sound_entries(keyword)` → Search SoundEntries.dbc
   - `find_light_params(zone_name)` → Extract LightParams from known zones
   - `list_zone_atmospheres(zone_name)` → Show all atmospheric IDs for a zone

3. **Batch Operations**
   - `clone_zone_atmosphere(source_zone, target_zone)` → Copy all atmospheric settings
   - `register_area_batch(subzones=[...])` → Create multiple subzones at once

4. **Validation Tools**
   - `validate_dbc_references()` → Check all foreign keys are valid
   - `detect_dbc_corruption()` → Verify DBC integrity before in-game testing

5. **Higher-Level Presets**
   - `apply_tropical_atmosphere(zone_id)` → One-shot STV-style setup
   - `apply_volcanic_atmosphere(zone_id)` → Burning Steppes-style setup
   - `apply_cave_atmosphere(zone_id)` → Deepholm-style setup

---

## 15. Summary

This plan extends the `world_builder` module with complete atmospheric support for custom WoW zones. The implementation follows the existing `dbc_injector.py` pattern (low-level binary DBC manipulation, no DBD dependencies) and integrates seamlessly with the existing `build_zone()` pipeline.

**Key Features:**
- Three new DBC injectors (ZoneMusic, SoundAmbience, Light)
- Enhanced `register_area()` with atmospheric parameters
- New `update_area_atmosphere()` for post-creation updates
- Comprehensive Tel'Abim use case demonstrating tropical zone creation
- Full unit and integration test coverage
- Reuses existing retail WoW resources (no custom audio/lighting required)

**Implementation Effort:**
- ~500 lines of new code (3 builder functions + 4 public functions + validation)
- ~400 lines of tests (unit + integration)
- ~2-4 hours of development time
- Maintains backward compatibility with existing `register_area()` calls

**Enables TODO Item 1.3:** Complete atmospheric customization for custom zones (music, ambience, lighting) with proper subzone inheritance and localized effects (e.g., volcanic glow).
