"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import type { PlatformClubCreated, PlatformClubRow } from "@/lib/types";
import { CategoryRows, ClubLogo, type CategoryDraft, toCategoryIn } from "./parts";
import styles from "./plataforma.module.css";

type FieldErrors = { name?: boolean; admin?: boolean };

export default function PlataformaPage() {
  const { user } = useAuth();
  const router = useRouter();
  const { toast } = useToast();
  const isRoot = !!user?.is_superuser;

  const [clubs, setClubs] = useState<PlatformClubRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [cats, setCats] = useState<CategoryDraft[]>([]);
  const [withAdmin, setWithAdmin] = useState(true);
  const [admin, setAdmin] = useState({ first_name: "", last_name: "", email: "" });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const adminRef = useRef<HTMLInputElement>(null);
  const errorId = "club-form-errors";

  useEffect(() => {
    if (!isRoot) return;
    let cancelled = false;
    api<PlatformClubRow[]>("/platform/clubs")
      .then((rows) => !cancelled && setClubs(rows))
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Error al cargar clubes");
      });
    return () => {
      cancelled = true;
    };
  }, [isRoot]);

  const openCreate = () => {
    setName("");
    setCats([{ name: "Primer Equipo", cohort_year: "", is_senior: true }]);
    setWithAdmin(true);
    setAdmin({ first_name: "", last_name: "", email: "" });
    setFieldErrors({});
    setFormError(null);
    setOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errors: FieldErrors = {};
    if (!name.trim()) errors.name = true;
    if (withAdmin && (!admin.first_name.trim() || !admin.last_name.trim()
      || !/.+@.+\..+/.test(admin.email.trim()))) errors.admin = true;
    if (Object.keys(errors).length) {
      setFieldErrors(errors);
      setFormError(errors.name
        ? "Ingresa el nombre del club."
        : "Completa nombre, apellido y un email válido del administrador.");
      (errors.name ? nameRef : adminRef).current?.focus();
      return;
    }
    setFieldErrors({});
    setFormError(null);
    setSubmitting(true);
    try {
      const res = await api<PlatformClubCreated>("/platform/clubs", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          categories: cats.filter((c) => c.name.trim()).map(toCategoryIn),
          admin: withAdmin
            ? { ...admin, email: admin.email.trim().toLowerCase() }
            : null,
        }),
      });
      toast.success(
        res.admin_email
          ? `Club creado. Contraseña temporal de ${res.admin_email}: ` +
            `${res.admin_temp_password} — también se envió por correo.`
          : "Club creado con la plantilla base.",
        { duration: res.admin_email ? 0 : undefined },
      );
      setOpen(false);
      router.push(`/plataforma/${res.club.id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "No se pudo crear el club");
    } finally {
      setSubmitting(false);
    }
  };

  if (!isRoot) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>Esta sección es solo para administradores de SLAB.</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Administración</span>
          <h1 className={styles.title}>SLAB Admin</h1>
          <p className={styles.subtitle}>
            Clubes de la plataforma. Un club nuevo parte con la plantilla base —
            Médico, Físico y Nutricional con sus exámenes— y desde su ficha le
            sumas categorías, departamentos y usuarios.
          </p>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.primaryBtn} onClick={openCreate}>
            + Nuevo club
          </button>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {clubs === null ? (
        <div className={styles.muted}>Cargando clubes…</div>
      ) : clubs.length === 0 ? (
        <div className={styles.empty}>Todavía no hay clubes. Crea el primero con + Nuevo club.</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Club</th>
                <th className={styles.num}>Categorías</th>
                <th className={styles.num}>Departamentos</th>
                <th className={styles.num}>Jugadores</th>
                <th className={styles.num}>Usuarios</th>
                <th>Creado</th>
              </tr>
            </thead>
            <tbody>
              {clubs.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className={styles.clubCell}>
                      <ClubLogo name={c.name} url={c.logo_url} />
                      <Link href={`/plataforma/${c.id}`} className={styles.clubLink}>
                        {c.name}
                      </Link>
                    </span>
                  </td>
                  <td className={styles.num}>{c.categories}</td>
                  <td className={styles.num}>{c.departments}</td>
                  <td className={styles.num}>{c.players}</td>
                  <td className={styles.num}>{c.users}</td>
                  <td>{new Date(c.created_at).toLocaleDateString("es-CL")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={open} title="Nuevo club" onClose={() => !submitting && setOpen(false)}>
        {open && (
          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <label className={styles.field}>
              <span className={styles.label}>Nombre del club *</span>
              <input
                ref={nameRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ej: Deportes Concepción"
                aria-invalid={fieldErrors.name || undefined}
                aria-describedby={fieldErrors.name ? errorId : undefined}
              />
            </label>

            <div className={styles.ok}>
              Se crea con la plantilla base: <strong>Médico</strong> (notas diarias),{" "}
              <strong>Físico</strong> (notas diarias, GPS partido y entrenamiento) y{" "}
              <strong>Nutricional</strong> (notas diarias, peso y talla,
              pentacompartimental), más las posiciones POR / DF / MC / DEL.
            </div>

            <div className={styles.section}>
              <span className={styles.label}>Categorías</span>
              <CategoryRows rows={cats} onChange={setCats} />
            </div>

            <div className={styles.section}>
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={withAdmin}
                  onChange={(e) => setWithAdmin(e.target.checked)}
                />
                <span>Crear el primer administrador del club</span>
              </label>
              {withAdmin && (
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    <span className={styles.label}>Nombre *</span>
                    <input
                      ref={adminRef}
                      value={admin.first_name}
                      onChange={(e) => setAdmin({ ...admin, first_name: e.target.value })}
                      aria-invalid={fieldErrors.admin || undefined}
                      aria-describedby={fieldErrors.admin ? errorId : undefined}
                    />
                  </label>
                  <label className={styles.field}>
                    <span className={styles.label}>Apellido *</span>
                    <input
                      value={admin.last_name}
                      onChange={(e) => setAdmin({ ...admin, last_name: e.target.value })}
                      aria-invalid={fieldErrors.admin || undefined}
                      aria-describedby={fieldErrors.admin ? errorId : undefined}
                    />
                  </label>
                  <label className={`${styles.field} ${styles.fieldFull}`}>
                    <span className={styles.label}>Email *</span>
                    <input
                      type="email"
                      value={admin.email}
                      onChange={(e) => setAdmin({ ...admin, email: e.target.value })}
                      placeholder="persona@club.cl"
                      aria-invalid={fieldErrors.admin || undefined}
                      aria-describedby={fieldErrors.admin ? errorId : undefined}
                    />
                  </label>
                  <span className={`${styles.hint} ${styles.fieldFull}`}>
                    Rol Administrador con acceso a todo el club. Recibe una
                    contraseña temporal por correo.
                  </span>
                </div>
              )}
            </div>

            {formError && (
              <div id={errorId} className={styles.error} role="alert">{formError}</div>
            )}

            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={() => setOpen(false)}
                disabled={submitting}
              >
                Cancelar
              </button>
              <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                {submitting ? "Creando…" : "Crear club"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
