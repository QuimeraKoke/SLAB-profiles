"use client";

import React, { useState } from "react";

import type { TeamReportSection as TeamReportSectionType } from "@/lib/types";
import { renderTeamWidget } from "./widgets";
import styles from "./TeamReportSection.module.css";

interface Props {
  section: TeamReportSectionType;
}

export default function TeamReportSection({ section }: Props) {
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
              style={
                {
                  "--col-span": widget.column_span,
                  // Tablet rule: max 2 widgets per row. ≤6 stays 6 (pair),
                  // >6 promotes to 12 (full row). Mobile overrides to 12 in CSS.
                  "--tablet-col-span": widget.column_span <= 6 ? 6 : 12,
                } as React.CSSProperties
              }
            >
              {renderTeamWidget(widget)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
