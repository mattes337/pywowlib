# Add Object Interaction

| Property | Value |
|---|---|
| **Complexity** | Low |
| **Client-Side Files** | `GameObjectDisplayInfo.dbc` (only for custom models; existing models need no patch) |
| **Server-Side Files** | SQL: `gameobject_template`, `gameobject` (spawns) |
| **pywowlib APIs** | `SQLGenerator.add_gameobject_templates()`, `SQLGenerator.add_gameobject_spawns()`, `SQLGenerator.add_quests()`, `SQLGenerator.add_smartai()` |
| **DBC APIs** | `dbc_injector.DBCInjector` (for `GameObjectDisplayInfo.dbc` custom visuals) |
| **Estimated Time** | 15-30 minutes for basic objects; 30-60 minutes with custom visuals |

## Overview

Gameobjects are the non-creature, non-terrain interactive elements of the world: chests,
quest objects, doors, levers, spell focuses, campfires, chairs, forges, mailboxes, and
hundreds of other clickable or proximity-triggered objects. Every "Wanted" poster on a
wall, every glowing quest item on the ground, and every resource node is a gameobject.

In the AzerothCore database, gameobjects are defined in two tables:
- `gameobject_template` -- the object's type, display model, name, and type-specific data
  fields.
- `gameobject` -- the spawn instances placing the template at specific world coordinates.

If you need a completely new visual appearance (a custom 3D model), you must also inject
a record into the client-side `GameObjectDisplayInfo.dbc` file. However, most quest
objects can reuse existing display IDs from the thousands of models already in the game.

This guide covers:
1. The gameobject type system and the meaning of `data0`-`data23` per type.
2. Linking gameobjects to quests via negative `RequiredNpcOrGo` entries.
3. Creating custom gameobject visuals with `GameObjectDisplayInfo.dbc`.
4. SmartAI scripting for gameobject behavior.
5. Complete code examples for a quest-interactable chest and a clickable quest object.

---

## Prerequisites

- Completion of the [Add New Quest](add_new_quest.md) guide.
- Python 3.8+ with pywowlib available on the Python path.
- An AzerothCore 3.3.5a server for testing.
- For custom visuals: access to the client's `DBFilesClient` directory for DBC patching.

---

## Step 1: Understand the gameobject_template Table

Every gameobject in the game is defined by a template row that specifies its type, visual
model, name, and up to 24 type-specific data fields.

### Core Columns

| Column | Type | Default | Description |
|---|---|---|---|
| `entry` | int | Auto | Primary key. Unique gameobject identifier. |
| `type` | int | 0 | The gameobject type. Determines the meaning of all `data` fields. See the Type Reference below. |
| `displayId` | int | 0 | Display ID from `GameObjectDisplayInfo.dbc`. This is the 3D model shown in the game world. Use `0` for invisible objects (area triggers, traps). |
| `name` | string | '' | The name shown when the player mouses over the object. For quest objects, this appears as the object's tooltip. |
| `IconName` | string | '' | Client-side icon override. Usually empty. |
| `castBarCaption` | string | '' | Text shown on the cast bar when interacting with the object (e.g., "Opening", "Mining", "Collecting"). |
| `unk1` | string | '' | Unknown/unused string field. |
| `size` | float | 1.0 | Visual scale multiplier. `1.0` is default size. `2.0` is double size. |
| `Data0` - `Data23` | int | 0 | Type-specific data fields. See the per-type reference below. |
| `AIName` | string | '' | AI engine name. Set to `'SmartGameObjectAI'` to enable SmartAI scripting on this gameobject. |
| `ScriptName` | string | '' | C++ script name (for core-scripted objects). |

### pywowlib Python Dict Keys

When using `SQLGenerator.add_gameobject_templates()`, pass a dict with these keys:

```python
go_def = {
    'entry': 90200,           # Optional, auto-allocated if omitted
    'type': 3,                # GAMEOBJECT_TYPE_CHEST
    'display_id': 259,        # Existing chest model
    'name': 'Ancient Chest',
    'icon_name': '',
    'cast_bar_caption': 'Opening',
    'size': 1.0,
    'data0': 57,              # Lock ID
    'data1': 43,              # Loot template ID
    # ... data2 through data23 ...
    'ai_name': '',
    'script_name': '',
}
```

---

## Step 2: Understand the Gameobject Type System

The `type` field completely changes the meaning of `Data0` through `Data23`. Each type
represents a fundamentally different game mechanic.

### Gameobject Type Reference

