import React from 'react';
import { Search, Filter } from 'lucide-react';
import styles from './PlayerListToolbar.module.css';

export default function PlayerListToolbar() {
  return (
    <div className={styles.toolbar}>
      <div className={styles.searchContainer}>
        <Search size={16} className={styles.searchIcon} />
        <input 
          type="text" 
          placeholder="Buscar jugador..." 
          className={styles.searchInput}
        />
      </div>
      <button className={styles.filterButton}>
        <Filter size={16} />
        <span>Filtros</span>
      </button>
    </div>
  );
}
