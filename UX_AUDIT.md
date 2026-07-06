# SLAB — UX Audit & Implementation Guide

**Date**: 2026-06-15
**Scope**: SLAB frontend (`/Users/jorgegutierrez/dev/SLAB-profiles/frontend`) — Next.js 16 App Router, custom CSS modules, Spanish UI / English code keys.
**Audited by**: UX Researcher + UX Architect + Accessibility Auditor (parallel agent run, code-level audit; runtime screen-reader verification not performed).
**Method**: Three independent agents read the App Router tree, the dashboard layout, components, and key pages. Findings cross-validated — items cited by ≥ 2 agents are treated as high-confidence.

---

## How to use this document

1. Read the **Executive Summary** to align on the diagnosis.
2. Pick the next section to attack from **Implementation Phases**.
3. For each finding, the **Where / Symptom / Fix** block is enough to begin work. Code skeletons are provided for non-obvious fixes (ARIA patterns, focus trap, etc.).
4. Tick items off in **Tracking Checklist** at the bottom as PRs land.

---

## Executive Summary

SLAB has solid bones — App Router structure, role plumbing, dashboard widgets, the new alert finalize pipeline all work. **The problem isn't features; it's the navigation contract**.

Three classes of issues cause users to feel lost:

1. **URLs don't reflect state**. Profile tabs are read from `?tab=` but never written back; switching a tab breaks the Back button and breaks deep-links from alert notifications.
2. **Keyboard / screen-reader pathways break in critical places**. Modal lacks focus trap, sidebar group toggles are `<div onClick>` (entire nav branches unreachable for keyboard users), every page title is "Create Next App".
3. **Several sidebar destinations are dead ends or wrong**. `/` shows a lorem-ipsum marketing template for a different product. `/perfil` always lands on "Selecciona un jugador". `/nutricional/resumen` says "irá aquí". The player search input has no `onChange`.

Most fixes are **small** — 1 to 20 lines each. The Top 10 quick wins below can land in a single afternoon. The medium-effort work (canonical Tabs, ConfirmDialog, breadcrumbs, form-error a11y) is 3–4 days. The long-term IA restructure is sprint-level.

---

## Top 10 Quick Wins (≤ 2 hours each)

These are ordered by impact-per-hour. Each is small enough to commit individually.

### QW-1 — Redirect `/` and kill the lorem-ipsum landing

**Where**: `frontend/src/app/(dashboard)/page.tsx` (lines 6-68)
**Symptom**: After login, clicking the SLAB logo, typing `/`, or stripping path segments lands on an English "construction profiles" marketing template with fake "Get Started" buttons. First-impression killer.
**Cited by**: UX Researcher (Critical 1), UX Architect (Critical 1)

