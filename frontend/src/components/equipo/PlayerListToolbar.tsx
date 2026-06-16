import React from 'react';
import { Search, Filter } from 'lucide-react';
import styles from './PlayerListToolbar.module.css';

interface PlayerListToolbarProps {
  query: string;
  onQueryChange: (q: string) => void;
}

export default function PlayerListToolbar({ query, onQueryChange }: PlayerListToolbarProps) {
  return (
    <div className={styles.toolbar}>
      <div className={styles.searchContainer}>
        <Search size={16} className={styles.searchIcon} aria-hidden="true" />
        <input
          type="search"
          placeholder="Buscar jugador…"
          aria-label="Buscar jugador"
          className={styles.searchInput}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
      </div>
      <button type="button" className={styles.filterButton}>
        <Filter size={16} aria-hidden="true" />
        <span>Filtros</span>
      </button>
    </div>
  );
}
