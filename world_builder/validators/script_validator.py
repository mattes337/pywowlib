"""
Script (Lua/C++) validator for WoW WotLK 3.3.5a.

Validates:
- Basic Lua syntax (balanced brackets, string literals, keywords)
- Script references to creature/spell/gameobject entries
- Phase transition coverage
- Boss encounter logic checks
"""

import os
import re

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_script_files(script_dir):
    """
    Find all script files under script_dir.

    Returns list of (filename, content, language) tuples.
    Language is 'lua' or 'cpp'.
    """
    scripts = []
    if not script_dir or not os.path.isdir(script_dir):
        return scripts

    for root, _dirs, files in os.walk(script_dir):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext == '.lua':
                lang = 'lua'
            elif ext in ('.cpp', '.h', '.hpp'):
                lang = 'cpp'
            else:
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                scripts.append((fname, content, lang))
            except IOError:
                pass

    return scripts


# ---------------------------------------------------------------------------
# Lua syntax validation (SCRIPT-001)
# ---------------------------------------------------------------------------

def _validate_lua_syntax(fname, content):
    """Basic Lua syntax checking."""
    errors = []

    # Remove string literals and comments for structural checks
    # Single-line comments
    cleaned = re.sub(r'--\[\[.*?\]\]', '', content, flags=re.DOTALL)
    cleaned = re.sub(r'--[^\n]*', '', cleaned)
    # String literals
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)
    cleaned = re.sub(r"'[^']*'", "''", cleaned)
    cleaned = re.sub(r'\[\[.*?\]\]', '""', cleaned, flags=re.DOTALL)

    # Check balanced brackets
    for open_char, close_char, name in [
        ('(', ')', 'parentheses'),
        ('{', '}', 'braces'),
        ('[', ']', 'brackets'),
    ]:
        count = cleaned.count(open_char) - cleaned.count(close_char)
        if count != 0:
            errors.append("Unbalanced {}: {} extra {}".format(
                name, abs(count),
                'opening' if count > 0 else 'closing'))

    # Check keyword pairing (function/end, if/end, do/end, etc.)
    # Simple heuristic: count openers vs 'end'
    openers = len(re.findall(
        r'\b(function|if|for|while|do|repeat)\b', cleaned))
    # 'then' is part of if, 'do' is part of for/while
    # 'end' closes function, if, for, while, do blocks
    enders = len(re.findall(r'\bend\b', cleaned))
    # 'until' closes repeat blocks
    untils = len(re.findall(r'\buntil\b', cleaned))
    repeats = len(re.findall(r'\brepeat\b', cleaned))

    expected_ends = openers - repeats  # repeat blocks end with 'until'
    if enders != expected_ends and abs(enders - expected_ends) > 1:
        errors.append("Keyword imbalance: {} openers, {} end, "
                      "{} repeat/until".format(
                          openers, enders, repeats))

    return errors


# ---------------------------------------------------------------------------
# Reference validation (SCRIPT-002)
# ---------------------------------------------------------------------------