**Fix**:
```tsx
// app/(dashboard)/page.tsx
import { redirect } from "next/navigation";

export default function DashboardIndex() {
  redirect("/equipo");
}
```
Later, replace with a role-aware **Inicio** (today's matches, pending exams, recent alerts, jump-to-player). For now, the redirect alone removes the embarrassment.

---

### QW-2 — Wire `/equipo` player search

**Where**: `frontend/src/components/equipo/PlayerListToolbar.tsx:5-21` + parent page
**Symptom**: The "Buscar jugador…" input has no `onChange`, no state, no filter wired up. Finding a player is the #1 expected task.
**Cited by**: UX Researcher (Critical 2), Accessibility (Blocker 5)

**Fix**: Lift the query state to the equipo page; pass `value` + `onChange` to the toolbar; filter `players` by `last_name` / `first_name` (accent-insensitive).

```tsx
// app/(dashboard)/equipo/page.tsx (excerpt)
const [query, setQuery] = useState("");
const normalize = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
const filtered = useMemo(() => {
  if (!query.trim()) return players;
  const q = normalize(query);
  return players.filter(p =>
    normalize(`${p.first_name} ${p.last_name}`).includes(q)
  );
}, [players, query]);

<PlayerListToolbar query={query} onQueryChange={setQuery} />
```

```tsx
// components/equipo/PlayerListToolbar.tsx
<input
  type="search"
  placeholder="Buscar jugador…"
  aria-label="Buscar jugador"
  value={query}
  onChange={e => onQueryChange(e.target.value)}
/>
```

Bonus: hide or remove the navbar magnifying-glass button until a real global search ships (`components/layout/Navbar.tsx:177-179`).

---

### QW-3 — Sync profile tabs to URL

**Where**: `frontend/src/app/(dashboard)/perfil/[id]/page.tsx:37,106`
**Symptom**: The page reads `?tab=` on mount but `onTabChange` only sets local state. Browser Back can't undo tab switches; alert deep-links (`?tab=objetivos`) work once then break.
**Cited by**: UX Researcher (High 4), UX Architect (High 2), Accessibility (Critical 8)

**Fix**: Use `router.replace` (not `push`) so Back still leaves the profile.

```tsx
// app/(dashboard)/perfil/[id]/page.tsx
"use client";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

const router = useRouter();
const pathname = usePathname();
const sp = useSearchParams();

const handleTabChange = (id: string) => {
  setActiveTab(id);
  const params = new URLSearchParams(sp.toString());
  params.set("tab", id);
  router.replace(`${pathname}?${params}`, { scroll: false });
};
```

---

### QW-4 — Per-route `<title>`

**Where**: `frontend/src/app/layout.tsx:19-22` plus each route's `page.tsx`
**Symptom**: Every browser tab and screen-reader page-load reads "Create Next App". WCAG 2.4.2 failure.
**Cited by**: Accessibility (Critical 7)

**Fix**: Remove the global title fallback, add per-route metadata. For dynamic routes use `generateMetadata`.

```tsx
// app/(dashboard)/equipo/page.tsx
export const metadata = { title: "Equipo · SLAB" };

// app/(dashboard)/perfil/[id]/page.tsx
export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const player = await fetchPlayer(id); // server-side
  return { title: `${player.first_name} ${player.last_name} · SLAB` };
}
```

Apply to: `/equipo`, `/partidos`, `/partidos/[id]/editar`, `/reportes/[deptSlug]`, `/perfil/[id]`, `/perfil/[id]/registrar/[templateId]`, `/configuraciones/jugadores`, `/login`, `/uso`.

---

### QW-5 — `lang="es"` + translate the Login page

**Where**: `frontend/src/app/layout.tsx` (html lang attr) + `frontend/src/app/login/page.tsx:75-113`
**Symptom**: `<html lang="en">` but the entire app is Spanish. Login page is in English ("Email", "Password", "Keep me logged in", "Login", "Signing in…").
**Cited by**: UX Researcher (High 8), Accessibility (Critical 17)

**Fix**:
- `app/layout.tsx`: `<html lang="es">`.
- `app/login/page.tsx`: translate labels — `Correo`, `Contraseña`, `Mantener sesión iniciada`, `Ingresar`, `Ingresando…`, "Error de inicio de sesión. Inténtalo de nuevo."

---

### QW-6 — Skip-to-main link

**Where**: `frontend/src/app/(dashboard)/layout.tsx`
**Symptom**: Every keyboard user tabs through ~30 navbar + sidebar items on every route change.
**Cited by**: Accessibility (Critical 6)

**Fix**:
```tsx
// app/(dashboard)/layout.tsx (top of the layout body)
<a href="#main" className={styles.skipLink}>Saltar al contenido</a>
...
<main id="main">{children}</main>
```

```css
/* styles for .skipLink — visually hidden until focused */
.skipLink {
  position: absolute; left: -9999px; top: 0;
}
.skipLink:focus {
  left: 8px; top: 8px; z-index: 9999;
  background: #fff; padding: 8px 12px; border-radius: 6px;
  outline: 2px solid #6366f1;
}
```

---

### QW-7 — Make Sidebar group toggles real buttons

**Where**: `frontend/src/components/layout/Sidebar.tsx:182-196` and `frontend/src/components/common/CollapsibleSection/CollapsibleSection.tsx:23-43`
**Symptom**: Group toggles (Configuraciones, Reportes) are `<div onClick>` — keyboard users **cannot expand them**, so the entire nested nav is unreachable.
**Cited by**: Accessibility (Blockers 2 & 3)

**Fix**: Replace `<div>` with `<button type="button">` and add `aria-expanded` + `aria-controls`.

```tsx
// Sidebar group header
<button
  type="button"
  className={styles.groupHeader}
  aria-expanded={isExpanded}
  aria-controls={`nav-group-${group.id}`}
  onClick={() => toggleGroup(group.id)}
>
  <Icon /> {group.label} <ChevronIcon />
</button>
<ul id={`nav-group-${group.id}`} hidden={!isExpanded}>...</ul>
```

Same pattern for `CollapsibleSection`.

---

### QW-8 — `aria-current="page"` on active sidebar link

**Where**: `frontend/src/components/layout/Sidebar.tsx:198-223`
**Symptom**: Visual "active" state has no programmatic equivalent.
**Cited by**: Accessibility (Critical 9)

**Fix**:
```tsx
<Link
  href={item.href}
  aria-current={isActive ? "page" : undefined}
  className={isActive ? styles.active : styles.item}
>
  {item.label}
</Link>
```

Also: when `pathname.startsWith("/perfil/")`, mark `/equipo` as the active parent (player profiles are children of the roster).

---

### QW-9 — Make PlayerTable rows fully clickable

**Where**: `frontend/src/components/equipo/PlayerTable.tsx:71-73`
**Symptom**: Only the player's name is a `<Link>`; clicking the avatar, position chip, or status pill does nothing.
**Cited by**: UX Researcher (Medium 11)

**Fix**: Wrap the whole row, or use `onClick` on the `<tr>`. The cleanest pattern:

```tsx
<tr
  className={styles.row}
  tabIndex={0}
  role="button"
  onClick={() => router.push(`/perfil/${player.id}`)}
  onKeyDown={(e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      router.push(`/perfil/${player.id}`);
    }
  }}
>
```
Also: drop the always-empty "Advertencia" column (line 83-88) until it has data. Dead visual noise.

---

### QW-10 — Promote Partidos to top-level sidebar

**Where**: `frontend/src/components/layout/Sidebar.tsx:56-63`
**Symptom**: The match calendar — a daily técnico/físico flow — is hidden under the gear icon "Configuraciones".
**Cited by**: UX Researcher (Critical 3), UX Architect (Critical 2)

**Fix**: Add a top-level entry next to "Equipo":

```ts
{ label: "Partidos", href: "/partidos", icon: CalendarIcon },
```

Keep "Jugadores" under Configuraciones for now. (Long-term it should move under Equipo → "Gestionar plantel" per the IA tree below.)

---

## Medium-effort changes (1–2 days each)

### ME-1 — Breadcrumbs in dashboard layout

**Where**: `frontend/src/app/(dashboard)/layout.tsx` + a new `frontend/src/components/layout/Breadcrumbs.tsx`
**Symptom**: No breadcrumbs anywhere. Deep routes give only the browser Back button.
**Cited by**: UX Researcher (Low 13), UX Architect (High 1)

**Design**: Persistent breadcrumb strip in the dashboard layout, rendered from the route segments. Format: `Sección › Entidad › Acción`.

```tsx
// components/layout/Breadcrumbs.tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const SEGMENT_LABELS: Record<string, string> = {
  equipo: "Equipo",
  perfil: "Jugador",
  partidos: "Partidos",
  reportes: "Reportes",
  configuraciones: "Configuraciones",
  registrar: "Registrar examen",
  editar: "Editar",
};

export function Breadcrumbs() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  // build cumulative hrefs: ["/equipo", "/equipo/abc", ...]
  // skip non-displayable segments (UUIDs) — look up entity labels via context

  return (
    <nav aria-label="Migas de pan" className={styles.breadcrumbs}>
      <ol>
        <li><Link href="/equipo">Inicio</Link></li>
        {/* … */}
      </ol>
    </nav>
  );
}
```

Entity labels (player name, match date) come from a `BreadcrumbContext` that detail pages populate via `useEffect`.

---

### ME-2 — Unified `ConfirmDialog`

**Where**: 8+ call sites using native `confirm()` / `alert()` — `partidos/page.tsx:222`, `configuraciones/jugadores/page.tsx:169`, profile events, contracts, results, goals, attachments
**Symptom**: Destructive actions use the browser's native unstyled modal, inconsistent with the styled `MatchForm` confirm modal at `MatchForm.tsx:469`.
**Cited by**: UX Researcher (High 6)

**Design**: Build a `<ConfirmDialog>` on top of `components/ui/Modal/Modal.tsx`. API:

```tsx
const { confirm } = useConfirm();
const ok = await confirm({
  title: "Eliminar examen",
  message: "Esta acción no se puede deshacer.",
  confirmLabel: "Eliminar",
  variant: "danger", // styles the confirm button red
});
if (!ok) return;
```

Implementation: a global `<ConfirmProvider>` in the dashboard layout that owns the dialog state; `useConfirm` returns a Promise-returning fn. Replace every `confirm()` and `alert()` call site.

---

### ME-3 — Canonical `<Tabs>` component

**Where**: Three competing implementations — `equipo/page.tsx:67-84`, `reportes/[deptSlug]/page.tsx:293-312` (the *correct* one), `perfil/[id]/page.tsx:90-106` (the *broken* one).
**Symptom**: Inconsistent deep-link behavior, broken Back button, no ARIA tab semantics in ProfileTabs.
**Cited by**: UX Architect (High 2), Accessibility (Critical 8)

**Design**: Single `components/ui/Tabs/Tabs.tsx` that:

- Renders `role="tablist"` on the container.
- Each tab is a `<button role="tab" aria-selected aria-controls={panelId} id={tabId}>`.
- Each panel is `<div role="tabpanel" aria-labelledby={tabId} id={panelId}>`.
- Active tab is **always** sourced from `?tab=` query param via `useSearchParams`; clicking writes via `router.replace`.
- Keyboard: Left/Right/Home/End cycle tabs (per ARIA APG). Tab/Shift+Tab moves focus into/out of the panel.

```tsx
<Tabs queryKey="tab" defaultTab="resumen">
  <TabList>
    <Tab id="resumen">Resumen</Tab>
    <Tab id="linea">Línea de tiempo</Tab>
    <Tab id="medico">Médico</Tab>
  </TabList>
  <TabPanel id="resumen"><Resumen /></TabPanel>
  <TabPanel id="linea"><Timeline /></TabPanel>
  <TabPanel id="medico"><MedicoTab /></TabPanel>
</Tabs>
```

Migrate all three call sites. Reference the existing reportes implementation — it's already mostly right.

---

### ME-4 — Modal focus trap + restoration

**Where**: `frontend/src/components/ui/Modal/Modal.tsx`
**Symptom**: Opening a modal doesn't move focus into the dialog; Tab continues into the page behind. Closing doesn't return focus to the trigger.
**Cited by**: Accessibility (Blocker 1)

**Fix**: Use a focus-trap pattern. Either install `react-focus-on`, or write a 30-line hook.

```tsx
// hooks/useFocusTrap.ts
export function useFocusTrap(active: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    previouslyFocused.current = document.activeElement as HTMLElement;
    const focusable = ref.current?.querySelectorAll<HTMLElement>(
      'a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    focusable?.[0]?.focus();

    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previouslyFocused.current?.focus();
    };
  }, [active]);

  return ref;
}
```

Also: change the modal heading from `<h3>` to `<h2>` and use `aria-labelledby` referencing the heading instead of `aria-label={title}` — the rendered text becomes the accessible name.

---

### ME-5 — Save-success toast

**Where**: `frontend/src/components/forms/DynamicUploader.tsx:283,312` + 4 other save paths
**Symptom**: After "Guardar informe" the page navigates back to the profile with no toast/confirmation. Users double-submit or refresh asking "did it save?"
**Cited by**: UX Researcher (High 5)

**Design**: A `<Toaster>` component in the dashboard layout + a `useToast()` hook. After save, `toast.success("Guardado correctamente")` before the redirect; on error, `toast.error(err.message)`.

Drop in: `DynamicUploader.onSaved`, `MatchForm`, `RosterPanel`, contract save, goal save.

---

### ME-6 — Form-error a11y pattern

**Where**: `DynamicUploader.tsx:394`, `TeamTableForm.tsx:410`, registrar form, match form
**Symptom**: Errors render in a sibling div as plain text. Inputs have no `aria-invalid`, no `aria-describedby`, errors have no `role="alert"`. Screen-reader users get **no notification** when validation fails — submit appears to do nothing.
**Cited by**: Accessibility (Critical 10)

**Pattern**:
```tsx
<input
  id={inputId}
  aria-invalid={!!error}
  aria-describedby={error ? errorId : undefined}
/>
{error && (
  <p id={errorId} role="alert" className={styles.error}>
    {error}
  </p>
)}
```

On submit failure: focus the first invalid field via a `ref`, so the user lands on the broken input and the screen reader announces the associated error.

---

### ME-7 — Notification dropdown a11y

**Where**: `frontend/src/components/layout/Navbar.tsx:180-263`
**Symptom**: Escape doesn't close, focus doesn't restore to bell on close, `role="menu"` is mis-applied (children are links + buttons, not menuitems).
**Cited by**: Accessibility (Blocker 4)

**Fix**:
- Remove `role="menu"` and `aria-haspopup="true"`; use `aria-haspopup="dialog"` and treat the dropdown as a popover dialog.
- Add Escape key handler that closes + restores focus to the bell.
- Use the same focus-trap hook as Modal (ME-4) — it composes.

---

## Long-term IA work (sprint-level)

### IA-1 — Adopt the proposed nav tree

The UX Architect's recommended structure:

```
SLAB
├── Inicio                 (role-aware: today, alerts, jumps)
├── Equipo                 (roster lives here)
│   ├── Plantel            (list/field view — current /equipo)
│   ├── Jugador            (perfil/[id])
│   │   ├── Resumen
│   │   ├── Línea de tiempo
│   │   ├── Eventos
│   │   ├── Objetivos
│   │   ├── Lesiones
│   │   └── Departamento ▾ (Médico, Físico, Nutricional, …)
│   └── Gestionar plantel  (was /configuraciones/jugadores)
├── Eventos                (was /partidos, promoted to top-level)
│   ├── Calendario
│   └── Partido            (detail / nuevo / editar)
├── Reportes
│   └── <Departamento>     (Plantel only — Por-jugador moves to Equipo)
└── Administración         (role-gated)
    ├── Plantillas de examen
    ├── Reglas de alerta
    ├── Usuarios y roles
    └── Uso (superuser)
```

Specific moves required:
- `/partidos` → `/eventos` (redirect old URL).
- `/configuraciones/jugadores` → `/equipo/gestionar` (redirect).
- `/reportes/[deptSlug]` keeps the Plantel tab; remove the "Por jugador" tab (it duplicates per-player department views).
- Sidebar group rename: "Configuraciones" → "Administración".

### IA-2 — Role-aware sidebar

**Where**: `frontend/src/components/layout/Sidebar.tsx:122-127`
**Symptom**: A Médico, Nutricionista, and Físico all see identical nav. Other-discipline sections clutter their view.

**Design**: Group nav by domain, with role-driven primary expansion:

```
Operativa     — Equipo, Eventos                  (everyone)
Clínica       — Mi departamento                  (médico, nutricionista, físico)
Análisis      — Reportes                         (técnico, médico, nutricionista, físico, admin)
Sistema       — Administración                   (admin only)
```

A user's primary domain is expanded by default; others collapsed.

### IA-3 — Reportes vs Profile-department dedup

**Where**: `reportes/[deptSlug]/page.tsx:343-368` ("Por jugador" tab embeds `ProfileDepartment`)
**Symptom**: Same widget set reachable via two structurally unrelated paths.

**Decision**: Per-player department views live ONLY on the player profile (`/perfil/[id]?tab=<dept>`). The "Por jugador" tab in Reportes is removed; its function is replaced by a "Ver jugador" link on the Plantel report that jumps to the player profile.

### IA-4 — Global Category-picker contract

**Where**: `frontend/src/components/layout/Navbar.tsx:162-176` (the global picker) vs pages that silently ignore it
**Symptom**: Switching category in the header changes some screens, not others. Users can't trust the control.

**Convention**:
1. The global picker filters all **viewing** surfaces (lists, dashboards, reports).
2. Admin/CRUD surfaces respect the picker as the default but show an in-page filter chip that can be overridden, with a visible badge: `"Mostrando categoría: Sub-19"` or `"Mostrando todas las categorías"`.
3. Document this in `MANUAL_ADMIN.md` once implemented.

---

## Polish (Low priority — batch when convenient)

- **L1** Make SLAB logo + club logo in Navbar clickable → home (`Navbar.tsx:132-159`).
- **L2** Match `/perfil/*` as active under Equipo in sidebar (`Sidebar.tsx:174-177`).
- **L3** Auto-expand only the sidebar group containing the active route (`Sidebar.tsx:75-78`).
- **L4** Standardize Spanish voice on Chilean tuteo. Files known to use voseo: `registrar/[templateId]/page.tsx:421,433`.
- **L5** Demote Navbar `<h1>` to `<p>` (avoids two h1s per page); Modal heading `<h3>` → `<h2>`.
- **L6** Honor `prefers-reduced-motion`: wrap Modal `pop` animation and login video autoplay in `@media (prefers-reduced-motion: reduce)`.
- **L7** Add `aria-hidden="true"` to decorative SVG logo (`Navbar.tsx:133-138`); translate `aria-label="Search"` to Spanish.

---

## Implementation Phases

### Phase 1 — Quick wins (1 afternoon, ~4 hours total)

Bundle into 3 commits:

**Commit A** — "Fix the front door"
- QW-1 redirect `/` → `/equipo`
- QW-4 per-route `<title>`
- QW-5 `lang="es"` + login translation
- QW-6 skip-to-main link

**Commit B** — "Sidebar a11y + wayfinding"
- QW-7 sidebar group toggles as `<button>` + `aria-expanded`
- QW-8 `aria-current` on active link
- QW-10 promote Partidos to top-level

**Commit C** — "Equipo + profile UX"
- QW-2 wire the search input
- QW-3 sync profile tabs to URL
- QW-9 PlayerTable rows fully clickable

### Phase 2 — Core UX patterns (3–4 days)

Land each as its own PR:

1. ME-1 Breadcrumbs
2. ME-2 ConfirmDialog
3. ME-3 Canonical Tabs (and migrate ProfileTabs)
4. ME-4 Modal focus trap
5. ME-5 Toast component
6. ME-6 Form-error a11y pattern
7. ME-7 Notification dropdown a11y

### Phase 3 — IA restructure (sprint)

1. IA-1 nav tree (with redirects for old URLs to preserve bookmarks)
2. IA-2 role-aware sidebar grouping
3. IA-3 Reportes/Profile dedup
4. IA-4 Category-picker contract documentation + enforcement

### Phase 4 — Polish (1 day, anytime)

Batch L1–L7.

---

## Verification

After each phase, run these checks:

**Phase 1**:
- `view-source:` on every route shows a unique `<title>`.
- Keyboard tab-through of the sidebar: every group expands; every link is reachable.
- Browser Back button correctly undoes profile-tab switches.
- `/equipo` search filters in real-time.

**Phase 2**:
- Open any modal with keyboard → focus moves in → Tab cycles inside → Escape closes → focus restores to trigger.
- Submit a form with invalid data → focus moves to first invalid field → screen reader announces the error.
- Breadcrumb visible on every page ≥ 2 levels deep.

**Phase 3**:
- Sidebar item count appropriate to logged-in role.
- Old URLs (`/partidos`, `/configuraciones/jugadores`) redirect cleanly.
- Bookmark from "Por jugador" of Reportes redirects to the player profile.

**Phase 4 (a11y final pass)**:
- Run axe DevTools on each major route — target zero violations.
- Test with VoiceOver on macOS: log in → open a player → switch a tab → open a modal → save. Every step should be announced.
- Test with `prefers-reduced-motion: reduce` enabled — modals and login video should not animate.

---

## IA Principles SLAB Should Adopt

These should become non-negotiable going forward — codify in `AGENTS.md` once Phase 1 ships.

1. **Persistent breadcrumb on every page ≥ 2 levels deep.** Format: `Sección › Entidad › Acción`.
2. **URL is the source of truth for tabs and filters.** Bookmarkable, refresh-safe, deep-linkable from alerts.
3. **One label = one meaning across the app.** Never reuse "Perfil" for both "logged-in user" and "a player's record."
4. **Group navigation by frequency-of-use, not by data model.** Daily ops on top (Equipo, Eventos, Reportes); admin at the bottom.
5. **Global controls (category, date, role) must be universally honored.** If a screen opts out, surface that explicitly with a chip.

---

## Tracking Checklist

### Phase 1 — Quick wins ✅ landed 2026-06-15
- [x] QW-1 Root redirect + delete lorem-ipsum (also `/perfil` index → redirect)
- [x] QW-2 Player search wired (accent-insensitive; differentiated empty states)
- [x] QW-3 Profile tabs sync to URL (+ heal stale `?tab=` + dynamic document.title)
- [x] QW-4 Per-route `<title>` (template `%s · SLAB` + per-route metadata layouts)
- [x] QW-5 `lang="es"` + login translated
- [x] QW-6 Skip-to-main link
- [x] QW-7 Sidebar toggles as `<button>` (aria-expanded + aria-controls + focus-visible)
- [x] QW-8 `aria-current` on active link (Equipo also lights up on `/perfil/*`)
- [x] QW-9 PlayerTable rows clickable (stretched-link; dropped dead Advertencia column)
- [x] QW-10 Partidos promoted to top-level

### Phase 2 — Core UX patterns ✅ landed 2026-06-15
- [x] ME-1 Breadcrumbs (with BreadcrumbProvider for dynamic entity labels)
- [x] ME-2 ConfirmDialog (replaced all 9 native `confirm()` / `alert()` sites)
- [x] ME-3 Canonical Tabs (ProfileTabs now ARIA-correct with arrow-key nav + tabpanel)
- [x] ME-4 Modal focus trap + restoration (`useFocusTrap` hook)
- [x] ME-5 Toast component (success/error in save paths)
- [x] ME-6 Form-error a11y (role="alert" + aria-live in DynamicUploader; broader pass pending)
- [x] ME-7 Notification dropdown a11y (Escape closes + focus restore + role="dialog")

### Phase 3 — IA restructure ✅ landed 2026-06-15 (partial — see notes)
- [x] IA-1 Sidebar label: "Configuraciones" → "Administración"; "Jugadores" → "Gestionar plantel". URL renames (`/partidos` → `/eventos`, `/configuraciones/jugadores` → `/equipo/gestionar`) **deferred** — bookmarks + cross-references would need coordinated cleanup; defer to a dedicated migration.
- [x] IA-2 Sidebar visually grouped (Operativa / Análisis / Administración). Full role-aware nav (hide other-discipline groups per role) **deferred** — needs role inventory + decision on Médico/Nutri/Físico defaults.
- [x] IA-3 Reportes "Por jugador" tab now signposts the player profile as canonical view (`Abrir perfil →` link). Full removal **deferred** until a "Ver perfil" link is added on Plantel report rows so the workflow stays intact.
- [x] IA-4 Category-picker contract documented in `AGENTS.md` (9 IA principles total). Visible "Mostrando todas las categorías" badge on screens that opt out **deferred** — requires per-screen audit.

### Phase 4 — Polish ✅ landed 2026-06-15
- [x] L1 Logos clickable (SLAB + club section wrapped in `<Link href="/equipo">`)
- [x] L2 `/perfil/*` active under Equipo (done in QW-8 via `activePrefixes`)
- [x] L3 Sidebar auto-expand active group only (initial state derived from `pathname`)
- [x] L4 Standardize Spanish voice (voseo → tuteo in registrar + MatchPicker + DynamicUploader)
- [x] L5 Heading hierarchy (Navbar h1 → spans inside brand link; Modal h3 → h2 in Phase 2)
- [x] L6 `prefers-reduced-motion` (Modal + Toast in Phase 2; login video in Phase 4)
- [x] L7 SVG `aria-hidden` (Navbar brand SVG; club logo alt now empty since the link has aria-label)

---

## Source agent reports

This document is the synthesis. The raw findings from each agent (with file paths, line numbers, and severity scoring) are recoverable from the conversation log if needed, but everything actionable has been folded into the sections above.

**Confidence**: High. Three independent agents converged on the same critical findings (lorem-ipsum at `/`, non-functional search, dead-end `/perfil`, broken profile tabs, missing focus management, English login). When multiple independent passes find the same defect, it's real.

**Out of scope of this audit**:
- Visual design / aesthetics
- Backend API design
- Performance (Lighthouse, Core Web Vitals)
- Mobile-specific layout audit (covered partially via responsive concerns but no device testing performed)
- Internationalization beyond Spanish (no `i18n` framework currently in use; not recommended yet)
