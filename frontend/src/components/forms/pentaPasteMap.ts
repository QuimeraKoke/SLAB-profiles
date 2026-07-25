// Canonical row order of the nutritionist's anthropometry Excel report
// ("5 componentes"), mapping each row to the pentacompartimental template's raw
// field key. Paste-to-fill maps by THIS order (labels repeat — e.g. "Pantorrilla
// (máxima)" is both a perímetro and a pliegue — so position, not label, is the
// source of truth; the pasted label is only used to sanity-check alignment).
//
// `label` is the report's exact column-1 text, used for the alignment check.
// Keep this list in sync with the report layout; `sexo` is intentionally absent
// (the report's two columns don't include it).
export interface PentaPasteRow {
  label: string;
  key: string;
}

export const PENTA_PASTE_ROWS: PentaPasteRow[] = [
  { label: "Peso Bruto (Kg)", key: "peso" },
  { label: "Talla Corporal (cm)", key: "talla" },
  { label: "Talla Sentado (cm)", key: "talla_sentado" },
  { label: "Biacromial", key: "biacromial" },
  { label: "Tórax Transverso", key: "diam_torax_transverso" },
  { label: "Tórax Antero-posterior", key: "diam_torax_ap" },
  { label: "Bi-iliocrestídeo", key: "bi_iliocrestideo" },
  { label: "Humeral (biepicondilar)", key: "humero" },
  { label: "Femoral (biepicondilar)", key: "femur" },
  { label: "Cabeza", key: "perim_cabeza" },
  { label: "Brazo Relajado", key: "perim_brazo_relajado" },
  { label: "Brazo Flexionado en Tensión", key: "perim_brazo_contraido" },
  { label: "Antebrazo Máximo", key: "perim_antebrazo" },
  { label: "Tórax Mesoesternal", key: "perim_torax" },
  { label: "Cintura (mínima)", key: "cintura" },
  { label: "Cadera (máximo)", key: "caderas" },
  { label: "Muslo (máximo)", key: "muslo_gluteo" },
  { label: "Muslo (medial)", key: "muslo_medio" },
  { label: "Pantorrilla (máxima)", key: "pierna_perim" },
  { label: "Tríceps", key: "pliegue_triceps" },
  { label: "Subescapular", key: "pliegue_subescapular" },
  { label: "Supraespinal", key: "pliegue_supra" },
  { label: "Abdominal", key: "pliegue_abdomen" },
  { label: "Muslo Medial", key: "pliegue_muslo" },
  { label: "Pantorrilla (máxima)", key: "pliegue_pierna" },
  { label: "Bicipital", key: "pliegue_bicipital" },
  { label: "Supracrestídeo", key: "pliegue_supracrestideo" },
];
