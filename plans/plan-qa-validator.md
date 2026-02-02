# Plan: Automated QA Validation Suite for WoW 3.3.5a Zone Generation

## 1. Overview

This plan documents the implementation of an automated QA validation suite that enables verification of ALL generated assets for a WoW 3.3.5a zone without requiring manual in-game testing. This enables **TODO 5.1 (End-to-End QA Test)** to be as automated as possible.

### 1.1 Context

**Current pywowlib world_builder capabilities:**
- **Client-side generation**: ADT, WDT, WMO, DBC patches, BLP textures, MPQ archives
- **Server-side generation** (planned): SQL scripts for TrinityCore 3.3.5a
- **Script generation** (planned): Lua/C++ scripts for NPC AI, boss encounters, quests

**Validation scope:**
- Cross-validate all generated assets for consistency
- Verify binary format correctness (headers, chunk sizes, field counts)
- Check referential integrity across DBC files
- Validate SQL foreign key relationships
- Ensure completeness (every entity has required dependencies)

### 1.2 What CAN Be Automated

✅ **Binary format validation** (DBC headers, ADT chunks, BLP magic)
✅ **Referential integrity** (Map.dbc ID → AreaTable.dbc ContinentID)
✅ **SQL syntax and FK constraints** (creature.id → creature_template.entry)
✅ **Completeness checks** (every quest has starter/ender NPCs)
✅ **Value range validation** (coordinates within tile bounds)
✅ **Cross-layer consistency** (DBC Map ID matches SQL instance_template)

### 1.3 What CANNOT Be Automated (Requires In-Game Testing)

❌ **Visual appearance** (texture quality, model placement aesthetics)
❌ **Gameplay feel** (pacing, quest flow, difficulty balance)
❌ **Pathfinding** (NPC pathing, player navigation smoothness)
❌ **Boss difficulty balance** (HP/damage tuning, mechanic timings)
❌ **Audio quality** (music transitions, ambient sound levels)
❌ **Performance** (client FPS in high-detail areas)

---

## 2. Architecture

### 2.1 Module Structure

```
world_builder/
├── qa_validator.py          # Main validator orchestrator
├── validators/
│   ├── __init__.py
│   ├── dbc_validator.py     # DBC file integrity and references
│   ├── adt_validator.py     # ADT terrain structure validation
│   ├── blp_validator.py     # BLP texture format validation
│   ├── wdt_validator.py     # WDT grid validation
│   ├── wmo_validator.py     # WMO structure validation
│   ├── mpq_validator.py     # MPQ archive validation
│   ├── sql_validator.py     # SQL syntax and FK validation
│   ├── script_validator.py  # Lua/C++ script validation
│   └── cross_validator.py   # Cross-layer consistency checks
└── qa_report.py             # Markdown report generation
```

### 2.2 Main Class: `QAValidator`

**File:** `world_builder/qa_validator.py`

```python
class QAValidator:
    """
    Main orchestrator for automated QA validation of WoW zone generation.

    Validates:
    - Client-side files: ADT, WDT, WMO, DBC, BLP, MPQ
    - Server-side SQL scripts (when present)
    - Lua/C++ scripts (when present)
    - Cross-layer consistency (client ↔ server)
    """

    def __init__(self, client_dir, sql_dir=None, script_dir=None, dbc_dir=None):
        """
        Initialize QA validator with paths to generated assets.

        Args:
            client_dir: Path to client patch output (e.g., './output/Patch-Z/')
            sql_dir: Optional path to SQL scripts (e.g., './output/sql/')
            script_dir: Optional path to Lua/C++ scripts (e.g., './output/scripts/')
            dbc_dir: Optional path to source DBC files for FK validation
                     (e.g., 'C:/WoW_3.3.5a/Data/DBFilesClient/')
        """

    def run_full_validation(self) -> QAReport:
        """
        Run all validation checks and return comprehensive report.

        Returns:
            QAReport: Object containing validation results with methods:
                - print_summary(): Print console summary
                - write_report(path): Write detailed Markdown report
                - get_score(): Get 0-100 coverage score
        """

    def validate_dbc_integrity(self) -> List[ValidationResult]:
        """Validate DBC file binary structure and referential integrity."""

    def validate_adt_files(self) -> List[ValidationResult]:
        """Validate ADT terrain files."""

    def validate_sql_references(self) -> List[ValidationResult]:
        """Validate SQL syntax and foreign key relationships."""

    def validate_completeness(self) -> List[ValidationResult]:
        """Validate that all required entities are present."""

    def validate_cross_layer(self) -> List[ValidationResult]:
        """Validate consistency between client and server data."""
```

### 2.3 Validation Result Classes

```python
from enum import Enum
from typing import List, Optional

class ValidationSeverity(Enum):
    ERROR = "ERROR"       # Critical issue, will crash client/server
    WARNING = "WARNING"   # Non-critical issue, may cause bugs
    INFO = "INFO"         # Informational, best practice violation
    SKIP = "SKIP"         # Check skipped (requires in-game testing)

class ValidationResult:
    """Single validation check result."""

    def __init__(self,
                 check_id: str,
                 severity: ValidationSeverity,
                 passed: bool,
                 message: str,
                 details: Optional[str] = None,
                 fix_suggestion: Optional[str] = None):
        self.check_id = check_id
        self.severity = severity
        self.passed = passed
        self.message = message
        self.details = details
        self.fix_suggestion = fix_suggestion

class QAReport:
    """Container for all validation results with reporting methods."""

    def __init__(self, results: List[ValidationResult], metadata: dict):
        self.results = results
        self.metadata = metadata  # Zone name, timestamp, file counts, etc.

    def get_score(self) -> float:
        """
        Calculate 0-100 coverage score.

        Formula:
            score = (passed_checks / total_checks) * 100
            where total_checks excludes SKIP results
        """

    def print_summary(self):
        """Print console summary with pass/fail counts by severity."""

    def write_report(self, output_path: str):
        """Write detailed Markdown report to file."""
```

---

## 3. Validation Rules

### 3.1 DBC Integrity Checks

**Validator:** `validators/dbc_validator.py`

