"use client";

import React, { useEffect, useMemo, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useCategoryContext } from "@/context/CategoryContext";
import { usePermission } from "@/lib/permissions";
import type {
  Category,
  PlayerCreateIn,
  PlayerPatchIn,
  PlayerSummary,
  Position,
  Sex,
} from "@/lib/types";
import styles from "./page.module.css";

type FormState = {
  first_name: string;
  last_name: string;
  date_of_birth: string;
  sex: Sex;
  nationality: string;
  is_active: boolean;
  category_id: string;
  position_id: string;
  current_weight_kg: string;
  current_height_cm: string;
};

const EMPTY_FORM: FormState = {
  first_name: "",
  last_name: "",
  date_of_birth: "",
  sex: "",
  nationality: "",
  is_active: true,
  category_id: "",
  position_id: "",
  current_weight_kg: "",
  current_height_cm: "",
};

function fromPlayer(p: PlayerSummary): FormState {
  return {
    first_name: p.first_name,
    last_name: p.last_name,
    date_of_birth: p.date_of_birth ?? "",
    sex: p.sex,
    nationality: p.nationality,
    is_active: p.is_active,
    category_id: p.category_id,
    position_id: p.position?.id ?? "",
    current_weight_kg:
      p.current_weight_kg !== null ? String(p.current_weight_kg) : "",
    current_height_cm:
      p.current_height_cm !== null ? String(p.current_height_cm) : "",
  };
}

