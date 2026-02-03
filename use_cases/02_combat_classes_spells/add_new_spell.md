# Add New Spell

**Complexity**: Advanced |
**DBC Files**: Spell.dbc, SpellIcon.dbc, SpellVisual.dbc |
**SQL Tables**: spell_dbc, spell_linked_spell, spell_bonus_data |
**pywowlib Modules**: `world_builder.dbc_injector.DBCInjector`, `world_builder.spell_registry.SpellRegistry`

---

## Overview

Adding a completely new spell to WoW WotLK 3.3.5a (build 12340) is one of the most involved modding tasks because it requires coordinated changes across both the client DBC files and the server database. The client uses Spell.dbc to render tooltips, icons, cast bars, and visual effects, while the server uses its own `spell_dbc` table (or equivalent) to validate mechanics, calculate damage, and enforce cooldowns.

A custom spell must exist in both places with matching IDs and compatible data. If the client has a spell record that the server does not recognize, casting will fail silently. If the server has a spell the client lacks, the player sees no tooltip, no icon, and no cast bar animation.

This guide walks through the entire process: reserving a safe custom spell ID, creating SpellIcon and SpellVisual entries, constructing the 234-field Spell.dbc binary record, registering the spell through SpellRegistry for project-wide tracking, and configuring the server-side SQL entries.

---

## Prerequisites

- A working WoW 3.3.5a client installation with access to the `DBFilesClient` directory
- An AzerothCore (or TrinityCore) server with a functioning `world` database
- Python 3.6+ with pywowlib installed or available on `PYTHONPATH`
- The stock `Spell.dbc`, `SpellIcon.dbc`, and `SpellVisual.dbc` extracted from the client MPQ files
- Familiarity with DBC binary layout concepts (see `dbc_injector.py` header comments)

---

## Step 1: Understand the Spell.dbc Field Layout (WotLK 3.3.5a)

The WotLK 3.3.5a Spell.dbc is one of the largest DBC files in the game. Based on the authoritative `.dbd` definition file shipped with pywowlib (at `wdbx/dbd/definitions/Spell.dbd`), the layout for builds `3.3.3.11685` through `3.3.5.12340` contains the following fields. Every field is a 32-bit value (uint32, int32, or float32) unless otherwise noted. Localized strings (locstring) occupy 17 consecutive uint32 fields (8 locale slots + 8 unused + 1 mask).

```
Index   Field Name                      Type        Count   Notes
------  ------------------------------  ----------  ------  ---------------------------
  0     ID                              uint32      1       Primary key
  1     Category                        uint32      1       SpellCategory.dbc FK
  2     DispelType                      uint32      1       SpellDispelType.dbc FK
  3     Mechanic                        uint32      1       SpellMechanic.dbc FK
  4     Attributes                      uint32      1       Base attribute flags
  5     AttributesEx                    uint32      1       Extended flags 1
  6     AttributesExB                   uint32      1       Extended flags 2
  7     AttributesExC                   uint32      1       Extended flags 3
  8     AttributesExD                   uint32      1       Extended flags 4
  9     AttributesExE                   uint32      1       Extended flags 5
 10     AttributesExF                   uint32      1       Extended flags 6
 11     AttributesExG                   uint32      1       Extended flags 7
 12-13  ShapeshiftMask                  uint32      [2]     Allowed shapeshift forms
 14-15  ShapeshiftExclude               uint32      [2]     Excluded shapeshift forms
 16     Targets                         uint32      1       Target type mask
 17     TargetCreatureType              uint32      1       Required creature type
 18     RequiresSpellFocus              uint32      1       SpellFocusObject.dbc FK
 19     FacingCasterFlags               uint32      1       Must face caster?
 20     CasterAuraState                 uint32      1       Required caster aura state
 21     TargetAuraState                 uint32      1       Required target aura state
 22     ExcludeCasterAuraState          uint32      1       Excluded caster aura state
 23     ExcludeTargetAuraState          uint32      1       Excluded target aura state
 24     CasterAuraSpell                 uint32      1       Required caster aura spell
 25     TargetAuraSpell                 uint32      1       Required target aura spell
 26     ExcludeCasterAuraSpell          uint32      1       Excluded caster aura spell
 27     ExcludeTargetAuraSpell          uint32      1       Excluded target aura spell
 28     CastingTimeIndex                uint32      1       SpellCastTimes.dbc FK
 29     RecoveryTime                    uint32      1       Spell cooldown (ms)
 30     CategoryRecoveryTime            uint32      1       Category cooldown (ms)
 31     InterruptFlags                  uint32      1       What interrupts the cast
 32     AuraInterruptFlags              uint32      1       What removes the aura
 33     ChannelInterruptFlags           uint32      1       What interrupts channel
 34     ProcTypeMask                    uint32      1       Proc trigger conditions
 35     ProcChance                      uint32      1       Proc chance (0-100)
 36     ProcCharges                     uint32      1       Max proc charges
 37     MaxLevel                        uint32      1       Max effective level
 38     BaseLevel                       uint32      1       Base level for scaling
 39     SpellLevel                      uint32      1       Required caster level
 40     DurationIndex                   uint32      1       SpellDuration.dbc FK
 41     PowerType                       uint32      1       0=mana, 1=rage, 3=energy...
 42     ManaCost                        uint32      1       Base mana cost
 43     ManaCostPerLevel                uint32      1       Additional cost per level
 44     ManaPerSecond                   uint32      1       Channeled mana per second
 45     ManaPerSecondPerLevel           uint32      1       Channel cost per level
 46     RangeIndex                      uint32      1       SpellRange.dbc FK
 47     Speed                           float       1       Projectile speed (if any)
 48     ModalNextSpell                  uint32      1       Next spell in sequence
 49     CumulativeAura                  uint32      1       Stack count
 50-51  Totem[2]                        uint32      [2]     Required totem items
 52-59  Reagent[8]                      uint32      [8]     Required reagent item IDs
 60-67  ReagentCount[8]                 uint32      [8]     Required reagent counts
 68     EquippedItemClass               uint32      1       Required equipped item class
 69     EquippedItemSubclass            uint32      1       Required equipped subclass
 70     EquippedItemInvTypes            uint32      1       Required inventory types
 71-73  Effect[3]                       uint32      [3]     Spell effect types
 74-76  EffectDieSides[3]               uint32      [3]     Die sides for random roll
 77-79  EffectRealPointsPerLevel[3]     float       [3]     Points scaling per level
 80-82  EffectBasePoints[3]             int32       [3]     Base points (value - 1)
 83-85  EffectMechanic[3]               uint32      [3]     Per-effect mechanic
 86-88  ImplicitTargetA[3]              uint32      [3]     Primary target type
 89-91  ImplicitTargetB[3]              uint32      [3]     Secondary target type
 92-94  EffectRadiusIndex[3]            uint32      [3]     SpellRadius.dbc FK
 95-97  EffectAura[3]                   uint32      [3]     Aura type for APPLY_AURA
 98-100 EffectAuraPeriod[3]             uint32      [3]     Periodic tick interval (ms)
101-103 EffectAmplitude[3]              float       [3]     Effect amplitude
104-106 EffectChainTargets[3]           uint32      [3]     Chain target count
107-109 EffectItemType[3]               uint32      [3]     Created item ID
110-112 EffectMiscValue[3]              int32       [3]     Misc value (school, etc.)
113-115 EffectMiscValueB[3]             int32       [3]     Misc value B
116-118 EffectTriggerSpell[3]           uint32      [3]     Triggered spell ID
119-121 EffectPointsPerCombo[3]         float       [3]     Points per combo point
122-124 EffectSpellClassMaskA[3]        uint32      [3]     Class mask A
125-127 EffectSpellClassMaskB[3]        uint32      [3]     Class mask B
128-130 EffectSpellClassMaskC[3]        uint32      [3]     Class mask C
131-132 SpellVisualID[2]                uint32      [2]     SpellVisual.dbc FK (2 slots)
133     SpellIconID                     uint32      1       SpellIcon.dbc FK
134     ActiveIconID                    uint32      1       Active spell icon FK
135     SpellPriority                   uint32      1       Priority for auto-cast
136-152 Name_lang                       locstring   17      Spell name (localized)
153-169 NameSubtext_lang                locstring   17      Rank/subtext (localized)
170-186 Description_lang                locstring   17      Tooltip description
187-203 AuraDescription_lang            locstring   17      Aura/buff description
204     ManaCostPct                     uint32      1       Mana cost as percentage
205     StartRecoveryCategory           uint32      1       GCD category
206     StartRecoveryTime               uint32      1       GCD duration (ms)
207     MaxTargetLevel                  uint32      1       Max target level
208     SpellClassSet                   uint32      1       Class family (3=mage, etc.)
209-211 SpellClassMask[3]               uint32      [3]     Class-specific mask
212     MaxTargets                      uint32      1       Maximum targets
213     DefenseType                     uint32      1       0=none, 1=magic, 2=melee
214     PreventionType                  uint32      1       0=none, 1=silence, 2=pacify
215     StanceBarOrder                  uint32      1       Position on stance bar
216-218 EffectChainAmplitude[3]         float       [3]     Chain damage multiplier
219     MinFactionID                    uint32      1       Required faction FK
220     MinReputation                   uint32      1       Required reputation level
221     RequiredAuraVision              uint32      1       Required aura vision
222-223 RequiredTotemCategoryID[2]      uint32      [2]     Required totem categories
224     RequiredAreasID                 uint32      1       AreaGroup.dbc FK
225     SchoolMask                      uint32      1       Damage school bitmask
226     RuneCostID                      uint32      1       SpellRuneCost.dbc FK (DK)
227     SpellMissileID                  uint32      1       SpellMissile.dbc FK
228     PowerDisplayID                  uint32      1       Alternate power display
229-231 EffectBonusCoefficient[3]       float       [3]     Spell power coefficients
232     DescriptionVariablesID          uint32      1       Description variable FK
233     Difficulty                      uint32      1       Difficulty flags

Total: 234 DBC fields = 936 bytes per record
```

