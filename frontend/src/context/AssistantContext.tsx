"use client";

import React, { createContext, useContext, useMemo, useState } from "react";

interface AssistantContextValue {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

const AssistantContext = createContext<AssistantContextValue | null>(null);

/**
 * Holds the open/closed state of the floating S-LAB AI chat, lifted out of
 * `TeamChat` so it's no longer the only entry point (NAV-02). Any surface —
 * the floating button, the "Ask S-LAB AI" sidebar entry, an alert deep-link —
 * can open the same chat via `useAssistant()`.
 */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo(() => ({ open, setOpen }), [open]);
  return (
    <AssistantContext.Provider value={value}>
      {children}
    </AssistantContext.Provider>
  );
}

export function useAssistant(): AssistantContextValue {
  const ctx = useContext(AssistantContext);
  if (!ctx) {
    throw new Error("useAssistant must be used within an AssistantProvider");
  }
  return ctx;
}
