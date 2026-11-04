"use client";

/**
 * One microcycle's plan: its days (a friendly can sit mid-week and cut the
 * microcycle), the match reference per position, the % per day and metric the
 * staff enters, and the target that results (reference × %). PLAN_CONTROL_CARGA.md §4.0.
 *
 * Targets are recomputed here as the % are typed, so the PF sees the metres
 * before saving; MD labels are recomputed by the server on save (they depend on
 * which days are matches).
 */

import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";
import {
  DAY_KIND_LABEL, type DayKind, fmt, isMatch, kindLabel, type McDetail, parsePct,
  refValue, shortDate, STATUS_LABEL,
} from "@/lib/loadControl";

import styles from "./loadControl.module.css";

interface DraftDay { date: string; weekday: string; md_label: string; kind: DayKind; pct: Record<string, string> }
interface Draft { kind: string; days: DraftDay[] }

function toDraft(d: McDetail): Draft {
  return {
    kind: d.kind,
    days: d.days.map((day) => ({
      date: day.date, weekday: day.weekday, md_label: day.md_label, kind: day.kind,
      pct: Object.fromEntries(d.metrics.map((m) => {
        const v = day.targets_pct?.[m.key];
        return [m.key, v == null ? "" : String(v)];
      })),
    })),
  };
}

const cellId = (date: string, metric: string) => `pct-${date}-${metric}`;

/** "vs COBRELOA", linked to the match's page when SLAB has it. */
function MatchLink({ eventId, opponent, className }: { eventId?: string | null; opponent?: string | null; className?: string }) {
  if (!eventId && !opponent) return null;
  const text = opponent ? `vs ${opponent}` : "Ver partido";
  return eventId
    ? <Link href={`/partidos/${eventId}`} className={className}>{text}</Link>
    : <span className={className}>{text}</span>;
}

interface Props {
  microcycleId: string;
  canEdit: boolean;
  onChanged: () => void;
}