| Type | Value | Name | Description |
|---|---|---|---|
| 0 | GAMEOBJECT_TYPE_DOOR | Door | A door that opens/closes. Used for instance doors, gates. |
| 1 | GAMEOBJECT_TYPE_BUTTON | Button | A clickable button/lever. Opens doors or triggers events. |
| 2 | GAMEOBJECT_TYPE_QUESTGIVER | Quest Giver | An object that offers quests (e.g., a "Wanted" poster). |
| 3 | GAMEOBJECT_TYPE_CHEST | Chest | A lootable container. Herb nodes, mining nodes, and treasure chests. |
| 5 | GAMEOBJECT_TYPE_GENERIC | Generic | A decorative/non-interactive object. Props, scenery. |
| 6 | GAMEOBJECT_TYPE_TRAP | Trap | An invisible proximity trigger that casts a spell. |
| 7 | GAMEOBJECT_TYPE_CHAIR | Chair | A sittable chair. |
| 8 | GAMEOBJECT_TYPE_SPELL_FOCUS | Spell Focus | Required focus for certain spells (forges, moonwells, campfires). |
| 10 | GAMEOBJECT_TYPE_GOOBER | Goober | A clickable quest object. The most common type for quest interactions. |
| 11 | GAMEOBJECT_TYPE_TRANSPORT | Transport | A ship or zeppelin (moving platform). |
| 13 | GAMEOBJECT_TYPE_CAMERA | Camera | Triggers a camera flyby cinematic. |
| 14 | GAMEOBJECT_TYPE_MAP_OBJECT | Map Object | A WMO-based decoration. |
| 22 | GAMEOBJECT_TYPE_SPELL_CASTER | Spell Caster | Casts a spell on the player when used (e.g., summoning stones). |
| 24 | GAMEOBJECT_TYPE_AURA_GENERATOR | Aura Generator | Generates a persistent area aura. |
| 25 | GAMEOBJECT_TYPE_DUNGEON_DIFFICULTY | Dungeon Difficulty | The meeting stone-style difficulty selector. |
| 33 | GAMEOBJECT_TYPE_DESTRUCTIBLE_BUILDING | Destructible | A building that can be attacked and destroyed (Wintergrasp). |

---

## Step 3: Data Field Reference Per Type

Each gameobject type assigns different meanings to the 24 data fields. Below are the most
commonly used types with their complete field mappings.

### Type 2: GAMEOBJECT_TYPE_QUESTGIVER

Objects like "Wanted" posters, bulletin boards, and quest-giving tablets.

| Field | Name | Description |
|---|---|---|
| `Data0` | `lockId` | Lock ID. `0` = no lock (always interactable). |
| `Data1` | `questList` | Quest ID offered by this object. For multiple quests, use `gameobject_queststarter` table. |
| `Data2` | `pageMaterial` | Page material type for the quest text dialog (0=default). |
| `Data3` | `gossipID` | Gossip menu ID shown when right-clicking. |
| `Data4` | `customAnim` | Custom animation index on interaction. |
| `Data5` | `noDamageImmune` | If `1`, the object can be damaged. |
| `Data6` | `openTextID` | Broadcast text ID for open text. |
| `Data7` | `losOK` | Allow interaction through line-of-sight blockers. |
| `Data8` | `allowMounted` | Allow interaction while mounted. |
| `Data9` | `large` | Large object flag. |
| `Data10`-`Data23` | (unused) | Set to `0`. |

### Type 3: GAMEOBJECT_TYPE_CHEST

Lootable containers, resource nodes (herbs, ore), and treasure chests.

| Field | Name | Description |
|---|---|---|
| `Data0` | `lockId` | Lock ID. Determines what opens the chest: `0`=no lock, or reference `Lock.dbc` for keys/skills. |
| `Data1` | `lootId` | Reference to `gameobject_loot_template.Entry`. Defines what items the chest contains. |
| `Data2` | `chestRestockTime` | Restock time in seconds. After looting, the chest respawns its contents after this delay. |
| `Data3` | `consumable` | `1` = single-use (disappears after looting), `0` = reusable. |
| `Data4` | `minSuccessOpens` | Minimum number of successful opens (for shared nodes). |
| `Data5` | `maxSuccessOpens` | Maximum number of successful opens. |
| `Data6` | `eventId` | Event triggered on open (references `event_scripts`). |
| `Data7` | `linkedTrapId` | Gameobject entry of a trap triggered when opened. |
| `Data8` | `questId` | Quest ID required to loot this chest. The chest only appears lootable if the player is on this quest. |
| `Data9` | `level` | Minimum level to interact. |
| `Data10` | `losOK` | Allow interaction through LoS blockers. |
| `Data11` | `leaveLoot` | Leave loot window open after looting. |
| `Data12` | `notInCombat` | Cannot interact while in combat. |
| `Data13` | `logLoot` | Log looting to the server console. |
| `Data14` | `openTextID` | Broadcast text ID. |
| `Data15` | `useGroupLootRules` | Use group loot rules. |
| `Data16` | `floatingTooltip` | Show floating tooltip. |
| `Data17`-`Data23` | (unused) | Set to `0`. |

### Type 8: GAMEOBJECT_TYPE_SPELL_FOCUS

Objects required as a focus for certain spells. Includes forges (for blacksmithing),
campfires (for cooking), and moonwells (for druid spells).

| Field | Name | Description |
|---|---|---|
| `Data0` | `focusId` | Spell focus type ID (from `SpellFocusObject.dbc`). Must match the spell's required focus. |
| `Data1` | `dist` | Maximum distance in yards the player can be from the object while casting. |
| `Data2` | `linkedTrapId` | Trap gameobject triggered when used. |
| `Data3` | `serverOnly` | `1` = server-side only (not sent to client). |
| `Data4` | `questId` | Quest required to interact. |
| `Data5` | `large` | Large object flag. |
| `Data6` | `floatingTooltip` | Show floating tooltip. |
| `Data7`-`Data23` | (unused) | Set to `0`. |

