import React from "react";
import Link from "next/link";
import styles from "./PlayerTable.module.css";

export interface EquipoPlayerRow {
  id: string;
  name: string;
  position: string;
  status: string;
  warning: string;
}

interface PlayerTableProps {
  players: EquipoPlayerRow[];
}

export default function PlayerTable({ players }: PlayerTableProps) {
  const getStatusLabel = (status: string) => {
    switch (status) {
      case "healthy":
        return "Alta";
      case "recuperation":
        return "Recuperación";
      case "injured":
        return "Lesionado";
      default:
        return status;
    }
  };

  const getInitials = (name: string) => {
    const parts = name.split(" ").filter(Boolean);
    if (parts.length === 0) return "";
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
  };

  if (players.length === 0) {
    return (
      <div className={styles.tableContainer}>
        <p style={{ padding: 24, color: "#6b7280" }}>
          No hay jugadores registrados todavía.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Jugador</th>
            <th>Posición</th>
            <th>Estado</th>
            <th>Advertencia</th>
          </tr>
        </thead>
        <tbody>
          {players.map((player) => (
            <tr key={player.id} className={styles.row}>
              <td className={styles.nameCell}>
                <div className={styles.avatarPlaceholder}>{getInitials(player.name)}</div>
                <Link href={`/perfil/${player.id}`} style={{ color: "inherit", textDecoration: "none" }}>
                  {player.name}
                </Link>
              </td>
              <td>
                <span className={styles.positionBadge}>{player.position}</span>
              </td>
              <td>
                <div className={`${styles.statusBadge} ${styles[player.status]}`}>
                  <span>{getStatusLabel(player.status)}</span>
                </div>
              </td>
              <td className={styles.warningCell}>
                {player.warning ? (
                  <span className={styles.warningText}>{player.warning}</span>
                ) : (
                  <span className={styles.noWarning}>-</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
