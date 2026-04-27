import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import styles from './CollapsibleSection.module.css';

interface CollapsibleSectionProps {
  title: string;
  icon?: React.ElementType;
  controls?: React.ReactNode;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}

export default function CollapsibleSection({ 
  title, 
  icon: Icon, 
  controls,
  children,
  defaultExpanded = true 
}: CollapsibleSectionProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className={styles.container}>
      <div 
        className={`${styles.header} ${isExpanded ? styles.headerExpanded : ''}`}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className={styles.headerLeft}>
          {Icon && <Icon size={16} />}
          {title}
        </div>
        <div className={styles.headerRight}>
          {controls && (
            <div className={styles.controls} onClick={(e) => e.stopPropagation()}>
              {controls}
            </div>
          )}
          <ChevronDown 
            size={18} 
            className={`${styles.chevron} ${isExpanded ? styles.chevronExpanded : ''}`} 
          />
        </div>
      </div>
      
      {isExpanded && (
        <div className={styles.content}>
          {children}
        </div>
      )}
    </div>
  );
}
