"use client";

import React, { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import styles from "./Modal.module.css";

interface ModalProps {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: React.ReactNode;
}

// Module-level stack of mounted modals — Escape only closes the topmost.
// Without this, a ConfirmDialog opened from inside a registrar Modal would
// have both modals close on Escape (each has its own document keydown).
const MODAL_STACK: symbol[] = [];

export default function Modal({ open, title, onClose, children }: ModalProps) {
  const titleId = useId();
  const modalIdRef = useRef<symbol>(Symbol("modal"));
  // ME-4: focus trap + restoration. Previously Tab leaked out into the
  // background page and Escape only worked because of the keydown
  // listener below. Now Tab cycles inside the dialog and focus returns
  // to the trigger on close.
  const dialogRef = useFocusTrap<HTMLDivElement>(open);

  // Escape closes; lock body scroll while open. Honors modal stack so a
  // nested dialog absorbs Escape without bubbling up to its parent.
  useEffect(() => {
    if (!open) return;
    const myId = modalIdRef.current;
    MODAL_STACK.push(myId);
    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Only the topmost modal in the stack responds to Escape.
      if (MODAL_STACK[MODAL_STACK.length - 1] !== myId) return;
      e.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", handleKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      const idx = MODAL_STACK.lastIndexOf(myId);
      if (idx >= 0) MODAL_STACK.splice(idx, 1);
      document.removeEventListener("keydown", handleKey);
      // Only restore body overflow when no modal remains.
      if (MODAL_STACK.length === 0) {
        document.body.style.overflow = prevOverflow;
      }
    };
  }, [open, onClose]);

  if (!open || typeof window === "undefined") return null;

  return createPortal(
    <div
      className={styles.backdrop}
      onClick={onClose}
    >
      {/* ME-4: aria-labelledby + an h2 so the accessible name is the
       * rendered heading, not a fabricated label. tabIndex=-1 lets the
       * focus-trap park here if the body has no focusable children. */}
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : "Diálogo"}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className={styles.header}>
          {title ? <h2 id={titleId} className={styles.title}>{title}</h2> : <span />}
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Cerrar"
          >
            ✕
          </button>
        </header>
        <div className={styles.body}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}
