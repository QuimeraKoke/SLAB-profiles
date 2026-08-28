"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError, getToken } from "@/lib/api";
import DeferredFilePicker from "@/components/forms/DeferredFilePicker";
import type { ExamField, ExamTemplate, PlayerSummary } from "@/lib/types";
import {
  FieldInput,
  defaultValue,
  groupFields,
  type FormValue,
} from "./DynamicUploader";
import styles from "./MultiRecordForm.module.css";

/** Varios registros INDEPENDIENTES en una pantalla.
 *
 *  El formulario individual apilado N veces: cada bloque tiene su jugador y
 *  todos los campos, y un botón agrega otro. Existe porque `team_table` resuelve
 *  un problema distinto —UNA carga compartida repartida entre jugadores, que
 *  sirve para "peso de todo el plantel"— y se siente forzado donde cada registro
 *  es su propia cosa: en medicación, cada indicación tiene su droga, su dosis y
 *  sus fechas.
 *
 *  Reusa `FieldInput` del formulario individual en vez de dibujar sus propios
 *  inputs, así que un campo nuevo (o un tipo nuevo, como el bodymap) aparece acá
 *  sin tocar este archivo.
 */

interface Props {
  template: ExamTemplate;
  categoryId: string;
  /** Jugador con el que arranca el primer bloque, si se entró desde su perfil. */
  initialPlayerId?: string;
  onSaved: () => void;
  onCancel?: () => void;
}

interface Block {
  /** Sólo para la key de React: los bloques se reordenan al borrar. */
  uid: number;
  playerId: string;
  values: Record<string, FormValue>;
  /** Archivos encolados por campo, subidos recién cuando existe el resultado. */
  files: Record<string, File[]>;
}

/** Campos que necesitan el ancho completo de la fila.
 *
 *  El resto entra en una grilla de columnas: con 8 campos por bloque, uno por
 *  fila hacía que dos registros no cupieran en la pantalla. Se decide por TIPO
 *  y no por una lista de claves, así que un examen nuevo no necesita tocar esto.
 */
