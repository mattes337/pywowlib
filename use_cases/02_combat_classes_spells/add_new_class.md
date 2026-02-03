# Add New Class

**Complexity**: Extreme (Near-Impossible on 3.3.5a) |
**DBC Files**: ChrClasses.dbc, CharBaseInfo.dbc, CharStartOutfit.dbc, Spell.dbc, Talent.dbc, TalentTab.dbc, SkillLineAbility.dbc |
**SQL Tables**: playercreateinfo, player_levelstats, player_classlevelstats, playercreateinfo_spell_custom |
**pywowlib Modules**: `world_builder.dbc_injector.DBCInjector`

---

## Overview

Adding a truly new class to WoW 3.3.5a is one of the most ambitious and technically demanding modifications possible. This guide is structured as an honest assessment of what is achievable and what is not, followed by a practical workaround that achieves similar results.

**The hard truth**: A genuinely new class (ClassID 12+) is effectively impossible on 3.3.5a without recompiling the game client. The WoW client has hardcoded class limits, hardcoded UI layouts, hardcoded animation mappings, and hardcoded power bar configurations that cannot be changed through DBC edits alone.

**The practical alternative**: Replace an existing class by overwriting its DBC data, talent trees, spell kit, and UI elements. This approach gives you a "new" class from the player's perspective while staying within the binary constraints of the client.

This guide covers both approaches in detail: first the full analysis of what a true new class would require (and where it breaks), then the complete step-by-step process for replacing an existing class.

---

## Prerequisites

- Deep understanding of all DBC files listed above
- A dedicated test server (you will break things repeatedly)
- All spells for the new class already created in Spell.dbc (see [Add New Spell](./add_new_spell.md))
- Talent tree spells created (see [Modify Talent Tree](./modify_talent_tree.md))
- Python 3.6+ with pywowlib

---

## Part 1: Why a True New Class is Near-Impossible

### 1.1 - The Hardcoded Class Limit

The WoW 3.3.5a client binary (Wow.exe) contains hardcoded references to exactly 10 playable classes (IDs 1-11, with ID 10 unused/reserved). These are not read from DBC files but compiled into the executable:

- The character creation screen has fixed UI slots for each class
- The class selection buttons are positioned by hardcoded coordinates
- The class icon grid expects exactly the known set of classes
- The `MAX_CLASSES` constant in the client is compiled, not configurable

### 1.2 - ChrClasses.dbc Field Layout (WotLK 3.3.5a)

For reference, here is the WotLK layout (builds `3.0.1.8681` through `3.3.5.12340`):

```
Index   Field                    Type       Count  Notes
------  -----------------------  ---------  -----  ---------------------------
  0     ID                       uint32     1      Class ID (primary key)
  1     DamageBonusStat          uint32     1      Primary damage stat index
  2     DisplayPower             uint32     1      0=mana, 1=rage, 3=energy, 6=runic
  3     PetNameToken             string     1      Pet naming token
  4-20  Name_lang                locstring  17     Class name
 21-37  Name_female_lang         locstring  17     Female class name
 38-54  Name_male_lang           locstring  17     Male class name
 55     Filename                 string     1      Class file prefix (e.g. "WARRIOR")
 56     SpellClassSet            uint32     1      Spell family (4=warrior, 3=mage...)
 57     Flags                    uint32     1      Class flags
 58     CinematicSequenceID      uint32     1      Class intro cinematic
 59     Required_expansion       uint32     1      0=classic, 1=TBC, 2=WotLK

Total: 60 fields = 240 bytes per record (varies with locstring/string lengths)
```

### 1.3 - What Would Need to Change for a True New Class

Even if you could add a ChrClasses.dbc entry, you would also need to modify:

