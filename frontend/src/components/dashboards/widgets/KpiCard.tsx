"use client";

/**
 * Un número grande con su sparkline — el encabezado de un tablero físico.
 *
 * La tarjeta **dice qué agregación está mostrando**. No es adorno: la suma de
 * la distancia de un período es volumen acumulado, el último valor es el estado
 * de hoy y el máximo es un techo alcanzado. Tres números muy distintos del
 * mismo campo, y sin la etiqueta el lector no puede saber cuál está viendo.
 *
 * La sparkline dibuja la MISMA serie que produjo el número. Si mostrara otra
 * ventana, la curva contaría una historia que el número no.
 */

import React, { useMemo } from "react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";

import { usePlayerInjuries } from "@/components/perfil/PlayerInjuries/PlayerInjuriesContext";
import { injuriesBetween } from "@/lib/injuryRanges";
import type { DashboardWidget, KpiCardPayload } from "@/lib/types";
import { INJURY_INK } from "./InjuryBands";
import styles from "./Widget.module.css";

const AGG_LABEL: Record<string, string> = {
  sum: "Total del período",
  mean: "Promedio del período",
  max: "Máximo del período",
  latest: "Último registro",
};

export default function KpiCard({ widget }: { widget: DashboardWidget }) {
  const data = widget.data as KpiCardPayload;
  const serie = useMemo(
    () => (data.sparkline ?? []).map((p, i) => ({ i, v: p.value })),
    [data.sparkline],
  );

  const vacio = data.empty || data.value === null || data.value === undefined;

  // Too small for a band: the sparkline only says, in words, that the period
  // it summarises includes an injury — a total over a layoff reads otherwise.
  const { injuries } = usePlayerInjuries();
  const puntos = data.sparkline ?? [];
  const enPeriodo = puntos.length
    ? injuriesBetween(injuries, puntos[0].recorded_at.slice(0, 10),
      puntos[puntos.length - 1].recorded_at.slice(0, 10))
    : [];
  const abierta = enPeriodo.some((l) => !l.ended_at);

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
      </header>

      {vacio ? (
        <div className={styles.empty}>
          {data.error ?? "Sin datos en el período."}
        </div>
      ) : (
        <div style={contenedor}>
          <div style={{ position: "relative", zIndex: 1 }}>
            <div style={numero}>
              {fmt(data.value as number)}
              {data.field?.unit && <span style={unidad}> {data.field.unit}</span>}
            </div>
            <div style={pie}>
              {AGG_LABEL[data.agg] ?? data.agg}
              {/* La `n` acompaña siempre: un "total del período" sobre dos
                  sesiones no se lee igual que sobre cuarenta. */}
              {typeof data.n === "number" && data.n > 0 && (
                <span style={{ color: "#98a2b3" }}> · {data.n} registro
                  {data.n === 1 ? "" : "s"}</span>
              )}
              {enPeriodo.length > 0 && (
                <span style={{ color: INJURY_INK }}>
                  {abierta ? " · en lesión"
                    : ` · ${enPeriodo.length} lesión${enPeriodo.length === 1 ? "" : "es"} en el período`}
                </span>
              )}
            </div>
          </div>

          {serie.length > 1 && (
            <div style={spark} aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={serie}
                  margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                  <Area type="monotone" dataKey="v" stroke="#dc2626"
                    strokeWidth={1.5} fill="#fecaca" fillOpacity={0.55}
                    isAnimationActive={false} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const contenedor: React.CSSProperties = {
  position: "relative", padding: "6px 4px 0", minHeight: 82,
};
const numero: React.CSSProperties = {
  fontSize: 30, fontWeight: 800, color: "#0a2240", lineHeight: 1.1,
  fontVariantNumeric: "tabular-nums",
};
const unidad: React.CSSProperties = {
  fontSize: 13, fontWeight: 600, color: "#98a2b3",
};
const pie: React.CSSProperties = {
  marginTop: 4, fontSize: 11, fontWeight: 600, color: "#667085",
};
const spark: React.CSSProperties = {
  position: "absolute", inset: "auto 0 0 0", height: 42, opacity: 0.9,
};

function fmt(v: number): string {
  return Number.isInteger(v)
    ? v.toLocaleString("es-CL")
    : v.toLocaleString("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}