**Critical locstring note**: In WotLK 3.3.5a, each locstring occupies 17 uint32 fields. Only the first slot (index 0, enUS) is typically populated. The last field (index 16) is a locale flags mask set to `0xFFFFFFFF`. All other slots are zero.

---

## Step 2: Plan the Custom Spell ID Range

Blizzard's stock Spell.dbc for 3.3.5a contains spell IDs up to approximately 80865. To avoid conflicts with existing spells and with other mods, pywowlib's `SpellRegistry` defaults to the 90000+ range for custom spells.

**Recommended ID ranges:**

| Range         | Purpose                               |
|---------------|---------------------------------------|
| 1 - 80865     | Stock WoW 3.3.5a spells (DO NOT USE)  |
| 80866 - 89999 | Buffer zone (avoid)                   |
| 90000 - 90999 | pywowlib custom spells (default)      |
| 91000 - 99999 | Extended custom range                 |
| 100000+       | Large-scale custom content            |

```python
from world_builder.spell_registry import SpellRegistry

# Initialize the registry. All custom spells start at 90000 by default.
registry = SpellRegistry(base_spell_id=90000)
```

---

## Step 3: Create a SpellIcon Entry

Every spell needs an icon. The icon is defined in `SpellIcon.dbc`, which has the simplest possible layout:

```
Index   Field               Type      Notes
------  ------------------  --------  ---------------------------------
  0     ID                  uint32    Primary key
  1     TextureFilename     string    Path in client (e.g. "Interface\\Icons\\Spell_Fire_Fireball02")
```

Record size: 2 fields = 8 bytes. The TextureFilename is a string offset into the DBC string block.

**Important**: The TextureFilename path must NOT include the `.blp` extension. The client appends it automatically. The path uses backslashes and is relative to the game's data root.

```python
import struct
from world_builder.dbc_injector import DBCInjector

def add_spell_icon(dbc_dir, icon_path, icon_id=None):
    """
    Add a new SpellIcon entry to SpellIcon.dbc.

    Args:
        dbc_dir: Directory containing SpellIcon.dbc.
        icon_path: Icon texture path WITHOUT .blp extension.
                   Example: "Interface\\Icons\\INV_Custom_Sword"
        icon_id: Explicit ID or None for auto-assignment.

    Returns:
        int: The assigned SpellIcon ID.
    """
    import os
    filepath = os.path.join(dbc_dir, 'SpellIcon.dbc')
    dbc = DBCInjector(filepath)

    if icon_id is None:
        icon_id = dbc.get_max_id() + 1

    # Add the texture path string to the string block
    texture_offset = dbc.add_string(icon_path)

    # SpellIcon.dbc: 2 fields, 8 bytes per record
    record = struct.pack('<II', icon_id, texture_offset)

    dbc.records.append(record)
    dbc.write(filepath)

    print("Added SpellIcon ID {} -> {}".format(icon_id, icon_path))
    return icon_id


# Usage:
DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"

custom_icon_id = add_spell_icon(
    DBC_DIR,
    "Interface\\Icons\\Spell_Shadow_ShadowBolt"  # reuse existing icon texture
)
```

**Reusing existing icons**: If you do not need a custom icon texture, you can skip creating a new SpellIcon entry entirely and reuse an existing SpellIcon ID. Common useful IDs from stock 3.3.5a:

