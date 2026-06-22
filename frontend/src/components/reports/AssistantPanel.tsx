"use client";

import React, { useEffect, useRef, useState } from "react";
import { Sparkles, Send, ChevronDown, ChevronUp } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./AssistantPanel.module.css";

/** A resolved chart payload plus the echoed `spec` the backend returns for
 *  promotion. Typed loosely to avoid narrowing the payload union. */
export interface ChartResult {
  chart_type: string;
  title?: string;
  empty?: boolean;
  error?: string;
  spec?: unknown;
  [k: string]: unknown;
}

interface ChatMessage {
  role: string;
  content: string;
}

interface Turn {
  question: string;
  reply: string;
  charts: ChartResult[];
  error?: boolean;
}

interface Props {
  /** Header title, e.g. "Preguntar a S-LAB AI". */
  label: string;
  /** Small scope suffix after the title (department or player name). */
  scope?: string;
  disabled?: boolean;
  placeholder?: string;
  suggestions?: string[];
  /** POST the conversation; return the reply + proposed charts. */
  sendMessage: (messages: ChatMessage[]) => Promise<{ reply: string; charts: ChartResult[] }>;
  /** Render one proposed chart payload (team vs per-player registries differ). */
  renderChart: (chart: ChartResult, id: string) => React.ReactNode;
  /** Persist a chart; resolves on success, rejects on failure (the caller owns
   *  the toast + any refetch). Omit to hide the promote button. */
  promote?: (chart: ChartResult) => Promise<void>;
  promoteLabel?: string;
}

/**
 * Shared "ask → chart → promote" panel. Used by both the team dashboard
 * (`DashboardAssistant`) and the player profile (`PlayerAssistant`); the
 * transport, renderer, and promote behavior come in as props so the shell is
 * identical across surfaces.
 */
export default function AssistantPanel({
  label,
  scope,
  disabled = false,
  placeholder = "Escribí tu pregunta…",
  suggestions = [],
  sendMessage,
  renderChart,
  promote,
  promoteLabel = "Promover al panel",
}: Props) {
  const [open, setOpen] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [promoted, setPromoted] = useState<Record<string, "promoting" | "done">>({});
  const transcriptRef = useRef<HTMLDivElement>(null);
  const lastTurnRef = useRef<HTMLDivElement>(null);

  // Keep the panel bounded: scroll the latest question to the top of the
  // (capped, scrollable) transcript — scoped to the container, not the page.
  useEffect(() => {
    const c = transcriptRef.current;
    const last = lastTurnRef.current;
    if (c && last) c.scrollTop = last.offsetTop;
  }, [turns.length]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || loading || disabled) return;
    setInput("");
    setLoading(true);
    const messages: ChatMessage[] = [
      ...turns.flatMap((t) => [
        { role: "user", content: t.question },
        { role: "assistant", content: t.reply },
      ]),
      { role: "user", content: q },
    ];
    try {
      const res = await sendMessage(messages);
      setTurns((prev) => [...prev, { question: q, reply: res.reply, charts: res.charts ?? [] }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "No se pudo consultar al asistente.";
      setTurns((prev) => [...prev, { question: q, reply: msg, charts: [], error: true }]);
    } finally {
      setLoading(false);
    }
  }

  async function doPromote(chart: ChartResult, key: string) {
    if (!promote || !chart.spec || promoted[key]) return;
    setPromoted((s) => ({ ...s, [key]: "promoting" }));
    try {
      await promote(chart);
      setPromoted((s) => ({ ...s, [key]: "done" }));
    } catch {
      // The caller showed the error toast; revert so the user can retry.
      setPromoted((s) => {
        const next = { ...s };
        delete next[key];
        return next;
      });
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(input);
    }
  }

  return (
    <section className={styles.card} aria-label="Asistente">
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={styles.headTitle}>
          <Sparkles size={16} aria-hidden="true" className={styles.spark} />
          {label}
          {scope && <span className={styles.scope}>· {scope}</span>}
        </span>
        {open ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
      </button>

      {open && (
        <div className={styles.body}>
          <p className={styles.hint}>
            Preguntá y, cuando ayude, te propongo un gráfico para visualizarlo.
          </p>

          <div ref={transcriptRef} className={styles.transcript}>
            {turns.length === 0 && suggestions.length > 0 && (
              <div className={styles.suggestions}>
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={styles.suggestion}
                    onClick={() => void ask(s)}
                    disabled={loading || disabled}
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
                      const canPromote = !!promote && !!c.spec && !c.empty && !c.error;
                      const st = promoted[key];
                      return (
                        <div key={j} className={styles.chartCard}>
                          {renderChart(c, `transient-${i}-${j}`)}
                          {canPromote && (
                            <div className={styles.chartActions}>
                              <button
                                type="button"
                                className={styles.promoteBtn}
                                onClick={() => void doPromote(c, key)}
                                disabled={st != null}
                              >
                                {st === "done"
                                  ? "✓ Fijado"
                                  : st === "promoting"
                                    ? "Agregando…"
                                    : promoteLabel}
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
              placeholder={placeholder}
              rows={1}
              disabled={disabled || loading}
            />
            <button
              type="button"
              className={styles.sendBtn}
              onClick={() => void ask(input)}
              disabled={loading || !input.trim() || disabled}
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