export default function PlanEditor({ microcycleId, canEdit, onChanged }: Props) {
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [detail, setDetail] = useState<McDetail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [pos, setPos] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  const show = useCallback((d: McDetail) => {
    setDetail(d);
    setDraft(toDraft(d));
    setPos((p) => (p && d.groups.some((g) => g.code === p) ? p : d.groups[0]?.code ?? null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<McDetail>(`/load-control/microcycles/${microcycleId}`)
      .then((d) => { if (!cancelled) { show(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la semana."); });
    return () => { cancelled = true; };
  }, [microcycleId, show]);

  const editable = canEdit && detail?.status !== "closed";
  const metrics = useMemo(() => detail?.metrics ?? [], [detail]);

  const invalid = useMemo(() => {
    const out: string[] = [];
    for (const day of draft?.days ?? []) {
      if (day.kind !== "training") continue;
      for (const m of metrics) if (!parsePct(day.pct[m.key] ?? "").valid) out.push(cellId(day.date, m.key));
    }
    return out;
  }, [draft, metrics]);

  const dirty = useMemo(() => !!detail && !!draft && JSON.stringify(toDraft(detail)) !== JSON.stringify(draft),
    [detail, draft]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!detail || !draft) return <p className={styles.muted}>Cargando semana…</p>;

  const ref = detail.reference;
  const changed = detail.changed_vs_copy;
  const serverDay = (date: string) => detail.days.find((d) => d.date === date);

  const setDay = (date: string, patch: Partial<DraftDay>) =>
    setDraft((d) => d && ({ ...d, days: d.days.map((x) => (x.date === date ? { ...x, ...patch } : x)) }));
  const setPct = (date: string, metric: string, value: string) =>
    setDraft((d) => d && ({ ...d, days: d.days.map((x) => (x.date === date ? { ...x, pct: { ...x.pct, [metric]: value } } : x)) }));

  const target = (day: DraftDay, metric: string): number | null => {
    const base = refValue(pos ? ref.groups[pos] : undefined, metric);
    if (base == null || day.kind === "rest") return null;
    if (isMatch(day.kind)) return base;
    const p = parsePct(day.pct[metric] ?? "");
    return p.value == null ? null : (base * p.value) / 100;
  };

  const trainingTotals = metrics.map((m) => draft.days
    .filter((d) => d.kind === "training")
    .reduce((acc, d) => acc + (target(d, m.key) ?? 0), 0));

  const save = async () => {
    setSaveError(null);
    if (invalid.length) {
      setSaveError("Hay porcentajes inválidos: deben ser números entre 0 y 200.");
      document.getElementById(invalid[0])?.focus();
      return;
    }
    setSaving(true);
    try {
      const body = {
        kind: draft.kind,
        days: draft.days.map((d) => ({
          date: d.date, kind: d.kind,
          targets_pct: d.kind === "training"
            ? Object.fromEntries(metrics.map((m) => [m.key, parsePct(d.pct[m.key] ?? "").value]))
            : {},
        })),
      };
      const out = await api<McDetail>(`/load-control/microcycles/${detail.id}`, {
        method: "PUT", body: JSON.stringify(body),
      });
      show(out);
      toast.success(`Semana ${out.number} guardada.`);
      onChanged();
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "No se pudo guardar el plan.");
      errorRef.current?.focus();
    } finally {
      setSaving(false);
    }
  };

  const open = async () => {
    const ok = await confirm({
      title: `¿Publicar la semana ${detail.number}?`,
      message: "Al publicar, la referencia de partido queda fija con los datos de hoy: los partidos que se jueguen después no la cambian. Los % se pueden seguir editando. No se puede volver a borrador.",
      confirmLabel: "Publicar",
    });
    if (!ok) return;
    try {
      const out = await api<McDetail>(`/load-control/microcycles/${detail.id}/open`, { method: "POST" });
      show(out);
      toast.success(`Semana ${out.number} publicada: la referencia quedó fija.`);
      onChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo publicar la semana.");
    }
  };

  const fallbackGroups = Object.entries(ref.groups).filter(([, g]) => g.fallback).map(([c]) => c);

  return (
    <>
      <section className={styles.card} aria-labelledby="lc-dias">
        <div className={styles.cardHead}>
          <h2 id="lc-dias" className={styles.h2}>
            Semana {detail.number} · {shortDate(detail.start_date)} – {shortDate(detail.end_date)}
          </h2>
          <span className={`${styles.badge} ${styles[`badge_${detail.status}`]}`}>{STATUS_LABEL[detail.status]}</span>
        </div>
        <p className={styles.muted}>
          Si el día ya tiene GPS, la etiqueta es la que escribió el club; si no, se calcula desde los partidos de la semana (un amistoso también corta el microciclo) y se actualiza al guardar.
        </p>
        <div className={styles.days}>
          {draft.days.map((d) => {
            const moved = serverDay(d.date)?.kind !== d.kind;
            return (
              <div key={d.date} className={`${styles.day} ${styles[`day_${d.kind}`] ?? ""}`}>
                <span className={styles.dayDate}>{d.weekday} {shortDate(d.date)}</span>
                <span className={styles.dayLabel}>{moved ? "…" : (d.md_label || "—")}</span>
                {!moved && isMatch(d.kind) && (
                  <MatchLink eventId={serverDay(d.date)?.event_id} opponent={serverDay(d.date)?.opponent}
                    className={styles.matchLink} />
                )}
                {!moved && d.md_label && (
                  <span className={styles.dayDate}>
                    {serverDay(d.date)?.md_label_source === "club" ? "Planilla del club" : "Calculada"}
                  </span>
                )}
                <label className={styles.dayDate}>
                  <span className={styles.srOnly}>Tipo de día {d.weekday} {shortDate(d.date)}</span>
                  <select className={styles.daySelect} value={d.kind} disabled={!editable}
                    onChange={(e) => setDay(d.date, { kind: e.target.value as DayKind })}>
                    {(Object.keys(DAY_KIND_LABEL) as DayKind[]).map((k) => (
                      <option key={k} value={k}>{DAY_KIND_LABEL[k]}</option>
                    ))}
                  </select>
                </label>
              </div>
            );
          })}
        </div>
        <label className={styles.label} style={{ maxWidth: 220 }}>
          Tipo de semana
          <select className={styles.select} value={draft.kind} disabled={!editable}
            onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
            <option value="">Sin tipo</option>
            {detail.kinds.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
          </select>
        </label>
      </section>

      <section className={styles.card} aria-labelledby="lc-ref">
        <div className={styles.cardHead}>
          <h2 id="lc-ref" className={styles.h2}>Referencia de partido (100%)</h2>
          <span className={styles.muted}>
            {ref.preview ? "Vista previa: queda fija al publicar la semana"
              : `Fija desde el ${detail.frozen_at ? shortDate(detail.frozen_at.slice(0, 10)) : ""}`}
          </span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Posición</th>
                {metrics.map((m) => <th key={m.key} scope="col">{m.short}{m.unit ? ` (${m.unit})` : ""}</th>)}
                <th scope="col">Base</th>
              </tr>
            </thead>
            <tbody>
              {detail.groups.map((g) => {
                const row = ref.groups[g.code];
                return (
                  <tr key={g.code}>
                    <th scope="row">{g.code} <span className={styles.muted}>· {g.label}</span></th>
                    {metrics.map((m) => <td key={m.key} className={styles.num}>{fmt(refValue(row, m.key))}</td>)}
                    <td className={row?.fallback ? styles.fallback : styles.muted}>
                      {row?.fallback
                        ? `Usa el equipo (${row.own_players ?? 0} jugador${row.own_players === 1 ? "" : "es"} propios)`
                        : `${row?.n_players ?? 0} jugadores · ${row?.n_matches ?? 0} partidos`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className={styles.provenance}>
          Datos usados: promedio por posición de los jugadores con más de {ref.params.ref_min_minutes} min de GPS en
          {ref.params.ref_official_only ? " partidos oficiales" : " partidos"} del {shortDate(ref.window.start)} al {shortDate(ref.window.end)} (excluido),
          {" "}{ref.params.ref_window_days} días. La posición es la que el club anotó en esa fila del GPS.
          {fallbackGroups.length > 0 && ` ${fallbackGroups.join(", ")}: sin muestra suficiente, usa el promedio del equipo.`}
        </p>
      </section>

      <section className={styles.card} aria-labelledby="lc-plan">
        <div className={styles.cardHead}>
          <h2 id="lc-plan" className={styles.h2}>% de la referencia por día y métrica</h2>
          {detail.copied_from && (
            <span className={styles.muted}>
              Copiado de la semana {detail.copied_from.number}
              {Object.keys(changed).length > 0 && ` · las celdas con borde violeta cambiaron`}
            </span>
          )}
        </div>
        {saveError && (
          <div id="lc-save-error" ref={errorRef} tabIndex={-1} role="alert" className={styles.error}>{saveError}</div>
        )}
        <div className={styles.tableWrap}>
          <table className={styles.planTable}>
            <thead>
              <tr>
                <th scope="col">Día</th>
                {metrics.map((m) => <th key={m.key} scope="col">{m.short}</th>)}
              </tr>
            </thead>
            <tbody>
              {draft.days.map((d) => (
                <tr key={d.date}>
                  <th scope="row" className={styles.rowHead}>
                    <span className={styles.rowLabel}>{d.md_label || "—"}</span>
                    <span className={styles.rowDate}>{d.weekday} {shortDate(d.date)}</span>
                  </th>
                  {isMatch(d.kind) && (
                    <td colSpan={metrics.length} className={`${styles.matchCell} ${styles[`matchCell_${d.kind}`]}`}>
                      {DAY_KIND_LABEL[d.kind]} · 100%
                      {serverDay(d.date)?.kind === d.kind && (serverDay(d.date)?.opponent || serverDay(d.date)?.event_id) && (
                        <> · <MatchLink eventId={serverDay(d.date)?.event_id} opponent={serverDay(d.date)?.opponent}
                          className={styles.matchLink} /></>
                      )}
                    </td>
                  )}
                  {d.kind === "rest" && <td colSpan={metrics.length} className={styles.restCell}>Descanso · sin objetivo</td>}
                  {d.kind === "training" && metrics.map((m) => {
                    const id = cellId(d.date, m.key);
                    const bad = invalid.includes(id);
                    const was = (changed[d.date] ?? []).includes(m.key);
                    return (
                      <td key={m.key}>
                        <input id={id} className={`${styles.pct} ${bad ? styles.pctInvalid : was ? styles.pctChanged : ""}`}
                          inputMode="decimal" value={d.pct[m.key] ?? ""} disabled={!editable}
                          placeholder="—" aria-label={`${m.short} ${d.md_label} ${d.weekday} ${shortDate(d.date)} (%)`}
                          aria-invalid={bad || undefined}
                          aria-describedby={bad && saveError ? "lc-save-error" : undefined}
                          onChange={(e) => setPct(d.date, m.key, e.target.value)} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={styles.provenance}>Una celda vacía es “sin objetivo” para esa métrica, no 0%. Un día de partido vale 100%.</p>
      </section>

      <section className={styles.card} aria-labelledby="lc-obj">
        <div className={styles.cardHead}>
          <h2 id="lc-obj" className={styles.h2}>Objetivo resultante{pos ? ` · ${pos}` : ""}</h2>
          <div role="group" aria-label="Posición" className={styles.chips}>
            {detail.groups.map((g) => (
              <button key={g.code} type="button" aria-pressed={pos === g.code}
                className={`${styles.posChip} ${pos === g.code ? styles.posChipOn : ""}`}
                onClick={() => setPos(g.code)}>{g.code}</button>
            ))}
          </div>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Día</th>
                {metrics.map((m) => <th key={m.key} scope="col">{m.short}{m.unit ? ` (${m.unit})` : ""}</th>)}
              </tr>
            </thead>
            <tbody>
              {draft.days.map((d) => (
                <tr key={d.date}>
                  <th scope="row">{d.md_label || "—"} <span className={styles.muted}>{d.weekday} {shortDate(d.date)}{isMatch(d.kind) ? " · partido" : ""}</span></th>
                  {metrics.map((m) => <td key={m.key} className={styles.num}>{fmt(target(d, m.key))}</td>)}
                </tr>
              ))}
              <tr>
                <th scope="row"><strong>Entrenamientos de la semana</strong></th>
                {trainingTotals.map((t, i) => <td key={metrics[i].key} className={styles.num}><strong>{fmt(t)}</strong></td>)}
              </tr>
            </tbody>
          </table>
        </div>
        <p className={styles.provenance}>Objetivo = referencia de la posición × % del día. Es el “óptimo” contra el que se evaluará el GPS.</p>
      </section>

      {editable && (
        <div className={styles.saveBar}>
          <span className={styles.muted}>{dirty ? "Cambios sin guardar" : "Sin cambios"}</span>
          <div className={styles.controls}>
            {detail.status === "draft" && (
              <button type="button" className={styles.secondary} onClick={open} disabled={dirty || saving}
                title={dirty ? "Guarda los cambios antes de publicar" : undefined}>
                Publicar
              </button>
            )}
            <button type="button" className={styles.primary} onClick={save} disabled={!dirty || saving}>
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