| SpellIcon ID | Texture                                        | Description           |
|-------------|------------------------------------------------|-----------------------|
| 1           | Interface\\Icons\\Spell_Fire_Fireball02        | Fireball              |
| 46          | Interface\\Icons\\Spell_Shadow_ShadowBolt      | Shadow Bolt           |
| 70          | Interface\\Icons\\Spell_Holy_HolyBolt          | Holy Light            |
| 260         | Interface\\Icons\\Spell_Nature_Lightning        | Lightning Bolt        |
| 15          | Interface\\Icons\\Spell_Frost_FrostBolt02       | Frostbolt             |

---

## Step 4: Create a SpellVisual Entry

SpellVisual.dbc controls the visual effects played during casting, impact, and channeling. For WotLK 3.3.5a (builds 3.2.0-3.3.5), the layout is:

```
Index   Field                        Type      Notes
------  ---------------------------  --------  ----------------------------
  0     ID                           uint32    Primary key
  1     PrecastKit                   uint32    Visual kit during precast
  2     CastKit                      uint32    Visual kit during casting
  3     ImpactKit                    uint32    Visual kit on impact
  4     StateKit                     uint32    Visual kit for persistent state
  5     StateDoneKit                 uint32    Visual kit when state ends
  6     ChannelKit                   uint32    Visual kit during channeling
  7     HasMissile                   uint32    1 if spell has a missile
  8     MissileModel                 uint32    Missile model FK
  9     MissilePathType              uint32    Missile trajectory type
 10     MissileDestinationAttachment uint32    Attachment point for impact
 11     MissileSound                 uint32    Sound on missile fire
 12     AnimEventSoundID             uint32    Animation event sound
 13     Flags                        uint32    Visual flags
 14     CasterImpactKit              uint32    Impact effect on caster
 15     TargetImpactKit              uint32    Impact effect on target
 16     MissileAttachment            uint32    Missile launch attachment
 17     MissileFollowGroundHeight    uint32    Missile ground follow height
 18     MissileFollowGroundDropSpeed uint32    Missile drop speed
 19     MissileFollowGroundApproach  uint32    Missile approach behavior
 20     MissileFollowGroundFlags     uint32    Missile ground flags
 21     MissileMotion                uint32    Missile motion type
 22     MissileTargetingKit          uint32    Targeting visual kit
 23     InstantAreaKit               uint32    Instant area effect kit
 24     ImpactAreaKit                uint32    Impact area effect kit
 25     PersistentAreaKit            uint32    Persistent area effect kit
 26-28  MissileCastOffset[3]         float     Missile launch offset (x,y,z)
 29-31  MissileImpactOffset[3]       float     Missile impact offset (x,y,z)

Total: 32 fields = 128 bytes per record
```

**Important**: Creating custom visual kits (PrecastKit, CastKit, etc.) requires editing SpellVisualKit.dbc, SpellVisualKitModelAttach.dbc, and potentially SpellVisualEffectName.dbc. This is an extremely deep rabbit hole. For most custom spells, the recommended approach is to **reuse an existing SpellVisual ID** from a stock spell that has similar visual characteristics.

```python
def add_spell_visual(dbc_dir, visual_id=None,
                     precast_kit=0, cast_kit=0, impact_kit=0,
                     state_kit=0, channel_kit=0,
                     has_missile=0, missile_model=0):
    """
    Add a new SpellVisual entry to SpellVisual.dbc.
    Most fields default to 0 (no effect). For custom spells,
    it is usually better to reuse an existing SpellVisual ID.

    Args:
        dbc_dir: Directory containing SpellVisual.dbc.
        visual_id: Explicit ID or None for auto-assignment.
        precast_kit: SpellVisualKit ID for precast phase.
        cast_kit: SpellVisualKit ID for cast phase.
        impact_kit: SpellVisualKit ID for impact phase.
        state_kit: SpellVisualKit ID for persistent state.
        channel_kit: SpellVisualKit ID for channeling.
        has_missile: 1 if spell fires a projectile.
        missile_model: Model FK for the missile visual.

    Returns:
        int: The assigned SpellVisual ID.
    """
    import os
    filepath = os.path.join(dbc_dir, 'SpellVisual.dbc')
    dbc = DBCInjector(filepath)

    if visual_id is None:
        visual_id = dbc.get_max_id() + 1

    # 32 fields, 128 bytes per record (WotLK 3.2.0 - 3.3.5)
    # Fields: ID, PrecastKit, CastKit, ImpactKit, StateKit, StateDoneKit,
    #         ChannelKit, HasMissile, MissileModel, MissilePathType,
    #         MissileDestinationAttachment, MissileSound, AnimEventSoundID,
    #         Flags, CasterImpactKit, TargetImpactKit, MissileAttachment,
    #         MissileFollowGroundHeight, MissileFollowGroundDropSpeed,
    #         MissileFollowGroundApproach, MissileFollowGroundFlags,
    #         MissileMotion, MissileTargetingKit, InstantAreaKit,
    #         ImpactAreaKit, PersistentAreaKit,
    #         MissileCastOffset[3] (float), MissileImpactOffset[3] (float)
    record = struct.pack(
        '<26I6f',
        visual_id,
        precast_kit,        # PrecastKit
        cast_kit,           # CastKit
        impact_kit,         # ImpactKit
        state_kit,          # StateKit
        0,                  # StateDoneKit
        channel_kit,        # ChannelKit
        has_missile,        # HasMissile
        missile_model,      # MissileModel
        0,                  # MissilePathType
        0,                  # MissileDestinationAttachment
        0,                  # MissileSound
        0,                  # AnimEventSoundID
        0,                  # Flags
        0,                  # CasterImpactKit
        0,                  # TargetImpactKit
        0,                  # MissileAttachment
        0,                  # MissileFollowGroundHeight
        0,                  # MissileFollowGroundDropSpeed
        0,                  # MissileFollowGroundApproach
        0,                  # MissileFollowGroundFlags
        0,                  # MissileMotion
        0,                  # MissileTargetingKit
        0,                  # InstantAreaKit
        0,                  # ImpactAreaKit
        0,                  # PersistentAreaKit
        0.0, 0.0, 0.0,     # MissileCastOffset[3]
        0.0, 0.0, 0.0,     # MissileImpactOffset[3]
    )

    dbc.records.append(record)
    dbc.write(filepath)

    print("Added SpellVisual ID {}".format(visual_id))
    return visual_id


# Commonly reused SpellVisual IDs from stock 3.3.5a:
# 47    = Shadow Bolt visual (purple projectile)
# 13    = Fireball visual (orange projectile + explosion)
# 64    = Frostbolt visual (blue projectile)
# 340   = Holy Light visual (golden glow)
# 2917  = Chain Lightning visual (bouncing electricity)
```

---

## Step 5: Register the Spell in SpellRegistry

