"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { usePermission } from "@/lib/permissions";
import type {
  AdminUser,
  AdminUserCreateIn,
  AdminUserCreateResult,
  AdminUserUpdateIn,
  Category,
  Department,
  UsersMeta,
} from "@/lib/types";
import styles from "./page.module.css";

type FieldErrors = {
  first_name?: boolean;
  last_name?: boolean;
  email?: boolean;
};

type FormState = {
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  all_categories: boolean;
  category_ids: string[];
  all_departments: boolean;
  department_ids: string[];
  is_active: boolean;
};

const EMPTY_FORM: FormState = {
  first_name: "",
  last_name: "",
  email: "",
  role: "",
  all_categories: false,
  category_ids: [],
  all_departments: false,
  department_ids: [],
  is_active: true,
};

function fromUser(u: AdminUser, fallbackRole: string): FormState {
  return {
    first_name: u.first_name,
    last_name: u.last_name,
    email: u.email,
    role: u.role || fallbackRole,
    all_categories: u.all_categories,
    category_ids: u.categories.map((c) => c.id),
    all_departments: u.all_departments,
    department_ids: u.departments.map((d) => d.id),
    is_active: u.is_active,
  };
}

function scopeSummary(u: AdminUser): string {
  const cats = u.all_categories
    ? "Todas las categorías"
    : u.categories.map((c) => c.name).join(", ") || "Sin categorías";
  const deps = u.all_departments
    ? "Todos los departamentos"
    : u.departments.map((d) => d.name).join(", ") || "Sin departamentos";
  return `${cats} · ${deps}`;
}

