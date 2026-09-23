"use client";

/**
 * Bitácora: una fila por sesión, columnas = los campos configurados.
 *
 * `ComparisonTable` no sirve para esto — está transpuesto (filas = métricas,
 * columnas = últimas tomas). Eso funciona para seguir la evolución de pocos
 * campos; acá lo que importa es recorrer el registro de actividad, y cada fila
 * es un entrenamiento.
 *
 * Más reciente arriba: una bitácora se lee desde lo último hacia atrás.
 */

import React from "react";

import type { DashboardWidget, SessionLogPayload } from "@/lib/types";
import styles from "./Widget.module.css";

/** Filas visibles antes de que la tabla scrollee sola. Sin tope, un jugador
 *  con 150 sesiones empuja todo lo que va debajo fuera de la pantalla. */
const ALTO_MAX = 360;

export default function SessionLog({ widget }: { widget: DashboardWidget }) {
  const data = widget.data as SessionLogPayload;
  const filas = data.rows ?? [];
  const columnas = data.columns ?? [];

  if (data.empty || filas.length === 0) {
    return (
      <div className={styles.widget}>
        <header className={styles.header}>
          <h4 className={styles.title}>{widget.title}</h4>
        </header>
        <div className={styles.empty}>
          {data.error ?? "Sin sesiones en el período."}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </header>

      <div style={{ maxHeight: ALTO_MAX, overflow: "auto" }}>
        <table style={tabla}>
          <thead>
            <tr>
              <th style={{ ...th, ...izq }}>Fecha</th>
              <th style={{ ...th, ...izq }}>MD</th>
              {columnas.map((c) => (
                <th key={c.key} style={th}>
                  {c.label}
                  {c.unit && <span style={unidad}> ({c.unit})</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.result_id}>
                <td style={{ ...td, ...izq }}>{f.recorded_at.slice(0, 10)}</td>
                <td style={{ ...td, ...izq }}>
                  {/* Sin etiqueta = sesión a más de una semana de cualquier
                      partido. Un guión lo dice; un vacío parecería un error. */}
                  {f.md_label ?? <span style={nulo}>—</span>}
                </td>
                {columnas.map((c) => {
                  const v = f.values?.[c.key];
                  return (
                    <td key={c.key} style={td}>
                      {v === null || v === undefined
                        ? <span style={nulo}>—</span>
                        : fmt(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const tabla: React.CSSProperties = {
  width: "100%", borderCollapse: "collapse", fontSize: 12.5,
};
const th: React.CSSProperties = {
  position: "sticky", top: 0, background: "#f9fafb", zIndex: 1,
  padding: "7px 10px", textAlign: "right", fontSize: 11, fontWeight: 700,
  color: "#667085", textTransform: "uppercase", letterSpacing: "0.03em",
  borderBottom: "1px solid #e8eaf0", whiteSpace: "nowrap",
};
const td: React.CSSProperties = {
  padding: "6px 10px", textAlign: "right", color: "#344054",
  borderBottom: "1px solid #f2f4f7", fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};
const izq: React.CSSProperties = { textAlign: "left" };
const unidad: React.CSSProperties = { fontWeight: 500, color: "#98a2b3" };
const nulo: React.CSSProperties = { color: "#c4cad3" };

function fmt(v: number): string {
  return Number.isInteger(v)
    ? v.toLocaleString("es-CL")
    : v.toLocaleString("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}