export default function PlayersAdminPage() {
  const { membership } = useAuth();
  // Configuraciones is a roster-management surface, not a viewer — show
  // ALL categories the user can manage, not just the navbar's pick. The
  // global picker still drives the default form's category for "+ Nuevo".
  const { categoryId: defaultCategoryId } = useCategoryContext();

  const [players, setPlayers] = useState<PlayerSummary[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Filter chips
  const [showInactive, setShowInactive] = useState(true);
  const [filterCategory, setFilterCategory] = useState<string>("");

  // Edit / create form state
  const [editing, setEditing] = useState<PlayerSummary | "new" | null>(null);
  const canAdd = usePermission("core.add_player");
  const canChange = usePermission("core.change_player");
  const canDelete = usePermission("core.delete_player");
  const showRowActions = canChange || canDelete;
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  // Load all the data we need on the page once. Reloads on `refreshKey`
  // so saves can trigger a refetch without a full route change.
  useEffect(() => {
    if (!membership) return;
    let cancelled = false;
    Promise.all([
      api<PlayerSummary[]>("/players?include_inactive=true"),
      api<Category[]>(`/categories?club_id=${membership.club.id}`),
      api<Position[]>(`/clubs/${membership.club.id}/positions`),
    ])
      .then(([ps, cats, poss]) => {
        if (cancelled) return;
        setPlayers(ps);
        setCategories(
          [...cats].sort((a, b) => a.name.localeCompare(b.name)),
        );
        setPositions(
          [...poss].sort(
            (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name),
          ),
        );
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Error al cargar jugadores",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [membership, refreshKey]);

  const filteredPlayers = useMemo(() => {
    if (!players) return [];
    return players.filter((p) => {
      if (!showInactive && !p.is_active) return false;
      if (filterCategory && p.category_id !== filterCategory) return false;
      return true;
    });
  }, [players, showInactive, filterCategory]);

  const openCreate = () => {
    setForm({
      ...EMPTY_FORM,
      category_id: defaultCategoryId ?? categories[0]?.id ?? "",
    });
    setEditing("new");
    setActionError(null);
  };

  const openEdit = (player: PlayerSummary) => {
    setForm(fromPlayer(player));
    setEditing(player);
    setActionError(null);
  };

  const closeModal = () => {
    setEditing(null);
    setActionError(null);
  };

  const toggleActive = async (player: PlayerSummary) => {
    setActionError(null);
    try {
      await api<PlayerSummary>(`/players/${player.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !player.is_active }),
      });
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "No se pudo cambiar el estado",
      );
    }
  };

  const handleDelete = async (player: PlayerSummary) => {
    const ok = confirm(
      `¿Borrar a ${player.first_name} ${player.last_name}? ` +
        `Si tiene historial (resultados, episodios, contratos) la operación va a fallar — ` +
        `usa el toggle para desactivarlo en su lugar.`,
    );
    if (!ok) return;
    setActionError(null);
    try {
      await api(`/players/${player.id}`, { method: "DELETE" });
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "No se pudo borrar el jugador",
      );
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setActionError(null);

    if (!form.first_name.trim() || !form.last_name.trim()) {
      setActionError("Nombre y apellido son requeridos.");
      return;
    }
    if (!form.category_id) {
      setActionError("Elige una categoría.");
      return;
    }

    setSubmitting(true);
    try {
      if (editing === "new") {
        const payload: PlayerCreateIn = {
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          date_of_birth: form.date_of_birth || null,
          sex: form.sex,
          nationality: form.nationality.trim(),
          is_active: form.is_active,
          category_id: form.category_id,
          position_id: form.position_id || null,
          current_weight_kg: form.current_weight_kg
            ? Number(form.current_weight_kg)
            : null,
          current_height_cm: form.current_height_cm
            ? Number(form.current_height_cm)
            : null,
        };
        await api("/players", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      } else {
        const payload: PlayerPatchIn = {
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          date_of_birth: form.date_of_birth || null,
          sex: form.sex,
          nationality: form.nationality.trim(),
          is_active: form.is_active,
          category_id: form.category_id,
          position_id: form.position_id || null,
          current_weight_kg: form.current_weight_kg
            ? Number(form.current_weight_kg)
            : null,
          current_height_cm: form.current_height_cm
            ? Number(form.current_height_cm)
            : null,
        };
        await api(`/players/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      }
      setRefreshKey((k) => k + 1);
      closeModal();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Error al guardar el jugador",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Configuraciones</span>
          <h1 className={styles.title}>Jugadores</h1>
          <p className={styles.subtitle}>
            Gestiona el plantel — alta, baja y edición de jugadores. Para
            mantener el historial sin contar al jugador en el plantel activo,
            desactivalo en lugar de borrarlo.
          </p>
        </div>
        {canAdd && (
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryBtn}
              onClick={openCreate}
              disabled={categories.length === 0}
            >
              + Nuevo jugador
            </button>
          </div>
        )}
      </header>

      <div className={styles.toolbar}>
        <label className={styles.field}>
          <span className={styles.label}>Categoría</span>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
          >
            <option value="">Todas</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          <span>Incluir inactivos</span>
        </label>
        <span className={styles.count}>
          {filteredPlayers.length} jugador
          {filteredPlayers.length === 1 ? "" : "es"}
        </span>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {actionError && <div className={styles.error}>{actionError}</div>}

      {players === null ? (
        <div className={styles.muted}>Cargando jugadores…</div>
      ) : filteredPlayers.length === 0 ? (
        <div className={styles.empty}>
          {(players?.length ?? 0) === 0
            ? "No hay jugadores cargados todavía. Haz clic en + Nuevo jugador para empezar."
            : "Ningún jugador coincide con los filtros."}
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Jugador</th>
                <th>Categoría</th>
                <th>Posición</th>
                <th>Nacimiento</th>
                <th>Peso</th>
                <th>Altura</th>
                <th>Estado</th>
                {showRowActions && <th aria-label="Acciones" />}
              </tr>
            </thead>
            <tbody>
              {filteredPlayers.map((p) => {
                const cat = categories.find((c) => c.id === p.category_id);
                return (
                  <tr key={p.id} className={p.is_active ? "" : styles.rowInactive}>
                    <td className={styles.nameCell}>
                      {p.first_name} {p.last_name}
                    </td>
                    <td>{cat?.name ?? "—"}</td>
                    <td>{p.position?.name ?? "—"}</td>
                    <td>{p.date_of_birth ?? "—"}</td>
                    <td>{p.current_weight_kg ?? "—"}</td>
                    <td>{p.current_height_cm ?? "—"}</td>
                    <td>
                      {canChange ? (
                        <button
                          type="button"
                          className={`${styles.statusPill} ${
                            p.is_active ? styles.statusActive : styles.statusInactive
                          }`}
                          onClick={() => toggleActive(p)}
                          title={p.is_active ? "Desactivar" : "Activar"}
                        >
                          {p.is_active ? "Activo" : "Inactivo"}
                        </button>
                      ) : (
                        <span
                          className={`${styles.statusPill} ${
                            p.is_active ? styles.statusActive : styles.statusInactive
                          }`}
                        >
                          {p.is_active ? "Activo" : "Inactivo"}
                        </span>
                      )}
                    </td>
                    {showRowActions && (
                      <td className={styles.rowActions}>
                        {canChange && (
                          <button
                            type="button"
                            className={styles.iconBtn}
                            onClick={() => openEdit(p)}
                            title="Editar"
                            aria-label="Editar jugador"
                          >
                            ✏️
                          </button>
                        )}
                        {canDelete && (
                          <button
                            type="button"
                            className={`${styles.iconBtn} ${styles.iconBtnDanger}`}
                            onClick={() => handleDelete(p)}
                            title="Borrar"
                            aria-label="Borrar jugador"
                          >
                            🗑
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={editing !== null}
        title={editing === "new" ? "Nuevo jugador" : "Editar jugador"}
        onClose={closeModal}
      >
        {editing !== null && (
          <form className={styles.form} onSubmit={handleSubmit}>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span className={styles.label}>Nombre *</span>
                <input
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                  required
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Apellido *</span>
                <input
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                  required
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Categoría *</span>
                <select
                  value={form.category_id}
                  onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                  required
                >
                  <option value="">— Seleccionar —</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Posición</span>
                <select
                  value={form.position_id}
                  onChange={(e) => setForm({ ...form, position_id: e.target.value })}
                >
                  <option value="">—</option>
                  {positions.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.abbreviation ? ` (${p.abbreviation})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Fecha de nacimiento</span>
                <input
                  type="date"
                  value={form.date_of_birth}
                  onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Sexo</span>
                <select
                  value={form.sex}
                  onChange={(e) => setForm({ ...form, sex: e.target.value as Sex })}
                >
                  <option value="">—</option>
                  <option value="M">Masculino</option>
                  <option value="F">Femenino</option>
                </select>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Nacionalidad</span>
                <input
                  value={form.nationality}
                  onChange={(e) => setForm({ ...form, nationality: e.target.value })}
                  placeholder="Chile"
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Peso (kg)</span>
                <input
                  type="number"
                  step="0.1"
                  value={form.current_weight_kg}
                  onChange={(e) => setForm({ ...form, current_weight_kg: e.target.value })}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.label}>Altura (cm)</span>
                <input
                  type="number"
                  step="0.1"
                  value={form.current_height_cm}
                  onChange={(e) => setForm({ ...form, current_height_cm: e.target.value })}
                />
              </label>
              <label className={`${styles.field} ${styles.checkboxField}`}>
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                />
                <span>Activo en el plantel</span>
              </label>
            </div>

            {actionError && <div className={styles.error}>{actionError}</div>}

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
