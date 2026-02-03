"""
Integration tests against real extracted WoW 3.3.5a DBC files.

Verifies that all new DBC schemas produce records with correct sizes
and that register/modify operations work against real game data.

Requires extracted DBCs at: tools/extractors/output/dbc/
"""

import os
import sys
import struct
import shutil
import tempfile
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from world_builder.dbc_injector import DBCInjector

# Path to real extracted DBCs
REAL_DBC_DIR = os.path.join(PROJECT_ROOT, "tools", "extractors", "output", "dbc")

_PASSED = 0
_FAILED = 0
_ERRORS = []


def _test(name, fn):
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


def _copy_dbc(src_dir, dst_dir, dbc_name):
    """Copy a real DBC to a temp dir for testing (so we don't modify originals)."""
    src = os.path.join(src_dir, dbc_name)
    dst = os.path.join(dst_dir, dbc_name)
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Validate real DBC record sizes match our schema constants
# ---------------------------------------------------------------------------

_EXPECTED_SCHEMAS = {
    'Spell.dbc':                (234, 936),
    'SkillLineAbility.dbc':     (14, 56),
    'Item.dbc':                 (8, 32),
    'ItemSet.dbc':              (53, 212),
    'SoundEntries.dbc':         (30, 120),
    'CreatureDisplayInfo.dbc':  (16, 64),
    'CreatureModelData.dbc':    (28, 112),
    'Talent.dbc':               (23, 92),
    'TalentTab.dbc':            (24, 96),
    'SpellIcon.dbc':            (2, 8),
    'GameObjectDisplayInfo.dbc': (19, 76),
    'ZoneIntroMusicTable.dbc':  (5, 20),
}


def test_schema_field_counts():
    """Verify our field_count/record_size constants match real DBC headers."""
    for dbc_name, (expected_fields, expected_size) in _EXPECTED_SCHEMAS.items():
        filepath = os.path.join(REAL_DBC_DIR, dbc_name)
        if not os.path.isfile(filepath):
            raise FileNotFoundError("Missing: {}".format(filepath))

        dbc = DBCInjector(filepath)
        assert dbc.field_count == expected_fields, \
            "{}: field_count {} != expected {}".format(
                dbc_name, dbc.field_count, expected_fields)
        assert dbc.record_size == expected_size, \
            "{}: record_size {} != expected {}".format(
                dbc_name, dbc.record_size, expected_size)


def test_dbc_record_counts():
    """Sanity check: real DBCs should have many records."""
    filepath = os.path.join(REAL_DBC_DIR, 'Spell.dbc')
    dbc = DBCInjector(filepath)
    assert dbc.record_count > 40000, \
        "Spell.dbc should have 40k+ records, got {}".format(dbc.record_count)

    filepath = os.path.join(REAL_DBC_DIR, 'Item.dbc')
    dbc = DBCInjector(filepath)
    assert dbc.record_count > 10000, \
        "Item.dbc should have 10k+ records, got {}".format(dbc.record_count)

    filepath = os.path.join(REAL_DBC_DIR, 'CreatureDisplayInfo.dbc')
    dbc = DBCInjector(filepath)
    assert dbc.record_count > 5000, \
        "CreatureDisplayInfo.dbc should have 5k+ records, got {}".format(dbc.record_count)


# ---------------------------------------------------------------------------
# Register into copies of real DBCs
# ---------------------------------------------------------------------------

