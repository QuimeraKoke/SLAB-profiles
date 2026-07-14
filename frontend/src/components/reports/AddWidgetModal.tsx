"use client";

import React, { useEffect, useMemo, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import { ApiError } from "@/lib/api";
import {
  addWidget,
  editWidget,
  fetchWidgetConfig,
  fetchWidgetOptions,
  type WidgetOptions,
  type WidgetSpec,
} from "@/lib/panelBuilder";
import styles from "./AddWidgetModal.module.css";

interface Props {
  open: boolean;
  deptSlug: string;
  categoryId: string;
  /** When set, the modal edits that widget in place (pre-filled) instead of
   *  creating a new one; its display_config is preserved on save (§5). */
  editWidgetId?: string | null;
  onClose: () => void;
  onAdded: () => void;
}

/** Add OR edit a team-report widget from a picked exam + metric(s) + chart
 *  type. Create reuses the promote-from-spec endpoint (new widgets land in
 *  "Mis gráficos"); edit PATCHes the widget's config in place (§2.c / §5). */
export default function AddWidgetModal({
  open, deptSlug, categoryId, editWidgetId, onClose, onAdded,
}: Props) {
  const { toast } = useToast();
  const isEdit = !!editWidgetId;
  const [opts, setOpts] = useState<WidgetOptions | null>(null);
  const [chartType, setChartType] = useState("team_leaderboard");
  const [templateSlug, setTemplateSlug] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  // Preserved on edit so we don't clobber the club's reference lines / coloring.
  const [existingDisplayConfig, setExistingDisplayConfig] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchWidgetOptions(deptSlug, categoryId)
      .then((o) => { if (!cancelled) setOpts(o); })
      .catch(() => { if (!cancelled) setError("No se pudieron cargar las opciones."); });
    if (editWidgetId) {
      fetchWidgetConfig(editWidgetId)
        .then((cfg) => {
          if (cancelled) return;
          setChartType(cfg.chart_type);
          setTemplateSlug(cfg.template_slug);
          setFields(cfg.field_keys);
          setTitle(cfg.title);
          setExistingDisplayConfig(cfg.display_config);
        })
        .catch(() => { if (!cancelled) setError("No se pudo cargar el widget."); });
    } else {
      // Fresh create — reset to defaults.
      setChartType("team_leaderboard");
      setTemplateSlug("");
      setFields([]);
      setTitle("");
      setExistingDisplayConfig(null);
    }
    return () => { cancelled = true; };
  }, [open, deptSlug, categoryId, editWidgetId]);

  const template = useMemo(
    () => opts?.templates.find((t) => t.slug === templateSlug),
    [opts, templateSlug],
  );
  const multi = opts?.chart_types.find((c) => c.value === chartType)?.multi_field ?? false;
  const numericFields = template?.numeric_fields ?? [];

  function toggleField(key: string) {
    setFields((cur) => {
      if (!multi) return [key]; // single-field chart → replace
      return cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
    });
  }

  async function submit() {
    if (!templateSlug || fields.length === 0) {
      setError("Elegí un examen y al menos una métrica.");
      return;
    }
    setBusy(true);
    setError(null);
    const isLeaderboard = chartType === "team_leaderboard";
    const source = {
      template_slug: templateSlug,
      field_keys: fields,
      aggregation: chartType === "team_horizontal_comparison" ? "last_n" : "latest",
      aggregation_param: 5,
    };
    // On edit, keep the widget's existing display_config (reference lines,
    // coloring, deviation mode…) — the builder only changes type/metric/title.
    const display_config = isEdit && existingDisplayConfig
      ? existingDisplayConfig
      : isLeaderboard
        ? { style: "vertical_bars", aggregator: "latest" }
        : {};
    const firstLabel = numericFields.find((f) => f.key === fields[0])?.label ?? "";
    const defaultTitle = template
      ? `${template.name}${fields.length === 1 && firstLabel ? ` · ${firstLabel}` : ""}`
      : "Widget";
    const spec: WidgetSpec = {
      chart_type: chartType,
      title: title.trim() || defaultTitle,
      sources: [source],
      display_config,
    };
    try {
      if (isEdit && editWidgetId) {
        await editWidget(editWidgetId, spec);
        toast.success("Widget actualizado.");
      } else {
        await addWidget(deptSlug, categoryId, spec);
        toast.success("Widget agregado.");
      }
      setFields([]);
      setTitle("");
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar el widget.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={isEdit ? "Editar widget" : "Agregar widget"} onClose={onClose}>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.form}>
        <label className={styles.field}>
          <span>Tipo de gráfico</span>
          <select
            value={chartType}
            onChange={(e) => { setChartType(e.target.value); setFields([]); }}
          >
            {(opts?.chart_types ?? []).map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Examen</span>
          <select
            value={templateSlug}
            onChange={(e) => { setTemplateSlug(e.target.value); setFields([]); }}
          >
            <option value="">— elegí —</option>
            {(opts?.templates ?? []).map((t) => (
              <option key={t.slug} value={t.slug}>{t.department} · {t.name}</option>
            ))}
          </select>
        </label>

        <div className={styles.field}>
          <span>{multi ? "Métricas" : "Métrica"}</span>
          {template ? (
            numericFields.length > 0 ? (
              <div className={styles.chips}>
                {numericFields.map((f) => (
                  <button
                    key={f.key} type="button"
                    className={fields.includes(f.key) ? styles.chipOn : styles.chip}
                    onClick={() => toggleField(f.key)}
                  >
                    {f.label}{f.unit ? ` (${f.unit})` : ""}
                  </button>
                ))}
              </div>
            ) : (
              <p className={styles.hint}>Este examen no tiene métricas numéricas.</p>
            )
          ) : (
            <p className={styles.hint}>Elegí un examen primero.</p>
          )}
        </div>

        <label className={styles.field}>
          <span>Título (opcional)</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Automático si lo dejás vacío"
          />
        </label>
      </div>

      <div className={styles.footer}>
        <button type="button" className={styles.secondaryBtn} onClick={onClose} disabled={busy}>
          Cancelar
        </button>
        <button
          type="button" className={styles.primaryBtn} onClick={submit}
          disabled={busy || !templateSlug || fields.length === 0}
        >
          {busy ? "Guardando…" : isEdit ? "Guardar" : "Agregar"}
        </button>
      </div>
    </Modal>
  );
}
