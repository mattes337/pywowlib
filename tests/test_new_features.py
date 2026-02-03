"""
Tests for all new world_builder features added in Phases 1-4.

Tests:
  Phase 1: register_spell, modify_spell, register_skill_line_ability, vmap_generator
  Phase 2: register_item, register_item_set, register_sound_entry,
           register_creature_display, register_creature_model,
           register_talent, register_talent_tab
  Phase 3: register_spell_icon, register_gameobject_display,
           register_zone_intro_music, add_doodad_to_adt, add_wmo_to_adt
  Phase 4: generate_addon

Requires: a WoW 3.3.5a client for full integration tests (DBC extraction),
          or runs standalone with freshly created seed DBC files.
"""

import os
import sys
import struct
import shutil
import tempfile
import traceback

# Ensure the project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from world_builder.dbc_injector import DBCInjector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASSED = 0
_FAILED = 0
_ERRORS = []


def _test(name, fn):
    """Run a test function, track pass/fail."""
    global _PASSED, _FAILED
    try:
        fn()
        _PASSED += 1
        print("  PASS  {}".format(name))
    except Exception as e:
        _FAILED += 1
        _ERRORS.append((name, e))
        print("  FAIL  {} -- {}".format(name, e))
        traceback.print_exc()


def _create_seed_dbc(filepath, field_count, record_size):
    """Create an empty DBC file with the WDBC header and no records."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    dbc = DBCInjector()
    dbc.field_count = field_count
    dbc.record_size = record_size
    dbc.write(filepath)
    return filepath


def _read_record_field(filepath, record_index, field_index):
    """Read a uint32 field from a specific record in a DBC file."""
    dbc = DBCInjector(filepath)
    rec = dbc.records[record_index]
    return struct.unpack_from('<I', rec, field_index * 4)[0]


def _read_record_float(filepath, record_index, field_index):
    """Read a float field from a specific record in a DBC file."""
    dbc = DBCInjector(filepath)
    rec = dbc.records[record_index]
    return struct.unpack_from('<f', rec, field_index * 4)[0]


# ---------------------------------------------------------------------------
# Phase 1 Tests: Spell.dbc, SkillLineAbility.dbc, VMap
# ---------------------------------------------------------------------------

def test_register_spell(dbc_dir):
    """Test register_spell creates a valid 936-byte record."""
    from world_builder.dbc_injector import register_spell

    spell_id = register_spell(
        dbc_dir,
        name="Test Fireball",
        spell_id=99001,
        school_mask=0x04,       # Fire
        cast_time_index=5,
        mana_cost=200,
        cooldown=0,
        gcd=1500,
        effect_1=2,             # School Damage
        effect_1_base_points=100,
        effect_1_target_a=6,    # TARGET_UNIT_TARGET_ENEMY
        description="Hurls a fiery ball.",
        aura_description=None,
    )
    assert spell_id == 99001, "Expected spell_id 99001, got {}".format(spell_id)

    dbc = DBCInjector(os.path.join(dbc_dir, 'Spell.dbc'))
    assert len(dbc.records) == 1, "Expected 1 record, got {}".format(len(dbc.records))
    assert len(dbc.records[0]) == 936, "Expected 936 bytes, got {}".format(len(dbc.records[0]))

    # Verify ID field
    rec_id = struct.unpack_from('<I', dbc.records[0], 0)[0]
    assert rec_id == 99001, "Record ID mismatch: {}".format(rec_id)

    # Verify SchoolMask (field index 225)
    school = struct.unpack_from('<I', dbc.records[0], 225 * 4)[0]
    assert school == 0x04, "SchoolMask mismatch: 0x{:X}".format(school)

    # Verify name is in string block
    name_offset = struct.unpack_from('<I', dbc.records[0], 136 * 4)[0]
    name_str = dbc.get_string(name_offset)
    assert name_str == "Test Fireball", "Name mismatch: {!r}".format(name_str)


def test_modify_spell(dbc_dir):
    """Test modify_spell changes fields in an existing record."""
    from world_builder.dbc_injector import register_spell, modify_spell

    # First create a spell
    register_spell(dbc_dir, name="Frostbolt", spell_id=99002,
                   school_mask=0x10, mana_cost=100)

    # Modify it
    modify_spell(dbc_dir, 99002, ManaCost=250, SchoolMask=0x20)

    dbc = DBCInjector(os.path.join(dbc_dir, 'Spell.dbc'))
    # Find the record with ID 99002
    for rec in dbc.records:
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == 99002:
            mana = struct.unpack_from('<I', rec, 42 * 4)[0]  # ManaCost at index 42
            assert mana == 250, "ManaCost not updated: {}".format(mana)
            school = struct.unpack_from('<I', rec, 225 * 4)[0]
            assert school == 0x20, "SchoolMask not updated: 0x{:X}".format(school)
            return
    raise AssertionError("Spell 99002 not found after modify")


def test_register_skill_line_ability(dbc_dir):
    """Test register_skill_line_ability."""
    from world_builder.dbc_injector import register_skill_line_ability

    ability_id = register_skill_line_ability(
        dbc_dir,
        skill_line=26,       # Arms (Warrior)
        spell_id=99001,
        ability_id=90001,
        acquire_method=1,     # Learn on trainer
        min_skill_rank=1,
    )
    assert ability_id == 90001

    dbc = DBCInjector(os.path.join(dbc_dir, 'SkillLineAbility.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 56, "Record size: {}".format(len(dbc.records[0]))

    rec_id = struct.unpack_from('<I', dbc.records[0], 0)[0]
    assert rec_id == 90001


def test_vmap_generator():
    """Test vmap_generator module loads and find_tool works."""
    from world_builder.vmap_generator import find_tool
    # find_tool should return None when tools aren't installed
    result = find_tool("vmap4extractor_nonexistent")
    assert result is None, "Should return None for missing tool"


# ---------------------------------------------------------------------------
# Phase 2 Tests
# ---------------------------------------------------------------------------

def test_register_item(dbc_dir):
    """Test register_item creates valid 32-byte records."""
    from world_builder.dbc_injector import register_item

    item_id = register_item(
        dbc_dir,
        class_id=2,          # Weapon
        subclass_id=7,       # 1H Sword
        sound_override=-1,
        material=1,          # Metal
        display_info_id=5000,
        inventory_type=21,   # Main Hand
        sheathe_type=3,
        item_id=80001,
    )
    assert item_id == 80001

    dbc = DBCInjector(os.path.join(dbc_dir, 'Item.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 32


def test_register_item_set(dbc_dir):
    """Test register_item_set creates valid 212-byte records."""
    from world_builder.dbc_injector import register_item_set

    set_id = register_item_set(
        dbc_dir,
        name="Test Battlegear",
        item_ids=[80001, 80002, 80003],
        set_id=9001,
    )
    assert set_id == 9001

    dbc = DBCInjector(os.path.join(dbc_dir, 'ItemSet.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 212


def test_register_sound_entry(dbc_dir):
    """Test register_sound_entry creates valid 120-byte records."""
    from world_builder.dbc_injector import register_sound_entry

    sound_id = register_sound_entry(
        dbc_dir,
        name="TestAmbience",
        sound_type=50,
        directory_base="Sound\\Ambience",
        files=["TestAmbience01.wav", "TestAmbience02.wav"],
        sound_id=70001,
    )
    assert sound_id == 70001

    dbc = DBCInjector(os.path.join(dbc_dir, 'SoundEntries.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 120


def test_register_creature_display(dbc_dir):
    """Test register_creature_display creates valid 64-byte records."""
    from world_builder.dbc_injector import register_creature_display

    display_id = register_creature_display(
        dbc_dir,
        model_id=500,
        display_id=60001,
        scale=1.5,
        alpha=200,
        textures=["CreatureTexture01.blp"],
    )
    assert display_id == 60001

    dbc = DBCInjector(os.path.join(dbc_dir, 'CreatureDisplayInfo.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 64

    # Verify model_id (field 1)
    model = struct.unpack_from('<I', dbc.records[0], 4)[0]
    assert model == 500, "ModelID mismatch: {}".format(model)


def test_register_creature_model(dbc_dir):
    """Test register_creature_model creates valid 112-byte records."""
    from world_builder.dbc_injector import register_creature_model

    model_id = register_creature_model(
        dbc_dir,
        model_path="Creature\\TestCreature\\TestCreature.m2",
        model_id=50001,
    )
    assert model_id == 50001

    dbc = DBCInjector(os.path.join(dbc_dir, 'CreatureModelData.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 112


def test_register_talent(dbc_dir):
    """Test register_talent creates valid 92-byte records."""
    from world_builder.dbc_injector import register_talent

    talent_id = register_talent(
        dbc_dir,
        tab_id=161,          # Arms tab
        tier=0,
        column=0,
        spell_ranks=[99001],
        talent_id=20001,
    )
    assert talent_id == 20001

    dbc = DBCInjector(os.path.join(dbc_dir, 'Talent.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 92


def test_register_talent_tab(dbc_dir):
    """Test register_talent_tab creates valid 96-byte records."""
    from world_builder.dbc_injector import register_talent_tab

    tab_id = register_talent_tab(
        dbc_dir,
        name="Custom Arms",
        spell_icon_id=1,
        race_mask=0xFFFFFFFF,
        class_mask=0x01,       # Warrior
        order_index=0,
        tab_id=30001,
    )
    assert tab_id == 30001

    dbc = DBCInjector(os.path.join(dbc_dir, 'TalentTab.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 96


# ---------------------------------------------------------------------------
# Phase 3 Tests
# ---------------------------------------------------------------------------

def test_register_spell_icon(dbc_dir):
    """Test register_spell_icon creates valid 8-byte records."""
    from world_builder.dbc_injector import register_spell_icon

    icon_id = register_spell_icon(
        dbc_dir,
        texture_path="Interface\\Icons\\Spell_Fire_TestFireball",
        icon_id=50001,
    )
    assert icon_id == 50001

    dbc = DBCInjector(os.path.join(dbc_dir, 'SpellIcon.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 8


def test_register_gameobject_display(dbc_dir):
    """Test register_gameobject_display creates valid 76-byte records."""
    from world_builder.dbc_injector import register_gameobject_display

    display_id = register_gameobject_display(
        dbc_dir,
        model_path="World\\wmo\\TestObject.wmo",
        display_id=40001,
    )
    assert display_id == 40001

    dbc = DBCInjector(os.path.join(dbc_dir, 'GameObjectDisplayInfo.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 76


def test_register_zone_intro_music(dbc_dir):
    """Test register_zone_intro_music creates valid 20-byte records."""
    from world_builder.dbc_injector import register_zone_intro_music

    intro_id = register_zone_intro_music(
        dbc_dir,
        name="TestZoneIntro",
        sound_id=70001,
        intro_id=10001,
    )
    assert intro_id == 10001

    dbc = DBCInjector(os.path.join(dbc_dir, 'ZoneIntroMusicTable.dbc'))
    assert len(dbc.records) == 1
    assert len(dbc.records[0]) == 20


def test_add_doodad_to_adt():
    """Test add_doodad_to_adt inserts a doodad into ADT binary."""
    from world_builder.adt_composer import create_adt, add_doodad_to_adt

    # Create a base ADT
    adt_bytes = create_adt(32, 32)
    original_size = len(adt_bytes)

    # Add a doodad
    modified = add_doodad_to_adt(
        adt_bytes,
        m2_path="World\\Azeroth\\Elwynn\\Tree01.m2",
        position=(100.0, 200.0, 50.0),
        rotation=(0, 45.0, 0),
        scale=1024,
    )

    assert len(modified) > original_size, \
        "Modified ADT should be larger (was {}, now {})".format(original_size, len(modified))

    # Verify MMDX chunk now contains the path
    mmdx_pos = modified.find(b'XDMM')  # reversed MMDX
    assert mmdx_pos >= 0, "MMDX chunk not found"
    mmdx_size = struct.unpack_from('<I', modified, mmdx_pos + 4)[0]
    assert mmdx_size > 0, "MMDX chunk should be non-empty"

    # Verify MDDF chunk has 36-byte entry
    mddf_pos = modified.find(b'FDDM')  # reversed MDDF
    assert mddf_pos >= 0, "MDDF chunk not found"
    mddf_size = struct.unpack_from('<I', modified, mddf_pos + 4)[0]
    assert mddf_size == 36, "MDDF should have exactly 1 entry (36 bytes), got {}".format(mddf_size)

    # Verify the position values in MDDF entry
    entry_start = mddf_pos + 8  # after header
    name_id = struct.unpack_from('<I', modified, entry_start)[0]
    assert name_id == 0, "name_id should be 0 (first M2)"
    px, py, pz = struct.unpack_from('<3f', modified, entry_start + 8)
    assert abs(px - 100.0) < 0.01 and abs(py - 200.0) < 0.01 and abs(pz - 50.0) < 0.01

    # Verify MVER is still present and valid
    assert modified[:4] == b'REVM', "MVER magic lost"

    # Add a second doodad and verify MDDF grows
    modified2 = add_doodad_to_adt(
        modified,
        m2_path="World\\Azeroth\\Elwynn\\Rock01.m2",
        position=(300.0, 400.0, 10.0),
    )
    mddf_pos2 = modified2.find(b'FDDM')
    mddf_size2 = struct.unpack_from('<I', modified2, mddf_pos2 + 4)[0]
    assert mddf_size2 == 72, "MDDF should have 2 entries (72 bytes), got {}".format(mddf_size2)


def test_add_wmo_to_adt():
    """Test add_wmo_to_adt inserts a WMO into ADT binary."""
    from world_builder.adt_composer import create_adt, add_wmo_to_adt

    adt_bytes = create_adt(32, 32)
    original_size = len(adt_bytes)

    modified = add_wmo_to_adt(
        adt_bytes,
        wmo_path="World\\wmo\\Dungeon\\TestDungeon.wmo",
        position=(500.0, 600.0, 0.0),
        rotation=(0, 90.0, 0),
    )

    assert len(modified) > original_size, \
        "Modified ADT should be larger"

    # Verify MWMO chunk
    mwmo_pos = modified.find(b'OMWM')
    assert mwmo_pos >= 0, "MWMO chunk not found"
    mwmo_size = struct.unpack_from('<I', modified, mwmo_pos + 4)[0]
    assert mwmo_size > 0, "MWMO should be non-empty"

    # Verify MODF chunk has 64-byte entry
    modf_pos = modified.find(b'FDOM')
    assert modf_pos >= 0, "MODF chunk not found"
    modf_size = struct.unpack_from('<I', modified, modf_pos + 4)[0]
    assert modf_size == 64, "MODF should have 1 entry (64 bytes), got {}".format(modf_size)


def test_add_doodad_and_wmo_combined():
    """Test adding both doodads and WMOs to the same ADT."""
    from world_builder.adt_composer import create_adt, add_doodad_to_adt, add_wmo_to_adt

    adt_bytes = create_adt(32, 32)

    # Add a doodad first
    adt_bytes = add_doodad_to_adt(
        adt_bytes,
        m2_path="World\\Tree.m2",
        position=(100.0, 100.0, 0.0),
    )

    # Then add a WMO
    adt_bytes = add_wmo_to_adt(
        adt_bytes,
        wmo_path="World\\Building.wmo",
        position=(200.0, 200.0, 0.0),
    )

    # Both should be present
    mddf_pos = adt_bytes.find(b'FDDM')
    mddf_size = struct.unpack_from('<I', adt_bytes, mddf_pos + 4)[0]
    assert mddf_size == 36, "MDDF should have 1 doodad entry"

    modf_pos = adt_bytes.find(b'FDOM')
    modf_size = struct.unpack_from('<I', adt_bytes, modf_pos + 4)[0]
    assert modf_size == 64, "MODF should have 1 WMO entry"

    # Verify the ADT is still structurally valid (starts with MVER)
    assert adt_bytes[:4] == b'REVM'

    # Verify 256 MCNKs still present
    mcnk_count = adt_bytes.count(b'KNCM')
    assert mcnk_count == 256, "Expected 256 MCNKs, got {}".format(mcnk_count)


# ---------------------------------------------------------------------------
# Phase 4 Tests
# ---------------------------------------------------------------------------

def test_generate_addon(output_dir):
    """Test generate_addon creates valid addon structure."""
    from world_builder.addon_generator import generate_addon

    result = generate_addon(
        name="TestAddon",
        output_dir=output_dir,
        title="Test AddOn",
        description="A test addon",
        author="pywowlib",
        events=["PLAYER_LOGIN", "ADDON_LOADED"],
        slash_commands=[{
            'command': '/testaddon',
            'handler': 'print("Hello from TestAddon")',
        }],
        saved_variables=["TestAddonDB"],
        frames=[{
            'name': 'TestAddonMainFrame',
            'width': 400,
            'height': 300,
            'movable': True,
        }],
    )

    assert os.path.isdir(result['addon_dir']), "Addon dir not created"
    assert os.path.isfile(result['toc_path']), "TOC file not created"
    assert os.path.isfile(result['lua_path']), "Lua file not created"
    assert os.path.isfile(result['xml_path']), "XML file not created"

    # Verify TOC content
    with open(result['toc_path'], 'r') as f:
        toc = f.read()
    assert '## Interface: 30300' in toc, "Missing interface version"
    assert '## Title: Test AddOn' in toc
    assert '## SavedVariables: TestAddonDB' in toc
    assert 'TestAddon.xml' in toc
    assert 'TestAddon.lua' in toc

    # Verify Lua content
    with open(result['lua_path'], 'r') as f:
        lua = f.read()
    assert 'PLAYER_LOGIN' in lua
    assert 'SLASH_TESTADDON1' in lua
    assert 'TestAddonDB' in lua

    # Verify XML content
    with open(result['xml_path'], 'r') as f:
        xml = f.read()
    assert 'TestAddonMainFrame' in xml
    assert 'movable="true"' in xml
    assert 'StartMoving' in xml


# ---------------------------------------------------------------------------
# Integration Test: Full roundtrip with ADT
# ---------------------------------------------------------------------------

def test_adt_roundtrip_with_objects():
    """Test create_adt -> add doodads/WMOs -> verify MCIN integrity."""
    from world_builder.adt_composer import create_adt, add_doodad_to_adt, add_wmo_to_adt

    adt = create_adt(32, 32, texture_paths=["Tileset\\Grass\\Grass01.blp"])

    # Add several doodads
    for i in range(5):
        adt = add_doodad_to_adt(
            adt,
            m2_path="World\\Tree{:02d}.m2".format(i),
            position=(100.0 + i * 50, 200.0, 0.0),
            unique_id=i + 1,
        )

    # Add a WMO
    adt = add_wmo_to_adt(
        adt,
        wmo_path="World\\Inn.wmo",
        position=(500.0, 500.0, 0.0),
        unique_id=100,
    )

    # Verify structural integrity
    # MVER
    assert adt[:4] == b'REVM'
    ver = struct.unpack_from('<I', adt, 8)[0]
    assert ver == 18, "ADT version should be 18"

    # MHDR
    mhdr_pos = adt.find(b'RDHM')
    assert mhdr_pos == 12, "MHDR should be at offset 12"

    # MCIN: verify first MCNK offset points to a valid MCNK
    mcin_pos = adt.find(b'NICM')
    assert mcin_pos > 0
    mcin_data_start = mcin_pos + 8
    first_mcnk_ofs = struct.unpack_from('<I', adt, mcin_data_start)[0]
    assert adt[first_mcnk_ofs:first_mcnk_ofs + 4] == b'KNCM', \
        "First MCIN entry should point to MCNK magic"

    # Verify MDDF has 5 entries
    mddf_pos = adt.find(b'FDDM')
    mddf_size = struct.unpack_from('<I', adt, mddf_pos + 4)[0]
    assert mddf_size == 5 * 36, "Expected 5 doodad entries (180 bytes), got {}".format(mddf_size)

    # Verify MODF has 1 entry
    modf_pos = adt.find(b'FDOM')
    modf_size = struct.unpack_from('<I', adt, modf_pos + 4)[0]
    assert modf_size == 64, "Expected 1 WMO entry (64 bytes), got {}".format(modf_size)

    # Verify all 256 MCNKs are reachable from MCIN
    for i in range(256):
        entry_ofs = mcin_data_start + i * 16
        mcnk_ofs = struct.unpack_from('<I', adt, entry_ofs)[0]
        mcnk_size = struct.unpack_from('<I', adt, entry_ofs + 4)[0]
        assert adt[mcnk_ofs:mcnk_ofs + 4] == b'KNCM', \
            "MCIN entry {} points to invalid MCNK at offset {}".format(i, mcnk_ofs)
        # Size should include the MCNK header
        assert mcnk_size > 128, "MCNK {} too small: {}".format(i, mcnk_size)


# ---------------------------------------------------------------------------
# DBC Seed Creation + Schema Registry
# ---------------------------------------------------------------------------

# Map of DBC name -> (field_count, record_size)
_DBC_SCHEMAS = {
    'Spell':                (234, 936),
    'SkillLineAbility':     (14, 56),
    'Item':                 (8, 32),
    'ItemSet':              (53, 212),
    'SoundEntries':         (30, 120),
    'CreatureDisplayInfo':  (16, 64),
    'CreatureModelData':    (28, 112),
    'Talent':               (23, 92),
    'TalentTab':            (24, 96),
    'SpellIcon':            (2, 8),
    'GameObjectDisplayInfo': (19, 76),
    'ZoneIntroMusicTable':  (5, 20),
}


def _create_all_seed_dbcs(dbc_dir):
    """Create empty seed DBC files for all schemas."""
    for name, (fields, size) in _DBC_SCHEMAS.items():
        _create_seed_dbc(
            os.path.join(dbc_dir, '{}.dbc'.format(name)),
            fields, size
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _PASSED, _FAILED

    print("=" * 70)
    print("pywowlib New Features Test Suite")
    print("=" * 70)

    # Create temp directories for test outputs
    test_root = tempfile.mkdtemp(prefix="pywowlib_test_")
    dbc_dir = os.path.join(test_root, "DBFilesClient")
    addon_dir = os.path.join(test_root, "AddOns")
    os.makedirs(dbc_dir, exist_ok=True)
    os.makedirs(addon_dir, exist_ok=True)

    print("\nTest directory: {}\n".format(test_root))

    # Create seed DBCs
    print("Creating seed DBC files...")
    _create_all_seed_dbcs(dbc_dir)
    print("  Created {} seed DBCs\n".format(len(_DBC_SCHEMAS)))

    # --- Phase 1 Tests ---
    print("--- Phase 1: Spell.dbc, SkillLineAbility.dbc, VMap ---")

    # Fresh Spell.dbc for each spell test
    _create_seed_dbc(os.path.join(dbc_dir, 'Spell.dbc'), 234, 936)
    _test("register_spell", lambda: test_register_spell(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'Spell.dbc'), 234, 936)
    _test("modify_spell", lambda: test_modify_spell(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'SkillLineAbility.dbc'), 14, 56)
    _test("register_skill_line_ability",
          lambda: test_register_skill_line_ability(dbc_dir))

    _test("vmap_generator find_tool", test_vmap_generator)

    # --- Phase 2 Tests ---
    print("\n--- Phase 2: Item, ItemSet, Sound, Creature, Talent ---")

    _create_seed_dbc(os.path.join(dbc_dir, 'Item.dbc'), 8, 32)
    _test("register_item", lambda: test_register_item(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'ItemSet.dbc'), 53, 212)
    _test("register_item_set", lambda: test_register_item_set(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'SoundEntries.dbc'), 30, 120)
    _test("register_sound_entry", lambda: test_register_sound_entry(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'CreatureDisplayInfo.dbc'), 16, 64)
    _test("register_creature_display",
          lambda: test_register_creature_display(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'CreatureModelData.dbc'), 28, 112)
    _test("register_creature_model",
          lambda: test_register_creature_model(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'Talent.dbc'), 23, 92)
    _test("register_talent", lambda: test_register_talent(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'TalentTab.dbc'), 24, 96)
    _test("register_talent_tab", lambda: test_register_talent_tab(dbc_dir))

    # --- Phase 3 Tests ---
    print("\n--- Phase 3: SpellIcon, GODisplayInfo, ZoneIntro, ADT Objects ---")

    _create_seed_dbc(os.path.join(dbc_dir, 'SpellIcon.dbc'), 2, 8)
    _test("register_spell_icon", lambda: test_register_spell_icon(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'GameObjectDisplayInfo.dbc'), 19, 76)
    _test("register_gameobject_display",
          lambda: test_register_gameobject_display(dbc_dir))

    _create_seed_dbc(os.path.join(dbc_dir, 'ZoneIntroMusicTable.dbc'), 5, 20)
    _test("register_zone_intro_music",
          lambda: test_register_zone_intro_music(dbc_dir))

    _test("add_doodad_to_adt", test_add_doodad_to_adt)
    _test("add_wmo_to_adt", test_add_wmo_to_adt)
    _test("add_doodad_and_wmo_combined", test_add_doodad_and_wmo_combined)

    # --- Phase 4 Tests ---
    print("\n--- Phase 4: AddOn Generator ---")
    _test("generate_addon", lambda: test_generate_addon(addon_dir))

    # --- Integration Tests ---
    print("\n--- Integration Tests ---")
    _test("adt_roundtrip_with_objects", test_adt_roundtrip_with_objects)

    # --- Summary ---
    print("\n" + "=" * 70)
    print("Results: {} passed, {} failed".format(_PASSED, _FAILED))

    if _ERRORS:
        print("\nFailures:")
        for name, err in _ERRORS:
            print("  {} -- {}".format(name, err))

    # Cleanup
    try:
        shutil.rmtree(test_root)
        print("\nCleaned up test directory.")
    except Exception:
        print("\nTest directory at: {}".format(test_root))

    print("=" * 70)
    return 0 if _FAILED == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
