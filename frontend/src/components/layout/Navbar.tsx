import React from "react";
import { Search, Bell } from "lucide-react";
import styles from "./Navbar.module.css";

export default function Navbar() {
  return (
    <header className={styles.navbar}>
      <div className={styles.leftSection}>
        <div className={styles.slabLogo}>
          {/* Detailed SVG for the 4 diamonds logo can be improved, here is a simple mockup matching structure */}
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
          <div className={styles.teamLogo}>
            {/* Placeholder for the U shield logo */}
            U
          </div>
          <div className={styles.teamText}>
            <h1 className={styles.teamTitle}>Perfil Jugadores — Universidad de Chile</h1>
            <p className={styles.teamSubtitle}>Información integral de los jugadores del club</p>
          </div>
        </div>
      </div>
      <div className={styles.rightSection}>
        <button className={styles.iconButton} aria-label="Search">
          <Search size={18} />
        </button>
        <button className={styles.iconButton} aria-label="Notifications">
          <Bell size={18} />
          <span className={styles.notificationDot}></span>
        </button>
      </div>
    </header>
  );
}
