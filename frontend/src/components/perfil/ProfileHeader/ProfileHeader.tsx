import React, { useEffect, useState } from 'react';
import { User, FileText } from 'lucide-react';
import styles from './ProfileHeader.module.css';
import ContractsPanel from '@/components/perfil/ContractsPanel/ContractsPanel';
import Modal from '@/components/ui/Modal/Modal';
import { api } from '@/lib/api';
import type { Alert, PlayerDetail, Sex } from '@/lib/types';

interface ProfileHeaderProps {
  player: PlayerDetail;
}

const SEX_LABEL: Record<Sex, string> = {
  '': '',
  M: 'Masculino',
  F: 'Femenino',
};

const STATUS_LABEL: Record<string, string> = {
  available: 'Disponible',
  injured: 'Lesionado',
  recovery: 'Recuperación',
  reintegration: 'Reintegración',
};

function formatMoney(amount: number | null, currency: string): string {
  if (amount === null) return '—';
  // Compact-style formatting: 50,450,000 → "$50.450.000" with currency suffix.
  const formatted = amount.toLocaleString('es-CL', { maximumFractionDigits: 0 });
  return `${currency} ${formatted}`;
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

  const [activeAlertCount, setActiveAlertCount] = useState(0);
  const [showContracts, setShowContracts] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api<Alert[]>(`/players/${player.id}/alerts?status=active`)
      .then((data) => {
        if (!cancelled) setActiveAlertCount(data.length);
      })
      .catch(() => {
        // Non-fatal — header still renders without the badge.
      });
    return () => {
      cancelled = true;
    };
  }, [player.id]);

  const contract = player.current_contract;

  return (
    <div className={styles.container}>
      <div className={styles.leftSection}>
        <div className={styles.avatar}>
          <User size={40} color="#9ca3af" />
          {activeAlertCount > 0 && (
            <span
              className={styles.alertBadge}
              title={`${activeAlertCount} alerta${activeAlertCount === 1 ? '' : 's'} activa${activeAlertCount === 1 ? '' : 's'}`}
            >
              {activeAlertCount}
            </span>
          )}
        </div>
        <div className={styles.info}>
          <span className={styles.tag}>
            {player.category.name.toUpperCase()}
            {player.status && (
              <span
                className={`${styles.statusPill} ${styles[`status_${player.status}`] ?? ''}`}
                title={
                  player.open_episode_count > 1
                    ? `${player.open_episode_count} episodios abiertos`
                    : undefined
                }
              >
                {STATUS_LABEL[player.status] ?? player.status}
                {player.open_episode_count > 1 && ` · ${player.open_episode_count}`}
              </span>
            )}
          </span>
          <h1 className={styles.name}>{fullName}</h1>
          <div className={styles.details}>
            <span>{positionLine}</span>
            {age !== null && player.date_of_birth && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{age} años ({player.date_of_birth})</span>
              </>
            )}
            {player.sex && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{SEX_LABEL[player.sex]}</span>
              </>
            )}
            {player.current_weight_kg !== null && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{player.current_weight_kg} kg</span>
              </>
            )}
            {player.current_height_cm !== null && (
              <>
                <span style={{ color: '#d1d5db' }}>|</span>
                <span>{player.current_height_cm} cm</span>
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

        <div className={styles.contractInfo}>
          <span className={styles.contractLabel}>CONTRATO VIGENTE</span>
          {contract ? (
            <>
              <span className={styles.contractValue}>
                {contract.season_label}
                {contract.salary_visible && contract.total_gross_amount !== null && (
                  <span> · {formatMoney(contract.total_gross_amount, contract.salary_currency)}</span>
                )}
              </span>
            </>
          ) : (
            <span className={styles.contractValue}>—</span>
          )}
          <button
            className={styles.verMasBtn}
            onClick={() => setShowContracts(true)}
            type="button"
          >
            <FileText size={14} />
            Ver más
          </button>
        </div>
      </div>
      <Modal
        open={showContracts}
        title={`Contratos · ${fullName}`}
        onClose={() => setShowContracts(false)}
      >
        <ContractsPanel playerId={player.id} />
      </Modal>
    </div>
  );
}
