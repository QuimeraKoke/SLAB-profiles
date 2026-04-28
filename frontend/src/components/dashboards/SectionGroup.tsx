"use client";

import React, { useState } from "react";

import type { DashboardSection } from "@/lib/types";
import { renderWidget } from "./widgets";
import styles from "./SectionGroup.module.css";

interface SectionGroupProps {
  section: DashboardSection;
}

export default function SectionGroup({ section }: SectionGroupProps) {
  const [collapsed, setCollapsed] = useState(section.default_collapsed);
  const showHeader = section.title.length > 0;
  const canCollapse = section.is_collapsible && showHeader;

  return (
    <section className={styles.section}>
      {showHeader && (
        <header
          className={`${styles.header} ${canCollapse ? styles.clickable : ""}`}
          onClick={canCollapse ? () => setCollapsed((c) => !c) : undefined}
          role={canCollapse ? "button" : undefined}
          tabIndex={canCollapse ? 0 : undefined}
          onKeyDown={
            canCollapse
              ? (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setCollapsed((c) => !c);
                  }
                }
              : undefined
          }
        >
          <h3 className={styles.title}>{section.title}</h3>
          {canCollapse && (
            <span className={styles.chevron} aria-hidden>
              {collapsed ? "▾" : "▴"}
            </span>
          )}
        </header>
      )}

      {!collapsed && (
        <div className={styles.grid}>
          {section.widgets.map((widget) => (
            <div
              key={widget.id}
              className={styles.cell}
              style={{ "--col-span": widget.column_span } as React.CSSProperties}
            >
              {renderWidget(widget)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
