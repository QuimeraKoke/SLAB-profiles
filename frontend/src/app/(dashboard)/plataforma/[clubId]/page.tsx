"use client";

import React, { use, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { useBreadcrumbLabel } from "@/components/layout/Breadcrumbs";
import Modal from "@/components/ui/Modal/Modal";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import type { PlatformCategory, PlatformClub } from "@/lib/types";
import { ClubLogo, type CategoryDraft, toCategoryIn } from "../parts";
import styles from "../plataforma.module.css";

type PageProps = { params: Promise<{ clubId: string }> };

// "" = no model: the new category takes every department and exam of the club.
const ALL = "";

export default function PlataformaClubPage({ params }: PageProps) {
  const { clubId } = use(params);
  const { user } = useAuth();
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const setBreadcrumbLabel = useBreadcrumbLabel();
  const isRoot = !!user?.is_superuser;

  const [club, setClub] = useState<PlatformClub | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");

  const [catOpen, setCatOpen] = useState(false);
  const [cat, setCat] = useState<CategoryDraft>({ name: "", cohort_year: "", is_senior: false });
  const [like, setLike] = useState<string>(ALL);

  const [deptSlug, setDeptSlug] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const logoInput = useRef<HTMLInputElement>(null);
  const catNameRef = useRef<HTMLInputElement>(null);
  const renameRef = useRef<HTMLInputElement>(null);
  const errorId = "platform-form-errors";

  useEffect(() => {
    if (!isRoot) return;
    let cancelled = false;
    api<PlatformClub>(`/platform/clubs/${clubId}`)
      .then((c) => !cancelled && setClub(c))
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Error al cargar el club");
      });
    return () => {
      cancelled = true;
    };
  }, [clubId, isRoot]);

  useEffect(() => {
    if (club) setBreadcrumbLabel(club.id, club.name);
  }, [club, setBreadcrumbLabel]);

  /** Every mutation answers with the whole club: one place updates the page. */
  const mutate = async (key: string, path: string, init: RequestInit, ok: string) => {
    setBusy(key);
    setError(null);
    try {
      const next = await api<PlatformClub>(path, init);
      setClub(next);
      toast.success(ok);
      return true;
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "No se pudo guardar";
      setError(msg);
      setFormError(msg);
      return false;
    } finally {
      setBusy(null);
    }
  };

  if (!isRoot) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>Esta sección es solo para administradores de SLAB.</div>
      </div>
    );
  }
  if (!club) {
    return (
      <div className={styles.container}>
        {error ? <div className={styles.error}>{error}</div>
          : <div className={styles.muted}>Cargando club…</div>}
      </div>
    );
  }

  const openCategory = () => {
    setCat({ name: "", cohort_year: "", is_senior: false });
    // Default model: an age group (a new series is almost always "like the
    // other series"), else whatever the club has.
    setLike(club.categories.find((c) => !c.is_senior)?.id ?? club.categories[0]?.id ?? ALL);
    setFormError(null);
    setCatOpen(true);
  };

  const submitCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cat.name.trim()) {
      setFormError("Ingresa el nombre de la categoría.");
      catNameRef.current?.focus();
      return;
    }
    const ok = await mutate("cat", `/platform/clubs/${club.id}/categories`, {
      method: "POST",
      body: JSON.stringify({ ...toCategoryIn(cat), like_id: like || null }),
    }, `Categoría ${cat.name.trim()} creada.`);
    if (ok) setCatOpen(false);
  };

  const deleteCategory = async (c: PlatformCategory) => {
    const yes = await confirm({
      title: `Eliminar ${c.label}`,
      message: "La categoría no tiene jugadores. Se quita de todos los exámenes y departamentos.",
      confirmLabel: "Eliminar",
      variant: "danger",
    });
    if (!yes) return;
    await mutate(`del-${c.id}`, `/platform/clubs/${club.id}/categories/${c.id}`,
      { method: "DELETE" }, `Categoría ${c.label} eliminada.`);
  };

  const submitRename = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      setFormError("Ingresa el nombre del club.");
      renameRef.current?.focus();
      return;
    }
    const ok = await mutate("rename", `/platform/clubs/${club.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: newName.trim() }),
    }, "Nombre actualizado.");
    if (ok) setRenaming(false);
  };

  const uploadLogo = async (file: File | undefined) => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    await mutate("logo", `/platform/clubs/${club.id}/logo`, { method: "POST", body },
      "Logo actualizado.");
    if (logoInput.current) logoInput.current.value = "";
  };

  const addDepartment = async () => {
    const spec = club.available_departments.find((d) => d.slug === deptSlug);
    if (!spec) return;
    const ok = await mutate("dept", `/platform/clubs/${club.id}/departments`, {
      method: "POST",
      body: JSON.stringify({ slug: spec.slug }),
    }, `Departamento ${spec.name} agregado a todas las categorías.`);
    if (ok) setDeptSlug("");
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <ClubLogo name={club.name} url={club.logo_url} large />
          <div>
            <span className={styles.eyebrow}>SLAB Admin</span>
            <h1 className={styles.title}>{club.name}</h1>
            <p className={styles.subtitle}>
              Creado el {new Date(club.created_at).toLocaleDateString("es-CL")} ·{" "}
              {club.positions} posiciones
            </p>
          </div>
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => {
              setNewName(club.name);
              setFormError(null);
              setRenaming(true);
            }}
          >
            Renombrar
          </button>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => logoInput.current?.click()}
            disabled={busy === "logo"}
          >
            {busy === "logo" ? "Subiendo…" : club.logo_url ? "Cambiar logo" : "Subir logo"}
          </button>
          <input
            ref={logoInput}
            type="file"
            accept="image/png,image/jpeg,image/svg+xml,image/webp"
            hidden
            onChange={(e) => uploadLogo(e.target.files?.[0])}
          />
        </div>
      </header>

      {error && !catOpen && !renaming && <div className={styles.error} role="alert">{error}</div>}

      <div className={styles.grid}>
        <section className={styles.card} aria-labelledby="sec-plantilla">
          <div className={styles.cardHead}>
            <h2 id="sec-plantilla" className={styles.cardTitle}>Plantilla base</h2>
            {club.missing.length > 0 && (
              <button
                type="button"
                className={styles.secondaryBtn}
                disabled={busy === "template"}
                onClick={() => mutate("template", `/platform/clubs/${club.id}/apply-template`,
                  { method: "POST" }, "Plantilla aplicada.")}
              >
                {busy === "template" ? "Aplicando…" : "Completar plantilla"}
              </button>
            )}
          </div>
          {club.missing.length === 0 ? (
            <div className={styles.ok}>
              Completa: Médico, Físico y Nutricional con sus exámenes base y las posiciones.
            </div>
          ) : (
            <div className={styles.warn}>
              Falta: {club.missing.join(", ")}. Completar la plantilla crea solo lo
              que falta; lo que el club ya tiene no se toca.
            </div>
          )}
        </section>

        <section className={styles.card} aria-labelledby="sec-usuarios">
          <div className={styles.cardHead}>
            <h2 id="sec-usuarios" className={styles.cardTitle}>Usuarios</h2>
            <Link
              href={`/configuraciones/usuarios?club=${club.id}`}
              className={styles.secondaryBtn}
            >
              Gestionar usuarios
            </Link>
          </div>
          <span className={styles.hint}>
            {club.users === 0
              ? "El club no tiene usuarios todavía."
              : `${club.users} usuario${club.users === 1 ? "" : "s"} del staff.`}{" "}
            Roles, alcance y contraseñas se gestionan en Administración › Usuarios.
          </span>
        </section>

        <section className={styles.card} aria-labelledby="sec-categorias">
          <div className={styles.cardHead}>
            <h2 id="sec-categorias" className={styles.cardTitle}>Categorías</h2>
            <button type="button" className={styles.secondaryBtn} onClick={openCategory}>
              + Nueva categoría
            </button>
          </div>
          {club.categories.length === 0 ? (
            <div className={styles.empty}>Sin categorías. Crea la primera para cargar jugadores.</div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Categoría</th>
                    <th className={styles.num}>Jugadores</th>
                    <th>Departamentos</th>
                    <th aria-label="Acciones" />
                  </tr>
                </thead>
                <tbody>
                  {club.categories.map((c) => (
                    <tr key={c.id}>
                      <td className={styles.nameCell}>
                        {c.label}
                        {c.is_senior && <span className={styles.badge}>Primer equipo</span>}
                      </td>
                      <td className={styles.num}>{c.players}</td>
                      <td className={styles.scopeCell}>{c.departments.join(", ") || "—"}</td>
                      <td className={styles.rowActions}>
                        {c.players === 0 && (
                          <button
                            type="button"
                            className={styles.iconBtn}
                            onClick={() => deleteCategory(c)}
                            disabled={busy === `del-${c.id}`}
                            title="Eliminar"
                            aria-label={`Eliminar ${c.label}`}
                          >
                            🗑️
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className={styles.card} aria-labelledby="sec-departamentos">
          <div className={styles.cardHead}>
            <h2 id="sec-departamentos" className={styles.cardTitle}>Departamentos y exámenes</h2>
          </div>
          {club.departments.map((d) => (
            <div key={d.id} className={styles.dept}>
              <span className={styles.deptName}>{d.name}</span>{" "}
              <span className={styles.examMeta}>
                · {d.categories} categoría{d.categories === 1 ? "" : "s"}
              </span>
              <ul className={styles.examList}>
                {d.exams.length === 0 && <li className={styles.hint}>Sin exámenes.</li>}
                {d.exams.map((t) => (
                  <li key={t.id}>
                    <span>{t.name}</span>
                    <span className={styles.examMeta}>
                      {t.categories} cat. · {t.results.toLocaleString("es-CL")} registros
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {club.available_departments.length > 0 && (
            <div className={styles.addRow}>
              <label className={styles.field}>
                <span className={styles.label}>Agregar departamento</span>
                <select value={deptSlug} onChange={(e) => setDeptSlug(e.target.value)}>
                  <option value="">Elige un departamento…</option>
                  {club.available_departments.map((d) => (
                    <option key={d.slug} value={d.slug}>
                      {d.name} — {d.exams.join(", ")}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={styles.primaryBtn}
                disabled={!deptSlug || busy === "dept"}
                onClick={addDepartment}
              >
                {busy === "dept" ? "Agregando…" : "Agregar"}
              </button>
            </div>
          )}
        </section>
      </div>

      <Modal open={catOpen} title="Nueva categoría" onClose={() => setCatOpen(false)}>
        {catOpen && (
          <form className={styles.form} onSubmit={submitCategory} noValidate>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span className={styles.label}>Nombre *</span>
                <input
                  ref={catNameRef}
                  value={cat.name}
                  onChange={(e) => setCat({ ...cat, name: e.target.value })}
                  placeholder="Ej: Serie 2013"
                  aria-invalid={(formError && !cat.name.trim()) || undefined}
                  aria-describedby={formError ? errorId : undefined}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Año cohorte</span>
                <input
                  inputMode="numeric"
                  value={cat.cohort_year}
                  onChange={(e) => setCat({
                    ...cat, cohort_year: e.target.value.replace(/\D/g, "").slice(0, 4),
                  })}
                  placeholder="Ej: 2013"
                />
              </label>
            </div>
            <span className={styles.hint}>
              Año de nacimiento del grupo, para las series formativas. Vacío para el
              primer equipo o el femenino.
            </span>
            <label className={styles.field}>
              <span className={styles.label}>Departamentos y exámenes</span>
              <select value={like} onChange={(e) => setLike(e.target.value)}>
                {club.categories.map((c) => (
                  <option key={c.id} value={c.id}>Igual que {c.label}</option>
                ))}
                <option value={ALL}>Todos los del club</option>
              </select>
            </label>
            <label className={`${styles.field} ${styles.checkboxField}`}>
              <input
                type="checkbox"
                checked={cat.is_senior}
                onChange={(e) => setCat({ ...cat, is_senior: e.target.checked })}
              />
              <span>Es el primer equipo del club (reemplaza al actual)</span>
            </label>
            {formError && (
              <div id={errorId} className={styles.error} role="alert">{formError}</div>
            )}
            <div className={styles.formActions}>
              <button type="button" className={styles.cancelBtn} onClick={() => setCatOpen(false)}>
                Cancelar
              </button>
              <button type="submit" className={styles.primaryBtn} disabled={busy === "cat"}>
                {busy === "cat" ? "Creando…" : "Crear categoría"}
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal open={renaming} title="Renombrar club" onClose={() => setRenaming(false)}>
        {renaming && (
          <form className={styles.form} onSubmit={submitRename} noValidate>
            <label className={styles.field}>
              <span className={styles.label}>Nombre *</span>
              <input
                ref={renameRef}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                aria-invalid={(formError && !newName.trim()) || undefined}
                aria-describedby={formError ? errorId : undefined}
              />
            </label>
            {formError && (
              <div id={errorId} className={styles.error} role="alert">{formError}</div>
            )}
            <div className={styles.formActions}>
              <button type="button" className={styles.cancelBtn} onClick={() => setRenaming(false)}>
                Cancelar
              </button>
              <button type="submit" className={styles.primaryBtn} disabled={busy === "rename"}>
                {busy === "rename" ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