| System                    | File/Table              | What Needs Changing                                    |
|---------------------------|-------------------------|--------------------------------------------------------|
| Class definition          | ChrClasses.dbc          | New record with all fields                             |
| Race-class combinations   | CharBaseInfo.dbc        | New race+class pair entries (2 bytes each)             |
| Starting equipment        | CharStartOutfit.dbc     | 24 item slots per race/class/sex combo                 |
| Starting spells           | SkillLineAbility.dbc    | Class skill line + all initial abilities               |
| Talent trees              | TalentTab.dbc           | 3 new tabs with backgrounds                           |
| Talent entries            | Talent.dbc              | 50-70 talent entries referencing unique spells          |
| All class spells          | Spell.dbc               | 100-200+ spells (all ranks, passives, procs)           |
| Base stats                | player_levelstats       | Stats for all 80 levels x every race combo             |
| Class-level stats         | player_classlevelstats  | HP/mana per level for 80 levels                        |
| Starting position         | playercreateinfo        | Spawn location for every race combo                    |
| Starting reputation       | playercreateinfo_reputation | Faction standings                                 |
| Starting action bars      | playercreateinfo_action | Default action bar layout                              |
| Starting skills           | playercreateinfo_skills | Initial skill proficiencies                            |
| UI class color            | Client binary           | HARDCODED - cannot change via DBC                      |
| UI class icon             | Client binary           | HARDCODED position mapping                             |
| Power bar type            | Client binary           | HARDCODED mapping of ClassID to power bar              |
| Character creation screen | Client binary           | HARDCODED button layout                                |
| Animations                | Client binary           | HARDCODED animation set selection                      |
| GlueXML/FrameXML          | Interface files          | Class button positioning, color tables                 |
| Server core               | C++ source              | Class enum, power type mapping, stat formulas          |

### 1.4 - The Blockers

These systems **cannot** be modified through DBC edits or SQL and require binary/source patching:

1. **Client class color**: The color used for class names in chat, nameplates, and UI frames is hardcoded in the client binary. A new class would show as white/default.

2. **Power bar**: The mapping of ClassID to power bar type (mana/rage/energy/runic power) is partially in ChrClasses.dbc (DisplayPower field) but the client also has hardcoded fallback logic.

3. **Character creation UI**: The class buttons on the character creation screen are positioned by hardcoded coordinates in GlueXML. Adding a new button requires editing the client's Interface files AND potentially the binary.

4. **Server core**: AzerothCore/TrinityCore has a `MAX_CLASSES` constant, class-specific spell handling, talent validation, and stat calculation formulas that are all hardcoded in C++. Adding a true new class requires recompiling the server.

5. **Animations**: Combat animations are selected based on class+weapon combination through hardcoded lookup tables.

---

## Part 2: The Practical Alternative - Replace an Existing Class

The most effective approach is to completely overhaul an existing class. You change its name, spells, talents, and mechanics while keeping the same ClassID. From the player's perspective, it IS a new class. From the engine's perspective, nothing changed structurally.

### 2.1 - Choosing Which Class to Replace

The best candidates for replacement are classes that you do not plan to use on your server:

| Class       | ID | Pros for Replacement                          | Cons                              |
|-------------|----|-----------------------------------------------|-----------------------------------|
| Death Knight| 6  | Unique starting experience, runic power bar   | Complex starting zone, level 55+  |
| Shaman      | 7  | Three distinct specs, totem system            | Many race combos available         |
| Warlock     | 9  | Pet system, soul shard mechanic               | Popular class                     |
| Druid       | 11 | Shapeshift forms, 4 roles                     | Night Elf/Tauren only (few combos)|

**Recommendation**: Death Knight (ClassID 6) is often the best choice because:
- It already has a unique resource (runic power) that can be themed
- The starting experience can be completely overwritten
- It requires WotLK expansion (no conflict with classic/TBC content)
- The 0x020 class mask bit is clean and isolated

### 2.2 - Step-by-Step: Rename the Class

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"
_LOC_SLOTS = 17

TARGET_CLASS_ID = 6  # Death Knight -> our custom class


def pack_locstring(string_offset):
    values = [0] * _LOC_SLOTS
    values[0] = string_offset
    values[16] = 0xFFFFFFFF
    return struct.pack('<{}I'.format(_LOC_SLOTS), *values)


