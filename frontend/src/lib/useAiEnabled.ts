"use client";

import { useAuth } from "@/context/AuthContext";

/** Whether the user's club allows the AI (Club.ai_enabled). Platform admins
 *  without a club see it on; the backend gate is the real enforcement. */
export function useAiEnabled(): boolean {
  const { membership } = useAuth();
  return membership?.club?.ai_enabled !== false;
}

/** One line shown wherever the assistant is offered (disclosure). */
export const AI_PRIVACY_NOTE =
  "Antes de enviarse a la IA, los nombres se reemplazan por códigos; los datos clínicos y de carga sí se envían para el análisis.";
