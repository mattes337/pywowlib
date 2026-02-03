# Use Case Feature Implementation Plan

Implementation roadmap for missing pywowlib features identified in
`use_cases/INDEX.md`. Organized into 4 phases by priority (number of use cases
unblocked). All DBC field layouts are derived from the authoritative `.dbd`
definitions in `wdbx/dbd/definitions/`.

**Target file:** `world_builder/dbc_injector.py` (all DBC schemas)
**Secondary files:** `world_builder/vmap_generator.py` (new), `world_builder/__init__.py` (exports)

---

## Phase 1: High Priority (unblocks 5+ use cases)

### 1.1 Spell.dbc Convenience Wrapper

**Unblocks:** #6 Add New Spell, #7 Change Spell Data, #9 Change Racial Traits,
#14 Custom Crafting Recipe, #16 Update Boss Mechanics (boss abilities)

**Source:** `wdbx/dbd/definitions/Spell.dbd` BUILD 3.3.3.11685-3.3.5.12340

**WotLK 3.3.5 Field Layout (234 fields, 936 bytes per record):**

```
Index  Field                        Type        Count  Notes
-----  ---------------------------  ----------  -----  -----
 0     ID                           uint32
 1     Category                     uint32             FK to SpellCategory.dbc
 2     DispelType                   uint32             FK to SpellDispelType.dbc
 3     Mechanic                     uint32             FK to SpellMechanic.dbc
 4     Attributes                   uint32             Base spell attributes bitmask
 5     AttributesEx                 uint32             Extended attributes A
 6     AttributesExB                uint32             Extended attributes B
 7     AttributesExC                uint32             Extended attributes C
 8     AttributesExD                uint32             Extended attributes D
 9     AttributesExE                uint32             Extended attributes E
10     AttributesExF                uint32             Extended attributes F
11     AttributesExG                uint32             Extended attributes G
12-13  ShapeshiftMask               uint32      [2]    Allowed shapeshift forms
14-15  ShapeshiftExclude            uint32      [2]    Excluded shapeshift forms
16     Targets                      uint32             Target flags bitmask
17     TargetCreatureType           uint32             Creature type bitmask
18     RequiresSpellFocus           uint32             FK to SpellFocusObject.dbc
19     FacingCasterFlags            uint32
20     CasterAuraState              uint32
21     TargetAuraState              uint32
22     ExcludeCasterAuraState       uint32
23     ExcludeTargetAuraState       uint32
24     CasterAuraSpell              uint32
25     TargetAuraSpell              uint32
26     ExcludeCasterAuraSpell       uint32
27     ExcludeTargetAuraSpell       uint32
28     CastingTimeIndex             uint32             FK to SpellCastTimes.dbc
29     RecoveryTime                 uint32             Spell cooldown (ms)
30     CategoryRecoveryTime         uint32             Category cooldown (ms)
31     InterruptFlags               uint32
32     AuraInterruptFlags           uint32
33     ChannelInterruptFlags        uint32
34     ProcTypeMask                 uint32
35     ProcChance                   uint32             0-100
36     ProcCharges                  uint32
37     MaxLevel                     uint32
38     BaseLevel                    uint32
39     SpellLevel                   uint32
40     DurationIndex                uint32             FK to SpellDuration.dbc
41     PowerType                    uint32             0=mana, 1=rage, 3=energy, 6=runic
42     ManaCost                     uint32
43     ManaCostPerLevel             uint32
44     ManaPerSecond                uint32
45     ManaPerSecondPerLevel        uint32
46     RangeIndex                   uint32             FK to SpellRange.dbc
47     Speed                        float              Projectile speed
48     ModalNextSpell               uint32
49     CumulativeAura               uint32
50-51  Totem                        uint32      [2]    Required totem items
52-59  Reagent                      uint32      [8]    Required reagent item IDs
60-67  ReagentCount                 uint32      [8]    Reagent quantities
68     EquippedItemClass            uint32
69     EquippedItemSubclass         uint32
70     EquippedItemInvTypes         uint32
71-73  Effect                       uint32      [3]    Spell effect type per slot
74-76  EffectDieSides               uint32      [3]
77-79  EffectRealPointsPerLevel     float       [3]
80-82  EffectBasePoints             uint32      [3]    Base damage/healing
83-85  EffectMechanic               uint32      [3]    Per-effect mechanic
86-88  ImplicitTargetA              uint32      [3]    Primary target type
89-91  ImplicitTargetB              uint32      [3]    Secondary target type
92-94  EffectRadiusIndex            uint32      [3]    FK to SpellRadius.dbc
95-97  EffectAura                   uint32      [3]    Aura type
98-100 EffectAuraPeriod             uint32      [3]    Tick interval (ms)
101-103 EffectAmplitude             float       [3]
104-106 EffectChainTargets          uint32      [3]
107-109 EffectItemType              uint32      [3]    Created item ID
110-112 EffectMiscValue             uint32      [3]
113-115 EffectMiscValueB            uint32      [3]
116-118 EffectTriggerSpell          uint32      [3]    Triggered spell ID
119-121 EffectPointsPerCombo        float       [3]
122-130 EffectSpellClassMask{A,B,C} uint32      [3]x3  9 fields total
131-132 SpellVisualID               uint32      [2]    FK to SpellVisual.dbc
133    SpellIconID                  uint32             FK to SpellIcon.dbc
134    ActiveIconID                 uint32
135    SpellPriority                uint32
136-152 Name_lang                   locstr      17     Spell name
153-169 NameSubtext_lang            locstr      17     Rank/subtext
170-186 Description_lang            locstr      17     Tooltip text
187-203 AuraDescription_lang        locstr      17     Buff tooltip
204    ManaCostPct                  uint32
205    StartRecoveryCategory        uint32
206    StartRecoveryTime            uint32             GCD (ms)
207    MaxTargetLevel               uint32
208    SpellClassSet                uint32
209-211 SpellClassMask              uint32      [3]
212    MaxTargets                   uint32
213    DefenseType                  uint32
214    PreventionType               uint32
215    StanceBarOrder               uint32
216-218 EffectChainAmplitude        float       [3]
219    MinFactionID                 uint32
220    MinReputation                uint32
221    RequiredAuraVision           uint32
222-223 RequiredTotemCategoryID     uint32      [2]
224    RequiredAreasID              uint32
225    SchoolMask                   uint32             1=phys,2=holy,4=fire,8=nature,16=frost,32=shadow,64=arcane
226    RuneCostID                   uint32
227    SpellMissileID               uint32
228    PowerDisplayID               uint32
229-231 EffectBonusCoefficient      float       [3]
232    DescriptionVariablesID       uint32
233    Difficulty                   uint32
```

