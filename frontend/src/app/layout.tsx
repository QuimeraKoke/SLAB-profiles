import type { Metadata } from "next";
import { Audiowide, Roboto } from "next/font/google";
import "./globals.css";

// Audiowide stays available as a CSS variable for branding only (logo).
const audiowide = Audiowide({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-audiowide",
});

// Roboto is the default content typeface — applied to body, headings, etc.
const roboto = Roboto({
  weight: ["300", "400", "500", "700"],
  subsets: ["latin"],
  variable: "--font-roboto",
});

export const metadata: Metadata = {
  title: {
    template: "%s · SLAB",
    default: "SLAB",
  },
  description: "Plataforma de gestión deportiva — Universidad de Chile",
};

import { AuthProvider } from "@/context/AuthContext";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={`${audiowide.variable} ${roboto.variable}`}>
      <body>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
