"use client";

import React from "react";

import type { ExamTemplate } from "@/lib/types";
import styles from "./BulkIngestPlaceholder.module.css";

interface BulkIngestPlaceholderProps {
  template: ExamTemplate;
}

interface FieldMapEntry {
  column: string;
  /** Resolved template key(s) — one per segment when pattern-substituted, else a single key. */
  resolved: string[];
  reduce?: string;
}

/**
 * Renders a friendly "coming soon" surface for templates configured with
 * `input_modes: ["bulk_ingest"]`. Also previews the persisted column_mapping
 * so admins can sanity-check the file format their staff will be uploading
 * against, before the real upload UI ships.
 */
export default function BulkIngestPlaceholder({ template }: BulkIngestPlaceholderProps) {
  const mapping = (template.input_config?.column_mapping ?? {}) as Record<string, unknown>;
  const playerLookup = mapping.player_lookup as
    | { column?: string; kind?: string; source?: string }
    | undefined;
  const sessionLabel = mapping.session_label as { column?: string } | undefined;
  const segment = mapping.segment as
    | { column?: string; values?: Record<string, string> }
    | undefined;
  const fieldMap = (mapping.field_map ?? {}) as Record<
    string,
    { template_key?: string; template_key_pattern?: string; reduce?: string }
  >;

  const segmentValues = segment?.values ?? {};
  const segmentSuffixes = Object.values(segmentValues);

  const fieldEntries: FieldMapEntry[] = Object.entries(fieldMap).map(([column, spec]) => {
    if (spec.template_key_pattern) {
      const resolved = segmentSuffixes.map((s) =>
        spec.template_key_pattern!.replace("{segment}", s),
      );
      return { column, resolved };
    }
    return {
      column,
      resolved: spec.template_key ? [spec.template_key] : [],
      reduce: spec.reduce,
    };
  });

  return (
    <div className={styles.wrapper}>
      <div className={styles.banner}>
        <strong>Esta plantilla usa carga por archivo.</strong>{" "}
        El flujo de subida (selector de archivo, vista previa y confirmación) se
        construirá en la próxima iteración. Mientras tanto, esta vista resume
        cómo está mapeado el archivo para que puedas validar la configuración.
      </div>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Identificación de fila</h3>
        <ul className={styles.list}>
          <li>
            <span className={styles.dim}>Jugador:</span>{" "}
            columna <code>{playerLookup?.column ?? "—"}</code>{" "}
            <span className={styles.tag}>{playerLookup?.kind ?? "—"}</span>
            {playerLookup?.source && (
              <span className={styles.tag}>fuente: {playerLookup.source}</span>
            )}
          </li>
          {sessionLabel?.column && (
            <li>
              <span className={styles.dim}>Sesión:</span>{" "}
              columna <code>{sessionLabel.column}</code>
            </li>
          )}
          {segment?.column && (
            <li>
              <span className={styles.dim}>Segmento:</span>{" "}
              columna <code>{segment.column}</code> →{" "}
              {Object.entries(segmentValues).map(([raw, suffix]) => (
                <span key={raw} className={styles.segmentChip}>
                  <code>{raw}</code> → <code>{suffix}</code>
                </span>
              ))}
            </li>
          )}
        </ul>
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>
          Columnas de métricas ({fieldEntries.length})
        </h3>
        {fieldEntries.length === 0 ? (
          <div className={styles.empty}>
            Esta plantilla no tiene columnas mapeadas todavía.
          </div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Columna del archivo</th>
                  <th>Campo(s) de la plantilla</th>
                  <th>Reducción</th>
                </tr>
              </thead>
              <tbody>
                {fieldEntries.map(({ column, resolved, reduce }) => (
                  <tr key={column}>
                    <td>
                      <code>{column}</code>
                    </td>
                    <td>
                      {resolved.length > 0
                        ? resolved.map((k) => (
                            <code key={k} className={styles.keyChip}>
                              {k}
                            </code>
                          ))
                        : "—"}
                    </td>
                    <td>{reduce ?? <span className={styles.dim}>—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
