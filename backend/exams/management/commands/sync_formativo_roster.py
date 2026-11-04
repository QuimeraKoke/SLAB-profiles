"""Serie and birth date of each formativo player, as the club's register
(tab JUGADORES) says. Thin CLI over `exams.formativo_roster`; dry-run by
default — read the plan, then run again with --commit.

    python manage.py sync_formativo_roster            # plan
    python manage.py sync_formativo_roster --commit
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Club
from exams import formativo_roster as ing

WHY = {
    "contradiccion": "Contradicción en la hoja (no se toca; corregir la hoja)",
    "sin_jugador": "Sin jugador en SLAB",
    "ambiguo": "Ambiguo: más de un jugador posible (no se toca)",
    "conflicto": "La hoja trae al jugador dos veces con datos distintos (no se toca)",
    "sin_categoria": "Sin categoría en la hoja (sólo se corrige la fecha)",
    "fecha_repetida": "Fecha repetida en la hoja: parece error de copia (no se cambia la fecha)",
}


class Command(BaseCommand):
    help = "Serie y fecha de nacimiento del formativo según la hoja JUGADORES (la regla del club)."

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="origen", default=settings.FORMATIVO_EVAL_SHEET_ID,
                            help="Id de la Google Sheet (por defecto FORMATIVO_EVAL_SHEET_ID) o .xlsx")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--season", type=int, default=None)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        if not opts["origen"]:
            raise CommandError("Falta --file (o FORMATIVO_EVAL_SHEET_ID).")
        season = opts["season"] or timezone.localdate().year
        try:
            rep = ing.run(opts["origen"], club, season=season, commit=opts["commit"],
                          creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                          creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        except ValueError as exc:
            raise CommandError(str(exc))
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("APLICADO" if opts["commit"] else "PLAN (sin cambios; usar --commit)"))
        w(f"  temporada {season} · filas en la hoja {rep.filas} · ya correctos {rep.sin_cambios} · a cambiar {len(rep.cambios)}")
        series = [c for c in rep.cambios if c.serie_despues]
        fechas = [c for c in rep.cambios if c.nac_despues]
        w(self.style.WARNING(f"  Cambios de Serie: {len(series)}"))
        for c in series:
            w(f"    {c.nombre:32} {c.serie_antes:12} → {c.serie_despues}")
        w(self.style.WARNING(f"  Fechas de nacimiento: {len(fechas)}"))
        for c in fechas:
            w(f"    {c.nombre:32} {c.nac_antes} → {c.nac_despues}")
        for key, names in rep.saltados.items():
            w(self.style.NOTICE(f"  {WHY.get(key, key)}: {len(names)}"))
            for n in names:
                w(f"    {n}")
