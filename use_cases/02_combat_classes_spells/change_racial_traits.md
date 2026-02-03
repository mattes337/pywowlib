# Change Racial Traits

**Complexity**: Intermediate |
**DBC Files**: Spell.dbc, SkillLineAbility.dbc, ChrRaces.dbc |
**SQL Tables**: player_levelstats, playercreateinfo_spell_custom |
**pywowlib Modules**: `world_builder.dbc_injector.DBCInjector`

---

## Overview

Every playable race in WoW 3.3.5a has a set of racial traits -- passive abilities and active spells that are automatically learned at character creation or at specific levels. Modifying these traits involves several interconnected systems:

1. **Spell.dbc** - Defines the spell itself (passive aura, active ability, etc.)
2. **SkillLineAbility.dbc** - Controls auto-learning: links a spell to a skill line with race/class masks
3. **ChrRaces.dbc** - Contains race-level references and configuration
4. **Server-side SQL** - `player_levelstats` for base stat adjustments, `playercreateinfo_spell_custom` for spells granted at creation

This guide covers reading existing racial trait data, modifying passive racial bonuses (like stat increases), changing active racial abilities, adding entirely new racial traits via SkillLineAbility auto-learning, and adjusting base stats through the server database.

---

## Prerequisites

- Stock `Spell.dbc`, `SkillLineAbility.dbc`, and `ChrRaces.dbc` from the WoW 3.3.5a client
- Python 3.6+ with pywowlib
- Knowledge of the target race's ID
- Access to the AzerothCore world database for stat modifications

---

## Step 1: Race and Class ID Reference

### Race IDs (WotLK 3.3.5a):

| Race ID | Name     | Faction  | Race Mask Bit |
|---------|----------|----------|---------------|
| 1       | Human    | Alliance | 0x001         |
| 2       | Orc      | Horde    | 0x002         |
| 3       | Dwarf    | Alliance | 0x004         |
| 4       | Night Elf| Alliance | 0x008         |
| 5       | Undead   | Horde    | 0x010         |
| 6       | Tauren   | Horde    | 0x020         |
| 7       | Gnome    | Alliance | 0x040         |
| 8       | Troll    | Horde    | 0x080         |
| 10      | Blood Elf| Horde    | 0x200         |
| 11      | Draenei  | Alliance | 0x400         |

### Class IDs and Masks:

| Class ID | Name         | Mask Bit |
|----------|--------------|----------|
| 1        | Warrior      | 0x001    |
| 2        | Paladin      | 0x002    |
| 3        | Hunter       | 0x004    |
| 4        | Rogue        | 0x008    |
| 5        | Priest       | 0x010    |
| 6        | Death Knight | 0x020    |
| 7        | Shaman       | 0x040    |
| 8        | Mage         | 0x080    |
| 9        | Warlock      | 0x100    |
| 11       | Druid        | 0x400    |

### Racial skill lines:

Each race has a dedicated skill line in `SkillLine.dbc`. The racial traits are linked to these skill lines via `SkillLineAbility.dbc`. Key skill line IDs:

| Skill Line ID | Race      |
|---------------|-----------|
| 754           | Human     |
| 125           | Orc       |
| 101           | Dwarf     |
| 126           | Night Elf |
| 220           | Undead    |
| 124           | Tauren    |
| 753           | Gnome     |
| 733           | Troll     |
| 756           | Blood Elf |
| 760           | Draenei   |

---

## Step 2: Understand SkillLineAbility.dbc (WotLK 3.3.5a)

From `wdbx/dbd/definitions/SkillLineAbility.dbd`, the WotLK layout for builds `3.0.1.8788` through `3.3.5.12340`:

