"use client";

import React from "react";

import type { TeamReportWidget } from "@/lib/types";
import TeamActiveRecords from "./TeamActiveRecords";
import TeamActivityCoverage from "./TeamActivityCoverage";
import TeamAlerts from "./TeamAlerts";
import TeamDistribution from "./TeamDistribution";
import TeamGoalProgress from "./TeamGoalProgress";
import TeamHorizontalComparison from "./TeamHorizontalComparison";
import TeamLeaderboard from "./TeamLeaderboard";
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
  team_activity_coverage: TeamActivityCoverage,
  team_leaderboard: TeamLeaderboard,
  team_goal_progress: TeamGoalProgress,
  team_alerts: TeamAlerts,
};

export function renderTeamWidget(widget: TeamReportWidget): React.ReactNode {
  const Component = teamWidgetRegistry[widget.chart_type];
  if (!Component) {
    return <Unsupported widget={widget} />;
  }
  return <Component widget={widget} />;
}
