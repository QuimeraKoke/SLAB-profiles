"use client";

import { use } from "react";

import ReportView from "./ReportView";

/** `/reportes/<dept>` — the department's default team layout. */
export default function ReportePage({ params }: { params: Promise<{ deptSlug: string }> }) {
  const { deptSlug } = use(params);
  return <ReportView deptSlug={deptSlug} />;
}
