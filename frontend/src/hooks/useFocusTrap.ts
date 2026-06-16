"use client";

import { useEffect, useRef } from "react";

/** Tab-only focus trap with restore-on-unmount.
 *
 * Use on dialog containers (modals, popovers). When `active` flips to true:
 *  1. Records `document.activeElement` so we can restore focus on close.
 *  2. Moves focus to the first focusable element inside the container.
 *  3. Cycles Tab/Shift+Tab within the container until `active` flips back.
 *
 * On deactivation, restores focus to the element that opened the dialog.
 *
 * This is a small handwritten trap rather than pulling in `react-focus-on`
 * to avoid an extra dep. It deliberately doesn't implement aria-hidden on
 * siblings — Modal already uses `role="dialog" aria-modal="true"` which
 * screen readers honor as a focus boundary.
 *
 * Returns a ref to attach to the container element.
 */
export function useFocusTrap<T extends HTMLElement = HTMLElement>(active: boolean) {
  const ref = useRef<T>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active || !ref.current) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;

    const FOCUSABLE_SELECTOR =
      'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
      'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    const getFocusable = (): HTMLElement[] => {
      if (!ref.current) return [];
      return Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        .filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
    };

    // Move focus inside. If nothing focusable, fall back to the container
    // (which must have tabIndex=-1) so the keyboard user lands inside the
    // dialog rather than back on the page.
    const focusables = getFocusable();
    if (focusables.length > 0) {
      focusables[0].focus();
    } else {
      ref.current.focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = getFocusable();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement as HTMLElement | null;

      if (e.shiftKey && current === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && current === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      // Restore focus to wherever it came from. Guard in case the
      // previously-focused element is no longer in the DOM.
      const target = previouslyFocused.current;
      if (target && document.contains(target)) {
        target.focus();
      }
    };
  }, [active]);

  return ref;
}
