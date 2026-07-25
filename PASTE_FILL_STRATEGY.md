# Strategy — move "Pegar desde Excel" (paste-to-fill) into the exam-template config

**Goal.** Turn the currently hardcoded, pentacompartimental-only paste-to-fill
feature into a **config-driven** capability defined on the exam template itself,
so any exam can opt in **without a code change or deploy** — just by adding a
paste map to its `input_config`.

**Hard scope constraint — single-player view ONLY.** Paste-to-fill fills the
form for *one player at a time*. It must never appear in the per-team entry
modes (team-table, bulk-ingest). This is naturally guaranteed because the tool
lives in `DynamicUploader` (the single-entry form); team-table uses
`TeamTableForm` and bulk-ingest uses `BulkIngestForm`, which are separate
components. Keep it that way — do **not** hoist the paste logic to a shared
place that the team/bulk forms could pick up. (`DynamicUploader` is used only in
single-player surfaces: registrar single mode, profile `DepartmentCard`,
`ResultsHistoryPanel`, `InjuryPanel`, and `subir-datos` — all one-player.)

---

## 1. Current state (as shipped — hardcoded, penta-only)

| Piece | File | Role |
|---|---|---|
| Row map | `frontend/src/components/forms/pentaPasteMap.ts` | `PENTA_PASTE_ROWS` const: ordered `{label, key}` of the report's 27 rows |
| Modal | `frontend/src/components/forms/PentaPasteModal.tsx` (+ `.module.css`) | Parse pasted TSV → fixed-order map → label sanity-check → preview → apply |
| Wiring | `frontend/src/components/forms/DynamicUploader.tsx` | Button gated by `template.slug === "pentacompartimental"`; `onApply` merges values into form state |

How it works today: user copies cells from Excel (clipboard is tab-separated),
pastes into a textarea; values are mapped to fields **by the report's fixed row
order** (labels repeat — e.g. "Pantorrilla (máxima)" is both a perímetro and a
pliegue — so position, not label, is authoritative); the pasted label column is
used only to flag misalignment; numbers parse as es-CL (comma decimal); a
preview table is shown; on confirm the raw fields fill and the user saves
normally (server recomputes the calculated masses).

**Limitation:** the map + the enable-gate are in code. Changing the mapping or
enabling another exam needs a code edit + deploy, and it's invisible in the
template config/admin.

---

## 2. Target architecture (config-driven)

Add an optional `paste_fill` block to the template's **`input_config`** (already
a free-form JSONB dict on `ExamTemplate`, already serialized to the frontend as
`template.input_config` — **no backend schema/endpoint change required**). The
single-entry form shows the paste tool **iff** `input_config.paste_fill` is
present; the map comes from there instead of a code const.

### 2.1 Config schema (`input_config.paste_fill`)

```jsonc
{
  "paste_fill": {
    "enabled": true,                 // optional; treat presence of `rows` as enabled
    "decimal_sep": ",",              // optional; "," (es-CL, default) or "."
    "rows": [                        // REQUIRED, ordered = the report's row order
      { "label": "Peso Bruto (Kg)", "key": "peso" },
      { "label": "Talla Corporal (cm)", "key": "talla" },
      // … one entry per source row, in the exact order they appear in the sheet
      { "label": "Supracrestídeo", "key": "pliegue_supracrestideo" }
    ]
  }
}
```

- `key` must reference a **raw** (non-calculated) field of this template. Rows
  whose `key` doesn't match a field are ignored (and surfaced during authoring —
  see §6 validation).
- `label` is the sheet's column-1 text, used only for the alignment sanity-check
  in the preview; it does not have to be unique (duplicates are expected).
- `decimal_sep` lets non-es-CL templates opt into dot-decimal parsing.

### 2.2 Backend

- **No schema change.** `input_config` is `dict[str, Any]` (see
  `backend/api/schemas.py`), so `paste_fill` rides through to the client as-is.
- **Seeding:** add the `paste_fill` block to the relevant `seed_*` command so
  re-seeds keep it. For pentacompartimental, put the 27 rows in
  `seed_pentacompartimental.py`'s `INPUT_CONFIG`. (The demo club's penta template
  shares the same seed, so both clubs get it — fine.)
- **Optional validation** (nice-to-have, not required): a light check in the
  template-config save path / a management command that warns when a
  `paste_fill.rows[].key` isn't a raw field on the template.

### 2.3 Frontend

1. **Type:** add `paste_fill?: PasteFillConfig` to `ExamInputConfig` in
   `frontend/src/lib/types.ts`:
   ```ts
   export interface PasteFillRow { label: string; key: string; }
   export interface PasteFillConfig {
     enabled?: boolean;
     decimal_sep?: "," | ".";
     rows: PasteFillRow[];
   }
   ```
2. **Generalize the modal:** rename `PentaPasteModal` → `PasteFillModal`
   (`frontend/src/components/forms/PasteFillModal.tsx`). It takes the ordered
   `rows` and `decimal_sep` as **props** (from `template.input_config.paste_fill`)
   instead of importing the const. All parse/preview logic is unchanged; only the
   source of `rows` and the decimal separator become parameters.
