import type { Metadata } from "next";

import RequirePermission from "@/components/common/RequirePermission";

export const metadata: Metadata = {
  title: "Control de carga — SLAB",
};

// Seen by every role that holds `load_control.view_microcycle`; planning
// (add/change) is gated inside the page.
export default function ControlCargaLayout({ children }: { children: React.ReactNode }) {
  return <RequirePermission codename="load_control.view_microcycle">{children}</RequirePermission>;
}
