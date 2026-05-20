"""Lookup tables that translate legacy values to SLAB canonical values.

Centralised here so the per-phase importers stay focused on the I/O
and the human-readable mappings are easy to review/edit in one place.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID


# --- Category name normalisation ---------------------------------------
# Legacy `categoria.nombre` → SLAB `Category.name`. Mostly identity;
# PEM (Primer Equipo Masculino) is the notable rename.
CATEGORY_NAME_MAP: dict[str, str] = {
    "PEM": "Primer Equipo",
    # Sub-X categories tend to come over verbatim; female-team variants
    # encode the gender in the name itself (e.g. "U18 - Femenino").
}


# --- Player preferred foot ----------------------------------------------
# Legacy `jugador.pie` (free-form Spanish) → SLAB Player.PREFERRED_FOOT_*.
PREFERRED_FOOT_MAP: dict[str, str] = {
    "Derecho": "right",
    "Izquierdo": "left",
    "Ambos": "both",
    "Ambidiestro": "both",
}


# --- Lesion mappings ----------------------------------------------------
# Legacy `tipo_lesion` → SLAB lesiones template `type`.
# Normalised input: strip + Spanish accents collapsed (`Concusión` and
# `Concusion` and `Concusi├│n` (mojibake) all hash to the same key).
LESION_TYPE_MAP: dict[str, str] = {
    "rotura muscular / desgarro / contractura / calambre": "Muscular",
    "rotura muscular / desgarro": "Muscular",
    "esguince / lesion de ligamento": "Ligamentosa",
    "lesion tendon /rotura / tendinosis / bursitis": "Tendinosa",
    "lesion tendon / rotura": "Tendinosa",
    "otra lesion osea": "Ósea / fractura",
    "fractura": "Ósea / fractura",
    "hematoma /contusion / equimosis": "Contusión",
    "hematoma / contusion": "Contusión",
    "lesion menisco / cartilago": "Articular",
    "dislocacion / subluxacion": "Articular",
    "concusion": "Concusión / TEC",
    "lesion del nervio": "Otra",
    "otra lesion": "Otra",
}

# Legacy `parte_lesionada` + `lateralidad` → SLAB `body_part`.
# Returns the SLAB body_part value, or None if no good match.
LESION_BODY_PART_BASE: dict[str, str] = {
    # left/right gets appended (` izq.` / ` der.`) below.
    "Muslo": "Muslo",
    "Rodilla": "Rodilla",
    "Tobillo": "Tobillo",
    "Pie / Dedos del pie": "Pie",
    "Pie": "Pie",
    "Pierna / Tendón de aquiles": "Pantorrilla",
    "Pierna / Tendón de a": "Pantorrilla",        # truncated row
    "Hombro / Clavicula": "Hombro",
    "Mano / Dedo / Pulgar": "Mano",
    "Muñeca": "Muñeca",
    "Codo": "Codo",
    "Antebrazo": "Antebrazo",
}
LESION_BODY_PART_NON_LATERAL: dict[str, str] = {
    # No laterality — direct mapping
    "Cabeza / Cara": "Cabeza",
    "Cuello / C.Cervical": "Cuello",
    "Pecho": "Pecho",
    "Abdomen": "Abdomen",
    "Esternon / Costillas / C.Toracica": "Pecho",
    "C.Lumbar / Sacro / Pelvis": "Espalda baja",
    "C.Lumbar / Sacro / F": "Espalda baja",       # truncated row
    "Cadera": "Cadera / pelvis",
}

# Legacy `lateralidad` normalisation
LATERALIDAD_LEFT = {"Izquierdo"}
LATERALIDAD_RIGHT = {"Derecho"}
LATERALIDAD_NONE = {"No Aplica", "No aplica", None, ""}


def map_lesion_body_part(parte: str | None, lateralidad: str | None) -> str | None:
    """Combine legacy `parte_lesionada` + `lateralidad` into the SLAB
    body_part option. Returns None when no mapping is available; callers
    should fall back to writing the raw value into body_part_detail."""
    if not parte:
        return None

    # First: non-lateralised parts (Cabeza / Pecho / etc.)
    if parte in LESION_BODY_PART_NON_LATERAL:
        return LESION_BODY_PART_NON_LATERAL[parte]

    base = LESION_BODY_PART_BASE.get(parte)
    if base is None:
        return None

    # Lateralise — collapse the casing dupes ('No Aplica' vs 'No aplica').
    if lateralidad in LATERALIDAD_LEFT:
        return f"{base} izq."
    if lateralidad in LATERALIDAD_RIGHT:
        return f"{base} der."
    # No laterality → use the "der." variant by default; callers can flag
    # via legacy_raw if the original was N/A. SLAB doesn't have unlateralised
    # options for limbs, so we pick a side rather than dropping.
    return f"{base} der."


# Legacy `causa` (Sobrecarga / Traumatica) → SLAB lesiones.causa option.
LESION_CAUSA_MAP: dict[str, str] = {
    "sobrecarga": "Sobrecarga",
    "traumatica": "Traumática",
    "traumática": "Traumática",
}

# Legacy `exposicion` → SLAB lesiones.exposicion option.
LESION_EXPOSICION_MAP: dict[str, str] = {
    "entrenamiento": "Entrenamiento",
    "partido": "Partido",
    "evento externo": "Evento externo",
}

# Legacy `tratamiento` → SLAB lesiones.tratamiento option.
LESION_TRATAMIENTO_MAP: dict[str, str] = {
    "kinesico": "Kinésico",
    "reposo deportivo": "Reposo deportivo",
    "kinesico + quirurgico": "Kinésico + quirúrgico",
}

# Legacy `estado` (`Alta` / `Lesionado`) + fecha_alta → SLAB `stage`.
# Returns one of: injured / recovery / reintegration / closed.
def map_lesion_stage(estado: str | None, fecha_alta) -> str:
    """`estado='Lesionado'` AND fecha_alta IS NULL → 'injured'.
    Otherwise → 'closed' (we don't have a signal to distinguish recovery
    from reintegration in legacy data)."""
    if estado and estado.strip().lower() == "lesionado" and fecha_alta is None:
        return "injured"
    return "closed"


def infer_lesion_severity(dias_perdidos: int | None) -> str:
    """Days lost → severity bucket: <8 mild, 8-30 moderate, >30 severe.
    Default to 'Moderada' when null (the median in the legacy data)."""
    if dias_perdidos is None:
        return "Moderada"
    if dias_perdidos < 8:
        return "Leve"
    if dias_perdidos <= 30:
        return "Moderada"
    return "Severa"


# --- Citation status (event participant match_role) --------------------
# Legacy `citaciones.estado` → SLAB EventParticipant.MatchRole value.
# Mojibake-friendly: `Selecci├│n` (legacy encoding bug) maps the same as
# `Selección`. Normalisation strips accents + lowercases for matching.
CITATION_STATUS_MAP: dict[str, str] = {
    "titular": "titular",
    "suplente ingresa": "suplente_ingresa",
    "suplente no ingresa": "suplente_no_ingresa",
    "no citado": "no_citado",
    "lesionado": "lesionado",
    "suspendido": "suspendido",
    "seleccion": "seleccion",
    "promovido": "promovido",
    "citado sin vestir": "citado_no_vestir",
}


# --- gps_partido tipo_evaluacion -> which SLAB period column ----------
GPS_PERIOD_MAP: dict[str, str] = {
    "Primer Tiempo": "p1",
    "Segundo Tiempo": "p2",
    "Partido Completo": "p1",   # see migration spec: Option B
}


# --- Medicacion tipo_de_medicamento normalisation ---------------------
# Maps known typos to the canonical value SLAB seeded.
MEDICACION_TIPO_NORMALIZE: dict[str, str] = {
    "Antiacido y antiulceren": "Antiacido y antiulcerosos",
    "Inductor del Sueño": "Inductor del sueño",
}


# --- helpers -----------------------------------------------------------


def _normalize(s: str | None) -> str:
    """Lowercase, strip, collapse accents. Mojibake characters (├ etc.)
    survive as themselves; the maps include the mojibake variants
    explicitly when relevant. Used as the key for fuzzy matching."""
    if s is None:
        return ""
    s = s.strip().lower()
    # Strip accents: NFD → drop combining chars
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def map_lesion_type(legacy_value: str | None) -> str:
    """Robust map for tipo_lesion handling mojibake/accents/typos."""
    if not legacy_value:
        return "Otra"
    key = _normalize(legacy_value)
    return LESION_TYPE_MAP.get(key, "Otra")


def map_lesion_causa(value: str | None) -> str | None:
    if not value:
        return None
    return LESION_CAUSA_MAP.get(_normalize(value))


def map_lesion_exposicion(value: str | None) -> str | None:
    if not value:
        return None
    return LESION_EXPOSICION_MAP.get(_normalize(value))


def map_lesion_tratamiento(value: str | None) -> str | None:
    if not value:
        return None
    return LESION_TRATAMIENTO_MAP.get(_normalize(value))


def map_citation_status(legacy_value: str | None) -> str | None:
    """Normalise + map. Returns None when the value can't be classified
    (caller defaults to 'no_citado' or skips)."""
    if not legacy_value:
        return None
    key = _normalize(legacy_value)
    return CITATION_STATUS_MAP.get(key)


def normalize_lateralidad(value: str | None) -> str:
    """Return canonical 'Derecho' / 'Izquierdo' / '' for the legacy
    casing-dupe values."""
    if value in LATERALIDAD_LEFT:
        return "Izquierdo"
    if value in LATERALIDAD_RIGHT:
        return "Derecho"
    return ""


def fix_mojibake(s: str | None) -> str | None:
    """Heuristic cleanup for legacy strings stored with bad encoding
    (the `├í` family). When `ftfy` isn't available we just return the
    string unchanged — the migration logs the raw value into legacy_raw
    so the original is always recoverable."""
    if not s:
        return s
    try:
        import ftfy  # type: ignore
        return ftfy.fix_text(s)
    except ImportError:
        return s


def jsonable(value: Any) -> Any:
    """Recursively convert a value into something Django's default
    JSONField encoder (json.JSONEncoder) can serialise. psycopg row
    values include date / datetime / time / Decimal / UUID / memoryview;
    none of those are JSON-safe by default. Used at every `legacy_raw =`
    write site so the source row can be stored verbatim."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Floats lose precision but pgvalues here are biometric numbers,
        # not money; the precision loss is below noise level.
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        # We don't expect any binary in legacy_raw payloads; fall back
        # to a length-tagged repr so the audit trail isn't lossy without
        # making the JSON huge.
        return f"<bytes len={len(bytes(value))}>"
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    # Last resort — stringify so we never crash on save.
    return str(value)