**Constants:**
```python
_SPELL_FIELD_COUNT = 234
_SPELL_RECORD_SIZE = _SPELL_FIELD_COUNT * 4  # 936
```

**Implementation approach:** Given the 234-field complexity, provide a `register_spell`
wrapper that accepts a **spell definition dict** with named keys for the commonly-used
fields, defaulting all others to 0. This avoids a function with 234 parameters.

**Public API:**
```python
def register_spell(
    dbc_dir,
    name,
    spell_id=None,
    # Core mechanics
    school_mask=0x01,        # 1=physical
    cast_time_index=1,       # instant
    duration_index=0,        # instant
    range_index=0,           # self
    power_type=0,            # mana
    mana_cost=0,
    cooldown=0,              # RecoveryTime (ms)
    gcd=1500,                # StartRecoveryTime (ms)
    # Effect slot 1
    effect_1=0,              # SPELL_EFFECT type
    effect_1_base_points=0,
    effect_1_aura=0,         # SPELL_AURA type
    effect_1_target_a=0,
    effect_1_target_b=0,
    effect_1_radius_index=0,
    effect_1_trigger_spell=0,
    effect_1_item_type=0,
    effect_1_misc_value=0,
    # Effect slots 2-3 (same pattern)
    effect_2=0, effect_2_base_points=0, ...
    effect_3=0, effect_3_base_points=0, ...
    # Visuals
    spell_icon_id=1,
    spell_visual_id=0,
    # Text
    name_subtext=None,       # Rank text
    description=None,        # Tooltip
    aura_description=None,   # Buff tooltip
    # Advanced (rarely needed)
    attributes=0,
    attributes_ex=0,
    category=0,
    mechanic=0,
    # Full override
    **kwargs,                # Any field by name
):
    """Register a new spell in Spell.dbc. Returns assigned spell_id."""
```

