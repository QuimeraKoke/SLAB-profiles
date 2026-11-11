import { api, ApiError } from "@/lib/api";

/**
 * Open the Drive sheet where an import problem is — the tab and row (or
 * column) of one of its examples. The link is computed by the API (it may read
 * the tab to find the row), so the new tab is opened FIRST, synchronously, and
 * pointed at the link when it arrives: a window opened after an `await` is
 * blocked as a popup.
 */
export async function openInSheet(categoryId: string, issueId: string, index = 0): Promise<string | null> {
  const w = window.open("about:blank", "_blank");
  try {
    const r = await api<{ url: string | null; note: string }>(
      `/data-sources/issues/${issueId}/locate?category_id=${categoryId}&i=${index}`);
    if (!r.url) {
      w?.close();
      return r.note || "Esta fuente no es una planilla.";
    }
    if (w) {
      w.opener = null;
      w.location.href = r.url;
    } else {
      window.location.href = r.url;
    }
    return null;
  } catch (e) {
    w?.close();
    return e instanceof ApiError ? e.message : "No se pudo abrir la planilla.";
  }
}