```
Index   Field                   Type      Notes
------  ----------------------  --------  ----------------------------------
  0     ID                      uint32    Primary key
  1     SkillLine               uint32    FK to SkillLine.dbc (racial skill)
  2     Spell                   uint32    FK to Spell.dbc (the ability)
  3     RaceMask                uint32    Which races learn this (bitmask)
  4     ClassMask               uint32    Which classes learn this (bitmask)
  5     ExcludeRace             uint32    Races that do NOT learn this
  6     ExcludeClass            uint32    Classes that do NOT learn this
  7     MinSkillLineRank        uint32    Min skill level to learn (0 = always)
  8     SupercededBySpell       uint32    Spell that replaces this at higher rank
  9     AcquireMethod           uint32    0=on creation, 1=on skill learn, 2=on level
 10     TrivialSkillLineRankHigh uint32   Skill level where this turns grey
 11     TrivialSkillLineRankLow  uint32   Skill level where this turns green
 12-13  CharacterPoints[2]      uint32    Talent points cost (always 0 for racials)

Total: 14 fields = 56 bytes per record
```

### AcquireMethod values:
- **0** = Learned on character creation (most racial passives)
- **1** = Learned when the skill itself is learned
- **2** = Learned when the player reaches a certain level (MinSkillLineRank acts as level)

### How racial auto-learning works:
When a character is created, the server iterates through `SkillLineAbility.dbc` and teaches any spell where:
1. The character's race matches the `RaceMask` (or RaceMask is 0 for all races)
2. The character's class matches the `ClassMask` (or ClassMask is 0 for all classes)
3. The `AcquireMethod` is 0 (learned on creation)
4. The `SkillLine` matches a skill the character has (racial skills are granted automatically)

---

## Step 3: Read Existing Racial Traits

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"

# Racial skill line IDs
RACIAL_SKILLS = {
    'Human':    754,
    'Orc':      125,
    'Dwarf':    101,
    'NightElf': 126,
    'Undead':   220,
    'Tauren':   124,
    'Gnome':    753,
    'Troll':    733,
    'BloodElf': 756,
    'Draenei':  760,
}

# Race mask lookup
RACE_MASKS = {
    'Human': 0x001, 'Orc': 0x002, 'Dwarf': 0x004, 'NightElf': 0x008,
    'Undead': 0x010, 'Tauren': 0x020, 'Gnome': 0x040, 'Troll': 0x080,
    'BloodElf': 0x200, 'Draenei': 0x400,
}


def list_racial_abilities(dbc_dir, race_name):
    """
    List all racial abilities for a given race.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_name: Race name (e.g., 'Human', 'Orc').

    Returns:
        list[dict]: List of racial ability entries.
    """
    skill_line_id = RACIAL_SKILLS[race_name]
    race_mask = RACE_MASKS[race_name]

    # Load SkillLineAbility.dbc
    sla_path = os.path.join(dbc_dir, 'SkillLineAbility.dbc')
    sla_dbc = DBCInjector(sla_path)

    # Load Spell.dbc for name lookup
    spell_path = os.path.join(dbc_dir, 'Spell.dbc')
    spell_dbc = DBCInjector(spell_path)

    # Build spell name cache (ID -> name)
    spell_names = {}
    for i in range(len(spell_dbc.records)):
        rec = spell_dbc.records[i]
        sid = struct.unpack_from('<I', rec, 0)[0]
        name_offset = struct.unpack_from('<I', rec, 136 * 4)[0]
        spell_names[sid] = spell_dbc.get_string(name_offset)

    # Find abilities linked to this race's skill line
    abilities = []
    for i in range(len(sla_dbc.records)):
        rec = sla_dbc.records[i]
        sla_id = struct.unpack_from('<I', rec, 0)[0]
        skill_line = struct.unpack_from('<I', rec, 4)[0]
        spell_id = struct.unpack_from('<I', rec, 8)[0]
        rmask = struct.unpack_from('<I', rec, 12)[0]
        cmask = struct.unpack_from('<I', rec, 16)[0]
        acquire = struct.unpack_from('<I', rec, 36)[0]

        if skill_line == skill_line_id:
            spell_name = spell_names.get(spell_id, "Unknown")
            abilities.append({
                'sla_id': sla_id,
                'spell_id': spell_id,
                'spell_name': spell_name,
                'race_mask': rmask,
                'class_mask': cmask,
                'acquire_method': acquire,
            })

    return abilities


# Example: List all Human racial abilities
print("=== Human Racial Abilities ===")
for ability in list_racial_abilities(DBC_DIR, 'Human'):
    print("  SLA {}: {} (spell {}) acquire={}".format(
        ability['sla_id'],
        ability['spell_name'],
        ability['spell_id'],
        ability['acquire_method'],
    ))
