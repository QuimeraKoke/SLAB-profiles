"use client";

/**
 * The profile's injuries, fetched ONCE and shared with every chart on the page.
 *
 * A context rather than a widget prop: the charts are rendered through
 * `renderWidget` from several tabs and from the assistant's transient charts,
 * and none of those paths should have to thread injuries through. Outside a
 * provider (layout editor, team reports) the hook returns `[]`, so a chart
 * there simply draws none.
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { InjuryRange } from "@/lib/injuryRanges";

interface Ctx {
  playerId: string | null;
  injuries: InjuryRange[];
  refresh: () => void;
}

const PlayerInjuriesCtx = createContext<Ctx>({ playerId: null, injuries: [], refresh: () => {} });

export function PlayerInjuriesProvider({
  playerId,
  children,
}: {
  playerId: string;
  children: React.ReactNode;
}) {
  const [injuries, setInjuries] = useState<InjuryRange[]>([]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<InjuryRange[]>(`/injuries/ranges?players=${encodeURIComponent(playerId)}`)
      .then((rows) => {
        if (!cancelled) setInjuries(rows);
      })
      // A chart without its injury bands is still a correct chart; never
      // let this call take the profile down with it.
      .catch(() => {
        if (!cancelled) setInjuries([]);
      });
    return () => {
      cancelled = true;
    };
  }, [playerId, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return (
    <PlayerInjuriesCtx.Provider value={{ playerId, injuries, refresh }}>
      {children}
    </PlayerInjuriesCtx.Provider>
  );
}

export function usePlayerInjuries(): Ctx {
  return useContext(PlayerInjuriesCtx);
}
