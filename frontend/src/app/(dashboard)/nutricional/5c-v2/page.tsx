"use client";

import React, { useState, useRef } from "react";
import { Download, UploadCloud, FileText, CheckCircle, Database } from "lucide-react";
import styles from "./page.module.css";

export default function Nutricional5CV2Page() {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Mock data for preview after upload
  const mockPreviewData = [
    { nombre: "Julián Álvarez", peso: 72.5, altura: 170, pliegues: 61, masaAdiposa: 12.4 },
    { nombre: "Lionel Messi", peso: 72.0, altura: 170, pliegues: 58, masaAdiposa: 11.8 },
    { nombre: "Emiliano Martínez", peso: 88.0, altura: 195, pliegues: 75, masaAdiposa: 14.2 },
  ];

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  const handleFile = (uploadedFile: File) => {
    setFile(uploadedFile);
    // Simulate processing time
    setTimeout(() => {
      setShowPreview(true);
    }, 800);
  };

  const triggerSelect = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Nutricional - 5C Version 2</h1>
        <p className={styles.subtitle}>Carga masiva de mediciones antropométricas (Plantel Completo)</p>
      </header>

      <div className={styles.card}>
        <div className={styles.actionGrid}>
          
          <div className={styles.downloadSection}>
            <h2 className={styles.sectionTitle}>
              <Download size={20} /> 1. Descargar Plantilla
            </h2>
            <p className={styles.sectionDescription}>
              Descarga la plantilla oficial en formato Excel (XLSX). Contiene las columnas exactas requeridas para calcular el modelo de 5 componentes estandarizado para todos los jugadores.
            </p>
            <button className={styles.btnDownload} onClick={(e) => { e.preventDefault(); alert("En un entorno real, esto descargará 'plantilla_5c.xlsx'"); }}>
              <FileText size={18} />
              Descargar Plantilla Vacía
            </button>
          </div>

          <div className={styles.uploadSection}>
            <h2 className={styles.sectionTitle}>
              <Database size={20} /> 2. Cargar Datos
            </h2>
            <p className={styles.sectionDescription}>
              Sube la plantilla completada. El sistema procesará las filas e importará automáticamente las mediciones y calculará las 5 masas para cada jugador.
            </p>
            
            <input 
              ref={fileInputRef}
              type="file" 
              className={styles.fileInput} 
              accept=".csv, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel"
              onChange={handleChange}
            />

            <div 
              className={`${styles.dropzone} ${dragActive ? styles.dropzoneActive : ""} ${file ? styles.uploadSuccess : ""}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={triggerSelect}
            >
              {file ? (
                <>
                  <CheckCircle size={32} className={styles.successIcon} />
                  <p className={styles.dropzoneText}><strong>{file.name}</strong> cargado con éxito</p>
                  <p className={styles.dropzoneSubtext}>Haz clic para reemplazar el archivo</p>
                </>
              ) : (
                <>
                  <UploadCloud size={32} className={styles.uploadIcon} />
                  <p className={styles.dropzoneText}>Haz clic aquí o arrastra tu archivo Excel</p>
                  <p className={styles.dropzoneSubtext}>Soporta .XLSX o .CSV hasta 10MB</p>
                </>
              )}
            </div>
          </div>

        </div>

        {showPreview && (
          <div className={styles.previewSection}>
            <h2 className={styles.sectionTitle}>Vista Previa de Importación</h2>
            <p className={styles.sectionDescription}>Valida que los cálculos preliminares sean correctos antes de guardar en la base de datos.</p>
            
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.th}>Jugador</th>
                    <th className={styles.th}>Peso (kg)</th>
                    <th className={styles.th}>Altura (cm)</th>
                    <th className={styles.th}>Σ Pliegues</th>
                    <th className={styles.th}>Masa Adiposa Est. (kg)</th>
                  </tr>
                </thead>
                <tbody>
                  {mockPreviewData.map((row, idx) => (
                    <tr key={idx} className={styles.tr}>
                      <td className={styles.td}><strong>{row.nombre}</strong></td>
                      <td className={styles.td}>{row.peso}</td>
                      <td className={styles.td}>{row.altura}</td>
                      <td className={styles.td}>{row.pliegues} mm</td>
                      <td className={styles.td}>{row.masaAdiposa} kg</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button className={styles.btnPrimary}>
              Confirmar e Importar Datos
            </button>
            <div style={{ clear: 'both' }}></div>
          </div>
        )}
      </div>
    </div>
  );
}
