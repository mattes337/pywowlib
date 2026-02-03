# Add Playable Race

## Complexity Rating: EXTREME

Adding a fully playable custom race to WoW WotLK 3.3.5a is one of the most complex
modding tasks possible. It touches virtually every layer of the game: client-side DBC
files, 3D model assets, server-side C++ core code, SQL database tables, and UI
elements. A realistic estimate for a complete custom race implementation is **200-500
hours of work** across multiple disciplines (3D modeling, C++ programming, database
configuration, and DBC editing).

This guide documents every DBC, SQL, and code change required. It also covers the
practical alternative approach of **reskinning an existing race**, which achieves
80% of the visual result with 10% of the effort.

**Why is this so hard?** Every piece of equipment in WoW (helmets, shoulders, gloves,
boots, chest pieces) is fitted to specific head, shoulder, hand, foot, and torso
geometry for each race and gender. When you add a new race, you must either:

- Refit **every single equipment model** in the game for your new race's body shape, or
- Clone an existing race's skeleton and modify only textures/proportions (reskin).

The helmet-refitting problem alone involves modifying thousands of M2 model files.

---

## Table of Contents

1. [Overview and Architecture](#1-overview-and-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Understanding the Race Data Model](#3-understanding-the-race-data-model)
4. [ChrRaces.dbc Field Layout](#4-chrracesdbc-field-layout)
5. [CharBaseInfo.dbc -- Race/Class Combinations](#5-charbaseinfodbc----raceclass-combinations)
6. [CharStartOutfit.dbc -- Starting Equipment](#6-charstartoutfitdbc----starting-equipment)
7. [Step 1: Register the Race in ChrRaces.dbc](#7-step-1-register-the-race-in-chrracesdbc)
8. [Step 2: Define Class Combinations in CharBaseInfo.dbc](#8-step-2-define-class-combinations-in-charbaseinfodbc)
9. [Step 3: Define Starting Outfits](#9-step-3-define-starting-outfits)
10. [Step 4: Server-Side C++ Core Changes](#10-step-4-server-side-c-core-changes)
11. [Step 5: Player Level Stats SQL](#11-step-5-player-level-stats-sql)
12. [Step 6: The Helmet-Refitting Problem](#12-step-6-the-helmet-refitting-problem)
13. [Alternative Approach: Reskinning an Existing Race](#13-alternative-approach-reskinning-an-existing-race)
14. [MPQ File Placement](#14-mpq-file-placement)
15. [Complete Code Examples](#15-complete-code-examples)
16. [Common Pitfalls and Troubleshooting](#16-common-pitfalls-and-troubleshooting)
17. [Cross-References](#17-cross-references)

---

## 1. Overview and Architecture

A playable race in WoW 3.3.5a is defined across multiple interconnected systems:

```
CLIENT SIDE (DBC + Models)                SERVER SIDE (C++ + SQL)
==============================            ==============================

ChrRaces.dbc                              Player.cpp / Player.h
  - Race ID, name, faction                  - Race bitmask validation
  - Male/Female display model               - Starting position
  - Client file prefix                      - Racial spells
  - Faction template                        - Creation screen logic
        |
        v                                 player_levelstats (SQL)
CharBaseInfo.dbc                            - STR/AGI/STA/INT/SPI
  - Valid race+class combos                   per level per class
        |                                     for this race (80 rows
        v                                     per class)
CharStartOutfit.dbc
  - Starting gear per                     player_createinfo (SQL)
    race/class/gender                       - Starting zone, map,
                                              position, orientation
        |
        v                                 playercreateinfo_spell (SQL)
Character Models (.m2)                      - Racial abilities
  - Body mesh                               - Language spells
  - Skeleton
  - Animations                            playercreateinfo_action (SQL)
  - Facial features                         - Action bar layout for
  - Hair styles                               each class
        |
        v
Helmet/Armor Models (.m2)
  - MUST be refit for new
    head/body geometry
  - Thousands of items affected
```

### The Scope of Changes

| System | Files Changed | Effort Level |
|--------|--------------|--------------|
| ChrRaces.dbc | 1 DBC file | Low |
| CharBaseInfo.dbc | 1 DBC file | Low |
| CharStartOutfit.dbc | 1 DBC file | Medium (many records) |
| Character models | 2+ M2 files (male/female) | Very High (3D art) |
| Helmet refitting | 1000+ M2 files | Extreme |
| Armor refitting | 500+ texture files | High |
| Server core C++ | 3-10 source files | High (requires rebuild) |
| SQL tables | 5+ tables, hundreds of rows | Medium |
| Character creation screen | XML/Lua UI files | Medium |

---

## 2. Prerequisites

### Required Knowledge and Tools

| Requirement | Purpose |
|-------------|---------|
| **pywowlib** | DBC injection via `DBCInjector` class |
| **C++ compiler** (Visual Studio / GCC) | Rebuilding the server core |
| **AzerothCore / TrinityCore source** | Server core modifications |
| **3D modeling tool** (Blender + WoW export plugin) | Character model creation |
| **M2 editor** (Multiconverter, WoW Model Viewer) | M2 model file editing |
| **BLP tools** (BLP Laboratory, BLPConverter) | Texture creation and conversion |
| **MPQ Editor** (Ladik's MPQEditor) | DBC extraction and patch packing |
| **SQL client** (HeidiSQL, DBeaver, mysql CLI) | Database modifications |

### Extracted DBC Files

You will need these DBC files extracted from the client:

```
DBFilesClient/ChrRaces.dbc
DBFilesClient/CharBaseInfo.dbc
DBFilesClient/CharStartOutfit.dbc
DBFilesClient/CreatureDisplayInfo.dbc     (reference)
DBFilesClient/CreatureModelData.dbc       (reference)
DBFilesClient/FactionTemplate.dbc         (reference)
DBFilesClient/ChrClasses.dbc              (reference)
```

---

## 3. Understanding the Race Data Model

### Existing WotLK 3.3.5a Race IDs

| ID | Race | Faction | ClientFilestring |
|----|------|---------|------------------|
| 1 | Human | Alliance | `Human` |
| 2 | Orc | Horde | `Orc` |
| 3 | Dwarf | Alliance | `Dwarf` |
| 4 | Night Elf | Alliance | `NightElf` |
| 5 | Undead | Horde | `Scourge` |
| 6 | Tauren | Horde | `Tauren` |
| 7 | Gnome | Alliance | `Gnome` |
| 8 | Troll | Horde | `Troll` |
| 9 | Goblin | (unused in 3.3.5) | `Goblin` |
| 10 | Blood Elf | Horde | `BloodElf` |
| 11 | Draenei | Alliance | `Draenei` |

Race IDs 12+ are available for custom races. The client can technically handle
race IDs up to approximately 31 due to bitmask limitations in the server core
(races are stored as a 32-bit bitmask in several places).

### The ClientFilestring System

The `ClientFilestring` field in ChrRaces.dbc tells the client where to find all
model and texture files for the race. For a race with `ClientFilestring = "Troll"`,
the client looks for:

```
Character\Troll\Male\TrollMale.m2           -- Male body model
Character\Troll\Female\TrollFemale.m2       -- Female body model
Character\Troll\Male\TrollMaleSkin00_00.blp  -- Male skin texture variant 0
Character\Troll\Female\TrollFemaleSkin00_00.blp
Character\Troll\Male\TrollMaleHair00_00.blp  -- Male hairstyle 0
...etc
```

When creating a custom race, you either:
1. Create new model/texture files at a new path (e.g., `Character\MyRace\...`), or
2. Reuse an existing race's `ClientFilestring` and only modify textures (reskin).

---

## 4. ChrRaces.dbc Field Layout

ChrRaces.dbc defines each playable (and non-playable) race in the game. The WotLK
3.3.5a version has the following field layout. This DBC is one of the largest and
most complex in the game.

**Record size: 236 bytes (59 fields)**

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `ID` | uint32 | Unique race ID. Existing races use 1-11. Custom races should use 12+. Maximum practical ID is around 23-31 due to bitmask constraints in the server core. |
| 1 | `Flags` | uint32 | Race behavior flags. `0x1` = playable. `0x2` = death knight available. Without `0x1`, the race will not appear on the character creation screen. |
| 2 | `FactionID` | uint32 | FK to `FactionTemplate.dbc`. Determines PvP faction, reputation behavior, and which NPCs are hostile. Alliance races use faction template IDs like 1 (Human), 3 (Dwarf), 4 (Night Elf), 115 (Gnome), 1629 (Draenei). Horde races use 2 (Orc), 5 (Undead), 6 (Tauren), 116 (Troll), 1610 (Blood Elf). |
| 3 | `ExplorationSoundID` | uint32 | FK to `SoundEntries.dbc`. Sound played when discovering a new area. Usually around 4797-4868 for retail races. |
| 4 | `MaleDisplayId` | uint32 | FK to `CreatureDisplayInfo.dbc`. The display ID for the default male character model. This display entry in turn references the M2 model file through `CreatureModelData.dbc`. |
| 5 | `FemaleDisplayId` | uint32 | FK to `CreatureDisplayInfo.dbc`. Same as above but for the female model. |
| 6 | `ClientPrefix` | string | Internal prefix used for some client file lookups. Examples: `"Hu"` (Human), `"Or"` (Orc), `"Dw"` (Dwarf), `"Ni"` (Night Elf), `"Sc"` (Undead), `"Ta"` (Tauren), `"Gn"` (Gnome), `"Tr"` (Troll), `"Be"` (Blood Elf), `"Dr"` (Draenei). |
| 7 | `BaseLanguage` | uint32 | Default language spoken by this race. `7` = Common (Alliance), `1` = Orcish (Horde). |
| 8 | `CreatureType` | uint32 | Creature type classification. `7` = Humanoid for all playable races. |
| 9 | `ResSicknessSpellID` | uint32 | Spell ID applied when resurrecting at a graveyard with resurrection sickness. Standard value: `15007`. |
| 10 | `SplashSoundID` | uint32 | FK to `SoundEntries.dbc`. Sound played when the character jumps into water. |
| 11 | `ClientFilestring` | string | **Critical field.** Directory name under `Character\` where all model and texture files are located. Examples: `"Human"`, `"Orc"`, `"NightElf"`, `"BloodElf"`, `"Draenei"`. This drives the entire model/texture loading pipeline. |
| 12 | `CinematicSequenceID` | uint32 | FK to `CinematicSequences.dbc`. The intro cinematic played after character creation. Set to `0` for no cinematic. Retail values: 81 (Human), 21 (Orc), 41 (Dwarf), 61 (Night Elf), 2 (Undead), 141 (Tauren), 101 (Gnome), 163 (Troll), 0 (Goblin), 162 (Blood Elf), 161 (Draenei). |
| 13 | `Alliance` | uint32 | Faction side. `0` = Alliance, `1` = Horde. Determines which faction tab the race appears on in the character creation screen. |
| 14-30 | `Name_lang` | locstring (17 uint32) | Localized race name (e.g., "Human", "Orc"). Slot 0 = enUS. |
| 31-47 | `NameFemale_lang` | locstring (17 uint32) | Localized female race name. In English this is usually identical to `Name_lang`. In languages with grammatical gender (e.g., German: "Mensch" / "Menschin"), this differs. Set to the same string offset as `Name_lang` if not using gender-specific names. |
| 48-64 | `NameMale_lang` | locstring (17 uint32) | Localized male race name. Same logic as `NameFemale_lang`. Usually identical to `Name_lang` for English. |
| 65 | `FacialHairCustomization[0]` | string | Internal name for the first facial hair customization category (e.g., `"Beards"`, `"Earrings"`, `"Tusks"`, `"Features"`). |
| 66 | `FacialHairCustomization[1]` | string | Internal name for the second facial hair customization category. |
| 67 | `HairCustomization` | string | Internal name for hair customization. Usually `"Normal"`. Tauren use `"Horns"`. |
| 68 | `Required_expansion` | uint32 | Expansion required to create this race. `0` = Classic/base game, `1` = TBC, `2` = WotLK. Blood Elf and Draenei use `1`. |

### Flags Field Detail

| Bit | Value | Meaning |
|-----|-------|---------|
| 0 | `0x1` | Playable -- race appears in character creation. |
| 1 | `0x2` | Death Knight eligible -- this race can be Death Knights. |
| 2 | `0x4` | (Unused in 3.3.5a) |
| 3 | `0x8` | NPC race -- used for NPC-only races like Naga. |

For a fully playable custom race with Death Knight support, use `Flags = 3` (0x1 | 0x2).

---

## 5. CharBaseInfo.dbc -- Race/Class Combinations

CharBaseInfo.dbc is a simple lookup table that defines which race/class combinations
are valid. Each record allows one combination.

**Record size: 4 bytes (2 fields, but packed as bytes in a 4-byte record)**

The structure is unusual for a DBC file: it uses byte-level packing rather than
uint32 fields.

| Byte Offset | Field | Type | Description |
|-------------|-------|------|-------------|
| 0 | `RaceID` | uint8 | Race ID (FK to ChrRaces.dbc). |
| 1 | `ClassID` | uint8 | Class ID (FK to ChrClasses.dbc). |
| 2-3 | (padding) | uint8[2] | Zero padding to align to 4 bytes. |

### WotLK 3.3.5a Class IDs

| ID | Class | Available to (Retail) |
|----|-------|-----------------------|
| 1 | Warrior | All races |
| 2 | Paladin | Human, Dwarf, Draenei, Blood Elf |
| 3 | Hunter | Dwarf, Night Elf, Draenei, Orc, Tauren, Troll, Blood Elf |
| 4 | Rogue | Human, Dwarf, Night Elf, Gnome, Orc, Undead, Troll, Blood Elf |
| 5 | Priest | Human, Dwarf, Night Elf, Draenei, Undead, Troll, Blood Elf |
| 6 | Death Knight | All races (requires level 55+ existing character) |
| 7 | Shaman | Draenei, Orc, Tauren, Troll |
| 8 | Mage | Human, Gnome, Draenei, Undead, Troll, Blood Elf |
| 9 | Warlock | Human, Gnome, Orc, Undead, Blood Elf |
| 11 | Druid | Night Elf, Tauren |

**Note**: Class ID `10` does not exist in 3.3.5a (it was reserved for Monks added later).

---

## 6. CharStartOutfit.dbc -- Starting Equipment

CharStartOutfit.dbc defines the gear, bags, and items that a newly created character
starts with. Each record specifies the equipment for one race/class/gender
combination.

**Record size: 296 bytes (74 fields)**

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | `ID` | uint32 | Unique record ID. |
| 1 | `RaceID` | uint8 | Race ID (packed in low byte of a uint32 along with ClassID and SexID). |
| 1 | `ClassID` | uint8 | Class ID (second byte). |
| 1 | `SexID` | uint8 | Gender: `0` = Male, `1` = Female. (Third byte). |
| 1 | `OutfitID` | uint8 | Outfit variant (fourth byte). Usually `0`. |
| 2-25 | `ItemID[24]` | int32[24] | Array of 24 item template IDs. Unused slots are `-1`. Slot order: Head, Neck, Shoulders, Body (shirt), Chest, Waist, Legs, Feet, Wrists, Hands, Finger1, Finger2, Trinket1, Trinket2, Back, MainHand, OffHand, Ranged, Tabard, Bag1, Bag2, Bag3, Bag4, Ammo. |
| 26-49 | `DisplayItemID[24]` | int32[24] | Display IDs for each item (FK to ItemDisplayInfo.dbc). `-1` for unused slots. |
| 50-73 | `InventoryType[24]` | int32[24] | Inventory slot type for each item (FK to item InventoryType enum). `-1` for unused. |

### Starting Gear Examples

A Human Warrior (Male) might start with:

| Slot Index | Slot Name | Item |
|------------|-----------|------|
| 0 | Head | -1 (none) |
| 1 | Neck | -1 (none) |
| 2 | Shoulders | -1 (none) |
| 3 | Body (Shirt) | Recruit's Shirt (6096) |
| 4 | Chest | Recruit's Vest (25) |
| 5 | Waist | -1 (none) |
| 6 | Legs | Recruit's Pants (26) |
| 7 | Feet | Recruit's Boots (29) |
| 8 | Wrists | -1 (none) |
| 9 | Hands | -1 (none) |
| 15 | MainHand | Worn Shortsword (25) |
| 16 | OffHand | Worn Wooden Shield (2362) |

Slots 10-14 and 17-23 are typically `-1` (empty) for starting characters.

---

## 7. Step 1: Register the Race in ChrRaces.dbc

Use the low-level `DBCInjector` class to add a new record to ChrRaces.dbc. There is
no high-level convenience function for this DBC because of its unusual field layout
and the extreme rarity of the operation.

```python
import struct
import os
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import DBCInjector, _pack_locstring


def register_custom_race(
    dbc_dir,
    race_id,
    race_name,
    faction_id,
    male_display_id,
    female_display_id,
    client_filestring,
    alliance_side,           # 0 = Alliance, 1 = Horde
    client_prefix="Cu",
    base_language=7,         # 7 = Common, 1 = Orcish
    exploration_sound_id=4797,
    creature_type=7,         # 7 = Humanoid
    res_sickness_spell=15007,
    splash_sound_id=0,
    cinematic_sequence_id=0,
    facial_hair_1="Beards",
    facial_hair_2="Earrings",
    hair_customization="Normal",
    required_expansion=2,    # 2 = WotLK
    flags=3,                 # 0x1 playable + 0x2 DK eligible
):
    """
    Register a new playable race in ChrRaces.dbc.

    This function directly constructs the binary record for ChrRaces.dbc
    using the WotLK 3.3.5a field layout (59 fields, 236 bytes per record).

    Args:
        dbc_dir: Path to directory containing ChrRaces.dbc.
        race_id: Unique race ID (12+ for custom races).
        race_name: English name for the race (e.g., "Naga").
        faction_id: FactionTemplate.dbc ID.
        male_display_id: CreatureDisplayInfo ID for male model.
        female_display_id: CreatureDisplayInfo ID for female model.
        client_filestring: Directory name under Character/ for models.
        alliance_side: 0 = Alliance, 1 = Horde.
        ... (see parameter list above for all options)

    Returns:
        int: The assigned race ID.
    """

    filepath = os.path.join(dbc_dir, 'ChrRaces.dbc')
    dbc = DBCInjector(filepath)

    # Add strings to string block
    name_offset = dbc.add_string(race_name)
    prefix_offset = dbc.add_string(client_prefix)
    filestring_offset = dbc.add_string(client_filestring)
    facial1_offset = dbc.add_string(facial_hair_1)
    facial2_offset = dbc.add_string(facial_hair_2)
    hair_offset = dbc.add_string(hair_customization)

    # Build the 236-byte record
    buf = bytearray()

    # Field 0: ID
    buf += struct.pack('<I', race_id)
    # Field 1: Flags
    buf += struct.pack('<I', flags)
    # Field 2: FactionID
    buf += struct.pack('<I', faction_id)
    # Field 3: ExplorationSoundID
    buf += struct.pack('<I', exploration_sound_id)
    # Field 4: MaleDisplayId
    buf += struct.pack('<I', male_display_id)
    # Field 5: FemaleDisplayId
    buf += struct.pack('<I', female_display_id)
    # Field 6: ClientPrefix (string offset)
    buf += struct.pack('<I', prefix_offset)
    # Field 7: BaseLanguage
    buf += struct.pack('<I', base_language)
    # Field 8: CreatureType
    buf += struct.pack('<I', creature_type)
    # Field 9: ResSicknessSpellID
    buf += struct.pack('<I', res_sickness_spell)
    # Field 10: SplashSoundID
    buf += struct.pack('<I', splash_sound_id)
    # Field 11: ClientFilestring (string offset)
    buf += struct.pack('<I', filestring_offset)
    # Field 12: CinematicSequenceID
    buf += struct.pack('<I', cinematic_sequence_id)
    # Field 13: Alliance (0=Alliance, 1=Horde)
    buf += struct.pack('<I', alliance_side)
    # Fields 14-30: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # Fields 31-47: NameFemale_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)  # Same name for simplicity
    # Fields 48-64: NameMale_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)  # Same name for simplicity
    # Field 65: FacialHairCustomization[0] (string offset)
    buf += struct.pack('<I', facial1_offset)
    # Field 66: FacialHairCustomization[1] (string offset)
    buf += struct.pack('<I', facial2_offset)
    # Field 67: HairCustomization (string offset)
    buf += struct.pack('<I', hair_offset)
    # Field 68: Required_expansion
    buf += struct.pack('<I', required_expansion)

    expected_size = 69 * 4  # 276 bytes for 69 fields
    # NOTE: The actual ChrRaces.dbc record size varies by build.
    # WotLK 3.3.5a uses 69 uint32 fields = 276 bytes.
    # If your extracted DBC shows a different record_size in its header,
    # pad or truncate accordingly.
    actual_record_size = dbc.record_size

    if len(buf) < actual_record_size:
        # Pad with zeros to match the expected record size
        buf += b'\x00' * (actual_record_size - len(buf))
    elif len(buf) > actual_record_size:
        # Truncate (should not happen with correct field count)
        buf = buf[:actual_record_size]

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    print(f"Registered race '{race_name}' with ID {race_id}")
    return race_id


# -------------------------------------------------------
# Example usage
# -------------------------------------------------------
if __name__ == '__main__':
    DBC_DIR = r'D:\modding\dbc'

    register_custom_race(
        dbc_dir=DBC_DIR,
        race_id=12,
        race_name="Naga",
        faction_id=1,          # Human faction template (Alliance)
        male_display_id=50,    # Placeholder: existing Naga model
        female_display_id=51,  # Placeholder: existing Naga model
        client_filestring="Human",  # Reuse Human models initially
        alliance_side=0,       # Alliance
        client_prefix="Na",
        base_language=7,       # Common
        flags=3,               # Playable + DK eligible
        required_expansion=2,  # WotLK
    )
```

**Critical note about `client_filestring`**: If you set this to `"Human"`, the client
will use Human body models and textures. To use truly custom models, you must create
new M2 files at `Character\<YourRaceName>\Male\<YourRaceName>Male.m2` (and Female)
and set `client_filestring` to match.

---

## 8. Step 2: Define Class Combinations in CharBaseInfo.dbc

CharBaseInfo.dbc uses byte-level packing rather than standard uint32 fields. Each
record is just 4 bytes: RaceID (1 byte), ClassID (1 byte), and 2 bytes of padding.

```python
import struct
import os
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import DBCInjector


def register_race_class_combo(dbc_dir, race_id, class_id):
    """
    Register a valid race/class combination in CharBaseInfo.dbc.

    Args:
        dbc_dir: Path to directory containing CharBaseInfo.dbc.
        race_id: Race ID (ChrRaces.dbc).
        class_id: Class ID (ChrClasses.dbc).
    """
    filepath = os.path.join(dbc_dir, 'CharBaseInfo.dbc')
    dbc = DBCInjector(filepath)

    # CharBaseInfo records are 4 bytes: raceID(1) + classID(1) + padding(2)
    # However, the DBC header reports field_count and record_size.
    # We must match the existing record_size exactly.
    record_size = dbc.record_size

    buf = bytearray(record_size)
    buf[0] = race_id & 0xFF
    buf[1] = class_id & 0xFF
    # Remaining bytes are zero padding

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    print(f"  Registered race {race_id} + class {class_id}")


def register_all_class_combos(dbc_dir, race_id, class_ids):
    """
    Register multiple class combinations for a race.

    Args:
        dbc_dir: Path to directory containing CharBaseInfo.dbc.
        race_id: Race ID.
        class_ids: List of class IDs to enable.
    """
    for class_id in class_ids:
        register_race_class_combo(dbc_dir, race_id, class_id)


# -------------------------------------------------------
# Example: Enable all standard classes for custom race 12
# -------------------------------------------------------
if __name__ == '__main__':
    DBC_DIR = r'D:\modding\dbc'
    RACE_ID = 12  # Custom "Naga" race

    # Allow Warrior, Hunter, Rogue, Priest, Mage, Warlock, Death Knight
    CLASS_IDS = [1, 3, 4, 5, 6, 8, 9]

    print(f"Registering class combos for race {RACE_ID}:")
    register_all_class_combos(DBC_DIR, RACE_ID, CLASS_IDS)
    print("Done.")
```

---

## 9. Step 3: Define Starting Outfits

Each race/class/gender combination needs a CharStartOutfit.dbc entry that defines
what gear, bags, and items the character starts with.

```python
import struct
import os
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import DBCInjector


def register_start_outfit(
    dbc_dir,
    race_id,
    class_id,
    sex_id,
    items,
    outfit_id=None,
):
    """
    Register a starting outfit in CharStartOutfit.dbc.

    Args:
        dbc_dir: Path to directory containing CharStartOutfit.dbc.
        race_id: Race ID.
        class_id: Class ID.
        sex_id: 0 = Male, 1 = Female.
        items: List of up to 24 dicts with keys:
               - 'item_id': Item template ID (int, -1 for empty)
               - 'display_id': ItemDisplayInfo ID (int, -1 for empty)
               - 'inv_type': Inventory type enum (int, -1 for empty)
        outfit_id: Record ID, or None for auto.

    Returns:
        int: Assigned outfit record ID.
    """
    filepath = os.path.join(dbc_dir, 'CharStartOutfit.dbc')
    dbc = DBCInjector(filepath)

    if outfit_id is None:
        outfit_id = dbc.get_max_id() + 1

    # Pad items list to exactly 24 entries
    padded_items = []
    for i in range(24):
        if i < len(items):
            padded_items.append(items[i])
        else:
            padded_items.append({
                'item_id': -1,
                'display_id': -1,
                'inv_type': -1,
            })

    # Build the record
    buf = bytearray()

    # Field 0: ID
    buf += struct.pack('<I', outfit_id)

    # Field 1: RaceID + ClassID + SexID + OutfitID (packed as 4 bytes)
    buf += struct.pack('<BBBB', race_id, class_id, sex_id, 0)

    # Fields 2-25: ItemID[24] (signed int32)
    for item in padded_items:
        buf += struct.pack('<i', item['item_id'])

    # Fields 26-49: DisplayItemID[24] (signed int32)
    for item in padded_items:
        buf += struct.pack('<i', item['display_id'])

    # Fields 50-73: InventoryType[24] (signed int32)
    for item in padded_items:
        buf += struct.pack('<i', item['inv_type'])

    # Verify record size matches existing records
    expected_size = dbc.record_size
    if len(buf) < expected_size:
        buf += b'\x00' * (expected_size - len(buf))
    elif len(buf) > expected_size:
        buf = buf[:expected_size]

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return outfit_id


# -------------------------------------------------------
# Example: Starting outfit for custom Race 12, Warrior, Male
# -------------------------------------------------------
if __name__ == '__main__':
    DBC_DIR = r'D:\modding\dbc'

    # Warrior starting gear (similar to Human Warrior)
    warrior_items = [
        # Slot 0: Head - empty
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        # Slot 1: Neck - empty
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        # Slot 2: Shoulders - empty
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        # Slot 3: Body (Shirt)
        {'item_id': 6096, 'display_id': 2311, 'inv_type': 4},
        # Slot 4: Chest - Recruit's Vest
        {'item_id': 25, 'display_id': 9987, 'inv_type': 5},
        # Slot 5: Waist - empty
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        # Slot 6: Legs - Recruit's Pants
        {'item_id': 26, 'display_id': 9985, 'inv_type': 7},
        # Slot 7: Feet - Recruit's Boots
        {'item_id': 29, 'display_id': 9984, 'inv_type': 8},
        # Slots 8-14: Wrists, Hands, Ring1, Ring2, Trinket1, Trinket2, Back
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        # Slot 15: MainHand - Worn Shortsword
        {'item_id': 25, 'display_id': 1542, 'inv_type': 21},
        # Slot 16: OffHand - Worn Wooden Shield
        {'item_id': 2362, 'display_id': 18730, 'inv_type': 14},
        # Slots 17-23: Ranged, Tabard, Bag1-4, Ammo - empty
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
        {'item_id': -1, 'display_id': -1, 'inv_type': -1},
    ]

    oid = register_start_outfit(
        dbc_dir=DBC_DIR,
        race_id=12,
        class_id=1,   # Warrior
        sex_id=0,      # Male
        items=warrior_items,
    )
    print(f"Created starting outfit ID: {oid}")

    # You need one of these for EVERY race/class/gender combination!
    # For race 12 with 7 classes and 2 genders = 14 records minimum.
```

### Scaling the Outfit Registration

For a race with 7 class options and 2 genders, you need 14 CharStartOutfit records.
A helper function can batch-create them:

```python
def register_all_starting_outfits(dbc_dir, race_id, class_outfits):
    """
    Register starting outfits for all class/gender combinations.

    Args:
        dbc_dir: Path to DBC directory.
        race_id: Custom race ID.
        class_outfits: Dict mapping class_id -> items list.
                       The same items are used for both genders.
    """
    count = 0
    for class_id, items in class_outfits.items():
        for sex_id in [0, 1]:  # Male, Female
            register_start_outfit(
                dbc_dir=dbc_dir,
                race_id=race_id,
                class_id=class_id,
                sex_id=sex_id,
                items=items,
            )
            count += 1
    print(f"Created {count} starting outfit records for race {race_id}")


# Define outfits per class (simplified -- real outfits vary by class)
CLASS_OUTFITS = {
    1: warrior_items,    # Warrior
    3: hunter_items,     # Hunter (define similarly)
    4: rogue_items,      # Rogue
    5: priest_items,     # Priest
    6: dk_items,         # Death Knight
    8: mage_items,       # Mage
    9: warlock_items,    # Warlock
}

register_all_starting_outfits(DBC_DIR, 12, CLASS_OUTFITS)
```

---

## 10. Step 4: Server-Side C++ Core Changes

The server core (AzerothCore/TrinityCore) has hardcoded race bitmasks and race
validation logic that must be modified to accept a new race ID.

### 10.1 Race Bitmask (SharedDefines.h)

The server uses a `RACEMASK_ALL_PLAYABLE` constant to validate character creation:

```cpp
// File: src/server/game/Entities/Player/SharedDefines.h
// (AzerothCore / TrinityCore)

// Original (supports races 1-11):
#define RACEMASK_ALL_PLAYABLE \
    ((1<<(RACE_HUMAN-1))    | (1<<(RACE_ORC-1))      | \
     (1<<(RACE_DWARF-1))    | (1<<(RACE_NIGHTELF-1))  | \
     (1<<(RACE_UNDEAD_PLAYER-1)) | (1<<(RACE_TAUREN-1))  | \
     (1<<(RACE_GNOME-1))    | (1<<(RACE_TROLL-1))     | \
     (1<<(RACE_BLOODELF-1)) | (1<<(RACE_DRAENEI-1)))

// Modified to include custom race 12:
#define RACE_CUSTOM_NAGA 12

#define RACEMASK_ALL_PLAYABLE \
    ((1<<(RACE_HUMAN-1))    | (1<<(RACE_ORC-1))      | \
     (1<<(RACE_DWARF-1))    | (1<<(RACE_NIGHTELF-1))  | \
     (1<<(RACE_UNDEAD_PLAYER-1)) | (1<<(RACE_TAUREN-1))  | \
     (1<<(RACE_GNOME-1))    | (1<<(RACE_TROLL-1))     | \
     (1<<(RACE_BLOODELF-1)) | (1<<(RACE_DRAENEI-1))  | \
     (1<<(RACE_CUSTOM_NAGA-1)))
```

### 10.2 Race Enum (SharedDefines.h)

Add the new race to the race enum:

```cpp
enum Races
{
    RACE_HUMAN          = 1,
    RACE_ORC            = 2,
    RACE_DWARF          = 3,
    RACE_NIGHTELF       = 4,
    RACE_UNDEAD_PLAYER  = 5,
    RACE_TAUREN         = 6,
    RACE_GNOME          = 7,
    RACE_TROLL          = 8,
    RACE_GOBLIN         = 9,
    RACE_BLOODELF       = 10,
    RACE_DRAENEI        = 11,
    RACE_CUSTOM_NAGA    = 12,    // <-- ADD THIS
};
```

### 10.3 Character Creation Validation (Player.cpp)

The `Player::Create()` function validates race/class combinations. You must ensure
your new race passes validation:

```cpp
// File: src/server/game/Entities/Player/Player.cpp

bool Player::Create(ObjectGuid::LowType guidlow, CharacterCreateInfo const* createInfo)
{
    // ... existing code ...

    // Ensure the new race is recognized
    // If using ChrRaces.dbc for validation (most cores do), this
    // should work automatically once the DBC is modified.

    // However, some hardcoded checks may need updating:
    switch (createInfo->Race)
    {
        case RACE_HUMAN:
        case RACE_ORC:
        // ... existing cases ...
        case RACE_DRAENEI:
        case RACE_CUSTOM_NAGA:    // <-- ADD THIS CASE
            break;
        default:
            LOG_ERROR("entities.player", "Invalid race %u", createInfo->Race);
            return false;
    }

    // ...
}
```

### 10.4 Starting Position (player_createinfo SQL)

The server needs to know where new characters of this race spawn:

```sql
-- Starting position for custom race 12
-- Using Borean Tundra as an example starting zone
INSERT INTO `playercreateinfo` (
    `race`, `class`, `map`, `zone`, `position_x`, `position_y`,
    `position_z`, `orientation`
) VALUES
    -- Warrior
    (12, 1, 571, 3537, 3298.77, 5572.58, 27.20, 5.34),
    -- Hunter
    (12, 3, 571, 3537, 3298.77, 5572.58, 27.20, 5.34),
    -- Rogue
    (12, 4, 571, 3537, 3298.77, 5572.58, 27.20, 5.34),
    -- Priest
    (12, 5, 571, 3537, 3298.77, 5572.58, 27.20, 5.34),
    -- Death Knight (different start zone)
    (12, 6, 609, 4298, 2355.84, -5664.77, 426.03, 3.65),
    -- Mage
    (12, 8, 571, 3537, 3298.77, 5572.58, 27.20, 5.34),
    -- Warlock
    (12, 9, 571, 3537, 3298.77, 5572.58, 27.20, 5.34);
```

### 10.5 Racial Abilities (playercreateinfo_spell SQL)

Define racial passive and active abilities:

```sql
-- ============================================================
-- Racial spells for custom race 12
-- ============================================================

-- Language: Common (Alliance) or Orcish (Horde)
INSERT INTO `playercreateinfo_spell_custom` (`racemask`, `classmask`, `Spell`, `Note`)
VALUES
    -- Language: Common (all classes of race 12)
    (2048, 0, 668, 'Language: Common'),

    -- Example racial abilities (create custom spell entries first)
    -- Passive: +10 Nature Resistance
    (2048, 0, 20596, 'Racial Passive: Nature Resistance'),
    -- Active: Sprint-like ability (cooldown racial)
    (2048, 0, 20589, 'Racial Active: Escape');

-- racemask for race 12 = 1 << (12-1) = 1 << 11 = 2048
-- classmask 0 = all classes
```

### 10.6 Rebuild the Server Core

After making C++ changes, rebuild the server:

```bash
# AzerothCore (Linux/macOS)
cd azerothcore/build
cmake .. -DCMAKE_INSTALL_PREFIX=/path/to/server
make -j$(nproc)
make install

# AzerothCore (Windows - Visual Studio)
# Open the .sln solution file and rebuild the worldserver project.
```

---

## 11. Step 5: Player Level Stats SQL

Every race/class combination needs base stat values (Strength, Agility, Stamina,
Intellect, Spirit) for all 80 levels in the `player_levelstats` table.

### player_levelstats Table Structure

| Column | Type | Description |
|--------|------|-------------|
| `race` | tinyint | Race ID |
| `class` | tinyint | Class ID |
| `level` | tinyint | Character level (1-80) |
| `str` | int | Base Strength at this level |
| `agi` | int | Base Agility at this level |
| `sta` | int | Base Stamina at this level |
| `inte` | int | Base Intellect at this level |
| `spi` | int | Base Spirit at this level |

### Generating Stats for All 80 Levels

The easiest approach is to clone an existing race's stats. Here is a Python script
that generates the SQL:

```python
"""
Generate player_levelstats SQL for a custom race.

Clones stat progression from an existing race (e.g., Human = race 1)
with optional stat modifiers to differentiate the custom race.
"""

import os
import sys


def generate_levelstats_sql(
    source_race_id,
    target_race_id,
    class_ids,
    output_path,
    stat_modifiers=None,
):
    """
    Generate player_levelstats SQL by cloning from a source race.

    Args:
        source_race_id: Existing race to clone stats from.
        target_race_id: Custom race ID to generate stats for.
        class_ids: List of class IDs enabled for this race.
        output_path: File path for the output SQL file.
        stat_modifiers: Optional dict with keys 'str', 'agi', 'sta',
                        'inte', 'spi' containing additive modifiers.
    """
    if stat_modifiers is None:
        stat_modifiers = {'str': 0, 'agi': 0, 'sta': 0, 'inte': 0, 'spi': 0}

    lines = [
        "-- ================================================================",
        f"-- player_levelstats for custom race {target_race_id}",
        f"-- Cloned from race {source_race_id} with stat modifiers:",
        f"--   STR {stat_modifiers['str']:+d}, "
        f"AGI {stat_modifiers['agi']:+d}, "
        f"STA {stat_modifiers['sta']:+d}, "
        f"INT {stat_modifiers['inte']:+d}, "
        f"SPI {stat_modifiers['spi']:+d}",
        "-- ================================================================",
        "",
        f"DELETE FROM `player_levelstats` WHERE `race` = {target_race_id};",
        "",
        "INSERT INTO `player_levelstats` "
        "(`race`, `class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`) "
        "VALUES",
    ]

    # For each class, generate 80 level entries
    # This generates the SELECT-based clone statement
    value_lines = []
    for class_id in class_ids:
        for level in range(1, 81):
            # These are placeholder values -- in practice, you would
            # query the actual source race stats from the database.
            # Here we show the structure; real deployment would use
            # INSERT ... SELECT from the source race.
            value_lines.append(
                f"({target_race_id}, {class_id}, {level}, "
                f"0, 0, 0, 0, 0)"  # Placeholder values
            )

    # Better approach: clone directly from existing data with SQL
    lines_alt = [
        "-- ================================================================",
        f"-- player_levelstats for custom race {target_race_id}",
        f"-- Cloned from race {source_race_id}",
        "-- ================================================================",
        "",
        f"DELETE FROM `player_levelstats` WHERE `race` = {target_race_id};",
        "",
    ]

    for class_id in class_ids:
        mod = stat_modifiers
        lines_alt.append(
            f"INSERT INTO `player_levelstats` "
            f"(`race`, `class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`)"
        )
        lines_alt.append(
            f"SELECT {target_race_id}, `class`, `level`, "
            f"`str` + ({mod['str']}), "
            f"`agi` + ({mod['agi']}), "
            f"`sta` + ({mod['sta']}), "
            f"`inte` + ({mod['inte']}), "
            f"`spi` + ({mod['spi']})"
        )
        lines_alt.append(
            f"FROM `player_levelstats` "
            f"WHERE `race` = {source_race_id} AND `class` = {class_id};"
        )
        lines_alt.append("")

    output = '\n'.join(lines_alt)

    with open(output_path, 'w') as f:
        f.write(output)

    total_rows = len(class_ids) * 80
    print(f"Generated {total_rows} stat rows for race {target_race_id}")
    print(f"SQL written to: {output_path}")


# -------------------------------------------------------
# Example usage
# -------------------------------------------------------
if __name__ == '__main__':
    generate_levelstats_sql(
        source_race_id=1,          # Clone from Human
        target_race_id=12,         # Custom Naga race
        class_ids=[1, 3, 4, 5, 6, 8, 9],  # Enabled classes
        output_path=r'D:\modding\sql\race12_levelstats.sql',
        stat_modifiers={
            'str': 1,   # +1 STR (slightly stronger)
            'agi': -1,  # -1 AGI (slightly less agile)
            'sta': 2,   # +2 STA (tougher)
            'inte': 0,  # Same INT
            'spi': -1,  # -1 SPI
        },
    )
```

### Total Row Count

For a race with 7 classes across 80 levels:
- 7 classes x 80 levels = **560 rows** in `player_levelstats`

This is why we use the clone-from-existing-race approach rather than manually
defining each value.

---

## 12. Step 6: The Helmet-Refitting Problem

This is the single biggest obstacle to adding a truly custom race with unique body
proportions. Understanding this problem is essential before deciding on your approach.

### How Equipment Rendering Works

In WoW 3.3.5a, when a character equips a helmet (or any visible armor piece), the
client:

1. Looks up the item's `ItemDisplayInfo.dbc` entry to find the model file path.
2. Loads the helmet `.m2` model file.
3. **Selects the correct geoset (mesh variant) based on the character's race and
   gender.** Each helmet M2 contains multiple mesh variants -- one for each
   race/gender combination -- because different races have different head shapes
   and sizes.

This means every helmet model in the game contains geometry data for:
- Human Male, Human Female
- Orc Male, Orc Female
- Dwarf Male, Dwarf Female
- Night Elf Male, Night Elf Female
- Undead Male, Undead Female
- Tauren Male, Tauren Female
- Gnome Male, Gnome Female
- Troll Male, Troll Female
- Blood Elf Male, Blood Elf Female
- Draenei Male, Draenei Female

**That is 20 geoset variants per helmet model.**

### The Scale of the Problem

WoW 3.3.5a contains approximately:

| Item Category | Approximate Count | Geosets Needed |
|---------------|-------------------|----------------|
| Helmets | ~800 unique models | 2 (M + F) per helmet |
| Shoulder pieces | ~600 unique models | 2 per item |
| Chest/Robes | ~500 unique models | 2 per item |
| Gloves | ~400 unique models | 2 per item |
| Boots | ~400 unique models | 2 per item |
| Belts | ~300 unique models | 2 per item |

**Total: ~3000 model files** need new geosets added for your custom race.

For each model, you must:
1. Open the M2 file.
2. Add a new geoset (mesh variant) that fits your custom race's body geometry.
3. Assign the correct geoset ID for your race.
4. Save the M2 file.

This is a task measured in **months of 3D artist work** for a fully unique race.

### Geoset ID Assignment

Geoset IDs in M2 files follow this pattern for helmets:

```
Geoset ID = (RaceID * 100) + (GenderID * 10) + VariantID

Example for a Helmet:
  Human Male:     0100 + 00 + 0 = 100
  Human Female:   0100 + 10 + 0 = 110
  Orc Male:       0200 + 00 + 0 = 200
  Orc Female:     0200 + 10 + 0 = 210
  ...
  Custom Race 12 Male:   1200 + 00 + 0 = 1200  <-- Must be added
  Custom Race 12 Female: 1200 + 10 + 0 = 1210  <-- Must be added
```

If the client cannot find the geoset for your race, the helmet will either:
- Not render at all (invisible), or
- Use a fallback geoset (often the Human variant, which may clip horribly).

### Practical Solutions

| Approach | Effort | Result |
|----------|--------|--------|
| **Clone existing race skeleton** | Low | Equipment works perfectly (same body = same geosets) |
| **Add geosets to every item** | Extreme | True custom body with perfect equipment fit |
| **Script to copy geosets** | High | Automated copying of nearest-race geosets to new IDs |
| **Accept visual glitches** | Zero | Equipment clips or is invisible on your race |

The **recommended approach** is to clone an existing race's skeleton and body
proportions, then modify only textures and facial features. This is covered in
section 13.

---

## 13. Alternative Approach: Reskinning an Existing Race

The practical way to add a "custom race" is to reskin an existing race. This
approach reuses the existing race's skeleton, animations, and equipment geosets
while providing a visually distinct appearance through modified textures.

### How Reskinning Works

1. Pick a base race whose body proportions match your vision (e.g., Night Elf for
   a tall, lean custom race; Dwarf for a stocky race).
2. Set your custom race's `ClientFilestring` in ChrRaces.dbc to the base race's
   filestring (e.g., `"NightElf"`).
3. The client will load the base race's M2 models and animations.
4. Optionally modify skin textures (BLP files) to give the race a unique look.

### Reskin Example: Creating a "High Elf" Race Based on Blood Elf

Since Blood Elves and High Elves share the same body type in WoW lore, this is a
natural choice:

```python
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import DBCInjector, _pack_locstring
import struct
import os

DBC_DIR = r'D:\modding\dbc'


# Step 1: Register the race using Blood Elf models
# (reusing the register_custom_race function from Step 1)
def register_reskinned_race():
    """Register a High Elf race that reuses Blood Elf models."""

    filepath = os.path.join(DBC_DIR, 'ChrRaces.dbc')
    dbc = DBCInjector(filepath)

    race_id = 12
    name_offset = dbc.add_string("High Elf")
    prefix_offset = dbc.add_string("He")

    # KEY: Use Blood Elf's ClientFilestring so all Blood Elf models load
    filestring_offset = dbc.add_string("BloodElf")

    facial1_offset = dbc.add_string("Beards")
    facial2_offset = dbc.add_string("Earrings")
    hair_offset = dbc.add_string("Normal")

    # Blood Elf display IDs (male=15476, female=15475 in retail)
    # These reference CreatureDisplayInfo entries that point to BloodElf M2s
    male_display = 15476
    female_display = 15475

    buf = bytearray()
    buf += struct.pack('<I', race_id)       # ID
    buf += struct.pack('<I', 3)              # Flags: playable + DK
    buf += struct.pack('<I', 1629)           # FactionID: Draenei (Alliance)
    buf += struct.pack('<I', 4797)           # ExplorationSoundID
    buf += struct.pack('<I', male_display)   # MaleDisplayId
    buf += struct.pack('<I', female_display) # FemaleDisplayId
    buf += struct.pack('<I', prefix_offset)  # ClientPrefix
    buf += struct.pack('<I', 7)              # BaseLanguage: Common
    buf += struct.pack('<I', 7)              # CreatureType: Humanoid
    buf += struct.pack('<I', 15007)          # ResSicknessSpellID
    buf += struct.pack('<I', 0)              # SplashSoundID
    buf += struct.pack('<I', filestring_offset)  # ClientFilestring: "BloodElf"
    buf += struct.pack('<I', 0)              # CinematicSequenceID
    buf += struct.pack('<I', 0)              # Alliance = 0 (Alliance side)
    buf += _pack_locstring(name_offset)      # Name_lang
    buf += _pack_locstring(name_offset)      # NameFemale_lang
    buf += _pack_locstring(name_offset)      # NameMale_lang
    buf += struct.pack('<I', facial1_offset)  # FacialHairCustomization[0]
    buf += struct.pack('<I', facial2_offset)  # FacialHairCustomization[1]
    buf += struct.pack('<I', hair_offset)     # HairCustomization
    buf += struct.pack('<I', 2)               # Required_expansion: WotLK

    # Pad to match record size
    actual_record_size = dbc.record_size
    if len(buf) < actual_record_size:
        buf += b'\x00' * (actual_record_size - len(buf))

    dbc.records.append(bytes(buf))
    dbc.write(filepath)
    print(f"Registered High Elf race with ID {race_id}")
    return race_id


register_reskinned_race()
```

### Optional: Custom Skin Textures

To give the reskinned race a unique appearance, create modified texture files. The
Blood Elf skin textures are located at:

```
Character\BloodElf\Male\BloodElfMaleSkin00_00.blp
Character\BloodElf\Male\BloodElfMaleSkin00_01.blp
Character\BloodElf\Male\BloodElfMaleSkin00_02.blp
Character\BloodElf\Female\BloodElfFemaleSkin00_00.blp
...
```

You can modify these BLP textures (e.g., change skin tone, add tattoos, alter eye
color) and place them in your patch MPQ. Since the `ClientFilestring` is `"BloodElf"`,
the client will load textures from `Character\BloodElf\`, and your patch MPQ's files
will override the base ones.

**Texture modification workflow:**

1. Extract the base BLP textures from the client data.
2. Convert BLP to PNG using BLP Laboratory or BLPConverter.
3. Edit the PNG in Photoshop, GIMP, or similar.
4. Convert back to BLP (DXT1 or DXT5 compression).
5. Place in your patch MPQ at the same internal path.

### Advantages of Reskinning

| Advantage | Explanation |
|-----------|-------------|
| All equipment works | Same skeleton = same geosets = no refitting |
| All animations work | Reuses existing animation data |
| Minimal file changes | Only DBC records and optional texture overrides |
| No C++ model code changes | Model loading code unchanged |
| Fast iteration | Can be done in hours instead of months |

### Limitations of Reskinning

| Limitation | Explanation |
|------------|-------------|
| Same body proportions | Cannot change height, limb length, or overall shape |
| Same skeleton | Custom race moves identically to the base race |
| Same facial feature options | Hair styles, facial hair are inherited from base |
| Shared display IDs | Changes to base race textures affect custom race too |

---

## 14. MPQ File Placement

### DBC Files

```
patch-4.MPQ
  |
  +-- DBFilesClient\
        +-- ChrRaces.dbc
        +-- CharBaseInfo.dbc
        +-- CharStartOutfit.dbc
```

### Model Files (Custom Race Only -- Not Needed for Reskins)

```
patch-4.MPQ
  |
  +-- Character\
        +-- MyRace\
              +-- Male\
              |     +-- MyRaceMale.m2
              |     +-- MyRaceMale.skin
              |     +-- MyRaceMaleSkin00_00.blp
              |     +-- MyRaceMaleSkin00_01.blp
              |     +-- MyRaceMaleHair00_00.blp
              |     +-- ...
              +-- Female\
                    +-- MyRaceFemale.m2
                    +-- MyRaceFemale.skin
                    +-- MyRaceFemaleSkin00_00.blp
                    +-- ...
```

### Texture Overrides (Reskin Approach)

```
patch-4.MPQ
  |
  +-- Character\
        +-- BloodElf\           (matches base race's ClientFilestring)
              +-- Male\
              |     +-- BloodElfMaleSkin00_00.blp   (modified textures)
              |     +-- BloodElfMaleSkin00_01.blp
              +-- Female\
                    +-- BloodElfFemaleSkin00_00.blp
                    +-- BloodElfFemaleSkin00_01.blp
```

### Using pywowlib's MPQPacker

```python
from world_builder.mpq_packer import MPQPacker
import os

packer = MPQPacker(output_dir=r'D:\modding\output', patch_name='patch-4.MPQ')

# Add modified DBC files
dbc_dir = r'D:\modding\dbc'
packer.add_dbc(os.path.join(dbc_dir, 'ChrRaces.dbc'))
packer.add_dbc(os.path.join(dbc_dir, 'CharBaseInfo.dbc'))
packer.add_dbc(os.path.join(dbc_dir, 'CharStartOutfit.dbc'))

# Add texture overrides for reskin (if applicable)
texture_dir = r'D:\modding\textures'
for root, dirs, files in os.walk(texture_dir):
    for f in files:
        local_path = os.path.join(root, f)
        # Convert local path to MPQ internal path
        rel_path = os.path.relpath(local_path, texture_dir)
        mpq_path = os.path.join('Character', rel_path)
        packer.add_file(local_path, mpq_path)

packer.build()
```

---

## 15. Complete Code Examples

### Full Pipeline Script

This script performs all DBC modifications for a reskinned custom race:

```python
"""
Complete pipeline: Add a custom "High Elf" race (reskinned from Blood Elf).

This script modifies:
  - ChrRaces.dbc (race definition)
  - CharBaseInfo.dbc (class combinations)
  - CharStartOutfit.dbc (starting gear)

And generates SQL for:
  - player_createinfo (starting position)
  - player_levelstats (stat progression)
  - playercreateinfo_spell_custom (racial abilities)
"""

import struct
import os
import sys
sys.path.insert(0, r'D:\Test\wow-pywowlib')

from world_builder.dbc_injector import DBCInjector, _pack_locstring


# ===============================================================
# Configuration
# ===============================================================

DBC_DIR = r'D:\modding\dbc'
SQL_OUTPUT = r'D:\modding\sql\high_elf_race.sql'

RACE_ID = 12
RACE_NAME = "High Elf"
BASE_RACE = "BloodElf"       # ClientFilestring (reuse Blood Elf models)
FACTION_SIDE = 0             # 0 = Alliance, 1 = Horde
FACTION_TEMPLATE = 1629      # Draenei faction (Alliance-friendly)
MALE_DISPLAY = 15476         # Blood Elf Male display ID
FEMALE_DISPLAY = 15475       # Blood Elf Female display ID
BASE_LANGUAGE = 7            # Common (Alliance)

# Classes available to this race
ENABLED_CLASSES = [
    1,   # Warrior
    2,   # Paladin
    3,   # Hunter
    4,   # Rogue
    5,   # Priest
    6,   # Death Knight
    8,   # Mage
    9,   # Warlock
]

# Source race for stat cloning
STAT_SOURCE_RACE = 10  # Blood Elf (similar physical build)

# Stat modifiers relative to source race
STAT_MODS = {
    'str': 0,
    'agi': 1,     # Slightly more agile (ranger heritage)
    'sta': 0,
    'inte': 1,    # Slightly more intelligent (magical heritage)
    'spi': -1,    # Slightly less spiritual
}


# ===============================================================
# Step 1: Register in ChrRaces.dbc
# ===============================================================

def step1_register_race():
    print("Step 1: Registering race in ChrRaces.dbc...")

    filepath = os.path.join(DBC_DIR, 'ChrRaces.dbc')
    dbc = DBCInjector(filepath)

    name_off = dbc.add_string(RACE_NAME)
    prefix_off = dbc.add_string("He")
    filestring_off = dbc.add_string(BASE_RACE)
    facial1_off = dbc.add_string("Beards")
    facial2_off = dbc.add_string("Earrings")
    hair_off = dbc.add_string("Normal")

    buf = bytearray()
    buf += struct.pack('<I', RACE_ID)
    buf += struct.pack('<I', 3)               # Flags: playable + DK
    buf += struct.pack('<I', FACTION_TEMPLATE)
    buf += struct.pack('<I', 4797)            # ExplorationSoundID
    buf += struct.pack('<I', MALE_DISPLAY)
    buf += struct.pack('<I', FEMALE_DISPLAY)
    buf += struct.pack('<I', prefix_off)
    buf += struct.pack('<I', BASE_LANGUAGE)
    buf += struct.pack('<I', 7)               # CreatureType: Humanoid
    buf += struct.pack('<I', 15007)           # ResSicknessSpellID
    buf += struct.pack('<I', 0)               # SplashSoundID
    buf += struct.pack('<I', filestring_off)
    buf += struct.pack('<I', 0)               # CinematicSequenceID
    buf += struct.pack('<I', FACTION_SIDE)
    buf += _pack_locstring(name_off)          # Name_lang
    buf += _pack_locstring(name_off)          # NameFemale_lang
    buf += _pack_locstring(name_off)          # NameMale_lang
    buf += struct.pack('<I', facial1_off)
    buf += struct.pack('<I', facial2_off)
    buf += struct.pack('<I', hair_off)
    buf += struct.pack('<I', 2)               # Required_expansion: WotLK

    # Pad to match record size
    if len(buf) < dbc.record_size:
        buf += b'\x00' * (dbc.record_size - len(buf))

    dbc.records.append(bytes(buf[:dbc.record_size]))
    dbc.write(filepath)
    print(f"  Race '{RACE_NAME}' registered with ID {RACE_ID}")


# ===============================================================
# Step 2: Register class combinations in CharBaseInfo.dbc
# ===============================================================

def step2_register_classes():
    print("Step 2: Registering class combos in CharBaseInfo.dbc...")

    filepath = os.path.join(DBC_DIR, 'CharBaseInfo.dbc')
    dbc = DBCInjector(filepath)

    for class_id in ENABLED_CLASSES:
        rec = bytearray(dbc.record_size)
        rec[0] = RACE_ID & 0xFF
        rec[1] = class_id & 0xFF
        dbc.records.append(bytes(rec))
        print(f"  Enabled: Race {RACE_ID} + Class {class_id}")

    dbc.write(filepath)


# ===============================================================
# Step 3: Register starting outfits in CharStartOutfit.dbc
# ===============================================================

def step3_register_outfits():
    print("Step 3: Registering starting outfits...")

    filepath = os.path.join(DBC_DIR, 'CharStartOutfit.dbc')
    dbc = DBCInjector(filepath)

    # Generic starter item sets by class archetype
    MELEE_ITEMS = [
        -1, -1, -1,           # Head, Neck, Shoulders
        6096, 25, -1, 26, 29,  # Shirt, Chest, Waist, Legs, Feet
        -1, -1, -1, -1, -1, -1, -1,  # Wrists through Back
        25, 2362,              # MainHand, OffHand (sword + shield)
        -1, -1, -1, -1, -1, -1, -1,  # Ranged through Ammo
    ]

    CASTER_ITEMS = [
        -1, -1, -1,
        6096, 6076, -1, 1396, 55,
        -1, -1, -1, -1, -1, -1, -1,
        472, -1,              # Staff, no offhand
        -1, -1, -1, -1, -1, -1, -1,
    ]

    DK_ITEMS = [
        -1, -1, -1,
        -1, 34652, -1, 34655, 34656,
        -1, -1, -1, -1, -1, -1, -1,
        38707, -1,
        -1, -1, -1, -1, -1, -1, -1,
    ]

    CLASS_ITEMS = {
        1: MELEE_ITEMS,   # Warrior
        2: MELEE_ITEMS,   # Paladin
        3: MELEE_ITEMS,   # Hunter
        4: MELEE_ITEMS,   # Rogue
        5: CASTER_ITEMS,  # Priest
        6: DK_ITEMS,      # Death Knight
        8: CASTER_ITEMS,  # Mage
        9: CASTER_ITEMS,  # Warlock
    }

    outfit_id = dbc.get_max_id() + 1

    for class_id in ENABLED_CLASSES:
        items = CLASS_ITEMS.get(class_id, MELEE_ITEMS)

        for sex_id in [0, 1]:  # Male, Female
            buf = bytearray()
            buf += struct.pack('<I', outfit_id)
            buf += struct.pack('<BBBB', RACE_ID, class_id, sex_id, 0)

            # ItemID[24]
            for i in range(24):
                item_id = items[i] if i < len(items) else -1
                buf += struct.pack('<i', item_id)

            # DisplayItemID[24] (set to 0 for auto-lookup)
            for i in range(24):
                buf += struct.pack('<i', 0)

            # InventoryType[24] (set to 0 for auto-lookup)
            for i in range(24):
                buf += struct.pack('<i', 0)

            # Pad to record size
            if len(buf) < dbc.record_size:
                buf += b'\x00' * (dbc.record_size - len(buf))

            dbc.records.append(bytes(buf[:dbc.record_size]))
            outfit_id += 1

    dbc.write(filepath)
    total = len(ENABLED_CLASSES) * 2
    print(f"  Created {total} starting outfit records")


# ===============================================================
# Step 4: Generate server-side SQL
# ===============================================================

def step4_generate_sql():
    print("Step 4: Generating server-side SQL...")

    lines = [
        "-- ================================================================",
        f"-- Server SQL for custom race: {RACE_NAME} (ID {RACE_ID})",
        "-- Target: AzerothCore acore_world database",
        "-- ================================================================",
        "",
        "-- ----- player_createinfo (starting positions) -----",
        f"DELETE FROM `playercreateinfo` WHERE `race` = {RACE_ID};",
        "",
    ]

    # Starting position for each class
    # Using Eversong Woods (Blood Elf starting area) as template
    start_map = 530          # Outland (Eversong is map 530)
    start_zone = 3431        # Eversong Woods
    start_x = 10349.6
    start_y = -6357.29
    start_z = 33.4026
    start_o = 5.31605

    for class_id in ENABLED_CLASSES:
        if class_id == 6:  # Death Knight has special start
            lines.append(
                f"INSERT INTO `playercreateinfo` VALUES "
                f"({RACE_ID}, {class_id}, 609, 4298, "
                f"2355.84, -5664.77, 426.03, 3.65);"
            )
        else:
            lines.append(
                f"INSERT INTO `playercreateinfo` VALUES "
                f"({RACE_ID}, {class_id}, {start_map}, {start_zone}, "
                f"{start_x}, {start_y}, {start_z}, {start_o});"
            )

    lines.extend([
        "",
        "-- ----- player_levelstats (base stats per level) -----",
        f"DELETE FROM `player_levelstats` WHERE `race` = {RACE_ID};",
        "",
    ])

    for class_id in ENABLED_CLASSES:
        m = STAT_MODS
        lines.append(
            f"INSERT INTO `player_levelstats` "
            f"(`race`, `class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`)"
        )
        lines.append(
            f"SELECT {RACE_ID}, `class`, `level`, "
            f"`str` + ({m['str']}), "
            f"`agi` + ({m['agi']}), "
            f"`sta` + ({m['sta']}), "
            f"`inte` + ({m['inte']}), "
            f"`spi` + ({m['spi']})"
        )
        lines.append(
            f"FROM `player_levelstats` "
            f"WHERE `race` = {STAT_SOURCE_RACE} AND `class` = {class_id};"
        )
        lines.append("")

    # Racial spells
    racemask = 1 << (RACE_ID - 1)  # Bitmask for this race

    lines.extend([
        "-- ----- Racial abilities -----",
        f"DELETE FROM `playercreateinfo_spell_custom` "
        f"WHERE `racemask` = {racemask};",
        "",
        f"INSERT INTO `playercreateinfo_spell_custom` "
        f"(`racemask`, `classmask`, `Spell`, `Note`) VALUES",
        f"({racemask}, 0, 668, 'Language: Common'),",
        f"({racemask}, 0, 28877, 'Racial Passive: Arcane Affinity'),",
        f"({racemask}, 0, 822, 'Racial Passive: Magic Resistance');",
        "",
    ])

    # Action bar setup
    lines.extend([
        "-- ----- Action bar layout -----",
        f"DELETE FROM `playercreateinfo_action` WHERE `race` = {RACE_ID};",
        "",
        "-- Clone from Blood Elf (race 10) action bar layout",
    ])

    for class_id in ENABLED_CLASSES:
        lines.append(
            f"INSERT INTO `playercreateinfo_action` "
            f"(`race`, `class`, `button`, `action`, `type`)"
        )
        lines.append(
            f"SELECT {RACE_ID}, `class`, `button`, `action`, `type`"
        )
        lines.append(
            f"FROM `playercreateinfo_action` "
            f"WHERE `race` = {STAT_SOURCE_RACE} AND `class` = {class_id};"
        )
        lines.append("")

    sql_content = '\n'.join(lines)

    os.makedirs(os.path.dirname(SQL_OUTPUT), exist_ok=True)
    with open(SQL_OUTPUT, 'w') as f:
        f.write(sql_content)

    print(f"  SQL written to: {SQL_OUTPUT}")


# ===============================================================
# Run the complete pipeline
# ===============================================================

if __name__ == '__main__':
    print("=" * 60)
    print(f"Adding custom race: {RACE_NAME}")
    print("=" * 60)
    print()

    step1_register_race()
    print()
    step2_register_classes()
    print()
    step3_register_outfits()
    print()
    step4_generate_sql()
    print()

    print("=" * 60)
    print("DBC modifications complete.")
    print(f"DBC files modified in: {DBC_DIR}")
    print(f"SQL generated at: {SQL_OUTPUT}")
    print()
    print("Remaining manual steps:")
    print("  1. Modify server core C++ (SharedDefines.h) to add race bitmask")
    print("  2. Rebuild and restart the server")
    print("  3. Execute the SQL file against the world database")
    print("  4. Pack modified DBCs into a client patch MPQ")
    print("  5. Optionally create custom skin textures")
    print("=" * 60)
```

---

## 16. Common Pitfalls and Troubleshooting

### "Unable to create character" / Character creation fails silently

**Cause 1:** Server core does not recognize the new race ID. The `RACEMASK_ALL_PLAYABLE`
bitmask has not been updated.

**Fix:** Modify `SharedDefines.h` to include `(1 << (RACE_CUSTOM - 1))` in
`RACEMASK_ALL_PLAYABLE` and rebuild the server.

**Cause 2:** No `playercreateinfo` row exists for this race/class combination.

**Fix:** Run the SQL to insert starting position data for every enabled class.

**Cause 3:** No `CharBaseInfo.dbc` entry exists for the attempted race/class combo.

**Fix:** Verify that `register_race_class_combo()` was called for every desired
class.

### Character appears as a cube or invisible

**Cause:** The `MaleDisplayId` or `FemaleDisplayId` in ChrRaces.dbc does not point
to a valid `CreatureDisplayInfo.dbc` entry, or the display info references a model
file that does not exist.

**Fix:** Use a known-good display ID from an existing race. For the reskin approach,
use the base race's existing display IDs.

### Equipment is invisible or clips badly

**Cause:** The M2 model files do not contain geosets for your custom race ID.

**Fix:** Use the reskin approach (section 13) to inherit the base race's geosets.
If you must use a unique model, you need to add geosets to every equipment M2 file
(section 12).

### Character has no stats / zero health at level 1

**Cause:** Missing `player_levelstats` rows for this race/class combination.

**Fix:** Run the stat generation SQL (section 11). Verify with:
```sql
SELECT COUNT(*) FROM player_levelstats WHERE race = 12;
-- Should return: (number_of_classes * 80)
```

### Race appears but has no name in character creation

**Cause:** The `Name_lang` locstring in ChrRaces.dbc has offset `0` (empty string).

**Fix:** Verify that `dbc.add_string(race_name)` returns a non-zero offset. Check
that the string block was correctly written by opening the DBC in a hex editor and
verifying the name appears in the string block at the end of the file.

### Client crashes when entering character creation

**Cause 1:** ChrRaces.dbc record size mismatch. Your record is a different size than
the DBC's declared `record_size` in the header.

**Fix:** Always pad or truncate your record to match `dbc.record_size` exactly.

**Cause 2:** Invalid string offset in a locstring field. The offset points past the
end of the string block.

**Fix:** Use `dbc.add_string()` to add strings -- it handles offset calculation
correctly. Never manually compute string offsets.

### Death Knight option not available for custom race

**Cause:** The `Flags` field in ChrRaces.dbc does not include bit `0x2`.

**Fix:** Set `Flags = 3` (0x1 for playable + 0x2 for DK eligible).

### Race does not appear on the correct faction tab

**Cause:** The `Alliance` field is wrong. `0` = Alliance tab, `1` = Horde tab.

**Fix:** Set the `Alliance` field to match your intended faction. Also verify
that the `FactionID` (FactionTemplate) is compatible -- an Alliance-side race with
a Horde faction template will confuse the game logic.

### Character starts in a void / falls through the world

**Cause:** The starting position coordinates in `playercreateinfo` are invalid or
point to a non-existent map.

**Fix:** Use known-good coordinates from an existing race's starting area. Test
the coordinates in-game using `.gps` to verify they are on solid ground.

---

## 17. Cross-References

| Topic | Guide | Relevance |
|-------|-------|-----------|
| DBC injector core API | `world_builder/dbc_injector.py` | Low-level `DBCInjector` class for all DBC manipulations. |
| SQL generation | `world_builder/sql_generator.py` | Bulk SQL generation for creature_template and other tables. |
| MPQ packing | `world_builder/mpq_packer.py` | Package modified DBC and texture files into client patches. |
| Custom UI for race selection | `06_system_ui/custom_ui_frame.md` | AddOn development for modifying the character creation screen. |
| Flight paths for starting zones | `06_system_ui/modify_flight_paths.md` | Add flight connections to your custom race's starting area. |
| Zone creation for starting area | `01_world_building_environment/` | Create the physical terrain and map for a new starting zone. |
| NPC creation for starting quests | `04_creatures_encounters/` | Spawn quest givers and trainers in the starting area. |
| Starting quest chains | `05_narrative_quests/` | Create the introductory quest line for the new race. |
