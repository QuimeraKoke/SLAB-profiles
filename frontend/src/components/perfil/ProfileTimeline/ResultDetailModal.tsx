"use client";

/**
 * One timeline entry, in full — rendered from the exam's OWN definition.
 *
 * Nothing here knows any particular exam. The template's `config_schema.fields`
 * says what each value is (number with unit and bands, categorical with display
 * labels, multiline text, date, boolean, body map, attached files) and in which
 * group it goes; the modal walks the fields in the order the form shows them
 * and renders each by its type. A new exam — or a field added to an existing
 * one — shows up here with no code change.
 *
 * What it adds around the fields:
 * * the linked calendar event (a match, a training session) when the result
 *   has one, with what its metadata carries (rival, local/visita, competition);
 * * provenance: who wrote it and where it came from, for imported or mirrored
 *   rows (`result_data.autor` / `origen`) — not the internal ids;
 * * a link to the department tab (or the Lesiones tab for an injury), where
 *   the record can be edited.
 *
 * Empty fields are left out: on a 40-field form, a modal of dashes hides the
 * five values that were actually recorded.
 */

import Link from "next/link";
import React, { useMemo } from "react";

import AttachmentList from "@/components/ui/AttachmentList/AttachmentList";
import BodyMapField from "@/components/forms/BodyMapField";
import Modal from "@/components/ui/Modal/Modal";
import { EVENT_TYPE_LABEL } from "@/lib/eventTypes";
import { bandColor, findBandForValue } from "@/lib/reference";
import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";

import styles from "./ResultDetailModal.module.css";

/** Where an imported or mirrored row came from, in the staff's words. */
const ORIGEN: Record<string, string> = {
  daily: "Daily (reunión de la mañana)",
  planilla_club_formativo: "Planilla de evaluaciones del formativo",
  planilla_club_formativo_gps: "Planilla GPS del formativo",
  google_sheets_formativo: "Formulario de wellness del formativo",
  planilla_club_lesiones_formativo: "Planilla de lesiones del formativo",
  planilla_peso_diario: "Planilla de peso diario (nutrición)",
};

interface Props {
  result: ExamResult | null;
  template: ExamTemplate | undefined;
  playerId: string;
  /** The date the timeline shows for this entry (doctor-typed `fecha` when set). */
  effectiveDate: Date | null;
  onClose: () => void;
}

