"use client";

import React, { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Smile, Meh, Frown, Pencil, UserMinus, ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

import styles from "./RosterTable.module.css";

export interface FormaBar { value: number | null; tone?: "ok" | "warn" | "crit"; date: string }
export interface RosterRow {
  id: string;
  initials: string;
  photo: string | null;
  name: string;
  position: string;
  status: string;
  status_label: string;
  readiness: number | null;
  readiness_source?: string;
  readiness_note?: string;
  wellness: number | null;
  acwr: number | null;
  acwr_meta?: AcwrMeta | null;
  forma: FormaBar[];
}
export interface AcwrMeta {
  ratio: number; acute_km: number; chronic_week_km: number; last: string | null;
}

const STATUS_DOT: Record<string, string> = {
  available: styles.dotOk,
  reintegration: styles.dotInfo,
  recovery: styles.dotWarn,
  injured: styles.dotCrit,
};

// Sort rank for the status column (worst → best).
const STATUS_ORDER: Record<string, number> = {
  injured: 0, recovery: 1, reintegration: 2, available: 3,
};

type SortDir = "asc" | "desc";
interface Column {
  key: string;
  label: string;
  align: "left" | "center" | "right";
  // value accessor for sorting; omit for non-sortable columns.
  val?: (r: RosterRow) => string | number | null;
}
const COLUMNS: Column[] = [
  { key: "name", label: "Jugador", align: "left", val: (r) => r.name.toLowerCase() },
  { key: "status", label: "Estado", align: "left", val: (r) => STATUS_ORDER[r.status] ?? 9 },
  { key: "readiness", label: "Readiness", align: "center", val: (r) => r.readiness },
  { key: "wellness", label: "Wellness", align: "center", val: (r) => r.wellness },
  { key: "acwr", label: "ACWR", align: "center", val: (r) => r.acwr },
  { key: "forma", label: "Tendencia wellness", align: "center" },
  { key: "actions", label: "Acciones", align: "right" },
];
// Numeric columns default to descending (best/highest first) on first click.
const NUMERIC = new Set(["readiness", "wellness", "acwr"]);

function alignClass(a: Column["align"]): string {
  return a === "left" ? styles.left : a === "right" ? styles.right : styles.center;
}

export default function RosterTable({
  rows, canEdit, canDeactivate, onEdit, onDeactivate,
}: {
  rows: RosterRow[];
  canEdit: boolean;
  canDeactivate: boolean;
  onEdit: (row: RosterRow) => void;
  onDeactivate: (row: RosterRow) => void;
}) {
  const showActions = canEdit || canDeactivate;
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = COLUMNS.find((c) => c.key === sort.key);
    if (!col?.val) return rows;
    const v = col.val;
    return [...rows].sort((a, b) => {
      const va = v(a), vb = v(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;   // nulls always last
      if (vb == null) return -1;
      const r = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === "asc" ? r : -r;
    });
  }, [rows, sort]);

  function toggleSort(key: string) {
    setSort((s) =>
      s?.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: NUMERIC.has(key) ? "desc" : "asc" },
    );
  }

  // Drop the actions column entirely when the user can do neither.
  const columns = showActions ? COLUMNS : COLUMNS.filter((c) => c.key !== "actions");

  if (rows.length === 0) {
    return <p className={styles.empty}>Sin jugadores para este filtro.</p>;
  }
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={alignClass(c.align)}>
                {c.val ? (
                  <button
                    type="button"
                    className={`${styles.sortBtn} ${sort?.key === c.key ? styles.sortActive : ""}`}
                    onClick={() => toggleSort(c.key)}
                  >
                    {c.label}
                    {sort?.key === c.key ? (
                      sort.dir === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />
                    ) : (
                      <ChevronsUpDown size={13} className={styles.sortIdle} />
                    )}
                  </button>
                ) : (
                  c.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id}>
              <td className={styles.left}>
                <Link href={`/perfil/${r.id}`} className={styles.player}>
                  <Avatar photo={r.photo} initials={r.initials} />
                  <span className={styles.pmeta}>
                    <span className={styles.pname}>{r.name}</span>
                    <span className={styles.ppos}>{r.position}</span>
                  </span>
                </Link>
              </td>
              <td>
                <span className={styles.status}>
                  <span className={`${styles.dot} ${STATUS_DOT[r.status] ?? styles.dotMuted}`} />
                  {r.status_label}
                </span>
              </td>
              <td className={styles.center}
                title={r.readiness_note ? `${r.readiness_note}${r.readiness_source === "agent" ? " · IA" : ""}` : undefined}>
                <Gauge value={r.readiness} />
              </td>
              <td className={styles.center}><Wellness value={r.wellness} /></td>
              <td className={styles.center}><Acwr value={r.acwr} meta={r.acwr_meta} /></td>
              <td className={styles.center}><Forma bars={r.forma} /></td>
              {showActions && (
                <td className={styles.right}>
                  <span className={styles.actions}>
                    {canEdit && (
                      <button
                        type="button"
                        className={styles.iconBtn}
                        onClick={() => onEdit(r)}
                        aria-label={`Editar ${r.name}`}
                      >
                        <Pencil size={15} aria-hidden="true" />
                      </button>
                    )}
                    {canDeactivate && (
                      <button
                        type="button"
                        className={`${styles.iconBtn} ${styles.iconDanger}`}
                        onClick={() => onDeactivate(r)}
                        aria-label={`Dar de baja a ${r.name}`}
                      >
                        <UserMinus size={15} aria-hidden="true" />
                      </button>
                    )}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── cells ──────────────────────────────────────────────────────────────

function Avatar({ photo, initials }: { photo: string | null; initials: string }) {
  const [failed, setFailed] = React.useState(false);
  if (photo && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={photo}
        alt=""
        className={styles.avatarImg}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  return <span className={styles.avatar}>{initials}</span>;
}

function Gauge({ value }: { value: number | null }) {
  if (value == null) return <span className={styles.dash}>—</span>;
  const R = 18, SW = 4, C = 2 * Math.PI * R, sweep = 0.75;
  const track = C * sweep;
  const val = C * sweep * Math.max(0, Math.min(100, value)) / 100;
  const color = value >= 75 ? "#16a34a" : value >= 60 ? "#f59e0b" : "#dc2626";
  return (
    <svg className={styles.gauge} viewBox="0 0 48 48" width="46" height="46">
      <circle cx="24" cy="24" r={R} fill="none" stroke="#eef0f4" strokeWidth={SW}
        strokeDasharray={`${track} ${C}`} strokeLinecap="round" transform="rotate(135 24 24)" />
      <circle cx="24" cy="24" r={R} fill="none" stroke={color} strokeWidth={SW}
        strokeDasharray={`${val} ${C}`} strokeLinecap="round" transform="rotate(135 24 24)" />
      <text x="24" y="24" textAnchor="middle" dominantBaseline="central"
        className={styles.gaugeNum} fill={color}>{value}</text>
    </svg>
  );
}

function Wellness({ value }: { value: number | null }) {
  if (value == null) return <span className={styles.dash}>—</span>;
  const tone = value >= 75 ? "ok" : value >= 60 ? "warn" : "crit";
  const color = tone === "ok" ? "#16a34a" : tone === "warn" ? "#f59e0b" : "#dc2626";
  const Icon = tone === "ok" ? Smile : tone === "warn" ? Meh : Frown;
  return (
    <span className={styles.wellness} style={{ color }}>
      <Icon size={18} aria-hidden="true" />
      {value}
    </span>
  );
}

function Acwr({ value, meta }: { value: number | null; meta?: AcwrMeta | null }) {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);
  if (value == null) return <span className={styles.dash}>—</span>;
  const label = meta
    ? `Agudo 7d: ${meta.acute_km} km · Crónico/sem: ${meta.chronic_week_km} km`
      + (meta.last ? ` · última carga GPS: ${formatBarDate(meta.last)}` : "")
    : `ACWR ${value.toFixed(2)}`;
  const set = (e: React.MouseEvent) => setTip({ text: label, x: e.clientX, y: e.clientY });
  return (
    <>
      <span
        className={`${styles.acwr} ${acwrTone(value)}`}
        aria-label={label}
        onMouseEnter={set}
        onMouseMove={set}
        onMouseLeave={() => setTip(null)}
      >
        {value.toFixed(2)}
      </span>
      {tip && typeof document !== "undefined" && createPortal(
        <div className={styles.formaTip} style={{ top: tip.y, left: tip.x }}>{tip.text}</div>,
        document.body,
      )}
    </>
  );
}

function Forma({ bars }: { bars: FormaBar[] }) {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);
  if (!bars.length) return <span className={styles.dash}>—</span>;

  const show = (text: string) => (e: React.MouseEvent) =>
    setTip({ text, x: e.clientX, y: e.clientY });
  const hide = () => setTip(null);

  return (
    <span className={styles.forma}>
      {bars.map((b, i) => {
        const empty = b.value == null;
        const label = empty
          ? `Sin check-in · ${formatBarDate(b.date)}`
          : `Bienestar ${b.value}/100 · ${formatBarDate(b.date)}`;
        const common = {
          "aria-label": label,
          onMouseEnter: show(label),
          onMouseMove: show(label),
          onMouseLeave: hide,
        } as const;
        return empty ? (
          <span key={i} className={styles.barEmpty} {...common}>–</span>
        ) : (
          <span
            key={i}
            className={`${styles.bar} ${barTone(b.tone ?? "")}`}
            style={{ height: `${6 + Math.round((b.value as number) / 100 * 12)}px` }}
            {...common}
          />
        );
      })}
      {tip && typeof document !== "undefined" && createPortal(
        <div className={styles.formaTip} style={{ top: tip.y, left: tip.x }}>{tip.text}</div>,
        document.body,
      )}
    </span>
  );
}

// ISO date (YYYY-MM-DD) → short local label, without timezone drift.
function formatBarDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}

function acwrTone(v: number | null): string {
  if (v == null) return styles.acwrMuted;
  if (v > 1.5) return styles.acwrCrit;
  if (v > 1.3 || v < 0.8) return styles.acwrWarn;
  return styles.acwrOk;
}
function barTone(t: string): string {
  return t === "ok" ? styles.barOk : t === "warn" ? styles.barWarn : styles.barCrit;
}
