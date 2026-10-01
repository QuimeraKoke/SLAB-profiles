import type { EventType } from "./types";

/** Display names of calendar event types — shared by the Eventos tab and the
 *  result detail modal so a "Partido" reads the same everywhere. */
export const EVENT_TYPE_LABEL: Record<EventType, string> = {
  match: "Partido",
  training: "Entrenamiento",
  medical_checkup: "Chequeo médico",
  physical_test: "Test físico",
  team_speech: "Charla / reunión",
  nutrition: "Nutricional",
  other: "Otro",
};
