/**
 * Permission helpers that mirror the backend's `_has_perm`.
 *
 * The backend returns `permissions: string[]` on the `me` / `login`
 * payloads. Superusers receive a single `"*"` sentinel because
 * enumerating every Django permission would be wasteful and noisy.
 *
 * These helpers are pure / context-free. Use `usePermission` inside
 * components for reactive reads, or `hasPermission(user, codename)`
 * when you already have the user (e.g. in render functions far from
 * the auth context).
 */

import { useAuth } from "@/context/AuthContext";
import type { ApiUser } from "@/lib/types";

/** Lower-level helper. Returns true when the user is a superuser OR
 *  has the exact codename. Codename format: `app_label.codename`
 *  (e.g. `"exams.delete_examresult"`). */
export function hasPermission(
  user: ApiUser | null | undefined,
  codename: string,
): boolean {
  if (!user) return false;
  if (user.permissions?.includes("*")) return true;
  return user.permissions?.includes(codename) ?? false;
}

/** React hook variant — re-renders when the auth user changes. */
export function usePermission(codename: string): boolean {
  const { user } = useAuth();
  return hasPermission(user, codename);
}

/** Convenience: does the user have ANY of the listed permissions?
 *  Used to hide entire action bars when none of their buttons would
 *  be usable. */
export function useAnyPermission(codenames: string[]): boolean {
  const { user } = useAuth();
  if (!user) return false;
  if (user.permissions?.includes("*")) return true;
  return codenames.some((c) => user.permissions?.includes(c) ?? false);
}
