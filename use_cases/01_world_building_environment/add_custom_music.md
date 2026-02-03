# Add Custom Music

## Overview

This guide covers every step required to add custom background music and ambient
sound to a WoW WotLK 3.3.5a (build 12340) zone using the `pywowlib` world
builder toolkit. By the end you will have:

- A **ZoneMusic.dbc** entry defining daytime and nighttime music tracks with
  silence intervals
- A **SoundAmbience.dbc** entry defining ambient background sound loops
  (birdsong, wind, insects, etc.)
- An existing **AreaTable.dbc** record patched to reference both the zone music
  and the ambient sound entries
- Optionally, a **Light.dbc** entry for zone-specific atmospheric lighting
- Custom MP3 audio files placed at the correct paths inside the **MPQ** archive
- A complete understanding of how the WoW client selects and plays zone audio

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.8+ | Standard CPython distribution |
| pywowlib | Cloned and importable (`pip install -e .` from repo root) |
| DBC files | A copy of `DBFilesClient/` from the WoW 3.3.5a client MPQ chain |
| MPQ tool | Native StormLib bindings or an external MPQ editor (ladik's MPQ Editor) |
| Audio files | MP3 files for music and/or ambient loops (44100 Hz, stereo, 128-320 kbps recommended) |
| Existing zone | An area that has already been registered in AreaTable.dbc (see [Add New Zone](add_new_zone.md)) |

> **Important**: Back up your DBC directory before running any injection
> functions. The `dbc_injector` module modifies DBC files in place.

---

## How WoW 3.3.5a Handles Zone Audio

Before diving into the code, it is important to understand the audio chain that
the WoW client uses to decide what sounds to play when a player enters a zone.

```
Player enters zone
       |
       v
AreaTable.dbc (area_id)
  |-- field 7  AmbienceID  --> SoundAmbience.dbc --> SoundEntries.dbc (loops)
  |-- field 8  ZoneMusic   --> ZoneMusic.dbc     --> SoundEntries.dbc (tracks)
  '-- field 35 LightID     --> Light.dbc         --> LightParams.dbc
```

### SoundEntries.dbc

`SoundEntries.dbc` is the master table that maps a sound ID to one or more
physical MP3/WAV files on disk. Each entry contains:

| Field | Type | Description |
|---|---|---|
| ID | uint32 | Unique sound entry ID |
| SoundType | uint32 | Category (28 = zone music, 50 = zone ambience) |
| Name | string | Internal identifier |
| File[0..9] | string[10] | Up to 10 MP3/WAV filenames (randomly cycled) |
| Freq[0..9] | uint32[10] | Play frequency weights for each file |
| DirectoryBase | string | Base directory path within the MPQ |
| VolumeFloat | float | Playback volume (0.0 -- 1.0) |
| Flags | uint32 | Playback flags |
| MinDistance | float | Minimum audible distance |
| MaxDistance | float | Maximum audible distance (falloff) |

The `dbc_injector` module provides a `register_sound_entry()` convenience
function that handles the full 31-field record layout automatically. You can
also reuse an existing SoundEntries ID from the retail data (e.g., Grizzly
Hills daytime music is sound entry `11803`) to skip this step entirely.

### ZoneMusic.dbc

Defines a named music set with separate day/night tracks and silence intervals.
The silence interval controls how long the client waits between music tracks
(creating the natural "quiet moment" effect familiar from retail WoW).

### SoundAmbience.dbc

Defines ambient sound loops (environmental background noise) with separate
day/night entries. Unlike ZoneMusic, ambient sounds loop continuously without
silence gaps.

### AreaTable.dbc (atmosphere fields)

Three fields on every AreaTable record control the audio/visual atmosphere:

| Index | Field | Description |
|---|---|---|
| 7 | AmbienceID | Foreign key to SoundAmbience.dbc |
| 8 | ZoneMusic | Foreign key to ZoneMusic.dbc |
| 35 | LightID | Foreign key to Light.dbc |

---

## Step-by-Step Walkthrough

### Step 1 -- Plan Your Audio Setup

Before writing code, decide what your zone needs:

```python
# Planning checklist:
#
# 1. How many music tracks?  (1 is fine, up to 10 per SoundEntries)
# 2. Different music for day vs. night?  (or same track both times)
# 3. Ambient sound loops?  (forest, desert, underwater, etc.)
# 4. Different ambience for day vs. night?  (crickets at night, birds by day)
# 5. Custom lighting atmosphere?  (or reuse existing Light.dbc entries)

# Example plan for a tropical island zone:
ZONE_NAME = "TelAbim"
AREA_ID = 5100            # Must already exist in AreaTable.dbc

# Music: calming island theme during day, mysterious at night
DAY_MUSIC_MP3 = "Sound\\Music\\ZoneMusic\\TelAbim\\TelAbim_Day01.mp3"
NIGHT_MUSIC_MP3 = "Sound\\Music\\ZoneMusic\\TelAbim\\TelAbim_Night01.mp3"

# Ambience: waves and seabirds by day, insects and waves at night
DAY_AMBIENCE_MP3 = "Sound\\Ambience\\TelAbim\\TelAbim_DayAmb.mp3"
NIGHT_AMBIENCE_MP3 = "Sound\\Ambience\\TelAbim\\TelAbim_NightAmb.mp3"
```

### Step 2 -- Register SoundEntries

If you want to use completely custom audio files, register them in
SoundEntries.dbc using the `register_sound_entry()` convenience function.

```python
from world_builder.dbc_injector import register_sound_entry

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"

# ------------------------------------------------------------------
# register_sound_entry() parameters:
#
#   dbc_dir         Path to directory containing SoundEntries.dbc
#   name            Internal name for the sound entry
#   sound_type      1=spell, 2=ambient, 6=zone_music, 50=zone_ambience
#   files           List of up to 10 sound file names
#   directory_base  Base directory path for files (e.g. "Sound\\Music\\")
#   sound_id        Specific sound ID or None for auto (max_id + 1)
#   volume          Volume multiplier 0.0-1.0 (default 1.0)
#   min_distance    Min audible distance (default 8.0)
#   max_distance    Max audible distance (default 45.0)
#   flags           Playback flags (default 0)
#   frequencies     Optional list of playback weights per file
#
# Returns: int -- the assigned sound entry ID
# ------------------------------------------------------------------

# Register four SoundEntries: day music, night music, day ambience,
# night ambience

day_music_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimDayMusic",
    sound_type=28,                        # 28 = zone music
    files=["TelAbim_Day01.mp3"],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.7,
)
print("Day music SoundEntries ID:", day_music_id)

night_music_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimNightMusic",
    sound_type=28,
    files=["TelAbim_Night01.mp3"],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.6,
)
print("Night music SoundEntries ID:", night_music_id)

day_ambience_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimDayAmbience",
    sound_type=50,                        # 50 = zone ambience
    files=["TelAbim_DayAmb.mp3"],
    directory_base="Sound\\Ambience\\TelAbim\\",
    volume=0.5,
)
print("Day ambience SoundEntries ID:", day_ambience_id)

night_ambience_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimNightAmbience",
    sound_type=50,
    files=["TelAbim_NightAmb.mp3"],
    directory_base="Sound\\Ambience\\TelAbim\\",
    volume=0.4,
)
print("Night ambience SoundEntries ID:", night_ambience_id)
```

#### SoundEntries.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique sound entry ID |
| 1 | SoundType | uint32 | Category (28 = zone music, 50 = zone ambience) |
| 2 | Name | string | Internal identifier |
| 3-12 | File[0..9] | string[10] | Up to 10 MP3/WAV filenames |
| 13-22 | Freq[0..9] | uint32[10] | Play frequency weights for each file |
| 23 | DirectoryBase | string | Base directory path within the MPQ |
| 24 | VolumeFloat | float | Playback volume (0.0 -- 1.0) |
| 25 | Flags | uint32 | Playback flags |
| 26 | MinDistance | float | Minimum audible distance |
| 27 | MaxDistance | float | Maximum audible distance (falloff) |
| 28 | DistanceCutoff | float | Distance cutoff |
| 29 | EAXDef | uint32 | EAX definition |
| 30 | SoundEntriesAdvancedID | uint32 | Advanced sound reference |

**Total: 31 fields = 124 bytes per record**

**Alternative: Reuse Retail SoundEntries IDs**

If you prefer to reuse existing WoW music rather than adding custom MP3 files,
simply pick IDs from the retail SoundEntries.dbc. Some well-known examples:

| Zone | SoundEntries ID | Description |
|---|---|---|
| Grizzly Hills (Day) | 11803 | Calm forest strings and woodwind |
| Howling Fjord (Day) | 11801 | Nordic orchestral theme |
| Elwynn Forest (Day) | 2 | Classic pastoral music |
| Duskwood (Day) | 23 | Creepy ambient strings |
| Stormwind City | 59 | Heroic city fanfare |
| Eversong Woods (Day) | 8417 | Ethereal blood elf theme |

```python
# Skip Step 2 entirely and use retail IDs:
day_music_id = 11803     # Grizzly Hills daytime
night_music_id = 11803   # Same track for night (or pick a different one)
day_ambience_id = 11804  # Grizzly Hills day ambience
night_ambience_id = 11804
```

### Step 3 -- Register ZoneMusic Entry

The `register_zone_music()` function creates an entry in **ZoneMusic.dbc**
that bundles a music set name, day/night SoundEntries references, and silence
intervals between tracks.

```python
from world_builder.dbc_injector import register_zone_music

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"

zone_music_id = register_zone_music(
    dbc_dir=DBC_DIR,
    set_name="ZoneMusicTelAbim",
    day_sound_id=day_music_id,
    night_sound_id=night_music_id,
    silence_min_day=120000,       # 2 minutes minimum silence between tracks
    silence_max_day=180000,       # 3 minutes maximum silence between tracks
    silence_min_night=90000,      # 1.5 min -- shorter silence at night
    silence_max_night=150000,     # 2.5 min
)
print("ZoneMusic ID:", zone_music_id)
```

#### ZoneMusic.dbc Field Reference

| Index | Field | Type | Bytes | Description |
|---|---|---|---|---|
| 0 | ID | uint32 | 0--3 | Unique ZoneMusic identifier |
| 1 | SetName | string | 4--7 | Offset into string block -- internal name |
| 2 | SilenceIntervalMin[0] | uint32 | 8--11 | Minimum silence between tracks (day), milliseconds |
| 3 | SilenceIntervalMin[1] | uint32 | 12--15 | Minimum silence between tracks (night), milliseconds |
| 4 | SilenceIntervalMax[0] | uint32 | 16--19 | Maximum silence between tracks (day), milliseconds |
| 5 | SilenceIntervalMax[1] | uint32 | 20--23 | Maximum silence between tracks (night), milliseconds |
| 6 | Sounds[0] | uint32 | 24--27 | FK to SoundEntries.dbc -- daytime music |
| 7 | Sounds[1] | uint32 | 28--31 | FK to SoundEntries.dbc -- nighttime music |

**Total: 8 fields = 32 bytes per record**

#### Parameter Details

- **set_name**: A purely internal label. Convention is `"ZoneMusic{ZoneName}"`.
  It is stored in the DBC string block and referenced by offset.
- **day_sound_id** / **night_sound_id**: Must be valid SoundEntries IDs. If
  `night_sound_id` is `None`, it defaults to `day_sound_id` (same music plays
  24 hours).
- **silence_min_day** / **silence_max_day**: The client picks a random silence
  duration between `min` and `max` after each track finishes. Values are in
  milliseconds. Retail zones typically use 120000--180000 ms (2--3 minutes).
- **silence_min_night** / **silence_max_night**: Same as day equivalents but
  for the nighttime cycle. If `None`, defaults to the day values.

### Step 4 -- Register SoundAmbience Entry

The `register_sound_ambience()` function creates an entry in
**SoundAmbience.dbc**. Ambient sounds loop continuously (no silence gaps)
and blend smoothly during the day/night transition.

```python
from world_builder.dbc_injector import register_sound_ambience

ambience_id = register_sound_ambience(
    dbc_dir=DBC_DIR,
    day_ambience_id=day_ambience_id,
    night_ambience_id=night_ambience_id,
)
print("SoundAmbience ID:", ambience_id)
```

#### SoundAmbience.dbc Field Reference

| Index | Field | Type | Bytes | Description |
|---|---|---|---|---|
| 0 | ID | uint32 | 0--3 | Unique SoundAmbience identifier |
| 1 | AmbienceID[0] | uint32 | 4--7 | FK to SoundEntries.dbc -- daytime ambient loop |
| 2 | AmbienceID[1] | uint32 | 8--11 | FK to SoundEntries.dbc -- nighttime ambient loop |

**Total: 3 fields = 12 bytes per record**

#### Parameter Details

- **day_ambience_id**: SoundEntries ID for the daytime ambient loop. This
  should point to a SoundEntries record with `SoundType = 50` (zone ambience).
- **night_ambience_id**: SoundEntries ID for the nighttime ambient loop. If
  `None`, defaults to `day_ambience_id` (same ambience plays 24 hours).
- **ambience_id**: Specific SoundAmbience ID, or `None` for auto-assignment
  (picks `max_id + 1`).

### Step 5 -- Link Audio to AreaTable (update_area_atmosphere)

Now connect the ZoneMusic and SoundAmbience entries to your zone's AreaTable
record using `update_area_atmosphere()`. This function patches three fields
in an existing AreaTable.dbc record without modifying any other fields.

```python
from world_builder.dbc_injector import update_area_atmosphere

AREA_ID = 5100  # Must already exist in AreaTable.dbc

update_area_atmosphere(
    dbc_dir=DBC_DIR,
    area_id=AREA_ID,
    ambience_id=ambience_id,      # SoundAmbience.dbc ID from Step 4
    zone_music=zone_music_id,     # ZoneMusic.dbc ID from Step 3
    # light_id=None,              # Optional: set a custom Light.dbc ID
)
print("AreaTable updated for area", AREA_ID)
```

#### What update_area_atmosphere() Patches

The function locates the AreaTable record with the matching `area_id` and
modifies these specific byte offsets:

| Byte Offset | Field Index | Field Name | Updated With |
|---|---|---|---|
| 28 | 7 | AmbienceID | `ambience_id` parameter |
| 32 | 8 | ZoneMusic | `zone_music` parameter |
| 140 | 35 | LightID | `light_id` parameter |

Any parameter set to `None` is skipped (the existing value is preserved).

If the `area_id` is not found in AreaTable.dbc, a `ValueError` is raised.

### Step 6 -- Place Audio Files in MPQ

The WoW client expects audio files at specific paths within the MPQ archive.
The path structure matches the `DirectoryBase` field from SoundEntries.dbc.

#### Music File Placement

```
patch-4.MPQ
  |
  +-- Sound/
       +-- Music/
            +-- ZoneMusic/
                 +-- TelAbim/
                      +-- TelAbim_Day01.mp3
                      +-- TelAbim_Night01.mp3
```

#### Ambience File Placement

```
patch-4.MPQ
  |
  +-- Sound/
       +-- Ambience/
            +-- TelAbim/
                 +-- TelAbim_DayAmb.mp3
                 +-- TelAbim_NightAmb.mp3
```

#### Packing with MPQPacker

```python
from world_builder.mpq_packer import MPQPacker

packer = MPQPacker(r"C:\output", patch_name="patch-4.MPQ")

# Add music MP3 files
with open(r"C:\audio\day_music.mp3", "rb") as f:
    packer.add_file(
        r"Sound\Music\ZoneMusic\TelAbim\TelAbim_Day01.mp3",
        f.read()
    )
with open(r"C:\audio\night_music.mp3", "rb") as f:
    packer.add_file(
        r"Sound\Music\ZoneMusic\TelAbim\TelAbim_Night01.mp3",
        f.read()
    )

# Add ambience MP3 files
with open(r"C:\audio\day_ambience.mp3", "rb") as f:
    packer.add_file(
        r"Sound\Ambience\TelAbim\TelAbim_DayAmb.mp3",
        f.read()
    )
with open(r"C:\audio\night_ambience.mp3", "rb") as f:
    packer.add_file(
        r"Sound\Ambience\TelAbim\TelAbim_NightAmb.mp3",
        f.read()
    )

# Add modified DBC files
for dbc_name in ["SoundEntries", "ZoneMusic", "SoundAmbience", "AreaTable"]:
    dbc_path = os.path.join(DBC_DIR, dbc_name + ".dbc")
    with open(dbc_path, "rb") as f:
        packer.add_dbc(dbc_name, f.read())

# Build the output
result = packer.build_mpq()
print("MPQ output:", result)
```

### Step 7 -- Optional: Add Custom Lighting (Light.dbc)

If your zone needs a custom atmosphere (coloured fog, special sky, sunset
tinting), register a Light.dbc entry. Light entries define 8 time-of-day bands
that control fog colours, ambient light, and sky dome rendering.

```python
from world_builder.dbc_injector import register_light

# LightParams IDs define the actual colours/fog/sky for each time band.
# Reuse IDs from a retail zone with a similar aesthetic.
# These IDs are from Grizzly Hills (green forest atmosphere):
GRIZZLY_LIGHT_PARAMS = [
    2337,  # midnight
    2338,  # dawn
    2339,  # morning
    2340,  # noon
    2341,  # afternoon
    2342,  # dusk
    2343,  # evening
    2344,  # night
]

MAP_ID = 800  # Your custom map ID

light_id = register_light(
    dbc_dir=DBC_DIR,
    map_id=MAP_ID,
    light_params_ids=GRIZZLY_LIGHT_PARAMS,
    position=(0.0, 0.0, 0.0),   # (0,0,0) = global zone light
    falloff_start=0.0,           # 0 = full strength everywhere
    falloff_end=1.0,             # 1 = no distance attenuation
)
print("Light ID:", light_id)

# Now link it to the area:
update_area_atmosphere(
    dbc_dir=DBC_DIR,
    area_id=AREA_ID,
    light_id=light_id,
)
```

#### Light.dbc Field Reference

| Index | Field | Type | Bytes | Description |
|---|---|---|---|---|
| 0 | ID | uint32 | 0--3 | Unique Light identifier |
| 1 | ContinentID | uint32 | 4--7 | FK to Map.dbc |
| 2 | GameCoords[0] | float | 8--11 | X position (0 for global) |
| 3 | GameCoords[1] | float | 12--15 | Y position (0 for global) |
| 4 | GameCoords[2] | float | 16--19 | Z position (0 for global) |
| 5 | GameFalloffStart | float | 20--23 | Inner radius -- full strength (yards) |
| 6 | GameFalloffEnd | float | 24--27 | Outer radius -- fades to zero (yards) |
| 7 | LightParamsID[0] | uint32 | 28--31 | FK to LightParams.dbc (midnight) |
| 8 | LightParamsID[1] | uint32 | 32--35 | FK to LightParams.dbc (dawn) |
| 9 | LightParamsID[2] | uint32 | 36--39 | FK to LightParams.dbc (morning) |
| 10 | LightParamsID[3] | uint32 | 40--43 | FK to LightParams.dbc (noon) |
| 11 | LightParamsID[4] | uint32 | 44--47 | FK to LightParams.dbc (afternoon) |
| 12 | LightParamsID[5] | uint32 | 48--51 | FK to LightParams.dbc (dusk) |
| 13 | LightParamsID[6] | uint32 | 52--55 | FK to LightParams.dbc (evening) |
| 14 | LightParamsID[7] | uint32 | 56--59 | FK to LightParams.dbc (night) |

**Total: 15 fields = 60 bytes per record**

The 8 `LightParamsID` slots correspond to time-of-day bands. Each
LightParams.dbc entry controls fog colour, fog distance, ambient light
colour, sun colour, and sky dome parameters for that time band. Creating
custom LightParams records is advanced and beyond the scope of this guide;
reusing retail IDs from a visually similar zone is the recommended approach.

---

## Complete End-to-End Example

This example brings together all the steps into a single script that adds
tropical island music and ambience to a custom zone.

```python
"""
Complete example: Add custom music and ambience to a WoW 3.3.5a zone.
"""

import os
from world_builder.dbc_injector import (
    register_sound_entry,
    register_zone_music,
    register_sound_ambience,
    register_light,
    update_area_atmosphere,
)
from world_builder.mpq_packer import MPQPacker

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
DBC_DIR = r"C:\Games\WoW335\DBFilesClient"
AUDIO_DIR = r"C:\MyMod\audio"
OUTPUT_DIR = r"C:\MyMod\output"
AREA_ID = 5100           # Existing AreaTable entry
MAP_ID = 800             # Map this area belongs to

# ------------------------------------------------------------------
# Step 1: Register SoundEntries for custom MP3 files
# ------------------------------------------------------------------

day_music_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimDayMusic",
    sound_type=28,
    files=["TelAbim_Day01.mp3"],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.7,
)

night_music_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimNightMusic",
    sound_type=28,
    files=["TelAbim_Night01.mp3"],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.6,
)

day_amb_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimDayAmb",
    sound_type=50,
    files=["TelAbim_DayAmb.mp3"],
    directory_base="Sound\\Ambience\\TelAbim\\",
    volume=0.5,
)

night_amb_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimNightAmb",
    sound_type=50,
    files=["TelAbim_NightAmb.mp3"],
    directory_base="Sound\\Ambience\\TelAbim\\",
    volume=0.4,
)

# ------------------------------------------------------------------
# Step 2: Register ZoneMusic
# ------------------------------------------------------------------
zone_music_id = register_zone_music(
    dbc_dir=DBC_DIR,
    set_name="ZoneMusicTelAbim",
    day_sound_id=day_music_id,
    night_sound_id=night_music_id,
    silence_min_day=120000,
    silence_max_day=180000,
    silence_min_night=90000,
    silence_max_night=150000,
)

# ------------------------------------------------------------------
# Step 3: Register SoundAmbience
# ------------------------------------------------------------------
ambience_id = register_sound_ambience(
    dbc_dir=DBC_DIR,
    day_ambience_id=day_amb_id,
    night_ambience_id=night_amb_id,
)

# ------------------------------------------------------------------
# Step 4: Register Light (optional -- reuse Grizzly Hills params)
# ------------------------------------------------------------------
light_id = register_light(
    dbc_dir=DBC_DIR,
    map_id=MAP_ID,
    light_params_ids=[2337, 2338, 2339, 2340, 2341, 2342, 2343, 2344],
    position=(0.0, 0.0, 0.0),
    falloff_start=0.0,
    falloff_end=1.0,
)

# ------------------------------------------------------------------
# Step 5: Link everything to AreaTable
# ------------------------------------------------------------------
update_area_atmosphere(
    dbc_dir=DBC_DIR,
    area_id=AREA_ID,
    ambience_id=ambience_id,
    zone_music=zone_music_id,
    light_id=light_id,
)

# ------------------------------------------------------------------
# Step 6: Pack audio files + DBC into MPQ
# ------------------------------------------------------------------
packer = MPQPacker(OUTPUT_DIR, patch_name="patch-4.MPQ")

# Audio files
audio_mapping = {
    r"Sound\Music\ZoneMusic\TelAbim\TelAbim_Day01.mp3":
        os.path.join(AUDIO_DIR, "day_music.mp3"),
    r"Sound\Music\ZoneMusic\TelAbim\TelAbim_Night01.mp3":
        os.path.join(AUDIO_DIR, "night_music.mp3"),
    r"Sound\Ambience\TelAbim\TelAbim_DayAmb.mp3":
        os.path.join(AUDIO_DIR, "day_ambience.mp3"),
    r"Sound\Ambience\TelAbim\TelAbim_NightAmb.mp3":
        os.path.join(AUDIO_DIR, "night_ambience.mp3"),
}

for mpq_path, local_path in audio_mapping.items():
    with open(local_path, "rb") as f:
        packer.add_file(mpq_path, f.read())

# DBC files
for dbc_name in ["SoundEntries", "ZoneMusic", "SoundAmbience",
                  "AreaTable", "Light"]:
    dbc_path = os.path.join(DBC_DIR, dbc_name + ".dbc")
    with open(dbc_path, "rb") as f:
        packer.add_dbc(dbc_name, f.read())

result = packer.build_mpq()
print("Complete! Output:", result)
```

---

## Advanced Topics

### Multiple Music Tracks per SoundEntries

SoundEntries.dbc supports up to 10 file slots per entry. The client randomly
selects from the available tracks each time it needs to play music, using the
frequency weights to bias selection.

```python
from world_builder.dbc_injector import register_sound_entry

# Register a SoundEntries with 3 daytime tracks
day_music_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimDayMusicSet",
    sound_type=28,
    files=[
        "TelAbim_Day01.mp3",
        "TelAbim_Day02.mp3",
        "TelAbim_Day03.mp3",
    ],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.7,
    frequencies=[2, 1, 1],    # First track plays twice as often
)
# The client will randomly pick from the three tracks
# biased by the frequency weights
```

### Day/Night Transition Behaviour

The WoW client manages day/night audio transitions automatically:

1. **Dawn** (06:00 game time): Day music/ambience fades in, night fades out
2. **Dusk** (18:00 game time): Night music/ambience fades in, day fades out
3. The crossfade duration is controlled by the client engine (approximately
   30 seconds) and cannot be customised via DBC
4. If `night_sound_id` equals `day_sound_id`, no audible transition occurs

### Subzone Music Override

Each subzone (child area in AreaTable.dbc) can have its own ZoneMusic and
SoundAmbience IDs, overriding the parent zone. This allows different music
in different parts of the same zone (e.g., a dark cave within a sunny forest).

```python
# Register the parent zone audio
update_area_atmosphere(
    dbc_dir=DBC_DIR,
    area_id=5100,             # Parent zone
    ambience_id=forest_amb,
    zone_music=forest_music,
)

# Register a subzone with different, darker music
dark_cave_music_id = register_zone_music(
    dbc_dir=DBC_DIR,
    set_name="ZoneMusicTelAbimCave",
    day_sound_id=cave_music_sound_id,
    night_sound_id=cave_music_sound_id,   # Same track 24h in a cave
    silence_min_day=60000,
    silence_max_day=120000,
)

update_area_atmosphere(
    dbc_dir=DBC_DIR,
    area_id=5101,             # Subzone area ID
    ambience_id=cave_amb,
    zone_music=dark_cave_music_id,
)
```

### Zone Intro Music (Stinger)

A zone intro music stinger is a short musical phrase that plays once when the
player first enters a zone (think of the dramatic fanfare when entering
Stormwind). This is managed through **ZoneIntroMusicTable.dbc** and can be
registered using the `register_zone_intro_music()` convenience function.

#### ZoneIntroMusicTable.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique intro music identifier |
| 1 | Name | string | Internal name |
| 2 | SoundID | uint32 | FK to SoundEntries.dbc |
| 3 | Priority | uint32 | Playback priority (default 0) |
| 4 | MinDelayMinutes | uint32 | Min delay in minutes between plays (default 0) |

**Total: 5 fields = 20 bytes per record**

```python
from world_builder.dbc_injector import register_sound_entry, register_zone_intro_music

# First register the intro stinger in SoundEntries.dbc
intro_sound_id = register_sound_entry(
    dbc_dir=DBC_DIR,
    name="TelAbimIntro",
    sound_type=28,                        # Music
    files=["TelAbim_Intro.mp3"],
    directory_base="Sound\\Music\\ZoneMusic\\TelAbim\\",
    volume=0.8,
)

# Then register the zone intro music entry
intro_id = register_zone_intro_music(
    dbc_dir=DBC_DIR,
    name="TelAbimIntroMusic",
    sound_id=intro_sound_id,              # FK to SoundEntries
    intro_id=None,                        # Auto-assign ID (max_id + 1)
    priority=1,                           # Playback priority
    min_delay=0,                          # Minimum delay in minutes
)
print("ZoneIntroMusic ID:", intro_id)
```

> **Note**: The intro music ID can be linked to a zone through AreaTable.dbc
> or directly via the client's zone trigger system, depending on your server
> emulator's implementation.

### Silence Interval Tuning

The silence interval between music tracks significantly affects zone feel:

| Style | Min (ms) | Max (ms) | Effect |
|---|---|---|---|
| Continuous | 0 | 0 | Music never stops (rare in retail) |
| Intense | 30000 | 60000 | 30s--1min gap (dungeons, battlegrounds) |
| Standard | 120000 | 180000 | 2--3min gap (most retail zones) |
| Sparse | 300000 | 600000 | 5--10min gap (desolate, eerie zones) |
| Very sparse | 600000 | 1200000 | 10--20min gap (extreme isolation) |

---

## Audio File Requirements

### MP3 Format

| Property | Recommended Value |
|---|---|
| Format | MP3 (MPEG Layer-3) |
| Sample rate | 44100 Hz |
| Channels | Stereo (2ch) |
| Bitrate | 128--320 kbps (CBR or VBR) |
| Length (music) | 2--5 minutes per track |
| Length (ambience) | 30--120 seconds, designed to loop seamlessly |

### WAV Format (Alternative)

WAV files are supported but significantly larger. Use only if MP3 compression
causes audible artefacts in ambient loops.

| Property | Recommended Value |
|---|---|
| Format | WAV (PCM) |
| Sample rate | 44100 Hz |
| Channels | Stereo (2ch) |
| Bit depth | 16-bit |

### Seamless Looping Tips for Ambient Sounds

1. Ensure the first and last 50ms of the audio file have matching amplitude
   and frequency content to avoid audible clicks at the loop point
2. Apply a very short crossfade (10--50ms) at the loop boundary
3. Test the loop in Audacity using "Effect > Repeat" before packaging
4. Keep ambient loops short (30--60s) to minimize memory usage

---

## Common Pitfalls and Troubleshooting

### No Music Plays In-Game

| Cause | Solution |
|---|---|
| AreaTable.dbc not updated | Verify `ZoneMusic` field (index 8) is set using `update_area_atmosphere()` |
| Wrong SoundEntries ID | Check that `day_sound_id` in ZoneMusic.dbc points to a valid SoundEntries record |
| MP3 file not found | Verify the MP3 file exists at the exact path specified in `DirectoryBase` + `File[0]` |
| MP3 in wrong MPQ | The patch MPQ must be loaded after the base MPQs (use `patch-4.MPQ` or higher) |
| Corrupt MP3 | Re-encode with a standard encoder (LAME); avoid unusual bitrates |

### Music Plays But No Ambient Sound

| Cause | Solution |
|---|---|
| AmbienceID field not set | Check AreaTable field index 7 is updated |
| Wrong SoundType | Ambient entries must use `SoundType = 50`, not 28 |
| Volume too low | Increase the `VolumeFloat` field in SoundEntries (default 1.0) |

### Audio Cuts Out When Entering Subzone

When a player crosses from one AreaTable zone into a subzone, the client
checks the subzone's own `ZoneMusic` and `AmbienceID` fields. If these are
0, the client falls back to the parent zone's audio. If they are set to
different IDs, the audio switches abruptly.

**Fix**: Either leave subzone audio fields at 0 (inherit from parent) or
ensure subzone music uses the same SoundEntries IDs as the parent for a
seamless experience.

### Patch MPQ Not Loading

The WoW 3.3.5a client loads MPQ patches in alphabetical order. Your patch
file must be named `patch-[letter/number].MPQ` where the letter/number sorts
after the existing patches. Common choices:

- `patch-4.MPQ` (safe default for most setups)
- `patch-A.MPQ` (loads after all numeric patches)
- `patch-Z.MPQ` (loads last, highest priority)

---

## Validation Checklist

After completing all steps, verify your setup:

- [ ] **SoundEntries.dbc** contains new records with correct `SoundType`
      (28 for music, 50 for ambience)
- [ ] **SoundEntries** `DirectoryBase` path matches the MPQ directory
      where MP3 files are placed
- [ ] **SoundEntries** `File[0]` matches the actual MP3 filename (case-sensitive)
- [ ] **ZoneMusic.dbc** contains a new record with valid `Sounds[0]` and
      `Sounds[1]` referencing SoundEntries IDs
- [ ] **SoundAmbience.dbc** contains a new record with valid `AmbienceID[0]`
      and `AmbienceID[1]`
- [ ] **AreaTable.dbc** record for your zone has `AmbienceID` (field 7) and
      `ZoneMusic` (field 8) set to non-zero values
- [ ] MP3 files are placed at the correct MPQ paths matching SoundEntries
- [ ] Patch MPQ is in the WoW `Data/` directory with a name that loads after
      base patches
- [ ] In-game: music plays after entering the zone and waiting for the silence
      interval to expire
- [ ] In-game: ambient sound is audible immediately upon zone entry
- [ ] In-game: day/night transition produces the expected audio change

---

## Cross-References

- [Add New Zone (Exterior)](add_new_zone.md) -- Creating the zone and
  AreaTable.dbc entry that this guide references
- [Add New Dungeon (Instance)](add_new_dungeon.md) -- Dungeons use the same
  ZoneMusic/SoundAmbience system
- [Change Loading Screen](change_loading_screen.md) -- Loading screens are
  linked via `LoadingScreens.dbc`, which is separate from audio but often
  configured at the same time
- [Update Zone Scenery](update_zone_scenery.md) -- Modifying terrain does not
  affect audio, but re-packing the MPQ may require including updated DBC files