**Record builder:** `_build_spell_record()` constructs 936 bytes from the dict,
using the field layout above. All 234 fields have sensible defaults (0 for most
uint32, 0.0 for floats, empty locstrings).

**Modification helper:**
```python
def modify_spell(dbc_dir, spell_id, **changes):
    """Modify fields of an existing spell record by field name."""
```

This reads the existing record, applies field-level changes by name->offset
mapping, and writes back. Enables use case #7 (Change Spell Data).

---

### 1.2 SkillLineAbility.dbc Convenience Wrapper

**Unblocks:** #6 Add New Spell (auto-learn), #9 Change Racial Traits, #14 Custom Crafting Recipe

**Source:** `wdbx/dbd/definitions/SkillLineAbility.dbd` BUILD 3.0.1.8788-3.3.5.12340

**WotLK 3.3.5 Field Layout (14 fields, 56 bytes per record):**

```
Index  Field                        Type     Notes
-----  ---------------------------  -------  -----
 0     ID                           uint32
 1     SkillLine                    uint32   FK to SkillLine.dbc (e.g. 8=Fishing, 164=Blacksmithing)
 2     Spell                        uint32   FK to Spell.dbc
 3     RaceMask                     uint32   Bitmask (0=all races)
 4     ClassMask                    uint32   Bitmask (0=all classes)
 5     ExcludeRace                  uint32   Excluded race bitmask
 6     ExcludeClass                 uint32   Excluded class bitmask
 7     MinSkillLineRank             uint32   Min skill level to learn
 8     SupercededBySpell            uint32   Higher rank replaces this
 9     AcquireMethod                uint32   0=trainer, 1=auto on skill, 2=item
10     TrivialSkillLineRankHigh     uint32   Orange→Yellow threshold
11     TrivialSkillLineRankLow      uint32   Yellow→Green threshold
12-13  CharacterPoints              uint32   [2]  Talent points (usually 0)
```

**Constants:**
```python
_SKILLLINEABILITY_FIELD_COUNT = 14
_SKILLLINEABILITY_RECORD_SIZE = _SKILLLINEABILITY_FIELD_COUNT * 4  # 56
```

**Public API:**
```python
def register_skill_line_ability(
    dbc_dir,
    skill_line,
    spell_id,
    ability_id=None,
    race_mask=0,
    class_mask=0,
    min_skill_rank=0,
    superceded_by=0,
    acquire_method=1,        # 1=auto on skill learn
    trivial_high=0,
    trivial_low=0,
):
    """Register a spell in a skill line (profession, racial, etc.). Returns ability ID."""
```

---

### 1.3 VMap/MMap Subprocess Integration

**Unblocks:** #1 Add New Zone, #2 Add New Dungeon (server-side collision and pathing)

**New file:** `world_builder/vmap_generator.py`

**Pattern:** Follow `mpq_packer.py` optional dependency pattern.

**Implementation:**

```python
# world_builder/vmap_generator.py

import os
import subprocess
import logging
import shutil

log = logging.getLogger(__name__)

def find_tool(tool_name, search_dirs=None):
    """
    Locate a server tool executable (vmap4extractor, vmap4assembler, mmaps_generator).
    Searches: search_dirs, PATH, common locations.
    Returns path or None.
    """

def generate_vmaps(wow_data_dir, output_dir, map_name=None, tools_dir=None):
    """
    Run vmap4extractor + vmap4assembler to generate server collision data.

    Args:
        wow_data_dir: Path to WoW Data/ directory (containing MPQ files).
        output_dir: Where to write vmaps/ output.
        map_name: Optional specific map to extract (None=all maps).
        tools_dir: Optional path to directory containing vmap tools.

    Returns:
        str: Path to vmaps/ directory, or None if tools unavailable.

    Raises:
        FileNotFoundError: If wow_data_dir doesn't exist.
        RuntimeError: If extraction fails (non-zero exit code).
    """

def generate_mmaps(vmaps_dir, output_dir, map_id=None, tools_dir=None):
    """
    Run mmaps_generator to generate server pathfinding meshes.
    Requires vmaps to be generated first.

    Args:
        vmaps_dir: Path to vmaps/ from generate_vmaps().
        output_dir: Where to write mmaps/ output.
        map_id: Optional specific map ID (None=all maps).
        tools_dir: Optional path to directory containing mmap tools.

    Returns:
        str: Path to mmaps/ directory, or None if tools unavailable.
    """

def generate_server_data(wow_data_dir, output_dir, map_name=None, map_id=None,
                         tools_dir=None):
    """
    Convenience: run both vmap and mmap generation in sequence.
    Skips gracefully if tools are not found (logs warning).
    """
```

