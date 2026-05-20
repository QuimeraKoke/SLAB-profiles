"""Diagnose why the women's team isn't landing in a Femenino category.

Read-only. Inspects the legacy DB and surfaces:

  1. Every categoría row with its `genero` value (so we can see which
     ids represent women's teams).
  2. Every competición row with its `genero` + `categoria_id` (so we
     can confirm Femenino competitions resolve to a Femenino categoría).
  3. Citación counts per competición (in scope) — does any female
     competition have partidos in 2025+?
  4. For each "no-citacion" active player, which legacy tables DO
     have rows for them (wellness / antropometria / etc.) — those
     are the women being missed by the dominant-cat lookup.

The output drives whichever signal we use as the fallback for the
69 uncovered players.
"""
from __future__ import annotations

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from core.legacy_migration.connection import (
    DEFAULT_DB, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USER, LegacyDB,
)


class Command(BaseCommand):
    help = "Diagnose why women's team players aren't being categorised."

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
            raise CommandError(str(exc))

        with LegacyDB(
            host=opts["legacy_host"],
            port=opts["legacy_port"],
            dbname=opts["legacy_db"],
            user=opts["legacy_user"],
        ) as db:
            # ---- 0) Probe for any non-citation jugador↔categoria signal
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "Probe — columns on `jugador` that might directly link to a team:"
            ))
            jugador_col_terms = (
                "%categoria%", "%equipo%", "%team%",
                "%genero%", "%sexo%", "%plantel%",
            )
            for r in db.iter_rows(
                "SELECT column_name, data_type FROM information_schema.columns "
                " WHERE table_schema='public' AND table_name='jugador' "
                "   AND (column_name ILIKE ANY(%s)) "
                " ORDER BY ordinal_position",
                (list(jugador_col_terms),),
            ):
                self.stdout.write(f"  · jugador.{r['column_name']:30s} {r['data_type']}")

            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "Probe — other tables that might hold jugador→categoria assignments:"
            ))
            table_terms = (
                "%jugador%", "%inscripcion%", "%plantel%",
                "%equipo_%", "%nomina%",
            )
            for r in db.iter_rows(
                "SELECT table_name FROM information_schema.tables "
                " WHERE table_schema='public' "
                "   AND (table_name ILIKE ANY(%s)) "
                " ORDER BY table_name",
                (list(table_terms),),
            ):
                # Also dump the columns of each one — cheap, useful intel.
                self.stdout.write(f"  [{r['table_name']}]")
                for c in db.iter_rows(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    " WHERE table_schema='public' AND table_name=%s "
                    " ORDER BY ordinal_position",
                    (r["table_name"],),
                ):
                    self.stdout.write(
                        f"    · {c['column_name']:30s} {c['data_type']}"
                    )

            # ---- 1) Every categoría --------------------------------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("All categorías in legacy:"))
            self.stdout.write(f"  {'id':>4s}  {'género':12s}  nombre")
            for r in db.iter_rows(
                "SELECT id_categoria, COALESCE(genero,'') AS genero, "
                "       COALESCE(nombre,'') AS nombre "
                "  FROM categoria ORDER BY id_categoria"
            ):
                self.stdout.write(
                    f"  {r['id_categoria']:>4d}  {r['genero']:12s}  {r['nombre']}"
                )

            # ---- 2) Every competición + its categoria_id + genero ---
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("All competiciones in legacy:"))
            self.stdout.write(
                f"  {'id':>4s}  {'comp.genero':14s}  {'cat_id':>6s}  {'nombre'}"
            )
            for r in db.iter_rows(
                "SELECT id_competicion, COALESCE(genero,'') AS genero, "
                "       categoria_id, COALESCE(nombre,'') AS nombre "
                "  FROM competicion ORDER BY id_competicion"
            ):
                cat = r["categoria_id"] if r["categoria_id"] is not None else "—"
                self.stdout.write(
                    f"  {r['id_competicion']:>4d}  {r['genero']:14s}  "
                    f"{str(cat):>6s}  {r['nombre']}"
                )

            # ---- 3) Citaciones per competición within scope ---------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                f"Citaciones per competición in scope ({df} → {dt}):"
            ))
            sql = """
                SELECT comp.id_competicion,
                       COALESCE(comp.nombre, '')  AS comp_nombre,
                       COALESCE(comp.genero, '')  AS comp_genero,
                       comp.categoria_id,
                       COALESCE(cat.nombre, '')   AS cat_nombre,
                       COALESCE(cat.genero, '')   AS cat_genero,
                       COUNT(c.id_citaciones)     AS n_citaciones,
                       COUNT(DISTINCT c.jugador_id) AS n_jugadores
                  FROM competicion comp
                  LEFT JOIN categoria cat ON cat.id_categoria = comp.categoria_id
                  LEFT JOIN competicion_temporada ct ON ct.competicion_id = comp.id_competicion
                  LEFT JOIN partido p ON p.competicion_temporada_id = ct.id_competicion_temporada
                                      AND p.fecha_partido BETWEEN %s AND %s
                  LEFT JOIN citaciones c ON c.partido_id = p.id_partido
                 GROUP BY comp.id_competicion, comp.nombre, comp.genero,
                          comp.categoria_id, cat.nombre, cat.genero
                 ORDER BY n_citaciones DESC, comp.id_competicion
            """
            self.stdout.write(
                f"  {'cmp':>3s} {'gen':6s} {'cat':>4s} "
                f"{'citas':>7s} {'jug':>5s}  comp.nombre → cat.nombre"
            )
            for r in db.iter_rows(sql, (df, dt)):
                marker = " ⚠" if (r["cat_genero"] or "").lower() == "femenino" else ""
                self.stdout.write(
                    f"  {r['id_competicion']:>3d} "
                    f"{(r['comp_genero'] or '')[:6]:6s} "
                    f"{str(r['categoria_id'] or '—'):>4s} "
                    f"{r['n_citaciones']:>7,} {r['n_jugadores']:>5,}  "
                    f"{r['comp_nombre']} → {r['cat_nombre']}{marker}"
                )

            # ---- 4) Active players that have NO citacion in scope ---
            # Where do they actually appear?
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "Active players with NO citaciones — which tables do they appear in?"
            ))
            window = (df, dt) * 8
            sql = """
                WITH active_no_cit AS (
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
                    ) t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM citaciones c
                          JOIN partido p ON p.id_partido = c.partido_id
                         WHERE c.jugador_id = t.jugador_id
                    )
                )
                SELECT 'antropometria' AS src, COUNT(*) AS n FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM antropometria WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'lesion', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM lesion WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'hoja_diaria', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM hoja_diaria WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'wellness', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM wellness WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'medicamentos', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM medicamentos WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'examenes', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM examenes WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'fase_densidad', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM fase_densidad WHERE jugador_id = a.jugador_id)
                UNION ALL SELECT 'gps_partido', COUNT(*) FROM active_no_cit a
                  WHERE EXISTS (SELECT 1 FROM gps_partido WHERE jugador_id = a.jugador_id)
            """
            self.stdout.write(f"  {'tabla':16s}  players")
            for r in db.iter_rows(sql, window):
                self.stdout.write(f"  {r['src']:16s}  {r['n']:>5,}")

            # ---- 5) The 5 first uncovered jugadores — names ---------
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE(
                "Sample of 10 uncovered players (no citaciones in scope):"
            ))
            sql = """
                WITH active_no_cit AS (
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
                    ) t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM citaciones c WHERE c.jugador_id = t.jugador_id
                    )
                )
                SELECT j.id_jugador, j.primer_nombre, j.primer_apellido,
                       j.segundo_apellido
                  FROM jugador j
                  JOIN active_no_cit a ON a.jugador_id = j.id_jugador
                 ORDER BY j.id_jugador
                 LIMIT 10
            """
            for r in db.iter_rows(sql, window):
                self.stdout.write(
                    f"  #{r['id_jugador']:<5d} "
                    f"{(r.get('primer_nombre') or '')} "
                    f"{(r.get('primer_apellido') or '')} "
                    f"{(r.get('segundo_apellido') or '')}"
                )
            self.stdout.write("")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()
