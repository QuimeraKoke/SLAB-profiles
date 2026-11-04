"""Default parameters of the load-control module, and how a club overrides them.

The club asked for "la mayoría de elementos configurables" (2026-11-03), so
every number the staff decided lives here as a DEFAULT, not in code paths:

    DEFAULTS  ←  LoadControlConfig.settings  ←  .bracket_overrides[<bracket code>]

Merging is per top-level key: a club that overrides `metrics` replaces the
whole list. Nested merging would make "remove a metric" impossible to say.
"""
from __future__ import annotations

import copy
import unicodedata
import re

DEFAULTS: dict = {
    # The five metrics with a target. Keys are `gps_sesion` / `gps_partido`
    # fields; labels follow the club's sheet headers (thresholds included).
    "metrics": [
        {"key": "tot_dist", "label": "Distancia total", "short": "DT", "unit": "m"},
        {"key": "hsr", "label": "HSR >20 km/h", "short": "HSR", "unit": "m"},
        {"key": "sprint_dist", "label": "Sprint >25 km/h", "short": "Sprint", "unit": "m"},
        {"key": "acc", "label": "Aceleraciones >3 m/s²", "short": "ACC", "unit": ""},
        {"key": "dec", "label": "Desaceleraciones <−3 m/s²", "short": "DEC", "unit": ""},
    ],
    # |Δ%| vs target: ≤ ok → en objetivo, ≤ mild → alerta leve, else grave.
    "band_ok_pct": 8,
    "band_mild_pct": 12,
    "symmetric": True,
    # Resumen "para compensar / pasados" — the club's artifact rules: short =
    # at least `short_min_metrics` metrics under −`band_ok_pct` %; over = any
    # metric above +`over_pct` % for the week so far.
    "short_min_metrics": 3,
    "over_pct": 20,
    # Match reference: mean per position group of players with more than
    # `ref_min_minutes` of GPS, in official matches of the last N days.
    "ref_window_days": 28,
    "ref_min_minutes": 75,
    "ref_official_only": True,
    # A group with fewer distinct qualifying players than this uses the team's
    # mean (and says so). 1 = only when it has none. What the club does with a
    # thin group is the club's call (2026-11-03: "lo que la U use"), so this is
    # a parameter, not a judgement baked in here.
    "ref_min_players": 1,
    # MD±n of a day the club has not coded yet (a future week). A day with GPS
    # always takes the club's own CÓDIGO. "nearest" = closest match (upcoming on
    # a tie); "next" = always counted to the next match. Measured against the
    # club's codes (2026 season): next fits 84–88%, nearest 72–78% — neither is
    # what the staff always do, so it is the PF's call, not ours.
    "md_label_rule": "nearest",
    # Check-in: an item at or below this (1–5, 5 = best) is "bienestar bajo".
    # 2 = the club's own dashboard (1–2 red, 3 amber, 4–5 green).
    "wellness_low": 2,
    # Minutos y asistencia: a team session is a day with team GPS for at least
    # this many players. Attendance under `attendance_low_pct` gets the red
    # light — None (off) until the PF says what the club uses.
    "session_min_players": 5,
    "attendance_low_pct": None,
    # Sparring adds to the player's load; the team average may leave it out.
    "include_sparring": True,
    # Jump fatigue (slice 3+): best attempt, RSI drop thresholds in %.
    "attempt_value": "best",
    "rsi_alert": {"ok_from": 0, "grave_at": -5},
    # Basal = mean of the player's last N PRE jumps (the MD+2 screen uses 5).
    "jump_baseline_n": 5,
    # The club's R-CMJ RSI levels (rebote / contacto), same for U15–U20.
    "rsi_levels": [
        {"label": "Deficiente", "max": 1.2},
        {"label": "< Media", "max": 1.4},
        {"label": "Media", "max": 1.8},
        {"label": "> Media", "max": 2.1},
        {"label": "Bueno", "max": None},
    ],
    # The club's TIPO values (seen in the GPS sheet, 2026-11-03).
    "microcycle_kinds": ["mixta", "amplitud", "profundidad", "adaptacion", "competencia"],
    # Position groups. A row is placed by the POSICIÓN the club wrote on it
    # (`posicion_hoja`); a row without one falls back to the player's roster
    # position, matched by NAME — never by abbreviation: SLAB's "DC" is a
    # centre-back while the club's DC group is the centre-forward.
    "position_groups": [
        {"code": "DFC", "label": "Defensa central",
         "sheet_labels": ["DEFENSA CENTRAL"], "position_names": ["Defensa central"]},
        {"code": "LAT", "label": "Lateral",
         "sheet_labels": ["DEFENSA LATERAL"],
         "position_names": ["Lateral", "Lateral derecho", "Lateral izquierdo",
                            "Lateral volante derecho", "Lateral volante izquierdo"]},
        {"code": "MC", "label": "Mediocampista",
         "sheet_labels": ["MEDIOCAMPISTA"],
         "position_names": ["Mediocampista", "Volante central", "Volante interior",
                            "Volante ofensivo", "Volante derecho", "Volante izquierdo"]},
        {"code": "EXT", "label": "Extremo",
         "sheet_labels": ["EXTREMO"], "position_names": ["Extremo"]},
        {"code": "DC", "label": "Centro delantero",
         "sheet_labels": ["CENTRO DELANTERO"],
         "position_names": ["Delantero", "Delantero centro"]},
        {"code": "POR", "label": "Arquero",
         "sheet_labels": ["GUARDAMETA"], "position_names": ["Arquero"]},
    ],
    "excluded_groups": ["POR"],
}


def merged(settings: dict | None = None, override: dict | None = None) -> dict:
    out = copy.deepcopy(DEFAULTS)
    for layer in (settings or {}, override or {}):
        for key, value in layer.items():
            if key in DEFAULTS:
                out[key] = copy.deepcopy(value)
    return out


def norm(value: object) -> str:
    """Accent- and case-insensitive key, the GPS ingest's own normalisation."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


class GroupResolver:
    """Places a GPS row (and its player) in a position group of a config."""

    def __init__(self, cfg: dict):
        self.by_sheet: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        for g in cfg["position_groups"]:
            for label in g.get("sheet_labels", []):
                self.by_sheet[norm(label)] = g["code"]
            for name in g.get("position_names", []):
                self.by_name[norm(name)] = g["code"]
        self.excluded = set(cfg.get("excluded_groups") or [])
        self.codes = [g["code"] for g in cfg["position_groups"]]

    def group(self, result_data: dict, position_name: str | None) -> str | None:
        code = self.by_sheet.get(norm(result_data.get("posicion_hoja")))
        if code is None and position_name:
            code = self.by_name.get(norm(position_name))
        return code

    @property
    def active_codes(self) -> list[str]:
        return [c for c in self.codes if c not in self.excluded]
