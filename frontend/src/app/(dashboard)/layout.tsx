"use client";

import React, { useState } from "react";

import Navbar from "@/components/layout/Navbar";
import Sidebar from "@/components/layout/Sidebar";
import { CategoryProvider } from "@/context/CategoryContext";
import styles from "./layout.module.css";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Sidebar visibility — only meaningful on tablet/mobile, ignored by CSS
  // on desktop. Closed by default; opens via the navbar hamburger and
  // closes when the user picks a destination (handled inside Sidebar via
  // its onClose callback bound to each Link's onClick).
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <CategoryProvider>
      <div className={styles.layoutWrapper}>
        <Navbar onMenuClick={() => setSidebarOpen((v) => !v)} />
        <div className={styles.mainContainer}>
          <Sidebar
            open={sidebarOpen}
            onClose={() => setSidebarOpen(false)}
          />
          {sidebarOpen && (
            <div
              className={styles.backdrop}
              onClick={() => setSidebarOpen(false)}
              aria-hidden="true"
            />
          )}
          <main className={styles.content}>{children}</main>
        </div>
      </div>
    </CategoryProvider>
  );
}
