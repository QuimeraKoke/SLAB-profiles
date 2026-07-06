# SLAB — Navigation & IA Audit (pivot-era)

> **Date:** 2026-06-21. **Method:** five parallel specialist agents (UX
> Researcher, UX Architect, Accessibility Auditor, Frontend Developer, UI
> Designer), read-only, over `Sidebar.tsx` / `Navbar.tsx` / `Breadcrumbs.tsx`
> / the `(dashboard)` route tree / the mobile drawer, assessed against the
> **SLAB IA principles** in `AGENTS.md` and the prior **`UX_AUDIT.md`**
> (whose Phases 1–4 already landed — those fixes are *preserved*, not
> re-litigated). This doc is the follow-on **navigation** assessment tied to
> the reports→dashboards + S-LAB AI pivot. Findings are tagged `NAV-NN` for
> tracking and code references, in the spirit of `UX_AUDIT.md`'s
> `QW-/IA-/L-/ME-` tags.

## Locked product decisions (2026-06-21)

- Downloadable Word/PDF **reports retired** (already unlinked from the UI);
  the on-screen `/reportes/[deptSlug]` pages are the interactive dashboards.
- The **"Reportes"** sidebar group is renamed **"Dashboard"** (label only;
  the `/reportes/[dept]` URL is kept for now — route migration deferred).
