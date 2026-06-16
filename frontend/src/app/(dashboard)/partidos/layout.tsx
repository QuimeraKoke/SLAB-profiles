import type { Metadata } from "next";

export const metadata: Metadata = { title: "Partidos" };

export default function PartidosLayout({ children }: { children: React.ReactNode }) {
  return children;
}
