"use client";

import React, { useState } from "react";

import Navbar from "@/components/layout/Navbar";
import Sidebar from "@/components/layout/Sidebar";
import Breadcrumbs, { BreadcrumbProvider } from "@/components/layout/Breadcrumbs";
import { CategoryProvider } from "@/context/CategoryContext";
import { ConfirmProvider } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { ToastProvider } from "@/components/ui/Toast/Toast";
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
      <ToastProvider>
        <ConfirmProvider>
          <BreadcrumbProvider>
            <div className={styles.layoutWrapper}>
              {/* QW-6: keyboard skip-link must be the first focusable element so
               * Tab from page load lands on it before any navbar/sidebar control. */}
              <a href="#main-content" className={styles.skipLink}>
                Saltar al contenido
              </a>
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
                <main id="main-content" className={styles.content} tabIndex={-1}>
                  {/* ME-1: route trail across all dashboard pages. */}
                  <Breadcrumbs />
                  {children}
                </main>
              </div>
            </div>
          </BreadcrumbProvider>
        </ConfirmProvider>
      </ToastProvider>
    </CategoryProvider>
  );
}
