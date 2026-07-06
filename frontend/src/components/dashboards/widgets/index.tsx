"use client";

import React from "react";

import type { DashboardWidget } from "@/lib/types";
import ActivityLog from "./ActivityLog";
import BodyMapHeatmap from "./BodyMapHeatmap";
import ComparisonTable from "./ComparisonTable";
import CrossExamLine from "./CrossExamLine";
import LineWithSelector from "./LineWithSelector";
import DonutPerResult from "./DonutPerResult";
import GoalCard from "./GoalCard";
import GroupedBar from "./GroupedBar";
import MultiLine from "./MultiLine";
import PlayerAlerts from "./PlayerAlerts";
import RadarTrainingLoad from "./RadarTrainingLoad";
import Unsupported from "./Unsupported";

const widgetRegistry: Record<
  string,
  React.ComponentType<{ widget: DashboardWidget; playerId?: string }>
> = {
  comparison_table: ComparisonTable,
  line_with_selector: LineWithSelector,
  training_radar: RadarTrainingLoad,
  donut_per_result: DonutPerResult,
  grouped_bar: GroupedBar,
  multi_line: MultiLine,
  cross_exam_line: CrossExamLine,
  body_map_heatmap: BodyMapHeatmap,
  goal_card: GoalCard,
  player_alerts: PlayerAlerts,
  activity_log: ActivityLog,
};

export function renderWidget(widget: DashboardWidget, playerId?: string): React.ReactNode {
  const Component = widgetRegistry[widget.chart_type];
  if (!Component) {
    return <Unsupported widget={widget} />;
  }
  return <Component widget={widget} playerId={playerId} />;
}
