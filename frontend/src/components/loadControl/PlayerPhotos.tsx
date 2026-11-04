"use client";

/**
 * Player photos for the Centro de mando: ONE request per category
 * (`/load-control/photos`) feeds every name on the page, so no panel payload
 * has to carry photos. `<PlayerAvatar>` falls back to the initials (from the
 * map, or from the name) when there is no photo or it fails to load.
 */

import React, { createContext, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";

type Photo = { photo: string | null; initials: string };
const Ctx = createContext<Record<string, Photo>>({});

export function PlayerPhotosProvider({ categoryId, children }: { categoryId: string | null; children: React.ReactNode }) {
  const [map, setMap] = useState<Record<string, Photo>>({});
  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<{ players: Record<string, Photo> }>(`/load-control/photos?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setMap(d.players); })
      .catch(() => { /* a missing photo is never an error: the initials show */ });
    return () => { cancelled = true; };
  }, [categoryId]);
  return <Ctx.Provider value={map}>{children}</Ctx.Provider>;
}

/** The photo of one player (null when there is none), for SVG charts. */
export function usePlayerPhoto(id: string): string | null {
  return useContext(Ctx)[id]?.photo ?? null;
}

const initialsOf = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export function PlayerAvatar({ id, name, size = 26 }: { id: string; name: string; size?: number }) {
  const p = useContext(Ctx)[id];
  const [failed, setFailed] = useState<string | null>(null);
  const base: React.CSSProperties = {
    width: size, height: size, borderRadius: "50%", flexShrink: 0, background: "#eef0fb",
  };
  if (p?.photo && failed !== p.photo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={p.photo} alt="" loading="lazy" style={{ ...base, objectFit: "cover" }}
        onError={() => setFailed(p.photo)} />
    );
  }
  return (
    <span aria-hidden="true" style={{ ...base, color: "#4338ca", fontSize: Math.round(size * 0.4), fontWeight: 700,
      display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
      {p?.initials || initialsOf(name)}
    </span>
  );
}

/** Photo + name, inline. `children` replaces the plain name (e.g. a <strong>). */
export function PlayerName({ id, name, size, children }: { id: string; name: string; size?: number; children?: React.ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, verticalAlign: "middle" }}>
      <PlayerAvatar id={id} name={name} size={size} />
      {children ?? name}
    </span>
  );
}
