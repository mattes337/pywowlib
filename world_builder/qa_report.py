"""
QA Report generator for WoW WotLK 3.3.5a zone validation.

Generates Markdown reports and console summaries from validation results.
"""

import os
import sys
import time
import platform

from .qa_validator import ValidationSeverity, ValidationResult


# ---------------------------------------------------------------------------
# Category labels for grouping results in reports
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = [
    'DBC',
    'ADT',
    'WDT',
    'BLP',
    'WMO',
    'MPQ',
    'SQL',
    'SCRIPT',
    'CROSS',
]

_CATEGORY_LABELS = {
    'DBC': 'DBC Integrity',
    'ADT': 'ADT Terrain',
    'WDT': 'WDT Grid',
    'BLP': 'BLP Textures',
    'WMO': 'WMO Structures',
    'MPQ': 'MPQ Archive',
    'SQL': 'SQL Scripts',
    'SCRIPT': 'Lua/C++ Scripts',
    'CROSS': 'Cross-Layer Consistency',
}


def _get_category(check_id):
    """Extract category prefix from a check ID like 'DBC-001' -> 'DBC'."""
    parts = check_id.split('-')
    if not parts:
        return 'OTHER'
    prefix = parts[0]
    # Map compound prefixes to their base category
    if prefix in ('DBC', 'ADT', 'WDT', 'BLP', 'WMO', 'MPQ', 'SQL', 'SCRIPT', 'CROSS'):
        return prefix
    return 'OTHER'


# ---------------------------------------------------------------------------
# QAReport class
# ---------------------------------------------------------------------------

