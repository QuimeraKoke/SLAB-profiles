import React from 'react';
import { User, FileText } from 'lucide-react';
import styles from './ProfileHeader.module.css';

export default function ProfileHeader() {
  return (
    <div className={styles.container}>
      <div className={styles.leftSection}>
        <div className={styles.avatar}>
          <User size={40} color="#9ca3af" />
        </div>
        <div className={styles.info}>
          <span className={styles.tag}>JUGADOR PRINCIPAL</span>
          <h1 className={styles.name}>Mateo Castillo</h1>
          <div className={styles.details}>
            <span>Mediocampista - Volante Interior</span>
            <span style={{ color: '#d1d5db' }}>|</span>
            <span>36 años (1989-04-17)</span>
            <span style={{ color: '#d1d5db' }}>|</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span role="img" aria-label="Chile">🇨🇱</span> Chile
            </span>
          </div>
        </div>
      </div>

      <div className={styles.rightSection}>
        <div className={styles.clubInfo}>
          {/* using a placeholder box for the club logo if we don't have the image asset */}
          <div className={styles.clubDetails}>
            <span className={styles.clubName}>Universidad de Chile</span>
            <span className={styles.clubAbbr}>UCH</span>
          </div>
          <div 
            style={{ 
              width: 40, 
              height: 48, 
              backgroundColor: '#1E3A8A', 
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              fontWeight: 'bold',
              fontSize: '20px'
            }}
          >
            U
          </div>
        </div>

        <div className={styles.contractInfo}>
          <span className={styles.contractLabel}>CONTRATO VIGENTE</span>
          <span className={styles.contractValue}>CLP 32.500.000 <span>/ mes</span></span>
          <button className={styles.verMasBtn}>
            <FileText size={14} />
            Ver más
          </button>
        </div>
      </div>
    </div>
  );
}
