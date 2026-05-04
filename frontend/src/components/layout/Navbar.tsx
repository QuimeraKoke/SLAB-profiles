"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Search, Bell, Menu } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import type { AlertWithPlayer } from "@/lib/types";
import styles from "./Navbar.module.css";

interface NavbarProps {
  /** Toggles the sidebar — only used on tablet/mobile, the hamburger
   *  button rendering it is hidden by CSS on desktop. */
  onMenuClick?: () => void;
}

const POLL_INTERVAL_MS = 30_000;
const MAX_DROPDOWN_ITEMS = 20;

const SOURCE_LABELS: Record<AlertWithPlayer["source_type"], string> = {
  goal: "Objetivo",
  goal_warning: "Aviso",
  threshold: "Umbral",
};

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "ahora";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} d`;
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
  });
}

export default function Navbar({ onMenuClick }: NavbarProps = {}) {
  const [alerts, setAlerts] = useState<AlertWithPlayer[]>([]);
  const [open, setOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { categories, categoryId, setCategoryId } = useCategoryContext();

  // Poll active alerts on mount + every 30s. Failures are silent so a
  // backend hiccup doesn't render a broken navbar — the badge just won't
  // refresh until the next successful poll.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api<AlertWithPlayer[]>(
          `/alerts?status=active&limit=${MAX_DROPDOWN_ITEMS}`,
        );
        if (!cancelled) {
          setAlerts(data);
          setLoadError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof ApiError ? err.message : "Error");
        }
      }
    };
    load();
    const id = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Click-outside-to-close.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!dropdownRef.current) return;
      if (!dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const dismiss = async (alert: AlertWithPlayer) => {
    // Optimistic remove — the badge decrements immediately.
    setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
    try {
      await api(`/alerts/${alert.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "dismissed" }),
      });
    } catch {
      // Revert on failure: refetch authoritative state.
      try {
        const fresh = await api<AlertWithPlayer[]>(
          `/alerts?status=active&limit=${MAX_DROPDOWN_ITEMS}`,
        );
        setAlerts(fresh);
      } catch {
        /* ignore */
      }
    }
  };

  const count = alerts.length;

  return (
    <header className={styles.navbar}>
      <div className={styles.leftSection}>
        {onMenuClick && (
          <button
            type="button"
            className={styles.menuToggle}
            onClick={onMenuClick}
            aria-label="Abrir menú"
          >
            <Menu size={20} />
          </button>
        )}
        <div className={styles.slabLogo}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L17 7L12 12L7 7L12 2Z" stroke="white" strokeWidth="1.5" />
            <path d="M12 12L17 17L12 22L7 17L12 12Z" stroke="white" strokeWidth="1.5" />
            <path d="M7 7L12 12L7 17L2 12L7 7Z" stroke="white" strokeWidth="1.5" />
            <path d="M17 7L22 12L17 17L12 12L17 7Z" stroke="white" strokeWidth="1.5" />
          </svg>
          SLAB
        </div>
        <div className={styles.teamDivider}></div>
        <div className={styles.teamSection}>
          <div className={styles.teamLogo}>U</div>
          <div className={styles.teamText}>
            <h1 className={styles.teamTitle}>Perfil Jugadores — Universidad de Chile</h1>
            <p className={styles.teamSubtitle}>Información integral de los jugadores del club</p>
          </div>
        </div>
      </div>
      <div className={styles.rightSection}>
        {categories.length > 0 && (
          <label className={styles.categoryPicker}>
            <span className={styles.categoryPickerHint}>Categoría</span>
            <select
              className={styles.categorySelect}
              value={categoryId ?? ""}
              onChange={(e) => setCategoryId(e.target.value)}
              aria-label="Seleccionar categoría"
            >
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
        )}
        <button className={styles.iconButton} aria-label="Search">
          <Search size={18} />
        </button>
        <div className={styles.bellWrapper} ref={dropdownRef}>
          <button
            type="button"
            className={styles.iconButton}
            aria-label={`Notificaciones${count > 0 ? ` (${count} activas)` : ""}`}
            aria-haspopup="true"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <Bell size={18} />
            {count > 0 && (
              <span className={styles.badge}>{count > 99 ? "99+" : count}</span>
            )}
          </button>
          {open && (
            <div className={styles.dropdown} role="menu">
              <div className={styles.dropdownHeader}>
                <span className={styles.dropdownTitle}>Alertas activas</span>
                <span className={styles.dropdownCount}>{count}</span>
              </div>
              {loadError && (
                <div className={styles.dropdownError}>{loadError}</div>
              )}
              {count === 0 ? (
                <div className={styles.dropdownEmpty}>
                  No hay alertas pendientes.
                </div>
              ) : (
                <ul className={styles.alertList}>
                  {alerts.map((a) => (
                    <li key={a.id} className={styles.alertItem}>
                      <span
                        className={`${styles.severityBar} ${styles[a.severity] ?? ""}`}
                        aria-hidden="true"
                      />
                      <div className={styles.alertBody}>
                        <div className={styles.alertHeader}>
                          <span className={styles.playerName}>
                            {a.player_first_name} {a.player_last_name}
                          </span>
                          {a.player_category_name && (
                            <span className={styles.playerCategory}>
                              · {a.player_category_name}
                            </span>
                          )}
                          <span className={styles.alertWhen}>
                            {formatRelative(a.last_fired_at ?? a.fired_at)}
                          </span>
                        </div>
                        <div className={styles.alertMessage}>
                          <span className={styles.alertSourceTag}>
                            {SOURCE_LABELS[a.source_type] ?? a.source_type}
                          </span>
                          {a.message}
                          {a.trigger_count > 1 && (
                            <span className={styles.triggerCount}>
                              · ×{a.trigger_count}
                            </span>
                          )}
                        </div>
                        <div className={styles.alertActions}>
                          <Link
                            href={`/perfil/${a.player_id}?tab=objetivos`}
                            className={styles.alertLink}
                            onClick={() => setOpen(false)}
                          >
                            Ver
                          </Link>
                          <button
                            type="button"
                            className={styles.alertDismissBtn}
                            onClick={() => dismiss(a)}
                          >
                            Descartar
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
