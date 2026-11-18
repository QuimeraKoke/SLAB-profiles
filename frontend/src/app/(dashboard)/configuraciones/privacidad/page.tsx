"use client";

/**
 * Administración › Privacidad e IA — the club decides whether its data may be
 * analysed by the AI provider, sees exactly what leaves the server and how
 * often it did. Backend: `audit/api.py` (/audit/ai-settings) and the single
 * gate `dashboards/ai_privacy.open_session`.
 */

import React, { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { usePermission } from "@/lib/permissions";
import { PRIVACY_EMAIL, PRIVACY_PATH } from "@/lib/privacy";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import type { MeResponse, UsersMeta } from "@/lib/types";
import base from "../usuarios/page.module.css";
import styles from "./page.module.css";

interface AiSettings {
  club_id: string;
  club_name: string;
  ai_enabled: boolean;
  pseudonymized: boolean;
  sends_30d: number;
  by_feature: { feature: string; count: number }[];
}

const SENT = [
  "Datos clínicos y de lesiones, check-in, cargas GPS y evaluaciones del jugador consultado",
  "Edad, posición y categoría",
  "Las preguntas del staff, con los nombres ya reemplazados",
];
const NOT_SENT = [
  "Nombres de jugadores (se envían como JUG-042) y del staff (STAFF-03)",
  "RUT, correos y teléfonos",
  "Fotos y fecha de nacimiento",
  "Identificadores internos de la plataforma",
];
const USES = [
  "Asistente del equipo, del panel, de la ficha y del resumen",
  "Readiness: lectura de cómo llega cada jugador (sin IA queda solo el cálculo determinístico)",
  "Narrativa de los informes PDF y Word (sin IA salen sin el texto interpretativo)",
];

function PrivacidadInner() {
  const { membership, setMe } = useAuth();
  const canView = usePermission("auth.view_user");
  const canChange = usePermission("auth.change_user");
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const [meta, setMeta] = useState<UsersMeta | null>(null);
  const clubId = membership ? membership.club.id : sp.get("club") || meta?.clubs[0]?.id || "";
  const [data, setData] = useState<AiSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!canView || membership) return;
    api<UsersMeta>("/users/meta").then(setMeta).catch(() => setMeta(null));
  }, [canView, membership]);

  const qs = membership || !clubId ? "" : `?club_id=${encodeURIComponent(clubId)}`;

  useEffect(() => {
    if (!canView || !clubId) return;
    let cancelled = false;
    api<AiSettings>(`/audit/ai-settings${qs}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar."); });
    return () => { cancelled = true; };
  }, [canView, clubId, qs]);

  const toggle = useCallback(async () => {
    if (!data || saving) return;
    const next = !data.ai_enabled;
    if (next) {
      const ok = await confirm({
        title: "Activar el análisis con IA",
        message: "Los datos del club se enviarán seudonimizados al proveedor de IA cuando alguien use el asistente, se calcule el readiness o se genere un informe. Cada envío queda en el Registro.",
        confirmLabel: "Activar",
      });
      if (!ok) return;
    } else {
      const ok = await confirm({
        title: "Desactivar el análisis con IA",
        message: "Los asistentes desaparecen, el readiness queda solo con el cálculo determinístico y los informes salen sin narrativa. No se enviará ningún dato al proveedor de IA.",
        confirmLabel: "Desactivar",
        variant: "danger",
      });
      if (!ok) return;
    }
    setSaving(true);
    try {
      const d = await api<AiSettings>(`/audit/ai-settings${qs}`, {
        method: "PUT",
        body: JSON.stringify({ ai_enabled: next }),
      });
      setData(d);
      toast.success(next ? "Análisis con IA activado." : "Análisis con IA desactivado.");
      if (membership) setMe(await api<MeResponse>("/auth/me")); // assistants show/hide right away
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar el cambio.");
    } finally {
      setSaving(false);
    }
  }, [data, saving, confirm, qs, toast, membership, setMe]);

  if (!canView) {
    return <div className={base.container}><div className={base.empty}>Esta sección es solo para administradores del club.</div></div>;
  }

  const copyPublicLink = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${PRIVACY_PATH}`);
      toast.success("Enlace copiado.");
    } catch {
      setError("No se pudo copiar el enlace.");
    }
  };

  const registroHref = `/configuraciones/registro?tab=accesos&tipo=ia${membership ? "" : `&club=${clubId}`}`;

  return (
    <div className={base.container}>
      <header className={base.header}>
        <div>
          <span className={base.eyebrow}>Administración</span>
          <h1 className={base.title}>Privacidad e IA</h1>
          <p className={base.subtitle}>
            Decide si los datos del club pueden analizarse con IA, y revisa qué se envía al proveedor y cuántas veces.
          </p>
        </div>
      </header>

      <div className={base.toolbar}>
        {membership ? (
          <span className={base.chip}>Club: {membership.club.name}</span>
        ) : (
          <label className={base.field}>
            <span className={base.label}>Club</span>
            <select value={clubId} onChange={(e) => router.replace(`${pathname}?club=${e.target.value}`, { scroll: false })}>
              {(meta?.clubs ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
      </div>

      {error && <div className={base.error} role="alert">{error}</div>}
      {!data && !error && <div className={base.muted}>Cargando…</div>}

      {data && (
        <>
          <section className={styles.card} aria-labelledby="ia-switch">
            <div className={styles.switchRow}>
              <div>
                <h2 id="ia-switch" className={styles.h2}>Análisis con IA</h2>
                <p className={styles.state}>
                  <span className={`${styles.dot} ${data.ai_enabled ? styles.dotOn : styles.dotOff}`} aria-hidden />
                  {data.ai_enabled ? "Activado" : "Desactivado: no se envía ningún dato al proveedor de IA"}
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={data.ai_enabled}
                aria-labelledby="ia-switch"
                className={`${styles.switch} ${data.ai_enabled ? styles.switchOn : ""}`}
                onClick={() => void toggle()}
                disabled={!canChange || saving}
                title={canChange ? undefined : "Solo un administrador del club puede cambiarlo"}
              >
                <span className={styles.knob} />
              </button>
            </div>
            <p className={styles.small}>Se usa en:</p>
            <ul className={styles.list}>{USES.map((u) => <li key={u}>{u}</li>)}</ul>
          </section>

          <div className={styles.grid}>
            <section className={styles.card} aria-labelledby="ia-sent">
              <h2 id="ia-sent" className={styles.h2}>Qué se envía</h2>
              <ul className={styles.list}>{SENT.map((u) => <li key={u}>{u}</li>)}</ul>
              <p className={styles.small}>
                Son datos de salud sin nombre, pero no anónimos: alguien que conoce el plantel podría reconocer al jugador
                por su edad y posición.
              </p>
            </section>
            <section className={styles.card} aria-labelledby="ia-notsent">
              <h2 id="ia-notsent" className={styles.h2}>Qué no se envía</h2>
              <ul className={styles.list}>{NOT_SENT.map((u) => <li key={u}>{u}</li>)}</ul>
              <p className={styles.small}>
                El reemplazo se hace en el servidor y la respuesta vuelve con los nombres reales. Si no se puede
                reemplazar, no se envía nada.
                {!data.pseudonymized && <strong> Atención: el seudonimizado está apagado en este entorno.</strong>}
              </p>
            </section>
          </div>

          <section className={styles.card} aria-labelledby="ia-sends">
            <h2 id="ia-sends" className={styles.h2}>Envíos de los últimos 30 días</h2>
            <p className={styles.big}>{data.sends_30d.toLocaleString("es-CL")}</p>
            {data.by_feature.length > 0 && (
              <ul className={styles.features}>
                {data.by_feature.map((f) => (
                  <li key={f.feature}><span>{f.feature}</span><span className={styles.num}>{f.count.toLocaleString("es-CL")}</span></li>
                ))}
              </ul>
            )}
            <Link href={registroHref} className={styles.link}>Ver cada envío en el Registro →</Link>
          </section>

          <section className={styles.card} aria-labelledby="ia-arco">
            <h2 id="ia-arco" className={styles.h2}>Derechos de los jugadores (ARCO)</h2>
            <p className={styles.text}>
              Un jugador, o el apoderado si es menor de edad, puede pedir una copia de sus datos, corregirlos,
              borrarlos u oponerse a un uso (por ejemplo, al análisis con IA) escribiendo a{" "}
              <a href={`mailto:${PRIVACY_EMAIL}`} className={styles.link}>{PRIVACY_EMAIL}</a>.
              SLAB verifica su identidad y coordina contigo antes de entregar o borrar cualquier dato.
            </p>
            <p className={styles.text}>
              Comparte la página pública con el plantel (por ejemplo, en la ficha de inscripción o el reglamento
              interno). No requiere cuenta en SLAB.
            </p>
            <div className={styles.actions}>
              <a href={PRIVACY_PATH} target="_blank" rel="noopener noreferrer" className={styles.link}>
                Ver la página pública ↗
              </a>
              <button type="button" className={styles.secondary} onClick={() => void copyPublicLink()}>
                Copiar enlace
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default function PrivacidadPage() {
  return (
    <Suspense fallback={null}>
      <PrivacidadInner />
    </Suspense>
  );
}