def test_register_spell_real(tmp_dir):
    """Register a new spell into a copy of the real Spell.dbc."""
    from world_builder.dbc_injector import register_spell

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'Spell.dbc')

    original = DBCInjector(os.path.join(REAL_DBC_DIR, 'Spell.dbc'))
    original_count = original.record_count
    original_max_id = original.get_max_id()

    spell_id = register_spell(
        tmp_dir,
        name="Pyroblast Test",
        school_mask=0x04,
        cast_time_index=15,
        mana_cost=500,
        effect_1=2,
        effect_1_base_points=800,
        effect_1_target_a=6,
        description="Massive fire damage test spell.",
    )

    assert spell_id == original_max_id + 1, \
        "Auto-ID should be max+1={}, got {}".format(original_max_id + 1, spell_id)

    modified = DBCInjector(os.path.join(tmp_dir, 'Spell.dbc'))
    assert modified.record_count == original_count + 1, \
        "Should have +1 records: {} vs {}".format(modified.record_count, original_count)

    # Verify the last record is our new spell
    last_rec = modified.records[-1]
    assert len(last_rec) == 936
    rec_id = struct.unpack_from('<I', last_rec, 0)[0]
    assert rec_id == spell_id

    # Verify name
    name_ofs = struct.unpack_from('<I', last_rec, 136 * 4)[0]
    assert modified.get_string(name_ofs) == "Pyroblast Test"


def test_modify_spell_real(tmp_dir):
    """Modify an existing real spell (Fireball, ID=133)."""
    from world_builder.dbc_injector import modify_spell

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'Spell.dbc')

    # Modify Fireball (ID 133) to have 999 mana cost
    modify_spell(tmp_dir, 133, ManaCost=999)

    dbc = DBCInjector(os.path.join(tmp_dir, 'Spell.dbc'))
    for rec in dbc.records:
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == 133:
            mana = struct.unpack_from('<I', rec, 42 * 4)[0]
            assert mana == 999, "ManaCost should be 999, got {}".format(mana)
            return
    raise AssertionError("Spell 133 (Fireball) not found")


def test_register_skill_line_ability_real(tmp_dir):
    """Register a new ability into real SkillLineAbility.dbc."""
    from world_builder.dbc_injector import register_skill_line_ability

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'SkillLineAbility.dbc')

    original = DBCInjector(os.path.join(REAL_DBC_DIR, 'SkillLineAbility.dbc'))
    original_count = original.record_count

    ability_id = register_skill_line_ability(
        tmp_dir,
        skill_line=26,
        spell_id=99999,
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'SkillLineAbility.dbc'))
    assert modified.record_count == original_count + 1
    last_rec = modified.records[-1]
    assert len(last_rec) == 56


def test_register_item_real(tmp_dir):
    """Register a new item into real Item.dbc."""
    from world_builder.dbc_injector import register_item

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'Item.dbc')

    original = DBCInjector(os.path.join(REAL_DBC_DIR, 'Item.dbc'))

    item_id = register_item(
        tmp_dir,
        class_id=2,
        subclass_id=7,
        display_info_id=12345,
        inventory_type=13,
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'Item.dbc'))
    assert modified.record_count == original.record_count + 1

    last_rec = modified.records[-1]
    assert len(last_rec) == 32
    rec_id = struct.unpack_from('<I', last_rec, 0)[0]
    assert rec_id == item_id


def test_register_item_set_real(tmp_dir):
    """Register a new item set into real ItemSet.dbc."""
    from world_builder.dbc_injector import register_item_set

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'ItemSet.dbc')

    set_id = register_item_set(
        tmp_dir,
        name="Cursed Battlegear",
        item_ids=[80001, 80002, 80003, 80004, 80005],
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'ItemSet.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 212

    name_ofs = struct.unpack_from('<I', last_rec, 1 * 4)[0]
    assert modified.get_string(name_ofs) == "Cursed Battlegear"


def test_register_sound_entry_real(tmp_dir):
    """Register a new sound into real SoundEntries.dbc."""
    from world_builder.dbc_injector import register_sound_entry

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'SoundEntries.dbc')

    sound_id = register_sound_entry(
        tmp_dir,
        name="CustomAmbience",
        sound_type=50,
        files=["Ambient01.wav"],
        directory_base="Sound\\Custom",
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'SoundEntries.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 120


def test_register_creature_display_real(tmp_dir):
    """Register a new creature display into real CreatureDisplayInfo.dbc."""
    from world_builder.dbc_injector import register_creature_display

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'CreatureDisplayInfo.dbc')

    original = DBCInjector(os.path.join(REAL_DBC_DIR, 'CreatureDisplayInfo.dbc'))

    display_id = register_creature_display(
        tmp_dir,
        model_id=123,
        scale=2.0,
        textures=["CustomSkin.blp"],
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'CreatureDisplayInfo.dbc'))
    assert modified.record_count == original.record_count + 1

    last_rec = modified.records[-1]
    assert len(last_rec) == 64