def _extract_entity_refs(content, lang):
    """
    Extract numeric entity references from script content.

    Looks for patterns like:
    - GetCreatureEntry(12345)
    - creature_template entry = 12345
    - NPC_ID = 12345
    """
    refs = set()

    # Common patterns for entity references
    patterns = [
        r'(?:NPC|CREATURE|BOSS|ENTRY|SPELL|GO|GAMEOBJECT)[\w_]*\s*=\s*(\d+)',
        r'(?:GetCreature|SpawnCreature|SummonCreature)\s*\(\s*(\d+)',
        r'(?:CastSpell|RemoveAura)\s*\(\s*(?:\w+,\s*)?(\d+)',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            try:
                val = int(match.group(1))
                if val > 100:  # Skip small constants
                    refs.add(val)
            except (ValueError, IndexError):
                pass

    return refs


def _read_sql_ids(sql_dir):
    """Read creature and spell IDs from SQL files if available."""
    creature_ids = set()
    if not sql_dir or not os.path.isdir(sql_dir):
        return creature_ids

    for fname in os.listdir(sql_dir):
        if not fname.lower().endswith('.sql'):
            continue
        fpath = os.path.join(sql_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            # Extract creature_template entries
            for match in re.finditer(
                r"INSERT\s+INTO\s+`?creature_template`?\s*"
                r"\([^)]*entry[^)]*\)\s*VALUES\s*\(\s*(\d+)",
                content, re.IGNORECASE
            ):
                try:
                    creature_ids.add(int(match.group(1)))
                except ValueError:
                    pass
        except IOError:
            pass

    return creature_ids


# ---------------------------------------------------------------------------
# Phase validation (SCRIPT-003)
# ---------------------------------------------------------------------------

def _validate_phase_coverage(fname, content):
    """Check if boss scripts cover HP range with phases."""
    issues = []

    # Look for phase definitions
    phase_patterns = [
        r'PHASE[_\s]*(\d+)',
        r'phase\s*[=<>]+\s*(\d+)',
        r'SetPhase\s*\(\s*(\d+)',
    ]

    phases = set()
    for pattern in phase_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            try:
                phases.add(int(match.group(1)))
            except ValueError:
                pass

    # Look for HP percentage checks
    hp_thresholds = set()
    hp_patterns = [
        r'HealthPct\s*[<>=]+\s*(\d+)',
        r'GetHealthPct\s*\(\s*\)\s*[<>=]+\s*(\d+)',
        r'HP_PCT\s*[<>=]+\s*(\d+)',
    ]
    for pattern in hp_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            try:
                hp_thresholds.add(int(match.group(1)))
            except ValueError:
                pass

    if phases and hp_thresholds:
        # Check if phases cover reasonable HP range
        if not any(t >= 90 for t in hp_thresholds):
            issues.append("No phase transition above 90% HP")
        if not any(t <= 30 for t in hp_thresholds):
            issues.append("No phase transition below 30% HP")

    return phases, hp_thresholds, issues


# ---------------------------------------------------------------------------
# Logic checks (SCRIPT-LOG-001 through SCRIPT-LOG-005)
# ---------------------------------------------------------------------------

def _validate_script_logic(fname, content, lang):
    """Validate script logic patterns."""
    results = []

    # SCRIPT-LOG-001: Boss encounters have ability timers
    has_timers = bool(re.search(
        r'(?:Timer|Cooldown|DoDelayedCast|ScheduleAbility|RegisterEvent)',
        content, re.IGNORECASE))
    has_boss = bool(re.search(
        r'(?:Boss|BOSS|boss_|RegisterBossEvent)',
        content, re.IGNORECASE))

    if has_boss:
        if has_timers:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-001',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Script {} has boss timers defined".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-001',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Script {} appears to be boss script but "
                        "no timers found".format(fname),
                fix_suggestion="Define phase timers for boss abilities",
            ))

    # SCRIPT-LOG-002: Instance script handles boss kill states
    has_instance = bool(re.search(
        r'(?:instance_|InstanceScript|InstanceData)',
        content, re.IGNORECASE))

    if has_instance:
        has_kill_handler = bool(re.search(
            r'(?:OnCreatureKill|BossKilled|SetBossState|DONE)',
            content, re.IGNORECASE))
        if has_kill_handler:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-002',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Script {} handles boss kill states".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-002',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="Script {} is instance script but no kill "
                        "state handler found".format(fname),
                fix_suggestion="Add kill state handlers",
            ))

    # SCRIPT-LOG-003: Door unlock logic
    if has_instance:
        has_door = bool(re.search(
            r'(?:Door|DOOR|HandleGameObject|GO_STATE)',
            content, re.IGNORECASE))
        if has_door:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-003',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Script {} has door/gameobject logic".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='SCRIPT-LOG-003',
                severity=ValidationSeverity.WARNING,
                passed=True,  # Not all instances need doors
                message="Script {} has no door logic (may be "
                        "intentional)".format(fname),
            ))

    # SCRIPT-LOG-004: Achievement criteria
    has_achievement = bool(re.search(
        r'(?:Achievement|ACHIEVEMENT|DoCompleteAchievement)',
        content, re.IGNORECASE))
    if has_achievement:
        results.append(ValidationResult(
            check_id='SCRIPT-LOG-004',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="Script {} has achievement hooks".format(fname),
        ))
    elif has_boss:
        results.append(ValidationResult(
            check_id='SCRIPT-LOG-004',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="Script {} has no achievement hooks (optional)".format(
                fname),
        ))

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_script_files(script_dir, sql_dir=None):
    """
    Validate all script files found in script_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    scripts = _find_script_files(script_dir)

    if not scripts:
        results.append(ValidationResult(
            check_id='SCRIPT-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No script files found to validate",
        ))
        return results

    sql_creature_ids = _read_sql_ids(sql_dir)

    for fname, content, lang in scripts:
        # SCRIPT-001: Syntax check
        if lang == 'lua':
            syntax_errors = _validate_lua_syntax(fname, content)
            if not syntax_errors:
                results.append(ValidationResult(
                    check_id='SCRIPT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="Lua script {} syntax OK".format(fname),
                ))
            else:
                results.append(ValidationResult(
                    check_id='SCRIPT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="Lua script {} syntax issues: {}".format(
                        fname, syntax_errors[:3]),
                    fix_suggestion="Fix syntax errors",
                ))
        else:
            # For C++, just check balanced braces
            cleaned = re.sub(r'"[^"]*"', '""', content)
            cleaned = re.sub(r"'[^']*'", "''", cleaned)
            cleaned = re.sub(r'//[^\n]*', '', cleaned)
            cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
            brace_count = cleaned.count('{') - cleaned.count('}')
            if brace_count == 0:
                results.append(ValidationResult(
                    check_id='SCRIPT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="C++ script {} braces balanced".format(fname),
                ))
            else:
                results.append(ValidationResult(
                    check_id='SCRIPT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="C++ script {} has {} unbalanced "
                            "braces".format(fname, abs(brace_count)),
                    fix_suggestion="Fix syntax errors",
                ))

        # SCRIPT-002: Entity references exist in SQL
        if sql_creature_ids:
            entity_refs = _extract_entity_refs(content, lang)
            missing_refs = entity_refs - sql_creature_ids
            if not missing_refs:
                results.append(ValidationResult(
                    check_id='SCRIPT-002',
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message="Script {} entity references all found "
                            "in SQL".format(fname),
                ))
            else:
                results.append(ValidationResult(
                    check_id='SCRIPT-002',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="Script {} references entries not in SQL: "
                            "{}".format(fname, sorted(missing_refs)[:5]),
                    fix_suggestion="Add missing SQL entries",
                ))

        # SCRIPT-003: Phase transitions
        phases, hp_thresholds, phase_issues = _validate_phase_coverage(
            fname, content)
        if phases:
            if not phase_issues:
                results.append(ValidationResult(
                    check_id='SCRIPT-003',
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message="Script {} phases {} cover HP range".format(
                        fname, sorted(phases)),
                ))
            else:
                results.append(ValidationResult(
                    check_id='SCRIPT-003',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="Script {} phase issues: {}".format(
                        fname, phase_issues),
                    fix_suggestion="Add missing phases to cover "
                                   "full HP range (100->0)",
                ))

        # Logic checks
        results.extend(_validate_script_logic(fname, content, lang))

    # SCRIPT-LOG-005: Boss difficulty balance - always SKIP
    results.append(ValidationResult(
        check_id='SCRIPT-LOG-005',
        severity=ValidationSeverity.SKIP,
        passed=True,
        message="Boss difficulty balance requires in-game testing",
    ))

    return results
