import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Daily — SLAB",
};

export default function DailyLayout({ children }: { children: React.ReactNode }) {
  return children;
}