def rename_class(dbc_dir, class_id, new_name, new_filename=None):
    """
    Rename an existing class in ChrClasses.dbc.

    Args:
        dbc_dir: Path to DBFilesClient.
        class_id: The class ID to rename.
        new_name: New display name.
        new_filename: New file prefix (optional, e.g. "TEMPLAR").
                      If None, keeps the original.
    """
    filepath = os.path.join(dbc_dir, 'ChrClasses.dbc')
    dbc = DBCInjector(filepath)

    # Find the class record
    target_idx = -1
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == class_id:
            target_idx = i
            break

    if target_idx < 0:
        raise ValueError("Class ID {} not found".format(class_id))

    rec = bytearray(dbc.records[target_idx])
    record_size = len(rec)

    # ChrClasses.dbc WotLK layout (3.0.1.8681 - 3.3.5.12340):
    # Field 0: ID (uint32)
    # Field 1: DamageBonusStat (uint32)
    # Field 2: DisplayPower (uint32)
    # Field 3: PetNameToken (string offset)
    # Fields 4-20: Name_lang (locstring, 17 uint32)
    # Fields 21-37: Name_female_lang (locstring, 17 uint32)
    # Fields 38-54: Name_male_lang (locstring, 17 uint32)
    # Field 55: Filename (string offset)
    # Field 56: SpellClassSet (uint32)
    # Field 57: Flags (uint32)
    # Field 58: CinematicSequenceID (uint32)
    # Field 59: Required_expansion (uint32)

    new_name_offset = dbc.add_string(new_name)

    # Update Name_lang (field 4, enUS = slot 0)
    struct.pack_into('<I', rec, 4 * 4, new_name_offset)

    # Update Name_female_lang (field 21, enUS = slot 0)
    struct.pack_into('<I', rec, 21 * 4, new_name_offset)

    # Update Name_male_lang (field 38, enUS = slot 0)
    struct.pack_into('<I', rec, 38 * 4, new_name_offset)

    # Optionally update Filename
    if new_filename:
        filename_offset = dbc.add_string(new_filename)
        struct.pack_into('<I', rec, 55 * 4, filename_offset)

    dbc.records[target_idx] = bytes(rec)
    dbc.write(filepath)

    print("Renamed class {} to '{}'".format(class_id, new_name))


# Example: Rename Death Knight to "Templar"
rename_class(DBC_DIR, 6, "Templar")
```

### 2.3 - Replace Talent Trees

You need to overwrite the 3 existing talent tabs for the class and replace all talent entries with new ones.

```python
def clear_class_talents(dbc_dir, class_id):
    """
    Remove all talent entries for a class by finding its talent tabs
    and removing talents linked to those tabs.

    Args:
        dbc_dir: Path to DBFilesClient.
        class_id: The class ID whose talents to clear.

    Returns:
        list[int]: The tab IDs belonging to this class.
    """
    # Find tabs belonging to this class
    tab_path = os.path.join(dbc_dir, 'TalentTab.dbc')
    tab_dbc = DBCInjector(tab_path)

    class_mask = 1 << (class_id - 1)
    class_tab_ids = []

    for i, rec in enumerate(tab_dbc.records):
        tab_id = struct.unpack_from('<I', rec, 0)[0]
        # ClassMask is at field 20 (after ID + Name_lang(17) + SpellIconID + RaceMask)
        # = field index: 1(ID) + 17(Name) + 1(Icon) + 1(Race) = field 20 = byte 80
        cm = struct.unpack_from('<I', rec, (3 + _LOC_SLOTS) * 4)[0]
        if cm & class_mask:
            class_tab_ids.append(tab_id)

    print("Found {} talent tabs for class {}: {}".format(
        len(class_tab_ids), class_id, class_tab_ids))

    # Remove all talents in those tabs
    talent_path = os.path.join(dbc_dir, 'Talent.dbc')
    talent_dbc = DBCInjector(talent_path)

    removed = 0
    i = 0
    while i < len(talent_dbc.records):
        rec = talent_dbc.records[i]
        tab_id = struct.unpack_from('<I', rec, 4)[0]
        if tab_id in class_tab_ids:
            talent_dbc.records.pop(i)
            removed += 1
        else:
            i += 1

    talent_dbc.write(talent_path)
    print("Removed {} talent entries".format(removed))

    return class_tab_ids


def setup_replacement_talent_tabs(dbc_dir, class_id, spec_names):
    """
    Rename the 3 talent tabs for a class to new spec names.

    Args:
        dbc_dir: Path to DBFilesClient.
        class_id: The class ID.
        spec_names: List of 3 spec names, in tab order.

    Returns:
        list[int]: The 3 tab IDs in order.
    """
    tab_path = os.path.join(dbc_dir, 'TalentTab.dbc')
    tab_dbc = DBCInjector(tab_path)

    class_mask = 1 << (class_id - 1)
    tabs = []

    for i, rec in enumerate(tab_dbc.records):
        tab_id = struct.unpack_from('<I', rec, 0)[0]
        cm = struct.unpack_from('<I', rec, (3 + _LOC_SLOTS) * 4)[0]
        if cm & class_mask:
            order = struct.unpack_from('<I', rec, (5 + _LOC_SLOTS) * 4)[0]
            tabs.append((order, i, tab_id))

    tabs.sort()  # Sort by order index

    if len(tabs) != 3:
        print("WARNING: Expected 3 tabs, found {}".format(len(tabs)))
        return []

    tab_ids = []
    for order_idx, (_, rec_idx, tab_id) in enumerate(tabs):
        rec = bytearray(tab_dbc.records[rec_idx])

        # Update Name_lang (field 1, enUS = byte offset 4)
        new_name = spec_names[order_idx] if order_idx < len(spec_names) else "Spec {}".format(order_idx + 1)
        name_offset = tab_dbc.add_string(new_name)
        struct.pack_into('<I', rec, 4, name_offset)

        tab_dbc.records[rec_idx] = bytes(rec)
        tab_ids.append(tab_id)

    tab_dbc.write(tab_path)
    print("Renamed tabs: {}".format(list(zip(tab_ids, spec_names))))
    return tab_ids


