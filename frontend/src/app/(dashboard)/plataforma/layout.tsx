import type { Metadata } from "next";

export const metadata: Metadata = { title: "SLAB Admin" };

export default function PlataformaLayout({ children }: { children: React.ReactNode }) {
  return children;
}
