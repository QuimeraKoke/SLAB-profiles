"use client";

import React, { useEffect, useRef, useState } from "react";
import { Sparkles, Send, X } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useCategoryContext } from "@/context/CategoryContext";
import styles from "./TeamChat.module.css";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTIONS = [
  "Análisis integral para el próximo partido",
  "¿Quiénes combinan carga alta y wellness bajo?",
  "¿Qué jugadores debería vigilar y por qué?",
];

/** Floating, team-grounded AI assistant. Available across the dashboard;
 *  scoped to the navbar's selected category. Stateless on the server — the
 *  full conversation is sent each turn. */
export default function TeamChat() {
  const { user } = useAuth();
  const { categoryId, categories } = useCategoryContext();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading, open]);

  // Don't render for logged-out users (e.g. the /login screen).
  if (!user) return null;

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  async function send(text: string) {
    const content = text.trim();
    if (!content || loading || !categoryId) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const res = await api<{ reply: string }>("/assistant/team", {
        method: "POST",
        body: JSON.stringify({ category_id: categoryId, messages: next }),
      });
      setMessages([...next, { role: "assistant", content: res.reply }]);
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "No se pudo contactar al asistente.";
      setMessages([...next, { role: "assistant", content: `⚠️ ${msg}` }]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  return (
    <>
      {!open && (
        <button
          type="button"
          className={styles.fab}
          onClick={() => setOpen(true)}
          aria-label="Abrir asistente del equipo"
        >
          <Sparkles size={20} aria-hidden="true" />
        </button>
      )}

      {open && (
        <div className={styles.panel} role="dialog" aria-label="Asistente del equipo">
          <header className={styles.header}>
            <div className={styles.headTitle}>
              <Sparkles size={16} aria-hidden="true" />
              <div>
                <div className={styles.title}>Asistente SLAB</div>
                <div className={styles.subtitle}>{categoryName || "Equipo"}</div>
              </div>
            </div>
            <button
              type="button"
              className={styles.close}
              onClick={() => setOpen(false)}
              aria-label="Cerrar asistente"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>

          <div className={styles.messages} ref={scrollRef}>
            {messages.length === 0 && (
              <div className={styles.intro}>
                <p className={styles.introText}>
                  Análisis integral del plantel — integra las áreas médica,
                  física, nutricional y de carga, con acceso a los datos de
                  todo el equipo.
                </p>
                <div className={styles.suggestions}>
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={styles.suggestion}
                      onClick={() => void send(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div
                key={i}
                className={`${styles.bubble} ${m.role === "user" ? styles.user : styles.assistant}`}
              >
                {m.role === "assistant" ? (
                  <div className={styles.md}>
                    <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>
                  </div>
                ) : (
                  m.content
                )}
              </div>
            ))}

            {loading && (
              <div className={`${styles.bubble} ${styles.assistant} ${styles.typing}`}>
                <span className={styles.dot} />
                <span className={styles.dot} />
                <span className={styles.dot} />
              </div>
            )}
          </div>

          <div className={styles.inputRow}>
            <textarea
              className={styles.input}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={categoryId ? "Escribí tu pregunta…" : "Seleccioná una categoría"}
              rows={1}
              disabled={!categoryId}
            />
            <button
              type="button"
              className={styles.sendBtn}
              onClick={() => void send(input)}
              disabled={loading || !input.trim() || !categoryId}
              aria-label="Enviar"
            >
              <Send size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