function isWide(f: ExamField): boolean {
  return (
    (f.type === "text" && f.multiline === true)
    || f.type === "file"
    || f.type === "bodymap"
  );
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function MultiRecordForm({
  template,
  categoryId,
  initialPlayerId,
  onSaved,
  onCancel,
}: Props) {
  /** Campos que viajan en `result_data`.
   *
   *  Sin los calculados (los resuelve el backend) y sin los `file`: un adjunto
   *  no es un valor, se sube después contra `/attachments` con el id del
   *  resultado. Antes estaban acá y `FieldInput` —que no sabe de archivos— los
   *  dibujaba como CAJA DE TEXTO, y ese texto se guardaba como si fuera el
   *  adjunto.
   */
  const fields = useMemo<ExamField[]>(
    () => (template.config_schema.fields ?? []).filter(
      (f) => f.type !== "calculated" && f.type !== "file",
    ),
    [template],
  );
  const fileFields = useMemo<ExamField[]>(
    () => (template.config_schema.fields ?? []).filter((f) => f.type === "file"),
    [template],
  );
  const groups = useMemo(() => groupFields(fields), [fields]);

  const blank = (playerId = ""): Block => ({
    uid: Math.random(),
    playerId,
    values: Object.fromEntries(fields.map((f) => [f.key, defaultValue(f)])),
    files: {},
  });

  const [blocks, setBlocks] = useState<Block[]>([blank(initialPlayerId ?? "")]);
  const [players, setPlayers] = useState<PlayerSummary[] | null>(null);
  const [recordedDate, setRecordedDate] = useState(todayISO());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<PlayerSummary[]>(`/players?category_id=${categoryId}`)
      .then((ps) => {
        if (!cancelled) setPlayers(ps.filter((p) => p.is_active));
      })
      .catch(() => {
        if (!cancelled) setError("No se pudo cargar el plantel.");
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  const setValue = (uid: number, key: string, v: FormValue) =>
    setBlocks((bs) =>
      bs.map((b) => (b.uid === uid ? { ...b, values: { ...b.values, [key]: v } } : b)),
    );

  /** Duplica los datos del bloque anterior menos el jugador.
   *
   *  Casi siempre el segundo registro se parece al primero —misma droga, otra
   *  persona— así que copiar y cambiar lo que difiere es menos trabajo que
   *  llenar todo de nuevo. El jugador queda vacío a propósito: es el único campo
   *  que NUNCA se comparte, y arrastrarlo invitaría a guardar dos registros del
   *  mismo jugador sin querer.
   */
  const addBlock = (copyFrom?: Block) =>
    setBlocks((bs) => [
      ...bs,
      copyFrom
        // Los archivos NO se copian: un adjunto pertenece a un registro.
        ? { uid: Math.random(), playerId: "", values: { ...copyFrom.values }, files: {} }
        : blank(),
    ]);

  const removeBlock = (uid: number) =>
    setBlocks((bs) => (bs.length === 1 ? bs : bs.filter((b) => b.uid !== uid)));

  const usable = blocks.filter((b) => b.playerId);
  const duplicated = useMemo(() => {
    const seen = new Set<string>();
    const dup = new Set<string>();
    for (const b of usable) {
      if (seen.has(b.playerId)) dup.add(b.playerId);
      seen.add(b.playerId);
    }
    return dup;
  }, [usable]);

  /** Sube los archivos encolados, ya con los resultados creados.
   *
   *  El mapeo es lo delicado: el servidor OMITE las filas sin datos, así que
   *  `results` no tiene por qué alinearse con los bloques por índice. Se rehace
   *  la misma regla de "vacío" del lado del cliente y se zipean en orden, que es
   *  el orden en que el servidor crea. Por eso funciona incluso con el mismo
   *  jugador en dos bloques, donde mapear por `player_id` sería ambiguo.
   */
  const uploadAttachments = async (
    rows: { player_id: string; result_data: Record<string, FormValue> }[],
    results: { id: string; player_id: string }[],
  ) => {
    const isBlank = (v: FormValue) => v === null || v === "" || v === undefined;
    const nonBlank = usable.filter((b, i) =>
      Object.values(rows[i].result_data).some((v) => !isBlank(v)),
    );
    if (nonBlank.length !== results.length) return;   // no adivinar

    const token = getToken();
    const base =
      process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "")
      ?? "http://localhost:8000/api";
    for (let i = 0; i < nonBlank.length; i++) {
      const block = nonBlank[i];
      for (const [fieldKey, list] of Object.entries(block.files)) {
        for (const file of list) {
          const fd = new FormData();
          fd.append("file", file);
          fd.append("source_type", "exam_field");
          fd.append("source_id", results[i].id);
          fd.append("field_key", fieldKey);
          await fetch(`${base}/attachments`, {
            method: "POST",
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            body: fd,
          });
        }
      }
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (usable.length === 0) {
      setError("Elegí al menos un jugador.");
      return;
    }
    setSaving(true);
    const rows = usable.map((b) => ({
      player_id: b.playerId,
      result_data: b.values,
    }));
    try {
      // `/results/team` con `shared_data` vacío: cada fila lleva TODO lo suyo,
      // que es exactamente la forma que este modo produce. No hace falta un
      // endpoint nuevo.
      const res = await api<{
        created: number;
        skipped: number;
        results: { id: string; player_id: string }[];
      }>(
        "/results/team",
        {
          method: "POST",
          body: JSON.stringify({
            template_id: template.id,
            category_id: categoryId,
            recorded_at: `${recordedDate}T12:00:00`,
            shared_data: {},
            rows,
          }),
        },
      );
      await uploadAttachments(rows, res.results ?? []);
      if (res.skipped > 0 && res.created === 0) {
        setError(
          "No se guardó nada: los registros no tienen datos además del jugador.",
        );
        return;
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
    } finally {
      setSaving(false);
    }
  };

  const nameOf = (id: string) => {
    const p = players?.find((x) => x.id === id);
    return p ? `${p.first_name} ${p.last_name}` : "";
  };

  return (
    <form className={styles.wrapper} onSubmit={submit}>
      <div className={styles.intro}>
        Cargá varios registros sin salir de la pantalla. Cada bloque es
        independiente: su jugador, sus datos.
      </div>

      <label className={styles.dateField}>
        <span className={styles.label}>Fecha del registro</span>
        <input
          type="date"
          value={recordedDate}
          onChange={(e) => setRecordedDate(e.target.value)}
        />
        <span className={styles.hint}>
          Es la fecha en que queda guardado, común a todos los bloques. Las
          fechas propias de cada registro (inicio, fin) van en sus campos.
        </span>
      </label>

      {blocks.map((b, i) => (
        <fieldset key={b.uid} className={styles.block}>
          <legend className={styles.blockTitle}>
            Registro {i + 1}
            {b.playerId && ` · ${nameOf(b.playerId)}`}
          </legend>

          <label className={`${styles.field} ${styles.playerField}`}>
            <span className={styles.label}>Jugador</span>
            <select
              value={b.playerId}
              onChange={(e) =>
                setBlocks((bs) =>
                  bs.map((x) =>
                    x.uid === b.uid ? { ...x, playerId: e.target.value } : x,
                  ),
                )
              }
              required
            >
              <option value="">— Seleccionar —</option>
              {(players ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.first_name} {p.last_name}
                </option>
              ))}
            </select>
            {duplicated.has(b.playerId) && (
              <span className={styles.warn}>
                Este jugador ya está en otro bloque — se van a guardar dos
                registros para él.
              </span>
            )}
          </label>

          {groups.map((g) => (
            <div key={g.group ?? "__none__"} className={styles.group}>
              {g.group && <h4 className={styles.groupTitle}>{g.group}</h4>}
              <div className={styles.grid}>
                {g.items.map((f) => (
                  <label
                    key={f.key}
                    className={`${styles.field} ${isWide(f) ? styles.wide : ""}`}
                  >
                    <span className={styles.label}>
                      {f.unit ? `${f.label} [${f.unit}]` : f.label}
                    </span>
                    <FieldInput
                      field={f}
                      value={b.values[f.key] ?? null}
                      onChange={(v) => setValue(b.uid, f.key, v)}
                    />
                  </label>
                ))}
              </div>
            </div>
          ))}

          {fileFields.map((f) => (
            <div key={f.key} className={styles.fileField}>
              <span className={styles.label}>{f.label}</span>
              <DeferredFilePicker
                value={b.files[f.key] ?? []}
                onChange={(list) =>
                  setBlocks((bs) =>
                    bs.map((x) =>
                      x.uid === b.uid
                        ? { ...x, files: { ...x.files, [f.key]: list } }
                        : x,
                    ),
                  )
                }
              />
            </div>
          ))}

          {blocks.length > 1 && (
            <button
              type="button"
              className={styles.remove}
              onClick={() => removeBlock(b.uid)}
            >
              Quitar este registro
            </button>
          )}
        </fieldset>
      ))}

      <div className={styles.addRow}>
        <button type="button" className={styles.add} onClick={() => addBlock()}>
          + Agregar otro registro
        </button>
        <button
          type="button"
          className={styles.addCopy}
          onClick={() => addBlock(blocks[blocks.length - 1])}
        >
          + Agregar copiando el anterior
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      <div className={styles.actions}>
        {onCancel && (
          <button type="button" className={styles.cancel} onClick={onCancel}>
            Cancelar
          </button>
        )}
        <button type="submit" className={styles.save} disabled={saving || usable.length === 0}>
          {saving
            ? "Guardando…"
            : `Guardar ${usable.length} registro${usable.length === 1 ? "" : "s"}`}
        </button>
      </div>
    </form>
  );
}