```

---

## Step 4: Modify an Existing Racial Passive in Spell.dbc

Most racial passives are `APPLY_AURA` spells with effect types like:
- `SPELL_AURA_MOD_BASE_RESISTANCE_PCT` (Stoneform armor bonus)
- `SPELL_AURA_MOD_SKILL` (Expansive Mind intellect bonus)
- `SPELL_AURA_MOD_RATING` (Sword/Mace specialization expertise)
- `SPELL_AURA_PROC_TRIGGER_SPELL` (Will of the Forsaken, etc.)
- `SPELL_AURA_MOD_STAT` (stat bonuses)

To change the magnitude of a passive racial, you modify `EffectBasePoints` in Spell.dbc:

```python
def modify_racial_passive_value(dbc_dir, spell_id, new_value, effect_slot=0):
    """
    Change the numeric value of a racial passive spell.

    For example, if a racial grants +5 Intellect via a passive aura,
    change that to +10 by setting new_value=9 (base_points = value - 1).

    Args:
        dbc_dir: Path to DBFilesClient.
        spell_id: The spell ID of the racial passive.
        new_value: New effect value (the number shown in tooltip).
        effect_slot: Which effect slot to modify (0, 1, or 2).
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    # Find the spell
    target_idx = -1
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == spell_id:
            target_idx = i
            break

    if target_idx < 0:
        raise ValueError("Spell {} not found".format(spell_id))

    rec = bytearray(dbc.records[target_idx])

    # EffectBasePoints: fields 80, 81, 82 (byte offsets 320, 324, 328)
    field_index = 80 + effect_slot
    byte_offset = field_index * 4

    old_value = struct.unpack_from('<i', rec, byte_offset)[0]
    struct.pack_into('<i', rec, byte_offset, new_value - 1)

    # Also set DieSides to 1 for a fixed value
    die_field = 74 + effect_slot
    struct.pack_into('<I', rec, die_field * 4, 1)

    dbc.records[target_idx] = bytes(rec)
    dbc.write(filepath)

    print("Spell {}: effect {} changed from {} to {}".format(
        spell_id, effect_slot, old_value + 1, new_value))


# Example: Gnome Expansive Mind (spell 20591) gives +5% Intellect.
# The base_points for a percentage aura stores the percentage value.
# To change it to +10%:
# modify_racial_passive_value(DBC_DIR, 20591, 10)

# Example: Human Spirit (spell 20598) gives +3% Spirit.
# Change to +5%:
# modify_racial_passive_value(DBC_DIR, 20598, 5)
```

---

## Step 5: Add a New Racial Trait

Adding a new racial trait requires three steps:
1. Create the spell in Spell.dbc (see [Add New Spell](./add_new_spell.md))
2. Add a SkillLineAbility entry to link it to the racial skill line
3. Optionally update server-side tables

```python
def build_skill_line_ability_record(sla_id, skill_line, spell_id,
                                     race_mask=0, class_mask=0,
                                     exclude_race=0, exclude_class=0,
                                     min_skill_rank=0,
                                     superceded_by=0,
                                     acquire_method=0,
                                     trivial_high=0, trivial_low=0):
    """
    Build a 56-byte SkillLineAbility.dbc record for WotLK 3.3.5a.

    Args:
        sla_id: Unique SkillLineAbility ID.
        skill_line: SkillLine.dbc FK (racial skill line ID).
        spell_id: Spell.dbc FK (the ability to learn).
        race_mask: Which races learn this (0 = all).
        class_mask: Which classes learn this (0 = all).
        exclude_race: Races that do NOT learn this.
        exclude_class: Classes that do NOT learn this.
        min_skill_rank: Minimum skill level to learn.
        superceded_by: Spell that replaces this at higher rank.
        acquire_method: 0=on creation, 1=on skill learn, 2=on level.
        trivial_high: Skill level where this turns grey.
        trivial_low: Skill level where this turns green.

    Returns:
        bytes: 56-byte binary record.
    """
    buf = bytearray()
    buf += struct.pack('<I', sla_id)            # 0: ID
    buf += struct.pack('<I', skill_line)         # 1: SkillLine
    buf += struct.pack('<I', spell_id)           # 2: Spell
    buf += struct.pack('<I', race_mask)          # 3: RaceMask
    buf += struct.pack('<I', class_mask)         # 4: ClassMask
    buf += struct.pack('<I', exclude_race)       # 5: ExcludeRace
    buf += struct.pack('<I', exclude_class)      # 6: ExcludeClass
    buf += struct.pack('<I', min_skill_rank)     # 7: MinSkillLineRank
    buf += struct.pack('<I', superceded_by)      # 8: SupercededBySpell
    buf += struct.pack('<I', acquire_method)     # 9: AcquireMethod
    buf += struct.pack('<I', trivial_high)       # 10: TrivialSkillLineRankHigh
    buf += struct.pack('<I', trivial_low)        # 11: TrivialSkillLineRankLow
    buf += struct.pack('<2I', 0, 0)             # 12-13: CharacterPoints[2]

    assert len(buf) == 56, "SLA record size mismatch: {}".format(len(buf))
    return bytes(buf)


def add_racial_ability(dbc_dir, race_name, spell_id,
                       class_mask=0, acquire_method=0,
                       sla_id=None):
    """
    Link a spell to a race's skill line so it is auto-learned.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_name: Race name (e.g., 'Human', 'Orc').
        spell_id: The spell to teach.
        class_mask: Class restriction (0 = all classes of this race).
        acquire_method: 0=on creation, 2=on level.
        sla_id: Explicit SLA ID, or None for auto.

    Returns:
        int: The assigned SkillLineAbility ID.
    """
    skill_line_id = RACIAL_SKILLS[race_name]
    race_mask = RACE_MASKS[race_name]

    filepath = os.path.join(dbc_dir, 'SkillLineAbility.dbc')
    dbc = DBCInjector(filepath)

    if sla_id is None:
        sla_id = dbc.get_max_id() + 1

    record = build_skill_line_ability_record(
        sla_id=sla_id,
        skill_line=skill_line_id,
        spell_id=spell_id,
        race_mask=race_mask,
        class_mask=class_mask,
        acquire_method=acquire_method,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    print("Added racial ability: {} -> spell {} (SLA ID {})".format(
        race_name, spell_id, sla_id))
    return sla_id


# Example: Give Orcs a new passive racial (spell 90400 must exist in Spell.dbc)
# This spell would be auto-learned on character creation.
# add_racial_ability(DBC_DIR, 'Orc', 90400)

# Example: Give Humans a new ability only for Warrior class
# add_racial_ability(DBC_DIR, 'Human', 90401, class_mask=0x001)
```

---

## Step 6: Remove a Racial Trait

```python
def remove_racial_ability(dbc_dir, race_name, spell_id):
    """
    Remove a spell from a race's auto-learn list.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_name: Race name.
        spell_id: The spell to remove.

    Returns:
        bool: True if found and removed, False otherwise.
    """
    skill_line_id = RACIAL_SKILLS[race_name]

    filepath = os.path.join(dbc_dir, 'SkillLineAbility.dbc')
    dbc = DBCInjector(filepath)

    for i, rec in enumerate(dbc.records):
        sla_skill = struct.unpack_from('<I', rec, 4)[0]
        sla_spell = struct.unpack_from('<I', rec, 8)[0]
        if sla_skill == skill_line_id and sla_spell == spell_id:
            dbc.records.pop(i)
            dbc.write(filepath)
            print("Removed racial ability: {} -> spell {}".format(
                race_name, spell_id))
            return True

    print("WARNING: Ability not found for {} with spell {}".format(
        race_name, spell_id))
    return False


# Example: Remove the Orc Blood Fury active racial
# Orc Blood Fury active is spell ID 33702 (melee version)
# remove_racial_ability(DBC_DIR, 'Orc', 33702)
```

---

## Step 7: Replace a Racial Trait

Replacing a racial trait combines removal and addition. This is the safest approach when you want to swap one ability for another:

```python
def replace_racial_ability(dbc_dir, race_name, old_spell_id, new_spell_id,
                           class_mask=0, acquire_method=0):
    """
    Replace one racial ability with another.

    Args:
        dbc_dir: Path to DBFilesClient.
        race_name: Race name.
        old_spell_id: The existing spell to remove.
        new_spell_id: The new spell to add.
        class_mask: Class restriction for the new ability.
        acquire_method: How the new ability is learned.

    Returns:
        int: The new SkillLineAbility ID.
    """
    # Remove old
    remove_racial_ability(dbc_dir, race_name, old_spell_id)

    # Add new
    return add_racial_ability(
        dbc_dir, race_name, new_spell_id,
        class_mask=class_mask,
        acquire_method=acquire_method,
    )


# Example: Replace Human Diplomacy (spell 20599) with a custom racial
# replace_racial_ability(DBC_DIR, 'Human', 20599, 90500)
```

---

## Step 8: Modify Base Stats via SQL

Racial base stats are stored in the server's `player_levelstats` table. Each row defines the base stats for a specific race/class/level combination.

```sql
-- ============================================================
-- Modify base stats for Orc Warriors
-- ============================================================

-- View current stats for Orc (race 2) Warrior (class 1) at level 80
SELECT * FROM `player_levelstats`
WHERE `race` = 2 AND `class` = 1 AND `level` = 80;

-- Increase Orc Warrior base strength at level 80 by 10
UPDATE `player_levelstats`
SET `str` = `str` + 10
WHERE `race` = 2 AND `class` = 1 AND `level` = 80;

-- Increase all Orc Warriors' strength at all levels by 5
UPDATE `player_levelstats`
SET `str` = `str` + 5
WHERE `race` = 2 AND `class` = 1;

-- Set exact stats for a specific race/class/level
UPDATE `player_levelstats`
SET `str` = 180, `agi` = 100, `sta` = 160, `inte` = 35, `spi` = 55
WHERE `race` = 2 AND `class` = 1 AND `level` = 80;
```

### player_levelstats columns:

| Column  | Type   | Description              |
|---------|--------|--------------------------|
| race    | uint8  | Race ID                  |
| class   | uint8  | Class ID                 |
| level   | uint8  | Character level (1-80)   |
| str     | uint16 | Base Strength            |
| agi     | uint16 | Base Agility             |
| sta     | uint16 | Base Stamina             |
| inte    | uint16 | Base Intellect           |
| spi     | uint16 | Base Spirit              |

---

## Step 9: Grant Spells at Character Creation via SQL

For spells that should be known immediately when creating a character (as an alternative or supplement to SkillLineAbility):

```sql
-- Grant a custom spell to all new Orc characters
DELETE FROM `playercreateinfo_spell_custom`
WHERE `racemask` = 2 AND `classmask` = 0 AND `Spell` = 90400;
INSERT INTO `playercreateinfo_spell_custom`
    (`racemask`, `classmask`, `Spell`, `Note`)
VALUES
    (2, 0, 90400, 'Custom Orc racial - Blood Fury Enhanced');

-- Grant a spell only to Orc Warriors
DELETE FROM `playercreateinfo_spell_custom`
WHERE `racemask` = 2 AND `classmask` = 1 AND `Spell` = 90401;
INSERT INTO `playercreateinfo_spell_custom`
    (`racemask`, `classmask`, `Spell`, `Note`)
VALUES
    (2, 1, 90401, 'Custom Orc Warrior racial - Axe Mastery Enhanced');
```

---

## Step 10: ChrRaces.dbc Reference

The `ChrRaces.dbc` file for WotLK 3.3.5a (builds `3.0.1.8681` through `3.3.5.12340`) contains fundamental race configuration. Key fields relevant to racial traits:

```
Index   Field                   Type       Notes
------  ----------------------  ---------  ----------------------------------
  0     ID                      uint32     Race ID (primary key)
  1     DamageBonusStat         uint32     Primary stat for damage bonus
  2     DisplayPower            uint32     Default power type shown
  3     PetNameToken            string     Pet naming convention
  4-20  Name_lang               locstring  Race name (17 x uint32)
 21-37  Name_female_lang        locstring  Female race name
 38-54  Name_male_lang          locstring  Male race name
 55     Filename                string     Model file prefix
 56     SpellClassSet           uint32     Spell class family
 57     Flags                   uint32     Race flags
 58     CinematicSequenceID     uint32     Intro cinematic
 59     Required_expansion      uint32     0=classic, 1=TBC, 2=WotLK

Total: 60 fields = 240 bytes per record (approximate, varies with locstring)
```

You generally do not need to modify ChrRaces.dbc for racial trait changes. It is listed here for completeness. The racial trait system is driven primarily by Spell.dbc and SkillLineAbility.dbc.

---

## Step 11: Complete Working Example

This complete example adds a custom passive racial trait to Dwarves that increases their armor by 5%:

```python
"""
Complete example: Add "Stoneblood" passive racial to Dwarves.
Increases armor by 5% for all Dwarf characters.
"""
import struct
import os
from world_builder.dbc_injector import DBCInjector

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"
OUTPUT_DIR = "output"
_LOC_SLOTS = 17

# --- Step 1: Create the passive spell in Spell.dbc ---
# (Using the build_spell_record function from add_new_spell.md)
# This is a passive APPLY_AURA spell with MOD_BASE_RESISTANCE_PCT aura.

spell_dbc_path = os.path.join(DBC_DIR, 'Spell.dbc')
spell_dbc = DBCInjector(spell_dbc_path)

STONEBLOOD_SPELL_ID = 90500

def pack_locstring(string_offset):
    values = [0] * _LOC_SLOTS
    values[0] = string_offset
    values[16] = 0xFFFFFFFF
    return struct.pack('<{}I'.format(_LOC_SLOTS), *values)

# Build the passive spell record (936 bytes for WotLK 3.3.5a)
name_off = spell_dbc.add_string("Stoneblood")
desc_off = spell_dbc.add_string("Increases armor from items by $s1%.")
aura_off = spell_dbc.add_string("Armor from items increased by $s1%.")

buf = bytearray()
buf += struct.pack('<I', STONEBLOOD_SPELL_ID)    # ID
buf += struct.pack('<I', 0)                       # Category
buf += struct.pack('<I', 0)                       # DispelType
buf += struct.pack('<I', 0)                       # Mechanic
# Attributes: PASSIVE (0x00000040) | NOT_SHAPESHIFT (0x10000000)
buf += struct.pack('<I', 0x00000040)              # Attributes (PASSIVE)
buf += struct.pack('<I', 0)                       # AttributesEx
buf += struct.pack('<6I', 0, 0, 0, 0, 0, 0)     # AttributesExB-G
buf += struct.pack('<2I', 0, 0)                   # ShapeshiftMask[2]
buf += struct.pack('<2I', 0, 0)                   # ShapeshiftExclude[2]
buf += struct.pack('<I', 0)                       # Targets
buf += struct.pack('<I', 0)                       # TargetCreatureType
buf += struct.pack('<I', 0)                       # RequiresSpellFocus
buf += struct.pack('<I', 0)                       # FacingCasterFlags
buf += struct.pack('<8I', 0,0,0,0,0,0,0,0)       # Aura states and spells
buf += struct.pack('<I', 1)                       # CastingTimeIndex (instant)
buf += struct.pack('<I', 0)                       # RecoveryTime
buf += struct.pack('<I', 0)                       # CategoryRecoveryTime
buf += struct.pack('<I', 0)                       # InterruptFlags
buf += struct.pack('<I', 0)                       # AuraInterruptFlags
buf += struct.pack('<I', 0)                       # ChannelInterruptFlags
buf += struct.pack('<3I', 0, 0, 0)               # ProcTypeMask, Chance, Charges
buf += struct.pack('<3I', 0, 0, 0)               # MaxLevel, BaseLevel, SpellLevel
buf += struct.pack('<I', 21)                      # DurationIndex (21 = infinite/-1)
buf += struct.pack('<I', 0)                       # PowerType
buf += struct.pack('<I', 0)                       # ManaCost
buf += struct.pack('<3I', 0, 0, 0)               # ManaCostPerLevel, MPS, MPSPL
buf += struct.pack('<I', 1)                       # RangeIndex (self)
buf += struct.pack('<f', 0.0)                     # Speed
buf += struct.pack('<2I', 0, 0)                   # ModalNextSpell, CumulativeAura
buf += struct.pack('<2I', 0, 0)                   # Totem[2]
buf += struct.pack('<8I', 0,0,0,0,0,0,0,0)       # Reagent[8]
buf += struct.pack('<8I', 0,0,0,0,0,0,0,0)       # ReagentCount[8]
buf += struct.pack('<i', -1)                      # EquippedItemClass
buf += struct.pack('<2I', 0, 0)                   # EquippedItemSubclass, InvTypes
# Effects: APPLY_AURA (6) with SPELL_AURA_MOD_BASE_RESISTANCE_PCT (142)
buf += struct.pack('<3I', 6, 0, 0)               # Effect[3] = APPLY_AURA
buf += struct.pack('<3I', 1, 0, 0)               # EffectDieSides[3]
buf += struct.pack('<3f', 0.0, 0.0, 0.0)         # EffectRealPointsPerLevel[3]
buf += struct.pack('<3i', 4, 0, 0)               # EffectBasePoints[3] (5-1=4)
buf += struct.pack('<3I', 0, 0, 0)               # EffectMechanic[3]
buf += struct.pack('<3I', 1, 0, 0)               # ImplicitTargetA[3] (SELF)
buf += struct.pack('<3I', 0, 0, 0)               # ImplicitTargetB[3]
buf += struct.pack('<3I', 0, 0, 0)               # EffectRadiusIndex[3]
buf += struct.pack('<3I', 142, 0, 0)             # EffectAura[3] = MOD_RESISTANCE_PCT
buf += struct.pack('<3I', 0, 0, 0)               # EffectAuraPeriod[3]
buf += struct.pack('<3f', 0.0, 0.0, 0.0)         # EffectAmplitude[3]
buf += struct.pack('<3I', 0, 0, 0)               # EffectChainTargets[3]
buf += struct.pack('<3I', 0, 0, 0)               # EffectItemType[3]
buf += struct.pack('<3i', 1, 0, 0)               # EffectMiscValue[3] (1=phys armor)
buf += struct.pack('<3i', 0, 0, 0)               # EffectMiscValueB[3]
buf += struct.pack('<3I', 0, 0, 0)               # EffectTriggerSpell[3]
buf += struct.pack('<3f', 0.0, 0.0, 0.0)         # EffectPointsPerCombo[3]
buf += struct.pack('<9I', 0,0,0,0,0,0,0,0,0)    # SpellClassMask A/B/C [3]
buf += struct.pack('<2I', 0, 0)                   # SpellVisualID[2]
buf += struct.pack('<I', 2588)                    # SpellIconID (stone shield icon)
buf += struct.pack('<I', 0)                       # ActiveIconID
buf += struct.pack('<I', 0)                       # SpellPriority
buf += pack_locstring(name_off)                   # Name_lang
buf += pack_locstring(0)                          # NameSubtext_lang
buf += pack_locstring(desc_off)                   # Description_lang
buf += pack_locstring(aura_off)                   # AuraDescription_lang
buf += struct.pack('<I', 0)                       # ManaCostPct
buf += struct.pack('<2I', 0, 0)                   # StartRecoveryCategory, Time
buf += struct.pack('<I', 0)                       # MaxTargetLevel
buf += struct.pack('<I', 0)                       # SpellClassSet
buf += struct.pack('<3I', 0, 0, 0)               # SpellClassMask[3]
buf += struct.pack('<I', 0)                       # MaxTargets
buf += struct.pack('<I', 0)                       # DefenseType
buf += struct.pack('<I', 0)                       # PreventionType
buf += struct.pack('<I', 0)                       # StanceBarOrder
buf += struct.pack('<3f', 0.0, 0.0, 0.0)         # EffectChainAmplitude[3]
buf += struct.pack('<2I', 0, 0)                   # MinFactionID, MinReputation
buf += struct.pack('<I', 0)                       # RequiredAuraVision
buf += struct.pack('<2I', 0, 0)                   # RequiredTotemCategoryID[2]
buf += struct.pack('<I', 0)                       # RequiredAreasID
buf += struct.pack('<I', 0x01)                    # SchoolMask (physical)
buf += struct.pack('<I', 0)                       # RuneCostID
buf += struct.pack('<I', 0)                       # SpellMissileID
buf += struct.pack('<I', 0)                       # PowerDisplayID
buf += struct.pack('<3f', 0.0, 0.0, 0.0)         # EffectBonusCoefficient[3]
buf += struct.pack('<I', 0)                       # DescriptionVariablesID
buf += struct.pack('<I', 0)                       # Difficulty

assert len(buf) == 936, "Record size: {} (expected 936)".format(len(buf))
spell_dbc.records.append(bytes(buf))
spell_dbc.write(spell_dbc_path)
print("Added Stoneblood spell (ID {})".format(STONEBLOOD_SPELL_ID))

# --- Step 2: Link to Dwarf racial skill line ---
add_racial_ability(DBC_DIR, 'Dwarf', STONEBLOOD_SPELL_ID)

# --- Step 3: Generate server SQL ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
sql_path = os.path.join(OUTPUT_DIR, 'racial_stoneblood.sql')
with open(sql_path, 'w') as f:
    f.write("-- Stoneblood: Dwarf racial passive - 5% armor bonus\n")
    f.write("DELETE FROM `spell_dbc` WHERE `ID` = {};\n".format(STONEBLOOD_SPELL_ID))
    f.write("INSERT INTO `spell_dbc` (`ID`, `Attributes`, `CastingTimeIndex`, "
            "`DurationIndex`, `RangeIndex`, `Effect1`, `EffectDieSides1`, "
            "`EffectBasePoints1`, `EffectImplicitTargetA1`, `EffectApplyAuraName1`, "
            "`EffectMiscValue1`, `SpellIconID`, `SpellName1`, `SchoolMask`, "
            "`Comment`) VALUES (\n")
    f.write("    {}, 64, 1, 21, 1, 6, 1, 4, 1, 142, 1, 2588, ".format(STONEBLOOD_SPELL_ID))
    f.write("'Stoneblood', 1, 'Dwarf racial - 5% armor');\n\n")
    f.write("-- Grant spell to existing Dwarf characters\n")
    f.write("-- (New characters learn it automatically via SkillLineAbility)\n")
print("Generated SQL: {}".format(sql_path))
```

---

## Common Pitfalls and Troubleshooting

### New racial does not appear on character creation
- **Cause**: The `SkillLineAbility` entry has `AcquireMethod` set to something other than 0, or the `RaceMask` does not match the character's race.
- **Fix**: Set `AcquireMethod = 0` for auto-learn on creation. Verify `RaceMask` matches the target race's bit value.

### Racial passive shows in spellbook but has no effect
- **Cause**: The spell is correctly displayed by the client (Spell.dbc works), but the server does not process the aura effect because the server's copy of Spell.dbc or `spell_dbc` table is missing the entry.
- **Fix**: Add a matching entry to the server's `spell_dbc` table, or copy the modified Spell.dbc to the server's DBC directory.

### Cannot learn racial ability that has ClassMask set
- **Cause**: The `ClassMask` in `SkillLineAbility` uses class bit positions, but the character's class does not match any set bit.
- **Fix**: Verify the class mask bits. Warrior = 0x001, Paladin = 0x002, etc. Use 0 for "all classes."

### Base stat changes do not apply
- **Cause**: `player_levelstats` changes require a server restart to take effect. The stat tables are loaded into memory at startup.
- **Fix**: Restart the worldserver after applying SQL changes.

### Tooltip shows wrong value for percentage-based racials
- **Cause**: Some aura types use `EffectBasePoints` as a flat value, others as a percentage. The tooltip `$s1` always shows `EffectBasePoints + 1`, but whether the game interprets it as flat or percent depends on the aura type.
- **Fix**: Verify the aura type. For `SPELL_AURA_MOD_BASE_RESISTANCE_PCT` (142), the value IS a percentage. For `SPELL_AURA_MOD_STAT` (29), it is a flat bonus.

---

## Cross-References

- [Add New Spell](./add_new_spell.md) - Creating the spell records for new racial abilities
- [Change Spell Data](./change_spell_data.md) - Modifying existing racial passive values
- [Modify Talent Tree](./modify_talent_tree.md) - Talents and racials share the passive aura system
- [Add New Class](./add_new_class.md) - Race-class combinations and starting equipment