**Integration points:**
- Add `generate_server_data` call as optional post-step in `build_zone()` / `build_dungeon()`
- Accept `server_tools_dir` parameter in high-level APIs
- Add `vmap_validator.py` to `validators/` for checking output

**Error handling:** Follow `_HAS_STORM_CREATE` pattern -- try to find tools, log warning
if unavailable, skip gracefully. Never fail the build pipeline if server tools are missing.

---

## Phase 2: Medium Priority (unblocks 2-3 use cases each)

### 2.1 Item.dbc Convenience Wrapper

**Unblocks:** #11 Add New Item, #14 Custom Crafting Recipe

**Source:** `wdbx/dbd/definitions/Item.dbd` BUILD 3.0.2.9056-3.3.5.12340

**WotLK 3.3.5 Field Layout (8 fields, 32 bytes per record):**

```
Index  Field                        Type     Notes
-----  ---------------------------  -------  -----
 0     ID                           uint32
 1     ClassID                      uint32   Item class (0=consumable, 2=weapon, 4=armor)
 2     SubclassID                   uint32   Subclass within class
 3     Sound_override_subclassID    uint32   Usually -1 (0xFFFFFFFF)
 4     Material                     uint32   0=undefined, 1=metal, 2=wood, 3=liquid, etc.
 5     DisplayInfoID                uint32   FK to ItemDisplayInfo.dbc
 6     InventoryType                uint32   0=non-equip, 1=head, 5=chest, 13=one-hand, etc.
 7     SheatheType                  uint32   0=none, 1=2h-weapon, 2=staff, 3=1h-left, etc.
```

**Constants:**
```python
_ITEM_FIELD_COUNT = 8
_ITEM_RECORD_SIZE = _ITEM_FIELD_COUNT * 4  # 32
```

**Public API:**
```python
def register_item(
    dbc_dir,
    item_id=None,
    class_id=0,
    subclass_id=0,
    material=0,
    display_info_id=0,
    inventory_type=0,
    sheathe_type=0,
    sound_override=-1,
):
    """Register a new item in Item.dbc. Returns assigned item ID."""
```

---

### 2.2 ItemSet.dbc Convenience Wrapper

**Unblocks:** #12 Create Item Set

**Source:** `wdbx/dbd/definitions/ItemSet.dbd` BUILD 3.0.1.8303-3.3.5.12340

**WotLK 3.3.5 Field Layout (46 fields, 184 bytes per record):**

```
Index  Field                        Type       Count  Notes
-----  ---------------------------  ---------  -----  -----
 0     ID                           uint32
 1-17  Name_lang                    locstr     17     Set name
18-34  ItemID                       uint32     [17]   Item IDs in set (0=unused)
35-42  SetSpellID                   uint32     [8]    Bonus spell IDs
43-50  SetThreshold                 uint32     [8]    Piece count for each bonus
51     RequiredSkill                uint32     FK to SkillLine.dbc (0=none)
52     RequiredSkillRank            uint32     Required skill level
```

**Constants:**
```python
_ITEMSET_FIELD_COUNT = 53  # 1 + 17 + 17 + 8 + 8 + 1 + 1
_ITEMSET_RECORD_SIZE = _ITEMSET_FIELD_COUNT * 4  # 212
```

Note: ID(1) + locstring(17) + ItemID[17] + SetSpellID[8] + SetThreshold[8] +
RequiredSkill(1) + RequiredSkillRank(1) = 53 fields.

**Public API:**
```python
def register_item_set(
    dbc_dir,
    name,
    item_ids,             # list of up to 17 item IDs
    bonuses=None,         # list of (threshold, spell_id) tuples
    set_id=None,
    required_skill=0,
    required_skill_rank=0,
):
    """Register a new item set in ItemSet.dbc. Returns assigned set ID."""
```

---

### 2.3 SoundEntries.dbc Convenience Wrapper

**Unblocks:** #4 Add Custom Music

