"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import MatchForm from "@/components/partidos/MatchForm";
import styles from "./page.module.css";

export default function NuevoPartidoPage() {
  const router = useRouter();
  const goBack = () => router.push("/partidos");

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href="/partidos" className={styles.backLink}>
          ← Volver a partidos
        </Link>
        <h1 className={styles.title}>Nuevo partido</h1>
      </header>

      <MatchForm onSaved={goBack} onCancel={goBack} />
    </div>
  );
}
