"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Grid,
  Users,
  User,
  TrendingUp,
  Crosshair,
  Plus,
  TreeDeciduous,
  Award,
  Edit,
  CheckSquare,
  Network,
  Menu,
  ChevronDown,
  ChevronRight,
  Shield,
  Settings,
} from "lucide-react";
import styles from "./Sidebar.module.css";

const navItems = [
  { label: "Panel", icon: Grid, href: "#" },
  { label: "Equipo", icon: Users, href: "/equipo" },
  { label: "Perfil", icon: User, href: "/perfil" },
  { label: "Estadísticas", icon: TrendingUp, href: "#" },
  { label: "Desempeño", icon: Crosshair, href: "#", hasDropdown: true },
  { label: "Médico", icon: Plus, href: "#" },
  { 
    label: "Nutricional", 
    icon: TreeDeciduous, 
    href: "#",
    hasDropdown: true,
    subItems: [
      { label: "Resumen", href: "/nutricional/resumen" },
      { label: "5C Version 1", href: "/nutricional/5c-v1" },
      { label: "5C Version 2", href: "/nutricional/5c-v2" },
      { label: "5C Version 3", href: "/nutricional/5c-v3" }
    ]
  },
  { label: "Psicosocial", icon: Award, href: "#" },
  { label: "Técnica", icon: Edit, href: "#", hasBadge: true },
  { label: "Tareas", icon: CheckSquare, href: "#" },
  { label: "Organización", icon: Network, href: "#" },
  {
    label: "Configuraciones",
    icon: Settings,
    href: "#",
    hasDropdown: true,
    subItems: [
      { label: "Partidos", href: "/partidos" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [expandedItems, setExpandedItems] = useState<string[]>([]);

  const toggleExpand = (label: string, e: React.MouseEvent) => {
    e.preventDefault();
    setExpandedItems(prev => 
      prev.includes(label) ? prev.filter(item => item !== label) : [...prev, label]
    );
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.profileSection}>
        <div className={styles.avatar}>
          <User size={24} color="#6b7280" />
        </div>
        <div className={styles.profileInfo}>
          <h2 className={styles.profileName}>Juan Ignacio Cuevas</h2>
          <p className={styles.profileRole}>Reporte</p>
        </div>
      </div>

      <nav className={styles.navMenu}>
        {navItems.map((item, index) => {
          const Icon = item.icon;
          const isExpanded = expandedItems.includes(item.label);
          // Set active state based on pathname properly
          const isActive =
            pathname === item.href ||
            (item.subItems && item.label === "Nutricional" && pathname.startsWith("/nutricional")) ||
            (item.subItems && item.label === "Configuraciones" && pathname.startsWith("/partidos"));

          return (
            <div key={index}>
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
                  {isExpanded ? <ChevronDown size={16} className={styles.icon} /> : <ChevronRight size={16} className={styles.icon} />}
                </div>
              ) : (
                <Link 
                  href={item.href} 
                  className={`${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                >
                  <div className={styles.navItemLeft}>
                    <Icon size={18} className={styles.icon} />
                    <span>{item.label}</span>
                  </div>
                  
                  {item.hasDropdown && <ChevronDown size={16} className={styles.icon} />}
                  {item.hasBadge && (
                    <div className={styles.badgeIcon}>
                      <Shield size={14} strokeWidth={2.5} />
                    </div>
                  )}
                </Link>
              )}
              
              {/* Render SubMenu */}
              {item.subItems && isExpanded && (
                <div className={styles.subItemsList}>
                  {item.subItems.map((subItem, subIndex) => {
                    const isSubActive = pathname === subItem.href;
                    return (
                      <Link 
                        key={subIndex} 
                        href={subItem.href}
                        className={`${styles.subItem} ${isSubActive ? styles.subItemActive : ""}`}
                      >
                        {subItem.label}
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className={styles.bottomSection}>
        <button className={styles.collapseButton}>
          <Menu size={18} className={styles.icon} />
          <span>Contraer</span>
        </button>
      </div>
    </aside>
  );
}
