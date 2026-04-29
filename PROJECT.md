# Product Vision & Requirements Document: SLAB Platform 2.0

**Product Name:** SLAB
**Document Owner:** Platform Owner / Lead Engineer
**Product Philosophy:** "Maximum flexibility, zero ongoing development." The platform must operate as a self-serve configuration engine to eliminate development bottlenecks and respect the limited time of the platform owner. 

---

### I. Product Vision & Strategy

SLAB is pivoting from a hardcoded athlete management application into a dynamic, headless Content Management System (CMS) tailored specifically for data-driven soccer team management. 

The core problem with the legacy platform is configuration friction. Every time the medical, tactical, or physical departments need to track a new metric or change a visualization, it requires developer intervention. SLAB 2.0 solves this by putting the power of data modeling and visualization mapping directly into an administrative control panel. The goal is to create a product so simple and adaptable that deploying a new sports-science metric takes three minutes of configuration instead of three days of coding.

---

### II. Target User Personas

1. **The Platform Administrator (System Owner):**
   * **Goal:** Configure the platform quickly without writing code. 
   * **Needs:** A powerful backend UI to define "Exam Templates," write proprietary sports-science math formulas, and link data to specific chart types.
2. **Department Staff (Medical, Physical, Nutritional, Psychosocial):**
   * **Goal:** Input player data as smoothly as possible.
   * **Needs:** Clean, auto-generated upload forms that only show the fields relevant to their specific department and the specific category of the player they are evaluating.
3. **Coaching & Management Staff:**
   * **Goal:** Understand player readiness and performance at a glance.
   * **Needs:** Intuitive visual dashboards (radars, line charts, body maps) that adapt to the data being viewed, alongside automated alerts when a player exceeds a safety threshold.

---

### III. Core Epics & Feature Requirements

#### Epic 1: The Dynamic Configuration Engine
*As an Admin, I need to create and modify exam templates without touching the codebase so that the platform can scale alongside the club's evolving needs.*
* **Feature 1.1: Template Builder:** Ability to create an "Exam" and assign specific data fields (Numbers, Text, Temporal Arrays like 'Distance at 30 min').
* **Feature 1.2: Formula Engine:** Ability to define custom mathematical expressions (e.g., Workload Ratios) that calculate automatically upon data entry.
* **Feature 1.3: Visual Mapping:** Ability to assign a specific field to a UI component (e.g., mapping an "Injury Array" strictly to a "Body Map" visualization).