# Example: Set up "Templar" class with 3 specs
# tab_ids = setup_replacement_talent_tabs(
#     DBC_DIR, 6,
#     ["Radiance", "Wrath", "Fortitude"]
# )
```

### 2.4 - Build Complete Talent Trees

After clearing the old talents and renaming the tabs, populate each tree with custom talents. Here is a framework for building a complete spec:

```python
def build_talent_record(talent_id, tab_id, tier, column,
                        spell_ranks, prereq_talents=None,
                        prereq_ranks=None, flags=0,
                        required_spell=0, category_mask=None):
    """Build a 92-byte Talent.dbc record. (See modify_talent_tree.md)"""
    ranks = list(spell_ranks) + [0] * 9
    ranks = ranks[:9]

    if prereq_talents is None:
        prereq_talents = [0, 0, 0]
    else:
        prereq_talents = list(prereq_talents) + [0] * 3
        prereq_talents = prereq_talents[:3]

    if prereq_ranks is None:
        prereq_ranks = [0, 0, 0]
    else:
        prereq_ranks = list(prereq_ranks) + [0] * 3
        prereq_ranks = prereq_ranks[:3]

    if category_mask is None:
        category_mask = [0, 0]

    buf = bytearray()
    buf += struct.pack('<I', talent_id)
    buf += struct.pack('<I', tab_id)
    buf += struct.pack('<I', tier)
    buf += struct.pack('<I', column)
    buf += struct.pack('<9I', *ranks)
    buf += struct.pack('<3I', *prereq_talents)
    buf += struct.pack('<3I', *prereq_ranks)
    buf += struct.pack('<I', flags)
    buf += struct.pack('<I', required_spell)
    buf += struct.pack('<2I', *category_mask)

    assert len(buf) == 92
    return bytes(buf)


def populate_spec_tree(dbc_dir, tab_id, talent_definitions):
    """
    Add a complete set of talents to a talent tab.

    Args:
        dbc_dir: Path to DBFilesClient.
        tab_id: TalentTab ID to populate.
        talent_definitions: List of talent dicts, each with:
            - 'tier': Row (0-10)
            - 'column': Column (0-3)
            - 'spell_ranks': List of spell IDs
            - 'prereq_index': Optional index into this list for prerequisite
            - 'prereq_rank': Required rank in prerequisite

    Returns:
        list[int]: Assigned talent IDs in definition order.
    """
    filepath = os.path.join(dbc_dir, 'Talent.dbc')
    dbc = DBCInjector(filepath)

    base_id = dbc.get_max_id() + 1
    talent_ids = []

    for idx, tdef in enumerate(talent_definitions):
        talent_id = base_id + idx

        # Resolve prerequisite by index
        prereq_talents = None
        prereq_ranks = None
        if 'prereq_index' in tdef and tdef['prereq_index'] is not None:
            prereq_idx = tdef['prereq_index']
            prereq_talents = [talent_ids[prereq_idx]]
            prereq_ranks = [tdef.get('prereq_rank', 1)]

        record = build_talent_record(
            talent_id=talent_id,
            tab_id=tab_id,
            tier=tdef['tier'],
            column=tdef['column'],
            spell_ranks=tdef['spell_ranks'],
            prereq_talents=prereq_talents,
            prereq_ranks=prereq_ranks,
        )

        dbc.records.append(record)
        talent_ids.append(talent_id)

    dbc.write(filepath)
    print("Added {} talents to tab {}".format(len(talent_ids), tab_id))
    return talent_ids


