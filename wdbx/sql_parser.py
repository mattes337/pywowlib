"""Mysqldump SQL parser for AzerothCore world database files.

Parses CREATE TABLE and INSERT INTO VALUES statements from mysqldump output.
Maps MySQL types to SQLite types. Streams INSERT rows for memory efficiency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator


# ---------------------------------------------------------------------------
# MySQL → SQLite type mapping
# ---------------------------------------------------------------------------
_TYPE_MAP = {
    "int": "INTEGER",
    "tinyint": "INTEGER",
    "smallint": "INTEGER",
    "mediumint": "INTEGER",
    "bigint": "INTEGER",
    "float": "REAL",
    "double": "REAL",
    "decimal": "REAL",
    "char": "TEXT",
    "varchar": "TEXT",
    "text": "TEXT",
    "tinytext": "TEXT",
    "mediumtext": "TEXT",
    "longtext": "TEXT",
    "enum": "TEXT",
    "set": "TEXT",
    "blob": "BLOB",
    "tinyblob": "BLOB",
    "mediumblob": "BLOB",
    "longblob": "BLOB",
}

# Regex for column definition line:
#   `column_name` type[(size)] [unsigned] [NOT NULL] [DEFAULT ...] [COMMENT ...]
_COL_RE = re.compile(
    r'^\s*`(\w+)`\s+'           # column name
    r'(\w+)'                    # base type (int, varchar, etc.)
    r'(?:\([^)]*\))?'           # optional size/values
    r'(.*)',                     # rest of line
    re.IGNORECASE,
)

# Regex for PRIMARY KEY line
_PK_RE = re.compile(
    r'PRIMARY\s+KEY\s*\(([^)]+)\)',
    re.IGNORECASE,
)


@dataclass
class ColumnDef:
    """Single column definition."""
    name: str
    mysql_type: str
    sqlite_type: str
    nullable: bool = True


@dataclass
class TableSchema:
    """Parsed CREATE TABLE result."""
    table_name: str
    columns: list[ColumnDef] = field(default_factory=list)
    pk_columns: list[str] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def parse_create_table(path: str) -> TableSchema | None:
    """Parse CREATE TABLE from a mysqldump SQL file.

    Returns TableSchema or None if no CREATE TABLE found.
    """
    in_create = False
    create_lines: list[str] = []
    table_name = ""

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not in_create:
                m = re.match(r'CREATE\s+TABLE\s+`(\w+)`', line, re.IGNORECASE)
                if m:
                    table_name = m.group(1)
                    in_create = True
                    create_lines = [line]
                continue
            create_lines.append(line)
            # End of CREATE TABLE
            if line.rstrip().rstrip(";").endswith(")") or re.match(r'\)\s*(ENGINE|;)', line):
                break

    if not table_name:
        return None

    schema = TableSchema(table_name=table_name)
    pk_cols: list[str] = []

    for cline in create_lines:
        cline = cline.strip().rstrip(",")

        # Check for PRIMARY KEY
        pk_match = _PK_RE.search(cline)
        if pk_match:
            pk_cols = [c.strip().strip("`") for c in pk_match.group(1).split(",")]
            continue

        # Skip non-column lines
        col_match = _COL_RE.match(cline)
        if not col_match:
            continue

        col_name = col_match.group(1)
        mysql_type = col_match.group(2).lower()
        rest = col_match.group(3)

        sqlite_type = _TYPE_MAP.get(mysql_type, "TEXT")
        nullable = "NOT NULL" not in rest.upper()

        schema.columns.append(ColumnDef(
            name=col_name,
            mysql_type=mysql_type,
            sqlite_type=sqlite_type,
            nullable=nullable,
        ))

    schema.pk_columns = pk_cols or ([schema.columns[0].name] if schema.columns else [])
    return schema


def parse_insert_rows(path: str, schema: TableSchema) -> Iterator[tuple]:
    """Stream-parse INSERT INTO VALUES rows from a mysqldump file.

    Handles:
    - Multi-line INSERT blocks: INSERT INTO `t` VALUES (v,...),(v,...);
    - Escaped quotes: \\' and \\\\ inside strings
    - NULL literals, numeric literals, empty strings
    - Multiple INSERT statements per file

    Yields tuples matching schema column order.
    """
    col_count = len(schema.columns)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("INSERT INTO") and not line.startswith("("):
                continue

            # For INSERT INTO lines, skip the preamble
            if line.startswith("INSERT INTO"):
                # Find the VALUES keyword
                idx = line.find("VALUES")
                if idx < 0:
                    idx = line.find("values")
                if idx < 0:
                    continue
                line = line[idx + 6:].lstrip()
                if not line or line == "\n":
                    continue

            # Now parse row tuples from this line
            yield from _parse_rows_from_text(line, col_count)


def _parse_rows_from_text(text: str, col_count: int) -> Iterator[tuple]:
    """Parse (val,val,...),(val,val,...) from a text chunk."""
    pos = 0
    length = len(text)

    while pos < length:
        # Find opening paren
        while pos < length and text[pos] != "(":
            pos += 1
        if pos >= length:
            break
        pos += 1  # skip (

        values: list = []
        while pos < length:
            c = text[pos]

            if c == ")":
                pos += 1
                break

            if c == ",":
                pos += 1
                continue

            if c == "'":
                # String value — scan to closing unescaped quote
                pos += 1
                parts: list[str] = []
                while pos < length:
                    c2 = text[pos]
                    if c2 == "\\":
                        if pos + 1 < length:
                            nc = text[pos + 1]
                            if nc == "'":
                                parts.append("'")
                            elif nc == "\\":
                                parts.append("\\")
                            elif nc == "n":
                                parts.append("\n")
                            elif nc == "r":
                                parts.append("\r")
                            elif nc == "t":
                                parts.append("\t")
                            elif nc == "0":
                                parts.append("\0")
                            else:
                                parts.append(nc)
                            pos += 2
                        else:
                            pos += 1
                        continue
                    if c2 == "'":
                        pos += 1
                        break
                    parts.append(c2)
                    pos += 1
                values.append("".join(parts))

            elif c == "N" and text[pos:pos+4] == "NULL":
                values.append(None)
                pos += 4

            elif c in "-0123456789.":
                # Numeric value
                start = pos
                pos += 1
                while pos < length and text[pos] in "0123456789.eE+-":
                    pos += 1
                num_str = text[start:pos]
                if "." in num_str or "e" in num_str.lower():
                    values.append(float(num_str))
                else:
                    values.append(int(num_str))

            else:
                pos += 1
                continue

        if len(values) == col_count:
            yield tuple(values)