3. **Gate by config, not slug**, in `DynamicUploader.tsx`:
   ```tsx
   const pasteFill = template.input_config?.paste_fill;
   const canPaste = !!pasteFill?.rows?.length && pasteFill.enabled !== false;
   // …render the button + <PasteFillModal rows={pasteFill.rows} ... /> when canPaste
   ```
   Because this is inside `DynamicUploader`, it is automatically single-player
   only. No extra guard needed, but do NOT move `canPaste` upstream into a shared
   parent that the team/bulk forms render from.
4. **Delete** `pentaPasteMap.ts` and the `slug === "pentacompartimental"` gate
   once the config carries the map.

---

## 3. Migration of the existing penta feature

1. Add `paste_fill.rows` (the 27 rows, current `PENTA_PASTE_ROWS` order/keys) to
   the **U. de Chile** and **Selección Chilena** pentacompartimental templates'
   `input_config` — same one-off ORM edit pattern used for the field cleanup
   (local first, verify, then prod with the `POSTGRES_*` override + host-assert
   guard). Alternatively re-run `seed_pentacompartimental` after updating its
   `INPUT_CONFIG` (but confirm the seed doesn't clobber other per-club config).
2. Add the same block to `seed_pentacompartimental.py` `INPUT_CONFIG` so it
   survives re-seeds (⚠ recall the field cleanup — the seed is club-agnostic, so
   whatever is in `INPUT_CONFIG` applies to every club's penta template).
3. Frontend refactor (§2.3): rename modal, prop-drive `rows`, gate on config,
   delete the const + slug gate.
4. `tsc --noEmit`, retest with the same paste sample, deploy.

---

## 4. Parsing / UX carried over verbatim (do not regress)

- **Fixed-order mapping** against `rows` (position i → `rows[i].key`).
- **Label sanity-check:** normalize (NFD, strip `[̀-ͯ]`, lowercase,
  drop non-alphanumerics) pasted label vs `rows[i].label`; ⚠ mismatches in the
  preview (catches misaligned/partial selections). Duplicate labels are fine —
  position disambiguates.
- **es-CL numbers:** `decimal_sep === ","` → strip `.` thousands, `,`→`.`;
  `"83,200" → 83.2`, `"9,000" → 9`. Make this honor `decimal_sep`.
- **One or both columns:** both = label+value (validated); values-only = mapped
  by order (preview marks rows "(por orden)").
- **Review before apply:** preview table + explicit "Rellenar N campos"; never
  auto-submit. Fill merges into form state; user still reviews + `Guardar`; the
  server recomputes calculated fields.
- Fields not in `rows` (e.g. `sexo`, date) are untouched — set as usual.

---

## 5. Edge cases & guards

- Blank value cell (both-columns): label present, value `null` → row shows "sin
  valor", stays aligned. Good — another reason to prefer both columns.
- Extra pasted rows beyond `rows.length`: ignored (flag in summary).
- Fewer pasted rows: only those fill.
- `key` not a field on the template: ignore that row (and warn at authoring).
- Never trust position blindly for values-only + interior blank lines — the
  preview is the safety net; document "pegá ambas columnas para validar".

---

## 6. Authoring a paste map for a NEW template

1. In Django admin (or the template-config UI), edit the template's
   `input_config` JSON and add a `paste_fill` block with `rows` in the source
   sheet's order, each `key` a raw field of the template.
2. (Optional helper) a `manage.py bootstrap_paste_fill --template-slug X`
   command that emits a starter `rows` list from the template's raw fields in
   `config_schema` order (labels = field labels), which the author then reorders
   / relabels to match the real sheet. Speeds up onboarding, avoids typos.
3. No deploy needed — it's config. The button appears on the single-entry form
   as soon as the config is saved.

---

## 7. Implementation checklist (ordered)

- [ ] FE: add `PasteFillConfig` / `PasteFillRow` to `ExamInputConfig` (`types.ts`).
- [ ] FE: `PentaPasteModal` → `PasteFillModal`, take `rows` + `decimal_sep` props; honor `decimal_sep` in `parseNum`.
- [ ] FE: `DynamicUploader` — gate button+modal on `input_config.paste_fill` (remove slug gate); pass `rows`.
- [ ] FE: delete `pentaPasteMap.ts`.
- [ ] BE: add `paste_fill` to `seed_pentacompartimental.py` `INPUT_CONFIG`.
- [ ] DATA: write `paste_fill` into both penta templates' `input_config` (local → verify → prod, guarded).
- [ ] (opt) BE: `bootstrap_paste_fill` command + authoring validation.
- [ ] Verify: `tsc` clean; parser unit test on the sample; manual paste on a player; prod smoke.

## 8. Rollout & backout

- Ship FE + config together. Backout = remove `paste_fill` from the template
  `input_config` (button vanishes; no data affected) and/or revert the FE commit.
- Zero data risk: paste-to-fill only pre-fills the form client-side; nothing is
  written until the user saves through the normal path.

## 9. Future enhancements (out of scope now)

- **Default map from schema order:** if a template sets `paste_fill: { auto: true }`
  with no `rows`, derive the order from raw fields in `config_schema` order —
  zero-config for simple templates.
- **Label-match mode:** for templates with unique labels, allow matching by
  label (+ per-field aliases) instead of fixed order.
- **Reuse `column_mapping`:** bulk-ingest already has a column→field map; a
  future refactor could share one mapping source between bulk-ingest and
  single-player paste (keeping the single-player UX separate).
