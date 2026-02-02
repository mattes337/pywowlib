"""
SQL script validator for WoW WotLK 3.3.5a TrinityCore.

Validates:
- SQL syntax (basic regex checks)
- Referential integrity across tables
- Completeness checks (quests have starters/enders, etc.)
- Value range validation
"""

import os
import re

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# SQL parsing helpers
# ---------------------------------------------------------------------------

def _read_sql_files(sql_dir):
    """
    Read all SQL files from sql_dir.

    Returns list of (filename, content_string) tuples.
    """
    files = []
    if not sql_dir or not os.path.isdir(sql_dir):
        return files

    for fname in os.listdir(sql_dir):
        if not fname.lower().endswith('.sql'):
            continue
        fpath = os.path.join(sql_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            files.append((fname, content))
        except IOError:
            pass

    return files


def _extract_inserts(sql_content, table_name):
    """
    Extract INSERT values for a given table name.

    Handles both:
        INSERT INTO table (cols) VALUES (vals);
        INSERT INTO `table` (cols) VALUES (vals);

    Returns list of tuples (column_list, values_list) where each is a list
    of strings.
    """
    pattern = (
        r"INSERT\s+INTO\s+`?{}`?\s*"
        r"\(([^)]*)\)\s*VALUES\s*"
        r"\(([^)]*)\)".format(re.escape(table_name))
    )
    matches = re.findall(pattern, sql_content, re.IGNORECASE)

    results = []
    for cols_str, vals_str in matches:
        cols = [c.strip().strip('`') for c in cols_str.split(',')]
        vals = [v.strip().strip("'\"") for v in vals_str.split(',')]
        results.append((cols, vals))

    return results


def _get_column_value(columns, values, col_name):
    """Get value for a named column from an INSERT row."""
    for i, col in enumerate(columns):
        if col.lower() == col_name.lower() and i < len(values):
            return values[i]
    return None


def _extract_table_ids(sql_content, table_name, id_column='entry'):
    """Extract set of IDs from INSERT statements for a table."""
    ids = set()
    inserts = _extract_inserts(sql_content, table_name)
    for cols, vals in inserts:
        val = _get_column_value(cols, vals, id_column)
        if val is not None:
            try:
                ids.add(int(val))
            except ValueError:
                pass
    return ids


# ---------------------------------------------------------------------------
# Syntax validation (SQL-001, SQL-002)
# ---------------------------------------------------------------------------

def _validate_sql_syntax(sql_files):
    """Validate basic SQL syntax."""
    results = []

    for fname, content in sql_files:
        # SQL-001: Basic syntax check
        # Look for common issues: unclosed strings, mismatched parentheses
        errors = []

        # Check balanced parentheses in each statement
        statements = content.split(';')
        for i, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt:
                continue
            # Remove string literals for paren counting
            cleaned = re.sub(r"'[^']*'", '', stmt)
            cleaned = re.sub(r'"[^"]*"', '', cleaned)
            open_count = cleaned.count('(')
            close_count = cleaned.count(')')
            if open_count != close_count:
                errors.append(
                    "Statement {} has mismatched parentheses".format(i + 1))

        if not errors:
            results.append(ValidationResult(
                check_id='SQL-001',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="SQL {} syntax check passed".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="SQL {} syntax errors: {}".format(
                    fname, errors[:3]),
                fix_suggestion="Fix SQL syntax errors",
            ))

        # SQL-002: INSERT column count matches value count
        insert_pattern = (
            r"INSERT\s+INTO\s+`?\w+`?\s*"
            r"\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)"
        )
        insert_matches = re.findall(insert_pattern, content, re.IGNORECASE)
        col_mismatch = 0

        for cols_str, vals_str in insert_matches:
            cols = [c.strip() for c in cols_str.split(',')]
            vals = [v.strip() for v in vals_str.split(',')]
            if len(cols) != len(vals):
                col_mismatch += 1

        if col_mismatch == 0:
            results.append(ValidationResult(
                check_id='SQL-002',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="SQL {} all INSERT column counts match".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-002',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="SQL {} has {} INSERTs with column "
                        "mismatch".format(fname, col_mismatch),
                fix_suggestion="Check column lists",
            ))

    return results


# ---------------------------------------------------------------------------
# Referential integrity (SQL-REF-001 through SQL-REF-010)
# ---------------------------------------------------------------------------

def _validate_sql_refs(sql_content, dbc_dir):
    """Validate SQL foreign key relationships."""
    results = []

    # Collect IDs from various tables
    creature_template_ids = _extract_table_ids(
        sql_content, 'creature_template', 'entry')
    item_template_ids = _extract_table_ids(
        sql_content, 'item_template', 'entry')
    quest_template_ids = _extract_table_ids(
        sql_content, 'quest_template', 'ID')

    # SQL-REF-001: creature_queststarter.id -> creature_template.entry
    queststarter_inserts = _extract_inserts(sql_content, 'creature_queststarter')
    bad_starters = []
    for cols, vals in queststarter_inserts:
        cid = _get_column_value(cols, vals, 'id')
        if cid:
            try:
                if int(cid) not in creature_template_ids:
                    bad_starters.append(int(cid))
            except ValueError:
                pass

    if queststarter_inserts:
        if not bad_starters:
            results.append(ValidationResult(
                check_id='SQL-REF-001',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All creature_queststarter IDs reference "
                        "valid templates",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="creature_queststarter references missing "
                        "templates: {}".format(bad_starters[:5]),
                fix_suggestion="Register creature_template first",
            ))

    # SQL-REF-002: creature_questender.id -> creature_template.entry
    questender_inserts = _extract_inserts(sql_content, 'creature_questender')
    bad_enders = []
    for cols, vals in questender_inserts:
        cid = _get_column_value(cols, vals, 'id')
        if cid:
            try:
                if int(cid) not in creature_template_ids:
                    bad_enders.append(int(cid))
            except ValueError:
                pass

    if questender_inserts:
        if not bad_enders:
            results.append(ValidationResult(
                check_id='SQL-REF-002',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All creature_questender IDs reference "
                        "valid templates",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-002',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="creature_questender references missing "
                        "templates: {}".format(bad_enders[:5]),
                fix_suggestion="Register creature_template first",
            ))

    # SQL-REF-003: quest_template reward items -> item_template.entry
    quest_inserts = _extract_inserts(sql_content, 'quest_template')
    bad_reward_items = []
    reward_cols = ['RewardItem1', 'RewardItem2', 'RewardItem3', 'RewardItem4']
    for cols, vals in quest_inserts:
        for rcol in reward_cols:
            item_id = _get_column_value(cols, vals, rcol)
            if item_id:
                try:
                    iid = int(item_id)
                    if iid > 0 and iid not in item_template_ids:
                        bad_reward_items.append(iid)
                except ValueError:
                    pass

    if quest_inserts and item_template_ids:
        if not bad_reward_items:
            results.append(ValidationResult(
                check_id='SQL-REF-003',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All quest reward items reference valid items",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-003',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Quest reward items referencing missing "
                        "item_template: {}".format(bad_reward_items[:5]),
                fix_suggestion="Register items before quests",
            ))

    # SQL-REF-004: quest_template required items -> item_template.entry
    bad_req_items = []
    req_cols = ['RequiredItemId1', 'RequiredItemId2', 'RequiredItemId3',
                'RequiredItemId4', 'RequiredItemId5', 'RequiredItemId6']
    for cols, vals in quest_inserts:
        for rcol in req_cols:
            item_id = _get_column_value(cols, vals, rcol)
            if item_id:
                try:
                    iid = int(item_id)
                    if iid > 0 and iid not in item_template_ids:
                        bad_req_items.append(iid)
                except ValueError:
                    pass

    if quest_inserts and item_template_ids:
        if not bad_req_items:
            results.append(ValidationResult(
                check_id='SQL-REF-004',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All quest required items reference valid items",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-004',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Quest required items referencing missing "
                        "item_template: {}".format(bad_req_items[:5]),
                fix_suggestion="Register items before quests",
            ))

    # SQL-REF-005: creature_loot_template.item -> item_template.entry
    loot_inserts = _extract_inserts(sql_content, 'creature_loot_template')
    bad_loot = []
    for cols, vals in loot_inserts:
        item_id = _get_column_value(cols, vals, 'item')
        if item_id:
            try:
                iid = int(item_id)
                if iid > 0 and iid not in item_template_ids:
                    bad_loot.append(iid)
            except ValueError:
                pass

    if loot_inserts and item_template_ids:
        if not bad_loot:
            results.append(ValidationResult(
                check_id='SQL-REF-005',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All loot items reference valid item_template",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-005',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Loot references missing items: {}".format(
                    bad_loot[:5]),
                fix_suggestion="Register items before loot tables",
            ))

    # SQL-REF-006: npc_vendor.item -> item_template.entry
    vendor_inserts = _extract_inserts(sql_content, 'npc_vendor')
    bad_vendor = []
    for cols, vals in vendor_inserts:
        item_id = _get_column_value(cols, vals, 'item')
        if item_id:
            try:
                iid = int(item_id)
                if iid > 0 and iid not in item_template_ids:
                    bad_vendor.append(iid)
            except ValueError:
                pass

    if vendor_inserts and item_template_ids:
        if not bad_vendor:
            results.append(ValidationResult(
                check_id='SQL-REF-006',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All vendor items reference valid item_template",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-006',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Vendor references missing items: {}".format(
                    bad_vendor[:5]),
                fix_suggestion="Register items before vendors",
            ))

    # SQL-REF-007: smart_scripts.entryorguid -> creature_template.entry
    smart_inserts = _extract_inserts(sql_content, 'smart_scripts')
    bad_smart = []
    for cols, vals in smart_inserts:
        entry = _get_column_value(cols, vals, 'entryorguid')
        source_type = _get_column_value(cols, vals, 'source_type')
        if entry and source_type:
            try:
                eid = int(entry)
                st = int(source_type)
                # source_type 0 = creature
                if st == 0 and eid > 0 and eid not in creature_template_ids:
                    bad_smart.append(eid)
            except ValueError:
                pass

    if smart_inserts:
        if not bad_smart:
            results.append(ValidationResult(
                check_id='SQL-REF-007',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All smart_scripts entries reference valid "
                        "creature templates",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-007',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="smart_scripts reference missing templates: "
                        "{}".format(bad_smart[:5]),
                fix_suggestion="Register creature_template first",
            ))

    # SQL-REF-008: creature.id -> creature_template.entry
    creature_inserts = _extract_inserts(sql_content, 'creature')
    bad_spawns = []
    for cols, vals in creature_inserts:
        cid = _get_column_value(cols, vals, 'id')
        if cid:
            try:
                if int(cid) not in creature_template_ids:
                    bad_spawns.append(int(cid))
            except ValueError:
                pass

    if creature_inserts:
        if not bad_spawns:
            results.append(ValidationResult(
                check_id='SQL-REF-008',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All creature spawns reference valid templates",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-008',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Creature spawns reference missing templates: "
                        "{}".format(bad_spawns[:5]),
                fix_suggestion="Register template before spawns",
            ))

    # SQL-REF-009: quest_template_addon.PrevQuestId -> quest_template.ID
    addon_inserts = _extract_inserts(sql_content, 'quest_template_addon')
    bad_prev = []
    for cols, vals in addon_inserts:
        prev = _get_column_value(cols, vals, 'PrevQuestId')
        if prev:
            try:
                pid = int(prev)
                if pid > 0 and pid not in quest_template_ids:
                    bad_prev.append(pid)
            except ValueError:
                pass

    if addon_inserts and quest_template_ids:
        if not bad_prev:
            results.append(ValidationResult(
                check_id='SQL-REF-009',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="All quest chain PrevQuestId references valid",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-REF-009',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Quest chain references missing quests: "
                        "{}".format(bad_prev[:5]),
                fix_suggestion="Verify quest chains",
            ))

    # SQL-REF-010: Spawn map IDs match DBC
    if dbc_dir:
        map_ids = set()
        map_dbc_path = os.path.join(dbc_dir, "Map.dbc")
        if os.path.isfile(map_dbc_path):
            try:
                from .dbc_validator import _DBCReader
                reader = _DBCReader(map_dbc_path)
                if reader.valid:
                    map_ids = reader.get_all_ids()
            except Exception:
                pass

        if map_ids:
            bad_maps = set()
            for cols, vals in creature_inserts:
                mid = _get_column_value(cols, vals, 'map')
                if mid:
                    try:
                        map_val = int(mid)
                        if map_val not in map_ids:
                            bad_maps.add(map_val)
                    except ValueError:
                        pass

            if not bad_maps:
                results.append(ValidationResult(
                    check_id='SQL-REF-010',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="All spawn map IDs match DBC entries",
                ))
            else:
                results.append(ValidationResult(
                    check_id='SQL-REF-010',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="Spawn map IDs not in DBC: {}".format(
                        sorted(bad_maps)[:5]),
                    fix_suggestion="Align SQL map IDs with DBC",
                ))

    return results


# ---------------------------------------------------------------------------
# Completeness checks (SQL-COMP-001 through SQL-COMP-010)
# ---------------------------------------------------------------------------

def _validate_sql_completeness(sql_content):
    """Validate SQL completeness requirements."""
    results = []

    quest_ids = _extract_table_ids(sql_content, 'quest_template', 'ID')
    creature_template_ids = _extract_table_ids(
        sql_content, 'creature_template', 'entry')
    item_template_ids = _extract_table_ids(
        sql_content, 'item_template', 'entry')

    # Get quest starter/ender creature IDs for each quest
    queststarter_inserts = _extract_inserts(sql_content, 'creature_queststarter')
    questender_inserts = _extract_inserts(sql_content, 'creature_questender')

    starter_quests = set()
    for cols, vals in queststarter_inserts:
        qid = _get_column_value(cols, vals, 'quest')
        if qid:
            try:
                starter_quests.add(int(qid))
            except ValueError:
                pass

    ender_quests = set()
    for cols, vals in questender_inserts:
        qid = _get_column_value(cols, vals, 'quest')
        if qid:
            try:
                ender_quests.add(int(qid))
            except ValueError:
                pass

    # SQL-COMP-001: Every quest has starter and ender
    if quest_ids:
        no_starter = quest_ids - starter_quests
        no_ender = quest_ids - ender_quests
        if not no_starter and not no_ender:
            results.append(ValidationResult(
                check_id='SQL-COMP-001',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All {} quests have starters and enders".format(
                    len(quest_ids)),
            ))
        else:
            issues = []
            if no_starter:
                issues.append("{} without starter".format(len(no_starter)))
            if no_ender:
                issues.append("{} without ender".format(len(no_ender)))
            results.append(ValidationResult(
                check_id='SQL-COMP-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Quest completeness: {}".format(
                    '; '.join(issues)),
                fix_suggestion="Add queststarter/ender entries",
            ))

    # SQL-COMP-002: Quest giver NPCs have npcflag & 2
    quest_giver_ids = set()
    for cols, vals in queststarter_inserts:
        cid = _get_column_value(cols, vals, 'id')
        if cid:
            try:
                quest_giver_ids.add(int(cid))
            except ValueError:
                pass

    creature_inserts = _extract_inserts(sql_content, 'creature_template')
    bad_flags = []
    for cols, vals in creature_inserts:
        entry = _get_column_value(cols, vals, 'entry')
        npcflag = _get_column_value(cols, vals, 'npcflag')
        if entry and npcflag:
            try:
                eid = int(entry)
                nf = int(npcflag)
                if eid in quest_giver_ids and not (nf & 2):
                    bad_flags.append(eid)
            except ValueError:
                pass

    if quest_giver_ids:
        if not bad_flags:
            results.append(ValidationResult(
                check_id='SQL-COMP-002',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All quest giver NPCs have questgiver flag",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-002',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Quest givers missing npcflag&2: {}".format(
                    bad_flags[:5]),
                fix_suggestion="Set npcflag in creature_template",
            ))

    # SQL-COMP-003: Vendor NPCs have npcflag & 128
    vendor_inserts = _extract_inserts(sql_content, 'npc_vendor')
    vendor_ids = set()
    for cols, vals in vendor_inserts:
        entry = _get_column_value(cols, vals, 'entry')
        if entry:
            try:
                vendor_ids.add(int(entry))
            except ValueError:
                pass

    bad_vendor_flags = []
    for cols, vals in creature_inserts:
        entry = _get_column_value(cols, vals, 'entry')
        npcflag = _get_column_value(cols, vals, 'npcflag')
        if entry and npcflag:
            try:
                eid = int(entry)
                nf = int(npcflag)
                if eid in vendor_ids and not (nf & 128):
                    bad_vendor_flags.append(eid)
            except ValueError:
                pass

    if vendor_ids:
        if not bad_vendor_flags:
            results.append(ValidationResult(
                check_id='SQL-COMP-003',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All vendor NPCs have vendor flag",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-003',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Vendors missing npcflag&128: {}".format(
                    bad_vendor_flags[:5]),
                fix_suggestion="Set npcflag in creature_template",
            ))

    # SQL-COMP-004: Kill objectives reference valid creatures
    bad_kill_obj = []
    kill_cols = ['RequiredNpcOrGo1', 'RequiredNpcOrGo2',
                 'RequiredNpcOrGo3', 'RequiredNpcOrGo4']
    quest_tmpl_inserts = _extract_inserts(sql_content, 'quest_template')
    for cols, vals in quest_tmpl_inserts:
        for kcol in kill_cols:
            val = _get_column_value(cols, vals, kcol)
            if val:
                try:
                    nid = int(val)
                    if nid > 0 and nid not in creature_template_ids:
                        bad_kill_obj.append(nid)
                except ValueError:
                    pass

    if quest_tmpl_inserts and creature_template_ids:
        if not bad_kill_obj:
            results.append(ValidationResult(
                check_id='SQL-COMP-004',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="All kill objectives reference valid creatures",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-004',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Kill objectives reference missing creatures: "
                        "{}".format(bad_kill_obj[:5]),
                fix_suggestion="Add creature_template entries",
            ))

    # SQL-COMP-005: Item objectives reference valid items
    bad_item_obj = []
    item_obj_cols = ['RequiredItemId1', 'RequiredItemId2',
                     'RequiredItemId3', 'RequiredItemId4',
                     'RequiredItemId5', 'RequiredItemId6']
    for cols, vals in quest_tmpl_inserts:
        for icol in item_obj_cols:
            val = _get_column_value(cols, vals, icol)
            if val:
                try:
                    iid = int(val)
                    if iid > 0 and iid not in item_template_ids:
                        bad_item_obj.append(iid)
                except ValueError:
                    pass

    if quest_tmpl_inserts and item_template_ids:
        if not bad_item_obj:
            results.append(ValidationResult(
                check_id='SQL-COMP-005',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="All item objectives reference valid items",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-005',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Item objectives reference missing items: "
                        "{}".format(bad_item_obj[:5]),
                fix_suggestion="Add item_template entries",
            ))

    # SQL-COMP-006: Quest chain links
    addon_inserts = _extract_inserts(sql_content, 'quest_template_addon')
    broken_chains = []
    for cols, vals in addon_inserts:
        prev = _get_column_value(cols, vals, 'PrevQuestId')
        next_q = _get_column_value(cols, vals, 'NextQuestId')
        qid = _get_column_value(cols, vals, 'ID')
        if prev:
            try:
                pid = int(prev)
                if pid > 0 and pid not in quest_ids:
                    broken_chains.append(
                        "Quest {} PrevQuestId={}".format(qid, pid))
            except ValueError:
                pass
        if next_q:
            try:
                nid = int(next_q)
                if nid > 0 and nid not in quest_ids:
                    broken_chains.append(
                        "Quest {} NextQuestId={}".format(qid, nid))
            except ValueError:
                pass

    if addon_inserts:
        if not broken_chains:
            results.append(ValidationResult(
                check_id='SQL-COMP-006',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="All quest chain links valid",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-006',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Broken quest chains: {}".format(
                    broken_chains[:3]),
                fix_suggestion="Fix quest chain links",
            ))

    # SQL-COMP-007: SmartAI creatures have AIName='SmartAI'
    smart_entries = set()
    smart_inserts = _extract_inserts(sql_content, 'smart_scripts')
    for cols, vals in smart_inserts:
        entry = _get_column_value(cols, vals, 'entryorguid')
        source_type = _get_column_value(cols, vals, 'source_type')
        if entry and source_type:
            try:
                if int(source_type) == 0:
                    smart_entries.add(int(entry))
            except ValueError:
                pass

    bad_ainame = []
    for cols, vals in creature_inserts:
        entry = _get_column_value(cols, vals, 'entry')
        ainame = _get_column_value(cols, vals, 'AIName')
        if entry:
            try:
                eid = int(entry)
                if eid in smart_entries:
                    if ainame != 'SmartAI':
                        bad_ainame.append(eid)
            except ValueError:
                pass

    if smart_entries:
        if not bad_ainame:
            results.append(ValidationResult(
                check_id='SQL-COMP-007',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All SmartAI creatures have AIName='SmartAI'",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-007',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Creatures with SmartAI scripts but wrong "
                        "AIName: {}".format(bad_ainame[:5]),
                fix_suggestion="Set AIName field to 'SmartAI'",
            ))

    # SQL-COMP-008: All spawned creatures have templates
    spawn_inserts = _extract_inserts(sql_content, 'creature')
    spawned_ids = set()
    for cols, vals in spawn_inserts:
        cid = _get_column_value(cols, vals, 'id')
        if cid:
            try:
                spawned_ids.add(int(cid))
            except ValueError:
                pass

    missing_templates = spawned_ids - creature_template_ids
    if spawned_ids:
        if not missing_templates:
            results.append(ValidationResult(
                check_id='SQL-COMP-008',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All spawned creatures have templates",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-008',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Spawned creatures missing templates: "
                        "{}".format(sorted(missing_templates)[:5]),
                fix_suggestion="Add missing creature_template entries",
            ))

    # SQL-COMP-009: Boss loot references valid items
    # (Same as SQL-REF-005 but specifically for boss loot)
    loot_inserts_list = _extract_inserts(sql_content, 'creature_loot_template')
    bad_boss_loot = []
    for cols, vals in loot_inserts_list:
        item_id = _get_column_value(cols, vals, 'item')
        if item_id:
            try:
                iid = int(item_id)
                if iid > 0 and item_template_ids and iid not in item_template_ids:
                    bad_boss_loot.append(iid)
            except ValueError:
                pass

    if loot_inserts_list and item_template_ids:
        if not bad_boss_loot:
            results.append(ValidationResult(
                check_id='SQL-COMP-009',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="All boss loot references valid items",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-COMP-009',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Boss loot references missing items: {}".format(
                    bad_boss_loot[:5]),
                fix_suggestion="Add items to item_template",
            ))

    # SQL-COMP-010: Locale tables exist
    has_locales = bool(re.search(
        r'INSERT\s+INTO\s+`?(\w+_locale)', sql_content, re.IGNORECASE))
    results.append(ValidationResult(
        check_id='SQL-COMP-010',
        severity=ValidationSeverity.INFO,
        passed=has_locales or True,  # Always pass, info only
        message="Locale tables {}".format(
            "present" if has_locales else "not present (optional)"),
    ))

    return results


