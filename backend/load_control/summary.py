"""Resumen — "¿Cómo está el plantel hoy / esta semana?" (question 1 of the
club's brief): traffic-light cards with a number, one conclusion sentence on
top, the detail folded. The whole point is the staff's three questions in
under 10 seconds: ¿cumplió la semana?, ¿a quién compensar?, ¿quién llega
fatigado?

Deterministic — no LLM (the AI summaries were removed from the Centro de
mando and the Daily for cost with no readers, 4492ab3). Nothing is computed
here that a tab does not already compute; each card is a tab's service and
links to it, so the summary and the tab never disagree:

* Carga        `evaluation.evaluate` (the week so far, accumulated).
* Fatiga       `fatigue.fatigue` (the latest measured match).
* Check-in     `wellness.wellness` on the latest day with answers.
* Disponibles  `availability.availability`.
* Entrenamientos / minutos  `participation.participation`.

"Para revisar" joins, per player, every flag the tabs raise with the club's
own bands: a metric in alerta grave for the week (short → compensar, over →
pasado), a hard match hit / no recovery, pain or illness in the check-in, not
available. No new thresholds.
"""
from __future__ import annotations

from django.utils import timezone

from load_control.week import days_of
from load_control.availability import availability
from load_control.evaluation import evaluate
from load_control.fatigue import fatigue
from load_control.models import LoadControlConfig, Microcycle
from load_control.participation import participation
from load_control.wellness import wellness


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary(mc: Microcycle) -> dict:
    today = timezone.localdate()
    ref = min(today, mc.end_date)

    # ── Carga: the week so far, squad and per player ──────────────────────
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    ok_pct, short_min, over_pct = float(cfg["band_ok_pct"]), int(cfg["short_min_metrics"]), float(cfg["over_pct"])
    ev = evaluate(mc)
    metrics = {m["key"]: m for m in ev["metrics"]}
    load_flags: dict[str, dict] = {}
    for p in ev["players"]:
        below = [k for k, c in p["cells"].items() if c["pct"] is not None and c["pct"] < -ok_pct]
        short = below if len(below) >= short_min else []
        over = [k for k, c in p["cells"].items() if c["pct"] is not None and c["pct"] > over_pct]
        if short or over:
            load_flags[p["player_id"]] = {"name": p["name"], "short": short, "over": over,
                                          "days": p["days"], "days_planned": p["days_planned"]}
    squad_load = [{"key": k, "label": metrics[k]["label"], **v} for k, v in ev["summary"].items()]
    worst = min((x for x in squad_load if x["pct"] is not None), key=lambda x: -abs(x["pct"]), default=None)

    # ── Fatiga: the latest measured match ─────────────────────────────────
    fa = fatigue(mc)
    recovery = fa["next_match"] is not None
    fat_flags = {}
    for r in fa["rows"]:
        band = r["llega_band"] if recovery else r["golpe_band"]
        if band == "grave":
            fat_flags[r["player_id"]] = {"name": r["name"], "pct": r["llega_pct"] if recovery else r["golpe_pct"]}
    fc = fa["summary"]["counts"]["llega" if recovery else "golpe"]

    # ── Check-in: the latest day of the week with answers, up to today ────
    days = sorted(d.date for d in days_of(mc) if d.date <= ref)
    wl, wl_day = None, None
    for d in reversed(days):
        w = wellness(mc, day=d)
        if w.get("answered", {}).get("checkin") or w.get("answered", {}).get("checkout"):
            wl, wl_day = w, d
            break
    well_flags = {}
    if wl:
        for r in wl["flagged"]:
            if r["pain"] or r["symptoms"] or r["lows"]:
                well_flags[r["player_id"]] = {"name": r["name"], "pain": r["pain"], "symptoms": r["symptoms"],
                                              "lows": [x["key"] for x in r["lows"]]}

    # ── Disponibles ───────────────────────────────────────────────────────
    av = availability(mc)
    counts = {c["status"]: c for c in av["counts"]}
    out_flags = {r["player_id"]: {"name": r["name"], "status_label": r["status_label"],
                                  "expected_return": (r["episode"] or {}).get("expected_return")}
                 for r in av["unavailable"]}

    # ── Entrenamientos / minutos ──────────────────────────────────────────
    pa = participation(mc)

    # ── Para revisar: every flag, per player ──────────────────────────────
    review: dict[str, dict] = {}

    def add(pid, name, kind, text, level):
        r = review.setdefault(pid, {"player_id": pid, "name": name, "flags": [], "score": 0})
        r["flags"].append({"kind": kind, "text": text, "level": level})
        r["score"] += 3 if level == "grave" else 1

    for pid, f in out_flags.items():
        add(pid, f["name"], "estado", f["status_label"] + (f" · retorno {f['expected_return']}" if f["expected_return"] else ""),
            "grave")
    for pid, f in fat_flags.items():
        add(pid, f["name"], "fatiga",
            ("No recuperó su salto" if recovery else "Golpe fuerte del partido") + f" ({f['pct']:+.1f} %)", "grave")
    for pid, f in load_flags.items():
        if f["short"]:
            add(pid, f["name"], "carga", "Para compensar: " + ", ".join(metrics[k]["short"] or metrics[k]["label"] for k in f["short"])
                + f" bajo −{ok_pct:g} %" + (f" ({f['days']} de {f['days_planned']} días con GPS)" if f["days"] < f["days_planned"] else ""),
                "leve")
        if f["over"]:
            add(pid, f["name"], "carga", "Pasado: " + ", ".join(metrics[k]["short"] or metrics[k]["label"] for k in f["over"])
                + f" sobre +{over_pct:g} %", "leve")
    for pid, f in well_flags.items():
        if f["pain"]:
            # One answer can list several zones ("Cuádriceps Izq., Tobillo") and
            # the same zone often comes in both forms: each zone once.
            parts = [z.strip() for txt in f["pain"] for z in txt.split(",") if z.strip()]
            zones = list({z.lower().rstrip("."): z for z in parts}.values())
            add(pid, f["name"], "checkin", "Molestia: " + ", ".join(zones), "grave")
        if f["symptoms"]:
            add(pid, f["name"], "checkin", "Síntoma: " + ", ".join(f["symptoms"]), "leve")
        if f["lows"]:
            labels = {i["key"]: i["label"] for i in wl["items"]}
            add(pid, f["name"], "checkin", "Bienestar bajo: " + ", ".join(labels.get(k, k) for k in f["lows"]), "leve")
    review_rows = sorted(review.values(), key=lambda r: (-r["score"], r["name"]))

    # ── The sentence ──────────────────────────────────────────────────────
    parts = []
    planned = ev.get("provenance", {}).get("planned", True)
    if not planned:
        parts.append("Semana sin planificar (sin objetivo de carga)")
    elif worst:
        word = "en objetivo" if worst["band"] == "ok" else ("bajo" if worst["pct"] < 0 else "sobre") + " el objetivo"
        parts.append(f"La semana va {word} (lo más alejado: {worst['label']} {worst['pct']:+.0f} %)"
                     if worst["band"] != "ok" else "La semana va en objetivo en todas las métricas")
    n_short = sum(1 for f in load_flags.values() if f["short"])
    if n_short:
        parts.append(_plural(n_short, "jugador para compensar", "jugadores para compensar"))
    if fat_flags:
        parts.append(_plural(len(fat_flags), "no recuperado" if recovery else "con golpe fuerte del partido",
                             "no recuperados" if recovery else "con golpe fuerte del partido"))
    n_pain = sum(1 for f in well_flags.values() if f["pain"])
    if n_pain:
        parts.append(_plural(n_pain, "con molestias", "con molestias") + " en el check-in")
    if out_flags:
        parts.append(_plural(len(out_flags), "no disponible", "no disponibles"))
    # The load statement (when there is one) is its own sentence; the counts
    # follow as one list.
    head = parts[:1] if (not planned or worst) else []
    rest = parts[len(head):]
    chunks = head + ([", ".join(rest)] if rest else [])
    sentence = (". ".join(c[0].upper() + c[1:] for c in chunks) + ".") if chunks else "Sin novedades esta semana."

    return {
        "ref_day": ref.isoformat(),
        "sentence": sentence,
        "cards": {
            "load": {"metrics": squad_load, "worst": worst, "days": len(ev["days"]), "planned": planned,
                     "rules": {"short_min_metrics": short_min, "below_pct": ok_pct, "over_pct": over_pct},
                     "short": n_short, "over": sum(1 for f in load_flags.values() if f["over"])},
            "fatigue": {"state": "recuperacion" if recovery else "fatiga", "match": fa["match"],
                        "next_match": fa["next_match"], "counts": fc,
                        "measured": fa["summary"]["llega_n" if recovery else "golpe_n"]},
            "wellness": {"day": wl_day.isoformat() if wl_day else None,
                         "answered": (wl or {}).get("answered"), "missing": len((wl or {}).get("missing", [])),
                         "pain": n_pain, "flagged": len(well_flags)},
            "availability": {"counts": av["counts"], "players": av["players"],
                             "available": counts.get("available", {}).get("n", 0)},
            "participation": {"sessions": pa["sessions"], "matches": len(pa["matches"])},
        },
        "review": review_rows,
    }
