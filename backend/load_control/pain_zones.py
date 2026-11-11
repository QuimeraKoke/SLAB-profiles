"""Where it hurts: the check-in / check-out pain answers as body zones.

The formativo's forms ask "Señala tu dolor muscular" (check-in) and "Señala si
tuviste alguna molestia muscular después del entrenamiento" (check-out) with a
fixed list of muscle groups and a side — "Isquiotibiales Izq.", "Gemelos /
Sóleo Der." — that most categories have used since 2024. They live side by
side with free text ("Tobillo derecho", "Ampollas pie derecho", "Dolor de
rodilla") from the "Otro" option and from the forms that never had the list
(Sub 11, Sub 12, the Sub 16 check-in), and with typos of the list itself
("Psoas Izq,", "Isquiotibiales Der,,").

`parse` turns one answer into (zone, side) pairs plus whatever it could not
place, which is kept as written — never dropped, a pain the map cannot draw is
still a pain. The parsing runs at read time over the stored text, so history
and the raw answer are untouched and a better alias list fixes the past too.

Zone keys match `frontend/src/lib/painZones.ts` (the map's geometry). Sides
are "izq" / "der", or None when the answer names the muscle but not the side
(the old free-text forms): those are counted, but drawn on neither leg.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

# key: (label, sided, aliases). Aliases are matched as whole words on the
# normalized text (no accents, lowercase), longest first, so "columna dorsal"
# wins over "dorsal" and "deltoides posterior" over "deltoides".
ZONES: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    "cuello": ("Cuello", True, ("cuello", "cervical")),
    "trapecio": ("Trapecio", True, ("trapecio", "trapecios")),
    "deltoides_anterior": ("Deltoides anterior", True, ("deltoides anterior",)),
    "deltoides_posterior": ("Deltoides posterior", True, ("deltoides posterior",)),
    "pectoral": ("Pectoral mayor", True, ("pectoral mayor", "pectoral", "pectorales")),
    "dorsal": ("Dorsal", True, ("dorsal", "dorsales", "dorsal ancho")),
    "triceps": ("Tríceps", True, ("triceps",)),
    "antebrazo": ("Antebrazo", True, ("antebrazo", "antebrazos")),
    "muneca": ("Muñeca", True, ("muneca", "munecas")),
    "abdomen": ("Abdomen", False, ("abdomen", "abdominal", "abdominales", "recto abdominal")),
    "oblicuo": ("Oblicuo", True, ("oblicuo", "oblicuos")),
    "columna_dorsal": ("Columna dorsal", False, ("columna dorsal",)),
    "columna_lumbar": ("Columna lumbar", False, ("columna lumbar", "lumbar", "lumbares", "espalda baja",
                                                 "zona lumbar")),
    "psoas": ("Psoas", True, ("psoas", "zoas", "flexores de cadera", "flexor de cadera", "psoas mayor",
                                    "iliaco o recto femoral", "iliaco", "recto femoral")),
    "gluteo": ("Glúteo", True, ("gluteo", "gluteos")),
    "aductores": ("Aductores", True, ("aductores", "aductor", "ingle")),
    "cuadriceps": ("Cuádriceps", True, ("cuadriceps", "cuadricep", "cuadricepts")),
    "isquiotibiales": ("Isquiotibiales", True, ("isquiotibiales", "isquiotibial", "isquios", "isquio")),
    "rodilla": ("Rodilla", True, ("rodilla", "rodillas")),
    "popliteo": ("Poplíteo", True, ("popliteo",)),
    "tibial": ("Tibial", True, ("tibial", "tibiales", "tibia", "canilla")),
    "gemelos": ("Gemelos / Sóleo", True, ("gemelos soleo", "gemelos", "gemelo", "soleo", "pantorrilla",
                                          "pantorrillas")),
    "tobillo": ("Tobillo", True, ("tobillo", "tobillos")),
    "pie": ("Pie", True, ("pie", "pies", "empeine", "talon", "planta del pie")),
}

SIDE_LABEL = {"izq": "Izq.", "der": "Der."}

_NOTHING = {"", "no", "ninguno", "ninguna", "nada", "sin molestias", "sin dolor", "ningun dolor",
            "ninguna molestia", "n a", "na"}

# Words that only frame the zone ("dolor de rodilla", "molestia en el lado
# derecho"): not something else that hurts.
_FILLER = {"dolor", "dolores", "de", "del", "en", "el", "la", "los", "las", "lado", "molestia", "molestias",
           "leve", "poco", "un", "una", "musculo", "muscular", "zona", "y", "con", "al", "a"}

_ALIASES = sorted(((alias, key) for key, (_, _, aliases) in ZONES.items() for alias in aliases),
                  key=lambda a: -len(a[0]))
_LEFT = re.compile(r"\b(izq\w*|izda|isq|isk)\b")
_RIGHT = re.compile(r"\b(der|dcha|derech\w*)\b")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]+", " ", t)          # "/", ".", "(" … → space
    return re.sub(r"\s+", " ", t).strip()


def zone_label(key: str, side: str | None) -> str:
    label = ZONES[key][0]
    return f"{label} {SIDE_LABEL[side]}" if side else label


def parse(text: object) -> tuple[list[tuple[str, str | None]], list[str]]:
    """One answer → ([(zone, side)], [what could not be placed, as written])."""
    if text is None:
        return [], []
    raw = str(text).strip()
    zones: list[tuple[str, str | None]] = []
    others: list[str] = []
    # The list joins options with ", "; a typo doubles the comma. " y " joins
    # free text ("rodilla y tobillo").
    for chunk in re.split(r",|;|\by\b", raw):
        piece = chunk.strip(" .,-")
        norm = _norm(piece)
        if norm in _NOTHING:
            continue
        found = []
        rest = f" {norm} "
        for alias, key in _ALIASES:
            if f" {alias} " in rest:
                found.append(key)
                rest = rest.replace(f" {alias} ", " ")
        if not found:
            others.append(piece)
            continue
        left, right = bool(_LEFT.search(norm)), bool(_RIGHT.search(norm))
        sides: list[str | None] = (["izq", "der"] if left and right else ["izq"] if left
                                   else ["der"] if right else [None])
        for key in dict.fromkeys(found):
            for side in (sides if ZONES[key][1] else [None]):
                zones.append((key, side))
        # Words left over once the zone and side are gone ("Mano derecha
        # (dedo)" has no zone; "Rodilla, ampolla"…) are not lost.
        leftover = " ".join(w for w in _RIGHT.sub(" ", _LEFT.sub(" ", rest)).split() if w not in _FILLER)
        if len(leftover) > 2 and leftover not in _NOTHING:
            others.append(piece)
    return list(dict.fromkeys(zones)), list(dict.fromkeys(others))


def labels(texts) -> list[str]:
    """Several answers of one player-day → the zones by name, then what could
    not be placed. What the screen lists as "Molestia"."""
    zs, os_ = [], []
    for t in texts:
        z, o = parse(t)
        zs += z
        os_ += o
    return [zone_label(k, s) for k, s in dict.fromkeys(zs)] + list(dict.fromkeys(os_))


def body_map(player_days) -> dict:
    """[(player_id, name, date, [texts])] → the squad's pain by zone.

    A zone marked in both forms of one day counts once for that day. `marks`
    = player-days, `players` = distinct players (who, and how many days each).
    """
    cells: dict[tuple, dict] = {}
    others: list[dict] = []
    for pid, name, day, texts in player_days:
        seen: set = set()
        for t in texts:
            z, o = parse(t)
            for zone in z:
                if zone in seen:
                    continue
                seen.add(zone)
                c = cells.setdefault(zone, {"marks": 0, "who": defaultdict(int), "names": {}})
                c["marks"] += 1
                c["who"][str(pid)] += 1
                c["names"][str(pid)] = name
            for text in o:
                others.append({"player_id": str(pid), "name": name, "date": day.isoformat(), "text": text})
    out = []
    for (key, side), c in cells.items():
        out.append({
            "zone": key, "side": side, "label": zone_label(key, side),
            "marks": c["marks"], "players": len(c["who"]),
            "who": sorted(({"player_id": p, "name": c["names"][p], "days": d} for p, d in c["who"].items()),
                          key=lambda w: (-w["days"], w["name"])),
        })
    out.sort(key=lambda z: (-z["players"], -z["marks"], z["label"]))
    others.sort(key=lambda o: (o["date"], o["name"]))
    return {"zones": out, "others": others}