#### Epic 2: Category & Roster Inheritance
*As a Staff Member, I need to see data requirements tailored to my roster so that I don't waste time filling out First Team metrics for U-8 players.*
* **Feature 2.1: Hierarchical Roster Management:** Organize players by Club -> Category (U-8, U-21, First Team, Women's Team).
* **Feature 2.2: Contextual Views:** Templates must be assignable by category. A U-8 coach should see a simplified version of the First Team physical exam, with advanced metrics automatically hidden.

#### Epic 3: Automated Intelligence & Alarms
*As a Coach, I need the system to warn me if a player is at risk so that I can adjust training loads proactively.*
* **Feature 3.1: Threshold Definitions:** Admins can set global or category-specific limits on specific metrics (e.g., Max Velocity drops below a certain baseline).
* **Feature 3.2: Automated Alerts:** The system must evaluate incoming data against these limits in the background and flag the player's profile with an active, time-bound alarm.

#### Epic 4: The Dynamic Player Profile
*As an End-User, I need a comprehensive, visual player profile so that I can consume complex data easily.*
* **Feature 4.1: Adaptive Dashboards:** The frontend must generate views based strictly on what the Admin configured. If a new nutritional metric is added on the backend, the player profile must automatically render the corresponding chart without a frontend update.
* **Feature 4.2: Historical Tracking:** Clear visual differentiation between isolated exam results and longitudinal (time-series) data.

---

### IV. MVP Boundaries (Phase 1 Scope)

To ensure rapid delivery and validate the architecture, the MVP will be strictly constrained:
* **In Scope:** * Core relational database setup (Clubs, Categories, Players).
  * Backend Admin UI for defining Templates and Custom Math.
  * API for auto-generating upload forms.
  * Next.js Profile View with 3 core visualizers: Line Chart (Temporal data), Stat Card (Calculated formulas), and Body Map (Medical data).
  * One complete vertical slice: Deploying a single department's workflow (e.g., Physical Performance) from configuration to visualization.
* **Out of Scope for MVP:**
  * Bulk CSV/GPS data uploads (manual entry only for Phase 1).
  * Complex cross-player comparative analytics (focusing purely on the individual player profile first).
  * Third-party integrations (e.g., pulling data directly from Catapult or Wimu APIs).

---

### V. Key Success Metrics (KPIs)
1. **Time-to-Deploy:** The time it takes the Administrator to add a completely new metric and have it visible on the frontend (Target: < 5 minutes).
2. **Zero-Code Updates:** Number of code deployments required to support new team methodologies (Target: 0).
3. **System Performance:** Background alarm processing and complex formula calculation must not block or delay the staff's data upload experience.

## The Codebase 

### I. Core Technology Stack
The stack is selected strictly to minimize configuration time while maximizing data flexibility and API performance.

* **Database:** PostgreSQL (Hybrid Relational + JSONB architecture).
* **Backend & Configuration:** Django.
* **API Layer & Validation:** Django Ninja (Pydantic-based REST API).
* **Frontend & Visualization:** Next.js (App Router) with React component registry.
* **Background Processing:** Celery + Redis (for asynchronous alarm/rule evaluation).

---

### II. System Architecture & Workflows

#### 1. The Data Schema Strategy
The database uses a hybrid approach to balance structural integrity with dynamic flexibility.
* **Strict Relational (Core Entities):** Clubs, Categories (e.g., First Team, U-21, U-8), Players, and Staff exist as standard relational tables.
* **Flexible Schema (The Engine):** `ExamTemplates` and `ExamResults` utilize PostgreSQL `JSONB` fields. The template acts as the schema definition, dictating what fields exist, their data types (primitive, temporal array, categorical), and how the Next.js frontend should render them.

#### 2. The Configuration Engine (Admin UI)
To eliminate the need for building a custom settings portal, the native **Django Admin** acts as the control center. Administrators use this to:
* Create new `ExamTemplates`.
* Assign templates to specific categories (enabling view inheritance, where U-8 sees a simplified version of the First Team's template).
* Define specific keys, labels, and mathematical formulas for calculated fields.

#### 3. The Calculation & Rules Engine
Metrics do not need to be calculated manually by the staff or processed entirely on the frontend.
* **Secure Evaluation:** When a payload is submitted to the API, the backend identifies any "calculated" fields in the template schema. It uses a secure Abstract Syntax Tree (AST) parser to safely evaluate custom administrator-defined strings (e.g., `([dist_30] * 1.5) / [hr_avg]`) by swapping in the raw uploaded variables.
* **Asynchronous Alarms:** Once data is saved, a background job immediately evaluates the new results against active threshold rules tied to the player or category, dispatching alerts if limits are breached.

#### 4. The Frontend Visualization Registry
Next.js acts as an intelligent "dumb client." It does not hardcode forms or charts for specific exams.
* **Dynamic Forms:** It reads the `ExamTemplate` JSON from the backend and auto-generates the input fields for the staff.
* **Component Mapping:** It utilizes a Component Registry pattern. When the backend sends a payload with `chart_type: "radar"`, the frontend maps that string to a pre-built React component and injects the data. Adding a new visualization type requires only adding one new component to the registry.

---

### III. Limitations & Engineering Considerations

Building a metadata-driven system introduces specific complexities that must be managed carefully.

#### 1. Security: Custom Formula Execution
* **Risk:** Allowing an administrator to input mathematical formulas that the server executes is a massive security vulnerability if handled via native `eval()`.
* **Mitigation:** You *must* strictly enforce the use of an AST parser or a sandboxed math library (like `py_expression_eval`). The parser must only allow basic mathematical operators and pre-defined variables, rejecting any system-level calls or complex Python logic.

#### 2. Database Querying & Indexing
* **Risk:** While JSONB is powerful, searching deeply nested JSON structures across thousands of player results can become a performance bottleneck over time.
* **Mitigation:** Rely heavily on PostgreSQL's `GIN` (Generalized Inverted Index) indexing for the `result_data` JSONB columns. Furthermore, if a specific calculated metric (e.g., "Max Velocity") becomes highly queried for team-wide dashboards, it may need to be temporarily extracted into an indexed materialized view or a standard relational column.

#### 3. Frontend Bundle Size & Rendering
* **Risk:** Loading a massive library of visualization components (charts, 3D body maps, tables) on every page load will severely impact the Next.js frontend performance.
* **Mitigation:** Utilize React's `lazy()` loading or Next.js Dynamic Imports within the Component Registry. Only fetch and load the specific chart component code over the network when the JSON payload explicitly requests it.

#### 4. Template Immutability vs. Historical Data
* **Risk:** If an administrator alters an existing `ExamTemplate` (e.g., changing a math formula or removing a field), it can break the frontend rendering of historical `ExamResults` that were saved under the old schema.
* **Mitigation:** Implement a strict versioning system for templates. Once a template has associated results, it should become immutable. Modifications should spawn a new version (e.g., `Template_v2`) to preserve the integrity of past data.

#### 5. Background Task Overhead
* **Risk:** Triggering complex alarm evaluations for an entire squad's GPS data simultaneously could overwhelm the web server.
* **Mitigation:** The Celery/Redis worker queue must be completely decoupled from the main Django application resources, ensuring that large data uploads return a quick `200 OK` to the frontend while the heavy calculation happens asynchronously.


# Architecture Components

### 1. Database Schema (PostgreSQL)

This schema uses a hybrid approach. It maintains strict relational integrity for the organizational hierarchy but leverages the flexibility of `JSONB` for the dynamic exam configurations and results.

**Table: `core_club`**
* `id` (UUID, Primary Key)
* `name` (String)

**Table: `core_category`**
* `id` (UUID, Primary Key)
* `club_id` (Foreign Key -> `core_club`)
* `name` (String) — *e.g., "First Team", "U-21", "U-8"*

**Table: `core_player`**
* `id` (UUID, Primary Key)
* `category_id` (Foreign Key -> `core_category`)
* `first_name` (String)
* `last_name` (String)
* `date_of_birth` (Date)
* `is_active` (Boolean)

**Table: `exams_examtemplate`**
* `id` (UUID, Primary Key)
* `name` (String) — *e.g., "Weekly Wellness", "Match Physical Performance"*
* `department` (String) — *e.g., "Medical", "Technical", "Psychosocial"*
* `applicable_categories` (ManyToMany -> `core_category`)
* `config_schema` (JSONB) — *Defines the fields, data types, and UI components.*

> **Example `config_schema` Payload:**
> ```json
> {
>   "fields": [
>     { "key": "dist_30", "label": "Distance 30m", "type": "number", "unit": "m", "chart_type": "line" },
>     { "key": "hr_avg", "label": "Average HR", "type": "number", "unit": "bpm", "chart_type": "line" },
>     { "key": "injury_zone", "label": "Injury Map", "type": "categorical", "chart_type": "body_map" },
>     { "key": "workload_ratio", "label": "Workload Ratio", "type": "calculated", "formula": "([dist_30] * 1.5) / [hr_avg]", "chart_type": "stat_card" }
>   ]
> }
> ```

**Table: `exams_examresult`**
* `id` (UUID, Primary Key)
* `player_id` (Foreign Key -> `core_player`)
* `template_id` (Foreign Key -> `exams_examtemplate`)
* `recorded_at` (DateTime)
* `result_data` (JSONB) — *Stores both the raw inputs and calculated outputs.*

---

### 2. Backend Architecture (Django + Django Ninja)

The backend is responsible for enforcing data validation via Pydantic, executing the custom math formulas securely, and serving the Next.js frontend.

#### Directory Structure
```text
slab_backend/
├── core/                 # App: Models for Club, Category, Player
├── exams/                # App: Models for Templates, Results, and Math Logic
├── api/                  # App: Django Ninja Routers and Pydantic Schemas
│   ├── schemas.py        # Pydantic models for request/response validation
│   └── routers.py        # Endpoint definitions
└── config/               # Main Django settings
```

#### The Evaluation Engine (Python AST)
When the AI tool generates the `ExamResult` creation logic, instruct it to include an AST parser.
* **Logic Flow:** When a `POST` request hits `/api/exams/upload`, the backend must iterate through the `config_schema` of the linked template. If it finds a `type: "calculated"`, it must extract the `formula`, replace the bracketed variables (e.g., `[dist_30]`) with the values provided in the payload, and evaluate it using Python's `ast.literal_eval` or a specialized safe-math library like `py_expression_eval` before saving the final JSONB object to the database.

#### API Endpoints (Django Ninja)
* **`GET /api/players/{player_id}`**: Returns player details and a list of their available `ExamTemplate` IDs based on their category.
* **`GET /api/templates/{template_id}`**: Returns the `config_schema` so the Next.js frontend knows how to build the dynamic upload form and render the views.
* **`POST /api/results/`**: Accepts the raw data from the staff, triggers the calculation engine, saves the `ExamResult`, and returns the processed data.
* **`GET /api/players/{player_id}/results?department={dept}`**: Fetches the historical `ExamResult` JSONB payloads for a specific player, filtered by department (e.g., to load the Medical dashboard).

---

### 3. Frontend Architecture (Next.js App Router)

The frontend acts as a "dumb client" that intelligently renders whatever the backend configuration dictates.

#### Directory Structure
```text
slab_frontend/
├── src/
│   ├── app/
│   │   ├── (dashboard)/
│   │   │   ├── players/[id]/page.tsx      # Main Player Profile View
│   │   │   └── templates/page.tsx         # Template viewer (optional, if not using Django Admin)
│   ├── components/
│   │   ├── forms/
│   │   │   └── DynamicUploader.tsx        # Auto-generates inputs based on template config
│   │   ├── visualizations/
│   │   │   ├── LineChart.tsx
│   │   │   ├── BodyMap.tsx
│   │   │   ├── StatCard.tsx
│   │   │   └── Registry.tsx               # Maps string 'chart_type' to actual React components
│   ├── lib/
│   │   └── api.ts                         # Axios/Fetch wrappers to Django Ninja
```

#### The Component Registry (`Registry.tsx`)
This is the most critical pattern for the AI to build. It ensures that when you add a new visualization type in the future, you only touch this one file.

```tsx
import { LineChart, BodyMap, StatCard } from '@/components/visualizations';

export const ComponentRegistry = {
  line: LineChart,
  body_map: BodyMap,
  stat_card: StatCard,
  // Add new visualization components here as the platform grows
};

export const DynamicVisualizer = ({ type, data, config }) => {
  const Component = ComponentRegistry[type];
  if (!Component) return <p>Unsupported visualization type: {type}</p>;
  return <Component data={data} config={config} />;
};
```

---

## Architecture additions (post-MVP)

The following capabilities have been layered on top of the original spec
above. They preserve the "configuration over code" thesis — none required
hardcoded forms, none added new chart-rendering paths in React.

### 1. Calendar events as first-class entities

`Event` (in the new `events` app) is the calendar primitive:

* Owned by a `Department` (whose calendar it lives on), authored by a `User`
* Typed via `event_type` (match / training / medical_checkup / physical_test
  / team_speech / nutrition / other)
* Three participation scopes: `individual` / `category` / `custom`. Whatever
  the scope, the actual roster is always materialized into a `participants`
  M2M at create time so a player joining the team next week isn't
  retroactively invited to last week's event.
* Type-specific data (e.g. opponent + score for matches, opponent club name,
  competition, is_home, duration) lives in `event.metadata` JSONB. Same
  flexibility-via-JSONB pattern as `ExamTemplate.config_schema`.

`ExamResult.event` is a nullable FK. When set, `recorded_at` is overridden
server-side to `event.starts_at` — the event is the authoritative timestamp.
This binds heterogenous data captures (GPS files, per-player match
performance, medical checkups) to the same calendar moment without forcing
any change to the result's storage shape.

### 2. Configurable input modes per template

`ExamTemplate.input_config` controls how staff submit data:

```json
{
  "input_modes": ["single", "bulk_ingest"],
  "default_input_mode": "single",
  "modifiers": { "prefill_from_last": false },
  "allow_event_link": true,
  "column_mapping": { /* file → template_key recipe; see STATUS §3.10 */ }
}
```

The frontend's registrar route reads this config and dispatches to either
the auto-generated single-form (`DynamicUploader`) or the file-upload flow
(`BulkIngestForm`). When `allow_event_link` is set, the single form also
shows a match-picker so per-player results can be FK-linked to the right
event. New input modes (team_table, quick_list) plug in without touching
templates that haven't opted into them.

### 3. Bulk ingest with player-alias matching

The `bulk_ingest` mode is a four-step pure-Python pipeline:

```
file bytes
  → parse_xlsx        (openpyxl, header strip, blank rows)
  → match_rows        (PlayerAlias-then-name, diacritics-folded)
  → transform_rows    (segment-aware: per-segment via {segment} pattern,
                       cross-segment via reduce: max|sum|avg|last)
  → preview / commit  (dry_run flag, optional event linking)
```

* Segment-aware transformations collapse multi-row exports (P1 / P2 / Total
  per player) into one `ExamResult` per player without changing the result
  schema. The formula engine learned `coalesce(a, b, …, 0)` so totals
  survive a substitute-only player whose P1 fields are missing.
* `PlayerAlias` (kind: nickname / squad_number / external_id, source:
  manual / catapult / wimu / …) holds the alternate identifiers files
  identify players by. External IDs are unique per `(kind, source, value)`
  within a club, validated in `clean()`. The same data path will serve
  third-party API integrations: a Catapult export becomes
  `kind="external_id", source="catapult"` aliases.

### 4. Authoring abstraction for `config_schema`

Rather than ask non-technical staff to type 48-field JSON blobs in a
textarea, the platform exposes `TemplateField` rows — a real Django model
that mirrors each entry of `config_schema['fields']`. Saving via the
admin's inline form regenerates the JSON. The reverse direction —
`rebuild_template_fields()` — is used by the data migration that backfilled
existing templates and by `python manage.py sync_template_fields` for
post-seed-command rebuilds.

The runtime canonical source is still `template.config_schema` JSONB. The
formula engine, frontend rendering, bulk ingest pipeline, and dashboard
layouts didn't change. `TemplateField` is purely an authoring layer.