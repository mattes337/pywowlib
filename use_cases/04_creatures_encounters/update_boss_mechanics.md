# Update Boss Mechanics

**Complexity**: Advanced
**Estimated Time**: 1-3 hours
**Applies To**: WoW WotLK 3.3.5a (build 12340) with AzerothCore + Eluna

---

## Overview

This guide covers every aspect of defining, scripting, and deploying custom boss encounter mechanics for WoW 3.3.5a. Boss encounters are the most complex content to create: they involve multi-phase combat sequences, timed ability rotations, add spawning, void zone placement, phase transition triggers, boss yells, achievement tracking, and instance state management.

The pywowlib toolkit offers two complementary scripting approaches:

1. **ScriptGenerator + Eluna Lua** (recommended for complex bosses): Generates complete, deployable Lua scripts from structured Python data definitions. Supports multi-phase encounters, timer-based abilities, target selection logic, add spawning, void zones, phase transitions, boss yells, and achievement tracking.
2. **SQLGenerator + SmartAI** (simpler encounters): SQL-only scripting using the `smart_scripts` table. Best for trash mobs, mini-bosses, and encounters with fewer than 5 abilities.

Both approaches use the `SpellRegistry` to manage spell ID assignments.

---

## Prerequisites

- Python 3.8+ with pywowlib and Jinja2 installed (`pip install jinja2`)
- A configured AzerothCore server with Eluna Lua engine enabled
- Extracted WotLK 3.3.5a DBC files (for Spell.dbc modifications if using custom spells)
- Familiarity with the creature creation process (see [add_new_creature.md](add_new_creature.md))
- Understanding of WoW boss encounter design patterns (phase transitions, timers, target selection)

---

## Table of Contents

