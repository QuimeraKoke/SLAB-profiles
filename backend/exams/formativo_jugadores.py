"""The formativo's player register — tab JUGADORES of "Evaluaciones físicas
categorías" — into the Player records: birth date, foot and photo.

    JUGADOR · FECHA DE NACIMIENTO · AÑOS Y MESES · CATEGORÍA · POSICIÓN · FOTOS · PERFIL

The evaluation import matched players against this sheet all along (birth
date first, name as the guard — `formativo_gps_ingest.build_matcher`) but never
WROTE what it holds. So:

* **Birth date** — filled where SLAB has none. Never overwritten: the matcher
  keys on it, and a disagreement is a question for a person, reported.
* **Foot** (PERFIL: DERECHO / IZQUIERDO / AMBOS) — the sheet is the club's
  register, so it wins: filled when empty, corrected when it differs.
* **Photo** (FOTOS: a Google Drive link) — COPIED into SLAB's storage, not
  linked. Drive is not a CDN: a changed permission, a moved file or a rate
  limit would blank every profile and every ficha at once, and the PDFs fetch
  the image server-side on every render. The copy is resized (≤ 600 px, JPEG)
  and named after the Drive file id, so a new photo in the sheet replaces the
  old one and an unchanged one is never downloaded twice. Folder links
  (13 rows in Oct 2026) carry no single image and are skipped.

Dry-run by default; `run(..., commit=True)` writes.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

import requests
from django.core.files.base import ContentFile

from core.models import Club, Player

logger = logging.getLogger(__name__)

HOJA = "JUGADORES"
FOTO_MAX_PX = 600
_DRIVE_FILE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^#]*&)?id=)([\w-]{20,})")
_PIE = {"DERECHO": Player.PREFERRED_FOOT_RIGHT, "IZQUIERDO": Player.PREFERRED_FOOT_LEFT,
        "AMBOS": Player.PREFERRED_FOOT_BOTH, "AMBIDIESTRO": Player.PREFERRED_FOOT_BOTH,
        "AMBIDEXTRO": Player.PREFERRED_FOOT_BOTH}


@dataclass
class Reporte:
    filas: int = 0
    sin_jugador: list[str] = field(default_factory=list)
    nacimiento: int = 0
    pie_nuevo: int = 0
    pie_corregido: int = 0
    fotos: int = 0
    fotos_fallidas: list[str] = field(default_factory=list)
    nacimiento_distinto: list[str] = field(default_factory=list)


def drive_id(link: str) -> str | None:
    m = _DRIVE_FILE.search(link or "")
    return m.group(1) if m else None


def _foto_nombre(player: Player, fid: str) -> str:
    return f"{player.id}-{fid}.jpg"


def descargar_foto(fid: str) -> bytes | None:
    """The Drive file as a ≤ 600 px JPEG, or None (not an image, not shared)."""
    from PIL import Image, ImageOps

    try:
        r = requests.get("https://drive.google.com/uc", params={"export": "download", "id": fid},
                         timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content)))
        img = img.convert("RGB")
        img.thumbnail((FOTO_MAX_PX, FOTO_MAX_PX))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — a corrupt file is one skipped photo
        return None


def run(origen: str, club: Club, *, commit: bool = False, fotos: bool = True,
        creds_file: str = "", creds_json: str = "") -> Reporte:
    from exams.formativo_gps_ingest import _fecha, build_matcher, norm
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    try:
        hoja = match_sheet(fuente.hojas(), HOJA)
        grid = fuente.filas(hoja) if hoja else []
    finally:
        fuente.cerrar()
    rep = Reporte()
    if not grid:
        return rep
    cab = [norm(c) for c in grid[0]]
    ix = {c: i for i, c in enumerate(cab) if c}
    i_nom, i_dob = ix.get("JUGADOR"), next((i for c, i in ix.items() if "NACIMIENTO" in c), None)
    i_foto, i_pie = ix.get("FOTOS") or ix.get("FOTO"), ix.get("PERFIL")
    if i_nom is None:
        return rep

    match = build_matcher(club)
    vistos: set = set()
    for r in grid[1:]:
        get = lambda i: (r[i] if i is not None and i < len(r) else None)  # noqa: E731
        nombre = str(get(i_nom) or "").strip()
        if not nombre:
            continue
        rep.filas += 1
        dob = _fecha(get(i_dob))
        p = match(nombre, dob)
        if p is None:
            rep.sin_jugador.append(nombre)
            continue
        if p.id in vistos:
            continue
        vistos.add(p.id)
        cambios: list[str] = []

        if dob and p.date_of_birth is None:
            p.date_of_birth = dob
            cambios.append("date_of_birth")
            rep.nacimiento += 1
        elif dob and p.date_of_birth != dob:
            rep.nacimiento_distinto.append(f"{nombre}: SLAB {p.date_of_birth} · planilla {dob}")

        pie = _PIE.get(norm(get(i_pie)))
        if pie and p.preferred_foot != pie:
            rep.pie_corregido += bool(p.preferred_foot)
            rep.pie_nuevo += not p.preferred_foot
            p.preferred_foot = pie
            cambios.append("preferred_foot")

        if commit and cambios:
            p.save(update_fields=cambios)

        fid = drive_id(str(get(i_foto) or ""))
        if fotos and fid and not (p.photo and p.photo.name.endswith(_foto_nombre(p, fid))):
            if not commit:
                rep.fotos += 1
                continue
            data = descargar_foto(fid)
            if data is None:
                rep.fotos_fallidas.append(nombre)
                continue
            viejo = p.photo.name if p.photo else None
            p.photo.save(_foto_nombre(p, fid), ContentFile(data), save=True)
            if viejo:
                p.photo.storage.delete(viejo)
            rep.fotos += 1
    return rep