def test_register_creature_model_real(tmp_dir):
    """Register a new creature model into real CreatureModelData.dbc."""
    from world_builder.dbc_injector import register_creature_model

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'CreatureModelData.dbc')

    model_id = register_creature_model(
        tmp_dir,
        model_path="Creature\\CustomBoss\\CustomBoss.m2",
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'CreatureModelData.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 112


def test_register_talent_real(tmp_dir):
    """Register a new talent into real Talent.dbc."""
    from world_builder.dbc_injector import register_talent

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'Talent.dbc')

    talent_id = register_talent(
        tmp_dir,
        tab_id=161,
        tier=0,
        column=0,
        spell_ranks=[99001, 99002, 99003],
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'Talent.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 92


def test_register_talent_tab_real(tmp_dir):
    """Register a new talent tab into real TalentTab.dbc."""
    from world_builder.dbc_injector import register_talent_tab

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'TalentTab.dbc')

    tab_id = register_talent_tab(
        tmp_dir,
        name="Shadow Mastery",
        class_mask=0x10,
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'TalentTab.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 96


def test_register_spell_icon_real(tmp_dir):
    """Register a new spell icon into real SpellIcon.dbc."""
    from world_builder.dbc_injector import register_spell_icon

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'SpellIcon.dbc')

    icon_id = register_spell_icon(
        tmp_dir,
        texture_path="Interface\\Icons\\Spell_Custom_TestIcon",
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'SpellIcon.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 8


def test_register_gameobject_display_real(tmp_dir):
    """Register a new GO display into real GameObjectDisplayInfo.dbc."""
    from world_builder.dbc_injector import register_gameobject_display

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'GameObjectDisplayInfo.dbc')

    display_id = register_gameobject_display(
        tmp_dir,
        model_path="World\\wmo\\TestChest.wmo",
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'GameObjectDisplayInfo.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 76


def test_register_zone_intro_music_real(tmp_dir):
    """Register a new zone intro music into real ZoneIntroMusicTable.dbc."""
    from world_builder.dbc_injector import register_zone_intro_music

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'ZoneIntroMusicTable.dbc')

    intro_id = register_zone_intro_music(
        tmp_dir,
        name="CustomZoneIntro",
        sound_id=12345,
    )

    modified = DBCInjector(os.path.join(tmp_dir, 'ZoneIntroMusicTable.dbc'))
    last_rec = modified.records[-1]
    assert len(last_rec) == 20


# ---------------------------------------------------------------------------
# Roundtrip: write and re-read to verify binary integrity
# ---------------------------------------------------------------------------

