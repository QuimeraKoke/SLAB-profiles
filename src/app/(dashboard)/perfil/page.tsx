"use client";

import React, { useState } from 'react';
import styles from './page.module.css';
import ProfileHeader from '@/components/perfil/ProfileHeader/ProfileHeader';
import ProfileTabs from '@/components/perfil/ProfileTabs/ProfileTabs';
import ProfileSummary from '@/components/perfil/ProfileSummary/ProfileSummary';
import ProfileStatistics from '@/components/perfil/ProfileStatistics/ProfileStatistics';
import ProfilePerformance from '@/components/perfil/ProfilePerformance/ProfilePerformance';
import ProfileMedical from '@/components/perfil/ProfileMedical/ProfileMedical';
import ProfileNutritional from '@/components/perfil/ProfileNutritional/ProfileNutritional';

export default function PerfilPage() {
  const [activeTab, setActiveTab] = useState('nutricional');

  return (
    <div className={styles.container}>
      <ProfileHeader />
      <ProfileTabs activeTab={activeTab} onTabChange={setActiveTab} />
      
      <div className={styles.contentArea}>
        {activeTab === 'resumen' && <ProfileSummary />}
        {activeTab === 'estadisticas' && <ProfileStatistics />}
        {activeTab === 'desempeno' && <ProfilePerformance />}
        {activeTab === 'medico' && <ProfileMedical />}
        {activeTab === 'nutricional' && <ProfileNutritional />}
        {activeTab !== 'resumen' && activeTab !== 'estadisticas' && activeTab !== 'desempeno' && activeTab !== 'medico' && activeTab !== 'nutricional' && (
          <div className={styles.placeholder}>
            Contenido para {activeTab} en construcción...
          </div>
        )}
      </div>
    </div>
  );
}