#### 3.1.1 Binary Format Validation

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-001` | ERROR | Verify WDBC magic header | Regenerate DBC with DBCInjector |
| `DBC-002` | ERROR | Verify `record_count * record_size + string_block_size` matches file size | Check record padding, string block |
| `DBC-003` | ERROR | Verify no duplicate IDs in single DBC | Remove duplicate entries |
| `DBC-004` | ERROR | Verify string offsets point within string block | Rebuild string block with deduplication |
| `DBC-005` | WARNING | Check for orphaned strings in string block | Clean up string block (optional) |

#### 3.1.2 Field-Specific Validation

**Map.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-MAP-001` | ERROR | Verify Directory field matches WDT/ADT folder name | Fix Directory string in Map.dbc |
| `DBC-MAP-002` | WARNING | Verify InstanceType is valid (0=world, 1=party, 2=raid, 3=pvp, 4=arena) | Correct InstanceType value |
| `DBC-MAP-003` | INFO | Check LoadingScreenID references valid LoadingScreens.dbc entry | Add LoadingScreens entry or use 0 |
| `DBC-MAP-004` | WARNING | Verify MinimapIconScale > 0 | Set to 1.0 default |

**AreaTable.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-AREA-001` | ERROR | Verify ContinentID references valid Map.dbc ID | Register map first, then area |
| `DBC-AREA-002` | WARNING | Verify ParentAreaID=0 for top-level zones OR references valid AreaTable ID | Set to 0 or valid parent |
| `DBC-AREA-003` | INFO | Check ExplorationLevel matches zone level range | Set to min quest level |
| `DBC-AREA-004` | WARNING | Verify FactionGroupMask is valid (0=both, 2=alliance, 4=horde) | Set appropriate faction mask |

**WorldMapArea.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-WMA-001` | ERROR | Verify MapID references valid Map.dbc entry | Register map first |
| `DBC-WMA-002` | ERROR | Verify AreaID references valid AreaTable.dbc entry | Register area first |
| `DBC-WMA-003` | WARNING | Check LocLeft < LocRight and LocTop < LocBottom | Swap coordinates if inverted |
| `DBC-WMA-004` | INFO | Verify DisplayMapID=-1 OR references valid Map | Use -1 for self-display |

**WorldMapOverlay.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-WMO-001` | ERROR | Verify MapAreaID references valid WorldMapArea.dbc entry | Register WorldMapArea first |
| `DBC-WMO-002` | WARNING | Verify AreaID[0-3] either 0 OR reference valid AreaTable entries | Set unused slots to 0 |
| `DBC-WMO-003` | INFO | Check TextureWidth/Height are powers of 2 | Use 512 or 1024 |

**LoadingScreens.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-LS-001` | WARNING | Verify FileName points to valid BLP path | Check BLP exists in output |
| `DBC-LS-002` | INFO | Check HasWideScreen flag (0 or 1) | Use 1 for modern support |

**LFGDungeons.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-LFG-001` | ERROR | Verify MapID references valid Map.dbc entry | Register map first |
| `DBC-LFG-002` | WARNING | Verify MinLevel ≤ MaxLevel | Swap if inverted |
| `DBC-LFG-003` | WARNING | Verify Difficulty is 0 (normal) or 1 (heroic) | Correct difficulty value |
| `DBC-LFG-004` | INFO | Check TypeID (1=dungeon, 2=raid) matches InstanceType | Align type with map instance type |

**DungeonEncounter.dbc checks:**

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-DE-001` | ERROR | Verify MapID references valid Map.dbc entry | Register map first |
| `DBC-DE-002` | WARNING | Verify Bit values are sequential (0, 1, 2, 3) for dungeon bosses | Reassign bit values |
| `DBC-DE-003` | WARNING | Verify OrderIndex values are sequential | Reassign order indices |

#### 3.1.3 Cross-DBC Referential Integrity

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `DBC-REF-001` | ERROR | AreaTable.ContinentID → Map.ID | Register map before area |
| `DBC-REF-002` | ERROR | WorldMapArea.MapID → Map.ID | Register map before WorldMapArea |
| `DBC-REF-003` | ERROR | WorldMapArea.AreaID → AreaTable.ID | Register area before WorldMapArea |
| `DBC-REF-004` | ERROR | WorldMapOverlay.MapAreaID → WorldMapArea.ID | Register WorldMapArea before overlay |
| `DBC-REF-005` | WARNING | WorldMapOverlay.AreaID[n] → AreaTable.ID (if non-zero) | Verify area IDs exist |
| `DBC-REF-006` | WARNING | Map.LoadingScreenID → LoadingScreens.ID (if non-zero) | Register loading screen or set to 0 |
| `DBC-REF-007` | ERROR | LFGDungeons.MapID → Map.ID | Register map before LFG entry |
| `DBC-REF-008` | ERROR | DungeonEncounter.MapID → Map.ID | Register map before encounters |

### 3.2 ADT Validation

**Validator:** `validators/adt_validator.py`

#### 3.2.1 Chunk Structure

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `ADT-001` | ERROR | Verify MVER chunk (version 18 for WotLK) | Regenerate ADT with correct version |
| `ADT-002` | ERROR | Verify MHDR present with correct offset structure | Check adt_composer.py header logic |
| `ADT-003` | ERROR | Verify MCIN has 256 entries pointing to 256 MCNKs | Regenerate with correct MCIN table |
| `ADT-004` | ERROR | Each MCNK has required sub-chunks: MCVT, MCNR | Add missing sub-chunks |
| `ADT-005` | WARNING | Check MCLY present if textures defined | Add MCLY for texture layers |
| `ADT-006` | WARNING | Check MCAL size matches texture layer count | Fix alpha map data |

#### 3.2.2 Heightmap Validation

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `ADT-HM-001` | ERROR | Verify MCVT has 145 float values (9x9 + 8x8 interleaved) | Check heightmap generation logic |
| `ADT-HM-002` | WARNING | Check height values within reasonable range (-2048 to +2048 yards) | Clamp heights to valid range |
| `ADT-HM-003` | INFO | Verify MCNR has 145 normal vectors (3 bytes each + 13 padding) | Regenerate normals |

#### 3.2.3 Texture References

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `ADT-TEX-001` | ERROR | Verify texture paths in MTEX exist in WoW client OR are custom | Document required custom BLPs |
| `ADT-TEX-002` | WARNING | Check texture indices in MCLY reference valid MTEX entries | Fix layer texture indices |
| `ADT-TEX-003` | WARNING | Verify MCAL alpha map size (4096 bytes per layer for highres uncompressed) | Fix alpha map packing |

