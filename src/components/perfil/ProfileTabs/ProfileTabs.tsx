import React from 'react';
import { Settings } from 'lucide-react';
import styles from './ProfileTabs.module.css';

interface ProfileTabsProps {
  activeTab: string;
  onTabChange: (tabId: string) => void;
}

export const tabs = [
  { id: 'resumen', label: 'Resumen' },
  { id: 'estadisticas', label: 'Estadísticas' },
  { id: 'desempeno', label: 'Desempeño' },
  { id: 'medico', label: 'Médico' },
  { id: 'nutricional', label: 'Nutricional' },
  { id: 'psicosocial', label: 'Psicosocial' },
  { id: 'tecnica', label: 'Técnica', icon: Settings },
];

export default function ProfileTabs({ activeTab, onTabChange }: ProfileTabsProps) {
  return (
    <div className={styles.container}>
      {tabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`${styles.tab} ${activeTab === tab.id ? styles.activeTab : ''}`}
          >
            {Icon && <Icon size={14} />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
