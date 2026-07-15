// Thin fetch wrapper that attaches the JWT and parses JSON.
// All API calls in the app go through `api()`.
//
// Session handling:
//  - The token slides forward while the user is active: before each request,
//    if it's within REFRESH_THRESHOLD of expiry, we transparently call
//    /auth/refresh to mint a fresh one — an active user never gets kicked out.
//  - On a genuine 401 (token already expired / invalid, e.g. the user was away
//    past the lifetime), we clear the session and bounce to /login instead of
//    letting every endpoint fail silently.

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

const TOKEN_KEY = "slab_token";
const EXP_KEY = "slab_token_exp";
// Refresh once the token has less than this left (12h lifetime → refresh during
// the last hour of activity).
const REFRESH_THRESHOLD_MS = 60 * 60 * 1000;

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** Persist the token and (optionally) its expiry, so the client can refresh
 *  proactively before it lapses. Pass null to clear the session. */
export function setToken(token: string | null, expiresAt?: string | null) {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
    if (expiresAt) {
      localStorage.setItem(EXP_KEY, String(new Date(expiresAt).getTime()));
    }
  } else {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXP_KEY);
  }
}

function getTokenExp(): number | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(EXP_KEY);
  return v ? Number(v) : null;
}

function isAuthEndpoint(path: string): boolean {
  return path.startsWith("/auth/login") || path.startsWith("/auth/refresh");
}

// ── Proactive sliding refresh ────────────────────────────────────────────────

let refreshInFlight: Promise<void> | null = null;

async function doRefresh(): Promise<void> {
  const token = getToken();
  if (!token) return;
  const res = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
  });
  if (!res.ok) throw new ApiError(res.status, "refresh failed");
  const body = (await res.json()) as { access_token: string; expires_at: string };
  setToken(body.access_token, body.expires_at);
}

/** Refresh the token if it's close to expiry. Deduped so concurrent requests
 *  trigger at most one refresh. Never throws (a failed refresh just lets the
 *  subsequent request 401 → login). */
function refreshIfNeeded(): Promise<void> {
  const token = getToken();
  const exp = getTokenExp();
  if (!token || exp === null) return Promise.resolve();
  const now = Date.now();
  // Still fresh, or already expired (can't refresh an expired token — let the
  // request 401 and bounce to login).
  if (exp - now > REFRESH_THRESHOLD_MS || exp <= now) return Promise.resolve();
  if (!refreshInFlight) {
    refreshInFlight = doRefresh()
      .catch(() => {})
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

function handleUnauthorized() {
  setToken(null);
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    // Full navigation clears in-memory app state cleanly.
    window.location.href = "/login";
  }
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  // Slide the session forward before it lapses (skip for the auth endpoints
  // themselves to avoid recursion).
  if (!isAuthEndpoint(path)) {
    await refreshIfNeeded();
  }

  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  // Don't force application/json on FormData — the browser must set its own
  // multipart Content-Type with the boundary marker.
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = path.startsWith("http") ? path : `${API_URL}${path}`;
  const res = await fetch(url, { ...init, headers });

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    // A 401 on a normal (non-login) request means the session lapsed — clear it
    // and send the user to login rather than surfacing errors on every screen.
    if (res.status === 401 && !isAuthEndpoint(path)) {
      handleUnauthorized();
    }
    const message =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }

  return body as T;
}
