// API client for the injury progression log ("bitácora") — dated notes on an
// Episode, each carrying documents (imaging/reports) rendered inline.
// Mutations are Editor-gated on the backend (exams.change_episode).

import { api, getToken } from "@/lib/api";
import type { Episode, EpisodeNote, EpisodeNoteMetrics } from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

export function listEpisodeNotes(episodeId: string): Promise<EpisodeNote[]> {
  return api<EpisodeNote[]>(`/episodes/${episodeId}/notes`);
}

export interface EpisodeNoteInput {
  entry_date: string;
  title: string;
  note: string;
  metrics: EpisodeNoteMetrics;
}

export function createEpisodeNote(
  episodeId: string,
  input: EpisodeNoteInput,
): Promise<EpisodeNote> {
  return api<EpisodeNote>(`/episodes/${episodeId}/notes`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateEpisodeNote(
  episodeId: string,
  noteId: string,
  patch: Partial<EpisodeNoteInput>,
): Promise<EpisodeNote> {
  return api<EpisodeNote>(`/episodes/${episodeId}/notes/${noteId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteEpisodeNote(episodeId: string, noteId: string): Promise<unknown> {
  return api(`/episodes/${episodeId}/notes/${noteId}`, { method: "DELETE" });
}

/** Upload one file and pin it to a note. Uses raw fetch for multipart
 *  (the shared `api` helper JSON-encodes bodies). */
export async function uploadNoteAttachment(noteId: string, file: File): Promise<void> {
  const token = getToken();
  const fd = new FormData();
  fd.append("file", file);
  fd.append("source_type", "episode_note");
  fd.append("source_id", noteId);
  const res = await fetch(`${API_URL}/attachments`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: fd,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Error ${res.status}`);
  }
}

export function deleteAttachment(attachmentId: string): Promise<unknown> {
  return api(`/attachments/${attachmentId}`, { method: "DELETE" });
}

export interface SignedUrl {
  url: string;
  mime_type: string;
  filename: string;
}

/** Fetch a fresh signed URL for full-size viewing (list URLs expire ~5 min). */
export function fetchSignedUrl(attachmentId: string): Promise<SignedUrl> {
  return api<SignedUrl>(`/attachments/${attachmentId}/signed-url`);
}

// ── Stage change (the only thing edited on the ficha) ────────────────────────

/** Advance ONLY the injury stage; the backend carries the definition forward. */
export function advanceEpisodeStage(
  episodeId: string,
  stage: string,
  effectiveDate?: string,
): Promise<Episode> {
  return api<Episode>(`/episodes/${episodeId}/stage`, {
    method: "POST",
    body: JSON.stringify({ stage, effective_date: effectiveDate ?? null }),
  });
}
