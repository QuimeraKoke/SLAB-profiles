"use client";

import React, { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  TeamDistributionBandCount,
  TeamDistributionPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamDistribution.module.css";

const DEFAULT_BAR_COLOR = "#6d28d9";

interface Props {
  widget: TeamReportWidget;
}

export default function TeamDistribution({ widget }: Props) {
  const data = widget.data as TeamDistributionPayload;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const unit = data.field?.unit ? ` ${data.field.unit}` : "";

  // Un bin por banda: el eje X deja de ser numérico y pasa a ser ORDINAL.
  // Las barras quedan de igual ancho aunque los rangos no lo sean (en 1RM
  // "Excelente" mide 29 kg y "Bueno" 14) — deja de ser un histograma y pasa
  // a ser un conteo por categoría, que es como el cuerpo técnico lo lee.
  const porBandas = data.binning === "bands";

  const chartData = useMemo(
    () =>
      (data.bins ?? []).map((b, i) => ({
        index: i,
        label: porBandas
          ? (b.band_label || "—")
          : rangoMedio(b.low, b.high),
        rangeLabel: rangoTexto(b.low, b.high),
        count: b.count,
        color: b.color ?? DEFAULT_BAR_COLOR,
        bandLabel: b.band_label ?? null,
      })),
    [data.bins, porBandas],
  );

  // Con bines por banda los chips repetirían exactamente lo que ya dicen las
  // barras, así que sobran.
  const bandCounts = porBandas ? null : (data.band_counts ?? null);

  if (data.empty || (data.bins ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} data={data} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  const height = widget.chart_height ?? 240;
  const hoveredBin =
    hoverIndex !== null && data.bins ? data.bins[hoverIndex] : null;

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <div className={styles.statsRow}>
        <Stat label="N" value={data.stats.n} format="int" />
        <Stat label="Media" value={data.stats.mean} unit={unit} />
        <Stat label="Mediana" value={data.stats.median} unit={unit} />
        <Stat label="Min" value={data.stats.min} unit={unit} />
        <Stat label="Max" value={data.stats.max} unit={unit} />
      </div>

      {porBandas ? (
        <BandLegendRow bins={data.bins ?? []} unit={unit} />
      ) : (
        bandCounts && bandCounts.length > 0 && (
          <BandCountsRow counts={bandCounts} unit={unit} />
        )
      )}

      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <BarChart
            data={chartData}
            margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
            /* El índice sale del CHART, no de cada barra. `onMouseEnter` del
               `Bar` sólo dispara sobre el rectángulo, y una banda con 0
               jugadores tiene altura 0: nunca lo recibía, así que el índice se
               quedaba pegado en el último bin hovereado y el detalle de abajo
               listaba jugadores de OTRA banda. Acá se lee el mismo
               `activeTooltipIndex` que alimenta el tooltip, así que los dos no
               pueden discrepar. */
            onMouseMove={(state) => {
              const i = state?.activeTooltipIndex;
              setHoverIndex(
                state?.isTooltipActive && typeof i === "number" ? i : null,
              );
            }}
            onMouseLeave={() => setHoverIndex(null)}
          >
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            {/* Con bines por banda las etiquetas las pone la leyenda de arriba,
                que además dice el rango — cosa que el eje no puede. Inclinadas
                acá abajo se pisaban entre ellas y se comían 58px de un gráfico
                de 240: la barra queda identificada por su color y por su
                posición, que es el mismo orden de la leyenda. */}
            <XAxis
              dataKey="label"
              tick={porBandas ? false : { fill: "#6b7280", fontSize: 11 }}
              height={porBandas ? 8 : 30}
            />
            <YAxis allowDecimals={false} tick={{ fill: "#6b7280", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0]?.payload as {
                  rangeLabel: string;
                  count: number;
                  bandLabel: string | null;
                };
                return (
                  <div className={styles.tooltip}>
                    {point.bandLabel && (
                      <span className={styles.tooltipBand}>
                        Banda {point.bandLabel}
                      </span>
                    )}
                    <span className={styles.tooltipRange}>
                      {point.rangeLabel}{unit}
                    </span>
                    <span className={styles.tooltipCount}>
                      {point.count} jugador{point.count === 1 ? "" : "es"}
                    </span>
                  </div>
                );
              }}
            />
            <Bar
              dataKey="count"
              fill={DEFAULT_BAR_COLOR}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            >
              {chartData.map((entry) => (
                <Cell key={entry.index} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {hoveredBin && (
        <div className={styles.binDetail}>
          <span className={styles.binDetailLabel}>
            {porBandas && hoveredBin.band_label
              ? hoveredBin.band_label
              : rangoTexto(hoveredBin.low, hoveredBin.high)}{unit}:
          </span>
          <span className={styles.binDetailPlayers}>
            {/* Vacío se dice, no se calla: si la fila desapareciera, el lector
                no sabría si la banda no tiene a nadie o si el detalle se
                rompió — que es justamente la duda que trajo este bug. */}
            {hoveredBin.players.length > 0
              ? hoveredBin.players
                  .map((p) => `${p.name} (${p.value.toFixed(1)})`)
                  .join(", ")
              : "sin jugadores"}
          </span>
        </div>
      )}
    </div>
  );
}

/** Punto medio del bin, para la etiqueta del eje numérico. */
function rangoMedio(low: number | null, high: number | null): string {
  if (low === null || high === null) return "—";
  return ((low + high) / 2).toFixed(1);
}

/** Texto del rango de un bin. Un extremo en `null` es una banda abierta:
 *  `≤ 36.1` o `≥ 50.4`, no un número inventado. */
function rangoTexto(low: number | null, high: number | null): string {
  const f = (n: number) => n.toFixed(1);
  if (low === null && high === null) return "";
  if (low === null) return `≤ ${f(high as number)}`;
  if (high === null) return `≥ ${f(low)}`;
  return `${f(low)} – ${f(high)}`;
}

/** Distributions with fewer than this many players in the filtered roster
 *  are flagged in the UI — too few samples to be a meaningful reference. */
const LIMITED_REFERENCE_THRESHOLD = 5;

function Header({
  widget,
  data,
}: {
  widget: TeamReportWidget;
  data: TeamDistributionPayload;
}) {
  const rosterSize = data.roster_size;
  const limitedReference =
    typeof rosterSize === "number"
    && rosterSize > 0
    && rosterSize < LIMITED_REFERENCE_THRESHOLD;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        {limitedReference && (
          <p className={styles.limitedBadge}>
            Con {rosterSize} jugador{rosterSize === 1 ? "" : "es"} — referencia limitada
          </p>
        )}
      </div>
      {data.field && (
        <span className={styles.fieldTag}>
          {data.field.label}
          {data.field.unit ? ` · ${data.field.unit}` : ""}
        </span>
      )}
    </header>
  );
}

interface StatProps {
  label: string;
  value?: number;
  unit?: string;
  format?: "int";
}

function Stat({ label, value, unit, format }: StatProps) {
  if (value === undefined || value === null) return null;
  const display =
    format === "int" ? String(value) : value.toFixed(2);
  return (
    <div className={styles.statItem}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>
        {display}{format === "int" ? "" : unit ?? ""}
      </span>
    </div>
  );
}

/** Clave de colores para el modo `binning: "bands"`.
 *
 *  Va en el MISMO orden que las barras (peor → mejor), así que la posición ya
 *  mapea banda ↔ barra sin que el lector tenga que comparar tres verdes. No
 *  repite el conteo a propósito: eso lo dice la altura de la barra, y lo que
 *  falta —y el eje no puede dar— es el rango numérico de cada banda. */
function BandLegendRow({
  bins,
  unit,
}: {
  bins: TeamDistributionPayload["bins"];
  unit: string;
}) {
  return (
    <div className={styles.bandCountsRow} aria-label="Bandas de referencia">
      {bins.map((b, idx) => {
        const rango = rangoTexto(b.low, b.high);
        return (
          <div key={`${b.band_label ?? idx}-${idx}`} className={styles.bandChip}>
            <span
              className={styles.bandSwatch}
              style={{ background: b.color ?? DEFAULT_BAR_COLOR }}
            />
            <div className={styles.bandChipText}>
              <span className={styles.bandLabel}>{b.band_label || "—"}</span>
              {rango && (
                <span className={styles.bandRange}>
                  {rango}{unit}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface BandCountsRowProps {
  counts: TeamDistributionBandCount[];
  unit: string;
}

function BandCountsRow({ counts, unit }: BandCountsRowProps) {
  return (
    <div className={styles.bandCountsRow} aria-label="Conteo por banda clínica">
      {counts.map((band, idx) => {
        const range = bandRangeText(band, unit);
        return (
          <div key={`${band.label}-${idx}`} className={styles.bandChip}>
            <span
              className={styles.bandSwatch}
              style={{ background: band.color ?? DEFAULT_BAR_COLOR }}
            />
            <div className={styles.bandChipText}>
              <span className={styles.bandLabel}>{band.label}</span>
              {range && <span className={styles.bandRange}>{range}</span>}
            </div>
            <span className={styles.bandCount}>{band.count}</span>
          </div>
        );
      })}
    </div>
  );
}

function bandRangeText(band: TeamDistributionBandCount, unit: string): string {
  const u = unit.trim();
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  if (band.min === null && band.max !== null) return `≤ ${fmt(band.max)}${u ? " " + u : ""}`;
  if (band.min !== null && band.max === null) return `≥ ${fmt(band.min)}${u ? " " + u : ""}`;
  if (band.min !== null && band.max !== null) return `${fmt(band.min)} – ${fmt(band.max)}${u ? " " + u : ""}`;
  return "";
}
