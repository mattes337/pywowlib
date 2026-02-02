"""
QA Validator orchestrator for WoW WotLK 3.3.5a zone generation.

Validates all generated assets for correctness:
- Client-side files: ADT, WDT, WMO, DBC, BLP, MPQ
- Server-side SQL scripts (when present)
- Lua/C++ scripts (when present)
- Cross-layer consistency (client <-> server)

Usage:
    from world_builder.qa_validator import QAValidator

    validator = QAValidator(
        client_dir='./output/Patch-Z/',
        sql_dir='./output/sql/',
        script_dir='./output/scripts/',
        dbc_dir='C:/WoW_3.3.5a/Data/DBFilesClient/',
    )
    report = validator.run_full_validation()
    report.print_summary()
    report.write_report('qa_report.md')
"""

import os
import time
from enum import Enum


# ---------------------------------------------------------------------------
# Validation result classes
# ---------------------------------------------------------------------------

class ValidationSeverity(Enum):
    """Severity level for a validation check."""
    ERROR = "ERROR"       # Critical issue, will crash client/server
    WARNING = "WARNING"   # Non-critical issue, may cause bugs
    INFO = "INFO"         # Informational, best practice violation
    SKIP = "SKIP"         # Check skipped (requires in-game testing)


class ValidationResult:
    """Single validation check result."""

    def __init__(self, check_id, severity, passed, message,
                 details=None, fix_suggestion=None):
        """
        Args:
            check_id: Unique identifier for this check (e.g. 'DBC-001').
            severity: ValidationSeverity enum value.
            passed: True if the check passed, False if it failed.
            message: Short human-readable description of result.
            details: Optional longer description of what was found.
            fix_suggestion: Optional suggestion for how to fix the issue.
        """
        self.check_id = check_id
        self.severity = severity
        self.passed = passed
        self.message = message
        self.details = details
        self.fix_suggestion = fix_suggestion

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return "ValidationResult({}, {}, {}, {!r})".format(
            self.check_id, self.severity.value, status, self.message
        )


# ---------------------------------------------------------------------------
# QAValidator - Main orchestrator
# ---------------------------------------------------------------------------