### Type 10: GAMEOBJECT_TYPE_GOOBER

The most versatile type for quest interactions. "Goobers" are clickable objects that
can complete quest objectives, cast spells, open pages, or trigger scripts.

| Field | Name | Description |
|---|---|---|
| `Data0` | `lockId` | Lock ID. `0` = always clickable. |
| `Data1` | `questId` | Quest ID that this object satisfies. When clicked, credit is given for this quest's `RequiredNpcOrGo` (negative entry). |
| `Data2` | `eventId` | Event triggered on use. |
| `Data3` | `autoCloseTime` | Auto-close delay in milliseconds. Object returns to closed state after this time. `0` = stays open. |
| `Data4` | `customAnim` | Custom animation index. |
| `Data5` | `consumable` | `1` = single-use (disappears after interaction). |
| `Data6` | `cooldown` | Cooldown in seconds before the object can be used again. |
| `Data7` | `pageId` | Page text ID shown when interacting (from `page_text` table). |
| `Data8` | `language` | Language of the page text. |
| `Data9` | `pageMaterial` | Page material type. |
| `Data10` | `spellId` | Spell cast on the player when interacting. |
| `Data11` | `noDamageImmune` | Object can be damaged. |
| `Data12` | `linkedTrapId` | Trap triggered on interaction. |
| `Data13` | `large` | Large object flag. |
| `Data14` | `openTextID` | Broadcast text ID. |
| `Data15` | `closeTextID` | Close broadcast text ID. |
| `Data16` | `losOK` | Allow interaction through LoS. |
| `Data17` | `allowMounted` | Allow interaction while mounted. |
| `Data18` | `floatingTooltip` | Show floating tooltip. |
| `Data19` | `gossipID` | Gossip menu ID. |
| `Data20`-`Data23` | (unused) | Set to `0`. |

### Type 0: GAMEOBJECT_TYPE_DOOR

Instance doors, gates, and portcullises.

| Field | Name | Description |
|---|---|---|
| `Data0` | `startOpen` | `1` = door starts in open state. |
| `Data1` | `lockId` | Lock required to open. |
| `Data2` | `autoCloseTime` | Auto-close delay in milliseconds. |
| `Data3` | `noDamageImmune` | Object can be damaged. |
| `Data4` | `openTextID` | Broadcast text on open. |
| `Data5` | `closeTextID` | Broadcast text on close. |
| `Data6`-`Data23` | (unused) | Set to `0`. |

### Type 1: GAMEOBJECT_TYPE_BUTTON

Levers, switches, and buttons that activate other objects.

| Field | Name | Description |
|---|---|---|
| `Data0` | `startOpen` | `1` = button starts in pressed/open state. |
| `Data1` | `lockId` | Lock required to activate. |
| `Data2` | `autoCloseTime` | Auto-reset delay in milliseconds. |
| `Data3` | `linkedTrapId` | Trap triggered on activation. |
| `Data4` | `noDamageImmune` | Object can be damaged. |
| `Data5` | `large` | Large object flag. |
| `Data6` | `openTextID` | Broadcast text on activation. |
| `Data7` | `closeTextID` | Broadcast text on deactivation. |
| `Data8` | `losOK` | Allow activation through LoS. |
| `Data9`-`Data23` | (unused) | Set to `0`. |

### Type 6: GAMEOBJECT_TYPE_TRAP

Invisible proximity triggers that cast spells when a player comes near.

| Field | Name | Description |
|---|---|---|
| `Data0` | `lockId` | Lock ID (usually `0` for traps). |
| `Data1` | `level` | Trap level. |
| `Data2` | `radius` | Detection radius in yards. |
| `Data3` | `spellId` | Spell cast when triggered. |
| `Data4` | `charges` | Number of charges (uses) before despawning. `0` = unlimited. |
| `Data5` | `cooldown` | Cooldown between activations in seconds. |
| `Data6` | `autoCloseTime` | Auto-close/reset delay in milliseconds. |
| `Data7` | `startDelay` | Delay before first activation after spawn. |
| `Data8` | `serverOnly` | `1` = not visible to client. |
| `Data9` | `stealthed` | Object is stealthed (requires detection). |
| `Data10` | `large` | Large object flag. |
| `Data11` | `stealthAffected` | Affected by stealth detection. |
| `Data12` | `openTextID` | Broadcast text on trigger. |
| `Data13` | `closeTextID` | Broadcast text on reset. |
| `Data14`-`Data23` | (unused) | Set to `0`. |

---

## Step 4: Understand the gameobject Spawn Table

The `gameobject` table places instances of a template at specific world coordinates.

### gameobject Table Schema

