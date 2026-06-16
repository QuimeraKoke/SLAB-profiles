"use client";

import React from "react";
import PlayerTriage from "./PlayerTriage";

interface Props {
  playerId: string;
}

/**
 * The player profile's "Resumen" tab. Per the UX audit (Phase 5 build),
 * this is now a triage card — see `PlayerTriage.tsx` for the structure
 * and `backend/api/triage.py` for the data contract.
 *
 * The previous season-recap implementation (cumulative match stats, GPS
 * averages) was retired here in favor of "what should I worry about
 * today?". The pre-match summary data is still surfaced via the
 * department tabs and dashboards.
 */
export default function ProfileSummary({ playerId }: Props) {
  return <PlayerTriage playerId={playerId} />;
}