Before creating the actual DBC record, register the spell in the project's `SpellRegistry`. This ensures a unique ID, provides Lua constant export for addon development, and prevents ID collisions across your project.

```python
from world_builder.spell_registry import SpellRegistry

registry = SpellRegistry(base_spell_id=90000)

# Register a completely new custom spell
storm_bolt_id = registry.register_spell(
    spell_name='SPELL_STORM_BOLT',
    description='Hurls a bolt of storm energy, dealing 500 Nature damage',
    spell_data={
        'school': 'nature',
        'damage_min': 450,
        'damage_max': 550,
        'cast_time': 2000,    # 2 seconds
        'cooldown': 6000,     # 6 seconds
        'range': 30,          # 30 yards
        'mana_cost': 200,
    },
    boss_label='Custom Spells',
)
print("Storm Bolt assigned ID: {}".format(storm_bolt_id))  # 90000

# Register a spell that reuses an existing WoW spell ID
# (for borrowing visuals/mechanics from the stock game)
frostbolt_id = registry.register_spell(
    spell_name='SPELL_FROSTBOLT_REUSE',
    existing_spell_id=116,  # stock Frostbolt Rank 1
    description='Reused Frostbolt for NPC casting',
    boss_label='Boss 1',
)

# Register with an explicit custom ID (skipping auto-increment)
custom_id = registry.register_spell(
    spell_name='SPELL_VOID_ERUPTION',
    custom_spell_id=90050,
    description='Eruption of void energy in a 10-yard radius',
    spell_data={
        'school': 'shadow',
        'damage_min': 800,
        'damage_max': 1000,
        'radius': 10,
    },
    boss_label='Custom Spells',
)

# Resolve an ID later by name
resolved = registry.resolve_spell_id('SPELL_STORM_BOLT')
print("Resolved: {}".format(resolved))  # 90000

# Export for Lua addon development
registry.export_lua_constants('output/spell_constants.lua')

# Export JSON for documentation and tooling
registry.export_json_config('output/spell_config.json')
```

---

## Step 6: Build the Spell.dbc Record

This is the core step. You must construct a 936-byte binary record containing all 234 fields. The helper function below packs locstrings correctly and sets the most important fields for a basic direct-damage spell.

