import { getToken } from "@/lib/api";

/** Fetch an API file with the JWT (the API lives on another origin, so a
 *  plain `<a href>` would not carry the header) and hand it to the browser
 *  as a download. Throws on a non-2xx response. */
export async function downloadFromApi(endpoint: string, filename: string): Promise<void> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${apiUrl}${endpoint}`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
