"use client";

import React from "react";
import Link from "next/link";
import styles from "./page.module.css";

export default function PerfilIndexPage() {
  return (
    <div className={styles.container}>
      <div className={styles.placeholder}>
        Selecciona un jugador desde{" "}
        <Link href="/equipo" style={{ marginLeft: 6 }}>
          el plantel
        </Link>
        .
      </div>
    </div>
  );
}
