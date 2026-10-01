"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  User,
  BarChart3,
  Calendar,
  GitCompareArrows,
  LayoutDashboard,
  Activity,
  Database,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
  Ruler,
  Sparkles,
  Sunrise,
  TrendingUp,
  X,
} from "lucide-react";

import { api } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { useAuth } from "@/context/AuthContext";
import { hasPermission } from "@/lib/permissions";
import { useAssistant } from "@/context/AssistantContext";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { TEAM_LAYOUTS_CHANGED } from "@/components/reports/LayoutManager";
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
  /** A third level: a department with several team layouts lists them here
   *  (Dashboard → Médico → General / Lesiones). The first child is what
   *  `href` itself opens. */
  children?: NavLeaf[];
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
  const { categoryId } = useCategoryContext();
  const [departments, setDepartments] = useState<Department[]>([]);

  // Fetch the departments visible to this user. `/clubs/{id}/departments`
  // already applies StaffMembership scoping — non-admins only see the
  // departments their membership grants. Platform admins (no membership)
  // skip this call and the Reportes group simply doesn't render.
  //
  // `with_team_layout_for` narrows it to the departments that actually have a
  // team report configured for the selected category: the submenu links to
  // `/reportes/{slug}`, and without a layout that page has nothing to draw.
  // A team layout is per (department, category), so this re-fetches when the
  // picker changes — the Formativo, for instance, has Físico in all 12 series
  // but Táctico only in the 8 that play matches.
  // Bumped when the report's layout manager creates/renames/reorders/deletes
  // a layout, so the Dashboard submenu reflects it without a reload.
  const [layoutsVersion, setLayoutsVersion] = useState(0);
  useEffect(() => {
    const bump = () => setLayoutsVersion((v) => v + 1);
    window.addEventListener(TEAM_LAYOUTS_CHANGED, bump);
    return () => window.removeEventListener(TEAM_LAYOUTS_CHANGED, bump);
  }, []);

  useEffect(() => {
    if (!membership || !categoryId) return;
    let cancelled = false;
    const qs = `?with_team_layout_for=${encodeURIComponent(categoryId)}`;
    api<Department[]>(`/clubs/${membership.club.id}/departments${qs}`)
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
  }, [membership, categoryId, layoutsVersion]);

  const reportsGroup: NavGroup | null =
    departments.length > 0
      ? {
          label: "Dashboard",
          icon: BarChart3,
          // One layout → a plain item, exactly as before. Several → the
          // department becomes a submenu of its layouts, in menu order.
          subItems: departments.map((d) => {
            const layouts = d.team_layouts ?? [];
            return {
              label: d.name,
              href: `/reportes/${d.slug}`,
              ...(layouts.length > 1
                ? { children: layouts.map((l) => ({ label: l.name, href: `/reportes/${d.slug}/${l.slug}` })) }
                : {}),
            };
          }),
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
  // Cohort development: reads across seasons, so it belongs in Análisis rather
  // than beside the daily flows.
  const canViewDevelopment = hasPermission(user, "core.view_development");

  const desarrolloItem: NavGroup = {
    label: "Desarrollo",
    icon: TrendingUp,
    href: "/desarrollo",
  };

  // Parallel to Desarrollo rather than nested in it: that one asks "does he play
  // above his age group?", this one "where is he in his growth?".
  const crecimientoItem: NavGroup = {
    label: "Crecimiento",
    icon: Ruler,
    href: "/crecimiento",
  };

  // Al mismo nivel que Dashboard y no anidado en "Datos": es una superficie de
  // lectura por derecho propio, no una utilidad de carga/exportación como sus
  // vecinos de allá.
  //
  // Detrás de `core.view_player_comparison`, hoy otorgado a nadie. Expone los
  // valores de cualquier jugador del club —el plantel profesional incluido—
  // así que se muestra sólo a quien tenga la llave. Ocultar el link es
  // cosmético: la puerta real es el @require_perm del endpoint.
  const compararItem: NavGroup = {
    label: "Comparar jugadores",
    icon: GitCompareArrows,
    href: "/comparar",
  };

  const navSections: Array<{ label: string | null; items: NavGroup[] }> = [
    {
      label: "Operativa",
      items: STATIC_NAV,
    },
    {
      label: "Análisis",
      items: [
        ...(reportsGroup ? [reportsGroup] : []),
        ...(hasPermission(user, "core.view_player_comparison")
          ? [compararItem] : []),
        // Detrás de `core.view_development`, hoy otorgado a nadie. Ocultar el
        // link es cosmético: la puerta real son los @require_perm del backend.
        // Pero un link que lleva a "no tenés permiso" es peor que no tenerlo.
        ...(canViewDevelopment ? [desarrolloItem, crecimientoItem] : []),
        datosGroup,
        askAiItem,
      ],
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
                    if (subItem.children) {
                      return (
                        <NestedGroup key={subItem.href} item={subItem} active={isSubActive}
                          pathname={pathname} onNavigate={onClose} />
                      );
                    }
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


/** A sub-item with its own children — the third level of the menu. Opens by
 *  itself when the current page is inside it, and toggles with its chevron
 *  otherwise. The first child is also active at the parent's own URL, which
 *  opens the same layout. */
function NestedGroup({
  item, active, pathname, onNavigate,
}: {
  item: NavLeaf;
  active: boolean;
  pathname: string;
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(active);
  // Follow navigation INTO the group (from a link elsewhere), never close it
  // behind the user's back — the "adjust state during render" pattern.
  const [prevActive, setPrevActive] = useState(active);
  if (prevActive !== active) {
    setPrevActive(active);
    if (active) setOpen(true);
  }
  const panelId = `nav-${item.href.replace(/[^a-z0-9]/gi, "-")}`;
  const children = item.children ?? [];
  return (
    <div>
      <button type="button"
        className={`${styles.subItem} ${styles.subGroupToggle} ${active ? styles.subGroupActive : ""}`}
        aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}>
        <span>{item.label}</span>
        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
      </button>
      <div id={panelId} className={styles.subSubList} hidden={!open}>
        {children.map((c, i) => {
          const isActive = pathname === c.href || pathname.startsWith(`${c.href}/`)
            || (i === 0 && pathname === item.href);
          return (
            <Link key={c.href} href={c.href} onClick={onNavigate}
              className={`${styles.subItem} ${styles.subSubItem} ${isActive ? styles.subSubItemActive : ""}`}
              aria-current={isActive ? "page" : undefined}>
              {c.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