class QAValidator:
    """
    Main orchestrator for automated QA validation of WoW zone generation.

    Validates:
    - Client-side files: ADT, WDT, WMO, DBC, BLP, MPQ
    - Server-side SQL scripts (when present)
    - Lua/C++ scripts (when present)
    - Cross-layer consistency (client <-> server)
    """

    def __init__(self, client_dir, sql_dir=None, script_dir=None, dbc_dir=None):
        """
        Initialize QA validator with paths to generated assets.

        Args:
            client_dir: Path to client patch output (e.g. './output/Patch-Z/')
                        This is the root of the MPQ content tree containing
                        World/Maps/ and optionally DBFilesClient/.
            sql_dir: Optional path to SQL scripts (e.g. './output/sql/').
            script_dir: Optional path to Lua/C++ scripts (e.g. './output/scripts/').
            dbc_dir: Optional path to source DBC files for FK validation
                     (e.g. 'C:/WoW_3.3.5a/Data/DBFilesClient/').
        """
        self.client_dir = os.path.abspath(client_dir) if client_dir else None
        self.sql_dir = os.path.abspath(sql_dir) if sql_dir else None
        self.script_dir = os.path.abspath(script_dir) if script_dir else None
        self.dbc_dir = os.path.abspath(dbc_dir) if dbc_dir else None

    # ------------------------------------------------------------------
    # Full validation
    # ------------------------------------------------------------------

    def run_full_validation(self):
        """
        Run all validation checks and return comprehensive report.

        Returns:
            QAReport: Object containing all validation results with methods
                for printing summaries and writing detailed reports.
        """
        from .qa_report import QAReport

        start_time = time.time()
        all_results = []

        # DBC integrity
        all_results.extend(self.validate_dbc_integrity())

        # ADT terrain files
        all_results.extend(self.validate_adt_files())

        # WDT grid
        all_results.extend(self.validate_wdt_files())

        # BLP textures
        all_results.extend(self.validate_blp_files())

        # WMO structures
        all_results.extend(self.validate_wmo_files())

        # MPQ archive
        all_results.extend(self.validate_mpq_files())

        # SQL scripts (when present)
        all_results.extend(self.validate_sql_references())

        # Lua/C++ scripts (when present)
        all_results.extend(self.validate_scripts())

        # Cross-layer consistency
        all_results.extend(self.validate_cross_layer())

        elapsed = time.time() - start_time

        metadata = self._build_metadata(all_results, elapsed)

        return QAReport(all_results, metadata)

    # ------------------------------------------------------------------
    # Individual validation categories
    # ------------------------------------------------------------------

    def validate_dbc_integrity(self):
        """Validate DBC file binary structure and referential integrity."""
        from .validators.dbc_validator import validate_dbc_files
        return validate_dbc_files(self.client_dir, self.dbc_dir)

    def validate_adt_files(self):
        """Validate ADT terrain files."""
        from .validators.adt_validator import validate_adt_files
        return validate_adt_files(self.client_dir, self.dbc_dir)

    def validate_wdt_files(self):
        """Validate WDT grid files."""
        from .validators.wdt_validator import validate_wdt_files
        return validate_wdt_files(self.client_dir)

    def validate_blp_files(self):
        """Validate BLP texture files."""
        from .validators.blp_validator import validate_blp_files
        return validate_blp_files(self.client_dir)

    def validate_wmo_files(self):
        """Validate WMO structure files."""
        from .validators.wmo_validator import validate_wmo_files
        return validate_wmo_files(self.client_dir)

    def validate_mpq_files(self):
        """Validate MPQ archive contents."""
        from .validators.mpq_validator import validate_mpq_files
        return validate_mpq_files(self.client_dir)

    def validate_sql_references(self):
        """Validate SQL syntax and foreign key relationships."""
        from .validators.sql_validator import validate_sql_files
        return validate_sql_files(self.sql_dir, self.dbc_dir)

    def validate_scripts(self):
        """Validate Lua/C++ script files."""
        from .validators.script_validator import validate_script_files
        return validate_script_files(self.script_dir, self.sql_dir)

    def validate_cross_layer(self):
        """Validate consistency between client and server data."""
        from .validators.cross_validator import validate_cross_layer
        return validate_cross_layer(
            self.client_dir, self.sql_dir, self.dbc_dir
        )

    def validate_completeness(self):
        """
        Validate that all required entities are present.

        This is a convenience wrapper that runs SQL completeness checks.
        """
        from .validators.sql_validator import validate_sql_completeness
        return validate_sql_completeness(self.sql_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_metadata(self, results, elapsed):
        """Build metadata dict for the QA report."""
        zone_name = self._detect_zone_name()
        map_id = self._detect_map_id()

        # Count files by type
        file_counts = {}
        if self.client_dir and os.path.isdir(self.client_dir):
            for root, _dirs, files in os.walk(self.client_dir):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    file_counts[ext] = file_counts.get(ext, 0) + 1

        return {
            'zone_name': zone_name,
            'map_id': map_id,
            'client_dir': self.client_dir,
            'sql_dir': self.sql_dir,
            'script_dir': self.script_dir,
            'dbc_dir': self.dbc_dir,
            'elapsed_seconds': elapsed,
            'file_counts': file_counts,
        }

    def _detect_zone_name(self):
        """Attempt to detect zone name from directory structure."""
        if not self.client_dir or not os.path.isdir(self.client_dir):
            return "Unknown"

        # Look for World/Maps/{name}/ subdirectory
        maps_dir = os.path.join(self.client_dir, "World", "Maps")
        if not os.path.isdir(maps_dir):
            # Try mpq_content subdirectory
            maps_dir = os.path.join(self.client_dir, "mpq_content",
                                    "World", "Maps")

        if os.path.isdir(maps_dir):
            entries = [e for e in os.listdir(maps_dir)
                       if os.path.isdir(os.path.join(maps_dir, e))]
            if entries:
                return entries[0]

        return "Unknown"

    def _detect_map_id(self):
        """Attempt to detect map ID from DBC files."""
        if not self.dbc_dir:
            return None

        map_dbc_path = os.path.join(self.dbc_dir, "Map.dbc")
        if not os.path.isfile(map_dbc_path):
            return None

        # Read last record ID from Map.dbc as a heuristic
        try:
            from .dbc_injector import DBCInjector
            dbc = DBCInjector(map_dbc_path)
            if dbc.records:
                return dbc.get_max_id()
        except Exception:
            pass

        return None
