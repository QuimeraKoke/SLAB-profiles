"use client";

/**
 * Dos métricas, dos escalas, un dibujo: barras al eje izquierdo, línea al
 * derecho.
 *
 * Existe porque el par que el cuerpo físico lee junto —distancia total contra
 * HSR, contra metros/minuto, contra duración— no entra en `multi_line`: 6.400 m
 * de distancia y 280 m de HSR comparten gráfico pero no escala, y forzados a un
 * solo eje el HSR queda aplastado contra el piso, indistinguible de cero.
 *
 * Cada barra es UNA sesión, etiquetada con su día de microciclo (`MD-3`) y
 * agrupada por semana. La semana la calcula el backend para que la pantalla y
 * el PDF agrupen igual sin duplicar la regla.
 */

import React, { useMemo } from "react";
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

import type { DashboardWidget, DualAxisBarLinePayload } from "@/lib/types";
import { ChartWindowNav, fullRangeDomain, useChartWindow, windowRangeLabel } from "./ChartWindow";
import styles from "./Widget.module.css";

const COLOR_BARRAS = "#2563eb";
const COLOR_LINEA = "#1e3a8a";

export default function DualAxisBarLine({ widget }: { widget: DashboardWidget }) {
  const data = widget.data as DualAxisBarLinePayload;
  const puntos = useMemo(() => data.points ?? [], [data.points]);

  const filas = useMemo(() => puntos.map((p, i) => ({
    idx: i,
    // La etiqueta es el día de microciclo; la fecha queda para el tooltip.
    // Sin `md_label` (sesión a más de una semana de cualquier partido) se
    // muestra el día, que es más útil que un hueco.
    label: p.md_label || p.recorded_at.slice(5, 10),
    recorded_at: p.recorded_at,
    md_label: p.md_label,
    week: p.week,
    bars: p.bars,
    line: p.line,
  })), [puntos]);

  const window = useChartWindow(filas);

  // Cada eje con su propio dominio sobre TODA la historia: es el punto del
  // gráfico, y además mantiene el marco quieto mientras se panea.
  const domBarras = useMemo(
    () => fullRangeDomain(filas.map((f) => f.bars)), [filas]);
  const domLinea = useMemo(
    () => fullRangeDomain(filas.map((f) => f.line)), [filas]);

  if (data.empty || filas.length === 0) {
    return (
      <div className={styles.widget}>
        <header className={styles.header}>
          <h4 className={styles.title}>{widget.title}</h4>
        </header>
        <div className={styles.empty}>
          {data.error ?? "Sin datos para este gráfico."}
        </div>
      </div>
    );
  }

  const tituloBarras = etiqueta(data.bars);
  const tituloLinea = etiqueta(data.line);

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </header>

      <ChartWindowNav window={window} label={windowRangeLabel(window.visible)} />

      <div className={styles.chartArea} style={{ height: widget.chart_height ?? 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={window.data}
            margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="idx" type="number" domain={window.xDomain}
              ticks={window.ticks}
              tickFormatter={(v) => filas[v as number]?.label ?? ""}
              allowDataOverflow height={40}
              tick={{ fontSize: 10, fill: "#6b7280" }} stroke="#d1d5db" />
            <YAxis yAxisId="barras" width={64}
              domain={domBarras ?? ["auto", "auto"]}
              tick={{ fontSize: 11, fill: "#6b7280" }} stroke="#d1d5db"
              label={{
                value: tituloBarras, angle: -90, position: "insideLeft", offset: 8,
                style: { textAnchor: "middle", fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }} />
            <YAxis yAxisId="linea" orientation="right" width={64}
              domain={domLinea ?? ["auto", "auto"]}
              tick={{ fontSize: 11, fill: COLOR_LINEA }} stroke="#c7d2fe"
              label={{
                value: tituloLinea, angle: 90, position: "insideRight", offset: 8,
                style: { textAnchor: "middle", fill: COLOR_LINEA, fontSize: 11, fontWeight: 600 },
              }} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const f = payload[0]?.payload as (typeof filas)[number];
              return (
                <div className={styles.tooltip ?? undefined}
                  style={tooltipStyle}>
                  <div style={{ fontWeight: 700 }}>
                    {f.recorded_at.slice(0, 10)}
                    {f.md_label && (
                      <span style={{ color: "#6b7280", fontWeight: 600 }}>
                        {" · "}{f.md_label}
                      </span>
                    )}
                  </div>
                  <div style={{ color: "#6b7280", fontSize: 11 }}>
                    Semana {f.week}
                  </div>
                  <div style={{ color: COLOR_BARRAS }}>
                    {tituloBarras}: {f.bars ?? "sin dato"}
                  </div>
                  <div style={{ color: COLOR_LINEA }}>
                    {tituloLinea}: {f.line ?? "sin dato"}
                  </div>
                </div>
              );
            }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8} />
            <Bar yAxisId="barras" dataKey="bars" name={tituloBarras}
              fill={COLOR_BARRAS} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Line yAxisId="linea" type="monotone" dataKey="line" name={tituloLinea}
              stroke={COLOR_LINEA} strokeWidth={2} dot={{ r: 2 }}
              isAnimationActive={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const tooltipStyle: React.CSSProperties = {
  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8,
  boxShadow: "0 4px 12px rgba(16,24,40,.1)", padding: "8px 10px",
  fontSize: 12, color: "#344054", display: "flex", flexDirection: "column",
  gap: 2,
};

function etiqueta(m: DualAxisBarLinePayload["bars"]): string {
  if (!m) return "";
  return `${m.label}${m.unit ? ` (${m.unit})` : ""}`;
}
