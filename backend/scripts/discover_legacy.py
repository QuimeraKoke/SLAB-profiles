"""Read-only discovery against the legacy uchile1 Postgres database.

Connects with `default_transaction_read_only=on` so even if a buggy
query somehow contained DDL/DML, the DB would reject it.

Dumps a Markdown report to `/tmp/legacy_discovery.md` with:
  - server version
  - per-table: column metadata, row count, 5-row sample
  - foreign-key map
  - a first-pass mapping guess to SLAB entities

Usage (from inside the backend container):
    LEGACY_DB_PASSWORD='...' python scripts/discover_legacy.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

# --- Config ---------------------------------------------------------------

LEGACY_HOST = "192.168.1.24"
LEGACY_PORT = 5432
LEGACY_DB = "uchile1"
LEGACY_USER = "slab_migration_ro"
LEGACY_SCHEMA = "public"
SAMPLE_ROWS = 5
OUT_FILE = pathlib.Path("/tmp/legacy_discovery.md")


# --- SLAB-side hints ------------------------------------------------------
# First-pass keyword → SLAB entity. Used only to suggest a mapping; the
# real mapping needs human confirmation.
_KEYWORD_TO_SLAB: list[tuple[str, str]] = [
    ("jugador", "core.Player"),
    ("player", "core.Player"),
    ("posicion", "core.Position"),
    ("position", "core.Position"),
    ("categor", "core.Category"),
    ("club", "core.Club"),
    ("equipo", "core.Category / core.Club"),
    ("departamento", "core.Department"),
    ("lesion", "exams.Episode (template_slug=lesiones)"),
    ("injur", "exams.Episode (template_slug=lesiones)"),
    ("episodi", "exams.Episode"),
    ("examen", "exams.ExamTemplate / ExamResult"),
    ("exam", "exams.ExamTemplate / ExamResult"),
    ("evaluacion", "exams.ExamResult"),
    ("medicion", "exams.ExamResult"),
    ("test", "exams.ExamResult"),
    ("medicac", "exams.ExamResult (template_slug=medicacion)"),
    ("contrato", "core.Contract"),
    ("contract", "core.Contract"),
    ("partido", "events.Event (kind=match)"),
    ("match", "events.Event (kind=match)"),
    ("evento", "events.Event"),
    ("event", "events.Event"),
    ("alerta", "goals.Alert / AlertRule"),
    ("alert", "goals.Alert / AlertRule"),
    ("usuario", "auth.User / core.StaffMembership"),
    ("user", "auth.User / core.StaffMembership"),
    ("staff", "core.StaffMembership"),
    ("archivo", "exams.Attachment"),
    ("attach", "exams.Attachment"),
    ("file", "exams.Attachment"),
]


def _guess_slab_target(table_name: str) -> str:
    name = table_name.lower()
    hits: list[str] = []
    for needle, target in _KEYWORD_TO_SLAB:
        if needle in name:
            hits.append(target)
    if not hits:
        return "(unknown — needs human mapping)"
    # Dedup but keep order
    return " · ".join(dict.fromkeys(hits))


# --- Helpers --------------------------------------------------------------


def _redact_value(col_name: str, value: Any) -> Any:
    """Hide values that look sensitive even in a sample dump."""
    if value is None:
        return None
    lc = col_name.lower()
    if any(s in lc for s in ("password", "passwd", "hash", "token", "secret", "salt")):
        return "<redacted>"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary {len(bytes(value))} bytes>"
    return value


def _md_table(rows: list[list[str]]) -> str:
    """Render a markdown table; first row is the header."""
    if not rows:
        return ""
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(rows[0]))) + " |"
    out = [line(rows[0]), sep] + [line(r) for r in rows[1:]]
    return "\n".join(out)


# --- Discovery passes -----------------------------------------------------


def run() -> None:
    pwd = os.environ.get("LEGACY_DB_PASSWORD")
    if not pwd:
        sys.exit("LEGACY_DB_PASSWORD env var not set")

    dsn = (
        f"host={LEGACY_HOST} port={LEGACY_PORT} dbname={LEGACY_DB} "
        f"user={LEGACY_USER} password={pwd}"
    )
    # `default_transaction_read_only` ensures the DB rejects any write.
    out_lines: list[str] = []

    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
        cur = conn.cursor()

        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SELECT current_database(), current_user, current_schema()")
        dbname, user, schema = cur.fetchone()
        cur.execute("SELECT pg_database_size(current_database())")
        db_size = cur.fetchone()[0]
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]

        out_lines += [
            "# Legacy DB discovery — `uchile1`",
            "",
            f"_Generated {now.isoformat()} · server `{version}`_",
            "",
            f"- Database: `{dbname}` · current user: `{user}` · schema: `{schema}`",
            f"- Approx. size on disk: {db_size:,} bytes (~{db_size / 1024 / 1024:.1f} MiB)",
            "",
            "## Read-only guarantee",
            "",
            "Connection opened with `default_transaction_read_only=on`. All",
            "queries issued by this script are `SELECT`. No INSERT / UPDATE /",
            "DELETE / DDL was attempted at any point.",
            "",
        ]

        # --- Inventory: tables + row counts -------------------------------
        cur.execute(
            """
            SELECT c.relname AS table_name,
                   c.reltuples::bigint AS approx_rows,
                   pg_total_relation_size(c.oid) AS bytes
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %s
               AND c.relkind = 'r'
             ORDER BY c.relname
            """,
            (LEGACY_SCHEMA,),
        )
        tables_meta = cur.fetchall()

        out_lines.append(f"## Table inventory ({len(tables_meta)} tables)")
        out_lines.append("")
        rows = [["Table", "Approx. rows", "Size", "First-pass SLAB target"]]
        for tname, approx_rows, size in tables_meta:
            rows.append([
                f"`{tname}`",
                f"{approx_rows:,}",
                f"{size / 1024:.0f} KiB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MiB",
                _guess_slab_target(tname),
            ])
        out_lines.append(_md_table(rows))
        out_lines.append("")

        # --- Per-table detail ---------------------------------------------
        out_lines.append("## Per-table detail")
        out_lines.append("")
        for tname, approx_rows, _size in tables_meta:
            out_lines.append(f"### `{tname}` _(≈{approx_rows:,} rows)_")
            out_lines.append("")

            # Exact row count for small/medium tables; use the approx for big.
            exact_count = None
            if approx_rows < 100_000:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{LEGACY_SCHEMA}"."{tname}"')
                    exact_count = cur.fetchone()[0]
                except Exception as exc:
                    out_lines.append(f"_count error: {exc}_")
            out_lines.append(
                f"- Exact row count: {exact_count:,}" if exact_count is not None
                else f"- Skipped exact count (>100k rows, est. {approx_rows:,})",
            )

            # Columns
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                  FROM information_schema.columns
                 WHERE table_schema = %s AND table_name = %s
                 ORDER BY ordinal_position
                """,
                (LEGACY_SCHEMA, tname),
            )
            col_rows = [["#", "Column", "Type", "Nullable", "Default"]]
            for i, (cname, ctype, nullable, default) in enumerate(cur.fetchall(), 1):
                col_rows.append([
                    str(i), f"`{cname}`", ctype, nullable,
                    (default[:40] + "…") if default and len(default) > 40 else (default or ""),
                ])
            out_lines.append("")
            out_lines.append(_md_table(col_rows))
            out_lines.append("")

            # Primary key + foreign keys
            cur.execute(
                """
                SELECT a.attname
                  FROM pg_index i
                  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                 WHERE i.indrelid = (
                       SELECT c.oid FROM pg_class c
                         JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = %s AND c.relname = %s
                       )
                   AND i.indisprimary
                """,
                (LEGACY_SCHEMA, tname),
            )
            pk = [r[0] for r in cur.fetchall()]
            cur.execute(
                """
                SELECT
                    kcu.column_name,
                    ccu.table_name  AS references_table,
                    ccu.column_name AS references_column
                  FROM information_schema.table_constraints tc
                  JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                   AND tc.table_schema = kcu.table_schema
                  JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                   AND ccu.table_schema = tc.table_schema
                 WHERE tc.constraint_type = 'FOREIGN KEY'
                   AND tc.table_schema = %s
                   AND tc.table_name = %s
                """,
                (LEGACY_SCHEMA, tname),
            )
            fks = cur.fetchall()
            out_lines.append(f"- Primary key: {', '.join(f'`{c}`' for c in pk) or '_(none)_'}")
            if fks:
                out_lines.append("- Foreign keys:")
                for col, ref_t, ref_c in fks:
                    out_lines.append(f"  - `{col}` → `{ref_t}.{ref_c}`")
            else:
                out_lines.append("- Foreign keys: _(none declared)_")
            out_lines.append("")

            # Sample rows
            try:
                cur.execute(f'SELECT * FROM "{LEGACY_SCHEMA}"."{tname}" LIMIT %s', (SAMPLE_ROWS,))
                col_names = [d.name for d in cur.description]
                samples = cur.fetchall()
            except Exception as exc:
                out_lines.append(f"_sample error: {exc}_")
                out_lines.append("")
                continue

            if not samples:
                out_lines.append("_empty table_")
                out_lines.append("")
                continue

            out_lines.append(f"<details><summary>Sample rows ({len(samples)})</summary>")
            out_lines.append("")
            out_lines.append("```json")
            for row in samples:
                out_lines.append(json.dumps({
                    col_names[i]: _redact_value(col_names[i], v)
                    for i, v in enumerate(row)
                }, ensure_ascii=False, default=str)[:1200])
            out_lines.append("```")
            out_lines.append("")
            out_lines.append("</details>")
            out_lines.append("")

    OUT_FILE.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {OUT_FILE} ({OUT_FILE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    run()
