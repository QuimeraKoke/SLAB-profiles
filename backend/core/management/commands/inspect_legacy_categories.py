"""Discovery helper for phase 1 category assignment.

Walks the legacy chain `citaciones → partido → competicion_temporada
→ competicion` to surface (a) the distinct competición names in scope
and (b) how many active players each one would claim if used as the
categorisation signal. The output drives the `COMPETICION_TO_CATEGORY`
map that phase 1 will use to set `Player.category` correctly.

Read-only — touches the legacy DB only, never SLAB.

Examples:

    LEGACY_DB_PASSWORD='...' python manage.py inspect_legacy_categories
    LEGACY_DB_PASSWORD='...' python manage.py inspect_legacy_categories \\
        --date-from 2025-01-01 --date-to 2026-12-31
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from core.legacy_migration.connection import (
    DEFAULT_DB, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USER, LegacyDB,
)


_SCHEMA_QUERY = """
    SELECT table_name, column_name, data_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name IN ('categoria', 'competicion', 'competicion_temporada')
     ORDER BY table_name, ordinal_position
"""

_DOMINANT_COMP_QUERY = """
    WITH cit_in_scope AS (
        SELECT c.jugador_id, p.competicion_temporada_id
          FROM citaciones c
          JOIN partido p ON p.id_partido = c.partido_id
         WHERE p.fecha_partido >= %s AND p.fecha_partido <= %s
           AND c.jugador_id IS NOT NULL
           AND p.competicion_temporada_id IS NOT NULL
    ),
    comp_per_player AS (
        SELECT
            cs.jugador_id,
            COALESCE(comp.nombre, '(unknown)')  AS competicion_nombre,
            COALESCE(temp.nombre, '(no-temp)')  AS temporada_nombre,
            COUNT(*) AS citation_count
          FROM cit_in_scope cs
          JOIN competicion_temporada ct ON ct.id_competicion_temporada = cs.competicion_temporada_id
          LEFT JOIN competicion comp ON comp.id_competicion = ct.competicion_id
          LEFT JOIN temporada   temp ON temp.id_temporada   = ct.temporada_id
         GROUP BY cs.jugador_id, comp.nombre, temp.nombre
    ),
    ranked AS (
        SELECT
            jugador_id, competicion_nombre, temporada_nombre, citation_count,
            ROW_NUMBER() OVER (
                PARTITION BY jugador_id
                ORDER BY citation_count DESC, competicion_nombre ASC
            ) AS rn
          FROM comp_per_player
    )
    SELECT competicion_nombre, temporada_nombre,
           COUNT(*) AS player_count,
           SUM(citation_count) AS total_citations
      FROM ranked
     WHERE rn = 1
     GROUP BY competicion_nombre, temporada_nombre
     ORDER BY player_count DESC, total_citations DESC
"""

# How competicion → categoria connects. The user said this is explicit
# in the schema; we'll auto-detect the column on competicion.
_COMP_TO_CAT_PROBE_COLS = ("categoria_id", "id_categoria", "categoria")

_ALL_COMP_NAMES_QUERY = """
    SELECT DISTINCT
           COALESCE(comp.nombre, '(unknown)') AS competicion_nombre
      FROM competicion_temporada ct
      LEFT JOIN competicion comp ON comp.id_competicion = ct.competicion_id
     ORDER BY 1
"""

_PLAYERS_WITHOUT_CITACIONES_QUERY = """
    WITH active_in_scope AS (
        -- Same active-set logic as phase 1.
        SELECT DISTINCT jugador_id FROM (
            SELECT jugador_id FROM antropometria
             WHERE fecha_evaluacion BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM lesion
             WHERE fecha_lesion BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM hoja_diaria
             WHERE fecha BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM wellness
             WHERE marca_temporal BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM medicamentos
             WHERE fecha BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM examenes
             WHERE fecha_examen BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM fase_densidad
             WHERE fecha_evaluacion BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT jugador_id FROM gps_partido
             WHERE fecha BETWEEN %s AND %s AND jugador_id IS NOT NULL
            UNION SELECT c.jugador_id FROM citaciones c
              JOIN partido p ON p.id_partido = c.partido_id
             WHERE p.fecha_partido BETWEEN %s AND %s
        ) t
    )
    SELECT COUNT(*) AS n FROM active_in_scope a
     WHERE NOT EXISTS (
         SELECT 1 FROM citaciones c
           JOIN partido p ON p.id_partido = c.partido_id
          WHERE c.jugador_id = a.jugador_id
            AND p.fecha_partido BETWEEN %s AND %s
     )
