"use client";

import React, { useEffect, useRef, useState } from "react";

import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/components/ui/Toast/Toast";
import type { Category, PlayerDetail, PlayerPatchIn, Position, Sex } from "@/lib/types";
import styles from "./PlayerEditModal.module.css";

interface FormState {
  first_name: string;
  last_name: string;
  date_of_birth: string;
  sex: Sex;
  nationality: string;
  category_id: string;
  position_id: string;
  current_height_cm: string;
  current_weight_kg: string;
}

/** Edit a player's core data in a modal (uses the shared <Modal>). Loads the
 *  player detail + categories + positions on open, PATCHes on save. */
export default function PlayerEditModal({
  playerId, onClose, onSaved,
}: { playerId: string; onClose: () => void; onSaved: () => void }) {
  const { membership } = useAuth();
  const { toast } = useToast();
  const [form, setForm] = useState<FormState | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const clubId = membership?.club.id;
    Promise.all([
      api<PlayerDetail>(`/players/${playerId}`),
      clubId ? api<Category[]>(`/categories?club_id=${clubId}`) : Promise.resolve([]),
      clubId ? api<Position[]>(`/clubs/${clubId}/positions`) : Promise.resolve([]),
    ])
      .then(([p, cats, pos]) => {
        if (cancelled) return;
        setCategories(cats);
        setPositions(pos);
        setForm({
          first_name: p.first_name ?? "",
          last_name: p.last_name ?? "",
          date_of_birth: p.date_of_birth ?? "",
          sex: p.sex ?? "",
          nationality: p.nationality ?? "",
          category_id: p.category?.id ?? "",
          position_id: p.position?.id ?? "",
          current_height_cm: p.current_height_cm != null ? String(p.current_height_cm) : "",
          current_weight_kg: p.current_weight_kg != null ? String(p.current_weight_kg) : "",
        });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "No se pudo cargar el jugador.");
      });
    return () => { cancelled = true; };
  }, [playerId, membership]);

  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => (f ? { ...f, [k]: v } : f));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    if (!form.first_name.trim() || !form.last_name.trim()) {
      setError("Nombre y apellido son requeridos.");
      firstFieldRef.current?.focus();
      return;
    }
    if (!form.category_id) {
      setError("Elegí una categoría.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload: PlayerPatchIn = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      date_of_birth: form.date_of_birth || null,
      sex: form.sex,
      nationality: form.nationality.trim(),
      category_id: form.category_id,
      position_id: form.position_id || null,
      current_height_cm: form.current_height_cm ? Number(form.current_height_cm) : null,
      current_weight_kg: form.current_weight_kg ? Number(form.current_weight_kg) : null,
    };
    try {
      await api(`/players/${playerId}`, { method: "PATCH", body: JSON.stringify(payload) });
      toast.success("Jugador actualizado.");
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open title="Editar jugador" onClose={onClose}>
      {error && <div className={styles.error} role="alert">{error}</div>}
      {!form ? (
        <p className={styles.muted}>Cargando…</p>
      ) : (
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Nombre</span>
              <input ref={firstFieldRef} value={form.first_name}
                onChange={(e) => set("first_name", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Apellido</span>
              <input value={form.last_name} onChange={(e) => set("last_name", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Categoría</span>
              <select value={form.category_id} onChange={(e) => set("category_id", e.target.value)}>
                <option value="">—</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className={styles.field}>
              <span>Posición</span>
              <select value={form.position_id} onChange={(e) => set("position_id", e.target.value)}>
                <option value="">—</option>
                {positions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className={styles.field}>
              <span>Fecha de nacimiento</span>
              <input type="date" value={form.date_of_birth}
                onChange={(e) => set("date_of_birth", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Sexo</span>
              <select value={form.sex} onChange={(e) => set("sex", e.target.value as Sex)}>
                <option value="">—</option>
                <option value="M">Masculino</option>
                <option value="F">Femenino</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>Nacionalidad</span>
              <input value={form.nationality} onChange={(e) => set("nationality", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Estatura (cm)</span>
              <input type="number" value={form.current_height_cm}
                onChange={(e) => set("current_height_cm", e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Peso (kg)</span>
              <input type="number" value={form.current_weight_kg}
                onChange={(e) => set("current_weight_kg", e.target.value)} />
            </label>
          </div>
          <div className={styles.actions}>
            <button type="button" className={styles.cancel} onClick={onClose}>Cancelar</button>
            <button type="submit" className={styles.save} disabled={submitting}>
              {submitting ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