# Example: Populate the "Radiance" spec tree
# (Assumes custom spell IDs 91000-91050 already exist)
# radiance_talents = [
#     {'tier': 0, 'column': 0, 'spell_ranks': [91000, 91001, 91002]},
#     {'tier': 0, 'column': 1, 'spell_ranks': [91003, 91004, 91005, 91006, 91007]},
#     {'tier': 0, 'column': 2, 'spell_ranks': [91008, 91009, 91010]},
#     {'tier': 1, 'column': 0, 'spell_ranks': [91011, 91012]},
#     {'tier': 1, 'column': 1, 'spell_ranks': [91013, 91014, 91015],
#      'prereq_index': 1, 'prereq_rank': 5},  # Requires 5/5 in talent at index 1
#     # ... continue for all tiers
# ]
# populate_spec_tree(DBC_DIR, tab_ids[0], radiance_talents)
```

### 2.5 - Replace the Starting Spell Kit

Remove all old class abilities from SkillLineAbility.dbc and add the new ones:

```python
def replace_class_abilities(dbc_dir, class_id, new_abilities):
    """
    Replace all auto-learned abilities for a class.

    Args:
        dbc_dir: Path to DBFilesClient.
        class_id: The class ID.
        new_abilities: List of dicts, each with:
            - 'spell_id': The spell to teach
            - 'skill_line': The skill line FK (use class skill line)
            - 'acquire_method': 0=on creation, 2=on level
            - 'min_skill_rank': Level requirement (for acquire_method=2)
    """
    filepath = os.path.join(dbc_dir, 'SkillLineAbility.dbc')
    dbc = DBCInjector(filepath)

    class_mask = 1 << (class_id - 1)

    # Remove existing entries for this class
    # (Only remove entries where ClassMask matches exactly or
    #  where the skill line is a class-specific skill)
    removed = 0
    i = 0
    while i < len(dbc.records):
        rec = dbc.records[i]
        cmask = struct.unpack_from('<I', rec, 16)[0]  # ClassMask at field 4
        # Only remove if ClassMask contains ONLY our class bit
        if cmask == class_mask:
            dbc.records.pop(i)
            removed += 1
        else:
            i += 1

    print("Removed {} existing class abilities".format(removed))

    # Add new abilities
    base_sla_id = dbc.get_max_id() + 1
    for idx, ability in enumerate(new_abilities):
        sla_id = base_sla_id + idx

        buf = bytearray()
        buf += struct.pack('<I', sla_id)
        buf += struct.pack('<I', ability['skill_line'])
        buf += struct.pack('<I', ability['spell_id'])
        buf += struct.pack('<I', 0)                       # RaceMask (all races)
        buf += struct.pack('<I', class_mask)               # ClassMask
        buf += struct.pack('<I', 0)                       # ExcludeRace
        buf += struct.pack('<I', 0)                       # ExcludeClass
        buf += struct.pack('<I', ability.get('min_skill_rank', 0))
        buf += struct.pack('<I', 0)                       # SupercededBySpell
        buf += struct.pack('<I', ability.get('acquire_method', 0))
        buf += struct.pack('<I', 0)                       # TrivialHigh
        buf += struct.pack('<I', 0)                       # TrivialLow
        buf += struct.pack('<2I', 0, 0)                   # CharacterPoints[2]

        assert len(buf) == 56
        dbc.records.append(bytes(buf))

    dbc.write(filepath)
    print("Added {} new class abilities".format(len(new_abilities)))
```

### 2.6 - Update CharBaseInfo.dbc

`CharBaseInfo.dbc` defines which race+class combinations are valid. For WotLK 3.3.5a, the layout is:

```
No header ID field. Each record is 2 bytes:
  Byte 0: RaceID (uint8)
  Byte 1: ClassID (uint8)
```

This file has **no ID field** and each record is only 2 bytes. The DBC header reports `field_count=1` and `record_size=4` due to the padding, but the actual data is the first 2 bytes of each 4-byte record.

Since we are replacing an existing class (keeping the same ClassID), the CharBaseInfo entries already exist. You only need to modify this if you want to change which races can be the replacement class.

```python
def read_char_base_info(dbc_dir):
    """
    Read all race+class combinations from CharBaseInfo.dbc.

    Returns:
        list[tuple]: List of (race_id, class_id) tuples.
    """
    filepath = os.path.join(dbc_dir, 'CharBaseInfo.dbc')
    dbc = DBCInjector(filepath)

    combos = []
    for rec in dbc.records:
        race_id = rec[0]
        class_id = rec[1]
        combos.append((race_id, class_id))

    return combos