class QAReport:
    """Container for all validation results with reporting methods."""

    def __init__(self, results, metadata):
        """
        Args:
            results: List of ValidationResult objects.
            metadata: Dict with zone_name, map_id, elapsed_seconds,
                      file_counts, paths, etc.
        """
        self.results = results
        self.metadata = metadata

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def get_score(self):
        """
        Calculate 0-100 coverage score.

        Formula: score = (passed_checks / total_checks) * 100
        where total_checks excludes SKIP results.
        Returns 100.0 if there are no applicable checks.
        """
        applicable = [r for r in self.results
                      if r.severity != ValidationSeverity.SKIP]
        if not applicable:
            return 100.0

        passed = sum(1 for r in applicable if r.passed)
        return (passed / float(len(applicable))) * 100.0

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def _count_by_severity(self, severity, passed_only=None):
        """Count results matching a severity and optional pass/fail filter."""
        count = 0
        for r in self.results:
            if r.severity != severity:
                continue
            if passed_only is not None and r.passed != passed_only:
                continue
            count += 1
        return count

    def _counts(self):
        """Return summary counts dict."""
        total = len(self.results)
        skipped = self._count_by_severity(ValidationSeverity.SKIP)
        applicable = total - skipped
        passed = sum(1 for r in self.results
                     if r.passed and r.severity != ValidationSeverity.SKIP)
        failed_errors = self._count_by_severity(ValidationSeverity.ERROR,
                                                passed_only=False)
        failed_warnings = self._count_by_severity(ValidationSeverity.WARNING,
                                                  passed_only=False)
        failed_info = self._count_by_severity(ValidationSeverity.INFO,
                                              passed_only=False)
        return {
            'total': total,
            'applicable': applicable,
            'passed': passed,
            'failed': applicable - passed,
            'errors': failed_errors,
            'warnings': failed_warnings,
            'infos': failed_info,
            'skipped': skipped,
        }

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------

    def print_summary(self):
        """Print console summary with pass/fail counts by severity."""
        counts = self._counts()
        zone_name = self.metadata.get('zone_name', 'Unknown')
        score = self.get_score()

        lines = []
        lines.append("")
        lines.append("=== QA Validation Summary: {} ===".format(zone_name))
        lines.append("")
        lines.append("Coverage Score: {:.1f}% ({}/{} checks passed)".format(
            score, counts['passed'], counts['applicable']
        ))
        lines.append("")
        lines.append("ERROR:   {} failed".format(counts['errors']))
        lines.append("WARNING: {} failed".format(counts['warnings']))
        lines.append("INFO:    {} failed".format(counts['infos']))
        lines.append("SKIPPED: {}".format(counts['skipped']))
        lines.append("")

        # List critical errors
        errors = [r for r in self.results
                  if not r.passed and r.severity == ValidationSeverity.ERROR]
        if errors:
            lines.append("Critical Issues:")
            for r in errors:
                lines.append("  [{}] {}".format(r.check_id, r.message))
            lines.append("")

        # List warnings
        warnings = [r for r in self.results
                    if not r.passed
                    and r.severity == ValidationSeverity.WARNING]
        if warnings:
            lines.append("Warnings:")
            for r in warnings[:10]:
                lines.append("  [{}] {}".format(r.check_id, r.message))
            if len(warnings) > 10:
                lines.append("  ... ({} more warnings)".format(
                    len(warnings) - 10))
            lines.append("")

        if not errors and not warnings:
            lines.append("All automated checks passed!")
            lines.append("")

        # Timing
        elapsed = self.metadata.get('elapsed_seconds', 0)
        if elapsed > 0:
            lines.append("Validation completed in {:.2f}s".format(elapsed))
            lines.append("")

        output = "\n".join(lines)
        print(output)

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------

    def write_report(self, output_path):
        """
        Write detailed Markdown report to file.

        Args:
            output_path: File path for the output Markdown report.
        """
        lines = self._build_report_lines()
        content = "\n".join(lines)

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _build_report_lines(self):
        """Build all lines of the Markdown report."""
        lines = []
        counts = self._counts()
        score = self.get_score()
        zone_name = self.metadata.get('zone_name', 'Unknown')
        map_id = self.metadata.get('map_id', 'N/A')
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

        # Title and metadata
        lines.append("# QA Validation Report: {}".format(zone_name))
        lines.append("")
        lines.append("**Generated:** {}".format(timestamp))
        lines.append("**Zone:** {}".format(zone_name))
        lines.append("**Map ID:** {}".format(map_id))
        lines.append("**Coverage Score:** {:.1f}/100".format(score))
        lines.append("")
        lines.append("---")
        lines.append("")

        # Executive summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append("- **Total Checks:** {}".format(counts['total']))
        lines.append("- **Passed:** {}".format(counts['passed']))
        lines.append("- **Failed:** {}".format(counts['failed']))
        lines.append("- **Warnings:** {}".format(counts['warnings']))
        lines.append("- **Skipped (In-Game Required):** {}".format(
            counts['skipped']))
        lines.append("")

        if counts['errors'] == 0:
            overall = "PASS"
        elif counts['errors'] <= 3:
            overall = "PARTIAL"
        else:
            overall = "FAIL"
        lines.append("**Overall Status:** {}".format(overall))
        lines.append("")
        lines.append("---")
        lines.append("")

        # Results by category
        lines.append("## Validation Results by Category")
        lines.append("")

        categorized = self._group_by_category()
        section_num = 1

        for cat_key in _CATEGORY_ORDER:
            if cat_key not in categorized:
                continue
            cat_results = categorized[cat_key]
            cat_label = _CATEGORY_LABELS.get(cat_key, cat_key)

            lines.append("### {}. {}".format(section_num, cat_label))
            lines.append("")
            lines.append("| Check ID | Severity | Status | Message |")
            lines.append("|----------|----------|--------|---------|")

            for r in cat_results:
                if r.severity == ValidationSeverity.SKIP:
                    status = "SKIP"
                elif r.passed:
                    status = "PASS"
                else:
                    status = "FAIL"
                lines.append("| {} | {} | {} | {} |".format(
                    r.check_id, r.severity.value, status, r.message
                ))

            lines.append("")

            # List failed checks with details
            failed = [r for r in cat_results if not r.passed
                      and r.severity != ValidationSeverity.SKIP]
            if failed:
                lines.append("**Failed Checks:**")
                for r in failed:
                    lines.append("- **{}:** {}".format(r.check_id, r.message))
                    if r.details:
                        lines.append("  - {}".format(r.details))
                    if r.fix_suggestion:
                        lines.append("  - **Fix:** {}".format(
                            r.fix_suggestion))
                lines.append("")

            lines.append("---")
            lines.append("")
            section_num += 1

        # Handle OTHER category if present
        if 'OTHER' in categorized:
            cat_results = categorized['OTHER']
            lines.append("### {}. Other Checks".format(section_num))
            lines.append("")
            lines.append("| Check ID | Severity | Status | Message |")
            lines.append("|----------|----------|--------|---------|")
            for r in cat_results:
                status = "PASS" if r.passed else "FAIL"
                lines.append("| {} | {} | {} | {} |".format(
                    r.check_id, r.severity.value, status, r.message
                ))
            lines.append("")
            lines.append("---")
            lines.append("")
            section_num += 1

        # Skipped checks section
        skipped = [r for r in self.results
                   if r.severity == ValidationSeverity.SKIP]
        if skipped:
            lines.append("## Skipped Checks (Require In-Game Testing)")
            lines.append("")
            lines.append("| Check ID | Category | Description |")
            lines.append("|----------|----------|-------------|")
            for r in skipped:
                cat = _get_category(r.check_id)
                cat_label = _CATEGORY_LABELS.get(cat, cat)
                lines.append("| {} | {} | {} |".format(
                    r.check_id, cat_label, r.message
                ))
            lines.append("")
            lines.append(
                "**Note:** These checks require manual in-game verification "
                "as they involve subjective quality assessment or runtime "
                "behavior that cannot be validated statically."
            )
            lines.append("")
            lines.append("---")
            lines.append("")

        # Detailed findings
        errors = [r for r in self.results
                  if not r.passed and r.severity == ValidationSeverity.ERROR]
        warnings = [r for r in self.results
                    if not r.passed
                    and r.severity == ValidationSeverity.WARNING]

        if errors or warnings:
            lines.append("## Detailed Findings")
            lines.append("")

            if errors:
                lines.append("### Critical Errors (Must Fix Before Release)")
                lines.append("")
                for i, r in enumerate(errors, 1):
                    lines.append("{}. **{}:** {}".format(
                        i, r.check_id, r.message))
                    if r.details:
                        lines.append("   - **Impact:** {}".format(r.details))
                    if r.fix_suggestion:
                        lines.append("   - **Fix:** {}".format(
                            r.fix_suggestion))
                lines.append("")

            if warnings:
                lines.append("### Warnings (Recommended to Fix)")
                lines.append("")
                for i, r in enumerate(warnings, 1):
                    lines.append("{}. **{}:** {}".format(
                        i, r.check_id, r.message))
                    if r.details:
                        lines.append("   - **Impact:** {}".format(r.details))
                    if r.fix_suggestion:
                        lines.append("   - **Fix:** {}".format(
                            r.fix_suggestion))
                lines.append("")

            lines.append("---")
            lines.append("")

        # Coverage breakdown table
        lines.append("## Coverage Breakdown")
        lines.append("")
        lines.append(
            "| Category | Total | Passed | Failed | Warnings | "
            "Skipped | Score |"
        )
        lines.append(
            "|----------|-------|--------|--------|----------|"
            "---------|-------|"
        )

        total_all = 0
        passed_all = 0
        failed_all = 0
        warn_all = 0
        skip_all = 0

        for cat_key in _CATEGORY_ORDER:
            if cat_key not in categorized:
                continue
            cat_results = categorized[cat_key]
            cat_label = _CATEGORY_LABELS.get(cat_key, cat_key)

            cat_total = len(cat_results)
            cat_skip = sum(1 for r in cat_results
                           if r.severity == ValidationSeverity.SKIP)
            cat_applicable = cat_total - cat_skip
            cat_passed = sum(1 for r in cat_results
                             if r.passed
                             and r.severity != ValidationSeverity.SKIP)
            cat_failed_err = sum(
                1 for r in cat_results
                if not r.passed and r.severity == ValidationSeverity.ERROR
            )
            cat_failed_warn = sum(
                1 for r in cat_results
                if not r.passed and r.severity == ValidationSeverity.WARNING
            )
            cat_failed = cat_applicable - cat_passed

            if cat_applicable > 0:
                cat_score = "{:.1f}%".format(
                    (cat_passed / float(cat_applicable)) * 100.0
                )
            else:
                cat_score = "N/A"

            lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                cat_label, cat_total, cat_passed, cat_failed_err,
                cat_failed_warn, cat_skip, cat_score
            ))

            total_all += cat_total
            passed_all += cat_passed
            failed_all += cat_failed
            warn_all += cat_failed_warn
            skip_all += cat_skip

        applicable_all = total_all - skip_all
        if applicable_all > 0:
            total_score = "{:.1f}%".format(
                (passed_all / float(applicable_all)) * 100.0
            )
        else:
            total_score = "N/A"
        err_all = sum(1 for r in self.results
                      if not r.passed
                      and r.severity == ValidationSeverity.ERROR)

        lines.append("| **TOTAL** | **{}** | **{}** | **{}** | **{}** "
                     "| **{}** | **{}** |".format(
                         total_all, passed_all, err_all,
                         warn_all, skip_all, total_score
                     ))
        lines.append("")
        lines.append("---")
        lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")
        if errors:
            lines.append("### Immediate Actions (Critical)")
            lines.append("")
            for i, r in enumerate(errors, 1):
                suggestion = r.fix_suggestion if r.fix_suggestion else r.message
                lines.append("{}. {}".format(i, suggestion))
            lines.append("")

        if warnings:
            lines.append("### Optional Improvements")
            lines.append("")
            for i, r in enumerate(warnings[:5], 1):
                suggestion = r.fix_suggestion if r.fix_suggestion else r.message
                lines.append("{}. {}".format(i, suggestion))
            lines.append("")

        # Appendix
        lines.append("---")
        lines.append("")
        lines.append("## Appendix: Tool Versions")
        lines.append("")
        lines.append("- **Python:** {}".format(platform.python_version()))
        lines.append("- **OS:** {}".format(platform.platform()))
        elapsed = self.metadata.get('elapsed_seconds', 0)
        lines.append("- **Validation Time:** {:.2f}s".format(elapsed))
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by pywowlib QA Validator*")
        lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _group_by_category(self):
        """Group results by check ID category prefix."""
        groups = {}
        for r in self.results:
            cat = _get_category(r.check_id)
            if cat not in groups:
                groups[cat] = []
            groups[cat].append(r)
        return groups