"""


class Command(BaseCommand):
    help = (
        "Surface the competición → player-count distribution for the "
        "active set in scope. Use the output to build the "
        "COMPETICION_TO_CATEGORY map for phase 1."
    )

    def add_arguments(self, parser):
        parser.add_argument("--date-from", default="2025-01-01")
        parser.add_argument("--date-to", default="2026-12-31")
        parser.add_argument("--legacy-host", default=DEFAULT_HOST)
        parser.add_argument("--legacy-port", type=int, default=DEFAULT_PORT)
        parser.add_argument("--legacy-db", default=DEFAULT_DB)
        parser.add_argument("--legacy-user", default=DEFAULT_USER)

    def handle(self, *args, **opts):
        try:
            df = _parse_date(opts["date_from"])
            dt = _parse_date(opts["date_to"])
        except ValueError as exc:
            raise CommandError(f"--date-from/--date-to: {exc}")

        with LegacyDB(
            host=opts["legacy_host"],
            port=opts["legacy_port"],
            dbname=opts["legacy_db"],
            user=opts["legacy_user"],
        ) as db:
            # ---- 0) Schema for the 3 reference tables --------------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "Schema for categoria / competicion / competicion_temporada:"
            ))
            cols_by_table: dict[str, list[tuple[str, str]]] = {}
            for r in db.iter_rows(_SCHEMA_QUERY):
                cols_by_table.setdefault(r["table_name"], []).append(
                    (r["column_name"], r["data_type"])
                )
            for table, cols in cols_by_table.items():
                self.stdout.write(f"  [{table}]")
                for col, dtype in cols:
                    self.stdout.write(f"    · {col:30s} {dtype}")

            # Detect which competicion column points at categoria.
            comp_cols = {c for c, _ in cols_by_table.get("competicion", [])}
            cat_cols = {c for c, _ in cols_by_table.get("categoria", [])}
            ct_cols = {c for c, _ in cols_by_table.get("competicion_temporada", [])}

            link_path = None
            if "categoria_id" in comp_cols:
                link_path = ("competicion", "categoria_id")
            elif "id_categoria" in comp_cols:
                link_path = ("competicion", "id_categoria")
            elif "competicion_id" in cat_cols or "id_competicion" in cat_cols:
                link_path = ("categoria", "competicion_id"
                             if "competicion_id" in cat_cols else "id_competicion")
            elif "categoria_id" in ct_cols:
                link_path = ("competicion_temporada", "categoria_id")

            self.stdout.write("")
            if link_path:
                self.stdout.write(self.style.SUCCESS(
                    f"Detected competición↔categoría link: "
                    f"{link_path[0]}.{link_path[1]}"
                ))
                self._show_categoria_distribution(db, link_path, df, dt)
            else:
                self.stdout.write(self.style.WARNING(
                    "Could not auto-detect the competición↔categoría FK. "
                    "Above schema dump should show the right column — paste it "
                    "back so I can wire phase 1."
                ))

            # ---- 1) Every competición name in the legacy DB --------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("All competición names in legacy:"))
            for r in db.iter_rows(_ALL_COMP_NAMES_QUERY):
                self.stdout.write(f"  · {r['competicion_nombre']}")

            # ---- 2) Dominant competición per active player ---------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                f"Dominant competición per active player ({df} → {dt}):"
            ))
            self.stdout.write(
                f"  {'competicion':45s} {'temporada':20s} {'players':>9s} {'citas':>8s}"
            )
            self.stdout.write("  " + "-" * 85)
            total_players = 0
            for r in db.iter_rows(_DOMINANT_COMP_QUERY, (df, dt)):
                comp = (r["competicion_nombre"] or "")[:43]
                temp = (r["temporada_nombre"] or "")[:18]
                pc = r["player_count"]
                tc = r["total_citations"]
                total_players += pc
                self.stdout.write(f"  {comp:45s} {temp:20s} {pc:>9,} {tc:>8,}")
            self.stdout.write("  " + "-" * 85)
            self.stdout.write(f"  {'TOTAL':45s} {'':20s} {total_players:>9,}")

            # ---- 3) Active players with no citaciones at all -------
            window = (df, dt) * 10
            r = db.fetch_one(_PLAYERS_WITHOUT_CITACIONES_QUERY, window)
            uncovered = r["n"] if r else 0
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                f"Active players with NO citaciones in scope: {uncovered}"
            ))
            self.stdout.write(
                "  (These need a fallback category — phase 1 currently sends "
                "them all to 'Primer Equipo'.)"
            )
            self.stdout.write("")


    # ------------------------------------------------------------------
    def _show_categoria_distribution(self, db, link_path, df, dt) -> None:
        """Run the full chain citaciones→partido→ct→competicion→categoria
        and report how many active players fall into each categoria
        when we pick the dominant one per player. Output drives phase 1."""
        table, col = link_path

        # Build the join based on where the FK actually lives.
        if table == "competicion":
            join_clause = (
                "JOIN competicion_temporada ct ON ct.id_competicion_temporada = p.competicion_temporada_id "
                "JOIN competicion comp ON comp.id_competicion = ct.competicion_id "
                f"JOIN categoria cat ON cat.id_categoria = comp.{col} "
            )
        elif table == "competicion_temporada":
            join_clause = (
                "JOIN competicion_temporada ct ON ct.id_competicion_temporada = p.competicion_temporada_id "
                f"JOIN categoria cat ON cat.id_categoria = ct.{col} "
            )
        elif table == "categoria":
            join_clause = (
                "JOIN competicion_temporada ct ON ct.id_competicion_temporada = p.competicion_temporada_id "
                "JOIN competicion comp ON comp.id_competicion = ct.competicion_id "
                f"JOIN categoria cat ON cat.{col} = comp.id_competicion "
            )
        else:
            self.stdout.write(self.style.WARNING(
                f"Don't know how to join through {table}.{col} — skipping."
            ))
            return

        sql = f"""
            WITH cit_in_scope AS (
                SELECT c.jugador_id, cat.id_categoria, cat.nombre AS cat_nombre
                  FROM citaciones c
                  JOIN partido p ON p.id_partido = c.partido_id
                  {join_clause}
                 WHERE p.fecha_partido BETWEEN %s AND %s
                   AND c.jugador_id IS NOT NULL
            ),
            per_player AS (
                SELECT jugador_id, id_categoria, cat_nombre,
                       COUNT(*) AS n,
                       ROW_NUMBER() OVER (
                         PARTITION BY jugador_id
                         ORDER BY COUNT(*) DESC, cat_nombre ASC
                       ) AS rn
                  FROM cit_in_scope
                 GROUP BY jugador_id, id_categoria, cat_nombre
            )
            SELECT id_categoria, cat_nombre,
                   COUNT(*) AS player_count,
                   SUM(n)   AS total_citations
              FROM per_player
             WHERE rn = 1
             GROUP BY id_categoria, cat_nombre
             ORDER BY player_count DESC
        """
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(
            f"Dominant categoría per active player ({df} → {dt}):"
        ))
        self.stdout.write(
            f"  {'id':>4s}  {'categoría':40s} {'players':>9s} {'citas':>8s}"
        )
        self.stdout.write("  " + "-" * 70)
        total = 0
        try:
            for r in db.iter_rows(sql, (df, dt)):
                name = (r["cat_nombre"] or "")[:38]
                pc = r["player_count"]
                tc = r["total_citations"]
                total += pc
                self.stdout.write(
                    f"  {r['id_categoria']:>4d}  {name:40s} {pc:>9,} {tc:>8,}"
                )
            self.stdout.write("  " + "-" * 70)
            self.stdout.write(f"  {'':4s}  {'TOTAL':40s} {total:>9,}")
        except Exception as exc:   # noqa: BLE001
            self.stdout.write(self.style.WARNING(
                f"Chain query failed ({type(exc).__name__}: {exc}). "
                "The detected link path may be wrong — paste the schema "
                "above and I'll wire it manually."
            ))


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()
