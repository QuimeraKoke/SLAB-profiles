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
      case "available":
        return "Disponible";
      case "reintegration":
        return "Return to Train";
      case "recovery":
        return "Recuperación";
      case "injured":
        return "Lesionado";
      // Legacy values kept for graceful fallback.
      case "healthy":
        return "Disponible";
      case "recuperation":
        return "Recuperación";
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

  // The caller (equipo/page.tsx) handles all empty states — distinguishes
  // "roster is empty" from "search returned nothing" from "status filter
  // matched nothing". Returning null here avoids a misleading "roster
  // empty" message when there are actually 30 players, just none matching.
  if (players.length === 0) return null;

  return (
    <div className={styles.tableContainer}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Jugador</th>
            <th>Posición</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {/* QW-9: stretched-link pattern. The Link spans the row via
              ::after { inset: 0 }, so clicking anywhere on the row
              navigates. The name cell stays the screen-reader-visible
              affordance, the rest of the cells become decorative content
              inside the same click target. */}
          {players.map((player) => (
            <tr key={player.id} className={styles.row}>
              <td className={styles.nameCell}>
                <div className={styles.avatarPlaceholder} aria-hidden="true">
                  {getInitials(player.name)}
                </div>
                <Link
                  href={`/perfil/${player.id}`}
                  className={styles.stretchedLink}
                >
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
