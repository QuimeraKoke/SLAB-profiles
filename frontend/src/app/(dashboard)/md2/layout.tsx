import type { Metadata } from "next";

import RequirePermission from "@/components/common/RequirePermission";

export const metadata: Metadata = {
  title: "MD+2 — SLAB",
};

// Primer Equipo screen: the "… Formativo" roles don't hold `core.view_md2`.
export default function Md2Layout({ children }: { children: React.ReactNode }) {
  return <RequirePermission codename="core.view_md2">{children}</RequirePermission>;
}
