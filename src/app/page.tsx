"use client";

import styles from "./page.module.css";
import { useAuth } from "@/context/AuthContext";

export default function Home() {
  const { user, logout } = useAuth();
  
  if (!user) return null; // Prevent showing flash of content before redirect

  return (
    <main className={styles.container}>
      {/* Background ambient lighting */}
      <div className={styles.background}>
        <div className={styles.blob1}></div>
        <div className={styles.blob2}></div>
      </div>

      <div className={styles.content}>
        <div style={{ position: "absolute", top: "-50px", right: 0 }}>
          <button 
            onClick={logout}
            style={{ 
              padding: "0.5rem 1rem", 
              background: "rgba(255,255,255,0.1)", 
              border: "1px solid rgba(255,255,255,0.2)",
              color: "white",
              borderRadius: "8px",
              cursor: "pointer"
            }}
          >
            Logout ({user.email})
          </button>
        </div>
        
        <div className={styles.badge}>v2.0 Early Access</div>
        
        <h1 className={styles.title}>
          Slab Profiles
        </h1>
        
        <p className={styles.subtitle}>
          The ultimate platform for managing, tracking, and analyzing construction profiles with unprecedented clarity.
        </p>

        <button className={styles.button}>
          Get Started
        </button>

        <div className={styles.cards}>
          <div className={styles.card}>
            <div className={styles.cardIcon}>✦</div>
            <h2 className={styles.cardTitle}>Precision Analytics</h2>
            <p className={styles.cardText}>
              Gain deep insights into your supply chain with our state-of-the-art analytical tools.
            </p>
          </div>
          <div className={styles.card}>
            <div className={styles.cardIcon}>⚡</div>
            <h2 className={styles.cardTitle}>Real-time Sync</h2>
            <p className={styles.cardText}>
              Instantly synchronize data across teams for seamless collaboration and execution.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
