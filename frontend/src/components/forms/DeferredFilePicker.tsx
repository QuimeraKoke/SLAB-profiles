"use client";

import React, { useRef, useState } from "react";

import {
  ACCEPTED_FILE_TYPES,
  formatSize,
  iconFor,
} from "@/components/ui/AttachmentList/utils";
import styles from "./DeferredFilePicker.module.css";

interface Props {
  /** Files queued client-side; uploaded later by the parent on form submit. */
  value: File[];
  onChange: (files: File[]) => void;
  /** Optional helper text shown above the dropzone. */
  hint?: string;
  /** Defaults to true; pass false to restrict to a single file at a time. */
  multiple?: boolean;
  /** Override the file-input accept= filter. Defaults to the platform allowlist. */
  accept?: string;
  disabled?: boolean;
}

/**
 * A file picker that holds its selection in state without uploading.
 *
 * Used by `DynamicUploader` so the doctor can drop X-rays / MRIs while still
 * filling the diagnosis fields. The parent uploads the queued files to
 * `/api/attachments` after the corresponding `ExamResult` is created.
 */
export default function DeferredFilePicker({
  value,
  onChange,
  hint,
  multiple = true,
  accept = ACCEPTED_FILE_TYPES,
  disabled = false,
}: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (files: FileList | File[]) => {
    const incoming = Array.from(files);
    if (incoming.length === 0) return;
    if (multiple) {
      onChange([...value, ...incoming]);
    } else {
      // Single-file mode: replace.
      onChange([incoming[0]]);
    }
  };

  const removeAt = (idx: number) => {
    onChange(value.filter((_, i) => i !== idx));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
    }
  };

  return (
    <div
      className={`${styles.container} ${dragOver ? styles.dragOver : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className={styles.dropZone}>
        <span>
          <strong>{hint ?? "Adjuntar archivos"}</strong> · arrastra aquí o
        </span>
        <button
          type="button"
          className={styles.uploadBtn}
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          + Seleccionar
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple={multiple}
          accept={accept}
          className={styles.hidden}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
          disabled={disabled}
        />
      </div>

      {value.length > 0 && (
        <ul className={styles.list}>
          {value.map((file, idx) => (
            <li key={`${idx}-${file.name}`} className={styles.row}>
              <div className={styles.left}>
                <span className={styles.icon}>{iconFor(file.type)}</span>
                <span className={styles.fname} title={file.name}>
                  {file.name}
                </span>
                <span className={styles.size}>{formatSize(file.size)}</span>
              </div>
              {!disabled && (
                <button
                  type="button"
                  className={styles.removeBtn}
                  aria-label={`Quitar ${file.name}`}
                  onClick={() => removeAt(idx)}
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
