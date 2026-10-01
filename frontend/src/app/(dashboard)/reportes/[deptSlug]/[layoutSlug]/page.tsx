"use client";

import { use } from "react";

import ReportView from "../ReportView";

/** `/reportes/<dept>/<layout>` — one of the department's team layouts. */
export default function ReporteLayoutPage({
  params,
}: {
  params: Promise<{ deptSlug: string; layoutSlug: string }>;
}) {
  const { deptSlug, layoutSlug } = use(params);
  return <ReportView deptSlug={deptSlug} layoutSlug={layoutSlug} />;
}
