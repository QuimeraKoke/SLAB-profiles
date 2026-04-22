import React from 'react';
import styles from './PlayerTable.module.css';

interface Player {
  id: number;
  name: string;
  position: string;
  status: string;
  warning: string;
}

interface PlayerTableProps {
  players: Player[];
}

export default function PlayerTable({ players }: PlayerTableProps) {
  
  const getStatusLabel = (status: string) => {
    switch(status) {
      case 'healthy': return 'Alta';
      case 'recuperation': return 'Recuperación';
      case 'injured': return 'Lesionado';
      default: return status;
    }
  };

  const getInitials = (name: string) => {
    const parts = name.split(' ').filter(Boolean);
    if (parts.length === 0) return '';
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
  };

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
          {players.map(player => (
            <tr 
              key={player.id} 
              className={styles.row}
            >
              <td className={styles.nameCell}>
                <div className={styles.avatarPlaceholder}>
                  {getInitials(player.name)}
                </div>
                {player.name}
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
