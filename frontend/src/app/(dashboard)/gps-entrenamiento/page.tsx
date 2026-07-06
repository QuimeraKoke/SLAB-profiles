"use client";

import React, { useRef, useState } from "react";
import {
  UploadCloud, FileSpreadsheet, RotateCcw, Trophy, Dumbbell,
  CheckCircle2, AlertTriangle,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "./page.module.css";

interface SessionRow { label: string; date: string; tipo: string; players: number }
interface PreviewRow {
  player: string; session: string; date: string; tipo: string;
  status: string; values: Record<string, number>;
}
interface GpsUploadResult {
  mode: string;
  dry_run: boolean;
  total_rows: number;
  planned: number;
  created: number;
  skipped: number;
  updated: number;
  matched_players: number;
  players: string[];
  events_created: number;
  events_reused: number;
  sessions: SessionRow[];
  rows: PreviewRow[];
  match_days: MatchDay[];
  needs_match: boolean;
  department_id: string;
  competitions: CompetitionOpt[];
  blocked: number;
  unmatched: { code: string; rows: number }[];
  undated: { session: string; rows: number }[];
}
interface RivalOpt { external_id: number; name: string }
interface CompetitionOpt {
  league_id: number; name: string; start: string | null; end: string | null;
  teams: RivalOpt[];
}
interface MatchDay {
  date: string; label: string; opponent: string; competition: string;
  players: number; event_id: string | null; event_title: string | null;
  event: {
    title: string; date: string; competition: string | null;
    opponent: string | null; score: { home: number | null; away: number | null } | null;
  } | null;
}

// Headline metrics shown in the "values before save" table (the template has
// more; these are the sanity-check columns). Keys = gps_sesion field keys.
const METRIC_COLS: { key: string; label: string }[] = [
  { key: "tot_dur", label: "Tiempo (min)" },
  { key: "tot_dist", label: "Dist. (m)" },
  { key: "mpm", label: "m/min" },
  { key: "hsr", label: "HSR (m)" },
  { key: "sprint_dist", label: "Sprint (m)" },
  { key: "max_vel", label: "Vel. máx" },
  { key: "acc_dec", label: "Acc+Dec" },
];

function fmt(v: number | undefined): string {
  if (v === undefined || v === null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

const TIPO_LABEL: Record<string, string> = {
  partido: "Partido", amistoso: "Amistoso", tareas: "Tareas tácticas",
  entrenamiento: "Entrenamiento", reintegro: "Reintegro", otro: "Otro",
};

type Stage = "idle" | "previewing" | "preview" | "committing";

type Kind = "match" | "training";
const KINDS: { value: Kind; label: string; icon: typeof Trophy }[] = [
  { value: "match", label: "Partido", icon: Trophy },
  { value: "training", label: "Entrenamiento", icon: Dumbbell },
];
const SUBTITLE: Record<Kind, string> = {
  match: "Sube el archivo GPS del partido. Se vincula a un evento de partido y se guarda por jugador.",
  training: "Sube el archivo GPS de entrenamiento. Cada sesión del día se guarda por separado.",
};

export default function GpsTrainingUploadPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<Kind>("match");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<GpsUploadResult | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);

  function changeKind(k: Kind) {
    setKind(k);
    setPreview(null);   // preview is kind-specific — re-previewing required
    setStage("idle");
    setError(null);
  }

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  async function send(dryRun: boolean) {
    if (!file) {
      setError("Selecciona un archivo .xls/.xlsx primero.");
      return;
    }
    if (!categoryId) {
      setError("Selecciona una categoría en la barra superior.");
      return;
    }
    setError(null);
    setStage(dryRun ? "previewing" : "committing");

    const form = new FormData();
    form.append("file", file);
    form.append("category_id", categoryId);
    form.append("kind", kind);
    form.append("dry_run", dryRun ? "true" : "false");
    try {
      const res = await api<GpsUploadResult>("/gps-sessions/upload", {
        method: "POST",
        body: form,
      });
      if (dryRun) {
        setPreview(res);
        setStage("preview");
      } else {
        toast.success(
          `${res.created} registro${res.created === 1 ? "" : "s"} de GPS cargado${res.created === 1 ? "" : "s"}.`,
        );
        reset();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error procesando el archivo.");
      setStage("idle");
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setError(null);
    setStage("idle");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>Cargar GPS</h1>
          <p className={styles.sub}>{SUBTITLE[kind]}</p>
        </div>
        <span className={styles.catChip}>
          Cargando en categoría: <strong>{categoryName || "—"}</strong>
        </span>
      </header>

      {/* Tipo de carga — partido vs entrenamiento */}
      <div className={styles.selector} role="tablist" aria-label="Tipo de carga">
        {KINDS.map((k) => {
          const Icon = k.icon;
          const active = kind === k.value;
          return (
            <button
              key={k.value}
              role="tab"
              aria-selected={active}
              className={`${styles.selectorBtn} ${active ? styles.selectorActive : ""}`}
              onClick={() => changeKind(k.value)}
              disabled={stage === "committing"}
            >
              <Icon size={16} aria-hidden="true" />
              {k.label}
            </button>
          );
        })}
      </div>

      {error && <div className={styles.error} role="alert">{error}</div>}

      {/* ---------- file picker ---------- */}
      {stage !== "preview" && stage !== "committing" && (
        <div className={styles.dropzone}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xls,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            id="gps-file"
            className={styles.fileInput}
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }}
          />
          <label htmlFor="gps-file" className={styles.fileLabel}>
            <UploadCloud size={28} aria-hidden="true" />
            <span>{file ? "Cambiar archivo" : "Elegir archivo .xls / .xlsx"}</span>
          </label>
          {file && (
            <div className={styles.fileChosen}>
              <FileSpreadsheet size={16} aria-hidden="true" /> {file.name}
            </div>
          )}
          <button
            className={styles.primaryBtn}
            disabled={!file || stage === "previewing"}
            onClick={() => send(true)}
          >
            {stage === "previewing" ? "Procesando…" : "Cargar y previsualizar"}
          </button>
        </div>
      )}

      {/* ---------- preview ---------- */}
      {(stage === "preview" || stage === "committing") && preview && (
        <div className={styles.previewWrap}>
          <div className={styles.summary}>
            <Metric label="Filas leídas" value={preview.total_rows} />
            <Metric label="Jugadores reconocidos" value={preview.matched_players} tone="ok" />
            <Metric label="A crear" value={preview.created} tone="ok" />
            <Metric label="Ya cargados (omitidos)" value={preview.skipped} tone="dim" />
            <Metric
              label="Códigos sin coincidencia"
              value={preview.unmatched.length}
              tone={preview.unmatched.length ? "warn" : "dim"}
            />
            {kind === "match" && (
              <Metric
                label="Eventos de partido"
                value={preview.events_created + preview.events_reused}
              />
            )}
          </div>

          {kind === "match" && preview.match_days.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>Partidos del archivo ({preview.match_days.length})</h3>
              {preview.needs_match && (
                <div className={styles.bigError} role="alert">
                  <AlertTriangle size={22} aria-hidden="true" />
                  <div>
                    <strong>Falta el partido en el calendario.</strong> Un GPS de
                    partido debe vincularse a un evento de partido. Crea los partidos
                    marcados en rojo antes de guardar.
                  </div>
                </div>
              )}
              <div className={styles.matchList}>
                {preview.match_days.map((m) =>
                  m.event_id ? (
                    <div key={m.date} className={styles.matchLinked}>
                      <CheckCircle2 size={20} aria-hidden="true" className={styles.matchIcon} />
                      <div>
                        <div className={styles.matchLinkedTitle}>
                          {m.event?.title ?? m.event_title}
                          {m.event?.score && m.event.score.home != null && (
                            <span className={styles.scorePill}>
                              {m.event.score.home}–{m.event.score.away}
                            </span>
                          )}
                        </div>
                        <div className={styles.matchLinkedMeta}>
                          {m.event?.date ?? m.date}
                          {m.event?.competition ? ` · ${m.event.competition}` : ""}
                          {" · "}{m.players} jug. GPS se vincularán a este partido
                        </div>
                      </div>
                    </div>
                  ) : (
                    <MissingMatch
                      key={m.date}
                      day={m}
                      categoryId={categoryId ?? ""}
                      departmentId={preview.department_id}
                      competitions={preview.competitions}
                      onCreated={() => send(true)}
                    />
                  ),
                )}
              </div>
            </section>
          )}

          {preview.matched_players === 0 ? (
            <div className={styles.emptyState}>
              Ningún código del archivo coincide con un jugador de esta categoría.
              Agrega aliases en Administración → Gestionar plantel y reintenta.
            </div>
          ) : (
            <section>
              <h3 className={styles.sectionTitle}>Sesiones en el archivo ({preview.sessions.length})</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr><th>Sesión</th><th>Fecha</th><th>Tipo</th><th>Jugadores</th></tr>
                  </thead>
                  <tbody>
                    {preview.sessions.map((s) => (
                      <tr key={`${s.label}-${s.date}`}>
                        <td>{s.label}</td>
                        <td>{s.date}</td>
                        <td><span className={styles.tipoTag}>{TIPO_LABEL[s.tipo] ?? s.tipo}</span></td>
                        <td>{s.players}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {preview.rows.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>Valores a guardar ({preview.rows.length})</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Jugador</th>
                      <th>Sesión</th>
                      {METRIC_COLS.map((c) => <th key={c.key}>{c.label}</th>)}
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r, i) => (
                      <tr key={`${r.player}-${r.session}-${i}`}>
                        <td className={styles.playerCell}>{r.player}</td>
                        <td className={styles.sessionCell}>{r.session}</td>
                        {METRIC_COLS.map((c) => <td key={c.key}>{fmt(r.values[c.key])}</td>)}
                        <td>
                          {r.status === "nuevo"
                            ? <span className={styles.badgeNew}>nuevo</span>
                            : <span className={styles.badgeDim}>ya cargado</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {preview.unmatched.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>Sin coincidencia ({preview.unmatched.length})</h3>
              <div className={styles.chips}>
                {preview.unmatched.map((u) => (
                  <span key={u.code} className={styles.chipWarn}>{u.code} · {u.rows} fila(s)</span>
                ))}
              </div>
              <p className={styles.hint}>Agrega un alias para estos códigos y vuelve a subir el archivo.</p>
            </section>
          )}

          {preview.undated.length > 0 && (
            <section>
              <h3 className={styles.sectionTitle}>Sesiones sin fecha (se omiten) ({preview.undated.length})</h3>
              <div className={styles.chips}>
                {preview.undated.map((u) => (
                  <span key={u.session} className={styles.chipDim}>{u.session} · {u.rows} fila(s)</span>
                ))}
              </div>
            </section>
          )}

          <div className={styles.actions}>
            <button className={styles.ghostBtn} onClick={reset} disabled={stage === "committing"}>
              <RotateCcw size={15} aria-hidden="true" /> Empezar de nuevo
            </button>
            <button
              className={styles.primaryBtn}
              disabled={
                stage === "committing" ||
                preview.created === 0 ||
                (kind === "match" && preview.needs_match)
              }
              title={
                kind === "match" && preview.needs_match
                  ? "Crea los partidos faltantes antes de guardar"
                  : undefined
              }
              onClick={() => send(false)}
            >
              {stage === "committing" ? "Guardando…" : `Confirmar y guardar ${preview.created}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function MissingMatch({ day, categoryId, departmentId, competitions, onCreated }: {
  day: MatchDay; categoryId: string; departmentId: string;
  competitions: CompetitionOpt[]; onCreated: () => void;
}) {
  const { toast } = useToast();
  // Only competitions whose season window contains the match-day date.
  const eligible = competitions.filter(
    (c) => (!c.start || c.start <= day.date) && (!c.end || day.date <= c.end),
  );
  const comps = eligible.length ? eligible : competitions; // fallback: all
  const initialComp = comps.find((c) => c.name === day.competition) ?? comps[0] ?? null;

  const [leagueId, setLeagueId] = useState<number | null>(initialComp?.league_id ?? null);
  const selected = comps.find((c) => c.league_id === leagueId) ?? null;
  const rivals = selected?.teams ?? [];

  const initialRival =
    (day.opponent && rivals.find((t) => t.name.toLowerCase().includes(day.opponent.toLowerCase())))
    || rivals[0] || null;
  const [opponentId, setOpponentId] = useState<number | null>(initialRival?.external_id ?? null);
  const [freeOpponent, setFreeOpponent] = useState(day.opponent); // when comp has no roster
  const [isHome, setIsHome] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const opponentName = rivals.length
    ? (rivals.find((t) => t.external_id === opponentId)?.name ?? "")
    : freeOpponent.trim();

  async function create() {
    if (!selected) { setErr("Selecciona la competición."); return; }
    if (!opponentName) { setErr("Selecciona el rival."); return; }
    setBusy(true);
    setErr(null);
    try {
      await api("/events", {
        method: "POST",
        body: JSON.stringify({
          department_id: departmentId,
          event_type: "match",
          title: `vs ${opponentName}`,
          starts_at: `${day.date}T12:00:00`,
          scope: "category",
          category_id: categoryId,
          metadata: {
            opponent: opponentName,
            opponent_team_id: rivals.length ? opponentId : null,
            competition: selected.name,
            league_id: selected.league_id,
            is_home: isHome,
          },
        }),
      });
      toast.success(`Partido del ${day.date} creado.`);
      onCreated();   // re-runs the dry-run preview → the day is now linked
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "No se pudo crear el partido.");
      setBusy(false);
    }
  }

  return (
    <div className={styles.matchMissing}>
      <div className={styles.matchMissingHead}>
        <AlertTriangle size={18} aria-hidden="true" />
        <span>
          No hay partido para el <strong>{day.date}</strong> — {day.players} jug. GPS
          sin dónde guardarse. Créalo aquí:
        </span>
      </div>
      {comps.length === 0 ? (
        <p className={styles.hint}>
          No hay competiciones sincronizadas. Sincroniza los partidos primero.
        </p>
      ) : (
        <div className={styles.matchForm}>
          <label className={styles.field}>
            <span>Competición</span>
            <select
              value={leagueId ?? ""}
              onChange={(e) => {
                const id = Number(e.target.value);
                setLeagueId(id);
                const c = comps.find((x) => x.league_id === id);
                setOpponentId(c?.teams[0]?.external_id ?? null);
              }}
            >
              {comps.map((c) => <option key={c.league_id} value={c.league_id}>{c.name}</option>)}
            </select>
          </label>
          <label className={styles.field}>
            <span>Rival</span>
            {rivals.length ? (
              <select value={opponentId ?? ""} onChange={(e) => setOpponentId(Number(e.target.value))}>
                <option value="">Selecciona…</option>
                {rivals.map((t) => <option key={t.external_id} value={t.external_id}>{t.name}</option>)}
              </select>
            ) : (
              <input value={freeOpponent} onChange={(e) => setFreeOpponent(e.target.value)} placeholder="Rival" />
            )}
          </label>
          <label className={styles.homeToggle}>
            <input type="checkbox" checked={isHome} onChange={(e) => setIsHome(e.target.checked)} />
            Local
          </label>
          <button className={styles.smallBtn} disabled={busy} onClick={create}>
            {busy ? "Creando…" : "Crear partido"}
          </button>
        </div>
      )}
      {err && <div className={styles.error} role="alert">{err}</div>}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: "ok" | "warn" | "dim" }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={`${styles.metricValue} ${tone ? styles[tone] : ""}`}>{value}</span>
    </div>
  );
}