export default function UsersAdminPage() {
  const { membership } = useAuth();
  const { confirm } = useConfirm();
  const { toast } = useToast();

  const canView = usePermission("auth.view_user");
  const canAdd = usePermission("auth.add_user");
  const canChange = usePermission("auth.change_user");

  const [meta, setMeta] = useState<UsersMeta | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Superuser-only club selector. Managers act on their own club implicitly.
  const [selectedClubId, setSelectedClubId] = useState<string>("");
  const managedClubId = membership ? membership.club.id : selectedClubId;
  const managedClubName = membership
    ? membership.club.name
    : meta?.clubs.find((c) => c.id === managedClubId)?.name ?? "";

  // A club-scoped manager can only grant a scope no wider than their own.
  const canGrantAllCats = !membership || membership.all_categories;
  const canGrantAllDeps = !membership || membership.all_departments;

  const [editing, setEditing] = useState<AdminUser | "new" | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  const firstNameRef = useRef<HTMLInputElement>(null);
  const lastNameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const errorId = "user-form-errors";

  // Load meta once (clubs + assignable roles). Superusers default to the
  // first club so the list + scope pickers have something to act on.
  useEffect(() => {
    if (!canView) return;
    let cancelled = false;
    api<UsersMeta>("/users/meta")
      .then((m) => {
        if (cancelled) return;
        setMeta(m);
        if (!membership && m.clubs[0]) {
          setSelectedClubId((prev) => prev || m.clubs[0].id);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Error al cargar datos");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [canView, membership]);

  // Load users + the managed club's categories/departments (scope pickers).
  useEffect(() => {
    if (!canView) return;
    if (!managedClubId) return; // superuser waiting for a club selection
    let cancelled = false;
    const clubQuery = !membership ? `?club_id=${managedClubId}` : "";
    Promise.all([
      api<AdminUser[]>(`/users${clubQuery}`),
      api<Category[]>(`/categories?club_id=${managedClubId}`),
      api<Department[]>(`/clubs/${managedClubId}/departments`),
    ])
      .then(([us, cats, deps]) => {
        if (cancelled) return;
        setUsers(us);
        setCategories([...cats].sort((a, b) => a.name.localeCompare(b.name)));
        setDepartments([...deps].sort((a, b) => a.name.localeCompare(b.name)));
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Error al cargar usuarios");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [canView, managedClubId, membership, refreshKey]);

  const assignableRoles = useMemo(() => meta?.assignable_roles ?? [], [meta]);
  const defaultRole = assignableRoles[0] ?? "Editor";

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, role: defaultRole });
    setFieldErrors({});
    setEditing("new");
    setActionError(null);
  };

  const openEdit = (u: AdminUser) => {
    setForm(fromUser(u, defaultRole));
    setFieldErrors({});
    setEditing(u);
    setActionError(null);
  };

  const closeModal = () => {
    setEditing(null);
    setActionError(null);
    setFieldErrors({});
  };

  const toggleActive = async (u: AdminUser) => {
    setActionError(null);
    try {
      await api<AdminUser>(`/users/${u.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !u.is_active } as AdminUserUpdateIn),
      });
      toast.success(u.is_active ? "Usuario desactivado." : "Usuario activado.");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "No se pudo cambiar el estado",
      );
    }
  };

  const handleResetPassword = async (u: AdminUser) => {
    const ok = await confirm({
      title: `Restablecer contraseña de ${u.first_name} ${u.last_name}`,
      message:
        "Se generará una contraseña temporal nueva y se enviará por correo a " +
        `${u.email}. La contraseña anterior dejará de funcionar.`,
      confirmLabel: "Restablecer",
    });
    if (!ok) return;
    setActionError(null);
    try {
      const res = await api<{ temp_password: string }>(
        `/users/${u.id}/reset-password`,
        { method: "POST" },
      );
      toast.success(
        `Contraseña temporal: ${res.temp_password} — también se envió por correo a ${u.email}.`,
        { duration: 0 },
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "No se pudo restablecer la contraseña",
      );
    }
  };

  const setScope = (
    key: "category_ids" | "department_ids",
    id: string,
    checked: boolean,
  ) => {
    setForm((f) => {
      const set = new Set(f[key]);
      if (checked) set.add(id);
      else set.delete(id);
      return { ...f, [key]: [...set] };
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setActionError(null);

    // IA #7: validate, mark invalid fields, focus the first offender.
    const errors: FieldErrors = {};
    if (!form.first_name.trim()) errors.first_name = true;
    if (!form.last_name.trim()) errors.last_name = true;
    const emailOk = /.+@.+\..+/.test(form.email.trim());
    if (!emailOk) errors.email = true;
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setActionError("Revisá los campos marcados.");
      (errors.first_name
        ? firstNameRef
        : errors.last_name
          ? lastNameRef
          : emailRef
      ).current?.focus();
      return;
    }
    setFieldErrors({});

    setSubmitting(true);
    try {
      if (editing === "new") {
        const payload: AdminUserCreateIn = {
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          email: form.email.trim().toLowerCase(),
          role: form.role,
          all_categories: form.all_categories,
          category_ids: form.all_categories ? [] : form.category_ids,
          all_departments: form.all_departments,
          department_ids: form.all_departments ? [] : form.department_ids,
          is_active: form.is_active,
          ...(membership ? {} : { club_id: managedClubId }),
        };
        const created = await api<AdminUserCreateResult>("/users", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast.success(
          `Usuario creado. Contraseña temporal: ${created.temp_password} — ` +
            `también se envió por correo a ${created.email}.`,
          { duration: 0 },
        );
      } else {
        const payload: AdminUserUpdateIn = {
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          email: form.email.trim().toLowerCase(),
          role: form.role,
          all_categories: form.all_categories,
          category_ids: form.all_categories ? [] : form.category_ids,
          all_departments: form.all_departments,
          department_ids: form.all_departments ? [] : form.department_ids,
          is_active: form.is_active,
        };
        await api(`/users/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        toast.success("Usuario actualizado.");
      }
      setRefreshKey((k) => k + 1);
      closeModal();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Error al guardar el usuario",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const count = users?.length ?? 0;

  const roleOptions = useMemo(() => {
    // When editing a user whose role isn't assignable by the requester
    // (e.g. a manager editing an existing Administrador), keep it in the
    // list so the select doesn't silently drop it.
    const opts = [...assignableRoles];
    if (editing && editing !== "new" && editing.role && !opts.includes(editing.role)) {
      opts.unshift(editing.role);
    }
    return opts;
  }, [assignableRoles, editing]);

  if (!canView) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>
          Esta sección es solo para administradores de equipo.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Administración</span>
          <h1 className={styles.title}>Usuarios</h1>
          <p className={styles.subtitle}>
            Creá cuentas para el staff, asigná su rol y el alcance de datos que
            ven, y restablecé contraseñas. Al crear un usuario se le envía por
            correo una contraseña temporal.
          </p>
        </div>
        {canAdd && (
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryBtn}
              onClick={openCreate}
              disabled={!managedClubId}
            >
              + Nuevo usuario
            </button>
          </div>
        )}
      </header>

      <div className={styles.toolbar}>
        {membership ? (
          <span className={styles.chip}>Mostrando usuarios de: {managedClubName}</span>
        ) : (
          <label className={styles.field}>
            <span className={styles.label}>Club</span>
            <select
              value={selectedClubId}
              onChange={(e) => setSelectedClubId(e.target.value)}
            >
              {(meta?.clubs ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
        )}
        <span className={styles.count}>
          {count} usuario{count === 1 ? "" : "s"}
        </span>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {actionError && <div className={styles.error}>{actionError}</div>}

      {users === null ? (
        <div className={styles.muted}>Cargando usuarios…</div>
      ) : count === 0 ? (
        <div className={styles.empty}>
          No hay usuarios todavía. Hacé clic en + Nuevo usuario para empezar.
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Email</th>
                <th>Rol</th>
                <th>Alcance</th>
                <th>Estado</th>
                <th>Último ingreso</th>
                {canChange && <th aria-label="Acciones" />}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.is_active ? "" : styles.rowInactive}>
                  <td className={styles.nameCell}>
                    {u.first_name} {u.last_name}
                    {u.is_superuser && " ★"}
                  </td>
                  <td className={styles.emailCell}>{u.email}</td>
                  <td>
                    {u.role ? (
                      <span className={styles.roleBadge}>{u.role}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={styles.scopeCell}>{scopeSummary(u)}</td>
                  <td>
                    {canChange ? (
                      <button
                        type="button"
                        className={`${styles.statusPill} ${
                          u.is_active ? styles.statusActive : styles.statusInactive
                        }`}
                        onClick={() => toggleActive(u)}
                        title={u.is_active ? "Desactivar" : "Activar"}
                      >
                        {u.is_active ? "Activo" : "Inactivo"}
                      </button>
                    ) : (
                      <span
                        className={`${styles.statusPill} ${
                          u.is_active ? styles.statusActive : styles.statusInactive
                        }`}
                      >
                        {u.is_active ? "Activo" : "Inactivo"}
                      </span>
                    )}
                  </td>
                  <td>
                    {u.last_login
                      ? new Date(u.last_login).toLocaleDateString("es-CL")
                      : "Nunca"}
                  </td>
                  {canChange && (
                    <td className={styles.rowActions}>
                      <button
                        type="button"
                        className={styles.iconBtn}
                        onClick={() => openEdit(u)}
                        title="Editar"
                        aria-label={`Editar ${u.first_name} ${u.last_name}`}
                      >
                        ✏️
                      </button>
                      <button
                        type="button"
                        className={styles.iconBtn}
                        onClick={() => handleResetPassword(u)}
                        title="Restablecer contraseña"
                        aria-label={`Restablecer contraseña de ${u.first_name} ${u.last_name}`}
                      >
                        🔑
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={editing !== null}
        title={editing === "new" ? "Nuevo usuario" : "Editar usuario"}
        onClose={closeModal}
      >
        {editing !== null && (
          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span className={styles.label}>Nombre *</span>
                <input
                  ref={firstNameRef}
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                  aria-invalid={fieldErrors.first_name || undefined}
                  aria-describedby={fieldErrors.first_name ? errorId : undefined}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Apellido *</span>
                <input
                  ref={lastNameRef}
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                  aria-invalid={fieldErrors.last_name || undefined}
                  aria-describedby={fieldErrors.last_name ? errorId : undefined}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Email *</span>
                <input
                  ref={emailRef}
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  aria-invalid={fieldErrors.email || undefined}
                  aria-describedby={fieldErrors.email ? errorId : undefined}
                  placeholder="persona@club.cl"
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Rol *</span>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                >
                  {roleOptions.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </label>
            </div>

            {/* Scope: categories */}
            <div className={`${styles.field} ${styles.scopeGroup}`}>
              <span className={styles.label}>Categorías</span>
              {canGrantAllCats && (
                <label className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    checked={form.all_categories}
                    onChange={(e) =>
                      setForm({ ...form, all_categories: e.target.checked })
                    }
                  />
                  <span>Todas las categorías (incluye futuras)</span>
                </label>
              )}
              {!form.all_categories && (
                <div className={styles.checkboxList}>
                  {categories.length === 0 ? (
                    <span className={styles.hint}>No hay categorías disponibles.</span>
                  ) : (
                    categories.map((c) => (
                      <label key={c.id} className={styles.checkboxRow}>
                        <input
                          type="checkbox"
                          checked={form.category_ids.includes(c.id)}
                          onChange={(e) =>
                            setScope("category_ids", c.id, e.target.checked)
                          }
                        />
                        <span>{c.name}</span>
                      </label>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* Scope: departments */}
            <div className={`${styles.field} ${styles.scopeGroup}`}>
              <span className={styles.label}>Departamentos</span>
              {canGrantAllDeps && (
                <label className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    checked={form.all_departments}
                    onChange={(e) =>
                      setForm({ ...form, all_departments: e.target.checked })
                    }
                  />
                  <span>Todos los departamentos (incluye futuros)</span>
                </label>
              )}
              {!form.all_departments && (
                <div className={styles.checkboxList}>
                  {departments.length === 0 ? (
                    <span className={styles.hint}>No hay departamentos disponibles.</span>
                  ) : (
                    departments.map((d) => (
                      <label key={d.id} className={styles.checkboxRow}>
                        <input
                          type="checkbox"
                          checked={form.department_ids.includes(d.id)}
                          onChange={(e) =>
                            setScope("department_ids", d.id, e.target.checked)
                          }
                        />
                        <span>{d.name}</span>
                      </label>
                    ))
                  )}
                </div>
              )}
            </div>

            <label className={`${styles.field} ${styles.checkboxField}`}>
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              <span>Cuenta activa</span>
            </label>

            {actionError && (
              <div id={errorId} className={styles.error} role="alert">
                {actionError}
              </div>
            )}

            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={closeModal}
                disabled={submitting}
              >
                Cancelar
              </button>
              <button
                type="submit"
                className={styles.primaryBtn}
                disabled={submitting}
              >
                {submitting ? "Guardando…" : editing === "new" ? "Crear" : "Guardar"}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
