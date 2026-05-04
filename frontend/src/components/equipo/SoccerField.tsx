import React from 'react';
import styles from './SoccerField.module.css';
import type { EquipoPlayerRow } from './PlayerTable';

interface SoccerFieldProps {
  players: EquipoPlayerRow[];
}

// Slot grid for a generic 4-3-3 view. Each slot points to the position
// abbreviation it pulls from (POR / DF / MC / DEL — matching what the
// seed creates) plus the index of the matching player to render.
type Slot = { top: string; left: string; pos: string; index: number };

const FIELD_SLOTS: Slot[] = [
  // Forwards (3)
  { top: '14%', left: '20%', pos: 'DEL', index: 0 },
  { top: '10%', left: '50%', pos: 'DEL', index: 1 },
  { top: '14%', left: '80%', pos: 'DEL', index: 2 },
  // Midfielders (3)
  { top: '38%', left: '25%', pos: 'MC', index: 0 },
  { top: '44%', left: '50%', pos: 'MC', index: 1 },
  { top: '38%', left: '75%', pos: 'MC', index: 2 },
  // Defenders (4)
  { top: '70%', left: '15%', pos: 'DF', index: 0 },
  { top: '76%', left: '38%', pos: 'DF', index: 1 },
  { top: '76%', left: '62%', pos: 'DF', index: 2 },
  { top: '70%', left: '85%', pos: 'DF', index: 3 },
  // Goalkeeper
  { top: '92%', left: '50%', pos: 'POR', index: 0 },
];

const STATUS_DOT_CLASS: Record<string, string> = {
  available: 'nodeBlue',
  injured: 'nodeRed',
  recovery: 'nodeOrange',
  reintegration: 'nodeYellow',
};

const POSITION_LABEL: Record<string, string> = {
  POR: 'Arqueros',
  DF: 'Defensa',
  MC: 'Mediocampo',
  DEL: 'Delantera',
};

const POSITION_ORDER = ['POR', 'DF', 'MC', 'DEL'];

function shortName(full: string): string {
  const parts = full.split(' ').filter(Boolean);
  if (parts.length <= 1) return full;
  return `${parts[0].charAt(0)}. ${parts.slice(1).join(' ')}`;
}

export default function SoccerField({ players }: SoccerFieldProps) {
  // Bucket players by position abbreviation.
  const byPos = new Map<string, EquipoPlayerRow[]>();
  for (const p of players) {
    const list = byPos.get(p.position) ?? [];
    list.push(p);
    byPos.set(p.position, list);
  }

  // Resolve which player lands at each pitch slot. Track ids so the
  // bench section below shows the rest without duplicates.
  const onFieldIds = new Set<string>();
  const renderedSlots = FIELD_SLOTS.map((slot) => {
    const candidates = byPos.get(slot.pos) ?? [];
    const player = candidates[slot.index];
    if (!player) return null;
    onFieldIds.add(player.id);
    const dotClass = STATUS_DOT_CLASS[player.status] ?? 'nodeBlue';
    return { ...slot, player, dotClass };
  });

  // Bench: anyone the slots couldn't accommodate, kept in their position
  // bucket so the panel stays tactical (Arqueros / Defensa / etc.).
  const benchByPos: Record<string, EquipoPlayerRow[]> = {};
  for (const [pos, list] of byPos.entries()) {
    const extras = list.filter((p) => !onFieldIds.has(p.id));
    if (extras.length > 0) benchByPos[pos] = extras;
  }
  // Players whose position abbreviation isn't in our 4-bucket map (e.g.
  // a custom one the admin set up) — surface them too so nobody hides.
  const unknownExtras = (byPos.get('—') ?? []).filter((p) => !onFieldIds.has(p.id));
  for (const [pos, list] of byPos.entries()) {
    if (!POSITION_ORDER.includes(pos) && pos !== '—') {
      const extras = list.filter((p) => !onFieldIds.has(p.id));
      if (extras.length > 0) {
        benchByPos[pos] = (benchByPos[pos] ?? []).concat(extras);
      }
    }
  }
  if (unknownExtras.length > 0) benchByPos['—'] = unknownExtras;

  const benchKeys = [
    ...POSITION_ORDER.filter((p) => benchByPos[p]),
    ...Object.keys(benchByPos).filter((p) => !POSITION_ORDER.includes(p)),
  ];

  return (
    <div className={styles.fieldWrapper}>
      <div className={styles.fieldContainer}>
        <div className={styles.pitch}>
          {/* Field markings */}
          <div className={styles.centerLine} />
          <div className={styles.centerCircle} />
          <div className={styles.penaltyAreaTop} />
          <div className={styles.penaltyAreaBottom} />
          <div className={styles.goalAreaTop} />
          <div className={styles.goalAreaBottom} />

          {renderedSlots.map((slot) => {
            if (!slot) return null;
            return (
              <div
                key={slot.player.id}
                className={styles.nodeWrapper}
                style={{
                  top: slot.top,
                  left: slot.left,
                  transform: 'translate(-50%, -50%)',
                }}
              >
                <div className={styles.nodeContent}>
                  <div className={`${styles.node} ${styles[slot.dotClass]}`}>
                    <span className={styles.nodePosText}>{slot.player.position}</span>
                  </div>
                  <span className={styles.nodeLabel}>{shortName(slot.player.name)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {benchKeys.length > 0 && (
        <div className={styles.benchSection}>
          <h4 className={styles.benchTitle}>Plantel completo</h4>
          <div className={styles.benchGrid}>
            {benchKeys.map((pos) => (
              <div key={pos} className={styles.benchColumn}>
                <span className={styles.benchPositionLabel}>
                  {POSITION_LABEL[pos] ?? pos}
                </span>
                <ul className={styles.benchList}>
                  {benchByPos[pos].map((p) => {
                    const dotClass = STATUS_DOT_CLASS[p.status] ?? 'nodeBlue';
                    return (
                      <li key={p.id} className={styles.benchPlayer}>
                        <span
                          className={`${styles.benchDot} ${styles[dotClass]}`}
                          aria-hidden="true"
                        />
                        <span className={styles.benchName}>{p.name}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
