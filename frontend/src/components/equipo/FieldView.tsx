import React from 'react';
import styles from './FieldView.module.css';
import SoccerField from './SoccerField';
import type { EquipoPlayerRow } from './PlayerTable';

interface FieldViewProps {
  players: EquipoPlayerRow[];
}

export default function FieldView({ players }: FieldViewProps) {
  // Status values come from the backend: available / injured / recovery /
  // reintegration. Earlier this used "healthy" / "recuperation" which
  // never matched, so every counter rendered 0.
  const availableCount = players.filter(p => p.status === 'available').length;
  const recuperatingCount = players.filter(
    p => p.status === 'recovery' || p.status === 'reintegration',
  ).length;
  const injuredCount = players.filter(p => p.status === 'injured').length;
  const totalPlayers = players.length;

  const availablePct = totalPlayers === 0 ? 0 : (availableCount / totalPlayers) * 100;
  const recuperatingPct = totalPlayers === 0 ? 0 : (recuperatingCount / totalPlayers) * 100;
  const injuredPct = totalPlayers === 0 ? 0 : (injuredCount / totalPlayers) * 100;

  return (
    <div className={styles.fieldViewContainer}>
      <div className={styles.leftColumn}>
        <SoccerField players={players} />
      </div>

      <div className={styles.rightColumn}>

        {/* Formación Card */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Formación</h3>
          <div className={styles.formationNumber}>4-3-3</div>
          <div className={styles.formationStats}>
            <div className={styles.statRow}>
              <span>Defensa:</span>
              <span className={styles.statValue}>4 jugadores</span>
            </div>
            <div className={styles.statRow}>
              <span>Mediocampo:</span>
              <span className={styles.statValue}>3 jugadores</span>
            </div>
            <div className={styles.statRow}>
              <span>Delantera:</span>
              <span className={styles.statValue}>3 jugadores</span>
            </div>
          </div>
        </div>

        {/* Leyenda de Estado Card */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Leyenda de Estado</h3>
          <div className={styles.legendContainer}>
            <div className={styles.legendRow}>
              <div className={`${styles.legendDot} ${styles.dotBlue}`} />
              <span>Alta - Disponible</span>
            </div>
            <div className={styles.legendRow}>
              <div className={`${styles.legendDot} ${styles.dotOrange}`} />
              <span>Recuperación</span>
            </div>
            <div className={styles.legendRow}>
              <div className={`${styles.legendDot} ${styles.dotRed}`} />
              <span>Lesionado</span>
            </div>
          </div>
        </div>

        {/* Resumen del Plantel Card */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Resumen del Plantel</h3>

          <div className={styles.progressContainer}>
            <div className={styles.progressHeader}>
              <span>Jugadores disponibles</span>
              <span className={styles.textGreen}>{availableCount}</span>
            </div>
            <div className={styles.progressBarBg}>
              <div className={styles.progressBarGreen} style={{ width: `${availablePct}%` }} />
            </div>
          </div>

          <div className={styles.progressContainer}>
            <div className={styles.progressHeader}>
              <span>En recuperación</span>
              <span className={styles.textOrange}>{recuperatingCount}</span>
            </div>
            <div className={styles.progressBarBg}>
              <div className={styles.progressBarOrange} style={{ width: `${recuperatingPct}%` }} />
            </div>
          </div>

          <div className={styles.progressContainer}>
            <div className={styles.progressHeader}>
              <span>Lesionados</span>
              <span className={styles.textRed}>{injuredCount}</span>
            </div>
            <div className={styles.progressBarBg}>
              <div className={styles.progressBarRed} style={{ width: `${injuredPct}%` }} />
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