# ---------------------------------------------------------------------------
# Value range validation (SQL-VAL-001 through SQL-VAL-005)
# ---------------------------------------------------------------------------

def _validate_sql_values(sql_content):
    """Validate SQL value ranges."""
    results = []

    # SQL-VAL-001: Item stats within reasonable bounds
    item_inserts = _extract_inserts(sql_content, 'item_template')
    bad_stats = 0
    for cols, vals in item_inserts:
        for stat_col in ['stat_value1', 'stat_value2', 'stat_value3']:
            val = _get_column_value(cols, vals, stat_col)
            if val:
                try:
                    sv = int(val)
                    if abs(sv) > 1000:  # Unreasonably high stat value
                        bad_stats += 1
                except ValueError:
                    pass

    if item_inserts:
        if bad_stats == 0:
            results.append(ValidationResult(
                check_id='SQL-VAL-001',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Item stats within reasonable bounds",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-VAL-001',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="{} item stats exceed reasonable bounds".format(
                    bad_stats),
                fix_suggestion="Adjust item stats",
            ))

    # SQL-VAL-002: Quest XP/gold appropriate for level
    quest_inserts = _extract_inserts(sql_content, 'quest_template')
    bad_rewards = 0
    for cols, vals in quest_inserts:
        level = _get_column_value(cols, vals, 'QuestLevel')
        xp = _get_column_value(cols, vals, 'RewardXPDifficulty')
        if level and xp:
            try:
                lvl = int(level)
                xp_val = int(xp)
                # Very rough heuristic: XP difficulty ID should be 1-10
                if xp_val > 10:
                    bad_rewards += 1
            except ValueError:
                pass

    if quest_inserts:
        if bad_rewards == 0:
            results.append(ValidationResult(
                check_id='SQL-VAL-002',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Quest rewards appear appropriate",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-VAL-002',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="{} quests have unusual reward values".format(
                    bad_rewards),
                fix_suggestion="Scale rewards to quest level",
            ))

    # SQL-VAL-003: Creature HP/damage appropriate
    creature_inserts = _extract_inserts(sql_content, 'creature_template')
    bad_creature_stats = 0
    for cols, vals in creature_inserts:
        minlevel = _get_column_value(cols, vals, 'minlevel')
        maxlevel = _get_column_value(cols, vals, 'maxlevel')
        if minlevel and maxlevel:
            try:
                minl = int(minlevel)
                maxl = int(maxlevel)
                if minl > maxl:
                    bad_creature_stats += 1
                if minl < 1 or maxl > 83:  # 83 is max for WotLK
                    bad_creature_stats += 1
            except ValueError:
                pass

    if creature_inserts:
        if bad_creature_stats == 0:
            results.append(ValidationResult(
                check_id='SQL-VAL-003',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Creature level ranges appear valid",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-VAL-003',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="{} creatures have invalid level ranges".format(
                    bad_creature_stats),
                fix_suggestion="Adjust creature stats",
            ))

    # SQL-VAL-004: Spawn coordinates within map bounds
    spawn_inserts = _extract_inserts(sql_content, 'creature')
    bad_coords = 0
    map_bound = 17066.67  # Approximate WoW map coordinate limit
    for cols, vals in spawn_inserts:
        for coord_col in ['position_x', 'position_y']:
            val = _get_column_value(cols, vals, coord_col)
            if val:
                try:
                    cv = float(val)
                    if abs(cv) > map_bound:
                        bad_coords += 1
                except ValueError:
                    pass

    if spawn_inserts:
        if bad_coords == 0:
            results.append(ValidationResult(
                check_id='SQL-VAL-004',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="All spawn coordinates within map bounds",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-VAL-004',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="{} spawn coordinates outside map bounds".format(
                    bad_coords),
                fix_suggestion="Clamp coordinates to valid range",
            ))

    # SQL-VAL-005: Respawn timers
    bad_respawn = 0
    for cols, vals in spawn_inserts:
        respawn = _get_column_value(cols, vals, 'spawntimesecs')
        if respawn:
            try:
                rt = int(respawn)
                if rt < 0 or rt > 86400:  # 0 to 24 hours
                    bad_respawn += 1
            except ValueError:
                pass

    if spawn_inserts:
        if bad_respawn == 0:
            results.append(ValidationResult(
                check_id='SQL-VAL-005',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="Respawn timers within expected ranges",
            ))
        else:
            results.append(ValidationResult(
                check_id='SQL-VAL-005',
                severity=ValidationSeverity.INFO,
                passed=False,
                message="{} spawns have unusual respawn timers".format(
                    bad_respawn),
                fix_suggestion="Adjust respawn times (60-3600 seconds)",
            ))

    return results


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def validate_sql_files(sql_dir, dbc_dir=None):
    """
    Validate all SQL files in sql_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    sql_files = _read_sql_files(sql_dir)

    if not sql_files:
        results.append(ValidationResult(
            check_id='SQL-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No SQL files found to validate",
        ))
        return results

    # Syntax validation
    results.extend(_validate_sql_syntax(sql_files))

    # Combine all SQL content for relationship checks
    combined = '\n'.join(content for _fname, content in sql_files)

    # Referential integrity
    results.extend(_validate_sql_refs(combined, dbc_dir))

    # Completeness
    results.extend(_validate_sql_completeness(combined))

    # Value ranges
    results.extend(_validate_sql_values(combined))

    return results


def validate_sql_completeness(sql_dir):
    """
    Run only SQL completeness checks.

    Returns:
        List of ValidationResult objects.
    """
    sql_files = _read_sql_files(sql_dir)
    if not sql_files:
        return []

    combined = '\n'.join(content for _fname, content in sql_files)
    return _validate_sql_completeness(combined)
