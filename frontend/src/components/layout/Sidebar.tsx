"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  User,
  BarChart3,
  Calendar,
  LayoutDashboard,
  Activity,
  Database,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
  Sparkles,
  Sunrise,
  X,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { hasPermission } from "@/lib/permissions";
import { useAssistant } from "@/context/AssistantContext";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import type { ApiUser, Department } from "@/lib/types";
import styles from "./Sidebar.module.css";

/** Best-effort display name. Falls back through:
 *    1. "First Last" (Django auth fields, often empty in older accounts)
 *    2. username
 *    3. email local-part (before the @)
 *    4. empty string — caller renders a generic placeholder.
 */
function displayName(user: ApiUser | null): string {
  if (!user) return "";
  const fullName = `${user.first_name ?? ""} ${user.last_name ?? ""}`.trim();
  if (fullName) return fullName;
  if (user.username) return user.username;
  if (user.email) return user.email.split("@")[0];
  return "";
}

interface NavLeaf {
  label: string;
  href: string;
}

interface NavGroup {
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  /** When set, renders an expandable group; href is unused. */
  subItems?: NavLeaf[];
  href?: string;
  /** Optional list of additional pathname prefixes that should mark this
   *  item as the active nav entry (e.g. /perfil/* → highlight Equipo). */
  activePrefixes?: string[];
  /** Action item (no route) — renders a <button> that runs this on click.
   *  Used by "Ask S-LAB AI" to open the floating chat (NAV-02). */
  onClick?: () => void;
}

// QW-10: Partidos promoted to a top-level entry — it's a daily flow for
// técnico/físico, not a setting. Roster CRUD lives under Administración
// (formerly "Configuraciones"; see IA-1 below).
const STATIC_NAV: NavGroup[] = [
  { label: "Centro de mando", icon: LayoutDashboard, href: "/centro-de-mando" },
  // The 8 AM cross-department planning meeting — a daily flow, so it sits
  // right under the command center in Operativa.
  { label: "Daily", icon: Sunrise, href: "/daily" },
  { label: "Equipo", icon: Users, href: "/equipo", activePrefixes: ["/perfil"] },
  { label: "Partidos", icon: Calendar, href: "/partidos" },
  { label: "Cargar GPS", icon: Activity, href: "/gps-entrenamiento" },
];

// IA-1: "Configuraciones" carried both daily ops (Jugadores) and admin
// surfaces. Renamed to "Administración" to match its actual contents —
// roster management, exam templates, alert rules. Daily ops belong
// elsewhere; the Jugadores entry here remains as the dedicated CRUD
// surface (roster *editing*, not just viewing).
const SETTINGS_NAV: NavGroup = {
  label: "Administración",
  icon: Settings,
  subItems: [
    { label: "Gestionar plantel", href: "/configuraciones/jugadores" },
  ],
};