**Source:** `wdbx/dbd/definitions/SoundEntries.dbd` BUILD 3.0.1.8303-3.0.9.9551
(applies to 3.3.5 as well based on the pre-3.1.0 layout being the base)

Note: The 3.1.0-3.3.5 layout adds `SoundEntriesAdvancedID` compared to the base.

**WotLK 3.3.5 Field Layout (BUILD 3.1.0.9767-3.3.5.12340):**

```
Index  Field                        Type     Count  Notes
-----  ---------------------------  -------  -----  -----
 0     ID                           uint32
 1     SoundType                    uint32          1=spell, 2=ambient, 6=zone music, etc.
 2     Name                         string          Internal name
 3-12  File                         string   [10]   Up to 10 sound file paths
13-22  Freq                         uint32   [10]   Playback frequency weights
23     DirectoryBase                string          Base path for files
24     VolumeFloat                  float           Volume multiplier (0.0-1.0)
25     Flags                        uint32          Playback flags
26     MinDistance                   float           Min audible distance
27     DistanceCutoff                float           Max audible distance
28     EAXDef                       uint32          Environment audio preset
29     SoundEntriesAdvancedID       uint32          FK to SoundEntriesAdvanced.dbc
```

Note: This has string fields (not just uint32), so record_size varies. The DBC
format stores string offsets as uint32, so we count all as uint32 fields:
ID(1) + SoundType(1) + Name(1) + File[10] + Freq[10] + DirectoryBase(1) +
VolumeFloat(1) + Flags(1) + MinDistance(1) + DistanceCutoff(1) + EAXDef(1) +
SoundEntriesAdvancedID(1) = 30 fields.

**Constants:**
```python
_SOUNDENTRIES_FIELD_COUNT = 30
_SOUNDENTRIES_RECORD_SIZE = _SOUNDENTRIES_FIELD_COUNT * 4  # 120
```

**Public API:**
```python
def register_sound_entry(
    dbc_dir,
    name,
    sound_type,           # 1=spell, 2=ambient, 6=zone_music, 50=zone_ambience
    files,                # list of up to 10 filename strings
    directory_base="",    # base directory path
    sound_id=None,
    volume=1.0,
    min_distance=8.0,
    max_distance=45.0,
    flags=0,
    frequencies=None,     # list of weights per file (default: equal)
):
    """Register a new sound entry in SoundEntries.dbc. Returns assigned sound ID."""
```

---

### 2.4 CreatureDisplayInfo.dbc Convenience Wrapper

**Unblocks:** #15 Add New Creature (custom models)

**Source:** `wdbx/dbd/definitions/CreatureDisplayInfo.dbd` BUILD 3.0.1.8820-3.3.5.12340

**WotLK 3.3.5 Field Layout:**

```
Index  Field                        Type     Count  Notes
-----  ---------------------------  -------  -----  -----
 0     ID                           uint32
 1     ModelID                      uint32          FK to CreatureModelData.dbc
 2     SoundID                      uint32          FK to CreatureSoundData.dbc
 3     ExtendedDisplayInfoID        uint32          FK to CreatureDisplayInfoExtra.dbc
 4     CreatureModelScale           float           Model scale multiplier
 5     CreatureModelAlpha           uint32          Transparency (255=opaque)
 6-8   TextureVariation             string   [3]    Up to 3 texture override paths
 9     PortraitTextureName          string          Portrait texture path
10     SizeClass                    uint32          1=small, 2=medium, 3=large, etc.
11     BloodID                      uint32          Blood splash type
12     NPCSoundID                   uint32          FK to NPCSounds.dbc
13     ParticleColorID              uint32          FK to ParticleColor.dbc
14     CreatureGeosetData           uint32          Geoset flags
15     ObjectEffectPackageID        uint32          FK to ObjectEffectPackage.dbc
```

String fields (TextureVariation[3] + PortraitTextureName) are stored as uint32
offsets. Total fields: 16 uint32/float values = 64 bytes.

**Constants:**
```python
_CREATUREDISPLAYINFO_FIELD_COUNT = 16
_CREATUREDISPLAYINFO_RECORD_SIZE = _CREATUREDISPLAYINFO_FIELD_COUNT * 4  # 64
```

