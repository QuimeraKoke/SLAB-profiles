"""Repair the formativo GPS loaded from the club's sheet: duplicates and match links.

1. **Re-coded duplicates.** In Sept 2026 the club re-coded its past match-day
   rows — `MD` → `MD OFICIAL` / `MD AMISTOSO` — and since the code was part of
   a row's identity, the next sync imported every one of them again
   (2026-09-24). The pairs are the same row; the NEWER one is kept, because the
   re-code came with corrections — except a pair with the SAME code, which is a
   plain re-import, where the older (already repaired) one stays (two players' numbers swapped on 2026-09-05).
   It inherits the match link of the one it replaces if it has none. Every
   row's `origen_id` is rewritten to the identity the sync now uses
   (`formativo_gps_ingest.codigo_identidad`), so the sheet's rows keep
   matching them.

2. **Match links.** `gps_partido` rows are (re)linked by the team that played
   and the opponent — see `formativo_gps_ingest.EventMatcher`. A row whose
   match cannot be found keeps its link, unless that link is another team's
   match (the old rule linked by the player's category): then it is cleared.

4. **Match fields.** `opponent`, `match_type`, `venue`, `result`,
   `opponent_quality`, `opponent_rank` (`formativo_gps_ingest.CAMPOS_PARTIDO`)
   are added to the GPS templates in place; their values come from the next
   sync, which refreshes them on rows that already exist.

3. **Friendlies.** `gps_sesion` gets back its "amistoso" session type (added
   in place to the template's `tipo_sesion` options — not by re-seeding the
   template, which would overwrite its whole schema) and every session the
   club coded `MD AMISTOSO` is labelled with it.

    docker compose exec backend python manage.py repair_formativo_gps            # plan
    docker compose exec backend python manage.py repair_formativo_gps --backup   # JSON of every row it would touch
    docker compose exec backend python manage.py repair_formativo_gps --commit
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Club
from exams import formativo_gps_ingest as ing
from exams.models import ExamResult, ExamTemplate


class Command(BaseCommand):
    help = "Quita duplicados re-codificados del GPS formativo y re-vincula partidos."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--backup", action="store_true",
                            help="Imprime en JSON todas las filas que se borrarían o "
                                 "modificarían, sin cambiar nada.")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError("Club no encontrado.")
        filas = list(ExamResult.objects
                     .filter(player__category__club=club, result_data__origen=ing.ORIGEN)
                     .select_related("template", "player", "event__bracket")
                     .order_by("created_at"))

        # ---- 1. duplicates -------------------------------------------------
        grupos: dict[tuple, list[ExamResult]] = defaultdict(list)
        for r in filas:
            d = r.result_data
            grupos[(r.player_id, r.template_id, r.recorded_at.date(), d.get("origen_hoja"),
                    ing.codigo_identidad(d.get("origen_codigo") or ""))].append(r)
        borrar: list[ExamResult] = []
        tocadas: dict = {}
        raros = 0
        por_codigos = Counter()
        for grupo in grupos.values():
            if len(grupo) < 2:
                continue
            codigos = [g.result_data.get("origen_codigo") or "" for g in grupo]
            if len(set(codigos)) == 1:
                # Same code, same identity: a re-import, not a re-code (a sync
                # still running the old identity rule after this command
                # rewrote the ids — 2026-10-01, local). The OLDER row is the
                # one already repaired (links, labels): keep it.
                queda, sobran = grupo[0], grupo[1:]
            elif len(set(codigos)) != len(codigos):
                raros += 1      # a mix nobody explains: not ours to judge
                continue
            else:
                queda, sobran = grupo[-1], grupo[:-1]
            por_codigos[" + ".join(codigos)] += 1
            if queda.event_id is None:
                heredado = next((s.event_id for s in sobran if s.event_id), None)
                if heredado:
                    queda.event_id = heredado
                    tocadas[queda.pk] = queda
            borrar.extend(sobran)
        ids_borrar = {r.pk for r in borrar}

        # ---- identity rewrite ------------------------------------------------
        nuevas_ids = 0
        for r in filas:
            if r.pk in ids_borrar:
                continue
            d = r.result_data
            if not d.get("origen_id"):
                continue
            # name|day|sheet|code|slug — only the code part changes.
            partes = d["origen_id"].split("|")
            if len(partes) != 5:
                continue
            partes[3] = ing.codigo_identidad(partes[3])
            esperado = "|".join(partes)
            if esperado != d["origen_id"]:
                d["origen_id"] = esperado
                tocadas[r.pk] = r
                nuevas_ids += 1

        # ---- 2. match links --------------------------------------------------
        matcher = ing.EventMatcher(club)
        enlaces = Counter()
        for r in filas:
            if r.pk in ids_borrar or r.template.slug != ing.SLUG_PARTIDO:
                continue
            d = r.result_data
            e = matcher.evento(d.get("origen_hoja") or "", r.recorded_at.date(),
                               ing.rival_de_sesion(d.get("sesion") or ""))
            if e is None:
                actual = r.event.bracket.name if r.event_id and r.event.bracket_id else None
                if actual and actual != matcher.bracket_de_hoja(d.get("origen_hoja") or ""):
                    # Linked by the old rule to ANOTHER team's match (a U20
                    # row on a Primera match): wrong, whatever the right one is.
                    enlaces["desvinculado (era el partido de otro equipo)"] += 1
                    r.event_id = None
                    tocadas[r.pk] = r
                else:
                    enlaces["sin partido encontrado" + (" (conserva el suyo)" if r.event_id else "")] += 1
            elif r.event_id == e.id:
                enlaces["ya bien vinculado"] += 1
            else:
                enlaces["corregido (otro partido)" if r.event_id else "vinculado (no tenía)"] += 1
                r.event_id = e.id
                tocadas[r.pk] = r

        # ---- 4. match fields (rival, localía, calidad, resultado) ------------
        # Only the template fields: the values arrive with the next sync,
        # which refreshes them on existing rows (`formativo_gps_ingest`).
        campos_nuevos: list[tuple] = []
        for slug, claves in ((ing.SLUG_PARTIDO, (*ing.CLAVES_PARTIDO, "md_label")),
                             (ing.SLUG_SESION, (*ing.CAMPOS_SESION_PARTIDO, "md_label"))):
            for t in ExamTemplate.objects.filter(department__club=club, slug=slug):
                faltan = [k for k in claves if k not in
                          {f.get("key") for f in (t.config_schema or {}).get("fields") or []}]
                if faltan:
                    campos_nuevos.append((t, claves, faltan))

        # ---- 3. friendlies ---------------------------------------------------
        plantillas_sin_amistoso = []
        for t in ExamTemplate.objects.filter(department__club=club, slug=ing.SLUG_SESION):
            campo = next((f for f in (t.config_schema or {}).get("fields") or []
                          if f.get("key") == "tipo_sesion"), None)
            if campo is not None and ing.TIPO_AMISTOSO not in (campo.get("options") or []):
                plantillas_sin_amistoso.append((t, campo))
        amistosos = 0
        for r in filas:
            d = r.result_data
            if (r.pk not in ids_borrar and r.template.slug == ing.SLUG_SESION
                    and d.get("origen_codigo") == "MD AMISTOSO"
                    and d.get("tipo_sesion") != ing.TIPO_AMISTOSO):
                d["tipo_sesion"] = ing.TIPO_AMISTOSO
                tocadas[r.pk] = r
                amistosos += 1

        if opts["backup"]:
            antes = ExamResult.objects.filter(pk__in=ids_borrar | set(tocadas))
            self.stdout.write("BACKUP_BEGIN")
            self.stdout.write(serializers.serialize(
                "json", [*antes, *(t for t, _ in plantillas_sin_amistoso),
                         *(t for t, _, _ in campos_nuevos)]))
            self.stdout.write("BACKUP_END")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nAPLICADO\n" if opts["commit"] else "\nPLAN (sin --commit no escribe)\n"))
        self.stdout.write(f"  filas del GPS formativo: {len(filas)}")
        self.stdout.write(f"  duplicados re-codificados a borrar: {len(borrar)}")
        for k, n in por_codigos.most_common():
            self.stdout.write(f"    {n:>5}  {k}")
        if raros:
            self.stdout.write(f"  grupos con el mismo código repetido (no se tocan): {raros}")
        self.stdout.write(f"  origen_id reescritos: {nuevas_ids}")
        self.stdout.write("  vínculo a partido (gps_partido):")
        for k, n in enlaces.most_common():
            self.stdout.write(f"    {n:>5}  {k}")

        self.stdout.write(f"  sesiones marcadas como amistoso: {amistosos}")
        self.stdout.write(f"  plantillas gps_sesion a las que se agrega «amistoso»: "
                          f"{len(plantillas_sin_amistoso)}")

        for t, _, faltan in campos_nuevos:
            self.stdout.write(f"  campos de partido a agregar en {t.slug}: {', '.join(faltan)}")

        if not opts["commit"]:
            return
        with transaction.atomic():
            for t, claves, _ in campos_nuevos:
                t.refresh_from_db()
                ing.asegurar_campos(t, claves)
                t.save(update_fields=["config_schema", "updated_at"])
                t.rebuild_template_fields()
            for t, _ in plantillas_sin_amistoso:
                t.refresh_from_db()     # step 4 may have just saved it
                campo = next(f for f in t.config_schema["fields"] if f.get("key") == "tipo_sesion")
                if ing.TIPO_AMISTOSO in (campo.get("options") or []):
                    continue
                campo["options"] = [*(campo.get("options") or []), ing.TIPO_AMISTOSO]
                campo.setdefault("option_labels", {})[ing.TIPO_AMISTOSO] = "Amistoso"
                t.save(update_fields=["config_schema", "updated_at"])
                t.rebuild_template_fields()
            ExamResult.objects.filter(pk__in=ids_borrar).delete()
            ExamResult.objects.bulk_update(
                [r for pk, r in tocadas.items() if pk not in ids_borrar],
                ["event", "result_data"], batch_size=500)
        self.stdout.write(self.style.SUCCESS("  listo."))