export default function ResultDetailModal({ result, template, playerId, effectiveDate, onClose }: Props) {
  const grupos = useMemo(() => (result && template ? agrupar(result, template) : []), [result, template]);
  if (!result) return null;

  const dept = template?.department;
  const esLesion = template?.slug === "lesiones";
  const destino = esLesion ? "lesiones" : dept?.slug;
  const registrado = new Date(result.recorded_at);
  const mostrarRegistro = effectiveDate
    && Math.abs(registrado.getTime() - effectiveDate.getTime()) > 36 * 3600 * 1000;
  const autor = texto(result.result_data?.autor);
  const origen = texto(result.result_data?.origen);

  return (
    <Modal open onClose={onClose} title={template?.name ?? "Registro"}>
      <div className={styles.body}>
        <div className={styles.meta}>
          {dept && <span className={styles.badge}>{dept.name}</span>}
          <span className={styles.fecha}>{fechaLarga(effectiveDate ?? registrado)}</span>
          {mostrarRegistro && (
            <span className={styles.muted}>· registrado el {fechaLarga(registrado)}</span>
          )}
        </div>

        {result.event && <EventoVinculado event={result.event} />}

        {grupos.length === 0 ? (
          <p className={styles.vacio}>Este registro no tiene valores cargados.</p>
        ) : (
          grupos.map((g) => (
            <section key={g.nombre} className={styles.grupo}>
              {grupos.length > 1 && <h4 className={styles.grupoTitulo}>{g.nombre}</h4>}
              <dl className={styles.campos}>
                {g.campos.map((f) => (
                  <Campo key={f.key} field={f} value={result.result_data[f.key]} resultId={result.id} />
                ))}
              </dl>
            </section>
          ))
        )}

        {(autor || origen) && (
          <p className={styles.procedencia}>
            {autor && <>Registrado por <strong>{autor}</strong></>}
            {autor && origen && " · "}
            {origen && <>Origen: {ORIGEN[origen] ?? origen}</>}
          </p>
        )}

        {destino && (
          <div className={styles.acciones}>
            <Link href={`/perfil/${playerId}?tab=${destino}`} className={styles.link} onClick={onClose}>
              {esLesion ? "Ver en Lesiones" : `Ver en ${dept?.name}`} →
            </Link>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ── fields ───────────────────────────────────────────────────────────────
interface Grupo {
  nombre: string;
  campos: ExamField[];
}

function vacio(field: ExamField, v: unknown): boolean {
  if (field.type === "file") return false;          // files live outside result_data
  if (v === null || v === undefined || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (field.type === "bodymap" && typeof v === "object") {
    const b = v as { zones?: unknown[]; pins?: unknown[] };
    return !(b.zones?.length || b.pins?.length);
  }
  return false;
}

/** Fields in form order, grouped by `group`, empties dropped. */
function agrupar(result: ExamResult, template: ExamTemplate): Grupo[] {
  const out: Grupo[] = [];
  for (const f of template.config_schema?.fields ?? []) {
    if (vacio(f, result.result_data?.[f.key])) continue;
    const nombre = f.group || "Datos";
    let g = out.find((x) => x.nombre === nombre);
    if (!g) {
      g = { nombre, campos: [] };
      out.push(g);
    }
    g.campos.push(f);
  }
  return out;
}

function Campo({ field, value, resultId }: { field: ExamField; value: unknown; resultId: string }) {
  if (field.type === "bodymap") {
    return (
      <div className={styles.campoAncho}>
        <dt>{field.label}</dt>
        <dd><BodyMapField diagramKey={field.diagram ?? "body"} value={value} readOnly /></dd>
      </div>
    );
  }
  if (field.type === "file") {
    return (
      <div className={styles.campoAncho}>
        <dt>{field.label}</dt>
        <dd><AttachmentList sourceType="exam_field" sourceId={resultId} fieldKey={field.key} readOnly /></dd>
      </div>
    );
  }
  if (field.type === "text" && field.multiline) {
    return (
      <div className={styles.campoAncho}>
        <dt>{field.label}</dt>
        <dd className={styles.textoLargo}>{String(value)}</dd>
      </div>
    );
  }
  return (
    <div className={styles.campo}>
      <dt>{field.label}</dt>
      <dd>{valor(field, value)}</dd>
    </div>
  );
}

function valor(field: ExamField, v: unknown): React.ReactNode {
  switch (field.type) {
    case "number":
    case "calculated": {
      const n = typeof v === "number" ? v : Number(v);
      if (!Number.isFinite(n)) return String(v);
      const banda = findBandForValue(n, field.reference_ranges);
      return (
        <>
          <span className={styles.numero}>{numero(n)}</span>
          {field.unit && <span className={styles.unidad}> {field.unit}</span>}
          {banda && (
            <span className={styles.banda} style={{ background: bandColor(banda) }}>{banda.label}</span>
          )}
        </>
      );
    }
    case "boolean":
      return v === true || v === "true" ? "Sí" : "No";
    case "date":
      return typeof v === "string" ? fechaCorta(v) : String(v);
    case "categorical": {
      const lista = Array.isArray(v) ? v : [v];
      return lista.map((x) => field.option_labels?.[String(x)] ?? String(x)).join(", ");
    }
    default:
      return Array.isArray(v) ? v.join(", ") : String(v);
  }
}

// ── linked event ─────────────────────────────────────────────────────────
function EventoVinculado({ event }: { event: NonNullable<ExamResult["event"]> }) {
  // Match metadata as fixtures_sync / COMET write it: `opponent`, `is_home`,
  // `score: {home, away}`, `competition`, `venue`. Other event types carry
  // none of these and show just their title and date.
  const m = event.metadata ?? {};
  const rival = texto(m.opponent);
  const local = m.is_home === true ? "Local" : m.is_home === false ? "Visita" : null;
  const sc = (m.score ?? {}) as { home?: unknown; away?: unknown };
  const marcador = typeof sc.home === "number" && typeof sc.away === "number"
    ? `${sc.home}–${sc.away}` : null;
  const detalle = [rival && `vs ${rival}`, local, marcador, texto(m.competition), texto(m.venue)]
    .filter(Boolean).join(" · ");
  return (
    <div className={styles.evento}>
      <span className={styles.eventoTipo}>{EVENT_TYPE_LABEL[event.event_type] ?? event.event_type}</span>
      <span className={styles.eventoTitulo}>{event.title}</span>
      <span className={styles.muted}>
        {fechaLarga(new Date(event.starts_at))}
        {detalle && ` · ${detalle}`}
      </span>
    </div>
  );
}

// ── formatting ───────────────────────────────────────────────────────────
function texto(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function numero(n: number): string {
  return Number.isInteger(n)
    ? n.toLocaleString("es-CL")
    : n.toLocaleString("es-CL", { maximumFractionDigits: 2 });
}

function fechaLarga(d: Date): string {
  return d.toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function fechaCorta(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString("es-CL", { day: "numeric", month: "short", year: "numeric" });
}
