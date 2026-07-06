"use client";

import React from "react";
import type { Department } from "@/lib/types";
import PlayerNotesCard from "@/components/perfil/PlayerNotesCard/PlayerNotesCard";
import PlayerTriage from "./PlayerTriage";
import ResumenAssistant from "./ResumenAssistant";
import ResumenSummary from "./ResumenSummary";

interface Props {
  playerId: string;
  playerName: string;
  departments: Department[];
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
 *
 * A cross-department Q&A bar (`ResumenAssistant`) sits above the triage —
 * collapsed by default — so the user can ask about the player and review
 * proposed charts inline. Charts are transient (this view isn't a
 * configurable layout, so they're not promotable).
 */
export default function ProfileSummary({ playerId, playerName, departments }: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <ResumenAssistant playerId={playerId} playerName={playerName} />
      <ResumenSummary playerId={playerId} playerName={playerName} />
      <PlayerNotesCard kind="pauta" playerId={playerId} playerName={playerName} departments={departments} />
      <PlayerNotesCard kind="plan" playerId={playerId} playerName={playerName} departments={departments} />
      <PlayerTriage playerId={playerId} />
    </div>
  );
}
