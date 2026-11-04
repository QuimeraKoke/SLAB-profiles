"use client";

/**
 * Create a microcycle from the server's suggestion: dates, the club's MICRO
 * number and TIPO (from the GPS sheet), match days (fixtures + the sheet's
 * friendlies) and the microcycle whose % it copies. The staff corrects any of
 * it before creating.
 */

import React, { useEffect, useRef, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import {
  DAY_KIND_LABEL, type DayKind, kindLabel, type McDetail, type McSummary, shortDate, type Suggestion,
} from "@/lib/loadControl";

import styles from "./loadControl.module.css";

interface Props {
  open: boolean;
  categoryId: string;
  season: number;
  teamLabel: string;
  microcycles: McSummary[];
  onClose: () => void;
  onCreated: (mc: McDetail) => void;
}

export default function NewMicrocycleModal({ open, categoryId, season, teamLabel, microcycles, onClose, onCreated }: Props) {
  const [s, setS] = useState<Suggestion | null>(null);
  const [number, setNumber] = useState("");
  const [kind, setKind] = useState("");
  const [copyFrom, setCopyFrom] = useState("");
  const [days, setDays] = useState<Suggestion["days"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const numberRef = useRef<HTMLInputElement>(null);

  const load = (start?: string) => {
    const sp = new URLSearchParams({ category_id: categoryId, season: String(season) });
    if (start) sp.set("start_date", start);
    api<Suggestion>(`/load-control/microcycles/suggestion?${sp}`)
      .then((d) => {
        setS(d); setNumber(String(d.number)); setKind(d.kind); setDays(d.days);
        setCopyFrom(d.copy_from?.id ?? ""); setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudo preparar la semana."));
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const sp = new URLSearchParams({ category_id: categoryId, season: String(season) });
    api<Suggestion>(`/load-control/microcycles/suggestion?${sp}`)
      .then((d) => {
        if (cancelled) return;
        setS(d); setNumber(String(d.number)); setKind(d.kind); setDays(d.days);
        setCopyFrom(d.copy_from?.id ?? ""); setError(null);
      })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo preparar la semana."); });
    return () => { cancelled = true; };
  }, [open, categoryId, season]);

  const numberInvalid = !/^\d+$/.test(number.trim()) || Number(number) < 1;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!s) return;
    if (numberInvalid) {
      setError("El número de semana debe ser un entero mayor que 0.");
      numberRef.current?.focus();
      return;
    }
    setSaving(true);
    try {
      const mc = await api<McDetail>("/load-control/microcycles", {
        method: "POST",
        body: JSON.stringify({
          category_id: categoryId, season, start_date: s.start_date, end_date: s.end_date,
          number: Number(number), kind, copy_from_id: copyFrom || null,
          days: days.map((d) => ({ date: d.date, kind: d.kind, targets_pct: {} })),
        }),
      });
      onCreated(mc);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la semana.");
      errorRef.current?.focus();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title={`Nueva semana · ${teamLabel}`} onClose={onClose}>
      {!s && !error && <p className={styles.muted}>Preparando…</p>}
      {error && <div ref={errorRef} tabIndex={-1} id="lc-new-error" role="alert" className={styles.error}>{error}</div>}
      {s && (
        <form className={styles.form} onSubmit={create} noValidate>
          <div className={styles.formRow}>
            <label className={styles.label}>
              Semana (lunes)
              <input type="date" className={styles.textInput} value={s.start_date}
                onChange={(e) => e.target.value && load(e.target.value)} />
            </label>
            <label className={styles.label}>
              N° de semana
              <input ref={numberRef} className={styles.textInput} inputMode="numeric" value={number}
                aria-invalid={numberInvalid || undefined}
                aria-describedby={numberInvalid && error ? "lc-new-error" : undefined}
                onChange={(e) => setNumber(e.target.value)} />
            </label>
            <label className={styles.label}>
              Tipo
              <select className={styles.select} value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">Sin tipo</option>
                {s.kinds.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
              </select>
            </label>
            <label className={styles.label}>
              Copiar % de
              <select className={styles.select} value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
                <option value="">No copiar</option>
                {microcycles.map((m) => <option key={m.id} value={m.id}>Semana {m.number} · {shortDate(m.start_date)}</option>)}
              </select>
            </label>
          </div>
          <p className={styles.muted}>
            {shortDate(s.start_date)} – {shortDate(s.end_date)}. Los partidos vienen del calendario oficial y de los
            amistosos (MD AMISTOSO) de la planilla GPS: corrígelos si falta alguno.
          </p>
          <div className={styles.modalDays}>
            {days.map((d) => (
              <label key={d.date} className={styles.label}>
                {d.weekday} {shortDate(d.date)}{d.opponent && d.kind !== "training" && d.kind !== "rest" ? ` · vs ${d.opponent}` : ""}
                <select className={styles.select} value={d.kind}
                  onChange={(e) => setDays(days.map((x) => (x.date === d.date ? { ...x, kind: e.target.value as DayKind } : x)))}>
                  {(Object.keys(DAY_KIND_LABEL) as DayKind[]).map((k) => <option key={k} value={k}>{DAY_KIND_LABEL[k]}</option>)}
                </select>
              </label>
            ))}
          </div>
          <div className={styles.formActions}>
            <button type="button" className={styles.secondary} onClick={onClose}>Cancelar</button>
            <button type="submit" className={styles.primary} disabled={saving}>{saving ? "Creando…" : "Crear semana"}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