interface SidebarProps {
  /** Whether the sidebar is shown. Only consumed on tablet/mobile —
   *  desktop CSS forces it visible regardless of this flag. */
  open?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ open = false, onClose }: SidebarProps = {}) {
  const pathname = usePathname();
  const { membership, user, logout } = useAuth();
  const { setOpen: setAssistantOpen } = useAssistant();
  // NAV-06: focus-trap the drawer while open (mobile only — `open` is always
  // false on desktop, so the trap stays inert there). On open it moves focus
  // inside; on close it restores focus to the opener (the navbar hamburger).
  const drawerRef = useFocusTrap<HTMLElement>(open);
  // L3 / NAV-08: expand only the group that contains the active route; on
  // Operativa pages expand nothing (the prior always-expand-Dashboard added
  // noise). Manual toggles still work via toggleExpand. Runs once at mount —
  // the Sidebar stays mounted across client navigation, so switching groups
  // mid-session relies on a manual toggle (acceptable).
  const [expandedItems, setExpandedItems] = useState<string[]>(() => {
    if (pathname.startsWith("/reportes")) return ["Dashboard"];
    if (
      pathname.startsWith("/exportar") || pathname.startsWith("/uso")
      || pathname.startsWith("/subir-datos")
    ) return ["Datos"];
    if (pathname.startsWith("/configuraciones")) return ["Administración"];
    return [];
  });
  const [departments, setDepartments] = useState<Department[]>([]);

  // Fetch the departments visible to this user. `/clubs/{id}/departments`
  // already applies StaffMembership scoping — non-admins only see the
  // departments their membership grants. Platform admins (no membership)
  // skip this call and the Reportes group simply doesn't render.
  useEffect(() => {
    if (!membership) return;
    let cancelled = false;
    api<Department[]>(`/clubs/${membership.club.id}/departments`)
      .then((data) => {
        if (!cancelled) {
          setDepartments(
            [...data].sort((a, b) => a.name.localeCompare(b.name)),
          );
        }
      })
      .catch(() => {
        if (!cancelled) setDepartments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [membership]);

  const reportsGroup: NavGroup | null =
    departments.length > 0
      ? {
          label: "Dashboard",
          icon: BarChart3,
          subItems: departments.map((d) => ({
            label: d.name,
            href: `/reportes/${d.slug}`,
          })),
        }
      : null;

  // "Datos" — el hogar de datos del sidebar (§5/§7.1): Subir datos (carga por
  // equipo, rol con permiso de captura) + Exportar datos (todo el staff) + Uso
  // (solo superuser, movido aquí desde Administración).
  const datosGroup: NavGroup = {
    label: "Datos",
    icon: Database,
    subItems: [
      ...(hasPermission(user, "exams.add_examresult")
        ? [{ label: "Subir datos", href: "/subir-datos" }]
        : []),
      { label: "Exportar datos", href: "/exportar" },
      ...(user?.is_superuser ? [{ label: "Uso", href: "/uso" }] : []),
    ],
  };

  // "Usuarios" (Administración) — only users who can manage staff accounts
  // (Administrador role / superuser) see it. Appended to the static
  // Administración sub-items so managers can onboard the rest of the club.
  const settingsGroup: NavGroup = {
    ...SETTINGS_NAV,
    subItems: [
      ...(SETTINGS_NAV.subItems ?? []),
      // §1.g — Editors configure the alert/threshold engine per category.
      ...(hasPermission(user, "goals.change_alertrule")
        ? [{ label: "Reglas de alerta", href: "/configuraciones/alertas" }]
        : []),
      // Only staff-managers (Administrador / superuser) onboard other users.
      ...(hasPermission(user, "auth.view_user")
        ? [{ label: "Usuarios", href: "/configuraciones/usuarios" }]
        : []),
    ],
  };

  // NAV-02: a discoverable doorway to the floating chat (no dedicated route)
  // — opens the same assistant the FAB does, via AssistantContext.
  const askAiItem: NavGroup = {
    label: "Ask S-LAB AI",
    icon: Sparkles,
    onClick: () => {
      onClose?.();
      setAssistantOpen(true);
    },
  };

  // IA-2: visually group navigation by frequency-of-use (audit principle #4).
  // Operativa = daily; Análisis = read-only insight (dashboards + the S-LAB AI
  // assistant); Administración = lower-traffic admin. NAV-11 moved "Uso" into
  // Administración; NAV-02 added the assistant entry. Role-aware hiding is
  // still TODO (P2) — for now everyone sees every group they can access.
  const navSections: Array<{ label: string | null; items: NavGroup[] }> = [
    {
      label: "Operativa",
      items: STATIC_NAV,
    },
    {
      label: "Análisis",
      items: [...(reportsGroup ? [reportsGroup] : []), datosGroup, askAiItem],
    },
    {
      label: "Administración",
      items: [settingsGroup],
    },
  ];

  // QW-7: was an inline onClick with preventDefault on a <div>. Now invoked
  // from a real <button>, so no preventDefault is needed.
  const toggleExpand = (label: string) => {
    setExpandedItems((prev) =>
      prev.includes(label) ? prev.filter((item) => item !== label) : [...prev, label],
    );
  };

  return (
    <aside
      ref={drawerRef}
      className={`${styles.sidebar} ${open ? styles.sidebarOpen : ""}`}
      tabIndex={-1}
      role={open ? "dialog" : undefined}
      aria-modal={open ? true : undefined}
      aria-label={open ? "Menú de navegación" : undefined}
    >
      <div className={styles.profileSection}>
        <div className={styles.avatar}>
          <User size={24} color="#6b7280" />
        </div>
        <div className={styles.profileInfo}>
          <h2
            className={styles.profileName}
            title={displayName(user) || undefined}
          >
            {displayName(user) || "Sesión activa"}
          </h2>
          {user?.email && (
            <p className={styles.profileRole} title={user.email}>
              {user.email}
            </p>
          )}
        </div>
        {onClose && (
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Cerrar menú"
          >
            <X size={18} />
          </button>
        )}
      </div>

      <nav className={styles.navMenu} aria-label="Navegación principal">
        {navSections.map((section) => (
          <div key={section.label ?? "default"} className={styles.navSection}>
            {section.label && (
              <div className={styles.navSectionLabel}>{section.label}</div>
            )}
            {section.items.map((item) => {
          const Icon = item.icon;
          const isExpanded = expandedItems.includes(item.label);
          // NAV-07: a leaf is active on its own route AND any child route
          // (so /partidos/nuevo highlights "Partidos"). activePrefixes still
          // covers cross-tree cases like /perfil/* → "Equipo".
          const matchesHref = item.href
            ? pathname === item.href || pathname.startsWith(`${item.href}/`)
            : false;
          const matchesPrefix =
            item.activePrefixes?.some((p) => pathname.startsWith(p)) ?? false;
          const matchesSubItem =
            item.subItems?.some(
              (s) => pathname === s.href || pathname.startsWith(`${s.href}/`),
            ) ?? false;
          const isActive = matchesHref || matchesPrefix || matchesSubItem;

          const groupPanelId = `nav-group-${item.label.toLowerCase().replace(/\s+/g, "-")}`;

          return (
            <div key={item.label}>
              {item.subItems ? (
                // QW-7: real <button> with aria-expanded so keyboard /
                // screen-reader users can operate the toggle. Previous
                // <div onClick> was unreachable by keyboard.
                <button
                  type="button"
                  className={`${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                  onClick={() => toggleExpand(item.label)}
                  aria-expanded={isExpanded}
                  aria-controls={groupPanelId}
                >
                  <div className={styles.navItemLeft}>
                    <Icon size={18} className={styles.icon} />
                    <span>{item.label}</span>
                  </div>
                  {isExpanded ? (
                    <ChevronDown size={16} className={styles.icon} />
                  ) : (
                    <ChevronRight size={16} className={styles.icon} />
                  )}
                </button>
              ) : item.onClick ? (
                // NAV-02: action item (no route) — opens the floating chat.
                // A real <button> so it's keyboard-operable.
                <button
                  type="button"
                  className={styles.navItem}
                  onClick={item.onClick}
                >
                  <div className={styles.navItemLeft}>
                    <Icon size={18} className={styles.icon} />
                    <span>{item.label}</span>
                  </div>
                </button>
              ) : (
                // QW-8: aria-current="page" communicates the active route
                // programmatically (visual highlight alone wasn't enough).
                <Link
                  href={item.href!}
                  className={`${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                  onClick={onClose}
                  aria-current={isActive ? "page" : undefined}
                >
                  <div className={styles.navItemLeft}>
                    <Icon size={18} className={styles.icon} />
                    <span>{item.label}</span>
                  </div>
                </Link>
              )}

              {item.subItems && (
                <div
                  id={groupPanelId}
                  className={styles.subItemsList}
                  hidden={!isExpanded}
                >
                  {item.subItems.map((subItem) => {
                    const isSubActive =
                      pathname === subItem.href ||
                      pathname.startsWith(`${subItem.href}/`);
                    return (
                      <Link
                        key={subItem.href}
                        href={subItem.href}
                        className={`${styles.subItem} ${isSubActive ? styles.subItemActive : ""}`}
                        onClick={onClose}
                        aria-current={isSubActive ? "page" : undefined}
                      >
                        {subItem.label}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
            })}
          </div>
        ))}
      </nav>

      <div className={styles.bottomSection}>
        <button
          type="button"
          className={styles.logoutButton}
          onClick={() => {
            // Close the drawer (mobile) then log out — AuthContext.logout
            // clears the token, resets user state, and pushes /login.
            onClose?.();
            logout();
          }}
          aria-label="Cerrar sesión"
        >
          <LogOut size={18} className={styles.icon} />
          <span>Cerrar sesión</span>
        </button>
      </div>
    </aside>
  );
}
