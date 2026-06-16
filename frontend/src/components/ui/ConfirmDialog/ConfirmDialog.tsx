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
import Modal from "@/components/ui/Modal/Modal";
import styles from "./ConfirmDialog.module.css";

/** Replaces every native `confirm()` / `alert()` call site. Use via
 *  `const { confirm } = useConfirm()` → `await confirm({ ... })`.
 *
 *  Returns `true` if the user clicked the confirm button, `false` otherwise
 *  (cancel, Escape, backdrop click). Built on top of `<Modal>`, so it
 *  inherits the focus-trap and Escape-to-close behavior added in ME-4.
 */

export interface ConfirmOptions {
  title: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** "danger" styles the confirm button red — use for destructive ops. */
  variant?: "default" | "danger";
}

interface ConfirmContextValue {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
}

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function useConfirm(): ConfirmContextValue {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    throw new Error(
      "useConfirm must be used inside <ConfirmProvider>. Mount one in the dashboard layout.",
    );
  }
  return ctx;
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  // We resolve the previous promise when a new confirm is requested OR
  // when the user makes a choice. `pendingRef` holds the resolver until
  // one of those happens.
  const pendingRef = useRef<((result: boolean) => void) | null>(null);

  const confirm = useCallback((next: ConfirmOptions): Promise<boolean> => {
    // Resolve any in-flight dialog as cancel before opening the new one.
    pendingRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      pendingRef.current = resolve;
      setOpts(next);
    });
  }, []);

  const handleClose = useCallback((result: boolean) => {
    pendingRef.current?.(result);
    pendingRef.current = null;
    setOpts(null);
  }, []);

  // Resolve any pending confirm to `false` if the provider unmounts
  // mid-flight (e.g. route change while the dialog is open) — otherwise
  // the awaited Promise hangs forever.
  useEffect(() => {
    return () => {
      pendingRef.current?.(false);
      pendingRef.current = null;
    };
  }, []);

  const value = useMemo<ConfirmContextValue>(() => ({ confirm }), [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Modal
        open={opts !== null}
        title={opts?.title}
        onClose={() => handleClose(false)}
      >
        {opts && (
          <div className={styles.body}>
            {opts.message && <div className={styles.message}>{opts.message}</div>}
            <div className={styles.actions}>
              {/* Auto-focus rule: for the danger variant focus lands on
                  Cancel (safer default — a reflex-Enter must not delete);
                  for default-confirm dialogs focus lands on Confirm so
                  Enter commits the standard happy-path action. */}
              <button
                type="button"
                className={styles.cancel}
                onClick={() => handleClose(false)}
                autoFocus={opts.variant === "danger"}
              >
                {opts.cancelLabel ?? "Cancelar"}
              </button>
              <button
                type="button"
                className={
                  opts.variant === "danger" ? styles.confirmDanger : styles.confirm
                }
                onClick={() => handleClose(true)}
                autoFocus={opts.variant !== "danger"}
              >
                {opts.confirmLabel ?? "Confirmar"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </ConfirmContext.Provider>
  );
}