def add_race_class_combo(dbc_dir, race_id, class_id):
    """
    Add a new race+class combination to CharBaseInfo.dbc.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_id: Race ID.
        class_id: Class ID.
    """
    filepath = os.path.join(dbc_dir, 'CharBaseInfo.dbc')
    dbc = DBCInjector(filepath)

    # Check if already exists
    for rec in dbc.records:
        if rec[0] == race_id and rec[1] == class_id:
            print("Combo {}/{} already exists".format(race_id, class_id))
            return

    # CharBaseInfo records are padded to record_size (typically 4 bytes)
    record = bytearray(dbc.record_size)
    record[0] = race_id
    record[1] = class_id
    # Remaining bytes are padding (zeros)

    dbc.records.append(bytes(record))
    dbc.write(filepath)
    print("Added race+class combo: race={} class={}".format(race_id, class_id))


def remove_race_class_combo(dbc_dir, race_id, class_id):
    """
    Remove a race+class combination from CharBaseInfo.dbc.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_id: Race ID.
        class_id: Class ID.
    """
    filepath = os.path.join(dbc_dir, 'CharBaseInfo.dbc')
    dbc = DBCInjector(filepath)

    for i, rec in enumerate(dbc.records):
        if rec[0] == race_id and rec[1] == class_id:
            dbc.records.pop(i)
            dbc.write(filepath)
            print("Removed race+class combo: race={} class={}".format(
                race_id, class_id))
            return

    print("Combo {}/{} not found".format(race_id, class_id))


# Example: Allow all races to be the replacement class (Death Knight = 6)
# for race_id in [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]:
#     add_race_class_combo(DBC_DIR, race_id, 6)
```

### 2.7 - Update CharStartOutfit.dbc

`CharStartOutfit.dbc` defines the items a character starts with. For WotLK 3.3.5a (builds `3.0.1.8303` through `3.3.5.12340`):

```
Index   Field                Type      Count   Notes
------  -------------------  --------  ------  ---------------------------
  0     ID                   uint32    1       Primary key
  1     RaceID               uint8     1       Race
  2     ClassID              uint8     1       Class
  3     SexID                uint8     1       0=male, 1=female
  4     OutfitID             uint8     1       Outfit variant (usually 0)
  5-28  ItemID[24]           uint32    [24]    Starting item IDs
 29-52  DisplayItemID[24]    uint32    [24]    Display info IDs
 53-76  InventoryType[24]    uint32    [24]    Inventory slot types

Total: Record starts with 4 uint32-sized fields (ID + packed race/class/sex/outfit)
       followed by 72 uint32 values (24x3) = 77 fields = 308 bytes
```

Note that RaceID, ClassID, SexID, and OutfitID are packed as individual bytes within a 4-byte block after the ID field.

```python
def update_start_outfit(dbc_dir, class_id, starting_items):
    """
    Update starting equipment for a class.

    This updates ALL CharStartOutfit records matching the class ID
    to use the same set of starting items.

    Args:
        dbc_dir: Path to DBFilesClient.
        class_id: The class ID.
        starting_items: List of item dicts, each with:
            - 'item_id': Item template entry
            - 'display_id': CreatureDisplayInfo ID (0 for auto)
            - 'inv_type': Inventory type
    """
    filepath = os.path.join(dbc_dir, 'CharStartOutfit.dbc')
    dbc = DBCInjector(filepath)

    # Pad items to 24 slots
    items = list(starting_items) + [{'item_id': 0, 'display_id': 0, 'inv_type': 0}] * 24
    items = items[:24]

    updated = 0
    for i, rec in enumerate(dbc.records):
        # ClassID is at byte offset 5 (after 4-byte ID + 1-byte RaceID)
        rec_class = rec[5]
        if rec_class == class_id:
            buf = bytearray(rec)

            # Item IDs start at field 5 (byte offset 8 for the first item)
            # Note: actual offset depends on record layout
            # In WotLK: fields are ID(4) + Race(1)+Class(1)+Sex(1)+Outfit(1)(=4 bytes)
            # Then 24 ItemIDs, 24 DisplayItemIDs, 24 InventoryTypes
            item_offset = 8  # After ID(4) + packed header(4)

            for j in range(24):
                struct.pack_into('<I', buf, item_offset + j * 4,
                                items[j]['item_id'])

            display_offset = item_offset + 24 * 4
            for j in range(24):
                struct.pack_into('<I', buf, display_offset + j * 4,
                                items[j]['display_id'])

            inv_offset = display_offset + 24 * 4
            for j in range(24):
                struct.pack_into('<I', buf, inv_offset + j * 4,
                                items[j]['inv_type'])

            dbc.records[i] = bytes(buf)
            updated += 1

    dbc.write(filepath)
    print("Updated {} CharStartOutfit records for class {}".format(
        updated, class_id))
