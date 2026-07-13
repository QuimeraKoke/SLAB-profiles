"use client";

import React from "react";
import Link from "next/link";
import { Clock } from "lucide-react";

import Modal from "@/components/ui/Modal/Modal";
import type { BriefingItem } from "./types";
import styles from "./ActionModal.module.css";

/**
 * "Ver info" (§7.2) — the full context behind a briefing card: the alert
 * message, the concrete evidence (numbers/dates), timing + owner, confidence,
 * and the affected players as deep-links to their ficha. (A metric chart
 * derived from the triggering alert is a planned follow-up.)
 */
export default function BriefingInfoModal({
  open,
  onClose,
  item,
  nameById,
}: {
  open: boolean;
  onClose: () => void;
  item: BriefingItem;
  nameById: Map<string, string>;
}) {
  return (
    <Modal open={open} title={item.title} onClose={onClose}>
      <div className={styles.body}>
        <div className={styles.recBox}>
          <span className={styles.recLabel}>Recomendación</span>
          {item.recommendation}
        </div>

        {item.evidence.length > 0 && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Evidencia</div>
            <ul className={styles.evList}>
              {item.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        )}

        <div className={styles.metaRow}>
          {item.owner_role && <span className={styles.metaTag}>{item.owner_role}</span>}
          {item.timing && (
            <span className={styles.metaTag}>
              <Clock size={12} aria-hidden="true" /> {item.timing}
            </span>
          )}
          <span className={styles.metaTag}>Confianza {item.confidence}%</span>
        </div>

        {item.player_ids.length > 0 && (
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Jugadores</div>
            <div className={styles.playerLinks}>
              {item.player_ids.map((id) => (
                <Link
                  key={id}
                  href={`/perfil/${id}?tab=${item.department}`}
                  className={styles.playerLink}
                  onClick={onClose}
                >
                  {nameById.get(id) ?? "Ver ficha"}
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
