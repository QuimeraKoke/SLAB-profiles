import React from 'react';
import { Activity, Thermometer, Stethoscope, FileHeart } from 'lucide-react';
import styles from './ProfileSummary.module.css';

export default function ProfileSummary() {
  return (
    <div className={styles.container}>
      <div className={styles.topRow}>
        
        {/* Estadisticas de Juego */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Activity size={14} />
              ESTADÍSTICAS DE JUEGO
            </div>
          </div>
          <div className={styles.cardList}>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Partidos jugados</span>
              <span className={`${styles.listValue} ${styles.listValueHighlight}`}>18</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>% Minutos</span>
              <span className={`${styles.listValue} ${styles.listValueHighlight}`}>83,58%</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Goles</span>
              <span className={styles.listValue}>2</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Asistencias</span>
              <span className={styles.listValue}>2</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Tarjetas rojas</span>
              <span className={styles.listValue} style={{ color: '#10b981' }}>0</span>
            </div>
          </div>
        </div>

        {/* Rendimiento Físico */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Thermometer size={14} />
              RENDIMIENTO FÍSICO
            </div>
          </div>
          <div className={styles.cardList}>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Distancia media/partido</span>
              <span className={`${styles.listValue} ${styles.listValueHighlight}`}>10.211 m</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>V Max promedio (85-95)</span>
              <span className={styles.listValue}>70,52</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>HIA promedio</span>
              <span className={styles.listValue}>206</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>HMLD promedio</span>
              <span className={styles.listValue}>2.500,05</span>
            </div>
            <div className={styles.listItem}>
              <span className={styles.listLabel}>Aceleraciones promedio</span>
              <span className={styles.listValue}>80</span>
            </div>
          </div>
        </div>

        {/* Reporte Médico */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Stethoscope size={14} />
              REPORTE MÉDICO
            </div>
            <div className={styles.cardHeaderRight}>ÚLTIMAS 3 LESIONES</div>
          </div>
          <div className={styles.cardList}>
            <div className={styles.listItem}>
              <div>
                <span className={styles.listLabel}>Isquiotibiales</span>
                <span className={styles.listLabelLight}>Sobrecarga · 09 mar 2026</span>
              </div>
              <span className={styles.listValueBadgeRed}>ACTIVO</span>
            </div>
            <div className={styles.listItem}>
              <div>
                <span className={styles.listLabel}>Sóleo</span>
                <span className={styles.listLabelLight}>Sobrecarga · 17 jul 2025 - 21 días</span>
              </div>
              <span className={styles.listValueBadge}>ALTA</span>
            </div>
            <div className={styles.listItem}>
              <div>
                <span className={styles.listLabel}>Sóleo</span>
                <span className={styles.listLabelLight}>Sobrecarga · 15 jun 2025 - 15 días</span>
              </div>
              <span className={styles.listValueBadge}>ALTA</span>
            </div>
          </div>
        </div>

      </div>

      {/* Evaluación Psicosocial */}
      <div className={`${styles.card} ${styles.bottomRow}`}>
        <div className={styles.cardHeader}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FileHeart size={14} />
            EVALUACIÓN PSICOSOCIAL
          </div>
        </div>
        <div className={styles.commentsGrid}>
          <div className={styles.commentSection}>
            <span className={styles.commentTitle}>Comentarios Psicólogo</span>
            <span className={styles.commentText}>No aplica</span>
          </div>
          <div className={styles.commentSection}>
            <span className={styles.commentTitle}>Comentarios Trabajador Social</span>
            <span className={styles.commentText}>No aplica</span>
          </div>
        </div>
      </div>
      
    </div>
  );
}
