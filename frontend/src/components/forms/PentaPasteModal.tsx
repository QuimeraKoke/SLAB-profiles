"use client";

import React, { useMemo, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import type { ExamField } from "@/lib/types";
import { PENTA_PASTE_ROWS } from "./pentaPasteMap";
import styles from "./PentaPasteModal.module.css";

/** Accent/case/punctuation-insensitive key for label comparison. */
function norm(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

/** Parse an es-CL number: comma is the decimal separator, dot the (optional)
 *  thousands separator. "83,200" -> 83.2 · "1.234,5" -> 1234.5 · "9,000" -> 9. */
function parseNum(raw: string): number | null {
  let s = (raw ?? "").trim().replace(/\s/g, "");
  if (!s) return null;
  if (s.includes(",") && s.includes(".")) s = s.replace(/\./g, "").replace(",", ".");
  else if (s.includes(",")) s = s.replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

type Status = "ok" | "mismatch" | "byorder" | "empty";

interface PreviewRow {
  idx: number;
  key: string;
  targetLabel: string; // the template field's own label
  pastedLabel: string; // col-1 text the user pasted (may be "")
  value: number | null;
  status: Status;
}

/** Split each pasted line into {label, valueStr}. Excel puts a tab between the
 *  two columns; a single column is a value if it parses numeric, else a label. */
function splitLines(raw: string): { label: string; valueStr: string }[] {
  return raw
    .split(/\r?\n/)
    .map((l) => l.replace(/\r$/, ""))
    .filter((l) => l.trim() !== "")
    .map((line) => {
      const cols = line.split("\t");
      if (cols.length >= 2) {
        return { label: cols[0].trim(), valueStr: cols[cols.length - 1].trim() };
      }
      const single = cols[0].trim();
      return parseNum(single) != null
        ? { label: "", valueStr: single }
        : { label: single, valueStr: "" };
    });
}

function buildPreview(raw: string, fieldLabels: Record<string, string>): PreviewRow[] {
  const parsed = splitLines(raw);
  return PENTA_PASTE_ROWS.map((row, i) => {
    const p = parsed[i];
    const value = p ? parseNum(p.valueStr) : null;
    const pastedLabel = p?.label ?? "";
    let status: Status;
    if (value == null) status = "empty";
    else if (!pastedLabel) status = "byorder";
    else status = norm(pastedLabel) === norm(row.label) ? "ok" : "mismatch";
    return {
      idx: i,
      key: row.key,
      targetLabel: fieldLabels[row.key] ?? row.label,
      pastedLabel,
      value,
      status,
    };
  });
}

export default function PentaPasteModal({
  open,
  onClose,
  fields,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  fields: ExamField[];
  onApply: (values: Record<string, number>) => void;
}) {
  const [raw, setRaw] = useState("");

  const fieldLabels = useMemo(() => {
    const m: Record<string, string> = {};
    for (const f of fields) m[f.key] = f.label ?? f.key;
    return m;
  }, [fields]);

  const rows = useMemo(
    () => (raw.trim() ? buildPreview(raw, fieldLabels) : []),
    [raw, fieldLabels],
  );
  const filled = rows.filter((r) => r.value != null);
  const mismatches = rows.filter((r) => r.status === "mismatch");

  function close() {
    setRaw("");
    onClose();
  }
  function apply() {
    const out: Record<string, number> = {};
    for (const r of rows) if (r.value != null) out[r.key] = r.value;
    onApply(out);
    close();
  }

  return (
    <Modal open={open} title="Pegar desde Excel" onClose={close}>
      <div className={styles.wrap}>
        <p className={styles.help}>
          Copiá las medidas desde el informe de Excel — la columna de valores, o
          ambas columnas para validar los nombres — y pegalas acá. Se asignan por
          el orden del informe; revisá la vista previa antes de rellenar.
        </p>
        <textarea
          className={styles.textarea}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={6}
          placeholder="Pegá acá las celdas copiadas (Ctrl/Cmd+V)…"
          aria-label="Contenido pegado desde Excel"
        />

        {rows.length > 0 && (
          <>
            <div className={styles.summary}>
              <strong>{filled.length}</strong> de {PENTA_PASTE_ROWS.length} campos con
              valor
              {mismatches.length > 0 && (
                <span className={styles.warn}>
                  {" · "}
                  {mismatches.length} nombre{mismatches.length === 1 ? "" : "s"} no
                  coincide{mismatches.length === 1 ? "" : "n"} — revisá el orden
                </span>
              )}
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Campo</th>
                    <th>Valor</th>
                    <th>Pegado</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.idx}
                      className={
                        r.status === "mismatch"
                          ? styles.rowWarn
                          : r.status === "empty"
                            ? styles.rowEmpty
                            : ""
                      }
                    >
                      <td>{r.targetLabel}</td>
                      <td className={styles.val}>{r.value != null ? r.value : "—"}</td>
                      <td className={styles.pasted}>
                        {r.status === "mismatch" && <span aria-hidden="true">⚠ </span>}
                        {r.pastedLabel ||
                          (r.status === "byorder" ? (
                            <span className={styles.byorder}>(por orden)</span>
                          ) : (
                            ""
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        <div className={styles.actions}>
          <button type="button" className={styles.ghost} onClick={close}>
            Cancelar
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={apply}
            disabled={filled.length === 0}
          >
            Rellenar {filled.length} campo{filled.length === 1 ? "" : "s"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