1. [Spell Management with SpellRegistry](#step-1-spell-management-with-spellregistry)
2. [Client-Side: Register Custom Boss Spells in Spell.dbc](#step-2-client-side-register-custom-boss-spells-in-spelldbc)
3. [Eluna Lua: Boss Definition Schema](#step-3-eluna-lua-boss-definition-schema)
4. [Eluna Lua: Multi-Phase Boss Encounters](#step-4-eluna-lua-multi-phase-boss-encounters)
5. [Eluna Lua: Timer-Based Abilities](#step-5-eluna-lua-timer-based-abilities)
6. [Eluna Lua: Target Selection](#step-6-eluna-lua-target-selection)
7. [Eluna Lua: Add Spawning](#step-7-eluna-lua-add-spawning)
8. [Eluna Lua: Void Zones and Ground Effects](#step-8-eluna-lua-void-zones-and-ground-effects)
9. [Eluna Lua: Phase Transitions](#step-9-eluna-lua-phase-transitions)
10. [Eluna Lua: Boss Yells and creature_text](#step-10-eluna-lua-boss-yells-and-creature_text)
11. [Eluna Lua: Achievement Tracking](#step-11-eluna-lua-achievement-tracking)
12. [Eluna Lua: Instance Script Integration](#step-12-eluna-lua-instance-script-integration)
13. [SmartAI Alternative: SQL-Only Boss Scripts](#step-13-smartai-alternative-sql-only-boss-scripts)
14. [Complete Working Example: Full Boss Encounter](#step-14-complete-working-example-full-boss-encounter)
15. [Writing and Deploying Scripts](#step-15-writing-and-deploying-scripts)
16. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
17. [Cross-References](#cross-references)

---

## Step 1: Spell Management with SpellRegistry

Every boss ability needs a spell ID. The `SpellRegistry` class manages the mapping between readable spell names and numeric IDs, supporting both:

- **Existing spells**: Reuse a WoW 3.3.5a spell by its original ID (for visuals/mechanics that already exist)
- **Custom spells**: Assign new IDs in the 90000+ range (requires server-side `spell_dbc` entries)

### 1.1 Creating and Populating a SpellRegistry

```python
from world_builder.spell_registry import SpellRegistry

# Initialize with a base ID for auto-assignment
registry = SpellRegistry(base_spell_id=90100)

# Register an existing WoW spell (reuse visuals from Naxxramas)
registry.register_spell(
    'SPELL_SHADOW_BOLT_VOLLEY',
    existing_spell_id=27831,
    description='Shadow Bolt Volley (reused from Naxxramas)',
    boss_label="BOSS 1: SHADE OF ZHAR'KAAN",
)

# Register a custom spell with an explicit ID
registry.register_spell(
    'SPELL_LIGHTNING_LASH',
    custom_spell_id=90104,
    description='Lightning Lash - chain lightning hitting 3 targets',
    boss_label="BOSS 1: SHADE OF ZHAR'KAAN",
)

# Register a custom spell with auto-assigned ID
# (uses the next available ID from base_spell_id)
spell_id = registry.register_spell(
    'SPELL_VOID_ERUPTION',
    description='Void Eruption - AoE damage around the boss',
    boss_label="BOSS 1: SHADE OF ZHAR'KAAN",
)
print(f"Auto-assigned spell ID: {spell_id}")  # e.g. 90105

# Look up a registered spell
bolt_id = registry.resolve_spell_id('SPELL_SHADOW_BOLT_VOLLEY')
print(f"Shadow Bolt Volley ID: {bolt_id}")  # 27831
```

### 1.2 SpellRegistry API Reference

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `register_spell()` | `spell_name`, `existing_spell_id=None`, `custom_spell_id=None`, `description=''`, `spell_data=None`, `boss_label=None` | `int` (spell ID) | Register a spell. If `existing_spell_id` is provided, reuse it. If `custom_spell_id` is given, use that explicit ID. Otherwise, auto-assign the next available custom ID. |
| `resolve_spell_id()` | `spell_name` | `int` (0 if not found) | Look up the numeric ID for a spell name. |
| `get_all_spells()` | (none) | `list[dict]` | Return all registered spell definitions. |
| `export_lua_constants()` | `filepath` | (none) | Write a Lua file with spell name = ID assignments, grouped by boss. |
| `export_json_config()` | `filepath` | (none) | Write a JSON file with all spell data for documentation. |
| `import_from_json()` | `filepath` | `int` (count) | Import spells from a previously exported JSON config. |
| `import_from_lua()` | `filepath` | `int` (count) | Import spells from a Lua constants file. |

### 1.3 Exporting Spell Constants

```python
# Generate a Lua constants file for use in scripts
registry.export_lua_constants('./output/scripts/spell_constants.lua')

# Generate a JSON config for documentation/tooling
registry.export_json_config('./output/scripts/spell_config.json')
```

The generated Lua file looks like:

```lua
-- Spell Constants for Vault of Storms
-- AUTO-GENERATED by world_builder.script_generator

-- ========================================
-- BOSS 1: SHADE OF ZHAR'KAAN
-- ========================================
SPELL_SHADOW_BOLT_VOLLEY = 27831              -- Existing: Shadow Bolt Volley (reused)
SPELL_LIGHTNING_LASH = 90104                  -- Custom: Lightning Lash
SPELL_VOID_ERUPTION = 90105                   -- Custom: Void Eruption
```

---

## Step 2: Client-Side -- Register Custom Boss Spells in Spell.dbc

Custom spells (IDs in the 90000+ range) do not exist in the base game. For the server to recognize them, you need `spell_dbc` entries in the AzerothCore database. For the client to show spell visuals, you may need client-side `Spell.dbc` modifications.

### 2.1 Server-Side: spell_dbc Table

AzerothCore provides a `spell_dbc` table that acts as an override/addition to the client's `Spell.dbc`. For server-only mechanics (damage, effects), this is sufficient:

```sql
-- Register a custom boss spell (server-side only)
INSERT INTO `spell_dbc` (
    `Id`, `Category`, `Dispel`, `Mechanic`, `Attributes`,
    `CastingTimeIndex`, `DurationIndex`, `RangeIndex`,
    `SchoolMask`, `SpellName_1`, `Description_1`,
    `Effect_1`, `EffectImplicitTargetA_1`, `EffectBasePoints_1`
) VALUES
(90104, 0, 0, 0, 0,       -- Lightning Lash
 1, 0, 6,                   -- Instant cast, no duration, 30yd range
 8,                          -- Nature school
 'Lightning Lash',
 'Strikes the target with chain lightning',
 6, 6, 4500);               -- Effect: SCHOOL_DAMAGE, target: CHAIN, base damage
```

### 2.2 Client-Side: Spell.dbc (Optional)

If you want players to see spell tooltips, cast bar names, or spell icons for custom spells, you must also inject entries into the client `Spell.dbc`. This is a large, complex DBC (over 200 fields per record). For most boss encounters, server-side `spell_dbc` entries are sufficient because the boss is casting -- the player only sees the visual effect, which you can borrow from an existing spell via `VisualEffect` fields.

### 2.3 Practical Approach: Reuse Existing Spells

The simplest approach is to reuse existing WoW spells for visual effects and override damage/behavior server-side:

```python
# Reuse an existing Chain Lightning visual for our custom ability
registry.register_spell(
    'SPELL_LIGHTNING_LASH',
    existing_spell_id=49268,    # Chain Lightning (DK rank 4)
    description='Chain Lightning visual - damage overridden server-side',
)
```

Then override the damage server-side with `spell_dbc` or handle it entirely in the Lua script.

---

## Step 3: Eluna Lua -- Boss Definition Schema

The `ScriptGenerator` consumes structured Python dictionaries that define every aspect of a boss encounter. Below is the complete schema with all fields documented.

### 3.1 Top-Level Boss Definition

```python
boss_def = {
    # ---- Identity ----
    'name': "Shade of Zhar'kaan",         # Display name
    'script_name': 'ShadeOfZharkaan',      # Eluna script name (no spaces)
    'entry': 90100,                         # creature_template entry ID
    'health': 85000,                        # Base HP
    'mana': 50000,                          # Base mana (0 if no mana)
    'encounter_id': 0,                      # Boss order in instance (0-based)

    # ---- Associated NPCs (adds, minions) ----
    'npcs': [
        {
            'entry': 90101,
            'name': 'NPC_DARKLING_WISP',    # Constant name in Lua
            'label': 'Darkling Wisp',       # Display name
        },
    ],

    # ---- Phases ----
    'phases': [
        # See Step 4 for full phase schema
    ],

    # ---- Death behavior ----
    'on_death': {
        'yell': 'The darkness... recedes...',
        'sound_id': 15002,                  # Sound file ID
        'unlock_door': 195000,              # Gameobject entry to unlock
    },

    # ---- Loot ----
    'loot_id': 90100,                       # FK to creature_loot_template

    # ---- Achievements ----
    'achievements': [
        # See Step 11 for achievement tracking
    ],
}
```

### 3.2 Phase Definition Schema

Each boss has one or more phases. Phases define HP thresholds, abilities, and transition behavior:

```python
phase = {
    'phase_id': 1,                          # Phase number (1-based)
    'name': 'Phase 1 - Shadow Phase',       # Descriptive name
    'const_name': 'PHASE_SHADOW',           # Lua constant name
    'hp_range': (100, 50),                  # (start_pct, end_pct)

    'on_enter': {
        'yell': 'The shadows consume you!',
        'sound_id': 15000,
        'action': {                          # Optional phase transition action
            'type': 'transform_adds',        # See Step 9
            'from_entry': 90101,
            'to_entry': 90102,
        },
    },

    'abilities': [
        # See Step 5 for ability schema
    ],
}
```

### 3.3 Ability Definition Schema

Each ability within a phase defines a spell cast with timing, targeting, and optional mechanics:

```python
ability = {
    'id': 'shadow_bolt_volley',             # Unique ability identifier
    'func_name': 'CastShadowBoltVolley',    # Generated Lua function name
    'spell': 'SPELL_SHADOW_BOLT_VOLLEY',    # SpellRegistry name
    'spell_id': 27831,                      # Numeric spell ID (resolved from registry)
    'name': 'Shadow Bolt Volley',           # Display name
    'description': 'AoE shadow damage',     # Description for comments

    # Timer configuration
    'timer': {
        'initial': 5000,                    # First cast delay (ms after phase start)
        'min': 8000,                        # Minimum repeat interval (ms)
        'max': 12000,                       # Maximum repeat interval (ms)
    },

    # Targeting
    'targeting': {
        'type': 'aoe',                      # See Step 6 for target types
    },

    'cast_time': 2000,                      # Cast time in ms (0 = instant)
    'interruptible': True,                  # Can players interrupt this?

    # Optional: Add spawning (see Step 7)
    'summon': { ... },

    # Optional: Void zone (see Step 8)
    'void_zone': { ... },

    # Optional: Chain ability
    'chain': {
        'enabled': True,
        'max_targets': 3,
        'range': 10.0,
    },
}
```

---

## Step 4: Eluna Lua -- Multi-Phase Boss Encounters

Multi-phase bosses transition between ability sets based on HP thresholds. The ScriptGenerator handles phase tracking, timer management, and transition logic automatically.

### 4.1 Two-Phase Boss Example

```python
boss_two_phase = {
    'name': 'Storm Warden',
    'script_name': 'StormWarden',
    'entry': 90600,
    'health': 100000,
    'mana': 0,
    'encounter_id': 0,

    'npcs': [],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Normal',
            'const_name': 'PHASE_NORMAL',
            'hp_range': (100, 50),          # Active from 100% to 50% HP

            'on_enter': {
                'yell': 'You dare challenge me?!',
                'sound_id': 0,
            },

            'abilities': [
                {
                    'id': 'cleave',
                    'func_name': 'CastCleave',
                    'spell': 'SPELL_CLEAVE',
                    'spell_id': 15496,      # Existing Cleave spell
                    'name': 'Cleave',
                    'description': 'Frontal cleave on tank',
                    'timer': {'initial': 5000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'current'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'whirlwind',
                    'func_name': 'CastWhirlwind',
                    'spell': 'SPELL_WHIRLWIND',
                    'spell_id': 15578,
                    'name': 'Whirlwind',
                    'description': 'AoE melee damage',
                    'timer': {'initial': 12000, 'min': 15000, 'max': 20000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 0,
                    'interruptible': False,
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Enraged',
            'const_name': 'PHASE_ENRAGED',
            'hp_range': (50, 0),            # Active from 50% to 0% HP

            'on_enter': {
                'yell': 'ENOUGH! Feel the fury of the storm!',
                'sound_id': 0,
                'action': {
                    'type': 'apply_buff',
                    'buff_spell': 8599,      # Enrage buff
                },
            },

            'abilities': [
                {
                    'id': 'cleave_p2',
                    'func_name': 'CastCleaveP2',
                    'spell': 'SPELL_CLEAVE',
                    'spell_id': 15496,
                    'name': 'Cleave',
                    'description': 'Faster cleave in P2',
                    'timer': {'initial': 3000, 'min': 5000, 'max': 8000},
                    'targeting': {'type': 'current'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'shockwave',
                    'func_name': 'CastShockwave',
                    'spell': 'SPELL_SHOCKWAVE',
                    'spell_id': 46968,       # Shockwave
                    'name': 'Shockwave',
                    'description': 'Cone stun + damage',
                    'timer': {'initial': 8000, 'min': 12000, 'max': 15000},
                    'targeting': {'type': 'current'},
                    'cast_time': 1000,
                    'interruptible': False,
                },
            ],
        },
    ],

    'on_death': {
        'yell': 'The storm... subsides...',
        'sound_id': 0,
        'unlock_door': 0,
    },

    'loot_id': 90600,
    'achievements': [],
}
```

### 4.2 Three-Phase Boss Example

For a three-phase boss (like Gorgash, Stormfather in the example dungeon), add a third phase entry:

```python
'phases': [
    {'phase_id': 1, 'hp_range': (100, 60), ...},  # Phase 1: 100-60%
    {'phase_id': 2, 'hp_range': (60, 30), ...},   # Phase 2: 60-30%
    {'phase_id': 3, 'hp_range': (30, 0), ...},    # Phase 3: 30-0% (execute)
],
```

The generated Lua script automatically checks `creature:GetHealthPct()` and transitions between phases at the specified thresholds.

---

## Step 5: Eluna Lua -- Timer-Based Abilities

Every boss ability is driven by a timer system. The ScriptGenerator produces `creature:RegisterEvent()` calls for each ability, implementing the WoW boss "rotation" pattern.

### 5.1 Timer Configuration

```python
'timer': {
    'initial': 5000,    # ms before first cast (after combat start or phase start)
    'min': 8000,        # minimum interval between subsequent casts
    'max': 12000,       # maximum interval (random between min-max)
}
```

### 5.2 Generated Lua Timer Pattern

The ScriptGenerator translates the above into Eluna Lua code like:

```lua
-- Timer registration (on combat enter / phase transition)
function Boss.OnEnterCombat(event, creature, target)
    -- Phase 1 timers
    creature:RegisterEvent(Boss.CastShadowBoltVolley, 5000, 0)  -- initial delay
    creature:RegisterEvent(Boss.SummonWisps, 10000, 0)
    creature:RegisterEvent(Boss.CastShadowPool, 8000, 0)
end

-- Ability handler with re-registration for variable timing
function Boss.CastShadowBoltVolley(eventId, delay, pCall, creature)
    creature:RemoveEvents()  -- Clear this timer
    if creature:IsInCombat() then
        creature:CastSpell(creature:GetVictim(), SPELL_SHADOW_BOLT_VOLLEY, false)
        -- Re-register with random delay
        creature:RegisterEvent(Boss.CastShadowBoltVolley,
            math.random(8000, 12000), 1)
    end
end
```

### 5.3 Instant vs. Cast-Time Abilities

- `cast_time: 0` -- Instant cast. The boss does not stop moving.
- `cast_time: 2000` -- 2 second cast. The boss stops, a cast bar appears.

The generated script handles cast bars and interruptibility automatically.

---

## Step 6: Eluna Lua -- Target Selection

Boss abilities target different players based on the `targeting.type` field:

### 6.1 Target Type Reference

| Targeting Type | Description | Typical Use |
|---------------|-------------|-------------|
| `'current'` | Current threat target (tank) | Melee attacks, tank busters |
| `'random_player'` | Random player in combat | Ranged abilities, debuffs |
| `'aoe'` | No specific target (hits all) | Area-of-effect spells |
| `'self'` | The boss itself | Buffs, summon spells |

### 6.2 Generated Target Selection Code

For `'random_player'` targeting, the ScriptGenerator generates a helper function:

```lua
function Boss.GetRandomPlayer(creature)
    local players = creature:GetPlayersInRange(40)
    if #players > 0 then
        return players[math.random(1, #players)]
    end
    return creature:GetVictim()
end
```

For `'current'` targeting:

```lua
local target = creature:GetVictim()
if target then
    creature:CastSpell(target, SPELL_SLAM, false)
end
```

---

## Step 7: Eluna Lua -- Add Spawning

Many boss encounters spawn additional creatures (adds) that players must handle. The `summon` field in an ability definition controls add spawning.

### 7.1 Summon Configuration

```python
'summon': {
    'entry': 90101,                 # creature_template entry for the add
    'count': 2,                     # Number of adds to spawn
    'position': 'random_around_boss',  # Spawn positioning
    'radius': 10.0,                 # Radius from boss for random positioning
    'duration': 60000,              # Despawn timer in ms (0 = permanent)
},
```

### 7.2 Generated Lua Summon Code

```lua
function Boss.SummonWisps(eventId, delay, pCall, creature)
    creature:RemoveEvents()
    if creature:IsInCombat() then
        local x, y, z = creature:GetLocation()
        for i = 1, 2 do
            local angle = math.random() * 2 * math.pi
            local dist = math.random() * 10.0
            local sx = x + math.cos(angle) * dist
            local sy = y + math.sin(angle) * dist
            creature:SpawnCreature(NPC_DARKLING_WISP, sx, sy, z, 0,
                2, 60000)  -- TEMPSUMMON_TIMED_DESPAWN, 60s
        end
        creature:RegisterEvent(Boss.SummonWisps,
            math.random(20000, 20000), 1)
    end
end
```

### 7.3 Add Creature Templates

Do not forget to create `creature_template` entries for the adds:

```python
gen.add_creatures([
    {
        'entry': 90101,
        'name': 'Darkling Wisp',
        'modelid1': 16946,       # Wisp model
        'minlevel': 78,
        'maxlevel': 79,
        'faction': 16,           # Hostile
        'rank': 0,               # Normal (not elite)
        'type': 4,               # Elemental
        'health_modifier': 0.5,  # Low HP -- kill quickly
        'damage_modifier': 0.3,
        'flags_extra': 0,
    },
])
```

---

## Step 8: Eluna Lua -- Void Zones and Ground Effects

Void zones are persistent ground effects that damage players who stand in them. The `void_zone` field in an ability definition creates these.

### 8.1 Void Zone Configuration

```python
'void_zone': {
    'visual_spell': 90002,      # Spell for the visual effect on the ground
    'damage_spell': 90003,      # Spell for the periodic damage aura
    'duration': 30000,           # How long the zone persists (ms)
    'radius': 5.0,               # Damage radius in yards
},
```

### 8.2 Generated Lua Void Zone Code

```lua
function Boss.CastShadowPool(eventId, delay, pCall, creature)
    creature:RemoveEvents()
    if creature:IsInCombat() then
        local target = Boss.GetRandomPlayer(creature)
        if target then
            local x, y, z = target:GetLocation()
            -- Spawn invisible trigger at player's position
            local trigger = creature:SpawnCreature(
                NPC_VOID_ZONE, x, y, z, 0,
                2, 30000)  -- TEMPSUMMON_TIMED_DESPAWN
            if trigger then
                trigger:CastSpell(trigger, SPELL_SHADOW_POOL, true)        -- Visual
                trigger:CastSpell(trigger, SPELL_SHADOW_POOL_DAMAGE, true) -- Damage aura
            end
        end
        creature:RegisterEvent(Boss.CastShadowPool,
            math.random(15000, 20000), 1)
    end
end
```

### 8.3 Void Zone NPC Template

The void zone itself is typically an invisible creature with a persistent aura:

```python
gen.add_creatures([
    {
        'entry': 90199,
        'name': 'Shadow Pool Trigger',
        'modelid1': 11686,           # Invisible stalker model
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 16,               # Hostile
        'unit_flags': 33554434,      # NOT_SELECTABLE | PACIFIED
        'type': 10,                  # Not specified
        'flags_extra': 128,          # TRIGGER
    },
])
```

---

## Step 9: Eluna Lua -- Phase Transitions

Phase transitions are triggered when the boss HP crosses a threshold defined in `hp_range`. The ScriptGenerator generates HP-check hooks that handle the transition.

### 9.1 Phase Transition Actions

The `on_enter.action` field supports several transition types:

| Action Type | Description | Fields |
|------------|-------------|--------|
| `'transform_adds'` | Transform existing adds into a different creature | `from_entry`, `to_entry` |
| `'apply_buff'` | Apply a buff/debuff to the boss | `buff_spell` |
| `'despawn_adds'` | Despawn all adds of a specific type | `entry` |
| `'spawn_objects'` | Spawn gameobjects at predefined positions | `objects` list |

### 9.2 Transform Adds Example

When the boss transitions to Phase 2, all Darkling Wisps transform into Shadowy Stalkers:

```python
'on_enter': {
    'yell': 'The storm awakens!',
    'sound_id': 15001,
    'action': {
        'type': 'transform_adds',
        'from_entry': 90101,     # Darkling Wisp
        'to_entry': 90102,       # Shadowy Stalker
    },
},
```

Generated Lua:

```lua
function Boss.TransitionToPhase2(creature)
    Boss.phase = PHASE_STORM
    creature:SendUnitYell("The storm awakens!", 0)

    -- Transform all Darkling Wisps into Shadowy Stalkers
    local wisps = creature:GetCreaturesInRange(100, NPC_DARKLING_WISP)
    for _, wisp in ipairs(wisps) do
        local x, y, z, o = wisp:GetLocation()
        wisp:DespawnOrUnsummon(0)
        creature:SpawnCreature(NPC_SHADOWY_STALKER, x, y, z, o, 2, 0)
    end

    -- Cancel Phase 1 timers and start Phase 2 timers
    creature:RemoveEvents()
    creature:RegisterEvent(Boss.CastLightningLash, 3000, 0)
    creature:RegisterEvent(Boss.CastShadowBoltVolleyP2, 8000, 0)
end
```

### 9.3 Apply Buff on Phase Transition

```python
'on_enter': {
    'yell': 'POWER CORE UNSTABLE. ENGAGING OVERDRIVE.',
    'sound_id': 15011,
    'action': {
        'type': 'apply_buff',
        'buff_spell': 90013,     # Overcharged (+10% damage stacking)
    },
},
```

Generated Lua:

```lua
function Boss.TransitionToPhase2(creature)
    Boss.phase = PHASE_OVERCHARGED
    creature:SendUnitYell("POWER CORE UNSTABLE. ENGAGING OVERDRIVE.", 0)
    creature:CastSpell(creature, SPELL_OVERCHARGED, true)
    -- ... timer setup ...
end
```

---

## Step 10: Eluna Lua -- Boss Yells and creature_text

Boss encounters need dramatic dialogue at key moments: on aggro, phase transitions, deaths, and special ability casts.

### 10.1 Yells in the Boss Definition

Yells are defined in the `on_enter` block of each phase and the `on_death` block:

```python
'phases': [
    {
        'on_enter': {
            'yell': 'The shadows consume you!',
            'sound_id': 15000,   # Voice-over sound ID (0 if none)
        },
        ...
    },
],
'on_death': {
    'yell': 'The darkness... recedes...',
    'sound_id': 15002,
},
```

### 10.2 Server-Side: creature_text Table

For SmartAI-based encounters (or as an alternative to Eluna `SendUnitYell`), you can use the `creature_text` table:

```sql
-- creature_text: Boss yells
DELETE FROM `creature_text` WHERE `CreatureID` = 90100;
INSERT INTO `creature_text` (`CreatureID`, `GroupID`, `ID`, `Text`, `Type`, `Language`,
    `Probability`, `Emote`, `Duration`, `Sound`, `BroadcastTextId`,
    `TextRange`, `comment`) VALUES
-- GroupID 0: Aggro
(90100, 0, 0, 'The shadows consume you!', 14, 0, 100, 0, 0, 15000, 0, 0,
 'Shade of Zharkaan - Aggro'),
-- GroupID 1: Phase 2 transition
(90100, 1, 0, 'The storm awakens! You cannot contain what was never meant to be caged!',
 14, 0, 100, 0, 0, 15001, 0, 0,
 'Shade of Zharkaan - Phase 2'),
-- GroupID 2: Death
(90100, 2, 0, 'The darkness... recedes...', 14, 0, 100, 0, 0, 15002, 0, 0,
 'Shade of Zharkaan - Death');
```

**creature_text.Type values:**

| Type | Description |
|------|-------------|
| 12 | BOSS_EMOTE (raid warning style) |
| 14 | BOSS_WHISPER_YELL (red boss yell) |
| 41 | BOSS_YELL (standard boss yell) |
| 15 | WHISPER (personal whisper) |

### 10.3 Random Yell Variants

You can define multiple texts per `GroupID` with the same `CreatureID` and `GroupID` but different `ID` values. The server picks one at random based on `Probability`:

```sql
(90100, 0, 0, 'The shadows consume you!', 14, 0, 50, 0, 0, 15000, 0, 0, 'Aggro v1'),
(90100, 0, 1, 'You tread where mortals are not welcome!', 14, 0, 50, 0, 0, 15000, 0, 0, 'Aggro v2');
```

---

## Step 11: Eluna Lua -- Achievement Tracking

Custom achievements can be tracked using variables in the boss script. The ScriptGenerator generates tracking code based on the achievement definition.

### 11.1 Achievement Definition

```python
'achievements': [
    {
        'id': 90001,
        'name': 'Shadow Dance',
        'description': "Defeat the boss without any player being hit by Shadow Pool",
        'criteria': 'no_player_hit_by_void_zone',
        'tracking': {
            'variable': 'shadow_pool_hits',     # Lua variable name
            'condition': 'equals',               # equals, less_than, greater_than
            'value': 0,                          # Target value
        },
    },
],
```

### 11.2 Generated Tracking Code

```lua
-- Achievement tracking variable
Boss.shadow_pool_hits = 0

-- In void zone damage handler:
function Boss.OnVoidZoneHit(eventId, delay, pCall, creature)
    Boss.shadow_pool_hits = Boss.shadow_pool_hits + 1
end

-- On boss death, check achievement:
function Boss.OnDied(event, creature, killer)
    -- ... loot and door unlock logic ...

    -- Check achievement: Shadow Dance
    if Boss.shadow_pool_hits == 0 then
        -- Grant achievement to all players in instance
        local players = creature:GetPlayersInRange(100)
        for _, player in ipairs(players) do
            player:CompletedAchievement(90001)
        end
    end
end
```

---

## Step 12: Eluna Lua -- Instance Script Integration

Boss encounters do not exist in isolation -- they are part of an instance that tracks which bosses are alive, manages doors between rooms, and persists progress across wipes.

### 12.1 Instance Definition

```python
from world_builder.encounter_definitions import VAULT_INSTANCE

# The instance definition tells ScriptGenerator about all bosses,
# doors, and events in the dungeon
instance_def = {
    'name': 'VaultOfStorms',
    'display_name': 'Vault of Storms',
    'map_id': 801,
    'script_name': 'instance_vault_of_storms',

    'bosses': [
        {
            'name': 'ShadeOfZharkaan',
            'entry': 90100,
            'encounter_id': 0,
            'encounter_name': 'BOSS_SHADE',
        },
        {
            'name': 'OverseerV7',
            'entry': 90200,
            'encounter_id': 1,
            'encounter_name': 'BOSS_OVERSEER',
        },
    ],

    'doors': [
        {
            'entry': 195000,
            'name': 'door_nexus_to_core',
            'const_name': 'DOOR_NEXUS_TO_CORE',
            'unlock_on_encounter': 0,    # Opens when boss 0 dies
            'initial_state': 'closed',
        },
    ],
}
```

### 12.2 Generating the Instance Script

```python
from world_builder.script_generator import ScriptGenerator

generator = ScriptGenerator(spell_registry=registry)
generator.add_instance_script(instance_def)
```

### 12.3 Generated Instance Script Features

The generated instance script includes:

- **Encounter state bitmask**: Tracks which bosses are killed using a bitmask saved to the database
- **Door management**: Locks doors on instance create, unlocks them when the required boss dies
- **OnCreatureCreate hooks**: Registers boss creature references for state management
- **Save/Load persistence**: Saves encounter progress using `SaveInstanceData` / `LoadInstanceData`
- **SetData/GetData interface**: Allows boss scripts to notify the instance of kills

---

## Step 13: SmartAI Alternative -- SQL-Only Boss Scripts

For simpler encounters (trash mobs, mini-bosses, encounters with <5 abilities), SmartAI provides a SQL-only alternative to Eluna Lua scripting.

### 13.1 SmartAI Constants

The `sql_generator` module exports all necessary SmartAI constants:

```python
from world_builder.sql_generator import (
    SMART_EVENT_UPDATE_IC,       # 0  - In Combat timer
    SMART_EVENT_UPDATE_OOC,      # 1  - Out of Combat timer
    SMART_EVENT_HEALTH_PCT,      # 2  - HP threshold
    SMART_EVENT_MANA_PCT,        # 3  - Mana threshold
    SMART_EVENT_AGGRO,           # 4  - On aggro
    SMART_EVENT_KILL,            # 5  - On player kill
    SMART_EVENT_DEATH,           # 6  - On death
    SMART_EVENT_EVADE,           # 7  - On evade
    SMART_EVENT_SPELLHIT,        # 8  - On spell hit
    SMART_EVENT_RANGE,           # 9  - Range check
    SMART_EVENT_JUST_SUMMONED,   # 37 - Just summoned

    SMART_ACTION_CAST,           # 11 - Cast spell
    SMART_ACTION_TALK,           # 1  - Say text (creature_text)
    SMART_ACTION_THREAT_ALL_PCT, # 32 - Modify threat
    SMART_ACTION_FLEE,           # 47 - Flee for assist
    SMART_ACTION_SET_EMOTE,      # 5  - Set emote state

    SMART_TARGET_SELF,           # 1  - Self target
    SMART_TARGET_VICTIM,         # 2  - Current victim (tank)
    SMART_TARGET_HOSTILE_SECOND, # 6  - Second on threat
    SMART_TARGET_RANDOM,         # 24 - Random player
    SMART_TARGET_RANDOM_NOT_TOP, # 25 - Random non-tank
)
```

### 13.2 SmartAI Boss Script Example

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90500, map_id=801, zone_id=9001)

# Create the boss creature template
gen.add_creatures([
    {
        'entry': 90500,
        'name': 'Minor Storm Elemental',
        'modelid1': 26693,
        'minlevel': 80,
        'maxlevel': 80,
        'faction': 16,
        'rank': 1,                        # Elite
        'type': 4,                        # Elemental
        'health_modifier': 10.0,
        'damage_modifier': 4.0,
        'ai_name': 'SmartAI',            # REQUIRED for SmartAI
        'flags_extra': 0,
    },
])

# Define SmartAI behavior
gen.add_smartai({
    90500: {
        'name': 'Minor Storm Elemental',
        'abilities': [
            # Ability 1: Chain Lightning every 8-12 seconds
            {
                'event': 'combat',
                'spell_id': 61546,
                'target': 'random',
                'min_repeat': 8000,
                'max_repeat': 12000,
                'comment': 'Storm Elemental - IC - Cast Chain Lightning',
            },
            # Ability 2: Thunderclap every 10-15 seconds
            {
                'event': 'combat',
                'spell_id': 8078,
                'target': 'self',       # AoE around self
                'min_repeat': 10000,
                'max_repeat': 15000,
                'comment': 'Storm Elemental - IC - Cast Thunderclap',
            },
            # Ability 3: Enrage at 30% HP (once)
            {
                'event': 'health_pct',
                'health_pct': 30,
                'spell_id': 8599,
                'target': 'self',
                'event_flags': 1,       # NOT_REPEATABLE
                'comment': 'Storm Elemental - 30% HP - Enrage',
            },
            # Ability 4: Yell on aggro
            {
                'event': 'aggro',
                'action_type': 1,       # SMART_ACTION_TALK
                'action_params': [0],   # creature_text GroupID 0
                'target': 'self',
                'comment': 'Storm Elemental - Aggro - Yell',
            },
            # Ability 5: Yell on death
            {
                'event': 'death',
                'action_type': 1,       # SMART_ACTION_TALK
                'action_params': [1],   # creature_text GroupID 1
                'target': 'self',
                'comment': 'Storm Elemental - Death - Yell',
            },
        ],
    },
})

gen.write_sql('./output/sql/boss_storm_elemental.sql')
```

### 13.3 Generated SmartAI SQL

```sql
-- Minor Storm Elemental (90500) - SmartAI
INSERT INTO `smart_scripts` (`entryorguid`, `source_type`, `id`, `link`,
    `event_type`, `event_phase_mask`, `event_chance`, `event_flags`,
    `event_param1`, `event_param2`, `event_param3`, `event_param4`, `event_param5`,
    `action_type`,
    `action_param1`, `action_param2`, `action_param3`,
    `action_param4`, `action_param5`, `action_param6`,
    `target_type`,
    `target_param1`, `target_param2`, `target_param3`, `target_param4`,
    `target_x`, `target_y`, `target_z`, `target_o`,
    `comment`) VALUES
(90500, 0, 0, 0, 0, 0, 100, 0, 8000, 12000, 8000, 12000, 0,
 11, 61546, 0, 0, 0, 0, 0, 24, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
 'Storm Elemental - IC - Cast Chain Lightning'),
(90500, 0, 1, 0, 0, 0, 100, 0, 10000, 15000, 10000, 15000, 0,
 11, 8078, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
 'Storm Elemental - IC - Cast Thunderclap'),
(90500, 0, 2, 0, 2, 0, 100, 1, 0, 30, 0, 0, 0,
 11, 8599, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
 'Storm Elemental - 30% HP - Enrage'),
(90500, 0, 3, 0, 4, 0, 100, 0, 0, 0, 0, 0, 0,
 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
 'Storm Elemental - Aggro - Yell'),
(90500, 0, 4, 0, 6, 0, 100, 0, 0, 0, 0, 0, 0,
 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
 'Storm Elemental - Death - Yell');
```

### 13.4 When to Use SmartAI vs. Eluna

| Criteria | SmartAI | Eluna Lua |
|----------|---------|-----------|
| Number of abilities | < 5 | Any |
| Multi-phase | No (complex to implement) | Yes (built-in) |
| Add spawning | Limited | Full control |
| Void zones | Limited | Full control |
| Achievement tracking | No | Yes |
| Instance integration | Limited | Full |
| Requires file deployment | No (SQL only) | Yes (Lua files) |
| Debugging | Harder (pure SQL) | Easier (Lua with print) |

---

## Step 14: Complete Working Example -- Full Boss Encounter

This example creates a complete two-phase boss encounter with all mechanics, using the ScriptGenerator:

```python
"""
Complete example: Two-phase boss encounter with ScriptGenerator.
Generates Eluna Lua scripts, spell constants, and creature SQL.
"""

from world_builder.sql_generator import SQLGenerator
from world_builder.script_generator import ScriptGenerator
from world_builder.spell_registry import SpellRegistry

# ---------------------------------------------------------------
# 1. Set up spell registry
# ---------------------------------------------------------------
registry = SpellRegistry(base_spell_id=90200)

# Phase 1 spells
registry.register_spell(
    'SPELL_SHADOW_BOLT_VOLLEY',
    existing_spell_id=27831,
    description='Shadow Bolt Volley (AoE)',
    boss_label='BOSS: Storm Shade',
)
registry.register_spell(
    'SPELL_SUMMON_WISPS',
    custom_spell_id=90201,
    description='Summon Darkling Wisps',
    boss_label='BOSS: Storm Shade',
)
registry.register_spell(
    'SPELL_SHADOW_POOL',
    custom_spell_id=90202,
    description='Shadow Pool void zone visual',
    boss_label='BOSS: Storm Shade',
)
registry.register_spell(
    'SPELL_SHADOW_POOL_DAMAGE',
    custom_spell_id=90203,
    description='Shadow Pool periodic damage',
    boss_label='BOSS: Storm Shade',
)

# Phase 2 spells
registry.register_spell(
    'SPELL_LIGHTNING_LASH',
    custom_spell_id=90204,
    description='Lightning Lash (chain)',
    boss_label='BOSS: Storm Shade',
)
registry.register_spell(
    'SPELL_ENRAGE',
    existing_spell_id=8599,
    description='Enrage buff',
    boss_label='BOSS: Storm Shade',
)

# ---------------------------------------------------------------
# 2. Define the boss encounter
# ---------------------------------------------------------------
boss_def = {
    'name': 'Storm Shade',
    'script_name': 'StormShade',
    'entry': 90700,
    'health': 85000,
    'mana': 50000,
    'encounter_id': 0,

    'npcs': [
        {'entry': 90701, 'name': 'NPC_DARKLING_WISP', 'label': 'Darkling Wisp'},
    ],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Shadow',
            'const_name': 'PHASE_SHADOW',
            'hp_range': (100, 50),
            'on_enter': {
                'yell': 'The shadows consume you!',
                'sound_id': 0,
            },
            'abilities': [
                {
                    'id': 'shadow_bolt_volley',
                    'func_name': 'CastShadowBoltVolley',
                    'spell': 'SPELL_SHADOW_BOLT_VOLLEY',
                    'spell_id': 27831,
                    'name': 'Shadow Bolt Volley',
                    'description': 'AoE shadow damage',
                    'timer': {'initial': 5000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 2000,
                    'interruptible': True,
                },
                {
                    'id': 'summon_wisps',
                    'func_name': 'SummonWisps',
                    'spell': 'SPELL_SUMMON_WISPS',
                    'spell_id': 90201,
                    'name': 'Summon Darkling Wisps',
                    'description': 'Summons 2 adds',
                    'timer': {'initial': 10000, 'min': 20000, 'max': 20000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90701,
                        'count': 2,
                        'position': 'random_around_boss',
                        'radius': 10.0,
                        'duration': 60000,
                    },
                },
                {
                    'id': 'shadow_pool',
                    'func_name': 'CastShadowPool',
                    'spell': 'SPELL_SHADOW_POOL',
                    'spell_id': 90202,
                    'name': 'Shadow Pool',
                    'description': 'Void zone at random player',
                    'timer': {'initial': 8000, 'min': 15000, 'max': 20000},
                    'targeting': {'type': 'random_player'},
                    'void_zone': {
                        'visual_spell': 90202,
                        'damage_spell': 90203,
                        'duration': 30000,
                        'radius': 5.0,
                    },
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Storm',
            'const_name': 'PHASE_STORM',
            'hp_range': (50, 0),
            'on_enter': {
                'yell': 'The storm awakens! Feel my wrath!',
                'sound_id': 0,
                'action': {
                    'type': 'apply_buff',
                    'buff_spell': 8599,
                },
            },
            'abilities': [
                {
                    'id': 'lightning_lash',
                    'func_name': 'CastLightningLash',
                    'spell': 'SPELL_LIGHTNING_LASH',
                    'spell_id': 90204,
                    'name': 'Lightning Lash',
                    'description': 'Chain lightning',
                    'timer': {'initial': 3000, 'min': 6000, 'max': 10000},
                    'targeting': {'type': 'random_player'},
                    'chain': {'enabled': True, 'max_targets': 3, 'range': 10.0},
                },
                {
                    'id': 'shadow_bolt_volley_p2',
                    'func_name': 'CastShadowBoltVolleyP2',
                    'spell': 'SPELL_SHADOW_BOLT_VOLLEY',
                    'spell_id': 27831,
                    'name': 'Shadow Bolt Volley',
                    'description': 'Continues from P1',
                    'timer': {'initial': 8000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 2000,
                    'interruptible': True,
                },
            ],
        },
    ],

    'on_death': {
        'yell': 'The darkness... recedes...',
        'sound_id': 0,
        'unlock_door': 0,
    },

    'loot_id': 90700,

    'achievements': [
        {
            'id': 90010,
            'name': 'Shadow Dance',
            'description': 'Kill Storm Shade without anyone hit by Shadow Pool',
            'criteria': 'no_void_zone_hits',
            'tracking': {
                'variable': 'shadow_pool_hits',
                'condition': 'equals',
                'value': 0,
            },
        },
    ],
}

# ---------------------------------------------------------------
# 3. Define the instance
# ---------------------------------------------------------------
instance_def = {
    'name': 'StormVault',
    'display_name': 'Storm Vault',
    'map_id': 801,
    'script_name': 'instance_storm_vault',
    'bosses': [
        {
            'name': 'StormShade',
            'entry': 90700,
            'encounter_id': 0,
            'encounter_name': 'BOSS_STORM_SHADE',
        },
    ],
    'doors': [],
    'events': [],
}

# ---------------------------------------------------------------
# 4. Generate Lua scripts
# ---------------------------------------------------------------
generator = ScriptGenerator(spell_registry=registry)
generator.add_instance_script(instance_def)
generator.add_boss_encounter(boss_def)

# Write scripts to disk
script_paths = generator.write_scripts('./output/scripts/storm_vault/')
print("Written scripts:")
for path in script_paths:
    print(f"  {path}")

# Validate
validation = generator.validate_scripts()
if validation['valid']:
    print("All scripts validated successfully!")
else:
    for err in validation['errors']:
        print(f"ERROR: {err}")
for warn in validation['warnings']:
    print(f"WARNING: {warn}")

# ---------------------------------------------------------------
# 5. Generate server-side SQL
# ---------------------------------------------------------------
sql_gen = SQLGenerator(start_entry=90700, map_id=801, zone_id=9001)

# Boss creature template
sql_gen.add_creatures([
    {
        'entry': 90700,
        'name': 'Storm Shade',
        'subname': '',
        'modelid1': 26693,
        'minlevel': 82,
        'maxlevel': 82,
        'faction': 16,
        'rank': 3,                # Boss rank
        'type': 6,                # Undead
        'health_modifier': 20.0,
        'damage_modifier': 5.0,
        'mechanic_immune_mask': 617299839,  # Boss immunities
        'flags_extra': 1,         # INSTANCE_BIND
        'script_name': 'StormShade',
    },
])

# Add creature templates
sql_gen.add_creatures([
    {
        'entry': 90701,
        'name': 'Darkling Wisp',
        'modelid1': 16946,
        'minlevel': 78,
        'maxlevel': 79,
        'faction': 16,
        'rank': 0,
        'type': 4,
        'health_modifier': 0.5,
        'damage_modifier': 0.3,
    },
])

# Boss spawn
sql_gen.add_spawns([
    {
        'entry': 90700,
        'position': (100.0, 200.0, 50.0, 3.14),
        'spawntimesecs': 604800,  # 7 day respawn (boss)
        'movement_type': 0,
    },
])

sql_gen.write_sql('./output/sql/boss_storm_shade.sql')
print("SQL written to ./output/sql/boss_storm_shade.sql")
```

---

## Step 15: Writing and Deploying Scripts

### 15.1 Script Output Files

The `ScriptGenerator.write_scripts()` method creates:

| File | Purpose |
|------|---------|
| `instance_<name>.lua` | Instance management (door locking, boss tracking, persistence) |
| `boss_<name>.lua` | Individual boss encounter script (one per boss) |
| `spell_constants.lua` | All spell name = ID mappings |
| `spell_config.json` | JSON documentation of all spells |

### 15.2 Deploying to AzerothCore

1. Copy all `.lua` files to your AzerothCore `lua_scripts/` directory (or wherever Eluna loads scripts from)
2. Apply the SQL file to your `acore_world` database
3. Restart the world server (or use `.reload eluna`)

### 15.3 Validation

Always run `validate_scripts()` before deployment:

```python
validation = generator.validate_scripts()
```

The validator checks for:

- Required Lua functions (`OnEnterCombat`, `OnLeaveCombat`, `OnDied`, `GetRandomPlayer`)
- Event registration calls (`RegisterCreatureEvent`, `RegisterInstanceEvent`)
- TODO/FIXME markers (indicates incomplete generation)
- Unresolved spell IDs (spell ID 0 in cast calls)

---

## Common Pitfalls and Troubleshooting

### Boss does not use abilities

- **Cause**: `creature_template.ScriptName` does not match the Eluna script name, or `AIName` is set to `SmartAI` when using Eluna.
- **Fix**: For Eluna bosses, set `ScriptName` to the `script_name` from your boss definition. Leave `AIName` empty (not `'SmartAI'`). SmartAI and Eluna are mutually exclusive per creature.

### Phase transition does not trigger

- **Cause**: The HP percentage check is not being evaluated, or the phase variable is already set.
- **Fix**: Verify the `hp_range` values are correct and do not overlap between phases. The generated script checks `creature:GetHealthPct()` on each timer tick.

### Adds do not spawn

- **Cause**: The add's `creature_template` entry does not exist, or the `SpawnCreature` call uses the wrong entry.
- **Fix**: Verify that creature_template entries exist for all NPCs listed in `boss_def['npcs']`. Check `entry` values match between the summon definition and the creature_template.

### Void zones do not damage players

- **Cause**: The damage aura spell does not exist or the invisible trigger NPC is not hostile.
- **Fix**: Create a `spell_dbc` entry for the damage spell. Verify the void zone trigger creature has `faction` set to 16 (hostile) and has the damage aura applied.

### Scripts not loading after restart

- **Cause**: Lua syntax error preventing the file from loading. Eluna silently skips files with syntax errors.
- **Fix**: Check the world server log for Lua errors. Test the script with `luac -p boss_script.lua` to check for syntax errors.

### "attempt to call a nil value" in Lua

- **Cause**: A function is referenced before it is defined, or a spell constant is undefined.
- **Fix**: Ensure `spell_constants.lua` is loaded before boss scripts. In Eluna, files load in alphabetical order by default.

### Boss instantly dies or has 1 HP

- **Cause**: `health_modifier` is 0 or very low in `creature_template`.
- **Fix**: Set `health_modifier` to an appropriate value. For dungeon bosses, values of 10.0-50.0 are typical. For raid bosses, 100.0+ is common.

### SmartAI creature_text yells do not show

- **Cause**: Missing `creature_text` rows or wrong `GroupID` in the `SMART_ACTION_TALK` action.
- **Fix**: Verify `creature_text.CreatureID` matches the creature entry, and `action_param1` in `smart_scripts` matches the `GroupID` in `creature_text`.

---

## Cross-References

- **[Add New Creature](add_new_creature.md)** -- Prerequisite: creating creature_template entries for bosses and adds
- **[Add Vendor/Trainer](add_vendor_trainer.md)** -- For creating NPCs that sell boss loot or teach spells
- **[Change NPC Pathing](change_npc_pathing.md)** -- For bosses or adds that follow waypoint patrol routes
- **SpellRegistry API** -- `world_builder/spell_registry.py` for spell ID management
- **ScriptGenerator API** -- `world_builder/script_generator.py` for Eluna Lua generation
- **SQLGenerator SmartAI API** -- `world_builder/sql_generator.py` SmartAIBuilder for SQL-only scripting
- **Encounter Definitions** -- `world_builder/encounter_definitions.py` for the complete Vault of Storms example
