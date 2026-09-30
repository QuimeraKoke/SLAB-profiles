"""Import the Formativo's injury register (tab `E` of the medical sheet).

Reads, matches, and — with `--commit` — creates one `lesiones` episode per
matched injury: an opening result at the injury date and, when discharged, a
closing one at the discharge date. Rows that match nobody are reported and
skipped; they come in on a later run once the club fixes them.

Re-runnable: each episode carries `legacy_raw.origen_id` (player + date +
region), so a second run creates nothing and only CLOSES the injuries the club
has discharged since.

    docker compose exec backend python manage.py import_lesiones_formativo            # plan
    docker compose exec backend python manage.py import_lesiones_formativo --commit   # write
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Club
from exams import lesiones_formativo_ingest as ing

METODOS = [
    ("rut", "RUT de la fila"),
    ("rut_dp", "RUT vía Datos Personales"),
    ("alias", "Alias confirmado"),
    ("dob", "Nacimiento vía Datos Personales"),
    ("nombre", "Nombre exacto"),
    ("parcial", "Nombre parcial (único)"),
    ("ambiguo", "Ambiguo — NO se asigna"),
    ("conflicto_rut", "RUT de otra persona — NO se asigna"),
    ("conflicto_edad", "Edad no coincide — NO se asigna"),
    ("sin_jugador", "Sin jugador en SLAB"),
]


class Command(BaseCommand):
    help = "Lesiones del formativo: lee la hoja E y reporta el emparejamiento."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=ing.SHEET_ID, dest="origen",
                            help="Id de la Google Sheet (por defecto la del club) o un .xlsx.")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--detalle", action="store_true",
                            help="Lista todos los nombres sin jugador, no sólo los primeros.")
        parser.add_argument("--commit", action="store_true",
                            help="Escribe los episodios (por defecto: sólo el plan).")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")

        lesiones, sin_fecha, personales = ing.leer(
            opts["origen"],
            creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
            creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        rep, pares = ing.diagnosticar(club, lesiones, personales, sin_fecha)
        w = self.stdout.write

        ok = sum(rep.por_metodo[m] for m in ("rut", "rut_dp", "alias", "dob", "nombre", "parcial"))
        w(self.style.MIGRATE_HEADING("\nEMPAREJAMIENTO\n"))
        w(f"  lesiones leídas     : {rep.filas}   (sin fecha: {rep.sin_fecha})")
        w(f"  Datos Personales    : {len(personales)} claves de nombre")
        w(self.style.SUCCESS(
            f"  emparejadas         : {ok} ({ok / max(rep.filas, 1):.0%}) "
            f"→ {len(rep.jugadores)} jugadores"))
        for clave, titulo in METODOS:
            w(f"    {titulo:<34} {rep.por_metodo[clave]:>4}")

        w("\n  por año de lesión      emparejadas / sin emparejar")
        for anio in sorted(rep.por_anio):
            c = rep.por_anio[anio]
            total = c["ok"] + c["no"]
            w(f"    {anio}   {c['ok']:>4} / {c['no']:<4}  ({c['ok'] / total:.0%})")
        w(f"\n  estado 'Lesionado' hoy: {rep.activas['ok']} emparejadas, "
          f"{rep.activas['no']} sin emparejar")
        if rep.desempatados:
            w(f"  desempatadas por el nombre (RUT/fecha compartidos): {rep.desempatados}")
        if rep.fuera_formativo:
            w(f"  emparejadas a un plantel senior: {dict(rep.fuera_formativo)}")

        if rep.ambiguos:
            w(self.style.WARNING(f"\n  Ambiguos: {len(rep.ambiguos)}"))
            for nombre, cands in rep.ambiguos.items():
                w(f"    {nombre}")
                for c in cands:
                    w(f"        · {c}")

        if rep.conflictos:
            w(self.style.ERROR(f"\n  Conflictos (no se asignan): {len(rep.conflictos)}"))
            for c in rep.conflictos:
                w(f"    {c}")

        if rep.ruts_compartidos:
            w(self.style.ERROR(
                f"\n  ⚠ RUT compartido por dos jugadores en SLAB: {len(rep.ruts_compartidos)}"))
            for ps in rep.ruts_compartidos:
                w("    " + " · ".join(
                    f"{p.first_name} {p.last_name} ({p.category.name}, {p.national_id}, "
                    f"{p.date_of_birth})" for p in ps))

        sin = sorted(rep.sin_jugador.items(), key=lambda kv: max(kv[1]), reverse=True)
        w(self.style.WARNING(
            f"\n  Sin jugador: {len(sin)} nombres, "
            f"{sum(len(v) for _, v in sin)} lesiones (más recientes primero)"))
        w(f"    {len(rep.en_personales)} están en Datos Personales del club · "
          f"{len(rep.sugerencias)} tienen un nombre parecido en SLAB")
        w("    DP = está en Datos Personales · ≈ sugerencia a confirmar (no se asigna)")
        for nombre, fechas in (sin if opts["detalle"] else sin[:30]):
            dp = "DP" if nombre in rep.en_personales else "  "
            sug = rep.sugerencias.get(nombre)
            extra = (f"≈ {sug[0].first_name} {sug[0].last_name} "
                     f"{sug[0].second_last_name} ({sug[0].category.name}, {sug[1]:.2f})"
                     if sug else "")
            w(f"    {dp} {nombre:<32} {len(fechas):>3}  última {max(fechas)}  {extra}")
        if not opts["detalle"] and len(sin) > 30:
            w(f"    … y {len(sin) - 30} más (--detalle)")

        self._plan(club, pares, opts)

    def _plan(self, club, pares, opts):
        from collections import Counter

        from exams.models import ExamTemplate

        w = self.stdout.write
        hoy = timezone.localdate()
        planes = ing.planificar(pares, hoy)
        acc = Counter(p.accion for p in planes)
        crear = [p for p in planes if p.accion == "crear"]
        abiertas = [p for p in crear if p.alta is None]

        w(self.style.MIGRATE_HEADING("\nPLAN\n"))
        w(self.style.SUCCESS(f"  episodios a crear   : {len(crear)} "
                             f"({len(abiertas)} abiertos, {len(crear) - len(abiertas)} cerrados)"))
        w(f"  a cerrar (re-corrida): {acc['cerrar']}")
        w(f"  ya existían         : {acc['ya_existe']}")
        w(f"  repetidas en la hoja: {acc['duplicado']}")
        w(f"  abiertas de Primer Equipo, omitidas: {acc['omitir_senior']}")
        for p in planes:
            if p.accion == "omitir_senior" or (p.accion == "ya_existe" and p.nota):
                w(f"    fila {p.lesion.fila}: {p.lesion.nombre} {p.lesion.fecha} — "
                  f"{p.nota or 'abierta en un plantel senior'}")
        sin_dur = [p for p in crear if p.nota]
        if sin_dur:
            w(self.style.WARNING(f"\n  Cerradas sin duración conocida: {len(sin_dur)}"))
            for p in sin_dur:
                w(f"    fila {p.lesion.fila}: {p.lesion.nombre} {p.lesion.fecha} — {p.nota}")
        viejas = [p for p in abiertas if (hoy - p.inicio).days > ing.REVISAR_DIAS]
        if viejas:
            w(self.style.WARNING(
                f"\n  Abiertas hace más de {ing.REVISAR_DIAS} días (confirmar con el club): {len(viejas)}"))
            for p in viejas:
                w(f"    fila {p.lesion.fila}: {p.lesion.nombre} desde {p.inicio} — "
                  f"{p.datos.get('body_part_detail', '')[:50]}")
        sin_region = sum(1 for p in crear if "body_part" not in p.datos)
        sin_tipo = sum(1 for p in crear if "type" not in p.datos)
        partido = sum(1 for p in crear if ing.norm(p.lesion.datos.get("exposicion")) == "PARTIDO")
        oficial = sum(1 for p in crear if p.datos.get("exposicion") == "Partido oficial")
        w(f"\n  sin región: {sin_region} · sin tipo: {sin_tipo} · "
          f"'Partido' confirmado oficial por ficha ANFP: {oficial}/{partido}")

        # The template applies only where the club records injuries today.
        # Without the formativo categories, "+ Nueva lesión" is missing on
        # every youth profile the import just filled.
        template = (ExamTemplate.objects.filter(slug="lesiones", department__club=club,
                                                is_active_version=True).first()
                    or ExamTemplate.objects.filter(slug="lesiones", department__club=club).first())
        if template is None:
            raise CommandError("No existe la plantilla 'lesiones' — correr seed_lesiones.")
        faltan = {p.player.category for p in crear} - set(template.applicable_categories.all())
        if faltan:
            w(f"\n  'lesiones' pasa a aplicar también a: "
              f"{', '.join(sorted(c.name for c in faltan))}")

        if not opts["commit"]:
            w(self.style.NOTICE("\nPlan — nada escrito. Repetir con --commit."))
            return
        with transaction.atomic():
            template.applicable_categories.add(*faltan)
            n = ing.escribir(planes, fuente=opts["origen"])
        w(self.style.SUCCESS(f"\nListo: {n}"))