- **Home = Centro de mando** — the brand link + breadcrumb "Inicio" point
  there (resolving today's split where only `/` and login redirect there).
- **S-LAB AI = three touchpoints, no dedicated chat page:**
  1. **Floating button** — quick ask-anywhere Q&A (global, category-scoped).
  2. **"Ask S-LAB AI" menu entry** — a discoverable doorway that opens the
     *same* floating chat (no new route).
  3. **Embedded AI widget** — contextual *ask → chart → promote to this
     board*, bound to a department + player/team context, on the Dashboard
     and player views. Built in the **views** phase.

## Findings (consolidated, tagged)

| Tag | Finding | Sev | Lens | Key refs | Phase |
| --- | ------- | --- | ---- | -------- | ----- |
| **NAV-01** | "Reportes" is now a misnomer — these are interactive dashboards, not downloadable docs; the label points users at the retired concept. String is load-bearing in ~5 spots. | High | UX·IA·FE·UI | `Sidebar.tsx:124`, `Breadcrumbs.tsx:25`, `centro-de-mando/page.tsx:113`, `Hero.tsx:73` | **P1** |
| **NAV-02** | The "ask S-LAB AI" assistant has no IA home, no route, and in-memory state (lost on reload); only a floating FAB. | High | UX·IA·FE·A11y·UI | `TeamChat.tsx`, `layout.tsx:57` | **P1/P2** |
| **NAV-03** | `/nutricional/resumen` is a dead placeholder route (no nav entry, no parent, "contenido… irá aquí"). | High | UX·IA·FE | `nutricional/resumen/page.tsx` | **P1** |
| **NAV-04** | The "Por jugador" tab inside `/reportes/[dept]` duplicates the player profile department view. **Decided 2026-06-21:** remove the tab — Dashboard = squad, profile = player (reached via Equipo). Mitigation: add a per-row **"Ver perfil →"** on the Plantel table so squad→player drill-down stays one click. | Med | UX·IA | `reportes/[deptSlug]/page.tsx:290` | **Views** |
| **NAV-05** | Label collisions (principle #3): navbar "Perfil Jugadores" vs "Perfil" (player record); home split; "Equipo"/"Gestionar plantel"/"Jugadores". | Med | UX·FE | `Navbar.tsx:181`, `Breadcrumbs.tsx:124,26` | **P1** |
| **NAV-06** | Mobile drawer: no focus trap, off-screen links stay focusable (the `aria-hidden` is inverted/ineffective), background not inert, backdrop not keyboard-dismissible. A reusable `useFocusTrap` already exists. | High | A11y | `Sidebar.tsx:174`, `layout.tsx:38-48`, `hooks/useFocusTrap.ts` | **P3** |
| **NAV-07** | `/partidos/nuevo` & `/partidos/[id]/editar` highlight zero nav entries (no `activePrefixes`). Generalize leaf active-state to prefix-match its own href. | Med | FE | `Sidebar.tsx:62,216` | **P2** |
| **NAV-08** | Default-expand hard-codes `"Reportes"`; the comment disagrees with behavior; it reads `pathname` once and never recomputes on client nav. | Med | FE | `Sidebar.tsx:91-95` | **P1/P2** |
| **NAV-09** | Departments fetch has no loading/error state — a hiccup silently deletes the whole Análisis section. | Med | FE | `Sidebar.tsx:102-119` | **P2** |
| **NAV-10** | `NavGroup` has no role field; section logic is inline ternaries; `navItems` (`:163`) is dead code with a false comment. | Med | FE | `Sidebar.tsx:121-163` | **P2** |
| **NAV-11** | "Uso" (superuser adoption metric) is mis-grouped under Análisis; belongs in Administración. | Low | UX·IA·FE | `Sidebar.tsx:135` | **P1** |
| **NAV-12** | Visual: sections read flat (no rhythm/dividers); two "active" languages (left-bar vs floating dot); bare-text department sub-items; overloaded navbar brand; no color tokens (hardcoded hex everywhere). | High* | UI | `Sidebar.module.css`, `Navbar.*` | **P4** |
| **NAV-13** | Reduced-motion is not honored on nav motion (drawer slide, backdrop fade, FAB lift) — inconsistent with the codebase's own L6 standard. | Med | A11y | `Sidebar.module.css:286`, `TeamChat.module.css` | **P3/P4** |
| **NAV-14** | TeamChat dialog lacks Escape/focus-move/restore; FAB has no `:focus-visible`. (Bell dropdown is correct — preserve.) | Med | A11y | `TeamChat.tsx:88`, `TeamChat.module.css` | **P3** |
| **NAV-15** | Breadcrumb renders dept slugs as `Fisico` (no accent/real name); wire `useBreadcrumbLabel(deptSlug, department.name)` like the profile page does. | Low | FE | `Breadcrumbs.tsx:34-39,107` | **P2** |

\* High within the visual lens; overall a polish phase.

## Preserve — already correct (do not regress)

Skip-to-main link; group toggles as real `<button>`s with `aria-expanded` +
`aria-controls` + genuinely `hidden` panels; `aria-current="page"` on active
leaves (with `/perfil/*` → Equipo); the bell dropdown pattern (`role="dialog"`
+ Escape-to-close + focus restore + click-outside); brand as a single home
link; heading hierarchy (navbar demoted from `<h1>`); decorative SVG
`aria-hidden`; breadcrumb landmark + `aria-current` on last crumb; both
`<nav>` landmarks uniquely named.

## Proposed IA tree

```
SIDEBAR
 Operativa
  ├ Centro de mando   /centro-de-mando     (home · cross-area daily triage)
  ├ Equipo            /equipo              (roster; active on /perfil/*)
  └ Partidos          /partidos            (active on /partidos/*)         [NAV-07]
 Análisis
  ├ Dashboard         /reportes/[dept]     [RENAME from "Reportes"]        [NAV-01]
  └ Ask S-LAB AI      → opens floating chat (no route)                     [NAV-02]
 Administración
  ├ Gestionar plantel /configuraciones/jugadores
  └ Uso               /uso  (superuser)    [MOVED from Análisis]           [NAV-11]
 Cerrar sesión

NAVBAR: brand → /centro-de-mando, retitled off "Perfil Jugadores"           [NAV-05]
REMOVE: /nutricional/resumen                                                [NAV-03]
VIEWS PHASE: drop "Por jugador" tab (rows → /perfil/[id]?tab=dept)          [NAV-04]
```

## Phased plan

- **P1 — Labels & IA (low risk):** NAV-01, NAV-03, NAV-05, NAV-11, +
  Ask-S-LAB-AI menu entry (NAV-02, needs lifting chat open-state) and the
  default-expand label fix (NAV-08, partial).
- **P2 — Nav model & active-state:** NAV-07, NAV-08, NAV-09, NAV-10, NAV-15.
- **P3 — Mobile-drawer accessibility:** NAV-06, NAV-13, NAV-14.
- **P4 — Visual polish:** NAV-12, NAV-13.
- **Views phase:** NAV-04 + the embedded contextual AI widget + the
  ask→chart→promote loop.