```

### 2.8 - Server-Side SQL Configuration

```sql
-- ============================================================
-- Server configuration for replacement class (Death Knight -> Templar)
-- ============================================================

-- 1. Update class-level stats (HP/mana per level)
-- player_classlevelstats defines base HP and mana per class per level
DELETE FROM `player_classlevelstats` WHERE `class` = 6;
-- Insert custom stats for all 80 levels (example for levels 1 and 80)
INSERT INTO `player_classlevelstats` (`class`, `level`, `basehp`, `basemana`)
VALUES
    (6, 1, 50, 100),     -- Level 1: 50 HP, 100 mana
    -- ... levels 2-79 ...
    (6, 80, 8500, 5000); -- Level 80: 8500 HP, 5000 mana

-- 2. Update race-specific base stats for the class
-- player_levelstats defines base stats (str/agi/sta/int/spi) per race/class/level
-- Example: Human Templar level 80 stats
DELETE FROM `player_levelstats` WHERE `class` = 6;
-- Insert for each race/level combination
INSERT INTO `player_levelstats` (`race`, `class`, `level`, `str`, `agi`, `sta`, `inte`, `spi`)
VALUES
    (1, 6, 1, 23, 20, 22, 20, 21),   -- Human level 1
    -- ... more levels ...
    (1, 6, 80, 150, 120, 145, 120, 130); -- Human level 80

-- 3. Starting position for new characters
DELETE FROM `playercreateinfo` WHERE `class` = 6;
-- Set spawn point for each race that can be this class
INSERT INTO `playercreateinfo` (`race`, `class`, `map`, `zone`, `position_x`,
    `position_y`, `position_z`, `orientation`)
VALUES
    (1, 6, 0, 12, -8949.95, -132.493, 83.5312, 0),  -- Human starting zone
    (2, 6, 1, 14, -618.518, -4251.67, 38.718, 0);    -- Orc starting zone
    -- ... add for each allowed race ...

-- 4. Starting action bar layout
DELETE FROM `playercreateinfo_action` WHERE `class` = 6;
INSERT INTO `playercreateinfo_action` (`race`, `class`, `button`, `action`, `type`)
VALUES
    (0, 6, 0, 91000, 0),    -- Slot 1: first class spell (all races)
    (0, 6, 1, 91001, 0),    -- Slot 2: second class spell
    (0, 6, 2, 91002, 0);    -- Slot 3: third class spell
    -- race=0 means "all races that can be this class"

-- 5. Starting spells (supplements SkillLineAbility)
DELETE FROM `playercreateinfo_spell_custom` WHERE `classmask` & 32;
INSERT INTO `playercreateinfo_spell_custom` (`racemask`, `classmask`, `Spell`, `Note`)
VALUES
    (0, 32, 91000, 'Templar Strike'),
    (0, 32, 91001, 'Holy Shield'),
    (0, 32, 91002, 'Divine Light');
    -- classmask 32 = Death Knight bit (0x020)
