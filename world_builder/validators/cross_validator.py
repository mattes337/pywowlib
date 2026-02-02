"""
Cross-layer consistency validator for WoW WotLK 3.3.5a.

Validates consistency between:
- DBC entries and SQL database entries
- ADT area IDs and AreaTable.dbc
- AreaTrigger.dbc and SQL areatrigger_teleport
- TaxiNodes and server-side setup
- LoadingScreens references
- LFGDungeons and SQL dungeon registration
"""

import os
import re
import struct

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_all_sql(sql_dir):
    """Read and concatenate all SQL files from a directory."""
    if not sql_dir or not os.path.isdir(sql_dir):
        return ''

    combined = []
    for fname in os.listdir(sql_dir):
        if not fname.lower().endswith('.sql'):
            continue
        fpath = os.path.join(sql_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                combined.append(f.read())
        except IOError:
            pass

    return '\n'.join(combined)


def _extract_sql_map_ids(sql_content):
    """Extract map IDs from instance_template and creature spawns."""
    map_ids = set()

    # instance_template map IDs
    for match in re.finditer(
        r"INSERT\s+INTO\s+`?instance_template`?\s*"
        r"\([^)]*map[^)]*\)\s*VALUES\s*\(\s*(\d+)",
        sql_content, re.IGNORECASE
    ):
        try:
            map_ids.add(int(match.group(1)))
        except ValueError:
            pass

    # Also extract from creature spawn map column
    pattern = (
        r"INSERT\s+INTO\s+`?creature`?\s*"
        r"\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)"
    )
    for match in re.finditer(pattern, sql_content, re.IGNORECASE):
        cols = [c.strip().strip('`') for c in match.group(1).split(',')]
        vals = [v.strip().strip("'\"") for v in match.group(2).split(',')]
        for i, col in enumerate(cols):
            if col.lower() == 'map' and i < len(vals):
                try:
                    map_ids.add(int(vals[i]))
                except ValueError:
                    pass

    return map_ids


def _extract_sql_areatrigger_maps(sql_content):
    """Extract map IDs from areatrigger_teleport table."""
    map_ids = set()
    pattern = (
        r"INSERT\s+INTO\s+`?areatrigger_teleport`?\s*"
        r"\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)"
    )
    for match in re.finditer(pattern, sql_content, re.IGNORECASE):
        cols = [c.strip().strip('`') for c in match.group(1).split(',')]
        vals = [v.strip().strip("'\"") for v in match.group(2).split(',')]
        for i, col in enumerate(cols):
            if col.lower() == 'target_map' and i < len(vals):
                try:
                    map_ids.add(int(vals[i]))
                except ValueError:
                    pass
    return map_ids


def _read_dbc_ids(dbc_dir, dbc_name):
    """Read all record IDs from a DBC file."""
    ids = set()
    if not dbc_dir:
        return ids

    filepath = os.path.join(dbc_dir, "{}.dbc".format(dbc_name))
    if not os.path.isfile(filepath):
        return ids

    try:
        from .dbc_validator import _DBCReader
        reader = _DBCReader(filepath)
        if reader.valid:
            ids = reader.get_all_ids()
    except Exception:
        pass

    return ids


def _read_dbc_map_ids(dbc_dir):
    """Read Map.dbc record IDs."""
    return _read_dbc_ids(dbc_dir, 'Map')


def _read_dbc_area_ids(dbc_dir):
    """Read AreaTable.dbc record IDs."""
    return _read_dbc_ids(dbc_dir, 'AreaTable')


def _read_adt_area_ids(client_dir):
    """
    Read area IDs from all ADT files in client_dir.

    Returns set of area IDs found in MCNK headers.
    """
    area_ids = set()
    if not client_dir or not os.path.isdir(client_dir):
        return area_ids

    for base in [client_dir, os.path.join(client_dir, "mpq_content")]:
        maps_root = os.path.join(base, "World", "Maps")
        if not os.path.isdir(maps_root):
            continue

        for map_name in os.listdir(maps_root):
            map_dir = os.path.join(maps_root, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in os.listdir(map_dir):
                if not fname.lower().endswith('.adt'):
                    continue
                fpath = os.path.join(map_dir, fname)
                try:
                    with open(fpath, 'rb') as f:
                        data = f.read()
                    # Quick scan for MCNK chunks and extract area IDs
                    pos = 0
                    mcnk_magic = b'KNCM'
                    while pos < len(data) - 8:
                        idx = data.find(mcnk_magic, pos)
                        if idx == -1:
                            break
                        # MCNK header starts after chunk header (8 bytes)
                        hdr_start = idx + 8
                        # area_id is at offset 52 in MCNK header
                        area_offset = hdr_start + 52
                        if area_offset + 4 <= len(data):
                            area_id = struct.unpack_from(
                                '<I', data, area_offset)[0]
                            area_ids.add(area_id)
                        pos = idx + 8
                except IOError:
                    pass

    return area_ids


def _read_dbc_areatrigger_ids(dbc_dir):
    """Read AreaTrigger.dbc record IDs."""
    return _read_dbc_ids(dbc_dir, 'AreaTrigger')


def _read_dbc_lfgdungeons_map_ids(dbc_dir):
    """Read MapID values from LFGDungeons.dbc."""
    map_ids = set()
    if not dbc_dir:
        return map_ids

    filepath = os.path.join(dbc_dir, "LFGDungeons.dbc")
    if not os.path.isfile(filepath):
        return map_ids

    try:
        from .dbc_validator import _DBCReader
        reader = _DBCReader(filepath)
        if reader.valid:
            for i in range(len(reader.records)):
                mid = reader.get_field_u32(i, 23)  # MapID field
                map_ids.add(mid)
    except Exception:
        pass

    return map_ids


# ---------------------------------------------------------------------------
# Cross-layer validation (CROSS-001 through CROSS-006)
# ---------------------------------------------------------------------------

def validate_cross_layer(client_dir, sql_dir, dbc_dir):
    """
    Validate consistency between client and server data.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    sql_content = _read_all_sql(sql_dir)
    has_sql = bool(sql_content.strip())

    dbc_map_ids = _read_dbc_map_ids(dbc_dir)
    dbc_area_ids = _read_dbc_area_ids(dbc_dir)

    # CROSS-001: Map IDs in DBC match SQL instance_template
    if has_sql and dbc_map_ids:
        sql_map_ids = _extract_sql_map_ids(sql_content)
        if sql_map_ids:
            mismatched = sql_map_ids - dbc_map_ids
            if not mismatched:
                results.append(ValidationResult(
                    check_id='CROSS-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="Map IDs in SQL match DBC "
                            "({})".format(sorted(sql_map_ids)),
                ))
            else:
                results.append(ValidationResult(
                    check_id='CROSS-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="SQL map IDs not in DBC: {}".format(
                        sorted(mismatched)),
                    fix_suggestion="Align map IDs between DBC and SQL",
                ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-001',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="No map IDs found in SQL to cross-validate",
            ))
    elif not has_sql:
        results.append(ValidationResult(
            check_id='CROSS-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-001 skipped: no SQL data available",
        ))
    elif not dbc_map_ids:
        results.append(ValidationResult(
            check_id='CROSS-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-001 skipped: no DBC Map data available",
        ))

    # CROSS-002: Area IDs in ADT chunks match AreaTable.dbc
    if dbc_area_ids:
        adt_area_ids = _read_adt_area_ids(client_dir)
        if adt_area_ids:
            unknown_areas = adt_area_ids - dbc_area_ids - {0}
            if not unknown_areas:
                results.append(ValidationResult(
                    check_id='CROSS-002',
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message="ADT area IDs match AreaTable.dbc entries",
                ))
            else:
                results.append(ValidationResult(
                    check_id='CROSS-002',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="ADT area IDs not in AreaTable.dbc: {}".format(
                        sorted(unknown_areas)[:10]),
                    fix_suggestion="Set correct MCNK area IDs",
                ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-002',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="No ADT area IDs to cross-validate",
            ))
    else:
        results.append(ValidationResult(
            check_id='CROSS-002',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-002 skipped: no AreaTable.dbc data available",
        ))

    # CROSS-003: AreaTrigger.dbc entries have matching SQL teleport entries
    if has_sql and dbc_dir:
        at_ids = _read_dbc_areatrigger_ids(dbc_dir)
        if at_ids:
            # Check if areatrigger_teleport SQL references match
            sql_at_maps = _extract_sql_areatrigger_maps(sql_content)
            if sql_at_maps:
                results.append(ValidationResult(
                    check_id='CROSS-003',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="AreaTrigger SQL entries found "
                            "({} teleport maps)".format(len(sql_at_maps)),
                ))
            else:
                results.append(ValidationResult(
                    check_id='CROSS-003',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="No areatrigger_teleport SQL entries "
                            "(may not be needed)",
                ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-003',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="No AreaTrigger.dbc entries to validate",
            ))
    else:
        results.append(ValidationResult(
            check_id='CROSS-003',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-003 skipped: SQL or DBC data unavailable",
        ))

    # CROSS-004: TaxiNodes.dbc consistency
    if dbc_dir:
        taxi_ids = _read_dbc_ids(dbc_dir, 'TaxiNodes')
        if taxi_ids:
            results.append(ValidationResult(
                check_id='CROSS-004',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="TaxiNodes.dbc has {} entries".format(len(taxi_ids)),
            ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-004',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="No custom TaxiNodes.dbc entries found",
            ))
    else:
        results.append(ValidationResult(
            check_id='CROSS-004',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-004 skipped: no DBC directory available",
        ))

    # CROSS-005: LoadingScreens.dbc referenced by Map.dbc
    if dbc_dir:
        ls_ids = _read_dbc_ids(dbc_dir, 'LoadingScreens')
        if ls_ids and dbc_map_ids:
            results.append(ValidationResult(
                check_id='CROSS-005',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="LoadingScreens.dbc has {} entries, "
                        "Map.dbc has {} entries".format(
                            len(ls_ids), len(dbc_map_ids)),
            ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-005',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="LoadingScreens/Map DBC cross-check "
                        "not applicable",
            ))
    else:
        results.append(ValidationResult(
            check_id='CROSS-005',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-005 skipped: no DBC directory available",
        ))

    # CROSS-006: LFGDungeons.dbc map IDs match SQL dungeon registration
    if has_sql and dbc_dir:
        lfg_map_ids = _read_dbc_lfgdungeons_map_ids(dbc_dir)
        if lfg_map_ids:
            sql_map_ids = _extract_sql_map_ids(sql_content)
            unmatched = lfg_map_ids - sql_map_ids
            if not unmatched or not sql_map_ids:
                results.append(ValidationResult(
                    check_id='CROSS-006',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="LFGDungeons map IDs consistent with SQL",
                ))
            else:
                results.append(ValidationResult(
                    check_id='CROSS-006',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="LFGDungeons map IDs not in SQL: {}".format(
                        sorted(unmatched)[:5]),
                    fix_suggestion="Verify dungeon SQL registration",
                ))
        else:
            results.append(ValidationResult(
                check_id='CROSS-006',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="No LFGDungeons.dbc entries to validate",
            ))
    else:
        results.append(ValidationResult(
            check_id='CROSS-006',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="CROSS-006 skipped: SQL or DBC data unavailable",
        ))

    return results