**Public API:**
```python
def register_creature_display(
    dbc_dir,
    model_id,
    display_id=None,
    sound_id=0,
    scale=1.0,
    alpha=255,
    textures=None,         # list of up to 3 texture paths
    portrait_texture=None,
    size_class=2,          # medium
    blood_id=0,
):
    """Register creature display info. Returns assigned display ID."""
```

---

### 2.5 CreatureModelData.dbc Convenience Wrapper

**Unblocks:** #15 Add New Creature (custom models, paired with 2.4)

**Source:** `wdbx/dbd/definitions/CreatureModelData.dbd`

The WotLK 3.3.5 layout needs to be extracted from the .dbd file. Based on
the general structure and the 6.0.1 layout, the WotLK version has these
commonly used fields:

```
Index  Field                        Type     Notes
-----  ---------------------------  -------  -----
 0     ID                           uint32
 1     Flags                        uint32
 2     ModelName                    string   Path to .m2 file
 3     SizeClass                    uint32
 4     ModelScale                   float
 5     BloodID                      uint32
 6     FootprintTextureID           uint32
 7     FootprintTextureLength       float
 8     FootprintTextureWidth        float
 9     FootprintParticleScale       float
10     FoleyMaterialID              uint32
11     FootstepShakeSize            uint32
12     DeathThudShakeSize           uint32
13     SoundID                      uint32
14     CollisionWidth               float
15     CollisionHeight              float
16     MountHeight                  float
17-19  GeoBoxMin                    float    [3]  Bounding box min (x,y,z)
20-22  GeoBoxMax                    float    [3]  Bounding box max (x,y,z)
23     WorldEffectScale             float
24     AttachedEffectScale          float
25     MissileCollisionRadius       float
26     MissileCollisionPush         float
27     MissileCollisionRaise        float
```

Note: Exact WotLK field count TBD from binary inspection. The convenience
wrapper will focus on the essential fields (ID, Flags, ModelName, scale,
collision, bounding box) with remaining fields defaulting to 0.

**Public API:**
```python
def register_creature_model(
    dbc_dir,
    model_path,             # e.g. "Creature\\FelOrc\\FelOrc.m2"
    model_id=None,
    collision_width=0.5,
    collision_height=2.0,
    model_scale=1.0,
    bounding_box=None,      # ((min_x,min_y,min_z), (max_x,max_y,max_z))
):
    """Register creature model data. Returns assigned model ID."""
```

---

### 2.6 Talent.dbc + TalentTab.dbc Convenience Wrappers

**Unblocks:** #8 Modify Talent Tree

**Source (Talent):** `wdbx/dbd/definitions/Talent.dbd` BUILD 3.0.1.8622-3.3.5.12340

**Talent.dbc WotLK 3.3.5 Field Layout (21 fields, 84 bytes per record):**

```
Index  Field                        Type     Count  Notes
-----  ---------------------------  -------  -----  -----
 0     ID                           uint32
 1     TabID                        uint32          FK to TalentTab.dbc
 2     TierID                       uint32          Row (0-10)
 3     ColumnIndex                  uint32          Column (0-3)
 4-12  SpellRank                    uint32   [9]    Spell ID per rank (0=unused)
13-15  PrereqTalent                 uint32   [3]    Prerequisite talent IDs (0=none)
16-18  PrereqRank                   uint32   [3]    Required rank of prereqs
19     Flags                        uint32
20     RequiredSpellID              uint32          Required spell to learn
21-22  CategoryMask                 uint32   [2]
```

Note: The exact WotLK count from the .dbd: ID(1) + TabID(1) + TierID(1) +
ColumnIndex(1) + SpellRank[9] + PrereqTalent[3] + PrereqRank[3] + Flags(1) +
RequiredSpellID(1) + CategoryMask[2] = 23 fields = 92 bytes.

**Constants:**
```python
_TALENT_FIELD_COUNT = 23
_TALENT_RECORD_SIZE = _TALENT_FIELD_COUNT * 4  # 92
```

**Source (TalentTab):** `wdbx/dbd/definitions/TalentTab.dbd` BUILD 3.0.1.8622-3.3.5.12340

**TalentTab.dbc WotLK 3.3.5 Field Layout:**