def test_spell_roundtrip(tmp_dir):
    """Register a spell, write, re-read, verify all fields survive."""
    from world_builder.dbc_injector import register_spell

    _copy_dbc(REAL_DBC_DIR, tmp_dir, 'Spell.dbc')

    spell_id = register_spell(
        tmp_dir,
        name="Roundtrip Bolt",
        school_mask=0x20,
        cast_time_index=3,
        mana_cost=350,
        cooldown=8000,
        gcd=1500,
        effect_1=6,
        effect_1_base_points=50,
        effect_1_aura=3,
        effect_1_target_a=1,
        description="Test roundtrip integrity.",
        aura_description="Periodic test effect.",
    )

    # Re-read
    dbc = DBCInjector(os.path.join(tmp_dir, 'Spell.dbc'))
    rec = dbc.records[-1]

    # Verify fields
    assert struct.unpack_from('<I', rec, 0)[0] == spell_id
    assert struct.unpack_from('<I', rec, 225 * 4)[0] == 0x20  # SchoolMask
    assert struct.unpack_from('<I', rec, 28 * 4)[0] == 3      # CastingTimeIndex
    assert struct.unpack_from('<I', rec, 42 * 4)[0] == 350    # ManaCost
    assert struct.unpack_from('<I', rec, 29 * 4)[0] == 8000   # RecoveryTime
    assert struct.unpack_from('<I', rec, 71 * 4)[0] == 6      # Effect0
    assert struct.unpack_from('<I', rec, 80 * 4)[0] == 50     # EffectBasePoints0
    assert struct.unpack_from('<I', rec, 95 * 4)[0] == 3      # EffectAura0

    # Verify name string
    name_ofs = struct.unpack_from('<I', rec, 136 * 4)[0]
    assert dbc.get_string(name_ofs) == "Roundtrip Bolt"

    # Verify description string
    desc_ofs = struct.unpack_from('<I', rec, 170 * 4)[0]
    assert dbc.get_string(desc_ofs) == "Test roundtrip integrity."

    # Verify all existing records still intact
    original = DBCInjector(os.path.join(REAL_DBC_DIR, 'Spell.dbc'))
    for i in range(min(10, original.record_count)):
        assert dbc.records[i] == original.records[i], \
            "Original record {} was corrupted".format(i)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _PASSED, _FAILED

    if not os.path.isdir(REAL_DBC_DIR):
        print("ERROR: Real DBC dir not found: {}".format(REAL_DBC_DIR))
        print("Run extraction first.")
        return 1

    print("=" * 70)
    print("Real DBC Integration Test Suite")
    print("DBC source: {}".format(REAL_DBC_DIR))
    print("=" * 70)

    tmp_dir = tempfile.mkdtemp(prefix="pywowlib_real_test_")
    print("Temp dir: {}\n".format(tmp_dir))

    # Schema validation
    print("--- Schema Validation (all 12 DBCs) ---")
    _test("field_count/record_size match real headers", test_schema_field_counts)
    _test("real DBC record counts sanity", test_dbc_record_counts)

    # Register into real DBC copies
    print("\n--- Phase 1: Spell + SkillLineAbility ---")
    _test("register_spell into real Spell.dbc", lambda: test_register_spell_real(tmp_dir))
    _test("modify_spell on real Fireball (ID 133)", lambda: test_modify_spell_real(tmp_dir))
    _test("register_skill_line_ability real", lambda: test_register_skill_line_ability_real(tmp_dir))

    print("\n--- Phase 2: Item, ItemSet, Sound, Creature, Talent ---")
    _test("register_item real", lambda: test_register_item_real(tmp_dir))
    _test("register_item_set real", lambda: test_register_item_set_real(tmp_dir))
    _test("register_sound_entry real", lambda: test_register_sound_entry_real(tmp_dir))
    _test("register_creature_display real", lambda: test_register_creature_display_real(tmp_dir))
    _test("register_creature_model real", lambda: test_register_creature_model_real(tmp_dir))
    _test("register_talent real", lambda: test_register_talent_real(tmp_dir))
    _test("register_talent_tab real", lambda: test_register_talent_tab_real(tmp_dir))

    print("\n--- Phase 3: SpellIcon, GODisplay, ZoneIntro ---")
    _test("register_spell_icon real", lambda: test_register_spell_icon_real(tmp_dir))
    _test("register_gameobject_display real", lambda: test_register_gameobject_display_real(tmp_dir))
    _test("register_zone_intro_music real", lambda: test_register_zone_intro_music_real(tmp_dir))

    print("\n--- Roundtrip Tests ---")
    _test("spell full roundtrip (write + re-read)", lambda: test_spell_roundtrip(tmp_dir))

    # Summary
    print("\n" + "=" * 70)
    print("Results: {} passed, {} failed".format(_PASSED, _FAILED))

    if _ERRORS:
        print("\nFailures:")
        for name, err in _ERRORS:
            print("  {} -- {}".format(name, err))

    try:
        shutil.rmtree(tmp_dir)
        print("\nCleaned up temp directory.")
    except Exception:
        print("\nTemp dir at: {}".format(tmp_dir))

    print("=" * 70)
    return 0 if _FAILED == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
