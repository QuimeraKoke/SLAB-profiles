"use client";

import React from "react";

import type { DashboardWidget } from "@/lib/types";
import BodyMapHeatmap from "./BodyMapHeatmap";
import ComparisonTable from "./ComparisonTable";
import LineWithSelector from "./LineWithSelector";
import DonutPerResult from "./DonutPerResult";
import GroupedBar from "./GroupedBar";
import MultiLine from "./MultiLine";
import Unsupported from "./Unsupported";

const widgetRegistry: Record<string, React.ComponentType<{ widget: DashboardWidget }>> = {
  comparison_table: ComparisonTable,
  line_with_selector: LineWithSelector,
  donut_per_result: DonutPerResult,
  grouped_bar: GroupedBar,
  multi_line: MultiLine,
  body_map_heatmap: BodyMapHeatmap,
};

export function renderWidget(widget: DashboardWidget): React.ReactNode {
  const Component = widgetRegistry[widget.chart_type];
  if (!Component) {
    return <Unsupported widget={widget} />;
  }
  return <Component widget={widget} />;
}