```
Index  Field                        Type     Count  Notes
-----  ---------------------------  -------  -----  -----
 0     ID                           uint32
 1-17  Name_lang                    locstr   17     Tab name (e.g. "Fire")
18     SpellIconID                  uint32          FK to SpellIcon.dbc
19     RaceMask                     uint32          0=all races
20     ClassMask                    uint32          Class bitmask (1=warrior, 2=paladin, etc.)
21     CategoryEnumID               uint32          Tab category
22     OrderIndex                   uint32          Display order (0, 1, 2)
23     BackgroundFile               string          Tab background texture path
```

Total: ID(1) + locstring(17) + 5 uint32 + 1 string = 24 fields = 96 bytes.

**Constants:**
```python
_TALENTTAB_FIELD_COUNT = 24
_TALENTTAB_RECORD_SIZE = _TALENTTAB_FIELD_COUNT * 4  # 96
```

**Public APIs:**
```python
def register_talent_tab(
    dbc_dir,
    name,
    class_mask,
    tab_id=None,
    spell_icon_id=1,
    order_index=0,
    background_file=None,
    race_mask=0,
):
    """Register a new talent tab. Returns assigned tab ID."""

def register_talent(
    dbc_dir,
    tab_id,
    tier,
    column,
    spell_ranks,           # list of up to 9 spell IDs (1 per rank)
    talent_id=None,
    prereq_talents=None,   # list of up to 3 (talent_id, required_rank) tuples
    required_spell_id=0,
):
    """Register a talent in a tab. Returns assigned talent ID."""
```

---

## Phase 3: Low Priority (nice to have)

### 3.1 SpellIcon.dbc Convenience Wrapper

**Unblocks:** #6 Add New Spell (icon assignment)

**Source:** `wdbx/dbd/definitions/SpellIcon.dbd` (all builds)

**Field Layout (2 fields, 8 bytes per record):**

```
Index  Field                        Type     Notes
-----  ---------------------------  -------  -----
 0     ID                           uint32
 1     TextureFilename              string   Icon texture path
```

**Public API:**
```python
def register_spell_icon(dbc_dir, texture_path, icon_id=None):
    """Register a spell icon. Returns assigned icon ID."""
```

---

### 3.2 GameObjectDisplayInfo.dbc Convenience Wrapper

**Unblocks:** #21 Add Object Interaction (custom display models)

Field layout TBD from `wdbx/dbd/definitions/GameObjectDisplayInfo.dbd`. Based on
community documentation, WotLK has: ID, FileDataID/ModelName, Sound[10],
GeoBoxMin[3], GeoBoxMax[3].

**Public API:**
```python
def register_gameobject_display(dbc_dir, model_path, display_id=None,
                                 bounding_box=None):
    """Register a gameobject display. Returns assigned display ID."""
```

---

### 3.3 ZoneIntroMusicTable.dbc Convenience Wrapper

**Unblocks:** #4 Add Custom Music (entrance stinger)

Small DBC with fields: ID, Name, SoundID, Priority, MinDelayMinutes.

**Public API:**
```python
def register_zone_intro_music(dbc_dir, name, sound_id, intro_id=None,
                               priority=0, min_delay=0):
    """Register a zone intro music stinger. Returns assigned ID."""
```

---

### 3.4 ADT Doodad/WMO Insertion API

**Unblocks:** #3 Update Zone Scenery (programmatic object placement)

**File:** `world_builder/adt_composer.py`

Currently `create_adt()` generates empty `MDDF`/`MODF` chunks. Add functions to
insert doodad and WMO references into existing ADT data:

```python
def add_doodad_to_adt(adt_bytes, m2_path, position, rotation=(0,0,0), scale=1.0):
    """Insert a doodad (.m2) placement into ADT binary data.
    Returns modified ADT bytes."""

def add_wmo_to_adt(adt_bytes, wmo_path, position, rotation=(0,0,0)):
    """Insert a WMO placement into ADT binary data.
    Returns modified ADT bytes."""
```

This modifies the `MMDX`/`MMID`/`MDDF` chunks (for M2 doodads) and
`MWMO`/`MWID`/`MODF` chunks (for WMO buildings) in the ADT binary.

---

## Phase 4: Nice to Have

### 4.1 AddOn Scaffold Generator

**Unblocks:** #24 Custom UI Frame

**New file:** `world_builder/addon_generator.py`

Generate WoW 3.3.5 AddOn boilerplate:

```python
def generate_addon(
    name,
    output_dir,
    title=None,
    description=None,
    frames=None,            # list of frame definitions
    events=None,            # list of event handlers
    slash_commands=None,     # list of /command definitions
    saved_variables=None,   # list of saved variable names
):
    """Generate a complete WoW 3.3.5 AddOn (TOC + Lua + XML).
    Returns dict with paths to generated files."""
```

Output structure:
```
{output_dir}/{name}/
  {name}.toc
  {name}.lua
  {name}.xml (optional, only if frames defined)
```

---

### 4.2 ChrRaces.dbc + CharStartOutfit.dbc (Reskin Support)

**Unblocks:** #23 Add Playable Race (reskin approach only)

For race reskinning (e.g., Blood Elf -> High Elf) without C++ core changes.
These schemas are large and complex, so implementation is deferred.

---

## Implementation Order

```
Phase 1 (do first, highest impact):
  1.1 Spell.dbc          → dbc_injector.py  (new schema + register + modify)
  1.2 SkillLineAbility   → dbc_injector.py  (new schema + register)
  1.3 VMap/MMap           → vmap_generator.py (new file)

Phase 2 (do second):
  2.1 Item.dbc            → dbc_injector.py  (new schema + register)
  2.2 ItemSet.dbc         → dbc_injector.py  (new schema + register)
  2.3 SoundEntries.dbc    → dbc_injector.py  (new schema + register)
  2.4 CreatureDisplayInfo → dbc_injector.py  (new schema + register)
  2.5 CreatureModelData   → dbc_injector.py  (new schema + register)
  2.6 Talent + TalentTab  → dbc_injector.py  (new schema + register x2)

Phase 3 (do third):
  3.1 SpellIcon.dbc       → dbc_injector.py  (new schema + register)
  3.2 GameObjectDisplayInfo → dbc_injector.py (new schema + register)
  3.3 ZoneIntroMusicTable → dbc_injector.py  (new schema + register)
  3.4 ADT doodad/WMO API  → adt_composer.py  (new functions)

Phase 4 (optional):
  4.1 AddOn scaffold      → addon_generator.py (new file)
  4.2 ChrRaces reskin     → dbc_injector.py  (deferred)
```

## Files Modified Per Phase

| Phase | File | Change |
|-------|------|--------|
| 1 | `world_builder/dbc_injector.py` | Add Spell.dbc + SkillLineAbility.dbc schemas (~600 lines) |
| 1 | `world_builder/vmap_generator.py` | New file (~200 lines) |
| 1 | `world_builder/__init__.py` | Export new register functions + vmap |
| 2 | `world_builder/dbc_injector.py` | Add 6 DBC schemas (~800 lines) |
| 2 | `world_builder/__init__.py` | Export new register functions |
| 3 | `world_builder/dbc_injector.py` | Add 3 DBC schemas (~200 lines) |
| 3 | `world_builder/adt_composer.py` | Add doodad/WMO insertion (~150 lines) |
| 4 | `world_builder/addon_generator.py` | New file (~300 lines) |

## Dependencies Between Features

```
1.1 Spell.dbc ──────┐
                     ├── 1.2 SkillLineAbility (references Spell IDs)
                     ├── 2.2 ItemSet.dbc (bonus spells reference Spell IDs)
                     └── 2.6 Talent.dbc (spell ranks reference Spell IDs)

2.5 CreatureModelData ── 2.4 CreatureDisplayInfo (references ModelID)

3.1 SpellIcon.dbc ────── 1.1 Spell.dbc (SpellIconID field)
```

Phases 1 and 2 are ordered so that dependencies flow forward. Spell.dbc should
be implemented first since multiple later features reference spell IDs.

## Verification

After each phase, verify by:

1. **Unit test:** Read an existing retail DBC, inject a new record, write, re-read,
   confirm the new record is present with correct field values.
2. **Round-trip test:** Create a new DBC from scratch, add records, write to disk,
   read back, verify field-by-field.
3. **Integration test (Phase 1.3):** If server tools are available, run
   `generate_server_data()` on test output from `build_zone()` and verify vmaps/mmaps
   directories are created.
4. **Cross-reference test:** Register a spell, then register a SkillLineAbility
   referencing it. Verify both DBCs contain consistent IDs.
