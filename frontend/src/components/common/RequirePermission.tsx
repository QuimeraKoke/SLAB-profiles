"use client";

import React from "react";

import { usePermission } from "@/lib/permissions";

/** Renders `children` only when the user holds `codename`; otherwise a short
 *  "no access" note. For whole screens gated by a feature permission — wrap
 *  them from the route's `layout.tsx`, so the page keeps its own hooks.
 *
 *  Cosmetic: the backend's `@require_perm` is the real gate. This only avoids
 *  showing a screen whose every request would come back 403 (someone typing
 *  the URL the menu no longer shows them). */
export default function RequirePermission({
  codename,
  children,
}: {
  codename: string;
  children: React.ReactNode;
}) {
  const allowed = usePermission(codename);
  if (allowed) return <>{children}</>;
  return (
    <div style={{ padding: 24 }}>
      <p style={{ fontSize: 13, color: "#98a2b3", margin: 0 }}>
        No tenés permiso para ver este módulo.
      </p>
    </div>
  );
}
