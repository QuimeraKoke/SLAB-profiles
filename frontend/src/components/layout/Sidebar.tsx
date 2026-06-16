"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  User,
  BarChart3,
  Calendar,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
  TrendingUp,
  X,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
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
}

// QW-10: Partidos promoted to a top-level entry — it's a daily flow for
// técnico/físico, not a setting. Roster CRUD lives under Administración
// (formerly "Configuraciones"; see IA-1 below).
const STATIC_NAV: NavGroup[] = [
  { label: "Equipo", icon: Users, href: "/equipo", activePrefixes: ["/perfil"] },
  { label: "Partidos", icon: Calendar, href: "/partidos" },
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
  // L3: only the group containing the current route is expanded by default.
  // Falls back to "Reportes" so first-time users on /equipo see the
  // department list at a glance. Manual toggles still work via toggleExpand.
  const [expandedItems, setExpandedItems] = useState<string[]>(() => {
    if (pathname.startsWith("/configuraciones")) return ["Administración"];
    if (pathname.startsWith("/reportes")) return ["Reportes"];
    return ["Reportes"];
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
          label: "Reportes",
          icon: BarChart3,
          subItems: departments.map((d) => ({
            label: d.name,
            href: `/reportes/${d.slug}`,
          })),
        }
      : null;

  // Admin-only "Uso" link — adoption / engagement chart. Superusers see it
  // regardless of membership; non-admins don't even get the nav entry.
  const usoItem: NavGroup | null = user?.is_superuser
    ? { label: "Uso", icon: TrendingUp, href: "/uso" }
    : null;

  // IA-2: visually group navigation by frequency-of-use (audit principle
   // #4). Operativa = daily; Análisis = read-only insight; Administración
   // = lower-traffic admin. A full role-aware nav (audit IA-2 long-term)
   // would also hide irrelevant groups per role; for now everyone sees
   // every group they have access to, just spatially grouped.
  const navSections: Array<{ label: string | null; items: NavGroup[] }> = [
    {
      label: "Operativa",
      items: STATIC_NAV,
    },
    ...(reportsGroup
      ? [{ label: "Análisis", items: [reportsGroup, ...(usoItem ? [usoItem] : [])] }]
      : usoItem
        ? [{ label: "Análisis", items: [usoItem] }]
        : []),
    {
      label: "Administración",
      items: [SETTINGS_NAV],
    },
  ];

  // Flat list still used by the iteration below (preserve existing
  // expansion logic + active-state matching). Sections only add visual
  // grouping headers, not behavior changes.
  const navItems: NavGroup[] = navSections.flatMap((s) => s.items);

  // QW-7: was an inline onClick with preventDefault on a <div>. Now invoked
  // from a real <button>, so no preventDefault is needed.
  const toggleExpand = (label: string) => {
    setExpandedItems((prev) =>
      prev.includes(label) ? prev.filter((item) => item !== label) : [...prev, label],
    );
  };

  return (
    <aside
      className={`${styles.sidebar} ${open ? styles.sidebarOpen : ""}`}
      aria-hidden={!open ? undefined : false}
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
          const matchesHref = item.href && pathname === item.href;
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
