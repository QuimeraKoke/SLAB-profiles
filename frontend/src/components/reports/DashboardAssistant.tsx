"use client";

import React, { useEffect, useRef, useState } from "react";
import { Sparkles, Send, ChevronDown, ChevronUp } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast/Toast";
import type { TeamReportWidget, TeamWidgetData } from "@/lib/types";
import { renderTeamWidget } from "./widgets";
import styles from "./DashboardAssistant.module.css";

/** A resolved chart payload (TeamWidgetData) plus the echoed `spec` the
 *  backend returns for promotion (V3). Typed loosely to avoid narrowing the
 *  payload union just to read chart_type/title. */
interface ChartResult {
  chart_type: string;
  title?: string;
  empty?: boolean;
  error?: string;
  spec?: unknown;
  [k: string]: unknown;
}

interface Turn {
  question: string;
  reply: string;
  charts: ChartResult[];
  error?: boolean;
}

interface Props {
  categoryId: string;
  departmentSlug: string;
  departmentName: string;
  /** The page's current filters, forwarded so a proposed chart respects the
   *  same position / player / date scope the dashboard is showing. */
  filters: {
    positionId: string;
    playerIds: string[];
    dateFrom: string;
    dateTo: string;
  };
  /** Called after a chart is promoted, so the page can refetch the layout
   *  and show the newly-pinned widget. */
  onPromoted?: () => void;
}

const SUGGESTIONS = [
  "¿Cómo está la distribución del plantel en la métrica clave de esta área?",
  "Compará a los jugadores por su último registro y mostrame un gráfico.",
  "¿Quiénes están fuera de rango? Visualizalo.",
];

/**
 * V2c — embedded "Ask S-LAB AI" tool, bound to ONE department Dashboard. Asks
 * the view-scoped assistant (`POST /assistant/dashboard`), which answers AND
 * can propose charts; those render transiently here through the same team-widget
 * renderers as the saved dashboard. (V3 will add "Promover al panel".)
 */
export default function DashboardAssistant({
  categoryId,
  departmentSlug,
  departmentName,
  filters,
  onPromoted,
}: Props) {
  const { toast } = useToast();
  const [open, setOpen] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  // Promote status per chart, keyed "<turn>-<chart>".
  const [promoted, setPromoted] = useState<Record<string, "promoting" | "done">>({});
  const transcriptRef = useRef<HTMLDivElement>(null);
  const lastTurnRef = useRef<HTMLDivElement>(null);

  // Keep the panel bounded: when a new answer arrives, scroll the (capped,
  // scrollable) transcript so the latest question sits at the top — scoped to
  // the transcript container, never the page.
  useEffect(() => {
    const c = transcriptRef.current;
    const last = lastTurnRef.current;
    if (c && last) c.scrollTop = last.offsetTop;
  }, [turns.length]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || loading || !categoryId) return;
    setInput("");
    setLoading(true);
    // Full conversation each turn (the backend is stateless + caps history).
    const messages = [
      ...turns.flatMap((t) => [
        { role: "user", content: t.question },
        { role: "assistant", content: t.reply },
      ]),
      { role: "user", content: q },
    ];
    try {
      const res = await api<{ reply: string; charts: ChartResult[] }>(
        "/assistant/dashboard",
        {
          method: "POST",
          body: JSON.stringify({
            category_id: categoryId,
            department_slug: departmentSlug,
            messages,
            position_id: filters.positionId || null,
            player_ids: filters.playerIds.length ? filters.playerIds : null,
            date_from: filters.dateFrom || null,
            date_to: filters.dateTo || null,
          }),
        },
      );
      setTurns((prev) => [
        ...prev,
        { question: q, reply: res.reply, charts: res.charts ?? [] },
      ]);
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        {
          question: q,
          reply: err instanceof ApiError ? err.message : "No se pudo consultar al asistente.",
          charts: [],
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function promote(chart: ChartResult, key: string) {
    if (!chart.spec || promoted[key]) return;
    setPromoted((s) => ({ ...s, [key]: "promoting" }));
    try {
      await api(`/reports/${departmentSlug}/widgets`, {
        method: "POST",
        body: JSON.stringify({ category_id: categoryId, spec: chart.spec }),
      });
      setPromoted((s) => ({ ...s, [key]: "done" }));
      toast.success("Gráfico agregado al panel.");
      onPromoted?.();
    } catch (err) {
      setPromoted((s) => {
        const next = { ...s };
        delete next[key];
        return next;
      });
      toast.error(
        err instanceof ApiError ? err.message : "No se pudo agregar el gráfico.",
      );
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(input);
    }
  }

  return (
    <section className={styles.card} aria-label="Asistente del panel">
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={styles.headTitle}>
          <Sparkles size={16} aria-hidden="true" className={styles.spark} />
          Preguntar a S-LAB AI
          <span className={styles.scope}>· {departmentName}</span>
        </span>
        {open ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
      </button>

      {open && (
        <div className={styles.body}>
          <p className={styles.hint}>
            Preguntá sobre el plantel en esta área. Puedo responder y proponer
            un gráfico para visualizarlo.
          </p>

          <div ref={transcriptRef} className={styles.transcript}>
          {turns.length === 0 && (
            <div className={styles.suggestions}>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={styles.suggestion}
                  onClick={() => void ask(s)}
                  disabled={loading || !categoryId}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {turns.map((t, i) => (
            <div
              key={i}
              ref={i === turns.length - 1 ? lastTurnRef : undefined}
              className={styles.turn}
            >
              <div className={styles.question}>{t.question}</div>
              <div className={`${styles.reply} ${t.error ? styles.replyError : ""}`}>
                <Markdown remarkPlugins={[remarkGfm]}>{t.reply}</Markdown>
              </div>
              {t.charts.length > 0 && (
                <div className={styles.charts}>
                  {t.charts.map((c, j) => {
                    const key = `${i}-${j}`;
                    const canPromote = !!c.spec && !c.empty && !c.error;
                    const st = promoted[key];
                    return (
                      <div key={j} className={styles.chartCard}>
                        {renderTeamWidget(toWidget(c, `transient-${i}-${j}`))}
                        {canPromote && (
                          <div className={styles.chartActions}>
                            <button
                              type="button"
                              className={styles.promoteBtn}
                              onClick={() => void promote(c, key)}
                              disabled={st != null}
                            >
                              {st === "done"
                                ? "✓ Fijado al panel"
                                : st === "promoting"
                                  ? "Agregando…"
                                  : "Promover al panel"}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}

          {loading && <div className={styles.loading}>Analizando…</div>}
          </div>

          <div className={styles.inputRow}>
            <textarea
              className={styles.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={categoryId ? "Escribí tu pregunta…" : "Seleccioná una categoría"}
              rows={1}
              disabled={!categoryId || loading}
            />
            <button
              type="button"
              className={styles.sendBtn}
              onClick={() => void ask(input)}
              disabled={loading || !input.trim() || !categoryId}
              aria-label="Enviar"
            >
              <Send size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** Wrap a resolved chart payload into the `TeamReportWidget` shape the
 *  team-widget renderers expect (they read `widget.data`). */
function toWidget(chart: ChartResult, id: string): TeamReportWidget {
  return {
    id,
    chart_type: chart.chart_type,
    title: chart.title ?? "",
    description: "",
    column_span: 12,
    chart_height: null,
    sort_order: 0,
    data: chart as unknown as TeamWidgetData,
  };
}
