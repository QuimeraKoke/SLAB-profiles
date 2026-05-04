"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import type { Category } from "@/lib/types";

const STORAGE_KEY = "slab.selectedCategoryId";

interface CategoryContextValue {
  categories: Category[];
  categoryId: string | null;
  setCategoryId: (id: string) => void;
  /** True while we're still resolving the user's category list / default. */
  loading: boolean;
}

const CategoryContext = createContext<CategoryContextValue | null>(null);

/**
 * Holds the globally-selected category for the dashboard. Pages that show
 * category-scoped data (Equipo, Partidos, Reportes, …) read `categoryId`
 * from here instead of carrying their own picker.
 *
 * - Categories load once when membership becomes available.
 * - The pick is persisted to localStorage so it survives reloads.
 * - When the persisted id no longer exists in the user's scoped list
 *   (admin removed access, club switch, etc.) we fall back to the first
 *   category so the UI never shows "no category selected".
 */
export function CategoryProvider({ children }: { children: React.ReactNode }) {
  const { membership } = useAuth();
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!membership) {
      // Platform admin / not logged in: skip the fetch and clear state via
      // a microtask so we're not synchronously setting state inside the
      // effect body (lint: react-hooks/set-state-in-effect).
      Promise.resolve().then(() => {
        if (cancelled) return;
        setCategories([]);
        setCategoryIdState(null);
        setLoading(false);
      });
      return () => {
        cancelled = true;
      };
    }
    // Read the persisted pick once per fetch — fresher than mount-only since
    // a tab in another window might have updated it. localStorage lookups
    // are sync and cheap.
    const persisted =
      typeof window !== "undefined"
        ? window.localStorage.getItem(STORAGE_KEY)
        : null;
    api<Category[]>(`/categories?club_id=${membership.club.id}`)
      .then((data) => {
        if (cancelled) return;
        const sorted = [...data].sort((a, b) => a.name.localeCompare(b.name));
        setCategories(sorted);

        // Resolve the active id: persisted-if-still-valid, else first.
        const validPersisted =
          persisted && sorted.some((c) => c.id === persisted)
            ? persisted
            : null;
        const next = validPersisted ?? sorted[0]?.id ?? null;
        setCategoryIdState(next);
        if (next && next !== persisted && typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, next);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCategories([]);
          setCategoryIdState(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [membership]);

  const setCategoryId = useCallback((id: string) => {
    setCategoryIdState(id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, id);
    }
  }, []);

  const value = useMemo<CategoryContextValue>(
    () => ({ categories, categoryId, setCategoryId, loading }),
    [categories, categoryId, setCategoryId, loading],
  );

  return (
    <CategoryContext.Provider value={value}>
      {children}
    </CategoryContext.Provider>
  );
}

export function useCategoryContext(): CategoryContextValue {
  const ctx = useContext(CategoryContext);
  if (!ctx) {
    throw new Error("useCategoryContext must be used within a CategoryProvider");
  }
  return ctx;
}
