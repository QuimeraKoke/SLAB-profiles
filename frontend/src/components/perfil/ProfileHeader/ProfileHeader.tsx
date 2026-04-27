import React from 'react';
import { User, FileText } from 'lucide-react';
import styles from './ProfileHeader.module.css';
import type { PlayerDetail } from '@/lib/types';

interface ProfileHeaderProps {
  player: PlayerDetail;
}

function calcAge(dob: string | null): number | null {
  if (!dob) return null;
  const birth = new Date(dob);
  if (Number.isNaN(birth.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - birth.getFullYear();
  const m = now.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < birth.getDate())) age -= 1;
  return age;
}

function clubAbbreviation(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
    .slice(0, 4) || '—';
}

export default function ProfileHeader({ player }: ProfileHeaderProps) {
  const fullName = `${player.first_name} ${player.last_name}`.trim();
  const age = calcAge(player.date_of_birth);
  const positionLine = player.position
    ? player.position.role
      ? `${player.position.role} - ${player.position.name}`
      : player.position.name
    : 'Sin posición asignada';

  return (
    <div className={styles.container}>
      <div className={styles.leftSection}>
        <div className={styles.avatar}>
          <User size={40} color="#9ca3af" />
        </div>
        <div className={styles.info}>
          <span className={styles.tag}>{player.category.name.toUpperCase()}</span>
          <h1 className={styles.name}>{fullName}</h1>
          <div className={styles.details}>
            <span>{positionLine}</span>
            {age !== null && player.date_of_birth && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{age} años ({player.date_of_birth})</span>
              </>
            )}
            {player.nationality && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{player.nationality}</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className={styles.rightSection}>
        <div className={styles.clubInfo}>
          <div className={styles.clubDetails}>
            <span className={styles.clubName}>{player.club.name}</span>
            <span className={styles.clubAbbr}>{clubAbbreviation(player.club.name)}</span>
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
              fontSize: '20px',
            }}
          >
            {player.club.name[0]?.toUpperCase() ?? '·'}
          </div>
        </div>

        {/* Contract info is not yet sourced from the API — placeholder retained for layout. */}
        <div className={styles.contractInfo}>
          <span className={styles.contractLabel}>CONTRATO VIGENTE</span>
          <span className={styles.contractValue}>—</span>
          <button className={styles.verMasBtn} disabled>
            <FileText size={14} />
            Ver más
          </button>
        </div>
      </div>
    </div>
  );
}
