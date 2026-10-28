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
 * Cada barra es UNA sesión. El eje la etiqueta en dos renglones —su día de
 * microciclo (`MD-3`) y la fecha— y la agrupa por el microciclo del club
 * (MICRO, "Micro 41") con un separador entre uno y otro, como el Power BI del
 * club. Sin MICRO, agrupa por semana ISO, que calcula el backend para que la
 * pantalla y el PDF agrupen igual.
 *
 * Sirve también al reporte de equipo (`team_dual_axis_bar_line`): mismo
 * payload, cada punto es la media por jugador de la sesión y trae `n`.
 */

import React, { useMemo } from "react";
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

import type { DashboardWidget, DualAxisBarLinePayload } from "@/lib/types";
import { ChartWindowNav, fullRangeDomain, useChartWindow, windowRangeLabel } from "./ChartWindow";
import { InjuryStrip, InjuryTooltipLine, injuryBandAreas, injuryDefs, useChartInjuries } from "./InjuryBands";
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
    grupo: grupoDe(p),
    n: p.n,
    bars: p.bars,
    line: p.line,
  })), [puntos]);

  // Dónde empieza cada microciclo (o semana): un separador y su nombre.
  const cortes = useMemo(() => filas.flatMap((f, i) =>
    i === 0 || f.grupo !== filas[i - 1].grupo ? [{ x: i - 0.5, label: f.grupo }] : []),
  [filas]);

  const window = useChartWindow(filas);

  const days = useMemo(() => filas.map((f) => f.recorded_at.slice(0, 10)), [filas]);
  const lesiones = useChartInjuries(days);
  const fullWidth = (widget.column_span ?? 12) >= 12;

  // Cada eje con su propio dominio sobre TODA la historia: es el punto del
  // gráfico, y además mantiene el marco quieto mientras se panea.
  // Las barras arrancan en 0: una barra que nace en 2.000 hace que 4.000 se
  // vea como la mitad de 6.000. Ninguno de los dos ejes baja de 0 si los
  // datos no lo hacen (un "−100 m de HSR" en el eje no significa nada).
  const domBarras = useMemo(
    () => desdeCero(filas.map((f) => f.bars), true), [filas]);
  const domLinea = useMemo(
    () => desdeCero(filas.map((f) => f.line), false), [filas]);

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
            {injuryDefs(lesiones.patternId)}
            {injuryBandAreas(lesiones.placed, {
              patternId: lesiones.patternId, xDomain: window.xDomain, labels: fullWidth,
              yAxisId: "barras",
            })}
            <XAxis
              dataKey="idx" type="number" domain={window.xDomain}
              ticks={window.ticks}
              allowDataOverflow height={44}
              tick={(props: TickProps) => <DosRenglones {...props} filas={filas} />}
              stroke="#d1d5db" />
            {cortes.map((c) => (
              <ReferenceLine key={c.x} x={c.x} yAxisId="barras" ifOverflow="hidden"
                stroke="#94a3b8" strokeDasharray="4 3"
                label={{ value: c.label, position: "insideTopLeft", fontSize: 10,
                  fontWeight: 700, fill: "#475467" }} />
            ))}
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
                    {f.grupo}
                    {typeof f.n === "number" && ` · media de ${f.n} jugador${f.n === 1 ? "" : "es"}`}
                  </div>
                  <InjuryTooltipLine light text={lesiones.contextFor(f.recorded_at.slice(0, 10))} />
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
      <InjuryStrip chart={lesiones} compact={!fullWidth}
        fromDay={window.visible[0]?.recorded_at.slice(0, 10)}
        toDay={window.visible[window.visible.length - 1]?.recorded_at.slice(0, 10)} />
    </div>
  );
}

const tooltipStyle: React.CSSProperties = {
  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8,
  boxShadow: "0 4px 12px rgba(16,24,40,.1)", padding: "8px 10px",
  fontSize: 12, color: "#344054", display: "flex", flexDirection: "column",
  gap: 2,
};

type Punto = DualAxisBarLinePayload["points"][number];

function desdeCero(
  values: ReadonlyArray<number | null | undefined>, barras: boolean,
): [number, number] | undefined {
  const dom = fullRangeDomain(values);
  if (!dom) return dom;
  const datos = values.filter((v): v is number => typeof v === "number");
  const sinNegativos = datos.every((v) => v >= 0);
  if (barras && sinNegativos) return [0, dom[1]];
  return [sinNegativos ? Math.max(0, dom[0]) : dom[0], dom[1]];
}

/** El grupo del eje: el microciclo del club, o la semana si no lo hay. */
function grupoDe(p: Punto): string {
  if (typeof p.micro === "number") return `Micro ${p.micro}`;
  const semana = p.week?.split("-W")[1];
  return semana ? `Semana ${Number(semana)}` : "";
}

interface TickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value: number };
}

/** Tick de dos renglones: el día de microciclo y, debajo, la fecha. */
function DosRenglones({ x, y, payload, filas }: TickProps & {
  filas: { md_label: string | null; recorded_at: string }[];
}) {
  const f = payload ? filas[payload.value] : undefined;
  if (!f) return null;
  const [, m, d] = f.recorded_at.slice(0, 10).split("-");
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={11} textAnchor="middle" fontSize={10} fontWeight={700} fill="#344054">
        {f.md_label ?? "—"}
      </text>
      <text dy={24} textAnchor="middle" fontSize={9} fill="#98a2b3">
        {d}/{m}
      </text>
    </g>
  );
}

function etiqueta(m: DualAxisBarLinePayload["bars"]): string {
  if (!m) return "";
  return `${m.label}${m.unit ? ` (${m.unit})` : ""}`;
}
