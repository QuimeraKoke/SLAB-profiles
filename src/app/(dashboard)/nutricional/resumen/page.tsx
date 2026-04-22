import React from "react";
import styles from "../nutricional.module.css";

export default function NutricionalResumenPage() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Nutricional - Resumen</h1>
      </header>
      <div className={styles.content}>
        <div className={styles.placeholder}>
          <p>Contenido del resumen nutricional irá aquí.</p>
        </div>
      </div>
    </div>
  );
}