#### 3.2.4 Area ID Assignment

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `ADT-AREA-001` | WARNING | Verify MCNK area IDs match expected zone assignment | Set correct area ID in MCNK header |
| `ADT-AREA-002` | INFO | Check area ID references valid AreaTable.dbc entry | Register area in DBC |

#### 3.2.5 Doodad/WMO References

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `ADT-DOOD-001` | WARNING | Verify MMDX/MMID doodad references exist (or are empty) | Clear or populate doodad lists |
| `ADT-DOOD-002` | WARNING | Verify MWMO/MWID WMO references exist (or are empty) | Clear or populate WMO lists |
| `ADT-DOOD-003` | INFO | Check MDDF/MODF placement definitions match reference counts | Align placement data |

### 3.3 WDT Validation

**Validator:** `validators/wdt_validator.py`

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `WDT-001` | ERROR | Verify active tile flags match existing ADT files | Regenerate WDT with correct tile list |
| `WDT-002` | WARNING | Check MPHD flags are correct (0x80 for big alpha recommended) | Set MPHD flags appropriately |
| `WDT-003` | ERROR | Verify MAIN chunk has 4096 entries (64x64 grid) | Use correct WDT generation |
| `WDT-004` | WARNING | Check for gaps in tile grid (isolated active tiles) | Fill gaps or document intentional |

### 3.4 WMO Validation

**Validator:** `validators/wmo_validator.py`

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `WMO-001` | ERROR | Verify group count matches number of group files | Fix MOHD header group count |
| `WMO-002` | WARNING | Check material references are valid | Provide valid material definitions |
| `WMO-003` | INFO | Verify portal definitions connect valid groups | Fix portal group indices |
| `WMO-004` | WARNING | Check bounding boxes are reasonable | Recalculate from geometry |
| `WMO-005` | SKIP | Visual appearance of WMO geometry | Requires in-game inspection |

### 3.5 BLP Validation

**Validator:** `validators/blp_validator.py`

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `BLP-001` | ERROR | Verify BLP2 magic header | Regenerate with PNG2BLP |
| `BLP-002` | ERROR | Verify dimensions are powers of 2 (64, 128, 256, 512, 1024, 2048) | Resize source PNG before conversion |
| `BLP-003` | WARNING | Check mipmap offsets/sizes are valid | Regenerate with proper mipmaps |
| `BLP-004` | ERROR | Verify file is not truncated (size matches header) | Check PNG2BLP conversion logs |
| `BLP-005` | INFO | Check compression type (DXT1/DXT3/DXT5 or uncompressed) | Use appropriate format for content |

### 3.6 MPQ Validation

