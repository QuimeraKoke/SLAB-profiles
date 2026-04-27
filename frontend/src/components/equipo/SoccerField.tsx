import React from 'react';
import styles from './SoccerField.module.css';
import type { EquipoPlayerRow } from './PlayerTable';

interface SoccerFieldProps {
  players: EquipoPlayerRow[];
}

export default function SoccerField({ players }: SoccerFieldProps) {

  // Renders a specific player node on the field by matching their position
  const renderNode = (top: string, left: string, targetPos: string, matchIndex: number = 0) => {
    // Basic mapping: find the Nth player matching this position
    const matchedPlayers = players.filter(p => p.position === targetPos);
    const player = matchedPlayers[matchIndex];

    if (!player) return null; // If we don't have enough players for this pos, render nothing

    // Format name e.g. "E. Martínez"
    const nameParts = player.name.split(' ').filter(Boolean);
    const shortName = nameParts.length > 1
      ? `${nameParts[0].charAt(0)}. ${nameParts.slice(1).join(' ')}`
      : player.name;

    const dotClass = player.status === 'healthy'
      ? styles.nodeBlue
      : player.status === 'recuperation'
        ? styles.nodeOrange
        : styles.nodeRed;

    return (
      <div
        className={styles.nodeWrapper}
        style={{ top, left, transform: 'translate(-50%, -50%)' }}
        key={player.id}
      >
        <div className={styles.nodeContent}>
           <div className={`${styles.node} ${dotClass}`}>
             <span className={styles.nodePosText}>{targetPos}</span>
           </div>
           <span className={styles.nodeLabel}>{shortName}</span>
        </div>
      </div>
    );
  };

  return (
    <div className={styles.fieldContainer}>
      <div className={styles.pitch}>
        {/* Field markings */}
        <div className={styles.centerLine} />
        <div className={styles.centerCircle} />
        <div className={styles.penaltyAreaTop} />
        <div className={styles.penaltyAreaBottom} />
        <div className={styles.goalAreaTop} />
        <div className={styles.goalAreaBottom} />

        {/* 4-3-3 Formation Nodes (Top to Bottom: Forward to Goalkeeper) */}

        {/* Forwards */}
        {renderNode('18%', '20%', 'EI')}
        {renderNode('14%', '50%', 'DC')}
        {renderNode('18%', '80%', 'ED')}

        {/* Midfielders */}
        {renderNode('42%', '25%', 'MC', 0)}
        {renderNode('48%', '50%', 'MCD')}
        {renderNode('42%', '75%', 'MC', 1)}

        {/* Defenders */}
        {renderNode('75%', '15%', 'LI')}
        {renderNode('82%', '35%', 'DFC', 0)}
        {renderNode('82%', '65%', 'DFC', 1)}
        {renderNode('75%', '85%', 'LD')}

        {/* Goalkeeper */}
        {renderNode('93%', '50%', 'POR', 0)}
      </div>
    </div>
  );
}