| Column | Type | Default | Description |
|---|---|---|---|
| `guid` | int | Auto | Unique spawn GUID. Auto-allocated by pywowlib. |
| `id` | int | -- | Gameobject template entry ID (FK to `gameobject_template.entry`). |
| `map` | int | gen.map_id | Map ID where the object spawns. |
| `zoneId` | int | gen.zone_id | Zone ID. |
| `areaId` | int | zone_id | Sub-area ID. |
| `spawnMask` | int | 1 | Difficulty mask. `1` = normal, `2` = heroic, `3` = both. |
| `phaseMask` | int | 1 | Phase mask. `1` = default phase. Use for phased content. |
| `position_x` | float | 0 | X world coordinate. |
| `position_y` | float | 0 | Y world coordinate. |
| `position_z` | float | 0 | Z world coordinate (height). |
| `orientation` | float | 0 | Facing direction in radians (0 to 2*pi). |
| `rotation0` | float | 0 | Quaternion rotation component 0. |
| `rotation1` | float | 0 | Quaternion rotation component 1. |
| `rotation2` | float | 0 | Quaternion rotation component 2 (sin(orientation/2)). |
| `rotation3` | float | 1 | Quaternion rotation component 3 (cos(orientation/2)). |
| `spawntimesecs` | int | 120 | Respawn time in seconds after despawning. |
| `animprogress` | int | 0 | Animation progress (0-255). Usually `100` for fully visible objects. |
| `state` | int | 1 | Initial state. `0` = activated/open, `1` = ready/closed. |
| `ScriptName` | string | '' | C++ script name. |

### Rotation Quaternion

For most objects, the orientation (facing direction) is sufficient. However, objects
that are tilted or rotated in 3D space require the full quaternion. For flat objects
(no tilt), use:

```python
import math

orientation = 1.57  # Facing north (radians)
rotation = (
    0,                                    # rotation0
    0,                                    # rotation1
    math.sin(orientation / 2),            # rotation2
    math.cos(orientation / 2),            # rotation3
)
```

---

## Step 5: Linking Gameobjects to Quests

Gameobjects serve as quest objectives through the `RequiredNpcOrGo` fields in
`quest_template`. The key rule is:

**Negative `RequiredNpcOrGo` values indicate gameobject entries.**

For example, if your gameobject template has entry `90200`, the quest's
`required_npc_or_go` list should use `-90200`.

### How It Works

1. The quest's `RequiredNpcOrGo1` (or 2, 3, 4) is set to the **negative** of the
   gameobject entry.
2. The gameobject template's `Data1` (for Type 10 GOOBER) is set to the quest ID.
3. When the player clicks the object and is on the quest, the objective counter
   increments.

```python
# Quest definition
quest_def = {
    'required_npc_or_go': [
        (-90200, 3),    # Interact with gameobject 90200 three times
    ],
    # ...
}

# Gameobject definition (Type 10 = GOOBER)
go_def = {
    'entry': 90200,
    'type': 10,                  # GOOBER
    'data1': quest_entry,        # The quest this object satisfies
    'data5': 0,                  # Not consumable (stays for other players)
    'data3': 10000,              # Auto-close after 10 seconds
    # ...
}
```

---

## Step 6: GameObjectDisplayInfo.dbc -- Custom Visuals

If you need a custom 3D model for your gameobject that does not exist in the default
game data, you must inject a new record into `GameObjectDisplayInfo.dbc`.

### GameObjectDisplayInfo.dbc Field Layout (WotLK 3.3.5)

The WotLK 3.3.5 layout (builds 3.0.1.8622 - 3.3.5.12340) has the following structure:

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | `ID` | uint32 | Unique display info identifier. |
| 1 | `ModelName` | string | Path to the `.wmo` or `.m2` model file (e.g., `World\\Generic\\Human\\Passive Doodads\\Crates\\BrokenCrate01.m2`). |
| 2-11 | `Sound[10]` | uint32[10] | Sound IDs for 10 interaction events (open, close, destroy, etc.). |
| 12-14 | `GeoBoxMin[3]` | float[3] | Bounding box minimum corner (x, y, z). |
| 15-17 | `GeoBoxMax[3]` | float[3] | Bounding box maximum corner (x, y, z). |
| 18 | `ObjectEffectPackageID` | uint32 | Visual effect package ID. |

**Total:** 19 fields.

### Using DBCInjector for Custom GameObjectDisplayInfo

The pywowlib `DBCInjector` class can read and write DBC files at the binary level.
While there is no dedicated `register_gameobject_display_info()` convenience function
(unlike `register_area_trigger()`), you can use the low-level API directly.