**Validator:** `validators/mpq_validator.py`

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `MPQ-001` | ERROR | Verify all expected files are present in archive | Check mpq_packer.py add_file calls |
| `MPQ-002` | WARNING | Check internal paths match WoW conventions (`World\Maps\{name}\`) | Fix path strings in packer |
| `MPQ-003` | WARNING | Check for extra/orphaned files not part of zone | Remove unused files |
| `MPQ-004` | INFO | Verify listfile is present (optional but recommended) | Generate listfile for archive |

### 3.7 SQL Validation (When Present)

**Validator:** `validators/sql_validator.py`

#### 3.7.1 Syntax Validation

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SQL-001` | ERROR | Parse SQL for syntax errors (basic regex or sqlite test) | Fix SQL syntax errors |
| `SQL-002` | ERROR | Verify all INSERT statements have matching column counts | Check column lists |

#### 3.7.2 Referential Integrity

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SQL-REF-001` | ERROR | `creature_queststarter.id` → `creature_template.entry` | Register creature_template first |
| `SQL-REF-002` | ERROR | `creature_questender.id` → `creature_template.entry` | Register creature_template first |
| `SQL-REF-003` | ERROR | `quest_template` reward items → `item_template.entry` | Register items before quests |
| `SQL-REF-004` | ERROR | `quest_template` required items → `item_template.entry` | Register items before quests |
| `SQL-REF-005` | ERROR | `creature_loot_template.item` → `item_template.entry` | Register items before loot tables |
| `SQL-REF-006` | ERROR | `npc_vendor.item` → `item_template.entry` | Register items before vendors |
| `SQL-REF-007` | ERROR | `smart_scripts.entryorguid` → `creature_template.entry` | Register creature_template first |
| `SQL-REF-008` | ERROR | `creature.id` → `creature_template.entry` | Register template before spawns |
| `SQL-REF-009` | WARNING | `quest_template_addon.PrevQuestId` → `quest_template.ID` | Verify quest chains |
| `SQL-REF-010` | ERROR | Spawn map IDs match registered Map.dbc entries | Align SQL map IDs with DBC |

#### 3.7.3 Completeness Checks

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SQL-COMP-001` | ERROR | Every quest has both a starter and ender NPC | Add queststarter/ender entries |
| `SQL-COMP-002` | ERROR | Every quest giver NPC has `npcflag & 2` (quest giver flag) | Set npcflag in creature_template |
| `SQL-COMP-003` | ERROR | Every vendor NPC has `npcflag & 128` | Set npcflag in creature_template |
| `SQL-COMP-004` | WARNING | Every quest with kill objectives references valid creature entries | Add creature_template entries |
| `SQL-COMP-005` | WARNING | Every quest with item objectives references valid item entries | Add item_template entries |
| `SQL-COMP-006` | WARNING | Every quest chain has correct PrevQuestId/NextQuestId links | Fix quest chain links |
| `SQL-COMP-007` | ERROR | All creatures with SmartAI have `AIName = 'SmartAI'` | Set AIName field |
| `SQL-COMP-008` | ERROR | All spawned creatures have creature_template entries | Add missing templates |
| `SQL-COMP-009` | WARNING | All boss loot entries reference valid item entries | Add items to item_template |
| `SQL-COMP-010` | INFO | Locale tables exist for all entities (if translation was generated) | Generate locale tables |

#### 3.7.4 Value Range Validation

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SQL-VAL-001` | WARNING | Item stats within reasonable bounds for level range | Adjust item stats |
| `SQL-VAL-002` | WARNING | Quest XP/gold appropriate for quest level | Scale rewards to level |
| `SQL-VAL-003` | WARNING | Creature HP/damage appropriate for level and rank | Adjust creature stats |
| `SQL-VAL-004` | ERROR | Spawn coordinates within map tile bounds | Clamp coordinates to valid range |
| `SQL-VAL-005` | INFO | Respawn timers within expected ranges (60-3600 seconds) | Adjust respawn times |

### 3.8 Script Validation (When Present)

**Validator:** `validators/script_validator.py`

#### 3.8.1 Lua Syntax

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SCRIPT-001` | ERROR | Basic Lua syntax check (balanced brackets, string literals, keywords) | Fix syntax errors |
| `SCRIPT-002` | WARNING | Verify all referenced creature/spell/gameobject entries exist in SQL | Add missing SQL entries |
| `SCRIPT-003` | WARNING | Verify phase transitions cover full HP range (100→0) | Add missing phases |

#### 3.8.2 Logic Checks

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `SCRIPT-LOG-001` | WARNING | Boss encounters have ability timers defined for all phases | Define phase timers |
| `SCRIPT-LOG-002` | WARNING | Instance script handles all boss kill states | Add kill state handlers |
| `SCRIPT-LOG-003` | WARNING | Door unlock logic covers all boss progression | Add door unlock events |
| `SCRIPT-LOG-004` | INFO | Achievement criteria are trackable | Verify achievement hooks |
| `SCRIPT-LOG-005` | SKIP | Boss difficulty balance (HP/damage/mechanic tuning) | Requires in-game testing |

### 3.9 Cross-Layer Validation

**Validator:** `validators/cross_validator.py`

| Check ID | Severity | Description | Fix Suggestion |
|----------|----------|-------------|----------------|
| `CROSS-001` | ERROR | Map IDs in DBC match instance_template map IDs in SQL | Align map IDs |
| `CROSS-002` | WARNING | Area IDs in ADT chunks match AreaTable.dbc entries | Set correct MCNK area IDs |
| `CROSS-003` | ERROR | AreaTrigger.dbc entries have matching areatrigger_teleport SQL entries | Add SQL teleport entries |
| `CROSS-004` | INFO | TaxiNodes.dbc entries match server-side taxi node setup | Verify taxi nodes |
| `CROSS-005` | INFO | LoadingScreens.dbc IDs referenced by Map.dbc | Link loading screens |
| `CROSS-006` | ERROR | LFGDungeons.dbc map IDs match SQL dungeon registration | Verify dungeon SQL |

---

## 4. Report Format

### 4.1 Markdown Report Structure

**File:** `world_builder/qa_report.py`

Generated report (`output/qa_report.md`) structure:

```markdown
# QA Validation Report: {Zone Name}

**Generated:** {timestamp}
**Zone:** {zone_name}
**Map ID:** {map_id}
**Coverage Score:** {score}/100

---

## Executive Summary

- **Total Checks:** {total_checks}
- **Passed:** {passed_count} ✅
- **Failed:** {failed_count} ❌
- **Warnings:** {warning_count} ⚠️
- **Skipped (In-Game Required):** {skip_count} 🎮

**Overall Status:** {PASS | FAIL | PARTIAL}

---

## Validation Results by Category

### 1. DBC Integrity

| Check ID | Severity | Status | Message |
|----------|----------|--------|---------|
| DBC-001 | ERROR | ✅ PASS | WDBC magic header verified |
| DBC-002 | ERROR | ✅ PASS | Record count matches file size |
| DBC-MAP-001 | ERROR | ❌ FAIL | Directory field mismatch: "TelAbim" != "TelAbimVault" |

**Failed Checks:**
- **DBC-MAP-001:** Directory field in Map.dbc ("TelAbim") does not match WDT folder name ("TelAbimVault")
  - **Fix:** Update Map.dbc Directory string to match actual folder structure

---

### 2. ADT Terrain

| Check ID | Severity | Status | Message |
|----------|----------|--------|---------|
| ADT-001 | ERROR | ✅ PASS | MVER chunk version 18 verified |
| ADT-HM-002 | WARNING | ⚠️ WARN | Height value out of range at tile (32,32) MCNK(5,8): 3500.0 yards |

**Warnings:**
- **ADT-HM-002:** Heightmap value exceeds recommended range (±2048 yards)
  - **Fix:** Clamp heights to valid range or document intentional extreme elevation

---

### 3. Cross-Layer Consistency

| Check ID | Severity | Status | Message |
|----------|----------|--------|---------|
| CROSS-001 | ERROR | ✅ PASS | Map ID 800 matches in DBC and SQL |
| CROSS-002 | WARNING | ✅ PASS | Area IDs in ADT match AreaTable.dbc |

---

### 4. Skipped Checks (Require In-Game Testing)

| Check ID | Category | Description |
|----------|----------|-------------|
| WMO-005 | Visual | WMO geometry appearance |
| SCRIPT-LOG-005 | Gameplay | Boss difficulty balance |

**Note:** These checks require manual in-game verification as they involve subjective quality assessment or runtime behavior that cannot be validated statically.

---

## Detailed Findings

### Critical Errors (Must Fix Before Release)

1. **DBC-MAP-001:** Map.dbc Directory field mismatch
   - **Impact:** Client will fail to load terrain files
   - **Location:** Map.dbc record ID 800
   - **Fix:** `register_map(dbc_dir, "TelAbimVault", map_id=800)`

### Warnings (Recommended to Fix)

1. **ADT-HM-002:** Heightmap value out of range
   - **Impact:** May cause visual glitches or pathfinding issues
   - **Location:** ADT tile (32, 32), MCNK chunk (5, 8)
   - **Fix:** Clamp heights: `height = max(-2048, min(2048, height))`

---

## Coverage Breakdown

| Category | Total | Passed | Failed | Warnings | Skipped | Score |
|----------|-------|--------|--------|----------|---------|-------|
| DBC Integrity | 45 | 43 | 2 | 0 | 0 | 95.6% |
| ADT Terrain | 30 | 28 | 0 | 2 | 0 | 93.3% |
| WDT Grid | 4 | 4 | 0 | 0 | 0 | 100% |
| BLP Textures | 5 | 5 | 0 | 0 | 0 | 100% |
| MPQ Archive | 4 | 4 | 0 | 0 | 0 | 100% |
| SQL Scripts | 25 | 23 | 1 | 1 | 0 | 92.0% |
| Lua Scripts | 8 | 7 | 0 | 0 | 1 | 87.5% |
| Cross-Layer | 6 | 6 | 0 | 0 | 0 | 100% |
| **TOTAL** | **127** | **120** | **3** | **3** | **1** | **94.5%** |

---

## Recommendations

### Immediate Actions (Critical)
1. Fix Map.dbc Directory field to match WDT folder name
2. Resolve SQL foreign key violations in creature_queststarter

### Optional Improvements
1. Clamp heightmap values to ±2048 yards range
2. Add locale tables for translated entity names

### In-Game Testing Required
1. Verify WMO visual appearance and lighting
2. Test boss encounter difficulty and mechanic timings
3. Validate pathfinding and player navigation
4. Check performance in high-detail areas

---

## Appendix: Tool Versions

- **pywowlib:** {version}
- **Python:** {python_version}
- **OS:** {os_platform}

---

*Report generated by pywowlib QA Validator*
```

### 4.2 Console Summary Format

```
=== QA Validation Summary: Tel'Abim ===

Coverage Score: 94.5% (120/127 checks passed)

ERROR:   3 ❌
WARNING: 3 ⚠️
INFO:    1 ℹ️
SKIPPED: 1 🎮

Critical Issues:
  [DBC-MAP-001] Map.dbc Directory field mismatch
  [SQL-REF-001] creature_queststarter references missing template entry 50001

Warnings:
  [ADT-HM-002] Height value out of range at tile (32,32)

Run 'report.write_report("qa_report.md")' for detailed analysis.
```

---

## 5. Tel'Abim Example: Expected Validation Output

### 5.1 Correctly Built Zone

For a correctly generated Tel'Abim zone:

```python
from world_builder.qa_validator import QAValidator

validator = QAValidator(
    client_dir='./output/Patch-Z/',
    sql_dir='./output/sql/',
    script_dir='./output/scripts/',
    dbc_dir='C:/WoW_3.3.5a/Data/DBFilesClient/',
)

report = validator.run_full_validation()
```

**Expected output:**
```
=== QA Validation Summary: Tel'Abim ===

Coverage Score: 100% (142/142 checks passed)

ERROR:   0 ❌
WARNING: 0 ⚠️
INFO:    0 ℹ️
SKIPPED: 5 🎮

All automated checks passed! ✅

Skipped checks (require in-game testing):
  - WMO visual appearance
  - Boss difficulty balance
  - Pathfinding validation
  - Audio quality
  - Performance testing

Proceed to in-game testing phase (TODO 5.2).
```

### 5.2 Zone with Issues

For a zone with validation errors:

```
=== QA Validation Summary: Tel'Abim ===

Coverage Score: 87.3% (124/142 checks passed)

ERROR:   3 ❌
WARNING: 12 ⚠️
INFO:    3 ℹ️
SKIPPED: 5 🎮

Critical Issues:
  [DBC-MAP-001] Map.dbc Directory "TelAbim" != WDT folder "TelAbimVault"
  [SQL-REF-008] creature spawn at (1500, 2000, 50) references missing template 50025
  [CROSS-001] Map ID mismatch: DBC=800, SQL=801

Warnings:
  [ADT-HM-002] 8 heightmap values exceed ±2048 yards
  [SQL-VAL-002] Quest 70001 XP (1200) low for level 53 (expected ~5500)
  [SQL-COMP-006] Quest chain broken: quest 70005 PrevQuestId=70003 not found
  ... (9 more warnings)

Fix critical issues before proceeding to in-game testing.
Run 'report.write_report("qa_report.md")' for detailed analysis.
```

---

## 6. Error Recovery Suggestions

### 6.1 Common Issues and Fixes

**Issue:** DBC-MAP-001 (Directory field mismatch)

```python
# Problem: Map.dbc Directory = "TelAbim", but WDT folder = "TelAbimVault"
# Fix: Regenerate Map.dbc with correct directory name
from world_builder.dbc_injector import register_map

register_map(
    dbc_dir='./DBFilesClient',
    map_name='TelAbimVault',  # Must match WDT folder name
    map_id=800,
)
```

**Issue:** SQL-REF-008 (Spawn references missing template)

```sql
-- Problem: creature spawn references entry 50025, but no creature_template exists
-- Fix: Add creature_template before spawning
INSERT INTO creature_template (entry, name, subname, minlevel, maxlevel, ...)
VALUES (50025, 'Tel\'Abim Pirate', '', 52, 54, ...);

-- Then add spawn
INSERT INTO creature (guid, id, map, position_x, position_y, position_z, ...)
VALUES (100001, 50025, 800, 1500.0, 2000.0, 50.0, ...);
```

**Issue:** ADT-HM-002 (Height value out of range)

```python
# Problem: Heightmap contains values > 2048 yards
# Fix: Clamp heights during generation
import numpy as np

heightmap = np.clip(heightmap, -2048.0, 2048.0)

# Or adjust source heightmap before generation
from world_builder import build_zone

result = build_zone(
    name='TelAbim',
    heightmap=np.clip(original_heightmap, -2048, 2048),
    ...
)
```

**Issue:** CROSS-001 (Map ID mismatch between DBC and SQL)

```python
# Problem: DBC Map ID = 800, SQL instance_template map = 801
# Fix: Ensure consistent map_id across all systems

# Client-side (DBC)
map_id = register_map(dbc_dir, 'TelAbim', map_id=800)

# Server-side (SQL) - use same map_id
sql_content = f"""
INSERT INTO instance_template (map, parent, script)
VALUES ({map_id}, 0, 'instance_telabim');
"""
```

### 6.2 Automated Fix Suggestions

The validator can provide automated fix suggestions:

```python
report = validator.run_full_validation()

# Get automated fix script
fix_script = report.generate_fix_script()
# Returns Python code to fix common issues

print(fix_script)
```

**Example fix script:**
```python
# Automated fixes for Tel'Abim validation errors
# Generated: 2026-02-02 14:35:12

from world_builder.dbc_injector import register_map

# Fix DBC-MAP-001: Map.dbc Directory field mismatch
register_map(
    dbc_dir='./DBFilesClient',
    map_name='TelAbimVault',  # Corrected from 'TelAbim'
    map_id=800,
    instance_type=0,
)

# Fix SQL-REF-008: Missing creature_template for spawn references
# Manual action required: Add the following SQL:
# INSERT INTO creature_template (entry, name, ...) VALUES (50025, '...', ...);

# Fix ADT-HM-002: Clamp heightmap values
# Manual action required: Regenerate ADTs with clamped heightmap
```

---

## 7. Integration with Build Pipeline

### 7.1 Automatic Validation in `build_zone()`

**File:** `world_builder/__init__.py`

```python
def build_zone(name, output_dir, coords, ..., run_qa_validation=True):
    """
    High-level API to build a complete custom zone.

    New Args:
        run_qa_validation: Run QA validation after build (default True).
                          If False, validation can be run manually.

    Returns:
        dict: {
            ...existing fields...
            'qa_report': QAReport or None,
        }
    """
    # ... existing build logic ...

    result = {
        'map_id': map_id,
        'area_id': area_id,
        'wdt_path': wdt_path,
        'adt_paths': adt_paths,
        'minimap_paths': minimap_paths,
        'output_dir': output_dir,
        'qa_report': None,
    }

    # NEW: Automatic validation
    if run_qa_validation:
        from .qa_validator import QAValidator

        validator = QAValidator(
            client_dir=output_dir,
            sql_dir=None,  # TODO: Add when SQL generator implemented
            script_dir=None,  # TODO: Add when script generator implemented
            dbc_dir=dbc_dir,
        )

        qa_report = validator.run_full_validation()
        result['qa_report'] = qa_report

        # Print summary to console
        qa_report.print_summary()

        # Write detailed report
        report_path = os.path.join(output_dir, 'qa_report.md')
        qa_report.write_report(report_path)
        print(f"\nDetailed QA report: {report_path}")

    return result
```

### 7.2 Tel'Abim Build with Validation

```python
from world_builder import build_zone

result = build_zone(
    name='TelAbim',
    output_dir='./output/TelAbim',
    coords=[(32, 32), (32, 33), (33, 32)],
    heightmap=telabim_heightmap,
    texture_paths=telabim_textures,
    dbc_dir='C:/WoW_3.3.5a/Data/DBFilesClient',
    run_qa_validation=True,  # Automatic validation
)

# Validation runs automatically
qa_report = result['qa_report']
score = qa_report.get_score()

if score < 95.0:
    print(f"⚠️ Warning: Coverage score {score}% below recommended threshold")
    print("Review qa_report.md for details")
else:
    print(f"✅ QA validation passed with {score}% coverage")
```

**Console output:**
```
Building zone 'TelAbim'...
  Phase 1: DBC injection... ✓
  Phase 2: WDT generation... ✓
  Phase 3: ADT generation... ✓ (3 tiles)
  Phase 4: Minimap generation... ✓ (3 tiles)
  Phase 5: MPQ packing... ✓

Running QA validation...
  DBC integrity... 45/45 ✓
  ADT terrain... 30/30 ✓
  WDT grid... 4/4 ✓
  BLP textures... 5/5 ✓
  MPQ archive... 4/4 ✓
  Cross-layer... 6/6 ✓

=== QA Validation Summary: TelAbim ===

Coverage Score: 100% (94/94 checks passed)

ERROR:   0 ❌
WARNING: 0 ⚠️
SKIPPED: 5 🎮

All automated checks passed! ✅

Detailed QA report: ./output/TelAbim/qa_report.md

✅ QA validation passed with 100.0% coverage
```

---

## 8. Testing Approach

### 8.1 Unit Tests

**File:** `tests/test_qa_validator.py`

```python
import unittest
import tempfile
import os
from world_builder.qa_validator import QAValidator
from world_builder.dbc_injector import DBCInjector

class TestQAValidator(unittest.TestCase):

    def test_dbc_magic_header_validation(self):
        """Test DBC magic header validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create invalid DBC (wrong magic)
            bad_dbc_path = os.path.join(tmpdir, 'Map.dbc')
            with open(bad_dbc_path, 'wb') as f:
                f.write(b'XXXX')  # Wrong magic
                f.write(struct.pack('<4I', 0, 66, 264, 1))
                f.write(b'\x00')  # String block

            validator = QAValidator(client_dir=tmpdir, dbc_dir=tmpdir)
            results = validator.validate_dbc_integrity()

            # Should fail DBC-001 check
            magic_check = next((r for r in results if r.check_id == 'DBC-001'), None)
            self.assertIsNotNone(magic_check)
            self.assertFalse(magic_check.passed)
            self.assertEqual(magic_check.severity, ValidationSeverity.ERROR)

    def test_dbc_referential_integrity(self):
        """Test cross-DBC referential integrity validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Map.dbc with ID 800
            map_dbc = DBCInjector()
            map_dbc.field_count = 66
            map_dbc.record_size = 264
            # ... create map record ...
            map_dbc.write(os.path.join(tmpdir, 'Map.dbc'))

            # Create AreaTable.dbc with ContinentID=999 (does not exist)
            area_dbc = DBCInjector()
            area_dbc.field_count = 36
            area_dbc.record_size = 144
            # ... create area record with ContinentID=999 ...
            area_dbc.write(os.path.join(tmpdir, 'AreaTable.dbc'))

            validator = QAValidator(client_dir=tmpdir, dbc_dir=tmpdir)
            results = validator.validate_dbc_integrity()

            # Should fail DBC-REF-001 check
            ref_check = next((r for r in results if r.check_id == 'DBC-REF-001'), None)
            self.assertIsNotNone(ref_check)
            self.assertFalse(ref_check.passed)

    def test_adt_version_validation(self):
        """Test ADT version chunk validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ADT with wrong version
            adt_path = os.path.join(tmpdir, 'Test_32_32.adt')
            with open(adt_path, 'wb') as f:
                f.write(b'REVM')  # MVER chunk
                f.write(struct.pack('<I', 4))  # Size
                f.write(struct.pack('<I', 19))  # Wrong version (19 instead of 18)

            validator = QAValidator(client_dir=tmpdir)
            results = validator.validate_adt_files()

            # Should fail ADT-001 check
            version_check = next((r for r in results if r.check_id == 'ADT-001'), None)
            self.assertIsNotNone(version_check)
            self.assertFalse(version_check.passed)

    def test_cross_layer_map_id_validation(self):
        """Test map ID consistency between DBC and SQL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Map.dbc with ID 800
            map_dbc = DBCInjector()
            # ... create map record with ID=800 ...
            map_dbc.write(os.path.join(tmpdir, 'Map.dbc'))

            # Create SQL with map=801 (mismatch)
            sql_dir = os.path.join(tmpdir, 'sql')
            os.makedirs(sql_dir)
            sql_file = os.path.join(sql_dir, 'instance.sql')
            with open(sql_file, 'w') as f:
                f.write("INSERT INTO instance_template (map) VALUES (801);\n")

            validator = QAValidator(
                client_dir=tmpdir,
                sql_dir=sql_dir,
                dbc_dir=tmpdir
            )
            results = validator.validate_cross_layer()

            # Should fail CROSS-001 check
            cross_check = next((r for r in results if r.check_id == 'CROSS-001'), None)
            self.assertIsNotNone(cross_check)
            self.assertFalse(cross_check.passed)

    def test_qa_report_generation(self):
        """Test QA report generation and scoring."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal valid zone
            # ... (setup minimal valid files) ...

            validator = QAValidator(client_dir=tmpdir)
            report = validator.run_full_validation()

            # Test score calculation
            score = report.get_score()
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

            # Test report writing
            report_path = os.path.join(tmpdir, 'test_report.md')
            report.write_report(report_path)
            self.assertTrue(os.path.exists(report_path))

            # Verify report contains key sections
            with open(report_path, 'r') as f:
                content = f.read()
                self.assertIn('QA Validation Report', content)
                self.assertIn('Coverage Score', content)
                self.assertIn('Executive Summary', content)
```

### 8.2 Integration Tests

**File:** `tests/test_build_zone_qa.py`

```python
def test_build_zone_with_qa_validation():
    """Test end-to-end zone build with automatic QA validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create temporary DBC directory
        dbc_dir = os.path.join(tmpdir, 'DBFilesClient')
        os.makedirs(dbc_dir)

        # Initialize empty DBCs
        for dbc_name, field_count, record_size in [
            ('Map.dbc', 66, 264),
            ('AreaTable.dbc', 36, 144),
        ]:
            dbc = DBCInjector()
            dbc.field_count = field_count
            dbc.record_size = record_size
            dbc.write(os.path.join(dbc_dir, dbc_name))

        # Build zone with QA validation
        result = build_zone(
            name='TestZone',
            output_dir=os.path.join(tmpdir, 'output'),
            coords=[(32, 32)],
            dbc_dir=dbc_dir,
            run_qa_validation=True,
        )

        # Verify QA report was generated
        self.assertIn('qa_report', result)
        self.assertIsNotNone(result['qa_report'])

        qa_report = result['qa_report']
        score = qa_report.get_score()

        # Should have high score for minimal valid zone
        self.assertGreaterEqual(score, 90.0)

        # Verify report file was created
        report_path = os.path.join(tmpdir, 'output', 'qa_report.md')
        self.assertTrue(os.path.exists(report_path))
```

### 8.3 Manual Testing Workflow

```bash
# 1. Generate Tel'Abim test zone
python -m tests.manual_generate_telabim

# 2. Run validation manually
python -m world_builder.qa_validator \
    --client-dir ./output/TelAbim/Patch-Z \
    --dbc-dir C:/WoW_3.3.5a/Data/DBFilesClient \
    --output qa_report.md

# 3. Review report
cat qa_report.md

# 4. Apply automated fixes (if available)
python -m world_builder.qa_validator \
    --client-dir ./output/TelAbim/Patch-Z \
    --generate-fix-script fixes.py

python fixes.py

# 5. Re-run validation
python -m world_builder.qa_validator \
    --client-dir ./output/TelAbim/Patch-Z \
    --dbc-dir C:/WoW_3.3.5a/Data/DBFilesClient \
    --output qa_report_fixed.md
```

---

## 9. Implementation Checklist

### Phase 1: Core Validator Framework
- [ ] Create `world_builder/qa_validator.py`
- [ ] Implement `QAValidator` class with initialization
- [ ] Implement `ValidationResult` and `ValidationSeverity` classes
- [ ] Implement `QAReport` class with scoring logic
- [ ] Add `run_full_validation()` orchestration method

### Phase 2: DBC Validation
- [ ] Create `world_builder/validators/dbc_validator.py`
- [ ] Implement binary format checks (DBC-001 to DBC-005)
- [ ] Implement Map.dbc field validation (DBC-MAP-001 to DBC-MAP-004)
- [ ] Implement AreaTable.dbc validation (DBC-AREA-001 to DBC-AREA-004)
- [ ] Implement WorldMapArea.dbc validation (DBC-WMA-001 to DBC-WMA-004)
- [ ] Implement WorldMapOverlay.dbc validation (DBC-WMO-001 to DBC-WMO-003)
- [ ] Implement LoadingScreens.dbc validation (DBC-LS-001 to DBC-LS-002)
- [ ] Implement LFGDungeons.dbc validation (DBC-LFG-001 to DBC-LFG-004)
- [ ] Implement DungeonEncounter.dbc validation (DBC-DE-001 to DBC-DE-003)
- [ ] Implement cross-DBC referential integrity (DBC-REF-001 to DBC-REF-008)

### Phase 3: ADT Validation
- [ ] Create `world_builder/validators/adt_validator.py`
- [ ] Implement chunk structure validation (ADT-001 to ADT-006)
- [ ] Implement heightmap validation (ADT-HM-001 to ADT-HM-003)
- [ ] Implement texture reference validation (ADT-TEX-001 to ADT-TEX-003)
- [ ] Implement area ID validation (ADT-AREA-001 to ADT-AREA-002)
- [ ] Implement doodad/WMO reference validation (ADT-DOOD-001 to ADT-DOOD-003)

### Phase 4: WDT, BLP, MPQ Validation
- [ ] Create `world_builder/validators/wdt_validator.py`
- [ ] Implement WDT validation (WDT-001 to WDT-004)
- [ ] Create `world_builder/validators/blp_validator.py`
- [ ] Implement BLP validation (BLP-001 to BLP-005)
- [ ] Create `world_builder/validators/mpq_validator.py`
- [ ] Implement MPQ validation (MPQ-001 to MPQ-004)

### Phase 5: SQL Validation (When SQL Generator Implemented)
- [ ] Create `world_builder/validators/sql_validator.py`
- [ ] Implement SQL syntax validation (SQL-001 to SQL-002)
- [ ] Implement referential integrity (SQL-REF-001 to SQL-REF-010)
- [ ] Implement completeness checks (SQL-COMP-001 to SQL-COMP-010)
- [ ] Implement value range validation (SQL-VAL-001 to SQL-VAL-005)

### Phase 6: Script Validation (When Script Generator Implemented)
- [ ] Create `world_builder/validators/script_validator.py`
- [ ] Implement Lua syntax validation (SCRIPT-001 to SCRIPT-003)
- [ ] Implement logic checks (SCRIPT-LOG-001 to SCRIPT-LOG-005)

### Phase 7: Cross-Layer Validation
- [ ] Create `world_builder/validators/cross_validator.py`
- [ ] Implement client ↔ server consistency (CROSS-001 to CROSS-006)

### Phase 8: Report Generation
- [ ] Create `world_builder/qa_report.py`
- [ ] Implement `QAReport.get_score()` scoring logic
- [ ] Implement `QAReport.print_summary()` console output
- [ ] Implement `QAReport.write_report()` Markdown generation
- [ ] Add report templates and formatting

### Phase 9: Build Pipeline Integration
- [ ] Update `world_builder/__init__.py` with `run_qa_validation` parameter
- [ ] Add automatic validation after `build_zone()` completes
- [ ] Generate and save qa_report.md to output directory
- [ ] Add qa_report to return dict

### Phase 10: Testing
- [ ] Write unit tests for DBC validation
- [ ] Write unit tests for ADT validation
- [ ] Write unit tests for cross-layer validation
- [ ] Write integration test for `build_zone()` with QA
- [ ] Create manual testing workflow documentation
- [ ] Test with Tel'Abim example zone

### Phase 11: Documentation
- [ ] Add docstrings to all validator classes and methods
- [ ] Update world_builder README with QA validator usage
- [ ] Add Tel'Abim QA example to documentation
- [ ] Document all check IDs and fix suggestions
- [ ] Create troubleshooting guide for common issues

### Phase 12: Error Recovery
- [ ] Implement `generate_fix_script()` for automated fixes
- [ ] Add fix suggestions to all validation checks
- [ ] Document manual fix procedures for complex issues

---

## 10. Known Limitations

### 10.1 Validation Scope

**Cannot validate:**
- Visual quality of textures/models
- Subjective gameplay experience
- Runtime performance characteristics
- Audio quality and transitions
- Balance tuning (difficulty, rewards)

**Mitigation:** Explicitly mark these as SKIP with notes directing to in-game testing phase.

### 10.2 SQL/Script Validation Dependencies

**Current limitation:** SQL and script generators are not yet implemented in pywowlib.

**Mitigation:**
- Design validator API to accept optional `sql_dir` and `script_dir` parameters
- Gracefully skip SQL/script validation if directories are None
- Document future integration points when generators are ready

### 10.3 External DBC References

**Limitation:** Cannot validate references to Blizzard's base DBC data without access to full client DBCs.

**Mitigation:**
- Require `dbc_dir` parameter pointing to WoW client DBFilesClient directory
- Skip FK checks if source DBC not available
- Document which checks require client data access

### 10.4 Performance for Large Zones

**Limitation:** Validation may be slow for zones with 64+ ADT tiles or 1000+ SQL entries.

**Mitigation:**
- Implement parallel validation where possible (multiprocessing)
- Add progress indicators for long-running checks
- Allow selective validation (e.g., only DBC, skip ADT)

---

## 11. Future Enhancements

### 11.1 Incremental Validation

Only re-validate changed files instead of full zone:

```python
validator = QAValidator(client_dir='./output')
report = validator.run_incremental_validation(
    changed_files=['Map.dbc', 'TelAbim_32_32.adt']
)
```

### 11.2 Continuous Integration Support

Export validation results in CI-friendly formats:

```python
report.export_junit_xml('qa_results.xml')  # For Jenkins/GitLab CI
report.export_json('qa_results.json')      # For custom CI tools
```

### 11.3 Visual Diff Reports

Generate visual diffs for geometry changes:

```python
report.generate_heightmap_diff(
    before='./old_zone/TelAbim_32_32.adt',
    after='./new_zone/TelAbim_32_32.adt',
    output='heightmap_diff.png'
)
```

### 11.4 SQL Query Validation

Test SQL queries against actual database schema:

```python
validator = QAValidator(
    sql_dir='./output/sql',
    test_db_connection='mysql://localhost:3306/world_test'
)
report = validator.validate_sql_queries()
```

### 11.5 In-Game Smoke Tests

Automate basic in-game checks via WoW client API:

```python
# Requires headless WoW client setup (advanced)
validator.run_ingame_smoke_tests(
    wow_client_path='C:/WoW_3.3.5a/Wow.exe',
    test_account='test@test.com',
    test_character='TestChar',
    checks=['zone_load', 'minimap_display', 'npc_spawn']
)
```

---

## 12. Success Criteria

This QA validator implementation is considered successful when:

1. **Coverage:** Validates all client-side assets (DBC, ADT, WDT, BLP, MPQ)
2. **Accuracy:** Detects 95%+ of common generation errors before in-game testing
3. **Speed:** Completes validation in <5 seconds for 9-tile zones
4. **Usability:** Provides clear, actionable error messages with fix suggestions
5. **Integration:** Seamlessly integrates into `build_zone()` pipeline
6. **Documentation:** Comprehensive docs with Tel'Abim examples
7. **Testing:** Passes all unit and integration tests

---

## 13. References

### 13.1 WoW Technical Documentation

- **WoWDev Wiki:** https://wowdev.wiki/ (archived)
- **WoW.tools DBC browser:** https://wow.tools/dbc/
- **TrinityCore SQL schema:** https://github.com/TrinityCore/TrinityCore/tree/3.3.5/sql

### 13.2 pywowlib Modules

- `world_builder/dbc_injector.py` - DBC read/write logic
- `world_builder/adt_composer.py` - ADT generation logic
- `world_builder/wdt_generator.py` - WDT generation logic
- `world_builder/mpq_packer.py` - MPQ archive packing

### 13.3 Existing Plans

- `plans/ROADMAP.md` - Overall world_builder implementation roadmap
- `plans/plan-dbc-zone-display.md` - WorldMapArea/WorldMapOverlay/LoadingScreens DBCs
- `plans/plan-dbc-dungeon.md` - LFGDungeons/DungeonEncounter DBCs
- `plans/plan-minimap-generator.md` - Minimap tile generation

---

## End of Plan

This plan provides a comprehensive roadmap for implementing an automated QA validation suite that maximizes automation coverage for WoW 3.3.5a zone generation, enabling TODO 5.1 (End-to-End QA Test) to be as automated as possible while clearly documenting what must remain manual in-game testing.
