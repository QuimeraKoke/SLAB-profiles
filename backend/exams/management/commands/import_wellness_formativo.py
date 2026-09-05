"""Import the Formativo's wellness documents (Check-IN + Check-OUT).

    # ensayo: no escribe nada, reporta lo que haría
    docker compose exec backend python manage.py import_wellness_formativo

    # histórico completo
    docker compose exec backend python manage.py import_wellness_formativo --commit

    # sólo lo nuevo (lo que corre el cron)
    docker compose exec backend python manage.py import_wellness_formativo \\
        --commit --dias 7

Los documentos salen de `FORMATIVO_WELLNESS_SHEET_IDS`. Un id suelto se puede
pasar con `--sheet-id` para probar uno solo sin tocar la configuración.

Cada documento cuesta 3 requests (abrir + dos hojas) y Sheets permite 60
lecturas por minuto: los ocho son 24, con margen. Un 503 transitorio de Google
ya apareció una vez en ocho aperturas, así que cada documento se reintenta y un
documento inalcanzable **no** hunde a los otros siete.
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Club
from exams import wellness_formativo_ingest as ingest


class Command(BaseCommand):
    help = "Importa los Check-IN y Check-OUT del formativo desde Google Sheets."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None)
        parser.add_argument("--sheet-id", action="append", dest="sheet_ids",
                            help="Un documento puntual (repetible).")
        parser.add_argument("--dias", type=int, default=None,
                            help="Sólo respuestas de los últimos N días.")
        parser.add_argument("--rol", choices=["checkin", "checkout"], default=None,
                            help="Sólo una de las dos hojas.")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--alertas", action="store_true",
                            help="Evaluar reglas de alerta sobre lo nuevo "
                                 "(sólo lo de los últimos 30 días).")

    def handle(self, *args, **opts):
        from integrations.google_sheets import Documento

        nombre = opts["club"] or settings.FORMATIVO_CLUB
        club = Club.objects.filter(name=nombre).first()
        if club is None:
            raise CommandError(f"No existe el club '{nombre}'.")

        ids = opts["sheet_ids"] or settings.FORMATIVO_WELLNESS_SHEET_IDS
        if not ids:
            raise CommandError(
                "No hay documentos: definí FORMATIVO_WELLNESS_SHEET_IDS o pasá "
                "--sheet-id.")
        creds = dict(creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                     creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        if not (creds["creds_file"] or creds["creds_json"]):
            raise CommandError("Faltan las credenciales de Google Sheets.")

        desde = ingest.ventana(opts["dias"])
        roles = [opts["rol"]] if opts["rol"] else ["checkin", "checkout"]
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("ENSAYO — no escribe nada.\n"))

        reportes, fallidos = [], []
        # Todo dentro de una transacción, incluso el ensayo, para que las dos
        # ramas recorran exactamente el mismo camino: un `if commit:` alrededor
        # de la escritura hace que el ensayo pruebe un código distinto del que
        # después corre de verdad.
        with transaction.atomic():
            for sid in ids:
                try:
                    doc = self._abrir(Documento, sid, creds)
                    titulo = doc.titulo()
                except Exception as exc:
                    fallidos.append((sid, f"{type(exc).__name__}: {exc}"))
                    self.stdout.write(self.style.ERROR(
                        f"  {sid[:16]}… inalcanzable: {exc}"))
                    continue
                for rol in roles:
                    try:
                        rep = ingest.ingerir(doc, titulo=titulo, club=club,
                                             rol=rol, commit=True, desde=desde,
                                             alertas=opts["alertas"])
                    except Exception as exc:
                        fallidos.append((f"{titulo}/{rol}",
                                         f"{type(exc).__name__}: {exc}"))
                        self.stdout.write(self.style.ERROR(
                            f"  {titulo} · {rol}: {exc}"))
                        continue
                    reportes.append(rep)
                    self._linea(rep)
            if not opts["commit"]:
                transaction.set_rollback(True)

        self._resumen(reportes, fallidos, commit=opts["commit"])
        if fallidos:
            raise CommandError(
                f"{len(fallidos)} documento(s)/hoja(s) fallaron — ver arriba.")

    def _abrir(self, Documento, sid, creds, intentos=3):
        """Reintenta: Google devolvió un 503 en uno de ocho documentos, y un
        429 de cuota en otros dos cuando el sync corrió pegado a otra lectura.
        La espera la decide `espera_reintento`, que distingue los dos casos."""
        for i in range(intentos):
            try:
                return Documento(sid, **creds)
            except Exception as exc:
                if i == intentos - 1:
                    raise
                time.sleep(ingest.espera_reintento(exc, i))

    def _linea(self, r):
        partes = [f"{r.creados:6} nuevos", f"{r.repetidos:6} ya estaban"]
        if r.no_encontrados:
            partes.append(f"{sum(r.no_encontrados.values())} sin jugador")
        if r.ambiguos:
            partes.append(f"{sum(r.ambiguos.values())} ambiguos")
        if r.fuera_de_categoria:
            partes.append(f"{r.fuera_de_categoria} de otra categoría")
        if r.sin_fecha:
            partes.append(f"{r.sin_fecha} sin fecha")
        if r.alertas:
            partes.append(f"{r.alertas} alertas")
        estilo = self.style.SUCCESS if r.creados else self.style.NOTICE
        self.stdout.write(estilo(
            f"  {r.documento:26} {r.hoja:10} {r.filas:6} filas · "
            + " · ".join(partes)))
        # Una columna sin mapear se grita: es la forma exacta en que una
        # métrica desaparece sin que nadie lo note.
        if r.columnas_sin_mapear:
            self.stdout.write(self.style.WARNING(
                f"      ⚠ columnas sin mapear: {r.columnas_sin_mapear}"))

    def _resumen(self, reportes, fallidos, *, commit):
        filas = sum(r.filas for r in reportes)
        creados = sum(r.creados for r in reportes)
        repetidos = sum(r.repetidos for r in reportes)
        sin_jug: dict = {}
        ambiguos: dict = {}
        for r in reportes:
            for k, v in r.no_encontrados.items():
                sin_jug[k] = sin_jug.get(k, 0) + v
            for k, v in r.ambiguos.items():
                ambiguos[k] = ambiguos.get(k, 0) + v

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"  {len(reportes)} hoja(s) · {filas} filas · {creados} nuevos · "
            f"{repetidos} ya estaban"))
        if sin_jug:
            self.stdout.write(self.style.WARNING(
                f"  {len(sin_jug)} nombre(s) sin jugador en SLAB "
                f"({sum(sin_jug.values())} filas):"))
            for n, c in sorted(sin_jug.items(), key=lambda kv: -kv[1])[:20]:
                self.stdout.write(f"      · {n} ({c})")
        if ambiguos:
            self.stdout.write(self.style.ERROR(
                f"  {len(ambiguos)} nombre(s) ambiguo(s) — NO se importaron, "
                f"hay que desambiguarlos a mano:"))
            for n, c in sorted(ambiguos.items(), key=lambda kv: -kv[1])[:20]:
                self.stdout.write(f"      · {n} ({c})")
        if fallidos:
            self.stdout.write(self.style.ERROR(f"  {len(fallidos)} fallo(s):"))
            for quien, err in fallidos:
                self.stdout.write(f"      · {quien}: {err}")
        if not commit:
            self.stdout.write(self.style.WARNING(
                "\n  ENSAYO — volvé a correr con --commit para escribir."))
