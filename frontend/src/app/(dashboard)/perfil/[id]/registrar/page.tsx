"use client";

import React, { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { FileText, ChevronRight } from "lucide-react";

import { useBreadcrumbLabel } from "@/components/layout/Breadcrumbs";
import { api, ApiError } from "@/lib/api";
import type { ExamTemplate, PlayerDetail } from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

interface DeptGroup {
  slug: string;
  name: string;
  templates: ExamTemplate[];
}

/** Registrar hub: lists every exam template the user can fill in for this
 *  player, grouped by department, each linking to the per-template form.
 *  This is the landing page for `/perfil/[id]/registrar` — reachable from the
 *  "Registrar examen" breadcrumb and as a one-stop "add new data" entry. */
export default function RegistrarIndexPage({ params }: PageProps) {
  const { id } = use(params);
  const setBreadcrumbLabel = useBreadcrumbLabel();

  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [templates, setTemplates] = useState<ExamTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(null);
      setTemplates(null);
      setError(null);
    });
    Promise.all([
      api<PlayerDetail>(`/players/${id}`),
      api<ExamTemplate[]>(`/players/${id}/templates`),
    ])
      .then(([p, tpls]) => {
        if (cancelled) return;
        setPlayer(p);
        setTemplates(tpls);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudieron cargar las plantillas.");
      });
    return () => { cancelled = true; };
  }, [id]);

  useEffect(() => {
    if (player) setBreadcrumbLabel(player.id, `${player.first_name} ${player.last_name}`.trim());
  }, [player, setBreadcrumbLabel]);

  const groups = useMemo<DeptGroup[]>(() => {
    if (!templates) return [];
    const byDept = new Map<string, DeptGroup>();
    for (const t of templates) {
      const slug = t.department?.slug ?? "otros";
      const name = t.department?.name ?? "Otros";
      if (!byDept.has(slug)) byDept.set(slug, { slug, name, templates: [] });
      byDept.get(slug)!.templates.push(t);
    }
    const out = [...byDept.values()];
    out.sort((a, b) => a.name.localeCompare(b.name));
    for (const g of out) g.templates.sort((a, b) => a.name.localeCompare(b.name));
    return out;
  }, [templates]);

  const backHref = `/perfil/${id}`;

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.error} role="alert">{error}</div>
        <Link href={backHref} className={styles.backLink}>← Volver al perfil</Link>
      </div>
    );
  }

  if (!player || !templates) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando…</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href={backHref} className={styles.backLink}>← Volver al perfil</Link>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>{player.first_name} {player.last_name}</span>
          <h1 className={styles.title}>Registrar examen</h1>
          <p className={styles.sub}>Elegí la plantilla para cargar nuevos datos.</p>
        </div>
      </header>

      {groups.length === 0 ? (
        <p className={styles.empty}>
          No hay plantillas disponibles para la categoría de este jugador.
        </p>
      ) : (
        <div className={styles.groups}>
          {groups.map((g) => (
            <section key={g.slug} className={styles.group}>
              <h2 className={styles.groupTitle}>{g.name}</h2>
              <ul className={styles.list}>
                {g.templates.map((t) => (
                  <li key={t.id}>
                    <Link
                      href={`/perfil/${id}/registrar/${t.id}?tab=${encodeURIComponent(g.slug)}`}
                      className={styles.item}
                    >
                      <span className={styles.itemIcon}><FileText size={16} aria-hidden="true" /></span>
                      <span className={styles.itemName}>{t.name}</span>
                      <ChevronRight size={16} aria-hidden="true" className={styles.itemChevron} />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