```python
import struct
from world_builder.dbc_injector import DBCInjector

def register_gameobject_display(dbc_dir, model_path, display_id=None,
                                 geo_box_min=(0, 0, 0),
                                 geo_box_max=(1, 1, 1)):
    """
    Inject a custom GameObjectDisplayInfo.dbc record.

    Args:
        dbc_dir: Path to directory containing GameObjectDisplayInfo.dbc.
        model_path: Path to the .m2 or .wmo model file (game-relative).
        display_id: Specific ID or None for auto-assignment.
        geo_box_min: Bounding box min corner (x, y, z).
        geo_box_max: Bounding box max corner (x, y, z).

    Returns:
        int: The assigned display ID.
    """
    import os
    filepath = os.path.join(dbc_dir, 'GameObjectDisplayInfo.dbc')
    dbc = DBCInjector(filepath)

    if display_id is None:
        display_id = dbc.get_max_id() + 1

    # Add model path string to string block
    model_offset = dbc.add_string(model_path)

    # Build the record (19 fields, 76 bytes)
    buf = bytearray()

    # Field 0: ID
    buf += struct.pack('<I', display_id)

    # Field 1: ModelName (string offset)
    buf += struct.pack('<I', model_offset)

    # Fields 2-11: Sound[10] (all zeros)
    for _ in range(10):
        buf += struct.pack('<I', 0)

    # Fields 12-14: GeoBoxMin[3]
    for v in geo_box_min:
        buf += struct.pack('<f', v)

    # Fields 15-17: GeoBoxMax[3]
    for v in geo_box_max:
        buf += struct.pack('<f', v)

    # Field 18: ObjectEffectPackageID
    buf += struct.pack('<I', 0)

    assert len(buf) == 76, "Record size mismatch: expected 76, got {}".format(len(buf))

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return display_id
```

### Finding Existing Display IDs

Before creating custom display info, check if a suitable model already exists. The game
ships with thousands of gameobject models. You can find display IDs using:

1. **In-game GM commands:**
   ```
   .gobject near 50          -- List nearby gameobjects with their entries
   .lookup gobject <name>    -- Search gameobjects by name
   .gobject info             -- Show info about targeted gameobject
   ```

2. **Database queries:**
   ```sql
   SELECT entry, type, displayId, name
   FROM gameobject_template
   WHERE name LIKE '%chest%'
   ORDER BY entry;
   ```

3. **Common display IDs for quest objects:**
   | Display ID | Description |
   |---|---|
   | 259 | Small wooden chest |
   | 3366 | Glowing quest object (purple) |
   | 6622 | Campfire |
   | 6784 | Cauldron |
   | 2560 | Document/scroll on table |
   | 4970 | Barrel |
   | 7905 | Cage (breakable) |
   | 8236 | Crystal formation (blue glow) |

---

## Step 7: SmartAI for Gameobject Scripting

Gameobjects can use SmartAI for scripted behavior when `AIName` is set to
`'SmartGameObjectAI'`. SmartAI scripts for gameobjects use `source_type = 1`
(SMART_SOURCE_GAMEOBJECT) in the `smart_scripts` table.

### SmartAI Gameobject Events

| Event Type | Value | Event Name | Description |
|---|---|---|---|
| 61 | SMART_EVENT_GOSSIP_HELLO | On gossip hello | Player right-clicks the object. |
| 62 | SMART_EVENT_GOSSIP_SELECT | On gossip select | Player selects a gossip option. |
| 64 | SMART_EVENT_GO_STATE_CHANGED | State changed | Object state changes (open/close). |
| 70 | SMART_EVENT_GO_EVENT_INFORM | Event inform | Object receives an event. |
| 71 | SMART_EVENT_ACTION_DONE | Action done | Previous action completed. |
| 72 | SMART_EVENT_ON_SPELLCLICK | Spell click | Player spell-clicks the object. |

### SmartAI Gameobject Actions

| Action Type | Value | Description | Param1 | Param2 |
|---|---|---|---|---|
| 1 | SMART_ACTION_TALK | Say text | creature_text.GroupID | 0 |
| 11 | SMART_ACTION_CAST | Cast spell | Spell ID | Cast flags |
| 9 | SMART_ACTION_ACTIVATE_GOBJECT | Activate | 0 | 0 |
| 33 | SMART_ACTION_SET_IN_COMBAT_WITH_ZONE | Zone combat | 0 | 0 |
| 12 | SMART_ACTION_OFFER_QUEST | Offer quest | Quest ID | Direct (0/1) |
| 99 | SMART_ACTION_SEND_GOSSIP_MENU | Send gossip | MenuID | TextID |
| 62 | SMART_ACTION_SET_COUNTER | Set counter | CounterID | Value |

### Example: Gameobject that casts a buff on interaction