```

---

## Part 3: UI Texture Requirements

When replacing a class, the UI textures come from the original class. This means:

1. **Talent tree backgrounds**: Defined in TalentTab.dbc's BackgroundFile field. You can change these to any BLP texture in the client's data files. Create new background BLPs and patch them into a custom MPQ.

2. **Class icon**: The class icon on the character creation screen is mapped by ClassID in the client's GlueXML. You CAN replace the texture file itself in a custom MPQ but cannot change the mapping without client binary edits.

3. **Class color**: Hardcoded in the client binary. Death Knight color is `0xC41F3B` (red). This cannot be changed via DBC edits. To change it, you need a client binary patch or a Lua addon that overrides `RAID_CLASS_COLORS`.

4. **Power bar**: Death Knight uses runic power (DisplayPower = 6). You can change this in ChrClasses.dbc's field 2 to another power type, but the power bar visual appearance is tied to the DisplayPower value in the client rendering code.

---

## Part 4: What About a True ClassID 12+?

If you absolutely must add ClassID 12+, here is what you need beyond DBC changes:

### Client-side binary patches required:
1. Patch `MAX_CLASSES` in the client binary
2. Patch class color table
3. Patch class button coordinates in GlueXML/FrameXML
4. Patch class power bar mapping
5. Patch combat animation lookup tables
6. Patch spell class family validation

### Server-side C++ changes required:
1. Update `MAX_CLASSES` constant
2. Add class enum value
3. Add stat calculation formulas
4. Add talent tree validation
5. Add spell class family handling
6. Add starting zone configuration
7. Recompile the server

### Community tools that enable this:
Some community projects have created client binary patchers that automate the hardcoded changes. Search for "WoW 3.3.5a custom class binary patch" in modding communities. These tools are outside the scope of pywowlib but are the missing piece for a true new class.

---

## Complete "Replace Class" Checklist

| Step | Component                  | Tool/File                | Status |
|------|----------------------------|--------------------------|--------|
| 1    | Rename class               | ChrClasses.dbc           | [ ]    |
| 2    | Create all spells          | Spell.dbc                | [ ]    |
| 3    | Create spell icons         | SpellIcon.dbc            | [ ]    |
| 4    | Clear old talents          | Talent.dbc               | [ ]    |
| 5    | Rename talent tabs         | TalentTab.dbc            | [ ]    |
| 6    | Populate talent trees      | Talent.dbc               | [ ]    |
| 7    | Replace auto-learn spells  | SkillLineAbility.dbc     | [ ]    |
| 8    | Update race combos         | CharBaseInfo.dbc         | [ ]    |
| 9    | Update starting gear       | CharStartOutfit.dbc      | [ ]    |
| 10   | Configure server stats     | player_levelstats SQL    | [ ]    |
| 11   | Configure class stats      | player_classlevelstats   | [ ]    |
| 12   | Set starting position      | playercreateinfo SQL     | [ ]    |
| 13   | Set starting spells        | playercreateinfo_spell   | [ ]    |
| 14   | Set action bar layout      | playercreateinfo_action  | [ ]    |
| 15   | Copy DBC to server         | Server dbc directory     | [ ]    |
| 16   | Create talent backgrounds  | Custom MPQ + BLP files   | [ ]    |
| 17   | Test character creation    | In-game testing          | [ ]    |
| 18   | Test all spells            | In-game testing          | [ ]    |
| 19   | Test talent trees          | In-game testing          | [ ]    |
| 20   | Test leveling progression  | In-game testing          | [ ]    |

---

## Common Pitfalls and Troubleshooting

### Client crashes on character creation screen
- **Cause**: ChrClasses.dbc record size mismatch or corrupted string references.
- **Fix**: Verify the record size matches the original. Use `modify_spell_field` style in-place edits rather than rebuilding the entire record.

### Talent panel is blank
- **Cause**: No talents linked to the class's TalentTab IDs, or the tab ClassMask does not match.
- **Fix**: Verify TalentTab.dbc ClassMask bits match the class ID. Verify Talent.dbc entries have the correct TabID.

### Character starts with no abilities
- **Cause**: SkillLineAbility entries were removed but new ones were not added, or the ClassMask is wrong.
- **Fix**: Verify SkillLineAbility entries have `ClassMask = (1 << (class_id - 1))` for the replaced class. Also check server-side `playercreateinfo_spell_custom`.

### "Character creation failed" error
- **Cause**: Missing CharBaseInfo entry for the race+class combination, or missing playercreateinfo entry on the server.
- **Fix**: Ensure both CharBaseInfo.dbc (client) and playercreateinfo (server) have entries for every allowed race+class combination.

### Starting equipment is invisible
- **Cause**: CharStartOutfit.dbc has item IDs that do not exist in the server's item_template table.
- **Fix**: Use item IDs that exist in both the server database and the client's item cache/DBC files.

### Power bar shows wrong resource type
- **Cause**: ChrClasses.dbc DisplayPower field does not match the intended power type.
- **Fix**: Set DisplayPower to: 0=mana, 1=rage, 3=energy, 6=runic power. Note that changing from the original class's power type may cause visual glitches since the bar appearance is partially hardcoded.

---

## Cross-References

- [Add New Spell](./add_new_spell.md) - Creating the entire spell kit for the replacement class
- [Change Spell Data](./change_spell_data.md) - Fine-tuning spell mechanics
- [Modify Talent Tree](./modify_talent_tree.md) - Building talent trees in detail
- [Change Racial Traits](./change_racial_traits.md) - Race-class auto-learn configuration