```python
import struct
import os
from world_builder.dbc_injector import DBCInjector

# Locstring packing: 17 uint32 values (8 locale slots + 8 unused + 1 mask)
# Only enUS (slot 0) is set. Mask (slot 16) = 0xFFFFFFFF.
_LOC_SLOTS = 17

def pack_locstring(string_offset):
    """Pack a WotLK locstring from a string block offset."""
    values = [0] * _LOC_SLOTS
    values[0] = string_offset   # enUS
    values[16] = 0xFFFFFFFF     # locale mask
    return struct.pack('<{}I'.format(_LOC_SLOTS), *values)


def build_spell_record(dbc, spell_id, name, description,
                       aura_description='',
                       rank_text='',
                       school_mask=0x01,
                       mana_cost=0,
                       cast_time_index=1,
                       range_index=1,
                       cooldown=0,
                       duration_index=0,
                       effect_type=2,
                       effect_base_points=0,
                       effect_die_sides=0,
                       implicit_target_a=6,
                       implicit_target_b=0,
                       spell_icon_id=1,
                       spell_visual_id=0,
                       attributes=0,
                       attributes_ex=0,
                       spell_level=1,
                       base_level=1,
                       max_level=0,
                       gcd=1500,
                       defense_type=0,
                       prevention_type=0,
                       power_type=0,
                       proc_chance=0,
                       proc_charges=0,
                       proc_type_mask=0,
                       effect_aura=0,
                       effect_aura_period=0,
                       effect_radius_index=0,
                       effect_misc_value=0,
                       effect_trigger_spell=0,
                       speed=0.0,
                       bonus_coefficient=0.0):
    """
    Build a complete 936-byte Spell.dbc record for WotLK 3.3.5a.

    Args:
        dbc: DBCInjector instance (for string block operations).
        spell_id: Unique spell ID.
        name: Spell display name (English).
        description: Tooltip description (English). Use $s1 for effect value.
        aura_description: Buff/aura tooltip description.
        rank_text: Rank subtext (e.g. "Rank 1").
        school_mask: Damage school bitmask (1=physical, 2=holy, 4=fire,
                     8=nature, 16=frost, 32=shadow, 64=arcane).
        mana_cost: Base mana cost.
        cast_time_index: FK to SpellCastTimes.dbc.
                         1 = instant, 4 = 1.5s, 5 = 2.0s, 14 = 2.5s, 15 = 3.0s.
        range_index: FK to SpellRange.dbc.
                     1 = self, 2 = 5yd (melee), 4 = 30yd, 5 = 40yd, 6 = 100yd.
        cooldown: Spell cooldown in milliseconds.
        duration_index: FK to SpellDuration.dbc.
                        0 = instant, 1 = 10s, 3 = 30s, 4 = 60s, 21 = 5min.
        effect_type: Primary effect type.
                     2 = SCHOOL_DAMAGE, 3 = DUMMY, 6 = APPLY_AURA,
                     10 = HEAL, 24 = ENERGIZE, 28 = SUMMON, 36 = LEARN_SPELL.
        effect_base_points: Base effect value (actual displayed value minus 1).
        effect_die_sides: Random variance (0 for fixed values).
        implicit_target_a: Primary target. 1=self, 6=enemy, 21=friend, 22=AoE(enemy).
        implicit_target_b: Secondary target type.
        spell_icon_id: SpellIcon.dbc FK.
        spell_visual_id: SpellVisual.dbc FK.
        attributes: Base attribute flags.
        attributes_ex: Extended attribute flags.
        spell_level: Required level to cast.
        base_level: Base level for scaling calculations.
        max_level: Maximum level for scaling (0 = no cap).
        gcd: Global cooldown in milliseconds (1500 = standard).
        defense_type: 0=none, 1=magic, 2=melee, 3=ranged.
        prevention_type: 0=none, 1=silence, 2=pacify.
        power_type: 0=mana, 1=rage, 2=focus, 3=energy, 6=runic power.
        proc_chance: Proc chance percentage (0-100).
        proc_charges: Number of proc charges.
        proc_type_mask: Proc trigger type bitmask.
        effect_aura: Aura type (for APPLY_AURA effect).
        effect_aura_period: Periodic tick interval in ms (for periodic auras).
        effect_radius_index: SpellRadius.dbc FK (for AoE spells).
        effect_misc_value: Misc value (school for SCHOOL_DAMAGE, etc.).
        effect_trigger_spell: Triggered spell ID (for TRIGGER_SPELL effect).
        speed: Projectile speed in yards/second (0 for instant).
        bonus_coefficient: Spell power scaling coefficient.

    Returns:
        bytes: 936-byte binary record.
    """
    buf = bytearray()

    # Add strings to the DBC string block
    name_offset = dbc.add_string(name)
    rank_offset = dbc.add_string(rank_text)
    desc_offset = dbc.add_string(description)
    aura_offset = dbc.add_string(aura_description)

    # Field 0: ID
    buf += struct.pack('<I', spell_id)
    # Field 1: Category
    buf += struct.pack('<I', 0)
    # Field 2: DispelType (0=none, 1=magic, 2=curse, 3=disease, 4=poison)
    buf += struct.pack('<I', 0)
    # Field 3: Mechanic (0=none)
    buf += struct.pack('<I', 0)
    # Field 4: Attributes
    buf += struct.pack('<I', attributes)
    # Field 5: AttributesEx
    buf += struct.pack('<I', attributes_ex)
    # Fields 6-11: AttributesExB through AttributesExG
    buf += struct.pack('<6I', 0, 0, 0, 0, 0, 0)
    # Fields 12-13: ShapeshiftMask[2]
    buf += struct.pack('<2I', 0, 0)
    # Fields 14-15: ShapeshiftExclude[2]
    buf += struct.pack('<2I', 0, 0)
    # Field 16: Targets
    buf += struct.pack('<I', 0)
    # Field 17: TargetCreatureType
    buf += struct.pack('<I', 0)
    # Field 18: RequiresSpellFocus
    buf += struct.pack('<I', 0)
    # Field 19: FacingCasterFlags
    buf += struct.pack('<I', 0)
    # Fields 20-23: Aura state requirements
    buf += struct.pack('<4I', 0, 0, 0, 0)
    # Fields 24-27: Aura spell requirements
    buf += struct.pack('<4I', 0, 0, 0, 0)
    # Field 28: CastingTimeIndex
    buf += struct.pack('<I', cast_time_index)
    # Field 29: RecoveryTime (cooldown in ms)
    buf += struct.pack('<I', cooldown)
    # Field 30: CategoryRecoveryTime
    buf += struct.pack('<I', 0)
    # Field 31: InterruptFlags
    buf += struct.pack('<I', 0x0F if cast_time_index > 1 else 0)
    # Field 32: AuraInterruptFlags
    buf += struct.pack('<I', 0)
    # Field 33: ChannelInterruptFlags
    buf += struct.pack('<I', 0)
    # Field 34: ProcTypeMask
    buf += struct.pack('<I', proc_type_mask)
    # Field 35: ProcChance
    buf += struct.pack('<I', proc_chance)
    # Field 36: ProcCharges
    buf += struct.pack('<I', proc_charges)
    # Field 37: MaxLevel
    buf += struct.pack('<I', max_level)
    # Field 38: BaseLevel
    buf += struct.pack('<I', base_level)
    # Field 39: SpellLevel
    buf += struct.pack('<I', spell_level)
    # Field 40: DurationIndex
    buf += struct.pack('<I', duration_index)
    # Field 41: PowerType
    buf += struct.pack('<I', power_type)
    # Field 42: ManaCost
    buf += struct.pack('<I', mana_cost)
    # Field 43: ManaCostPerLevel
    buf += struct.pack('<I', 0)
    # Field 44: ManaPerSecond
    buf += struct.pack('<I', 0)
    # Field 45: ManaPerSecondPerLevel
    buf += struct.pack('<I', 0)
    # Field 46: RangeIndex
    buf += struct.pack('<I', range_index)
    # Field 47: Speed (float)
    buf += struct.pack('<f', speed)
    # Field 48: ModalNextSpell
    buf += struct.pack('<I', 0)
    # Field 49: CumulativeAura
    buf += struct.pack('<I', 0)
    # Fields 50-51: Totem[2]
    buf += struct.pack('<2I', 0, 0)
    # Fields 52-59: Reagent[8]
    buf += struct.pack('<8I', 0, 0, 0, 0, 0, 0, 0, 0)
    # Fields 60-67: ReagentCount[8]
    buf += struct.pack('<8I', 0, 0, 0, 0, 0, 0, 0, 0)
    # Field 68: EquippedItemClass (-1 = any)
    buf += struct.pack('<i', -1)
    # Field 69: EquippedItemSubclass
    buf += struct.pack('<I', 0)
    # Field 70: EquippedItemInvTypes
    buf += struct.pack('<I', 0)

    # Fields 71-73: Effect[3]
    buf += struct.pack('<3I', effect_type, 0, 0)
    # Fields 74-76: EffectDieSides[3]
    buf += struct.pack('<3I', effect_die_sides, 0, 0)
    # Fields 77-79: EffectRealPointsPerLevel[3] (float)
    buf += struct.pack('<3f', 0.0, 0.0, 0.0)
    # Fields 80-82: EffectBasePoints[3] (signed)
    buf += struct.pack('<3i', effect_base_points, 0, 0)
    # Fields 83-85: EffectMechanic[3]
    buf += struct.pack('<3I', 0, 0, 0)
    # Fields 86-88: ImplicitTargetA[3]
    buf += struct.pack('<3I', implicit_target_a, 0, 0)
    # Fields 89-91: ImplicitTargetB[3]
    buf += struct.pack('<3I', implicit_target_b, 0, 0)
    # Fields 92-94: EffectRadiusIndex[3]
    buf += struct.pack('<3I', effect_radius_index, 0, 0)
    # Fields 95-97: EffectAura[3]
    buf += struct.pack('<3I', effect_aura, 0, 0)
    # Fields 98-100: EffectAuraPeriod[3]
    buf += struct.pack('<3I', effect_aura_period, 0, 0)
    # Fields 101-103: EffectAmplitude[3] (float)
    buf += struct.pack('<3f', 0.0, 0.0, 0.0)
    # Fields 104-106: EffectChainTargets[3]
    buf += struct.pack('<3I', 0, 0, 0)
    # Fields 107-109: EffectItemType[3]
    buf += struct.pack('<3I', 0, 0, 0)
    # Fields 110-112: EffectMiscValue[3] (signed)
    buf += struct.pack('<3i', effect_misc_value, 0, 0)
    # Fields 113-115: EffectMiscValueB[3] (signed)
    buf += struct.pack('<3i', 0, 0, 0)
    # Fields 116-118: EffectTriggerSpell[3]
    buf += struct.pack('<3I', effect_trigger_spell, 0, 0)
    # Fields 119-121: EffectPointsPerCombo[3] (float)
    buf += struct.pack('<3f', 0.0, 0.0, 0.0)
    # Fields 122-130: EffectSpellClassMask A/B/C [3] each
    buf += struct.pack('<9I', 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # Fields 131-132: SpellVisualID[2]
    buf += struct.pack('<2I', spell_visual_id, 0)
    # Field 133: SpellIconID
    buf += struct.pack('<I', spell_icon_id)
    # Field 134: ActiveIconID
    buf += struct.pack('<I', 0)
    # Field 135: SpellPriority
    buf += struct.pack('<I', 0)

    # Fields 136-152: Name_lang (locstring, 17 uint32)
    buf += pack_locstring(name_offset)
    # Fields 153-169: NameSubtext_lang (locstring, 17 uint32)
    buf += pack_locstring(rank_offset)
    # Fields 170-186: Description_lang (locstring, 17 uint32)
    buf += pack_locstring(desc_offset)
    # Fields 187-203: AuraDescription_lang (locstring, 17 uint32)
    buf += pack_locstring(aura_offset)

    # Field 204: ManaCostPct
    buf += struct.pack('<I', 0)
    # Field 205: StartRecoveryCategory
    buf += struct.pack('<I', 133 if gcd > 0 else 0)
    # Field 206: StartRecoveryTime (GCD in ms)
    buf += struct.pack('<I', gcd)
    # Field 207: MaxTargetLevel
    buf += struct.pack('<I', 0)
    # Field 208: SpellClassSet
    buf += struct.pack('<I', 0)
    # Fields 209-211: SpellClassMask[3]
    buf += struct.pack('<3I', 0, 0, 0)
    # Field 212: MaxTargets
    buf += struct.pack('<I', 0)
    # Field 213: DefenseType
    buf += struct.pack('<I', defense_type)
    # Field 214: PreventionType
    buf += struct.pack('<I', prevention_type)
    # Field 215: StanceBarOrder
    buf += struct.pack('<I', 0)
    # Fields 216-218: EffectChainAmplitude[3] (float)
    buf += struct.pack('<3f', 0.0, 0.0, 0.0)
    # Field 219: MinFactionID
    buf += struct.pack('<I', 0)
    # Field 220: MinReputation
    buf += struct.pack('<I', 0)
    # Field 221: RequiredAuraVision
    buf += struct.pack('<I', 0)
    # Fields 222-223: RequiredTotemCategoryID[2]
    buf += struct.pack('<2I', 0, 0)
    # Field 224: RequiredAreasID
    buf += struct.pack('<I', 0)
    # Field 225: SchoolMask
    buf += struct.pack('<I', school_mask)
    # Field 226: RuneCostID
    buf += struct.pack('<I', 0)
    # Field 227: SpellMissileID
    buf += struct.pack('<I', 0)
    # Field 228: PowerDisplayID
    buf += struct.pack('<I', 0)
    # Fields 229-231: EffectBonusCoefficient[3] (float)
    buf += struct.pack('<3f', bonus_coefficient, 0.0, 0.0)
    # Field 232: DescriptionVariablesID
    buf += struct.pack('<I', 0)
    # Field 233: Difficulty
    buf += struct.pack('<I', 0)

    record = bytes(buf)
    expected_size = 234 * 4  # 936 bytes
    assert len(record) == expected_size, (
        "Spell record size mismatch: expected {}, got {}".format(
            expected_size, len(record))
    )
    return record
```

