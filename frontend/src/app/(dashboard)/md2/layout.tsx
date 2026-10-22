import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MD+2 — SLAB",
};

export default function Md2Layout({ children }: { children: React.ReactNode }) {
  return children;
}
