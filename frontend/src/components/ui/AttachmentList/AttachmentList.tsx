"use client";

import React, { useEffect, useRef, useState } from "react";

import { api, ApiError, getToken } from "@/lib/api";
import type { Attachment, AttachmentSourceType } from "@/lib/types";
import styles from "./AttachmentList.module.css";
import { ACCEPTED_FILE_TYPES, formatSize, iconFor } from "./utils";

interface Props {
  sourceType: AttachmentSourceType;
  sourceId: string;
  /** Required when sourceType === 'exam_field'. */
  fieldKey?: string;
  /** Hide upload UI + delete actions. */
  readOnly?: boolean;
  /** Optional label rendered above the dropzone. */
  hint?: string;
}

interface UploadingFile {
  tempId: string;
  filename: string;
  size: number;
}

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

const ACCEPTED_TYPES = ACCEPTED_FILE_TYPES;

export default function AttachmentList({
  sourceType,
  sourceId,
  fieldKey = "",
  readOnly = false,
  hint,
}: Props) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState<UploadingFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      source_type: sourceType,
      source_id: sourceId,
    });
    if (fieldKey) params.set("field_key", fieldKey);
    api<Attachment[]>(`/attachments?${params}`)
      .then((data) => {
        if (!cancelled) {
          setAttachments(data);
          setLoaded(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Error al cargar archivos");
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sourceType, sourceId, fieldKey]);

  const upload = async (files: FileList | File[]) => {
    setError(null);
    const list = Array.from(files);
    if (list.length === 0) return;

    const uploads: UploadingFile[] = list.map((f, i) => ({
      tempId: `${Date.now()}-${i}`,
      filename: f.name,
      size: f.size,
    }));
    setUploading((prev) => [...prev, ...uploads]);

    // Upload sequentially — keeps progress UI simple and avoids slamming the
    // backend with concurrent multipart uploads.
    const created: Attachment[] = [];
    const failures: string[] = [];
    const token = getToken();
    for (let i = 0; i < list.length; i++) {
      const file = list[i];
      const upload = uploads[i];
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("source_type", sourceType);
        fd.append("source_id", sourceId);
        if (fieldKey) fd.append("field_key", fieldKey);

        const res = await fetch(`${API_URL}/attachments`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body: fd,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `Error ${res.status}`);
        }
        const att = (await res.json()) as Attachment;
        created.push(att);
      } catch (err) {
        failures.push(`${file.name}: ${err instanceof Error ? err.message : "fallo"}`);
      } finally {
        setUploading((prev) => prev.filter((u) => u.tempId !== upload.tempId));
      }
    }
    if (created.length > 0) {
      setAttachments((prev) => [...created, ...prev]);
    }
    if (failures.length > 0) {
      setError(failures.join(" · "));
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (readOnly) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      upload(e.dataTransfer.files);
    }
  };

  const handleDelete = async (att: Attachment) => {
    if (!confirm(`¿Borrar "${att.filename}"?`)) return;
    try {
      await api(`/attachments/${att.id}`, { method: "DELETE" });
      setAttachments((prev) => prev.filter((a) => a.id !== att.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al borrar");
    }
  };

  const triggerPicker = () => fileInputRef.current?.click();

  return (
    <div
      className={`${styles.container} ${dragOver ? styles.dragOver : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!readOnly) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {!readOnly && (
        <div className={styles.dropZone}>
          <span>
            <strong>{hint ?? "Adjuntar archivos"}</strong> · arrastra aquí o
          </span>
          <button
            type="button"
            className={styles.uploadBtn}
            onClick={triggerPicker}
          >
            + Seleccionar
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_TYPES}
            className={styles.hidden}
            onChange={(e) => {
              if (e.target.files) upload(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      {(attachments.length > 0 || uploading.length > 0) ? (
        <ul className={styles.list}>
          {attachments.map((att) => (
            <li key={att.id} className={styles.row}>
              <div className={styles.left}>
                <span className={styles.icon}>{iconFor(att.mime_type)}</span>
                <span className={styles.fname} title={att.filename}>
                  {att.filename}
                </span>
                <span className={styles.size}>{formatSize(att.size_bytes)}</span>
              </div>
              <div className={styles.actions}>
                <a
                  className={styles.iconBtn}
                  href={`${API_URL}/attachments/${att.id}/download`}
                  onClick={(e) => {
                    // The /download endpoint requires a Bearer token, but
                    // <a href> can't carry headers. Fetch the redirect URL
                    // ourselves with the token and follow it client-side.
                    e.preventDefault();
                    openSignedUrl(att.id);
                  }}
                >
                  Ver
                </a>
                {!readOnly && (
                  <button
                    type="button"
                    className={`${styles.iconBtn} ${styles.danger}`}
                    onClick={() => handleDelete(att)}
                  >
                    Borrar
                  </button>
                )}
              </div>
            </li>
          ))}
          {uploading.map((u) => (
            <li key={u.tempId} className={`${styles.row} ${styles.uploading}`}>
              <div className={styles.left}>
                <span className={styles.icon}>⬆️</span>
                <span className={styles.fname}>{u.filename}</span>
                <span className={styles.size}>Subiendo… {formatSize(u.size)}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        loaded && <div className={styles.empty}>Sin archivos adjuntos.</div>
      )}
    </div>
  );
}

async function openSignedUrl(attachmentId: string) {
  const token = getToken();
  const res = await fetch(`${API_URL}/attachments/${attachmentId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    redirect: "manual",
  });
  // The backend returns 302 with a Location header. With redirect:'manual'
  // some browsers expose status 0 / opaqueredirect; Location may not be
  // readable cross-origin. Easiest path: let the browser follow normally,
  // but auth fails because Bearer isn't included. Instead we ask the API
  // for the URL directly via a Range-fetch and inspect.
  // Workaround: use redirect:'follow' and rely on the browser to handle it.
  // Safari/Chrome will keep following without re-sending the Authorization
  // header on the cross-origin redirect, which is what we want.
  if (res.status === 0 || res.type === "opaqueredirect") {
    // Fallback: re-issue with redirect 'follow' and open the final URL.
    const followed = await fetch(`${API_URL}/attachments/${attachmentId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      redirect: "follow",
    });
    window.open(followed.url, "_blank", "noopener,noreferrer");
    return;
  }
  if (res.ok || res.redirected) {
    window.open(res.url, "_blank", "noopener,noreferrer");
    return;
  }
  alert(`Error al descargar (${res.status})`);
}
