"use client";

import React, { useEffect, useMemo, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import { ApiError } from "@/lib/api";
import {
  addPlayerWidget,
  addWidget,
  editPlayerWidget,
  editWidget,
  fetchPlayerWidgetConfig,
  fetchPlayerWidgetOptions,
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
  /** "team" (default) edits team-report widgets; "player" edits per-player
   *  profile-layout widgets (§5b). Swaps the endpoints + chart-type vocab. */
  scope?: "team" | "player";
  /** Required when scope === "player" and creating (not editing) a widget. */
  playerId?: string;
  /** When set, the modal edits that widget in place (pre-filled) instead of
   *  creating a new one; its display_config is preserved on save (§5). */
  editWidgetId?: string | null;
  onClose: () => void;
  onAdded: () => void;
}

const DEFAULT_CHART: Record<"team" | "player", string> = {
  team: "team_leaderboard",
  player: "line_with_selector",
};

/** Aggregation the resolver expects per chart type (mirrors how the seeds +
 *  promote flow configure data sources). */
function aggregationFor(chartType: string): string {
  switch (chartType) {
    case "team_horizontal_comparison":
    case "grouped_bar":
    case "comparison_table":
      return "last_n";
    case "line_with_selector":
    case "multi_line":
      return "all";
    default:
      return "latest";
  }
}

/** Add OR edit a widget from a picked exam + metric(s) + chart type. Serves
 *  both the team-report layout and the per-player profile layout via `scope`.
 *  Create reuses the promote-from-spec endpoint; edit PATCHes config in place. */
export default function AddWidgetModal({
  open, deptSlug, categoryId, scope = "team", playerId, editWidgetId, onClose, onAdded,
}: Props) {
  const { toast } = useToast();
  const isEdit = !!editWidgetId;
  const isPlayer = scope === "player";
  const [opts, setOpts] = useState<WidgetOptions | null>(null);
  const [chartType, setChartType] = useState(DEFAULT_CHART[scope]);
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
    const optionsFn = isPlayer ? fetchPlayerWidgetOptions : fetchWidgetOptions;
    const configFn = isPlayer ? fetchPlayerWidgetConfig : fetchWidgetConfig;
    optionsFn(deptSlug, categoryId)
      .then((o) => { if (!cancelled) setOpts(o); })
      .catch(() => { if (!cancelled) setError("No se pudieron cargar las opciones."); });
    if (editWidgetId) {
      configFn(editWidgetId)
        .then((cfg) => {
          if (cancelled) return;
          setChartType(cfg.chart_type);
          setTemplateSlug(cfg.template_slug);
          setFields(cfg.field_keys);
          setTitle(cfg.title);
          setExistingDisplayConfig(cfg.display_config);
        })
        .catch(() => { if (!cancelled) setError("No se pudo cargar el gráfico."); });
    } else {
      // Fresh create — reset to defaults.
      setChartType(DEFAULT_CHART[scope]);
      setTemplateSlug("");
      setFields([]);
      setTitle("");
      setExistingDisplayConfig(null);
    }
    return () => { cancelled = true; };
  }, [open, deptSlug, categoryId, editWidgetId, isPlayer, scope]);

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
    if (isPlayer && !isEdit && !playerId) {
      setError("Falta el jugador para crear el gráfico.");
      return;
    }
    setBusy(true);
    setError(null);
    const isLeaderboard = chartType === "team_leaderboard";
    const source = {
      template_slug: templateSlug,
      field_keys: fields,
      aggregation: aggregationFor(chartType),
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
      : "Gráfico";
    const spec: WidgetSpec = {
      chart_type: chartType,
      title: title.trim() || defaultTitle,
      sources: [source],
      display_config,
    };
    try {
      if (isEdit && editWidgetId) {
        await (isPlayer ? editPlayerWidget : editWidget)(editWidgetId, spec);
        toast.success("Gráfico actualizado.");
      } else if (isPlayer) {
        await addPlayerWidget(playerId as string, deptSlug, spec);
        toast.success("Gráfico agregado.");
      } else {
        await addWidget(deptSlug, categoryId, spec);
        toast.success("Gráfico agregado.");
      }
      setFields([]);
      setTitle("");
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar el gráfico.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={isEdit ? "Editar gráfico" : "Agregar gráfico"} onClose={onClose}>
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
