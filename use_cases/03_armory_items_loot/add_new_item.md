# Add New Item

**Complexity:** Advanced | **Estimated Time:** 30-60 minutes | **Files Modified:** 3+ DBC files, 1+ SQL files, MPQ archive

## Overview

This guide walks through every step of creating a fully custom item in WoW WotLK 3.3.5a using pywowlib. A complete item requires coordinated entries across multiple systems:

1. **Item.dbc** (client-side) -- Registers the item's class, subclass, material type, inventory slot, sheathe animation, and links to its visual display entry.
2. **ItemDisplayInfo.dbc** (client-side) -- Connects the item to its 3D model (.m2), textures (.blp), inventory icon, and particle effects.
3. **.m2 and .blp asset files** (client-side) -- The actual 3D model geometry and texture bitmaps, placed inside a custom MPQ patch archive.
4. **item_template SQL** (server-side) -- Defines every gameplay-relevant property: stats, damage, armor, required level, class restrictions, sockets, set membership, on-equip spells, durability, and pricing.

If any one of these layers is missing or misconfigured, the item will either be invisible, crash the client, or simply not function on the server.

## Prerequisites

- Python 3.7 or later
- pywowlib repository cloned and importable (`world_builder/` on your Python path)
- Extracted DBC files from `DBFilesClient/` (via MPQ extraction or previous pipeline step)
- An MPQ editor (MPQ Editor by Ladik, or StormLib-based tool) for packing asset files
- AzerothCore (or TrinityCore) 3.3.5a database with `acore_world` schema
- Basic familiarity with WoW item classes, subclasses, and inventory types

## Table of Contents

