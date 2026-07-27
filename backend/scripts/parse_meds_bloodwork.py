#!/usr/bin/env python3
"""Parse a folder of Clínica MEDS blood-panel PDFs (one per player) into a CSV.

Each PDF's filename is the player's name. The panels share a fixed MEDS
layout, so we extract with `pdftotext -layout` and match known labels. Both
the single-value section (Ferritina, CK, Testosterona…) and the tabular
profiles (Hemograma, Perfil lipídico, bioquímico, hepático…) are captured.

Out-of-range arrows (↑/↓, rendered as ñ/ò by pdftotext) and below-detection
markers (e.g. "<0.300") are stripped from the numeric value but the raw
token is preserved verbatim for auditability where it matters.

Usage:
    python3 parse_meds_bloodwork.py "/path/to/Exámenes" [--out out.csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

# ── Single-value tests: "  <Label>: <value> <unit>" ──────────────────────────
# key -> (regex label, human column). The label is matched at line start after
# leading whitespace, up to the colon.
SINGLE_VALUE = [
    ("ferritina",            r"Ferritina"),
    ("transferrina",         r"Transferrina"),
    ("ck_total",             r"CK Total"),
    ("magnesio",             r"Magnesio"),
    ("vitamina_b12",         r"Vitamina B12"),
    ("vitamina_d",           r"Vitamina D"),
    ("cortisol_am",          r"Cortisol AM"),
    ("testosterona_total",   r"Testosterona Total"),
    ("tsh",                  r"Hormona Tiroestimulante \(TSH\)"),
    ("pcr_ultrasensible",    r"Proteina C Reactiva Ultrasensible"),
]

# Qualitative single-value tests (result is a word, not a number).
SINGLE_QUAL = [
    ("hepatitis_b_ag",  r"Hepatitis B Ant[ií]geno de superficie"),
    ("hepatitis_c_ac",  r"Hepatitis C, Anticuerpos"),
]

# ── Tabular tests: "<param>  <value>  <unit>  ..." ───────────────────────────
# key -> exact parameter label as printed in the table (anchored at line start).
TABLE_PARAMS = [
    # Capacidad de Fijación del Fierro (TIBC)
    ("tibc",                 r"Capacidad de Fijaci[oó]n del Fierro"),
    ("uibc",                 r"UIBC"),
    ("fierro_serico",        r"Fierro s[eé]rico"),
    ("saturacion_fierro",    r"% Saturaci[oó]n Fierro"),
    # Hemograma
    ("eritrocitos",          r"Eritrocitos"),
    ("hemoglobina",          r"Hemoglobina"),
    ("hematocrito",          r"Hematocrito"),
    ("hcm",                  r"HCM"),
    ("chcm",                 r"CHCM"),
    ("rdw_cv",               r"RDW-CV"),
    ("vcm",                  r"VCM"),
    ("leucocitos",           r"Leucocitos"),
    ("plaquetas",            r"Plaquetas"),
    ("recuento_basofilos",   r"Recuento Bas[oó]filos"),
    ("recuento_eosinofilos", r"Recuento eosin[oó]filos"),
    ("recuento_neutrofilos", r"Recuento neutr[oó]filos"),
    ("recuento_linfocitos",  r"Recuento linfocitos"),
    ("recuento_monocitos",   r"Recuento monocitos"),
    ("vhs",                  r"VHS"),
    # Creatinina
    ("creatinina",           r"Creatinina"),
    ("mdrd",                 r"MDRD"),
    # Electrolitos
    ("cloro",                r"Cloro plasm[aá]tico \(Cl\)"),
    ("sodio",                r"Sodio plasm[aá]tico \(Na\)"),
    ("potasio",              r"Potasio plasm[aá]tico \(K\)"),
    # Perfil lipídico
    ("colesterol_total",     r"Colesterol Total"),
    ("colesterol_hdl",       r"Colesterol HDL"),
    ("colesterol_ldl",       r"Colesterol LDL \(calculado\)"),
    ("colesterol_vldl",      r"Colesterol VLDL"),
    ("relacion_ldl_hdl",     r"Relacion LDL/HDL"),
    ("trigliceridos",        r"Triglic[eé]ridos"),
    ("colesterol_no_hdl",    r"Colesterol no HDL"),
    # Perfil bioquímico
    ("glucosa",              r"Glucosa basal"),
    ("acido_urico",          r"[AÁ]cido [uú]rico"),
    ("urea",                 r"Urea"),
    ("bun",                  r"Nitrogeno Ureico \(BUN\)"),
    ("bilirrubina_total",    r"Bilirrubina Total \(BT\)"),
    ("alp",                  r"Fosfatasas Alcalinas \(ALP\)"),
    ("got_ast",              r"GOT/AST"),
    ("fosforo",              r"F[oó]sforo"),
    ("calcio",               r"Calcio"),
    ("ldh",                  r"Deshidrogenasa lactica \(LDH\)"),
    ("globulinas",           r"Globulinas"),
    ("albumina",             r"Alb[uú]mina"),
    ("proteinas_totales",    r"Prote[ií]nas totales"),
    ("indice_ag",            r"Indice A/G"),
    # Perfil hepático
    ("gpt_alt",              r"GPT/ALT"),
    ("ggt",                  r"GGT"),
    ("bilirrubina_directa",  r"Bilirrubina Directa"),
    ("bilirrubina_indirecta", r"Bilirrubina Indirecta"),
    ("tiempo_protrombina",   r"Tiempo de Protrombina"),
    ("inr",                  r"INR"),
]

# Column order for the CSV.
COLUMNS = (
    ["player", "rut", "fecha_muestra"]
    + [k for k, _ in SINGLE_VALUE]
    + [k for k, _ in SINGLE_QUAL]
    + ["grupo_sanguineo", "rh"]
    + [k for k, _ in TABLE_PARAMS
       if k not in {c for c, _ in SINGLE_VALUE}]  # avoid dup keys
    + ["vih"]
)

NUM_RE = r"[<>]?\s*-?\d+(?:[.,]\d+)?"


def _clean_num(raw: str) -> str:
    """Strip arrows/markers, normalise decimal comma; keep '<'/'>' prefixes."""
    raw = raw.strip().replace(",", ".")
    return raw


def extract_text(pdf: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def parse_single_value(text: str, label: str) -> str | None:
    # e.g. "   Ferritina: 25.3 ng/mL"  or "  CK Total: 372 U/L ñ"
    m = re.search(rf"^\s*{label}:\s*({NUM_RE})\b", text, re.MULTILINE)
    return _clean_num(m.group(1)) if m else None


def parse_qual(text: str, label: str) -> str | None:
    m = re.search(rf"^\s*{label}:\s*(\S+)", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_table_param(text: str, label: str) -> str | None:
    # "<param>   <value>   <unit>   ..." — first numeric token after ≥2 spaces.
    # An out-of-range value carries a leading marker glyph (pdftotext renders
    # the ↑/↓ arrow as "¬"): "Urea   ¬ 52". Skip an optional non-numeric,
    # non-space marker token before the number so those values aren't dropped.
    m = re.search(
        rf"^\s*{label}\s{{2,}}(?:[^\d\s.,<>+-]+\s+)?({NUM_RE})\b",
        text, re.MULTILINE,
    )
    return _clean_num(m.group(1)) if m else None


def parse_pdf(pdf: Path) -> dict:
    text = extract_text(pdf)
    row: dict = {"player": pdf.stem}

    # RUT + sampling date (from any "Toma de Muestra ... DD-MM-YYYY").
    m = re.search(r"^(\d{7,8}-[\dкK])\s", text, re.MULTILINE)
    row["rut"] = m.group(1) if m else None
    m = re.search(r"Toma de Muestra[^\d]*(\d{2}-\d{2}-\d{4})", text)
    if m:
        d, mth, y = m.group(1).split("-")
        row["fecha_muestra"] = f"{y}-{mth}-{d}"  # ISO
    else:
        row["fecha_muestra"] = None

    for key, label in SINGLE_VALUE:
        row[key] = parse_single_value(text, label)
    for key, label in SINGLE_QUAL:
        row[key] = parse_qual(text, label)
    for key, label in TABLE_PARAMS:
        if key in row:  # already filled by single-value (e.g. colesterol dup)
            continue
        row[key] = parse_table_param(text, label)

    # Grupo sanguíneo / Rh
    m = re.search(r"^\s*Grupo sangu[ií]neo\s{2,}(\S+)", text, re.MULTILINE)
    row["grupo_sanguineo"] = m.group(1).strip() if m else None
    m = re.search(r"^\s*Rh\s{2,}(\S+)", text, re.MULTILINE)
    row["rh"] = m.group(1).strip() if m else None

    # VIH
    m = re.search(r"Resultado\s{2,}(No Reactivo|Reactivo)", text)
    row["vih"] = m.group(1).strip() if m else None

    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    folder = Path(args.folder)
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {folder}", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else folder / "analisis_sangre.csv"
    rows = [parse_pdf(p) for p in pdfs]

    # Report any missing template-relevant fields for QA.
    critical = ["ferritina", "ck_total", "testosterona_total", "cortisol_am",
                "tsh", "hemoglobina", "hematocrito", "vitamina_b12", "vitamina_d",
                "fecha_muestra"]
    for r in rows:
        missing = [c for c in critical if not r.get(c)]
        if missing:
            print(f"  ⚠ {r['player']}: missing {missing}", file=sys.stderr)

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} rows → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
