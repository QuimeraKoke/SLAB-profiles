# Dashboards Guide

How to configure player profile dashboards in SLAB — and how to add new
visualization types when the built-in ones aren't enough.

> **Read first:** [`PROJECT.md`](./PROJECT.md) for the platform's
> "configuration over code" philosophy and [`STATUS.md`](./STATUS.md) §3.8 for
> the runtime architecture. This guide is the *operator's manual*.

---

## 1. Vocabulary

- **Department layout** — the dashboard configured for one
  `(department, category)` pair. Two categories share *no* layout state, so
  U-21 can evolve independently from First Team.
- **Section** — a visual group inside a layout, with an optional title and
  a collapse toggle.
- **Widget** — one chart, table, or card on the page.
- **Data source** — what feeds a widget: which exam template, which fields
  inside that template, and how to aggregate the results.

```
DepartmentLayout (department, category)
  └── LayoutSection (title, collapsible)
        └── Widget (chart_type, title, column_span)
              └── WidgetDataSource (template, field_keys, aggregation)
```

---

## 2. Quick walkthrough — build a Nutricional dashboard from scratch

Goal: reproduce the seeded layout one widget at a time, so you understand
every knob before you go off-script.

### 2.1 Create the layout

1. Open Django Admin → **Dashboards → Department layouts → Add**.
2. Pick `Department: Nutricional` and `Category: First Team`.
3. Leave **Name** as "Default" (it's just an internal label).
4. Tick **Is active** (otherwise the frontend falls back to the legacy grid).
5. Click **Save and continue editing**.

### 2.2 Add sections

The "Layout sections" inline appears at the bottom of the layout page. Add three rows:

| Sort order | Title                                 | Is collapsible | Default collapsed |
| ---------- | ------------------------------------- | -------------- | ----------------- |
| 0          | *(blank)*                             | ☐              | ☐                 |
| 1          | Fraccionamiento 5 masas               | ☑              | ☐                 |
| 2          | Análisis M. adiposa y M. muscular     | ☑              | ☐                 |

A blank-title section renders without a header — perfect for the "intro row"
of side-by-side widgets at the top of the page.

Click **Save**.

### 2.3 Add widgets to section 0

Click the **Edit widgets →** link on the row for section 0. Add two widgets:

**Widget A — Comparison table**
- Chart type: `Comparison table (last N takes)`
- Title: `Evolución antropométrica — últimas 3 tomas`
- Column span: `6`
- Sort order: `0`
- Click **Save and continue editing**.

**Widget B — Line chart**
- Chart type: `Line chart with field selector`
- Title: `Evolución en el tiempo`
- Column span: `6`
- Sort order: `1`
- Save.

`column_span: 6` puts both widgets on a 12-column row, side by side.

### 2.4 Wire data sources

Click **Edit data sources →** on Widget A:

- Template: `Pentacompartimental`
- Field keys: `peso`, `talla`, `masa_adiposa`, `masa_muscular`, `masa_osea`, `masa_piel`, `masa_residual`
  - Each key on its own line in the array field. Match the `key` from
    `config_schema.fields[].key` exactly — typos surface as form errors with
    the list of valid keys for that template.
- Aggregation: `Last N results`
- Aggregation param: `3`
- Save.

Repeat for Widget B with the same template and field keys, but
`Aggregation: All results` (the user will pick which field to plot from a
dropdown at runtime).

### 2.5 Verify

Open any First Team player → **Nutricional** tab. You should see the
table + line chart side by side. If you don't, jump to §6 Troubleshooting.

To finish reproducing the mockup, add the donut widget to section 1 and
the grouped-bar widget to section 2. Or just run
`seed_nutricional_layout --all-applicable-categories` to rebuild the
whole thing.

---

## 3. Reference — built-in chart types

| `chart_type`         | Best for                                          | Required data shape                                              |
| -------------------- | ------------------------------------------------- | ---------------------------------------------------------------- |
| `comparison_table`   | Last N takes side-by-side, with deltas            | 1 source · `last_n` · multiple `field_keys` (one row per field)  |
| `line_with_selector` | Trend over time, one variable at a time (dropdown)| 1 source · `all` · multiple `field_keys`                         |
| `multi_line`         | Trend over time, all series visible at once       | 1 source · `all` (or `last_n`) · multiple `field_keys`           |
| `donut_per_result`   | Body-composition fractions, one donut per take    | 1 source · `last_n` · `field_keys` that sum to a meaningful whole |
| `grouped_bar`        | Compare a few values across recent takes          | 1 source · `last_n` · 2–5 `field_keys`                           |

### Reserved (configure now, render later)

| `chart_type`        | What V2 will render                                                       |
| ------------------- | ------------------------------------------------------------------------- |
| `reference_card`    | Latest result vs a target reference (e.g. Kerr 1988 / Phantom).           |
| `goals_list`        | Goals from a Metas template, with checkboxes.                             |
| `cross_exam_line`   | One line chart pulling from multiple exam templates (e.g. weight + sprint + injury subjective pain). |

Configure them today and the frontend renders an "Unsupported renderer"
placeholder. The data wiring stays valid, so when V2 ships these light up
without admin re-work.

---

## 4. Reference — aggregation modes

| Aggregation | Returns                                  | `aggregation_param` | Pick when                                          |
| ----------- | ---------------------------------------- | ------------------- | -------------------------------------------------- |
| `latest`    | Just the most recent result              | *(ignored)*         | Single-snapshot widgets, current-state cards       |
| `last_n`    | Last N results, oldest → newest          | N (default 3)       | Comparison tables, recent-history donuts/bars      |
| `all`       | Every result, time-ordered               | *(ignored)*         | Trend lines spanning months / years                |

The frontend never re-aggregates — what comes back from `/api/players/{id}/views`
is already shaped for the chart. So picking `all` on a 200-result dataset for
a sparkline is fine; the cost is server-side and bounded.

---

## 5. Reference — `display_config`

Per-widget JSON for chart-specific knobs. Leave empty (`{}`) when defaults
are good.

### Color palette (donut, grouped bar, multi line)
```json
{ "colors": ["#3b82f6", "#f97316", "#10b981", "#f59e0b", "#a855f7"] }
```
Colors apply in `field_keys` order. Missing entries fall back to the default
palette.

### Axis titles (line with selector, grouped bar, multi line)
```json
{ "x_axis_title": "Tiempo", "y_axis_title": "Composición corporal" }
```
Both keys are optional. Defaults:
- **X-axis:** `"Fecha"`.
- **Y-axis:**
  - `line_with_selector` → the active field's label + unit, e.g. `"Peso (kg)"`.
    Updates automatically when the user picks a different field from the dropdown.
  - `multi_line`, `grouped_bar` → the shared unit when every plotted field uses
    the same one (e.g. `"kg"`); blank when units are mixed.

### Title-only widgets
For tables and line charts there are no knobs in V1. Future chart types
should document their `display_config` shape in this guide.

---

## 6. Layout & sizing

- **Column span** — each widget takes `column_span` columns out of 12.
  - `12` = full width, `6` = half, `4` = third, `3` = quarter.
- Widgets flow left-to-right within a section and wrap when the row is full.
- Below 768px every widget collapses to full width regardless of `column_span`.
- Sections always stack vertically — there's no "two columns of sections"
  layout.

### Section behavior
- **Title blank** → no header rendered (use this for the intro row).
- **Is collapsible** → user gets a chevron toggle. Leave off for sections
  that should always be visible.
- **Default collapsed** → start closed when the page loads. The toggle state
  resets per page load (no per-user persistence yet).

---

## 7. Permissions & scoping

- A user only sees a layout if their `StaffMembership.departments` includes
  the layout's department (or `all_departments=True`).
- A widget whose data sources all reference templates the user can't access
  is silently dropped from the rendered page — they don't see broken cards.
- Cross-department widgets (only `cross_exam_line` is allowed to mix) lose
  individual sources the user can't access but keep the rest.
- The platform admin (no `StaffMembership`) sees everything.

---

## 8. Troubleshooting

### `Unknown field key(s) for template 'X'`
You typed a field key that doesn't exist in the chosen template's
`config_schema`. The error message lists every valid key. Most often: a typo,
or you switched the template after typing the keys.

### Dashboard doesn't appear; the legacy template grid shows
Check, in order:
1. The layout's **Is active** checkbox is ticked.
2. The layout's `(department, category)` matches the **player's** category
   (not just any First Team player).
3. The user has access to the layout's department via their
   `StaffMembership`.

### Widget renders empty (or "Sin datos registrados")
1. The player has no `ExamResult` rows for the source template. Add one via
   the "+ Template" button at the bottom of the profile page, or generate
   fake data with `seed_fake_exams --reset`.
2. The chosen `field_keys` are valid in the schema but `result_data` doesn't
   have values for them. Common after a schema change.

### `Department and category must belong to the same club`
You picked a department and category from different clubs. Both must come
from the same `Club`.

### `Category 'X' has not opted in to department 'Y'`
On the Category admin page (Core → Categories → X), add the department to
its `Departments` list, save, then come back to the layout form.

### Widget configured but renders "Unsupported renderer"
You picked one of the reserved `chart_type`s
(`reference_card`, `goals_list`, `cross_exam_line`). The data wiring is fine
— the frontend renderer just isn't built yet. Pick a built-in chart type
or wait for V2.

---

## 9. Re-running the seeder

The bundled seed command is idempotent. Re-running rebuilds the targeted
`(department, category)` layouts from scratch:

```bash
docker compose exec backend python manage.py seed_nutricional_layout \
    --all-applicable-categories
```

Useful flags:
- `--category-name "First Team"` — seed one category instead of all.
- `--skip-existing` — leave already-configured pairs untouched.
- `--club "Universidad de Chile"` — required when more than one club exists.
- `--template-name "..."` — point at a renamed Pentacompartimental template.

---

## 10. Adding a brand new visualization (developer)

Adding a chart type is a four-file change. The `grouped_bar` widget is a
good template to clone.

### 10.1 Pick a key and register it

`backend/dashboards/models.py` — add to the `ChartType` enum:

```python
class ChartType(models.TextChoices):
    ...
    SCATTER_PLOT = "scatter_plot", "Scatter plot"
```

The first arg is the database/API value; the second is the admin-facing label.

### 10.2 Write the server-side resolver

`backend/dashboards/aggregation.py`:

```python
def _resolve_scatter_plot(widget, sources, player_id):
    if not sources:
        return _empty(widget, ChartType.SCATTER_PLOT.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

    # Expect exactly two field_keys: x-axis and y-axis.
    if len(source.field_keys) < 2:
        return _empty(widget, ChartType.SCATTER_PLOT.value)
    x_key, y_key = source.field_keys[0], source.field_keys[1]

    points = [
        {
            "x": _safe_float(_read(r, x_key)),
            "y": _safe_float(_read(r, y_key)),
            "recorded_at": r.recorded_at.isoformat(),
        }
        for r in results
    ]
    return {
        "chart_type": ChartType.SCATTER_PLOT.value,
        "x_axis": _field_meta(template, x_key),
        "y_axis": _field_meta(template, y_key),
        "points": points,
    }


_RESOLVERS = {
    ...,
    ChartType.SCATTER_PLOT.value: _resolve_scatter_plot,
}
```

If your chart needs a chart-specific empty shape, extend `_empty()` to
include it (so the frontend can read `data.points.length` safely).

### 10.3 Add a TypeScript type

`frontend/src/lib/types.ts` — append to `WidgetData`:

```typescript
export interface ScatterPlotPayload {
  chart_type: "scatter_plot";
  x_axis: FieldMeta;
  y_axis: FieldMeta;
  points: { x: number | null; y: number | null; recorded_at: string }[];
}

export type WidgetData =
  | ComparisonTablePayload
  | ...
  | ScatterPlotPayload;
```

### 10.4 Build the React component

`frontend/src/components/dashboards/widgets/ScatterPlot.tsx`:

```tsx
"use client";

import React from "react";
import { ScatterChart, Scatter, XAxis, YAxis, ResponsiveContainer } from "recharts";

import type { DashboardWidget, ScatterPlotPayload } from "@/lib/types";
import styles from "./Widget.module.css";

export default function ScatterPlot({ widget }: { widget: DashboardWidget }) {
  const data = widget.data as ScatterPlotPayload;
  // … render Recharts scatter chart …
}
```

Reuse `Widget.module.css` for the card frame so it matches the others.

### 10.5 Register the renderer

`frontend/src/components/dashboards/widgets/index.tsx`:

```tsx
import ScatterPlot from "./ScatterPlot";

const widgetRegistry = {
  ...,
  scatter_plot: ScatterPlot,
};
```

### 10.6 Document it

Add a row to §3 above so the next admin knows what to expect.

### 10.7 Migrations
The `chart_type` column is just a `CharField(choices=…)` — adding values
**does not require a migration**. New choices show up in admin immediately
after a backend reload.

---

## 11. File map

| Concern                        | Location                                                              |
| ------------------------------ | --------------------------------------------------------------------- |
| Models                         | `backend/dashboards/models.py`                                        |
| Admin                          | `backend/dashboards/admin.py`                                         |
| Server-side resolvers          | `backend/dashboards/aggregation.py`                                   |
| API endpoint                   | `backend/api/routers.py` → `get_player_view`                          |
| API response schemas           | `backend/api/schemas.py` (`LayoutResponseOut`, `WidgetPayloadOut`, …) |
| Seed command                   | `backend/dashboards/management/commands/seed_nutricional_layout.py`   |
| Frontend dashboard renderer    | `frontend/src/components/dashboards/DepartmentDashboard.tsx`          |
| Frontend section group         | `frontend/src/components/dashboards/SectionGroup.tsx`                 |
| Frontend widget registry       | `frontend/src/components/dashboards/widgets/index.tsx`                |
| Individual widget components   | `frontend/src/components/dashboards/widgets/*.tsx`                    |
| TypeScript payload types       | `frontend/src/lib/types.ts`                                           |