```python
from world_builder.sql_generator import (
    SQLGenerator, BaseBuilder,
    SMART_SOURCE_GAMEOBJECT, SMART_TARGET_SELF,
)

gen = SQLGenerator(start_entry=90200, map_id=0, zone_id=12)

# Create the gameobject template with SmartAI enabled
gen.add_gameobject_templates([
    {
        'entry': 90200,
        'type': 10,                  # GOOBER
        'display_id': 8236,          # Blue crystal
        'name': 'Moonwell Crystal',
        'cast_bar_caption': 'Channeling',
        'size': 1.5,
        'data0': 0,                  # No lock
        'data3': 5000,               # Auto-close after 5 seconds
        'ai_name': 'SmartGameObjectAI',
    },
])

# Add SmartAI script manually (gameobjects use source_type=1)
helper = BaseBuilder(gen)
smart_cols = [
    'entryorguid', 'source_type', 'id', 'link',
    'event_type', 'event_phase_mask', 'event_chance', 'event_flags',
    'event_param1', 'event_param2', 'event_param3', 'event_param4',
    'event_param5',
    'action_type',
    'action_param1', 'action_param2', 'action_param3',
    'action_param4', 'action_param5', 'action_param6',
    'target_type',
    'target_param1', 'target_param2', 'target_param3', 'target_param4',
    'target_x', 'target_y', 'target_z', 'target_o',
    'comment',
]

smart_rows = [
    [
        90200,       # entryorguid: gameobject entry
        1,           # source_type: SMART_SOURCE_GAMEOBJECT
        0,           # id: script line 0
        0,           # link: no chain
        64,          # event_type: SMART_EVENT_GO_STATE_CHANGED
        0,           # event_phase_mask
        100,         # event_chance: 100%
        0,           # event_flags
        0, 0, 0, 0, 0,  # event params (not used for state change)
        11,          # action_type: SMART_ACTION_CAST
        34076,       # action_param1: spell ID (Mark of the Wild rank 1, example)
        0, 0, 0, 0, 0,
        7,           # target_type: SMART_TARGET_ACTION_INVOKER (the player)
        0, 0, 0, 0,
        0, 0, 0, 0,
        'Moonwell Crystal - On State Change - Cast buff on player',
    ],
]

sql = helper.format_insert('smart_scripts', smart_cols, smart_rows,
                           comment='-- SmartAI: Moonwell Crystal')
helper.add_sql('smart_scripts', sql)
```

---

## Step 8: Complete Code Example -- Quest Object Interaction

This example creates a complete quest where the player must click 3 "Corrupted
Mushroom Cluster" objects in a mine, linked to the quest chain from
[Create Quest Chain](create_quest_chain.md).

```python
#!/usr/bin/env python3
"""
Complete example: Quest with gameobject interaction objectives.

Creates:
  - 3 Corrupted Mushroom Cluster gameobjects (Type 10 GOOBER)
  - A quest requiring interaction with all 3
  - A quest-giver NPC
  - All spawn positions

Output: output/mushroom_quest.sql
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator


def main():
    gen = SQLGenerator(start_entry=90300, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 1. Create the quest-giver NPC
    # ---------------------------------------------------------------
    gen.add_npcs([
        {
            'entry': 90300,
            'name': 'Botanist Elara',
            'subname': 'Fungal Researcher',
            'minlevel': 12,
            'maxlevel': 12,
            'faction': 12,
            'npcflag': 2,           # Quest giver
            'modelid1': 4720,       # Night elf female model
            'type': 7,              # Humanoid
            'health_modifier': 1.0,
            'gossip_menu_id': 90300,
            'gossip_text': (
                'I have been studying the unusual fungal growths appearing '
                'in the mine. The spore patterns are unlike anything in my '
                'reference texts.'
            ),
        },
    ])

    # ---------------------------------------------------------------
    # 2. Create the gameobject templates
    # ---------------------------------------------------------------
    # These are Type 10 (GOOBER) quest objects.
    # The player clicks them to "investigate" the mushroom cluster.
    gen.add_gameobject_templates([
        {
            'entry': 90301,
            'type': 10,                  # GOOBER (clickable quest object)
            'display_id': 2844,          # Mushroom cluster model
            'name': 'Corrupted Mushroom Cluster',
            'cast_bar_caption': 'Investigating',
            'size': 1.5,

            # GOOBER data fields:
            'data0': 0,                  # lockId: no lock
            'data1': 90302,              # questId: the quest this satisfies
            'data3': 10000,              # autoCloseTime: 10 seconds (ms)
            'data5': 0,                  # consumable: no (stays for others)
            'data6': 0,                  # cooldown: no per-player cooldown
        },
    ])

    # ---------------------------------------------------------------
    # 3. Create the quest
    # ---------------------------------------------------------------
    gen.add_quests([
        {
            'entry': 90302,
            'title': 'Catalog the Corruption',
            'quest_type': 2,
            'quest_level': 9,
            'min_level': 6,
            'quest_sort': 12,

            'flags': 8,                  # Sharable

            # IMPORTANT: Negative entry = gameobject!
            # The player must interact with 3 instances of gameobject 90301.
            'required_npc_or_go': [
                (-90301, 3),             # Interact with 3 Corrupted Mushroom Clusters
            ],
            'objective_text': [
                'Mushroom Clusters investigated',
            ],

            'reward_xp_difficulty': 3,
            'reward_money': 800,

            'quest_giver_entry': 90300,  # Botanist Elara
            'quest_ender_entry': 90300,  # Same NPC

            'log_description': (
                'I need samples from the corrupted mushroom clusters growing '
                'deep in the mine. There should be three distinct clusters '
                'in the lower chambers.$B$B'
                'Approach each cluster and take a sample. Be careful -- the '
                'spores may attract nearby creatures.'
            ),
            'quest_description': (
                'Investigate 3 Corrupted Mushroom Clusters in the mine.'
            ),
            'quest_completion_log': (
                'Return to Botanist Elara with your samples.'
            ),
        },
    ])

    # ---------------------------------------------------------------
    # 4. Spawn the NPC
    # ---------------------------------------------------------------
    gen.add_spawns([
        {
            'entry': 90300,
            'position': (-9310.0, -115.0, 63.0, 4.71),
            'spawntimesecs': 60,
            'wander_distance': 0,
            'movement_type': 0,
        },
    ])

    # ---------------------------------------------------------------
    # 5. Spawn the gameobjects
    # ---------------------------------------------------------------
    # Place 3 mushroom clusters at different locations in the mine.
    # Each has a unique position but uses the same template.
    mushroom_positions = [
        (-9340.0, -130.0, 58.0, 0.0),    # Deep chamber 1
        (-9360.0, -100.0, 55.0, 1.57),   # Deep chamber 2
        (-9380.0, -120.0, 52.0, 3.14),   # Deepest chamber
    ]

    for pos in mushroom_positions:
        gen.add_gameobject_spawns([
            {
                'entry': 90301,
                'position': pos,
                'spawntimesecs': 120,    # Respawn after 2 minutes
                'animprogress': 100,     # Fully visible
                'state': 1,              # Ready state
            },
        ])

    # ---------------------------------------------------------------
    # 6. Validate and write
    # ---------------------------------------------------------------
    result = gen.validate()

    if result['errors']:
        print("ERRORS:")
        for err in result['errors']:
            print("  [ERROR] {}".format(err))
        sys.exit(1)

    if result['warnings']:
        print("Warnings:")
        for warn in result['warnings']:
            print("  [WARN] {}".format(warn))

    os.makedirs('output', exist_ok=True)
    output_path = os.path.join('output', 'mushroom_quest.sql')
    gen.write_sql(output_path)

    print("Gameobject quest SQL written to: {}".format(
        os.path.abspath(output_path)))


if __name__ == '__main__':
    main()
```

