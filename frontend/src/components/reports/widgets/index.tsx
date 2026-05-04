"use client";

import React from "react";

import type { TeamReportWidget } from "@/lib/types";
import TeamActiveRecords from "./TeamActiveRecords";
import TeamDistribution from "./TeamDistribution";
import TeamHorizontalComparison from "./TeamHorizontalComparison";
import TeamRosterMatrix from "./TeamRosterMatrix";
import TeamStatusCounts from "./TeamStatusCounts";
import TeamTrendLine from "./TeamTrendLine";
import Unsupported from "./Unsupported";

const teamWidgetRegistry: Record<
  string,
  React.ComponentType<{ widget: TeamReportWidget }>
> = {
  team_horizontal_comparison: TeamHorizontalComparison,
  team_roster_matrix: TeamRosterMatrix,
  team_status_counts: TeamStatusCounts,
  team_trend_line: TeamTrendLine,
  team_distribution: TeamDistribution,
  team_active_records: TeamActiveRecords,
};

export function renderTeamWidget(widget: TeamReportWidget): React.ReactNode {
  const Component = teamWidgetRegistry[widget.chart_type];
  if (!Component) {
    return <Unsupported widget={widget} />;
  }
  return <Component widget={widget} />;
}
