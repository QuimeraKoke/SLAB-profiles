"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import styles from "./Toast.module.css";

/** Lightweight toast system. Mount `<ToastProvider>` once at the dashboard
 *  layout level; consume via `const { toast } = useToast()`.
 *
 *  Used by form save paths (DynamicUploader, MatchForm, etc.) so users get
 *  positive confirmation that their save landed, without a full-page
 *  redirect being the only signal.
 *
 *  Each toast auto-dismisses after `duration` ms (default 4s) and exposes
 *  a manual dismiss button. Live region is `aria-live="polite"` so screen
 *  readers announce on next idle, not by interrupting whatever the user
 *  is doing.
 */

type ToastKind = "success" | "error" | "info";

interface ToastEntry {
  id: number;
  kind: ToastKind;
  message: string;
  duration: number;
}

interface ToastContextValue {
  toast: {
    success: (message: string, opts?: { duration?: number }) => void;
    error: (message: string, opts?: { duration?: number }) => void;
    info: (message: string, opts?: { duration?: number }) => void;
  };
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>.");
  }
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  // Provider-local counter rather than a module-level `let nextId` so the
  // ID state is scoped to this React tree (avoids HMR / multi-provider
  // weirdness and keeps the ID space clean across remounts).
  const nextIdRef = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((curr) => curr.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind) =>
      (message: string, opts?: { duration?: number }) => {
        const id = nextIdRef.current++;
        const duration = opts?.duration ?? 4000;
        setToasts((curr) => [...curr, { id, kind, message, duration }]);
      },
    [],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      toast: {
        success: push("success"),
        error: push("error"),
        info: push("info"),
      },
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastEntry[];
  onDismiss: (id: number) => void;
}) {
  if (typeof window === "undefined") return null;
  return createPortal(
    <div
      aria-live="polite"
      aria-atomic="false"
      className={styles.viewport}
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} entry={t} onDismiss={onDismiss} />
      ))}
    </div>,
    document.body,
  );
}

function ToastItem({
  entry,
  onDismiss,
}: {
  entry: ToastEntry;
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    if (entry.duration === 0) return; // 0 means sticky
    const t = setTimeout(() => onDismiss(entry.id), entry.duration);
    return () => clearTimeout(t);
  }, [entry, onDismiss]);

  const Icon =
    entry.kind === "success" ? CheckCircle2
    : entry.kind === "error" ? XCircle
    : Info;
  const className =
    entry.kind === "success" ? styles.success
    : entry.kind === "error" ? styles.error
    : styles.info;

  return (
    <div className={`${styles.toast} ${className}`} role="status">
      <Icon size={18} aria-hidden="true" className={styles.icon} />
      <span className={styles.message}>{entry.message}</span>
      <button
        type="button"
        className={styles.close}
        onClick={() => onDismiss(entry.id)}
        aria-label="Cerrar notificación"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
