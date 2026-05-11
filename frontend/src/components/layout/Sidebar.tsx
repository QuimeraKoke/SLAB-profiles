"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users,
  User,
  BarChart3,
  ChevronDown,
  ChevronRight,
  LogOut,
  Settings,
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
}

const STATIC_NAV: NavGroup[] = [
  { label: "Equipo", icon: Users, href: "/equipo" },
  { label: "Perfil", icon: User, href: "/perfil" },
];

const SETTINGS_NAV: NavGroup = {
  label: "Configuraciones",
  icon: Settings,
  subItems: [
    { label: "Jugadores", href: "/configuraciones/jugadores" },
    { label: "Partidos", href: "/partidos" },
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
  const [expandedItems, setExpandedItems] = useState<string[]>([
    "Reportes",
    "Configuraciones",
  ]);
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

  const navItems: NavGroup[] = [
    ...STATIC_NAV,
    ...(reportsGroup ? [reportsGroup] : []),
    SETTINGS_NAV,
  ];

  const toggleExpand = (label: string, e: React.MouseEvent) => {
    e.preventDefault();
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

      <nav className={styles.navMenu}>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isExpanded = expandedItems.includes(item.label);
          const isActive =
            (item.href && pathname === item.href) ||
            (item.subItems &&
              item.subItems.some((s) => pathname === s.href || pathname.startsWith(`${s.href}/`)));

          return (
            <div key={item.label}>
              {item.subItems ? (
                <div
                  className={`${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                  onClick={(e) => toggleExpand(item.label, e)}
                  style={{ cursor: "pointer" }}
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
                </div>
              ) : (
                <Link
                  href={item.href!}
                  className={`${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                  onClick={onClose}
                >
                  <div className={styles.navItemLeft}>
                    <Icon size={18} className={styles.icon} />
                    <span>{item.label}</span>
                  </div>
                </Link>
              )}

              {item.subItems && isExpanded && (
                <div className={styles.subItemsList}>
                  {item.subItems.map((subItem) => {
                    const isSubActive = pathname === subItem.href;
                    return (
                      <Link
                        key={subItem.href}
                        href={subItem.href}
                        className={`${styles.subItem} ${isSubActive ? styles.subItemActive : ""}`}
                        onClick={onClose}
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
