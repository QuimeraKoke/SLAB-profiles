"""Scheduled wellness Check-IN sync (Google Sheet → ExamResults).

Beat fires `sync_wellness_responses` frequently during the morning check-in
window and less often off-peak (see config/celery.py). Each run pulls the form
responses, feeds them through the shared `wellness_ingest` pipeline, and
upserts molestia alerts. A Redis lock prevents overlapping runs from stacking.

No-ops cleanly (logs + returns) when the sheet/credentials aren't configured,
so the schedule is safe to ship before the club wires its own Google key.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

_LOCK_KEY = "lock:sync_wellness_responses"
_LOCK_TTL = 240  # seconds — longer than a normal run, shorter than the 5-min tick


@shared_task(name="exams.tasks.sync_wellness_responses")
def sync_wellness_responses(mode: str = "today", since_days: int = 3) -> dict:
    """Pull wellness form responses and ingest them.

    mode: "today" (frequent ticks) | "reconcile" (daily catch-up of the last
    `since_days`) | "all" (full backfill).
    """
    from core.models import Category
    from exams.models import ExamTemplate
    from exams.wellness_ingest import WELLNESS_SLUG, ingest_wellness
    from integrations.google_sheets import GoogleSheetsError, fetch_rows

    sheet_id = settings.WELLNESS_SHEET_ID
    creds_file = settings.GOOGLE_SHEETS_CREDENTIALS_FILE
    creds_json = settings.GOOGLE_SHEETS_CREDENTIALS_JSON
    if not sheet_id or not (creds_file or creds_json):
        logger.info("wellness sync skipped: WELLNESS_SHEET_ID / credentials not set")
        return {"status": "skipped", "reason": "not configured"}

    # Best-effort cross-run lock (skip if a previous run is still going).
    lock = None
    try:
        from django.core.cache import cache
        lock = cache
        if not cache.add(_LOCK_KEY, "1", _LOCK_TTL):
            logger.info("wellness sync skipped: another run holds the lock")
            return {"status": "skipped", "reason": "locked"}
    except Exception:  # pragma: no cover — cache backend unavailable
        lock = None

    try:
        category = (
            Category.objects.filter(
                name=settings.WELLNESS_CATEGORY, club__name=settings.WELLNESS_CLUB,
            ).select_related("club").first()
        )
        if category is None:
            logger.warning("wellness sync: category %r / club %r not found",
                           settings.WELLNESS_CATEGORY, settings.WELLNESS_CLUB)
            return {"status": "error", "reason": "category not found"}
        template = ExamTemplate.objects.filter(
            slug=WELLNESS_SLUG, department__club=category.club,
        ).first()
        if template is None:
            logger.warning("wellness sync: template %r not found", WELLNESS_SLUG)
            return {"status": "error", "reason": "template not found"}

        try:
            rows = fetch_rows(
                sheet_id, settings.WELLNESS_SHEET_WORKSHEET,
                creds_file=creds_file, creds_json=creds_json,
            )
        except GoogleSheetsError as exc:
            logger.error("wellness sync: %s", exc)
            return {"status": "error", "reason": str(exc)}

        report = ingest_wellness(
            rows, template=template, category=category,
            mode=mode, since_days=since_days,
        )
        logger.info("wellness sync (%s): %s", mode, report)
        return {"status": "ok", "mode": mode, **report}
    finally:
        if lock is not None:
            try:
                lock.delete(_LOCK_KEY)
            except Exception:  # pragma: no cover
                pass


# ── Formativo: las dos planillas vivas del club ─────────────────────────
# El club NO trabaja sobre archivos: mantiene dos Google Sheets y reparte
# exports .xlsx de ellas. Sincronizar el documento vivo es lo que convierte una
# importación puntual en un dato que se mantiene: entre el export que
# importamos y la hoja de hoy ya había 76 filas más de GPS y 35 de
# evaluaciones, y esa brecha crece todos los días.
#
# Los dos ingests son idempotentes por `result_data["origen_id"]`, así que un
# tick sólo escribe lo nuevo y re-leer la hoja completa es seguro. Leerla
# completa es además lo correcto: el club edita filas viejas (corrige una
# fecha, completa un dato que faltaba), y una ventana por fecha se perdería
# esas correcciones.
_LOCK_FORMATIVO = "lock:sync_formativo_sheets"
_LOCK_FORMATIVO_TTL = 3600  # una corrida completa toma minutos, no segundos


def _formativo_creds() -> tuple[str, str]:
    return (settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
            settings.GOOGLE_SHEETS_CREDENTIALS_JSON)


@shared_task(name="exams.tasks.sync_formativo_sheets")
def sync_formativo_sheets(commit: bool = True, alerts: bool = False) -> dict:
    """Pull both Formativo sheets into their exams.

    `alerts=False` on purpose: these documents carry two seasons of history, and
    an alert anchored on a two-year-old reading is expired again by the next
    staleness sweep — firing them would only churn the alert list. The daily
    tick that DOES want alerts can pass `alerts=True` once the club is caught
    up.
    """
    from core.models import Club
    from exams import formativo_gps_ingest, formativo_ingest
    from integrations.google_sheets import GoogleSheetsError

    creds_file, creds_json = _formativo_creds()
    gps_id = settings.FORMATIVO_GPS_SHEET_ID
    eval_id = settings.FORMATIVO_EVAL_SHEET_ID
    if not (creds_file or creds_json) or not (gps_id or eval_id):
        logger.info("formativo sync skipped: sheets/credentials not configured")
        return {"status": "skipped", "reason": "not configured"}

    club = Club.objects.filter(name=settings.FORMATIVO_CLUB).first()
    if club is None:
        logger.warning("formativo sync skipped: club %r not found",
                       settings.FORMATIVO_CLUB)
        return {"status": "skipped", "reason": "club not found"}

    lock = None
    try:
        from django.core.cache import cache

        lock = cache
        if not cache.add(_LOCK_FORMATIVO, "1", _LOCK_FORMATIVO_TTL):
            logger.info("formativo sync skipped: another run holds the lock")
            return {"status": "skipped", "reason": "locked"}
    except Exception:  # pragma: no cover — cache backend unavailable
        lock = None

    salida: dict = {"status": "ok"}
    try:
        for clave, sheet_id, modulo in (
            ("evaluaciones", eval_id, formativo_ingest),
            ("gps", gps_id, formativo_gps_ingest),
        ):
            if not sheet_id:
                continue
            try:
                rep = modulo.run(
                    sheet_id, club, commit=commit, fire_alerts=alerts,
                    creds_file=creds_file, creds_json=creds_json,
                )
            except GoogleSheetsError as exc:
                # One unreachable document must not sink the other.
                logger.warning("formativo sync (%s) failed: %s", clave, exc)
                salida[clave] = {"status": "error", "error": str(exc)}
                salida["status"] = "partial"
                continue
            salida[clave] = {
                "creados": rep.creados, "ya_existian": rep.ya_existian,
                "sin_jugador": len(rep.sin_jugador),
                "fuera_de_rango": len(rep.fuera_de_rango),
            }
            # These two are the tell that the club changed the sheet's shape,
            # and they are worth a log line rather than a silent partial load.
            faltan = getattr(rep, "columnas_sin_mapear", None)
            if faltan:
                logger.error("formativo sync (%s): métricas sin mapear %s",
                             clave, faltan)
                salida[clave]["columnas_sin_mapear"] = faltan
            desconocidas = getattr(rep, "columnas_desconocidas", None)
            if desconocidas:
                logger.warning("formativo sync (%s): columnas nuevas %s",
                               clave, desconocidas)
                salida[clave]["columnas_desconocidas"] = desconocidas
        logger.info("formativo sync: %s", salida)
        return salida
    finally:
        if lock is not None:
            try:
                lock.delete(_LOCK_FORMATIVO)
            except Exception:  # pragma: no cover
                pass


_LOCK_WELLNESS_FORM = "lock:sync_wellness_formativo"
_LOCK_WELLNESS_FORM_TTL = 3600


@shared_task(name="exams.tasks.sync_wellness_formativo")
def sync_wellness_formativo(commit: bool = True, dias: int | None = 7,
                            alerts: bool = True) -> dict:
    """Pull the Formativo's eight wellness documents (Check-IN + Check-OUT).

    `dias=7` by default rather than the full history. The documents go back to
    February 2024 and hold ~118.000 responses between them; re-reading all of
    it every tick would cost minutes per run to find the handful of rows that
    are new. The window is generous on purpose — a day of downtime, like the
    nine the local Celery stack spent unable to resolve Redis, still gets
    caught up without a manual backfill. Pass `dias=None` for the full sweep.

    One unreachable document does NOT sink the other seven: Google returned a
    503 on one of eight during the first survey, and a sync that gives up on
    the first failure would silently skip a whole category until someone
    noticed.

    `alerts=True` here, unlike the GPS/evaluations sync: this one reads a
    7-day window of live responses, so every row it finds is recent enough to
    be worth an alert. The full weekly sweep passes `dias=None` and would
    re-read two seasons, but the ingest bounds the evaluation to the last 30
    days on its own — a 2024 reading is expired again by the next sweep.
    """
    import time

    from core.models import Club
    from exams import wellness_formativo_ingest as ingest
    from integrations.google_sheets import Documento

    creds_file, creds_json = _formativo_creds()
    ids = settings.FORMATIVO_WELLNESS_SHEET_IDS
    if not (creds_file or creds_json) or not ids:
        logger.info("wellness formativo skipped: sheets/credentials not configured")
        return {"status": "skipped", "reason": "not configured"}

    club = Club.objects.filter(name=settings.FORMATIVO_CLUB).first()
    if club is None:
        logger.warning("wellness formativo skipped: club %r not found",
                       settings.FORMATIVO_CLUB)
        return {"status": "skipped", "reason": "club not found"}

    lock = None
    try:
        from django.core.cache import cache

        lock = cache
        if not cache.add(_LOCK_WELLNESS_FORM, "1", _LOCK_WELLNESS_FORM_TTL):
            logger.info("wellness formativo skipped: another run holds the lock")
            return {"status": "skipped", "reason": "locked"}
    except Exception:  # pragma: no cover — cache backend unavailable
        lock = None

    creds = {"creds_file": creds_file, "creds_json": creds_json}
    desde = ingest.ventana(dias)
    salida: dict = {"status": "ok", "documentos": len(ids), "creados": 0,
                    "repetidos": 0, "sin_jugador": 0, "ambiguos": 0,
                    "alertas": 0, "fallidos": []}
    try:
        for sid in ids:
            doc = titulo = None
            for intento in range(3):
                try:
                    doc = Documento(sid, **creds)
                    titulo = doc.titulo()
                    break
                except Exception as exc:
                    if intento == 2:
                        logger.warning("wellness formativo: %s inalcanzable: %s",
                                       sid[:16], exc)
                        salida["fallidos"].append(f"{sid[:16]}: {exc}")
                        salida["status"] = "partial"
                    else:
                        time.sleep(3 * (intento + 1))
            if doc is None:
                continue
            for rol in ("checkin", "checkout"):
                try:
                    rep = ingest.ingerir(doc, titulo=titulo, club=club, rol=rol,
                                         commit=commit, desde=desde,
                                         alertas=alerts)
                except Exception as exc:
                    logger.warning("wellness formativo (%s/%s): %s",
                                   titulo, rol, exc)
                    salida["fallidos"].append(f"{titulo}/{rol}: {exc}")
                    salida["status"] = "partial"
                    continue
                salida["creados"] += rep.creados
                salida["repetidos"] += rep.repetidos
                salida["sin_jugador"] += sum(rep.no_encontrados.values())
                salida["ambiguos"] += sum(rep.ambiguos.values())
                salida["alertas"] += rep.alertas
                # Una columna nueva en el formulario es la forma exacta en que
                # una métrica desaparece sin que nadie lo note.
                if rep.columnas_sin_mapear:
                    logger.error("wellness formativo (%s/%s): columnas nuevas %s",
                                 titulo, rol, rep.columnas_sin_mapear)
                    salida.setdefault("columnas_nuevas", []).append(
                        {"documento": titulo, "hoja": rol,
                         "columnas": rep.columnas_sin_mapear})
        logger.info("wellness formativo: %s", salida)
        return salida
    finally:
        if lock is not None:
            try:
                lock.delete(_LOCK_WELLNESS_FORM)
            except Exception:  # pragma: no cover
                pass


@shared_task(name="exams.tasks.sync_all_vald_clubs")
def sync_all_vald_clubs(full: bool = False) -> list[dict]:
    """Scheduled VALD Hub sync for every club with an enabled integration.

    No-ops cleanly when nothing is bound / no credentials are configured, so
    the beat schedule is safe to ship before a club wires its VALD keys.
    """
    from exams.models import ValdIntegration

    if not ValdIntegration.objects.filter(enabled=True).exists():
        logger.info("VALD sync skipped: no enabled integrations.")
        return []
    from exams.services.vald_sync import sync_all_bound_clubs

    reports = sync_all_bound_clubs(full=full)
    logger.info("VALD sync: %s", reports)
    return reports


@shared_task(name="exams.tasks.sync_all_catapult_categories")
def sync_all_catapult_categories() -> list[dict]:
    """Scheduled Catapult OpenField GPS sync for every category with an enabled
    integration — matches → gps_partido, trainings → gps_sesion, gap-fill so
    re-runs are idempotent (dedup on the Catapult activity_id).

    No-ops cleanly when nothing is bound / no token is configured, so the beat
    schedule is safe to ship before a club wires its Catapult key.
    """
    from exams.models import CatapultIntegration

    if not CatapultIntegration.objects.filter(enabled=True).exists():
        logger.info("Catapult sync skipped: no enabled integrations.")
        return []
    from exams.services.catapult_sync import plan_all_enabled

    plans = plan_all_enabled(dry_run=False)
    summary = [{"category": p.category, "errors": p.errors, **p.totals()} for p in plans]
    logger.info("Catapult sync: %s", summary)
    return summary


@shared_task(name="exams.tasks.sync_all_comet_clubs")
def sync_all_comet_clubs() -> list[dict]:
    """Scheduled COMET LIVE sync for every club with an enabled integration —
    played matches → the "Ficha oficial de partido" template + the match Event's
    general data (score, round, referee, venue).

    No-ops cleanly when nothing is bound, so the beat schedule is safe to ship
    before a club wires its federation key. Additive: a ficha that already
    exists for (player, match-day) is skipped, so re-runs are idempotent.
    """
    from exams.models import CometIntegration

    if not CometIntegration.objects.filter(enabled=True).exists():
        logger.info("COMET sync skipped: no enabled integrations.")
        return []
    from exams.services.comet_sync import sync_all_clubs

    reports = sync_all_clubs(dry_run=False)
    logger.info("COMET sync: %s", reports)
    return reports
