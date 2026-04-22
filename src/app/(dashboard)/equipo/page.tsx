"use client";

import React, { useState } from "react";
import styles from "./page.module.css";
import PlayerTable from "@/components/equipo/PlayerTable";
import PlayerListToolbar from "@/components/equipo/PlayerListToolbar";
import FieldView from "@/components/equipo/FieldView";

export type TabType = 'list' | 'field';

export const mockPlayers = [
  { id: 1, name: "Juan Pérez", position: "POR", status: "healthy", warning: "" },
  { id: 2, name: "Carlos Gómez", position: "LD", status: "healthy", warning: "" },
  { id: 3, name: "Luis Hernández", position: "DFC", status: "recuperation", warning: "Fatiga muscular" },
  { id: 4, name: "Diego López", position: "DFC", status: "healthy", warning: "1 Tirón Abductor" },
  { id: 5, name: "Pedro Silva", position: "LI", status: "healthy", warning: "" },
  { id: 6, name: "Andrés Rojas", position: "MC", status: "healthy", warning: "" },
  { id: 7, name: "Santiago Díaz", position: "MCD", status: "healthy", warning: "" },
  { id: 8, name: "Matías Castro", position: "MC", status: "healthy", warning: "" },
  { id: 9, name: "Ricardo Marín", position: "ED", status: "healthy", warning: "Minutos reducidos" },
  { id: 10, name: "Javier Morales", position: "DC", status: "healthy", warning: "" },
  { id: 11, name: "Alejandro Vargas", position: "EI", status: "injured", warning: "Esguince ligamento" },
  { id: 12, name: "Miguel Torres", position: "POR", status: "healthy", warning: "" },
  { id: 13, name: "Fernando Ruiz", position: "DFC", status: "recuperation", warning: "" },
  { id: 14, name: "Tomás Herrera", position: "MCD", status: "healthy", warning: "" },
  { id: 15, name: "Sebastián Reyes", position: "DC", status: "healthy", warning: "" }
];

export default function EquipoPage() {
  const [activeTab, setActiveTab] = useState<TabType>('list');

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.tabs}>
          <button 
            className={`${styles.tab} ${activeTab === 'list' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('list')}
          >
            Plantel Profesional
          </button>
          <button 
            className={`${styles.tab} ${activeTab === 'field' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('field')}
          >
            Vista de Campo
          </button>
        </div>
      </header>

      <div className={styles.content}>
        {activeTab === 'list' ? (
          <>
            <PlayerListToolbar />
            <PlayerTable players={mockPlayers} />
          </>
        ) : (
          <FieldView players={mockPlayers} />
        )}
      </div>
    </div>
  );
}
