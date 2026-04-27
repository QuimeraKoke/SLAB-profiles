import type { ExamField } from "@/lib/types";

export interface SeriesPoint {
  /** ISO timestamp of when the result was recorded. */
  recorded_at: string;
  /** The value for this field at that point in time. May be null if the
   *  formula errored or the doctor didn't record it. */
  value: number | string | boolean | null;
}

export interface VisualizerProps {
  field: ExamField;
  /** Chronological (oldest → newest). */
  series: SeriesPoint[];
}
