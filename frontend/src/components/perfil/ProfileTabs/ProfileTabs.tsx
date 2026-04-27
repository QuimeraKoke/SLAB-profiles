import React from 'react';
import styles from './ProfileTabs.module.css';

export interface TabSpec {
  id: string;
  label: string;
}

interface ProfileTabsProps {
  tabs: TabSpec[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
}

export default function ProfileTabs({ tabs, activeTab, onTabChange }: ProfileTabsProps) {
  return (
    <div className={styles.container}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`${styles.tab} ${activeTab === tab.id ? styles.activeTab : ''}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
