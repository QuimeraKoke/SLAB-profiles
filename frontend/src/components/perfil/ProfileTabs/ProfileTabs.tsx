"use client";

import React, { useRef } from 'react';
import styles from './ProfileTabs.module.css';

export interface TabSpec {
  id: string;
  label: string;
}

interface ProfileTabsProps {
  tabs: TabSpec[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
}

/**
 * ME-3: ARIA-correct tablist. Was a row of `<button>`s without semantics.
 * Now:
 *   - container has `role="tablist"`,
 *   - each tab has `role="tab"`, `aria-selected`, `aria-controls`,
 *   - Left/Right/Home/End cycle the focused tab (per ARIA APG),
 *   - only the active tab is in the natural Tab order (tabIndex=0);
 *     siblings get tabIndex=-1 so the user lands on the active tab
 *     once, then arrow-keys through.
 *
 * The corresponding panels in the parent should use `role="tabpanel"`
 * and `aria-labelledby={tabId}`. Panel IDs are derived from each tab
 * id via `panelIdFor()` so the parent and this component agree.
 */
export function panelIdFor(tabId: string): string {
  return `tabpanel-${tabId}`;
}

function tabIdFor(tabId: string): string {
  return `tab-${tabId}`;
}

export default function ProfileTabs({ tabs, activeTab, onTabChange }: ProfileTabsProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    const idx = tabs.findIndex((t) => t.id === activeTab);
    if (idx < 0) return;
    let nextIdx: number | null = null;
    switch (e.key) {
      case "ArrowRight":
        nextIdx = (idx + 1) % tabs.length;
        break;
      case "ArrowLeft":
        nextIdx = (idx - 1 + tabs.length) % tabs.length;
        break;
      case "Home":
        nextIdx = 0;
        break;
      case "End":
        nextIdx = tabs.length - 1;
        break;
      default:
        return;
    }
    if (nextIdx !== null) {
      e.preventDefault();
      const nextTab = tabs[nextIdx];
      onTabChange(nextTab.id);
      // Move focus to the newly-active tab button.
      const el = containerRef.current?.querySelector<HTMLButtonElement>(
        `#${CSS.escape(tabIdFor(nextTab.id))}`,
      );
      el?.focus();
    }
  };

  return (
    <div
      ref={containerRef}
      role="tablist"
      aria-label="Secciones del perfil"
      className={styles.container}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            id={tabIdFor(tab.id)}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={panelIdFor(tab.id)}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onTabChange(tab.id)}
            onKeyDown={handleKeyDown}
            className={`${styles.tab} ${isActive ? styles.activeTab : ''}`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