---

## Step 7: Inject the Spell Record into Spell.dbc

```python
def add_custom_spell(dbc_dir, spell_id, name, description, **kwargs):
    """
    Full pipeline: inject a new spell into Spell.dbc.

    Args:
        dbc_dir: Path to DBFilesClient directory.
        spell_id: The spell ID (from SpellRegistry).
        name: Spell display name.
        description: Tooltip text. Use $s1 for effect value placeholder.
        **kwargs: Additional parameters passed to build_spell_record.

    Returns:
        int: The spell ID.
    """
    filepath = os.path.join(dbc_dir, 'Spell.dbc')
    dbc = DBCInjector(filepath)

    # Verify the DBC structure matches WotLK 3.3.5a
    assert dbc.record_size == 936, (
        "Unexpected Spell.dbc record size: {} (expected 936 for WotLK 3.3.5a)".format(
            dbc.record_size)
    )

    # Check for ID collision
    for rec in dbc.records:
        existing_id = struct.unpack_from('<I', rec, 0)[0]
        if existing_id == spell_id:
            print("WARNING: Spell ID {} already exists, skipping".format(spell_id))
            return spell_id

    record = build_spell_record(
        dbc, spell_id, name, description, **kwargs
    )

    dbc.records.append(record)
    dbc.write(filepath)

    print("Injected spell '{}' (ID {}) into Spell.dbc".format(name, spell_id))
    return spell_id


# --- Full Example: Add "Storm Bolt" ---
DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"

from world_builder.spell_registry import SpellRegistry

registry = SpellRegistry(base_spell_id=90000)

# Step A: Register in the project
storm_id = registry.register_spell(
    spell_name='SPELL_STORM_BOLT',
    description='Hurls a bolt of storm energy, dealing $s1 Nature damage.',
    spell_data={'school': 'nature', 'damage': 500, 'cast_time': 2000},
    boss_label='Custom Encounter',
)

# Step B: Inject into Spell.dbc
add_custom_spell(
    dbc_dir=DBC_DIR,
    spell_id=storm_id,
    name="Storm Bolt",
    description="Hurls a bolt of storm energy, dealing $s1 Nature damage.",
    school_mask=0x08,               # Nature = 8
    mana_cost=200,
    cast_time_index=5,              # 2.0 second cast
    range_index=4,                  # 30 yards
    cooldown=6000,                  # 6 second cooldown
    effect_type=2,                  # SCHOOL_DAMAGE
    effect_base_points=499,         # Displays as 500 (base + 1)
    effect_die_sides=1,             # 500 to 500 (base+1 to base+die_sides)
    implicit_target_a=6,            # TARGET_UNIT_TARGET_ENEMY
    spell_icon_id=260,              # Lightning Bolt icon
    spell_visual_id=2917,           # Chain Lightning visual (reused)
    defense_type=1,                 # Magic
    prevention_type=1,              # Silence prevents cast
    speed=24.0,                     # Projectile speed
    bonus_coefficient=0.7143,       # ~71.4% spell power coefficient
)

# Step C: Export spell constants for addon use
registry.export_lua_constants('output/custom_spell_constants.lua')
```

---

## Step 8: Server-Side SQL Configuration

The client DBC record handles tooltips and visuals, but the server needs its own spell data to actually process the spell mechanically. On AzerothCore, the server reads from the `spell_dbc` table for custom spells.

### 8.1 - The spell_dbc Table