---

## Step 9: Complete Code Example -- Lootable Chest

This example creates a treasure chest that contains quest-required items and can only
be looted while on the quest.

```python
#!/usr/bin/env python3
"""
Complete example: Lootable quest chest with quest-required items.

Creates:
  - A chest gameobject (Type 3)
  - A quest item that drops from the chest
  - A collection quest
  - Loot table entries

Output: output/quest_chest.sql
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.sql_generator import SQLGenerator


def main():
    gen = SQLGenerator(start_entry=90400, map_id=0, zone_id=12)

    # ---------------------------------------------------------------
    # 1. Create the quest item (found in the chest)
    # ---------------------------------------------------------------
    gen.add_items([
        {
            'entry': 90400,
            'name': 'Ancient Rune Fragment',
            'class': 12,             # Quest item
            'subclass': 0,
            'quality': 1,            # Common (white)
            'bonding': 4,            # Quest binding
            'max_count': 5,
            'stackable': 5,
            'description': 'A fragment of an ancient dwarven rune stone.',
        },
    ])

    # ---------------------------------------------------------------
    # 2. Create the NPC
    # ---------------------------------------------------------------
    gen.add_npcs([
        {
            'entry': 90401,
            'name': 'Archaeologist Brynn',
            'subname': 'Explorers League',
            'minlevel': 15,
            'maxlevel': 15,
            'faction': 12,
            'npcflag': 2,
            'modelid1': 3253,
            'type': 7,
            'health_modifier': 1.0,
            'gossip_menu_id': 90401,
            'gossip_text': 'The ruins hold many secrets. Help me uncover them.',
        },
    ])

    # ---------------------------------------------------------------
    # 3. Create the chest gameobject template
    # ---------------------------------------------------------------
    gen.add_gameobject_templates([
        {
            'entry': 90402,
            'type': 3,                  # CHEST
            'display_id': 259,          # Standard wooden chest model
            'name': 'Runed Stone Chest',
            'cast_bar_caption': 'Opening',
            'size': 1.0,

            # Chest data fields:
            'data0': 0,                 # lockId: no lock (anyone can open)
            'data1': 90402,             # lootId: references gameobject_loot_template
            'data2': 0,                 # chestRestockTime: no restock
            'data3': 0,                 # consumable: not consumable (stays)
            'data4': 1,                 # minSuccessOpens
            'data5': 1,                 # maxSuccessOpens
            'data8': 90403,             # questId: only lootable on this quest
        },
    ])

    # ---------------------------------------------------------------
    # 4. Create loot table for the chest
    # ---------------------------------------------------------------
    gen.add_loot('gameobject_loot_template', 90402, [
        {
            'item': 90400,             # Ancient Rune Fragment
            'chance': 100.0,           # Always drops
            'quest_required': 1,       # Only drops when on quest
            'min': 1,
            'max': 2,                  # Drops 1-2 fragments per chest
            'comment': 'Ancient Rune Fragment (quest item)',
        },
    ])

    # ---------------------------------------------------------------
    # 5. Create the collection quest
    # ---------------------------------------------------------------
    gen.add_quests([
        {
            'entry': 90403,
            'title': 'Fragments of the Past',
            'quest_type': 2,
            'quest_level': 12,
            'min_level': 8,
            'quest_sort': 12,

            'flags': 8 | 131072,        # Sharable + show item in tracker

            # Item collection objective
            'required_item': [
                (90400, 5),              # Collect 5 Ancient Rune Fragments
            ],

            'reward_xp_difficulty': 4,
            'reward_money': 1200,

            'quest_giver_entry': 90401,
            'quest_ender_entry': 90401,

            'log_description': (
                'The ancient dwarves who built these tunnels left behind '
                'stone chests filled with runed fragments. I believe these '
                'fragments, when assembled, will reveal a map to a much '
                'greater treasure.$B$B'
                'Search the mine tunnels for Runed Stone Chests and collect '
                'five fragments for me.'
            ),
            'quest_description': (
                'Collect 5 Ancient Rune Fragments from Runed Stone Chests.'
            ),
            'quest_completion_log': (
                'Bring the fragments to Archaeologist Brynn.'
            ),
        },
    ])

    # ---------------------------------------------------------------
    # 6. Spawn everything
    # ---------------------------------------------------------------
    # NPC spawn
    gen.add_spawns([
        {
            'entry': 90401,
            'position': (-9300.0, -105.0, 65.0, 2.35),
            'spawntimesecs': 60,
        },
    ])

    # Chest spawns (7 chests for 5-collect objective, spread through mine)
    chest_positions = [
        (-9325.0, -120.0, 60.0, 0.0),
        (-9340.0, -105.0, 58.0, 1.57),
        (-9355.0, -130.0, 56.0, 3.14),
        (-9370.0, -115.0, 54.0, 4.71),
        (-9385.0, -100.0, 52.0, 0.78),
        (-9350.0, -95.0, 57.0, 2.35),
        (-9365.0, -140.0, 53.0, 5.49),
    ]

    for pos in chest_positions:
        gen.add_gameobject_spawns([
            {
                'entry': 90402,
                'position': pos,
                'spawntimesecs': 180,     # 3 minute respawn
                'animprogress': 100,
                'state': 1,               # Closed/ready
            },
        ])

    # ---------------------------------------------------------------
    # 7. Validate and write
    # ---------------------------------------------------------------
    result = gen.validate()

    if result['errors']:
        print("ERRORS:")
        for err in result['errors']:
            print("  [ERROR] {}".format(err))
        sys.exit(1)

    if result['warnings']:
        print("Warnings:")
        for warn in result['warnings']:
            print("  [WARN] {}".format(warn))

    os.makedirs('output', exist_ok=True)
    gen.write_sql(os.path.join('output', 'quest_chest.sql'))
    print("Quest chest SQL written to output/quest_chest.sql")


if __name__ == '__main__':
    main()
```