1. [Step 1: Understand the Item Data Model](#step-1-understand-the-item-data-model)
2. [Step 2: Create the Item.dbc Entry](#step-2-create-the-itemdbc-entry)
3. [Step 3: Create the ItemDisplayInfo.dbc Entry](#step-3-create-the-itemdisplayinfodbc-entry)
4. [Step 4: Place Model and Texture Files in MPQ](#step-4-place-model-and-texture-files-in-mpq)
5. [Step 5: Generate item_template SQL](#step-5-generate-item_template-sql)
6. [Step 6: Complete Working Example](#step-6-complete-working-example)
7. [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
8. [Reference Tables](#reference-tables)
9. [Cross-References](#cross-references)

---

## Step 1: Understand the Item Data Model

An item in WoW 3.3.5a is split across client-side DBC files and a server-side SQL table. The client needs the DBC entries to render the item visually and play the correct sounds. The server needs the `item_template` row to enforce stats, restrictions, and gameplay behavior.

### Data Flow Diagram

```
item_template.entry  ------>  Item.dbc.ID  (must match)
item_template.displayid  -->  ItemDisplayInfo.dbc.ID
                                   |
                                   +---> ModelName[0] / ModelName[1]  ---> .m2 file in MPQ
                                   +---> ModelTexture[0/1]            ---> .blp file in MPQ
                                   +---> InventoryIcon[0/1]           ---> Interface\Icons\*.blp
                                   +---> Texture[0..7]                ---> Character texture overrides
```

### Key ID Relationships

| Server Column | DBC File | DBC Field | Purpose |
|---|---|---|---|
| `item_template.entry` | `Item.dbc` | `ID` | Must be identical; links server to client |
| `item_template.displayid` | `Item.dbc` | `DisplayInfoID` | Points to visual definition |
| `item_template.displayid` | `ItemDisplayInfo.dbc` | `ID` | Must match DisplayInfoID above |
| `item_template.class` | `Item.dbc` | `ClassID` | Should match for consistency |
| `item_template.subclass` | `Item.dbc` | `SubclassID` | Should match for consistency |
| `item_template.InventoryType` | `Item.dbc` | `InventoryType` | Must match; determines equip slot |
| `item_template.Material` | `Item.dbc` | `Material` | Controls impact/footstep sounds |
| `item_template.sheath` | `Item.dbc` | `SheatheType` | Where weapon appears when sheathed |

---

## Step 2: Create the Item.dbc Entry

### Item.dbc Field Layout (WotLK 3.3.5a build 12340)

The WotLK Item.dbc has 8 fields per record, each 32 bits (4 bytes), for a total record size of 32 bytes.

| Field Index | Byte Offset | Field Name | Type | Description |
|---|---|---|---|---|
| 0 | 0 | ID | uint32 | Unique item ID. Must match `item_template.entry` |
| 1 | 4 | ClassID | uint32 | Item class (0=Consumable, 2=Weapon, 4=Armor, ...) |
| 2 | 8 | SubclassID | uint32 | Item subclass within class (e.g. class=2 subclass=7 = Swords) |
| 3 | 12 | Sound_override_subclassID | int32 | Override for sound selection (-1 = use SubclassID) |
| 4 | 16 | Material | uint32 | Material type for sounds (1=Metal, 2=Wood, 3=Liquid, 4=Jewelry, 5=Chain, 6=Plate, 7=Cloth, 8=Leather) |
| 5 | 20 | DisplayInfoID | uint32 | FK to ItemDisplayInfo.dbc -- controls model/texture/icon |
| 6 | 24 | InventoryType | uint32 | Equipment slot (see reference table below) |
| 7 | 28 | SheatheType | uint32 | Where weapon is drawn when sheathed (0=None, 1=TwoHandLeft, 2=TwoHandRight, 3=Staff/Polearm back, 4=Shield left, 5=Quiver right hip, 6=Quiver back, 7=OneHand left hip) |

### Python Code: Inject Item.dbc Record

```python
import struct
from world_builder.dbc_injector import DBCInjector

def create_item_dbc_entry(
    dbc_dir,
    item_id,
    class_id,
    subclass_id,
    display_info_id,
    inventory_type,
    material=1,
    sound_override=-1,
    sheathe_type=0,
):
    """
    Create a new Item.dbc record for WotLK 3.3.5a.

    Args:
        dbc_dir: Path to directory containing Item.dbc.
        item_id: Unique item ID (must match item_template.entry).
        class_id: Item class (0=Consumable, 2=Weapon, 4=Armor, etc.).
        subclass_id: Item subclass (depends on class_id).
        display_info_id: FK to ItemDisplayInfo.dbc.
        inventory_type: Equipment slot type (see InventoryType table).
        material: Material for sound effects (1=Metal, 2=Wood, etc.).
        sound_override: Sound override subclass (-1 = use subclass_id).
        sheathe_type: Sheathe position for weapons.

    Returns:
        int: The item_id that was injected.
    """
    import os
    filepath = os.path.join(dbc_dir, 'Item.dbc')
    dbc = DBCInjector(filepath)

    # Item.dbc WotLK layout: 8 fields, 32 bytes per record
    # All fields are uint32 except Sound_override_subclassID which is int32
    record = struct.pack(
        '<IIIiIIII',  # Note: field 3 is signed int32
        item_id,              # 0: ID
        class_id,             # 1: ClassID
        subclass_id,          # 2: SubclassID
        sound_override,       # 3: Sound_override_subclassID (-1 = default)
        material,             # 4: Material
        display_info_id,      # 5: DisplayInfoID
        inventory_type,       # 6: InventoryType
        sheathe_type,         # 7: SheatheType
    )

    assert len(record) == 32, (
        "Item.dbc record size mismatch: expected 32, got {}".format(len(record))
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return item_id


# Example: Register a one-handed sword
create_item_dbc_entry(
    dbc_dir='C:/wow335/DBFilesClient',
    item_id=90001,
    class_id=2,           # Weapon
    subclass_id=7,        # Sword (one-handed)
    display_info_id=80001,  # Our custom ItemDisplayInfo entry
    inventory_type=13,    # INVTYPE_WEAPON (one-hand)
    material=1,           # Metal
    sound_override=-1,    # Use default sword sounds
    sheathe_type=3,       # Left hip sheathe
)
```

### Item Class Reference

| Class ID | Name | Common Subclasses |
|---|---|---|
| 0 | Consumable | 0=Generic, 1=Potion, 2=Elixir, 3=Flask, 5=Food/Drink, 8=Scroll |
| 1 | Container | 0=Bag, 1=Soul Bag, 2=Herb Bag, 3=Enchanting Bag |
| 2 | Weapon | 0=1H Axe, 1=2H Axe, 2=Bow, 3=Gun, 4=1H Mace, 5=2H Mace, 6=Polearm, 7=1H Sword, 8=2H Sword, 10=Staff, 13=Fist, 15=Dagger, 16=Thrown, 18=Crossbow, 19=Wand |
| 3 | Gem | 0=Red, 1=Blue, 2=Yellow, 3=Purple, 4=Green, 5=Orange, 6=Meta, 8=Prismatic |
| 4 | Armor | 0=Misc, 1=Cloth, 2=Leather, 3=Mail, 4=Plate, 6=Shield |
| 5 | Reagent | 0=Reagent |
| 7 | Tradeskill | 0=Tradeskill |
| 9 | Recipe | 0=Book, 1=Leatherworking, 2=Tailoring, 3=Engineering, 4=Blacksmithing, 5=Cooking, 6=Alchemy, 8=Enchanting, 9=Fishing, 10=Jewelcrafting, 11=Inscription |
| 12 | Quest | 0=Quest item |
| 15 | Miscellaneous | 0=Junk, 1=Reagent, 2=Pet, 4=Mount |

### InventoryType Reference

| Value | Constant | Description |
|---|---|---|
| 0 | INVTYPE_NON_EQUIP | Not equippable |
| 1 | INVTYPE_HEAD | Head slot |
| 2 | INVTYPE_NECK | Neck slot |
| 3 | INVTYPE_SHOULDERS | Shoulder slot |
| 4 | INVTYPE_BODY | Shirt slot |
| 5 | INVTYPE_CHEST | Chest slot |
| 6 | INVTYPE_WAIST | Belt slot |
| 7 | INVTYPE_LEGS | Legs slot |
| 8 | INVTYPE_FEET | Boots slot |
| 9 | INVTYPE_WRISTS | Wrist slot |
| 10 | INVTYPE_HANDS | Gloves slot |
| 11 | INVTYPE_FINGER | Ring slot |
| 12 | INVTYPE_TRINKET | Trinket slot |
| 13 | INVTYPE_WEAPON | One-hand weapon |
| 14 | INVTYPE_SHIELD | Shield (off-hand) |
| 15 | INVTYPE_RANGED | Ranged weapon (bow/gun/crossbow) |
| 16 | INVTYPE_CLOAK | Back/cloak slot |
| 17 | INVTYPE_2HWEAPON | Two-hand weapon |
| 20 | INVTYPE_ROBE | Chest (robe variant) |
| 21 | INVTYPE_WEAPONMAINHAND | Main-hand only weapon |
| 22 | INVTYPE_WEAPONOFFHAND | Off-hand only weapon |
| 23 | INVTYPE_HOLDABLE | Off-hand held item (book, orb) |
| 25 | INVTYPE_THROWN | Thrown weapon |
| 26 | INVTYPE_RANGEDRIGHT | Wand/ranged right slot |
| 28 | INVTYPE_RELIC | Relic slot (libram/totem/idol/sigil) |
| 29 | INVTYPE_TABARD | Tabard slot |

---

## Step 3: Create the ItemDisplayInfo.dbc Entry

### ItemDisplayInfo.dbc Field Layout (WotLK 3.3.5a)

The WotLK ItemDisplayInfo.dbc layout (builds 3.0.1.8303 - 3.3.5.12340) has the following fields. String fields are stored as uint32 offsets into the string block.

| Field Index | Byte Offset | Field Name | Type | Description |
|---|---|---|---|---|
| 0 | 0 | ID | uint32 | Unique display info ID. Referenced by Item.dbc.DisplayInfoID |
| 1 | 4 | ModelName[0] | string | Left-hand .m2 model path (e.g. "Item\\ObjectComponents\\Weapon\\Sword_1H_Custom.m2") |
| 2 | 8 | ModelName[1] | string | Right-hand .m2 model path (usually empty for 1H weapons) |
| 3 | 12 | ModelTexture[0] | string | Left-hand model texture override (.blp, no extension) |
| 4 | 16 | ModelTexture[1] | string | Right-hand model texture override |
| 5 | 20 | InventoryIcon[0] | string | Primary inventory icon path (e.g. "INV_Sword_Custom") |
| 6 | 24 | InventoryIcon[1] | string | Secondary inventory icon (usually empty) |
| 7 | 28 | GeosetGroup[0] | uint32 | Geoset group for body mesh toggling (helmets, shoulders) |
| 8 | 32 | GeosetGroup[1] | uint32 | Second geoset group |
| 9 | 36 | GeosetGroup[2] | uint32 | Third geoset group |
| 10 | 40 | Flags | uint32 | Display flags (0 = default) |
| 11 | 44 | SpellVisualID | uint32 | FK to SpellVisual.dbc for weapon enchant glow |
| 12 | 48 | GroupSoundIndex | uint32 | Sound group for equip/unequip/sheathe |
| 13 | 52 | HelmetGeosetVisID[0] | uint32 | Helmet visibility: which character geosets to hide |
| 14 | 56 | HelmetGeosetVisID[1] | uint32 | Second helmet geoset visibility override |
| 15 | 60 | Texture[0] | string | Body texture override slot 0 (e.g. upper arm texture) |
| 16 | 64 | Texture[1] | string | Body texture override slot 1 (e.g. lower arm) |
| 17 | 68 | Texture[2] | string | Body texture override slot 2 (e.g. hand) |
| 18 | 72 | Texture[3] | string | Body texture override slot 3 (e.g. upper torso) |
| 19 | 76 | Texture[4] | string | Body texture override slot 4 (e.g. lower torso) |
| 20 | 80 | Texture[5] | string | Body texture override slot 5 (e.g. upper leg) |
| 21 | 84 | Texture[6] | string | Body texture override slot 6 (e.g. lower leg) |
| 22 | 88 | Texture[7] | string | Body texture override slot 7 (e.g. foot) |
| 23 | 92 | ItemVisual | uint32 | FK to ItemVisuals.dbc for permanent visual effects |
| 24 | 96 | ParticleColorID | uint32 | FK to ParticleColor.dbc for particle color override |

**Total: 25 fields = 100 bytes per record**

### Python Code: Inject ItemDisplayInfo.dbc Record

```python
import struct
from world_builder.dbc_injector import DBCInjector

def create_item_display_info(
    dbc_dir,
    display_id,
    model_left='',
    model_right='',
    model_texture_left='',
    model_texture_right='',
    icon='',
    icon2='',
    geoset_groups=None,
    flags=0,
    spell_visual_id=0,
    group_sound_index=0,
    helmet_geoset_vis=None,
    body_textures=None,
    item_visual=0,
    particle_color_id=0,
):
    """
    Create a new ItemDisplayInfo.dbc record for WotLK 3.3.5a.

    Args:
        dbc_dir: Path to directory containing ItemDisplayInfo.dbc.
        display_id: Unique display info ID.
        model_left: .m2 model path for left hand / primary model.
        model_right: .m2 model path for right hand (dual wield).
        model_texture_left: Texture override for left model.
        model_texture_right: Texture override for right model.
        icon: Primary inventory icon name (without path prefix or .blp).
        icon2: Secondary icon (usually empty).
        geoset_groups: List of 3 uint32 geoset group values.
        flags: Display flags.
        spell_visual_id: SpellVisual.dbc ID for enchant glow.
        group_sound_index: Sound group index.
        helmet_geoset_vis: List of 2 uint32 helmet geoset visibility IDs.
        body_textures: List of up to 8 body texture override strings.
        item_visual: ItemVisuals.dbc ID for permanent visual effect.
        particle_color_id: ParticleColor.dbc ID.

    Returns:
        int: The display_id that was injected.
    """
    import os
    filepath = os.path.join(dbc_dir, 'ItemDisplayInfo.dbc')
    dbc = DBCInjector(filepath)

    if geoset_groups is None:
        geoset_groups = [0, 0, 0]
    if helmet_geoset_vis is None:
        helmet_geoset_vis = [0, 0]
    if body_textures is None:
        body_textures = [''] * 8

    # Pad body_textures to exactly 8 entries
    while len(body_textures) < 8:
        body_textures.append('')

    # Add all strings to string block and get offsets
    model_left_off = dbc.add_string(model_left)
    model_right_off = dbc.add_string(model_right)
    tex_left_off = dbc.add_string(model_texture_left)
    tex_right_off = dbc.add_string(model_texture_right)
    icon_off = dbc.add_string(icon)
    icon2_off = dbc.add_string(icon2)
    body_tex_offs = [dbc.add_string(t) for t in body_textures]

    # Build the 100-byte record (25 uint32 fields)
    buf = bytearray()

    # Field 0: ID
    buf += struct.pack('<I', display_id)
    # Fields 1-2: ModelName[2]
    buf += struct.pack('<II', model_left_off, model_right_off)
    # Fields 3-4: ModelTexture[2]
    buf += struct.pack('<II', tex_left_off, tex_right_off)
    # Fields 5-6: InventoryIcon[2]
    buf += struct.pack('<II', icon_off, icon2_off)
    # Fields 7-9: GeosetGroup[3]
    buf += struct.pack('<III', *geoset_groups[:3])
    # Field 10: Flags
    buf += struct.pack('<I', flags)
    # Field 11: SpellVisualID
    buf += struct.pack('<I', spell_visual_id)
    # Field 12: GroupSoundIndex
    buf += struct.pack('<I', group_sound_index)
    # Fields 13-14: HelmetGeosetVisID[2]
    buf += struct.pack('<II', *helmet_geoset_vis[:2])
    # Fields 15-22: Texture[8] (body texture overrides)
    for off in body_tex_offs[:8]:
        buf += struct.pack('<I', off)
    # Field 23: ItemVisual
    buf += struct.pack('<I', item_visual)
    # Field 24: ParticleColorID
    buf += struct.pack('<I', particle_color_id)

    assert len(buf) == 100, (
        "ItemDisplayInfo record size mismatch: expected 100, got {}".format(
            len(buf))
    )

    dbc.records.append(bytes(buf))
    dbc.write(filepath)

    return display_id


# Example: Create display info for a custom one-handed sword
create_item_display_info(
    dbc_dir='C:/wow335/DBFilesClient',
    display_id=80001,
    model_left='Item\\ObjectComponents\\Weapon\\Sword_1H_Custom.m2',
    icon='INV_Sword_Custom',
    group_sound_index=6,  # Metal weapon sounds
)
```

### Reusing Existing Display IDs

If you want your custom item to look like an existing item, you can skip creating a new ItemDisplayInfo.dbc entry entirely. Instead, find the `displayid` value of the existing item you want to copy the appearance from (using a DBC viewer or by looking up the item on Wowhead) and use that value directly in both your Item.dbc `DisplayInfoID` field and your `item_template.displayid` SQL column.

For example, Thunderfury uses displayid `32318`. You could create a custom item with `displayid=32318` and it would look exactly like Thunderfury without needing any custom model files.

---

## Step 4: Place Model and Texture Files in MPQ

### File Placement Rules

The WoW client loads model and texture assets from specific paths within MPQ archives. Your custom files must be placed at exactly the paths referenced in your ItemDisplayInfo.dbc entry.

### Required File Types

| File Type | Extension | Purpose | Placement Example |
|---|---|---|---|
| 3D Model | .m2 | Item geometry and animation | `Item\ObjectComponents\Weapon\Sword_1H_Custom.m2` |
| Model Skin | .skin | Mesh subsets and batches | `Item\ObjectComponents\Weapon\Sword_1H_Custom00.skin` |
| Model Texture | .blp | Texture applied to the 3D model | `Item\ObjectComponents\Weapon\Sword_1H_Custom.blp` |
| Inventory Icon | .blp | 64x64 or 128x128 icon | `Interface\Icons\INV_Sword_Custom.blp` |

### Standard Directory Structure in MPQ

```
patch-custom.MPQ/
  |
  +-- Item/
  |     +-- ObjectComponents/
  |           +-- Weapon/
  |           |     +-- Sword_1H_Custom.m2
  |           |     +-- Sword_1H_Custom00.skin
  |           |     +-- Sword_1H_Custom.blp
  |           +-- Shield/
  |           +-- Head/
  |           +-- Shoulder/
  |           +-- Chest/  (for tabards)
  |
  +-- Interface/
  |     +-- Icons/
  |           +-- INV_Sword_Custom.blp
  |
  +-- DBFilesClient/
        +-- Item.dbc
        +-- ItemDisplayInfo.dbc
```

### Category-Specific Model Paths

| Item Category | Base Path | Notes |
|---|---|---|
| Weapons (all) | `Item\ObjectComponents\Weapon\` | Both 1H and 2H |
| Shields | `Item\ObjectComponents\Shield\` | |
| Helmets | `Item\ObjectComponents\Head\` | Character model attachment |
| Shoulders | `Item\ObjectComponents\Shoulder\` | Left/Right variants |
| Cloaks | `Item\ObjectComponents\Cape\` | Uses flat mesh |
| Armor (body) | No .m2 file | Uses Texture[0..7] body overlays |
| Tabards | `Item\ObjectComponents\Chest\` | Special tabard mesh |
| Quivers | `Item\ObjectComponents\Quiver\` | |

### MPQ Patch Priority

Custom MPQ files must be named with a higher patch number than the default game files to ensure they override existing content:

```
Data/
  common.MPQ            (base game)
  common-2.MPQ
  expansion.MPQ
  lichking.MPQ
  patch.MPQ
  patch-2.MPQ
  patch-3.MPQ           (last official patch)
  patch-4.MPQ           (your custom patch -- loaded last, highest priority)
```

The client loads patch archives in alphabetical/numerical order. Files in `patch-4.MPQ` override anything in `patch-3.MPQ` and earlier. You can also use letter suffixes: `patch-A.MPQ`, `patch-B.MPQ`, etc.

### Practical Tips for Asset Files

1. **Reuse existing .m2 files**: The simplest approach is to copy an existing weapon/armor model and retexture it. The .m2 format is complex; creating new geometry from scratch requires specialized tools (WoW Model Viewer, BLP Lab, 010 Editor with M2 template).
2. **BLP Format**: Inventory icons must be DXT1 or DXT5 compressed BLP files. Use BLP Lab or BLP Converter to create them from PNG sources.
3. **Icon naming convention**: Icon names referenced in ItemDisplayInfo.dbc do NOT include the `Interface\Icons\` prefix or the `.blp` extension. The DBC stores just the bare icon name like `INV_Sword_Custom`, and the client resolves the full path automatically.

---

## Step 5: Generate item_template SQL

The `item_template` table in the AzerothCore world database defines every gameplay property of an item. pywowlib's `SQLGenerator` provides a structured Python API to generate this SQL.

### item_template Column Reference

Below is a comprehensive listing of every column the `SQLGenerator.add_items()` method supports, grouped by category.

#### Identity Columns

| Column | Type | Default | Description |
|---|---|---|---|
| `entry` | int | auto | Unique item entry ID. Must match Item.dbc ID |
| `class` | int | 0 | Item class (0=Consumable, 2=Weapon, 4=Armor, ...) |
| `subclass` | int | 0 | Item subclass within class |
| `SoundOverrideSubclass` | int | -1 | Override for sound FX (-1=use subclass) |
| `name` | string | '' | Item display name shown in tooltip |
| `displayid` | int | 0 | FK to ItemDisplayInfo.dbc |

#### Quality and Flags

| Column | Type | Default | Description |
|---|---|---|---|
| `Quality` | int | 0 | Item quality color: 0=Poor(gray), 1=Common(white), 2=Uncommon(green), 3=Rare(blue), 4=Epic(purple), 5=Legendary(orange), 6=Artifact(red), 7=Heirloom(yellow) |
| `Flags` | int | 0 | Item flags bitmask (see flag reference) |
| `FlagsExtra` | int | 0 | Extra flags bitmask |

**Common Flag Values:**

| Flag | Value | Description |
|---|---|---|
| ITEM_FLAG_SOULBOUND | 0x00000001 | Item is soulbound (BoP) |
| ITEM_FLAG_CONJURED | 0x00000002 | Conjured item (deleted on logout) |
| ITEM_FLAG_LOOTABLE | 0x00000004 | Item can be right-clicked to open (loot container) |
| ITEM_FLAG_HEROIC | 0x00000008 | Heroic item (shows "Heroic" tag) |
| ITEM_FLAG_UNK4 | 0x00000010 | "Deprecated" text |
| ITEM_FLAG_INDESTRUCTIBLE | 0x00000100 | Cannot be destroyed |
| ITEM_FLAG_UNIQUE_EQUIPPED | 0x00080000 | Unique-equipped (only 1 equipped at a time) |
| ITEM_FLAG_USABLE_IN_ARENA | 0x00200000 | Can be used in arena |
| ITEM_FLAG_BOA | 0x08000000 | Bind on Account (heirloom) |

#### Economy

| Column | Type | Default | Description |
|---|---|---|---|
| `BuyCount` | int | 1 | Stack size when buying from vendor |
| `BuyPrice` | int | 0 | Purchase price in copper (100 copper = 1 silver, 10000 = 1 gold) |
| `SellPrice` | int | 0 | Sell price in copper (typically BuyPrice/4) |

#### Equipment Properties

| Column | Type | Default | Description |
|---|---|---|---|
| `InventoryType` | int | 0 | Equipment slot (see InventoryType table above) |
| `AllowableClass` | int | -1 | Bitmask of allowed classes (-1=all). Bit 0=Warrior, 1=Paladin, 2=Hunter, 3=Rogue, 4=Priest, 5=DK, 6=Shaman, 7=Mage, 8=Warlock, 10=Druid |
| `AllowableRace` | int | -1 | Bitmask of allowed races (-1=all). Bit 0=Human, 1=Orc, 2=Dwarf, 3=NightElf, 4=Undead, 5=Tauren, 6=Gnome, 7=Troll, 9=BloodElf, 10=Draenei |
| `ItemLevel` | int | 0 | Item level (determines stat budget, affects stat scaling) |
| `RequiredLevel` | int | 0 | Minimum character level to equip |
| `MaxDurability` | int | 0 | Maximum durability (0=indestructible) |
| `bonding` | int | 0 | Bind type: 0=No bind, 1=BoP(Pickup), 2=BoE(Equip), 3=BoU(Use), 4=Quest item, 5=Quest item2 |

#### Stats (up to 10 stat slots)

Stats are provided as a list of `{type, value}` dictionaries. The `stat_type` values map to specific character attributes:

| stat_type | Stat Name | Description |
|---|---|---|
| 0 | MANA | Maximum mana |
| 1 | HEALTH | Maximum health |
| 3 | AGILITY | Agility |
| 4 | STRENGTH | Strength |
| 5 | INTELLECT | Intellect |
| 6 | SPIRIT | Spirit |
| 7 | STAMINA | Stamina |
| 12 | DEFENSE_RATING | Defense rating |
| 13 | DODGE_RATING | Dodge rating |
| 14 | PARRY_RATING | Parry rating |
| 15 | BLOCK_RATING | Block rating |
| 16 | MELEE_HIT_RATING | Melee hit rating |
| 17 | RANGED_HIT_RATING | Ranged hit rating |
| 18 | SPELL_HIT_RATING | Spell hit rating |
| 19 | MELEE_CRIT_RATING | Melee critical strike rating |
| 20 | RANGED_CRIT_RATING | Ranged critical strike rating |
| 21 | SPELL_CRIT_RATING | Spell critical strike rating |
| 31 | HIT_RATING | Hit rating (all) |
| 32 | CRIT_RATING | Critical strike rating (all) |
| 35 | RESILIENCE_RATING | Resilience rating |
| 36 | HASTE_RATING | Haste rating |
| 37 | EXPERTISE_RATING | Expertise rating |
| 38 | ATTACK_POWER | Attack power |
| 41 | SPELL_HEALING | Spell healing (pre-3.x, legacy) |
| 42 | SPELL_DAMAGE | Spell damage (pre-3.x, legacy) |
| 43 | MANA_REGEN | Mana regeneration |
| 44 | ARMOR_PEN_RATING | Armor penetration rating |
| 45 | SPELL_POWER | Spell power |
| 46 | HEALTH_REGEN | Health regen per 5 sec |
| 47 | SPELL_PEN | Spell penetration |
| 48 | BLOCK_VALUE | Block value |

#### Combat Properties

| Column | Type | Default | Description |
|---|---|---|---|
| `dmg_min1` | float | 0 | Minimum damage for primary damage range |
| `dmg_max1` | float | 0 | Maximum damage for primary damage range |
| `dmg_type1` | int | 0 | Damage school: 0=Physical, 1=Holy, 2=Fire, 3=Nature, 4=Frost, 5=Shadow, 6=Arcane |
| `armor` | int | 0 | Armor value (for armor items) |
| `delay` | int | 0 | Weapon speed in milliseconds (e.g. 2600 = 2.6 sec) |
| `ammo_type` | int | 0 | Ammo type: 0=None, 2=Arrows, 3=Bullets |
| `block` | int | 0 | Shield block value |

#### Socket Properties

| Column | Type | Default | Description |
|---|---|---|---|
| `socketColor_1` | int | 0 | Socket 1 color: 0=None, 1=Meta, 2=Red, 4=Yellow, 8=Blue |
| `socketContent_1` | int | 0 | Socket 1 default gem (0=empty) |
| `socketColor_2` | int | 0 | Socket 2 color |
| `socketContent_2` | int | 0 | Socket 2 default gem |
| `socketColor_3` | int | 0 | Socket 3 color |
| `socketContent_3` | int | 0 | Socket 3 default gem |
| `socketBonus` | int | 0 | Bonus enchantment ID when all sockets are filled with matching colors |

#### Spell Effects (up to 5 slots)

Each spell slot has these sub-fields:

| Sub-field | Type | Default | Description |
|---|---|---|---|
| `id` | int | 0 | Spell ID to trigger |
| `trigger` | int | 0 | When to trigger: 0=On Use, 1=On Equip, 2=On Hit (chance), 4=Soulstone, 5=On Use (no delay), 6=Learn Spell |
| `charges` | int | 0 | Number of charges (-1=infinite, 0=no charges) |
| `ppm_rate` | float | 0 | Procs per minute (for trigger=2) |
| `cooldown` | int | -1 | Spell cooldown in ms (-1=default) |
| `category` | int | 0 | Spell category for shared cooldowns |
| `category_cooldown` | int | -1 | Category cooldown in ms (-1=default) |

#### Miscellaneous

| Column | Type | Default | Description |
|---|---|---|---|
| `description` | string | '' | Flavor text shown in tooltip (yellow text) |
| `Material` | int | 0 | Material type (for sounds) |
| `sheath` | int | 0 | Sheathe type |
| `area` | int | 0 | Required area ID to use (0=anywhere) |
| `BagFamily` | int | 0 | Bag family bitmask for special bag types |
| `startquest` | int | 0 | Quest ID started by this item |
| `lockid` | int | 0 | Lock ID for locked items (lockpicking/keys) |
| `RandomProperty` | int | 0 | Random property group for green items |
| `RandomSuffix` | int | 0 | Random suffix group ("of the Eagle", etc.) |
| `itemset` | int | 0 | FK to ItemSet.dbc (0=no set) |
| `MaxDurability` | int | 0 | Max durability points |
| `RequiredSkill` | int | 0 | Required skill ID (e.g. 136=Staves) |
| `RequiredSkillRank` | int | 0 | Required skill rank |
| `RequiredDisenchantSkill` | int | -1 | Enchanting skill needed to disenchant (-1=cannot disenchant) |
| `DisenchantID` | int | 0 | Disenchant loot template ID |
| `FoodType` | int | 0 | Food type for pet feeding |
| `duration` | int | 0 | Item duration in seconds (0=permanent) |
| `minMoneyLoot` | int | 0 | Min money from opening (for lockboxes) |
| `maxMoneyLoot` | int | 0 | Max money from opening |
| `ScriptName` | string | '' | C++ script name for custom behavior |
| `stackable` | int | 1 | Max stack size |
| `maxcount` | int | 0 | Max count a player can carry (0=unlimited) |
| `ContainerSlots` | int | 0 | Number of bag slots (for container items) |

### Python Code: Generate item_template SQL

```python
from world_builder.sql_generator import SQLGenerator

gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)

# Example 1: Epic one-handed sword with stats
gen.add_items([{
    'entry': 90001,
    'name': 'Blade of the Stormforged',
    'class': 2,             # Weapon
    'subclass': 7,          # Sword (1H)
    'displayid': 80001,     # Our custom ItemDisplayInfo ID
    'quality': 4,           # Epic (purple)
    'flags': 0,
    'inventory_type': 13,   # INVTYPE_WEAPON
    'item_level': 232,
    'required_level': 80,
    'bonding': 1,           # Bind on Pickup
    'material': 1,          # Metal
    'sheath': 3,            # Left hip

    # Stats
    'stats': [
        {'type': 4, 'value': 52},   # +52 Strength
        {'type': 7, 'value': 47},   # +47 Stamina
        {'type': 32, 'value': 38},  # +38 Critical Strike Rating
        {'type': 31, 'value': 25},  # +25 Hit Rating
    ],

    # Damage
    'dmg_min1': 175.0,
    'dmg_max1': 326.0,
    'dmg_type1': 0,         # Physical
    'delay': 2600,          # 2.6 second swing speed

    # Durability
    'max_durability': 105,

    # Socket
    'socket_color_1': 2,    # Red socket
    'socket_bonus': 3312,   # +4 Strength enchant ID

    # Economy
    'buy_price': 1215348,
    'sell_price': 243069,

    # Description
    'description': 'Forged in the heart of a dying star.',

    # Allowable classes: all melee (-1 for all, or specific bitmask)
    'allowable_class': -1,
    'allowable_race': -1,
}])

# Example 2: Cloth armor chest piece
gen.add_items([{
    'entry': 90002,
    'name': 'Robes of the Arcane Tempest',
    'class': 4,             # Armor
    'subclass': 1,          # Cloth
    'displayid': 51382,     # Reuse existing Blizzard display
    'quality': 4,           # Epic
    'inventory_type': 20,   # INVTYPE_ROBE
    'item_level': 245,
    'required_level': 80,
    'bonding': 1,           # BoP
    'material': 7,          # Cloth

    'stats': [
        {'type': 5, 'value': 91},   # +91 Intellect
        {'type': 7, 'value': 85},   # +85 Stamina
        {'type': 6, 'value': 64},   # +64 Spirit
        {'type': 36, 'value': 72},  # +72 Haste Rating
        {'type': 45, 'value': 105}, # +105 Spell Power
    ],

    'armor': 356,
    'max_durability': 100,
    'socket_color_1': 4,    # Yellow socket
    'socket_color_2': 4,    # Yellow socket
    'socket_bonus': 2878,   # +5 Spell Power enchant ID
    'buy_price': 947250,
    'sell_price': 189450,

    # Only caster classes
    'allowable_class': 0x4D4,  # Priest + Mage + Warlock
}])

# Example 3: Consumable potion with on-use spell effect
gen.add_items([{
    'entry': 90003,
    'name': 'Elixir of Temporal Displacement',
    'class': 0,             # Consumable
    'subclass': 1,          # Potion
    'displayid': 33748,     # Reuse existing potion icon
    'quality': 1,           # Common (white)
    'inventory_type': 0,    # Non-equippable
    'item_level': 80,
    'required_level': 78,
    'bonding': 0,           # No bind
    'stackable': 20,
    'buy_price': 50000,     # 5 gold
    'sell_price': 2500,
    'description': 'Time seems to slow around you.',

    # On-use spell effect
    'spells': [
        {
            'id': 53908,         # Potion of Speed effect
            'trigger': 0,        # On Use
            'charges': -1,       # Infinite (consumed by stack)
            'cooldown': 60000,   # 60 second cooldown
            'category': 4,       # Potion category
            'category_cooldown': 120000,  # 2 min shared potion CD
        },
    ],
}])

# Write the SQL file
gen.write_sql('output/custom_items.sql')
print("SQL generated successfully.")
print("Entry range: 90001-90003")
```

### Generated SQL Example

The above code produces SQL statements like this:

```sql
-- Item: Blade of the Stormforged (90001)
INSERT INTO `item_template` (`entry`, `class`, `subclass`, `SoundOverrideSubclass`,
    `name`, `displayid`, `Quality`, `Flags`, `FlagsExtra`,
    `BuyCount`, `BuyPrice`, `SellPrice`, `InventoryType`,
    `AllowableClass`, `AllowableRace`,
    `ItemLevel`, `RequiredLevel`,
    `RequiredSkill`, `RequiredSkillRank`,
    `maxcount`, `stackable`, `ContainerSlots`, `StatsCount`,
    `stat_type1`, `stat_value1`, `stat_type2`, `stat_value2`,
    `stat_type3`, `stat_value3`, `stat_type4`, `stat_value4`,
    ... -- remaining stat slots zeroed
    `dmg_min1`, `dmg_max1`, `dmg_type1`,
    `armor`, `delay`, `ammo_type`,
    ... -- spell slots
    `bonding`, `description`,
    `Material`, `sheath`, `block`,
    `MaxDurability`, `area`,
    ... -- sockets, misc
) VALUES
(90001, 2, 7, -1, 'Blade of the Stormforged', 80001, 4, 0, 0,
 1, 1215348, 243069, 13, -1, -1, 232, 80, 0, 0, 0, 1, 0, 4,
 4, 52, 7, 47, 32, 38, 31, 25, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
 175.0, 326.0, 0,
 0, 2600, 0,
 ...
 1, 'Forged in the heart of a dying star.',
 1, 3, 0, 105, 0,
 ...);
```

---

## Step 6: Complete Working Example

This example creates a complete item end-to-end: Item.dbc + ItemDisplayInfo.dbc + item_template SQL.

```python
"""
Complete example: Create a custom epic 2H mace for WoW WotLK 3.3.5a.

This script:
1. Injects an ItemDisplayInfo.dbc entry for the visual appearance
2. Injects an Item.dbc entry linking to the display info
3. Generates item_template SQL for server-side stats

Prerequisites:
- Extracted DBC files in DBC_DIR
- pywowlib on Python path
"""
import struct
import os
from world_builder.dbc_injector import DBCInjector
from world_builder.sql_generator import SQLGenerator

# Configuration
DBC_DIR = 'C:/wow335/DBFilesClient'
SQL_OUTPUT = 'output/custom_mace.sql'

ITEM_ID = 90010
DISPLAY_ID = 80010

# ----------------------------------------------------------------
# Step 1: Create ItemDisplayInfo.dbc entry
# ----------------------------------------------------------------
idi_path = os.path.join(DBC_DIR, 'ItemDisplayInfo.dbc')
idi_dbc = DBCInjector(idi_path)

# Add strings to string block
model_off = idi_dbc.add_string(
    'Item\\ObjectComponents\\Weapon\\Mace_2H_Custom.m2'
)
icon_off = idi_dbc.add_string('INV_Mace_2H_Custom')

# Build 100-byte record (25 uint32 fields)
idi_buf = bytearray()
idi_buf += struct.pack('<I', DISPLAY_ID)       # ID
idi_buf += struct.pack('<I', model_off)         # ModelName[0]
idi_buf += struct.pack('<I', 0)                 # ModelName[1]
idi_buf += struct.pack('<I', 0)                 # ModelTexture[0]
idi_buf += struct.pack('<I', 0)                 # ModelTexture[1]
idi_buf += struct.pack('<I', icon_off)          # InventoryIcon[0]
idi_buf += struct.pack('<I', 0)                 # InventoryIcon[1]
idi_buf += struct.pack('<III', 0, 0, 0)         # GeosetGroup[3]
idi_buf += struct.pack('<I', 0)                 # Flags
idi_buf += struct.pack('<I', 0)                 # SpellVisualID
idi_buf += struct.pack('<I', 21)                # GroupSoundIndex (mace)
idi_buf += struct.pack('<II', 0, 0)             # HelmetGeosetVisID[2]
for _ in range(8):
    idi_buf += struct.pack('<I', 0)             # Texture[8]
idi_buf += struct.pack('<I', 0)                 # ItemVisual
idi_buf += struct.pack('<I', 0)                 # ParticleColorID

assert len(idi_buf) == 100
idi_dbc.records.append(bytes(idi_buf))
idi_dbc.write(idi_path)
print("[OK] ItemDisplayInfo.dbc: added entry {}".format(DISPLAY_ID))

# ----------------------------------------------------------------
# Step 2: Create Item.dbc entry
# ----------------------------------------------------------------
item_path = os.path.join(DBC_DIR, 'Item.dbc')
item_dbc = DBCInjector(item_path)

item_record = struct.pack(
    '<IIIiIIII',
    ITEM_ID,          # ID
    2,                # ClassID = Weapon
    5,                # SubclassID = 2H Mace
    -1,               # Sound_override_subclassID
    1,                # Material = Metal
    DISPLAY_ID,       # DisplayInfoID
    17,               # InventoryType = INVTYPE_2HWEAPON
    1,                # SheatheType = TwoHandLeft (back)
)

assert len(item_record) == 32
item_dbc.records.append(item_record)
item_dbc.write(item_path)
print("[OK] Item.dbc: added entry {}".format(ITEM_ID))

# ----------------------------------------------------------------
# Step 3: Generate item_template SQL
# ----------------------------------------------------------------
gen = SQLGenerator(start_entry=90010)

gen.add_items([{
    'entry': ITEM_ID,
    'name': 'Worldbreaker Maul',
    'class': 2,
    'subclass': 5,           # 2H Mace
    'displayid': DISPLAY_ID,
    'quality': 4,            # Epic
    'inventory_type': 17,    # INVTYPE_2HWEAPON
    'item_level': 264,
    'required_level': 80,
    'bonding': 1,            # BoP

    'stats': [
        {'type': 4, 'value': 198},   # +198 Strength
        {'type': 7, 'value': 183},   # +183 Stamina
        {'type': 32, 'value': 84},   # +84 Crit Rating
        {'type': 44, 'value': 76},   # +76 Armor Pen Rating
    ],

    'dmg_min1': 590.0,
    'dmg_max1': 886.0,
    'dmg_type1': 0,
    'delay': 3600,           # 3.6 sec (typical 2H)

    'armor': 0,
    'max_durability': 120,
    'material': 1,
    'sheath': 1,

    'socket_color_1': 2,     # Red
    'socket_color_2': 4,     # Yellow
    'socket_bonus': 3370,    # +6 Strength

    'buy_price': 2589410,
    'sell_price': 517882,

    'description': 'The ground trembles with each swing.',
    'allowable_class': -1,
    'allowable_race': -1,
}])

os.makedirs(os.path.dirname(SQL_OUTPUT), exist_ok=True)
gen.write_sql(SQL_OUTPUT)
print("[OK] SQL written to: {}".format(SQL_OUTPUT))
print()
print("Next steps:")
print("  1. Place Mace_2H_Custom.m2 in patch MPQ")
print("  2. Place INV_Mace_2H_Custom.blp in patch MPQ")
print("  3. Pack modified DBC files into patch MPQ")
print("  4. Apply SQL to acore_world database")
print("  5. Restart worldserver and clear client cache")
```

---

## Common Pitfalls and Troubleshooting

### Problem: Item appears as a red question mark cube

**Cause:** The client cannot find the .m2 model file at the path specified in ItemDisplayInfo.dbc.

**Fix:**
- Verify the model path in ItemDisplayInfo matches exactly (case-insensitive on Windows, but case-sensitive in MPQ)
- Ensure the .m2 file and its companion .skin file are both present in the MPQ
- Check that your custom MPQ has a higher patch number than base game files

### Problem: Item has no icon (shows as gray square)

**Cause:** The inventory icon path in ItemDisplayInfo.dbc is wrong or the .blp file is missing.

**Fix:**
- The icon field should contain ONLY the icon name, not the full path. Write `INV_Sword_Custom`, NOT `Interface\Icons\INV_Sword_Custom.blp`
- Verify the .blp file exists at `Interface\Icons\INV_Sword_Custom.blp` in your MPQ

### Problem: Item exists in database but `.item` command shows "Item not found"

**Cause:** The Item.dbc entry ID does not match the `item_template.entry` value.

**Fix:**
- Double-check that `item_template.entry` and `Item.dbc.ID` are identical
- Verify that your modified Item.dbc is being loaded by the client (check MPQ patch order)

### Problem: Item stats/damage do not match what you defined

**Cause:** For weapons, the client displays DPS calculated from `item_template.dmg_min1`, `dmg_max1`, and `delay`. The server enforces these values.

**Fix:**
- Ensure `delay` is in milliseconds (2600 = 2.6 seconds, not 2.6)
- DPS = (dmg_min1 + dmg_max1) / 2 / (delay / 1000)
- `ItemLevel` affects stat budget calculations; set it appropriately for your intended power level

### Problem: Item cannot be equipped ("You can't use that item")

**Cause:** Class/race restrictions or incorrect `InventoryType`.

**Fix:**
- `AllowableClass=-1` means all classes can equip it
- If restricting to specific classes, the bitmask must include bit positions for each allowed class (e.g., Warrior=bit0=1, Paladin=bit1=2, Hunter=bit2=4, so Warrior+Paladin = 3)
- Verify `InventoryType` matches the actual item type (e.g., a shield must be 14, not 13)

### Problem: Client crashes when mousing over item

**Cause:** Corrupted DBC entry (wrong record size, or string offset pointing past end of string block).

**Fix:**
- Verify your record byte count matches the expected size (Item.dbc = 32 bytes, ItemDisplayInfo.dbc = 100 bytes)
- Ensure all string offsets returned by `add_string()` are used correctly
- Do not manually construct string offsets; always use `DBCInjector.add_string()`

### Problem: Item shows wrong equip sound or no sound

**Cause:** `Material` field mismatch between Item.dbc and item_template, or wrong `GroupSoundIndex` in ItemDisplayInfo.

**Fix:**
- Set `Material` consistently in both Item.dbc and item_template SQL
- `GroupSoundIndex` in ItemDisplayInfo controls equip/unequip sounds: 0=Generic, 6=Metal weapon, 21=2H Mace, etc.

---

## Reference Tables

### Material Types

| Value | Material | Sound When |
|---|---|---|
| 0 | Generic | Default sounds |
| 1 | Metal | Metal clank on equip/drop |
| 2 | Wood | Wooden thud |
| 3 | Liquid | Splash/pouring sound |
| 4 | Jewelry | Crystal/gem sound |
| 5 | Chain | Chain mail rattle |
| 6 | Plate | Heavy plate clank |
| 7 | Cloth | Fabric rustle |
| 8 | Leather | Leather creak |

### Quality Colors

| Value | Name | Color | Tooltip |
|---|---|---|---|
| 0 | Poor | Gray | Vendor trash |
| 1 | Common | White | Basic items |
| 2 | Uncommon | Green | "Of the Eagle" etc. |
| 3 | Rare | Blue | Dungeon drops |
| 4 | Epic | Purple | Raid drops |
| 5 | Legendary | Orange | Quest chain rewards |
| 6 | Artifact | Red | GM-only items |
| 7 | Heirloom | Yellow | Account-bound |

### SheatheType Values

| Value | Position | Used For |
|---|---|---|
| 0 | None | Items that are not sheathed (held items, shields in some cases) |
| 1 | TwoHandLeft | 2H weapons worn on back (swords, axes) |
| 2 | TwoHandRight | Staff/Polearm on back (alternate position) |
| 3 | LeftHip | 1H weapons on left hip |
| 4 | Shield | Shield on back |
| 5 | QuiverHip | Quiver at right hip |
| 6 | QuiverBack | Quiver on back |
| 7 | OneHandLeft | 1H weapons on left hip (alternate) |

---

## Cross-References

- **[Create Item Set](create_item_set.md)** -- Link multiple items into a set with bonus effects via ItemSet.dbc and the `itemset` column in item_template
- **[Modify Loot Tables](modify_loot_tables.md)** -- Make your custom item drop from creatures or chests
- **[Custom Crafting Recipe](custom_crafting_recipe.md)** -- Create a profession recipe that crafts your custom item
- **pywowlib API Reference:**
  - `world_builder.dbc_injector.DBCInjector` -- Low-level DBC read/write
  - `world_builder.sql_generator.SQLGenerator.add_items()` -- Item SQL generation
  - `world_builder.sql_generator.ItemBuilder.add_item()` -- Single item builder
