"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Sparkles, ChevronDown, ChevronUp, Clock, ArrowRight } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import type { BriefingItem } from "./types";
import styles from "./BriefingPanel.module.css";

const TABS = ["Todos", "Médico", "Carga", "Wellness", "Nutrición", "RTP"] as const;
const TAB_DEPT: Record<string, string> = {
  "Médico": "medico",
  "Carga": "fisico",
  "Wellness": "psicosocial",
  "Nutrición": "nutricional",
};

// Departments with a per-department report (CTA target).
const REPORT_DEPTS = new Set(["medico", "fisico", "nutricional", "tactico"]);

export default function BriefingPanel({ categoryId }: { categoryId: string | null }) {
  const [items, setItems] = useState<BriefingItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string>("Todos");
  const [expanded, setExpanded] = useState<Set<number>>(new Set([0]));

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) { setItems(null); setError(null); }
    });
    api<{ items: BriefingItem[] }>(`/briefing?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) { setItems(d.items); setExpanded(new Set([0])); } })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "No se pudo generar el briefing.");
      });
    return () => { cancelled = true; };
  }, [categoryId]);

  const filtered = useMemo(
    () => (items ?? []).filter((it) => matchesTab(it, tab)),
    [items, tab],
  );

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <span className={styles.headIcon}><Sparkles size={18} aria-hidden="true" /></span>
        <div>
          <div className={styles.title}>
            Briefing SLAB <span className={styles.iaTag}>IA</span>
          </div>
          <div className={styles.subtitle}>
            Lectura automática de señales médicas, físicas y operacionales
          </div>
        </div>
      </header>

      <div className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            className={`${styles.tab} ${tab === t ? styles.tabActive : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className={styles.body}>
        {error ? (
          <p className={styles.note} role="alert">{error}</p>
        ) : items === null ? (
          <p className={styles.note}>
            Analizando los datos del plantel con los agentes por departamento…
          </p>
        ) : filtered.length === 0 ? (
          <p className={styles.note}>
            {items.length === 0
              ? "Sin recomendaciones: los agentes no detectaron señales accionables, o falta configurar el asistente de IA."
              : "Sin recomendaciones en esta categoría."}
          </p>
        ) : (
          filtered.map((it, i) => (
            <Card
              key={`${it.department}-${i}`}
              item={it}
              n={i + 1}
              open={expanded.has(i)}
              onToggle={() => toggle(i)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function Card({
  item, n, open, onToggle,
}: { item: BriefingItem; n: number; open: boolean; onToggle: () => void }) {
  const Chevron = open ? ChevronUp : ChevronDown;
  const ctaHref = REPORT_DEPTS.has(item.department) ? `/reportes/${item.department}` : null;

  return (
    <div className={styles.card}>
      <div className={styles.cardTop} onClick={onToggle} role="button" tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}>
        <span className={styles.num}>{n}</span>
        <div className={styles.cardMain}>
          <div className={styles.tags}>
            <span className={`${styles.tag} ${prioTone(item.priority)}`}>
              {cap(item.priority)}
            </span>
            {item.tags.map((t) => (
              <span key={t} className={`${styles.tag} ${tagTone(t)}`}>{t}</span>
            ))}
          </div>
          <div className={styles.cardTitle}>{item.title}</div>
          <div className={styles.recommendation}>
            <span className={styles.recLabel}>Recomendación:</span> {item.recommendation}
          </div>
        </div>
        <Chevron size={18} aria-hidden="true" className={styles.chevron} />
      </div>

      {open && (item.evidence.length > 0 || item.confidence > 0) && (
        <div className={styles.evidence}>
          {item.evidence.length > 0 && (
            <>
              <div className={styles.evidenceLabel}>Evidencia</div>
              <ul className={styles.evidenceList}>
                {item.evidence.map((e, i) => (
                  <li key={i}><span className={styles.evDot} />{e}</li>
                ))}
              </ul>
            </>
          )}
          <div className={styles.confianza}>
            <Sparkles size={13} aria-hidden="true" />
            <span className={styles.confLabel}>Confianza {item.confidence}%</span>
            <span className={styles.confTrack}>
              <span className={styles.confFill} style={{ width: `${item.confidence}%` }} />
            </span>
          </div>
        </div>
      )}

      <div className={styles.footer}>
        <div className={styles.owner}>
          <span className={styles.avatar}>{roleInitials(item.owner_role)}</span>
          <span className={styles.ownerRole}>{item.owner_role}</span>
          {item.timing && (
            <span className={styles.timing}>
              <Clock size={12} aria-hidden="true" /> {item.timing}
            </span>
          )}
        </div>
        {ctaHref ? (
          <Link href={ctaHref} className={styles.cta}>
            {item.cta_label || "Ver detalle"} <ArrowRight size={14} aria-hidden="true" />
          </Link>
        ) : (
          <span className={styles.ctaDisabled}>
            {item.cta_label || "Ver detalle"} <ArrowRight size={14} aria-hidden="true" />
          </span>
        )}
      </div>
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────

function matchesTab(it: BriefingItem, tab: string): boolean {
  if (tab === "Todos") return true;
  if (TAB_DEPT[tab] && it.department === TAB_DEPT[tab]) return true;
  const t = tab.toLowerCase();
  if (it.tags.some((x) => x.toLowerCase() === t)) return true;
  if (tab === "RTP") return it.tags.some((x) => /rtp|reintegr/i.test(x));
  return false;
}

function prioTone(p: string): string {
  return p === "alta" ? styles.toneCrit : p === "media" ? styles.toneWarn : styles.toneMuted;
}

const TAG_TONES: Record<string, string> = {
  carga: "toneInfo", hsr: "toneInfo", nordic: "toneInfo", "carga interna": "toneInfo",
  reintegración: "toneInfo", rtp: "toneInfo", "día de partido": "toneInfo",
  riesgo: "toneWarn", asimetría: "toneWarn", adherencia: "toneWarn",
  wellness: "toneCyan", bienestar: "toneCyan", "1:1": "toneCyan",
  médico: "toneCrit", wada: "toneCrit", medicación: "toneCrit",
  nutrición: "toneGreen", oportunidad: "toneGreen", hidratación: "toneGreen",
  "calidad de dato": "toneMuted",
};

function tagTone(tag: string): string {
  return styles[TAG_TONES[tag.toLowerCase()] ?? "toneSlate"];
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function roleInitials(role: string): string {
  const words = role.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "—";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