```sql
-- ============================================================
-- Server-side spell definition for Storm Bolt (ID 90000)
-- This table mirrors key Spell.dbc fields for the server core.
-- ============================================================
DELETE FROM `spell_dbc` WHERE `ID` = 90000;
INSERT INTO `spell_dbc` (
    `ID`, `Category`, `DispelType`, `Mechanic`,
    `Attributes`, `AttributesEx`, `AttributesEx2`, `AttributesEx3`,
    `AttributesEx4`, `AttributesEx5`, `AttributesEx6`, `AttributesEx7`,
    `CastingTimeIndex`, `RecoveryTime`, `CategoryRecoveryTime`,
    `InterruptFlags`, `AuraInterruptFlags`, `ChannelInterruptFlags`,
    `ProcFlags`, `ProcChance`, `ProcCharges`,
    `MaxLevel`, `BaseLevel`, `SpellLevel`,
    `DurationIndex`, `PowerType`, `ManaCost`,
    `RangeIndex`, `Speed`, `StackAmount`,
    `Effect1`, `Effect2`, `Effect3`,
    `EffectDieSides1`, `EffectDieSides2`, `EffectDieSides3`,
    `EffectBasePoints1`, `EffectBasePoints2`, `EffectBasePoints3`,
    `EffectImplicitTargetA1`, `EffectImplicitTargetA2`, `EffectImplicitTargetA3`,
    `EffectImplicitTargetB1`, `EffectImplicitTargetB2`, `EffectImplicitTargetB3`,
    `EffectRadiusIndex1`, `EffectRadiusIndex2`, `EffectRadiusIndex3`,
    `EffectApplyAuraName1`, `EffectApplyAuraName2`, `EffectApplyAuraName3`,
    `EffectAmplitude1`, `EffectAmplitude2`, `EffectAmplitude3`,
    `EffectMiscValue1`, `EffectMiscValue2`, `EffectMiscValue3`,
    `EffectTriggerSpell1`, `EffectTriggerSpell2`, `EffectTriggerSpell3`,
    `SpellIconID`, `SpellName1`, `SchoolMask`,
    `Comment`
) VALUES (
    90000, 0, 0, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
    5, 6000, 0,       -- CastTimeIndex=5 (2s), 6s cooldown
    15, 0, 0,          -- InterruptFlags (movement+pushback+interrupt)
    0, 0, 0,
    0, 1, 1,           -- BaseLevel=1, SpellLevel=1
    0, 0, 200,         -- No duration, Mana power, 200 mana cost
    4, 24.0, 0,        -- RangeIndex=4 (30yd), Speed=24
    2, 0, 0,           -- Effect1=SCHOOL_DAMAGE
    1, 0, 0,           -- DieSides1=1
    499, 0, 0,         -- BasePoints1=499 (displays 500)
    6, 0, 0,           -- TargetA1=TARGET_UNIT_TARGET_ENEMY
    0, 0, 0,           -- No secondary targets
    0, 0, 0,           -- No radius
    0, 0, 0,           -- No aura
    0, 0, 0,           -- No amplitude
    0, 0, 0,           -- No misc value
    0, 0, 0,           -- No trigger spells
    260, 'Storm Bolt', 8,  -- Icon, Name, SchoolMask=Nature
    'Custom spell: Storm Bolt - Nature damage projectile'
);
```

### 8.2 - spell_bonus_data (Spell Power Scaling)

```sql
-- Spell power coefficient for Storm Bolt
DELETE FROM `spell_bonus_data` WHERE `entry` = 90000;
INSERT INTO `spell_bonus_data` (`entry`, `direct_bonus`, `dot_bonus`,
    `ap_bonus`, `ap_dot_bonus`, `comments`)
VALUES (90000, 0.7143, 0, 0, 0, 'Storm Bolt - 71.43% SP coefficient');
```

### 8.3 - spell_linked_spell (Linked Effects)

If your custom spell should trigger another spell on hit (e.g., applying a debuff):

```sql
-- When Storm Bolt (90000) hits, also apply Storm Weakness debuff (90001)
DELETE FROM `spell_linked_spell` WHERE `spell_trigger` = 90000;
INSERT INTO `spell_linked_spell` (`spell_trigger`, `spell_effect`, `type`, `comment`)
VALUES (90000, 90001, 0, 'Storm Bolt -> apply Storm Weakness debuff');
-- type: 0 = on cast, 1 = on hit, 2 = on aura apply, 3 = on aura remove
```

### 8.4 - spell_custom_attr (Custom Attributes)

```sql
-- Mark spell as unresistable binary spell
DELETE FROM `spell_custom_attr` WHERE `entry` = 90000;
INSERT INTO `spell_custom_attr` (`entry`, `attributes`)
VALUES (90000, 0x00000000);
-- Attribute flags:
--   0x00000001 = SPELL_ATTR0_CU_ENCHANT_PROC
--   0x00000002 = SPELL_ATTR0_CU_CONE_BACK
--   0x00000004 = SPELL_ATTR0_CU_CONE_LINE
--   0x00000100 = SPELL_ATTR0_CU_SHARE_DAMAGE
--   0x00001000 = SPELL_ATTR0_CU_NO_PVP_FLAG
```

---

## Step 9: Client-Server Synchronization

The most critical aspect of custom spells is keeping the client and server in sync.

### What the client controls (Spell.dbc):
- Spell name, description, and tooltip text
- Icon display (SpellIconID)
- Cast bar animation and visual effects (SpellVisualID)
- Tooltip variable substitution ($s1, $d, etc.)
- Range display in tooltip
- Cast time display
- Cooldown display
- Mana cost display

### What the server controls (spell_dbc / core):
- Actual damage calculation
- Mana cost enforcement
- Cooldown enforcement
- Range validation
- Target validation
- Effect processing (damage, heal, aura, etc.)
- Spell power scaling (spell_bonus_data)

### Synchronization rules:
1. **ID must match exactly** between client Spell.dbc and server `spell_dbc`.
2. **ManaCost**: Client uses it for tooltip display; server enforces it. They must match.
3. **CastingTimeIndex**: Client animates the cast bar; server validates cast duration. Must match.
4. **RangeIndex**: Client shows range in tooltip; server does range checks. Must match.
5. **RecoveryTime**: Client greys out the action button; server blocks re-casting. Must match.
6. **EffectBasePoints**: Client shows `$s1` in tooltip (base_points + 1); server uses same for damage. Must match.
7. **SchoolMask**: Client colors the damage numbers; server classifies for resistances. Must match.

**Tooltip variable substitution**: The `$s1` token in Description_lang is replaced by `EffectBasePoints[0] + 1`. Use `$s2` for effect 2, `$s3` for effect 3. `$d` shows the duration. `$o1` shows total periodic damage. `$t1` shows the tick interval.

---

## Step 10: Complete Working Example

Here is a complete self-contained script that adds a custom spell end-to-end:

```python
"""
Complete example: Add a custom "Arcane Barrage" spell (ID 90010).
Instant cast, 3-second cooldown, deals 600-800 Arcane damage.
"""
import struct
import os
from world_builder.dbc_injector import DBCInjector
from world_builder.spell_registry import SpellRegistry

DBC_DIR = "C:/Games/WoW335/Data/DBFilesClient"
OUTPUT_DIR = "output"

# --- 1. Registry ---
registry = SpellRegistry(base_spell_id=90010)
spell_id = registry.register_spell(
    spell_name='SPELL_ARCANE_BARRAGE_CUSTOM',
    description='Launches bolts of arcane energy at the enemy target, '
                'causing $s1 Arcane damage.',
    spell_data={'school': 'arcane', 'damage_min': 600, 'damage_max': 800},
    boss_label='Custom NPC Spells',
)
print("Registered spell ID: {}".format(spell_id))

# --- 2. Inject into Spell.dbc ---
spell_dbc_path = os.path.join(DBC_DIR, 'Spell.dbc')
dbc = DBCInjector(spell_dbc_path)

record = build_spell_record(
    dbc=dbc,
    spell_id=spell_id,
    name="Arcane Barrage",
    description="Launches bolts of arcane energy at the enemy target, "
                "causing $s1 Arcane damage.",
    rank_text="",
    school_mask=0x40,               # Arcane = 64
    mana_cost=0,                    # NPC spell, no mana cost displayed
    cast_time_index=1,              # Instant cast
    range_index=4,                  # 30 yards
    cooldown=3000,                  # 3 second cooldown
    effect_type=2,                  # SCHOOL_DAMAGE
    effect_base_points=599,         # Displays as 600
    effect_die_sides=201,           # 600 to 800 (599+1 to 599+201)
    implicit_target_a=6,            # TARGET_UNIT_TARGET_ENEMY
    spell_icon_id=2271,             # Arcane Barrage icon (stock)
    spell_visual_id=11244,          # Arcane Barrage visual (stock)
    defense_type=1,                 # Magic defense
    prevention_type=1,              # Silence prevents
    gcd=1500,                       # Standard GCD
    bonus_coefficient=0.7143,
)

dbc.records.append(record)
dbc.write(spell_dbc_path)
print("Injected into Spell.dbc")

# --- 3. Export constants ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
registry.export_lua_constants(os.path.join(OUTPUT_DIR, 'spell_constants.lua'))
registry.export_json_config(os.path.join(OUTPUT_DIR, 'spell_config.json'))
print("Exported Lua + JSON constants")

# --- 4. Generate server SQL ---
sql_path = os.path.join(OUTPUT_DIR, 'custom_spell.sql')
with open(sql_path, 'w') as f:
    f.write("-- Custom spell: Arcane Barrage (ID {})\n".format(spell_id))
    f.write("DELETE FROM `spell_dbc` WHERE `ID` = {};\n".format(spell_id))
    f.write("INSERT INTO `spell_dbc` (`ID`, `CastingTimeIndex`, "
            "`RecoveryTime`, `RangeIndex`, `Speed`, "
            "`Effect1`, `EffectDieSides1`, `EffectBasePoints1`, "
            "`EffectImplicitTargetA1`, `SpellIconID`, "
            "`SpellName1`, `SchoolMask`, `Comment`) VALUES (\n")
    f.write("    {}, 1, 3000, 4, 0, ".format(spell_id))
    f.write("2, 201, 599, 6, 2271, ")
    f.write("'Arcane Barrage', 64, 'Custom Arcane Barrage');\n\n")
    f.write("DELETE FROM `spell_bonus_data` WHERE `entry` = {};\n".format(spell_id))
    f.write("INSERT INTO `spell_bonus_data` (`entry`, `direct_bonus`, "
            "`dot_bonus`, `ap_bonus`, `ap_dot_bonus`, `comments`) VALUES (\n")
    f.write("    {}, 0.7143, 0, 0, 0, 'Arcane Barrage custom');\n".format(spell_id))
print("Generated SQL: {}".format(sql_path))
```

---

## Common Pitfalls and Troubleshooting

### Spell does not appear in client
- **Cause**: Record size mismatch. Spell.dbc expects exactly 936 bytes (234 fields x 4 bytes) for WotLK 3.3.5a.
- **Fix**: Verify `len(record) == 936` before appending to the DBC.

### Tooltip shows "$s1" literally instead of a number
- **Cause**: The client reads `EffectBasePoints[0]` to substitute `$s1`. If the effect type (field 71) is 0, the value is never calculated.
- **Fix**: Ensure `Effect[0]` is set to a valid effect type (2 for SCHOOL_DAMAGE, 10 for HEAL, etc.).

### Cast bar does not appear
- **Cause**: `CastingTimeIndex` points to a nonexistent entry in SpellCastTimes.dbc, or the value is 0.
- **Fix**: Use a valid CastingTimeIndex. Value 1 = instant (no bar). Values 4, 5, 14, 15 give progressively longer cast times.

### Spell has no visual effect
- **Cause**: `SpellVisualID[0]` is 0 or points to a nonexistent SpellVisual.
- **Fix**: Use a known stock SpellVisual ID (e.g., 47 for Shadow Bolt, 13 for Fireball).

### Server rejects the spell with "Unknown spell"
- **Cause**: No `spell_dbc` entry exists on the server for the custom ID.
- **Fix**: Insert matching data into the `spell_dbc` table in the world database.

### Damage is always 0
- **Cause**: `EffectBasePoints` is 0 and `EffectDieSides` is 0 on the server side.
- **Fix**: The displayed value is `EffectBasePoints + 1` (minimum) to `EffectBasePoints + EffectDieSides` (maximum). Set `EffectBasePoints` to (desired_min - 1) and `EffectDieSides` to (desired_max - desired_min + 1).

### Wrong damage school color
- **Cause**: `SchoolMask` mismatch between client and server, or wrong value entirely.
- **Fix**: School bitmask values: 1=Physical, 2=Holy, 4=Fire, 8=Nature, 16=Frost, 32=Shadow, 64=Arcane. They can be OR'd for multi-school: Fire+Shadow = 36.

---

## ID Conflict Avoidance Strategy

1. **Always use SpellRegistry** to track all custom spell IDs across your project.
2. **Call `registry.resolve_spell_id(name)` before creating a new spell** to check if it already exists.
3. **Export JSON config regularly** with `registry.export_json_config()` and commit it to version control.
4. **Import previous configs** when resuming work: `registry.import_from_json('spell_config.json')`.
5. **Reserve ID blocks** per feature: boss spells 90000-90099, player spells 90100-90199, item procs 90200-90299, etc.

---

## Cross-References

- [Change Spell Data](./change_spell_data.md) - Modify existing spell records
- [Modify Talent Tree](./modify_talent_tree.md) - Add custom spells to talent trees
- [Change Racial Traits](./change_racial_traits.md) - Auto-learned racial spells
- [Add New Class](./add_new_class.md) - Complete class spell kits
