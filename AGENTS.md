<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:ia-principles -->
# SLAB IA principles (UX_AUDIT.md, codified 2026-06-15)

Non-negotiable conventions for the frontend. New screens must respect these
or explicitly justify the deviation in code review.

1. **Persistent breadcrumb on every page ≥ 2 levels deep**. Format:
   `Sección › Entidad › Acción`. Implemented via
   `frontend/src/components/layout/Breadcrumbs.tsx`. Detail pages set
   their entity label via `useBreadcrumbLabel(segment, label)` in a
   `useEffect`. Don't render a separate "back" link if the breadcrumb is
   already telling the same story.

2. **URL is the source of truth for tabs and filters**. Bookmarkable,
   refresh-safe, deep-linkable from alerts. Use the canonical
   `<ProfileTabs>` pattern (`?tab=` query param synced via `router.replace`).
   Do not store tab/filter state in local React state alone.

3. **One label = one meaning across the app**. "Perfil" is the player's
   record at `/perfil/[id]`, not the logged-in user. "Equipo" is the
   roster. "Partidos" is the match calendar. Don't reuse labels.

4. **Group navigation by frequency-of-use, not data model**. Sidebar
   groups (Operativa, Análisis, Administración) reflect how often users
   touch each section, not how the backend models them.

5. **Global controls (category, date, role) must be universally honored**.
   The navbar's category picker filters all *viewing* surfaces (lists,
   dashboards, reports). Admin/CRUD surfaces (Administración → Gestionar
   plantel) take the picker's value as their default but show a visible
   chip indicating "Mostrando categoría X" or "Mostrando todas las
   categorías" so the user knows the in-page filter has taken over.
   Screens that silently ignore the global picker are an anti-pattern.

6. **Destructive actions use `<ConfirmDialog variant="danger">`**, never
   `window.confirm()`. The danger variant auto-focuses Cancel.

7. **Form errors are programmatically associated with inputs**. Errors
   live in a container with `role="alert"`. The offending input(s) get
   `aria-invalid="true"` + `aria-describedby={errorId}`. On submit
   failure, focus the first invalid field.

8. **All modals use `<Modal>`**, which provides focus trap + restoration
   and respects the modal stack (nested modals close one layer at a time
   on Escape).

9. **Successful mutations show a `toast.success()`**. A silent redirect
   isn't enough feedback — users will double-submit.
<!-- END:ia-principles -->
