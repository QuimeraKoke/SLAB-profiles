"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Bell, Plus } from "lucide-react";

import { useCategoryContext } from "@/context/CategoryContext";
import { usePermission } from "@/lib/permissions";
import { useToast } from "@/components/ui/Toast/Toast";
import {
  type AlertRuleDTO,
  type RuleMeta,
  fetchRuleMeta,
  fetchRules,
} from "@/lib/alertRules";
import RuleForm from "./RuleForm";
import AcwrConfigSection from "./AcwrConfigSection";
import styles from "./page.module.css";

const KIND_LABEL: Record<string, string> = {
  bound: "Umbral",
  variation: "Variación",
  zscore: "Desviación (z)",
  pct_match: "% de partido",
  band: "Banda",
};

function describe(rule: AlertRuleDTO): string {
  const c = rule.config || {};
  switch (rule.kind) {
    case "bound": {
      const parts: string[] = [];
      if (c.upper != null) parts.push(`> ${c.upper}`);
      if (c.lower != null) parts.push(`< ${c.lower}`);
      return parts.join(" · ") || "sin límites";
    }
    case "variation":
      return `${c.threshold_pct != null ? `±${c.threshold_pct}%` : ""} ${
        (c.direction as string) && c.direction !== "any" ? `(${c.direction})` : ""
      }`.trim();
    case "zscore":
      return `z ≥ ${c.threshold_z ?? "?"} · ${
        c.method === "ewma" ? "EWMA" : "media móvil"
      }`;
    case "pct_match":
      return [c.ratio_upper != null ? `≥ ${c.ratio_upper}×` : null, c.ratio_lower != null ? `≤ ${c.ratio_lower}×` : null]
        .filter(Boolean).join(" · ");
    case "band":
      return Array.isArray(c.trigger_labels) && (c.trigger_labels as string[]).length
        ? (c.trigger_labels as string[]).join(", ")
        : "bandas rojas";
    default:
      return "";
  }
}

function scopeChips(rule: AlertRuleDTO): string[] {
  const s = rule.scope || {};
  return [
    ...(s.session_types || []),
    ...(s.roles || []),
    ...(s.microcycle_days || []),
  ];
}

/**
 * Reglas de alerta (§1.g) — Editor-gated, category-scoped configuration of the
 * threshold/alert engine. List rules by exam, create/edit with a live backtest
 * preview so a physio can tune thresholds and see who would have been flagged
 * before saving. Honors the global category picker (IA principle #5).
 */
export default function AlertRulesPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const canEdit = usePermission("goals.change_alertrule");
  const { toast } = useToast();

  const [meta, setMeta] = useState<RuleMeta | null>(null);
  const [rules, setRules] = useState<AlertRuleDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<AlertRuleDTO | null | "new">(null);

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId || !canEdit) return;
    let cancelled = false;
    // Reset off the synchronous effect body (React 19 set-state-in-effect).
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true);
      setEditing(null);
    });
    Promise.all([fetchRuleMeta(categoryId), fetchRules(categoryId)])
      .then(([m, r]) => {
        if (cancelled) return;
        setMeta(m);
        setRules(r.rules);
      })
      .catch(() => {
        if (!cancelled) setMeta(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId, canEdit]);

  const byTemplate = useMemo(() => {
    const m = new Map<string, { name: string; items: AlertRuleDTO[] }>();
    for (const r of rules) {
      if (!m.has(r.template_id)) m.set(r.template_id, { name: r.template_name, items: [] });
      m.get(r.template_id)!.items.push(r);
    }
    return [...m.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [rules]);

  function refresh() {
    if (!categoryId) return;
    fetchRules(categoryId).then((r) => setRules(r.rules)).catch(() => {});
  }

  if (!canEdit) {
    return <div className={styles.muted}>No tenés permiso para configurar alertas.</div>;
  }
  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>
            <Bell size={20} aria-hidden="true" /> Reglas de alerta
          </h1>
          <p className={styles.sub}>
            {categoryName} · configurá umbrales y desviaciones; simulá antes de guardar
          </p>
        </div>
        {meta && editing === null && (
          <button type="button" className={styles.primaryBtn} onClick={() => setEditing("new")}>
            <Plus size={16} /> Nueva regla
          </button>
        )}
      </header>

      {editing === null && (
        <AcwrConfigSection categoryId={categoryId} canEdit={canEdit} />
      )}

      {editing !== null && meta && (
        <RuleForm
          meta={meta}
          categoryId={categoryId}
          categoryName={categoryName}
          initial={editing === "new" ? null : editing}
          onSaved={(saved) => {
            toast.success(editing === "new" ? "Regla creada." : "Regla actualizada.");
            setEditing(null);
            refresh();
            // ensure the just-saved rule shows even if scoped to all categories
            setRules((prev) => {
              const rest = prev.filter((r) => r.id !== saved.id);
              return [...rest, saved];
            });
          }}
          onDeleted={() => {
            toast.success("Regla eliminada.");
            setEditing(null);
            refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      {loading ? (
        <div className={styles.muted}>Cargando reglas…</div>
      ) : byTemplate.length === 0 ? (
        editing === null && (
          <div className={styles.empty}>
            Todavía no hay reglas para esta categoría. Creá la primera con “Nueva regla”.
          </div>
        )
      ) : (
        byTemplate.map((grp) => (
          <section key={grp.name} className={styles.card}>
            <h2 className={styles.cardTitle}>{grp.name}</h2>
            <ul className={styles.ruleList}>
              {grp.items.map((r) => {
                const chips = scopeChips(r);
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      className={styles.ruleRow}
                      onClick={() => setEditing(r)}
                    >
                      <span className={styles.ruleMain}>
                        <span className={`${styles.sev} ${styles[`sev_${r.severity}`]}`} />
                        <span className={styles.ruleField}>{r.field_label}</span>
                        <span className={styles.kindTag}>{KIND_LABEL[r.kind] ?? r.kind}</span>
                        <span className={styles.ruleDesc}>{describe(r)}</span>
                      </span>
                      <span className={styles.ruleMeta}>
                        {!r.is_active && <span className={styles.inactive}>inactiva</span>}
                        {r.category_id === null && <span className={styles.globalTag}>todas las cat.</span>}
                        {chips.map((c) => (
                          <span key={c} className={styles.scopePill}>{c}</span>
                        ))}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