---

## Common Pitfalls and Troubleshooting

### Object does not appear in the world

| Symptom | Cause | Fix |
|---|---|---|
| Object invisible | `displayId = 0` | Set a valid display ID from `GameObjectDisplayInfo.dbc`. |
| Object invisible | Wrong map/zone/coordinates | Verify coordinates are on the correct map. Use `.gps` in-game. |
| Object visible but not clickable | Wrong `type` | Ensure the type matches the desired behavior (10 for GOOBER). |
| Object appears underground | Z coordinate too low | Adjust the Z position. Use `.gps` at the target location. |

### Quest objective does not increment

| Symptom | Cause | Fix |
|---|---|---|
| Clicking does nothing | `RequiredNpcOrGo` not negative | Gameobjects need **negative** entries: `-90301`, not `90301`. |
| Clicking does nothing | `data1` (questId) mismatch | For GOOBER objects, `data1` must match the quest entry. |
| Clicking gives "no quest" error | Player not on the quest | Accept the quest first, then interact. |
| Only works once per spawn | `data5 = 1` (consumable) | Set `data5 = 0` for reusable objects. |

### Chest loot problems

| Symptom | Cause | Fix |
|---|---|---|
| Chest has no loot | `data1` (lootId) mismatch | Must match `gameobject_loot_template.Entry`. |
| Quest items do not drop | `quest_required` not set | Set `quest_required: 1` in loot definition. |
| Chest not lootable | `data8` (questId) blocks non-quest players | Remove or set `data8 = 0` for public chests. |

### Custom model issues

| Symptom | Cause | Fix |
|---|---|---|
| Pink/missing texture | Model path wrong in DBC | Verify the path uses backslashes and matches the MPQ structure. |
| Model too large/small | Bounding box wrong | Adjust `GeoBoxMin`/`GeoBoxMax` values in the DBC record. |
| Client crash on approach | Corrupted DBC | Regenerate the DBC from scratch. Verify record size. |

---

## Cross-References

- **[Add New Quest](add_new_quest.md)** -- Detailed reference for quest_template fields,
  including `RequiredNpcOrGo` with negative gameobject entries.
- **[Create Quest Chain](create_quest_chain.md)** -- Chain gameobject-interaction quests
  together using PrevQuestID/NextQuestID.
- **[Custom Teleporter](custom_teleporter.md)** -- Gameobjects can also serve as
  teleportation triggers using Type 6 (TRAP) with teleport spells.
