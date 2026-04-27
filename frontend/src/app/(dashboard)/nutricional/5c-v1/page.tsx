"use client";

import React, { useState } from "react";
import { User, TrendingUp, Save } from "lucide-react";
import styles from "./page.module.css";

// Formulas for the 5-way fractionation model (Kerr 1988 / Phantom stratagem)
// These constants estimate the mass of the 5 tissues.
const calculate5C = (data: any) => {
  const height = parseFloat(data.altura) || 0;
  const weight = parseFloat(data.peso) || 0;

  if (!height || !weight) return null;

  // Validate all necessary inputs are somewhat present
  const sumSkinfolds = 
    (parseFloat(data.pliegues.triceps) || 0) + 
    (parseFloat(data.pliegues.subescapular) || 0) + 
    (parseFloat(data.pliegues.supraespinal) || 0) + 
    (parseFloat(data.pliegues.abdominal) || 0) + 
    (parseFloat(data.pliegues.muslo) || 0) + 
    (parseFloat(data.pliegues.pantorrilla) || 0);

  // Phantom constants (P and S) approximations for Kerr
  const hScale = 170.18 / height;

  // 1. Masa Adiposa (Adipose Mass) - relies on sum of 6 skinfolds
  const zAdiposa = ((sumSkinfolds * hScale) - 116.41) / 34.79;
  const adiposa = (zAdiposa * 5.85 + 25.6) / Math.pow(hScale, 3);

  // 2. Masa Muscular (Muscle Mass) - uses corrected girths
  // Corrected girths = Girth - (Pi * Skinfold / 10)
  const cgArm = (parseFloat(data.perimetros.brazo) || 0) - (Math.PI * (parseFloat(data.pliegues.triceps) || 0) / 10);
  const cgCalf = (parseFloat(data.perimetros.pantorrilla) || 0) - (Math.PI * (parseFloat(data.pliegues.pantorrilla) || 0) / 10);
  const cgThigh = (parseFloat(data.perimetros.muslo) || 0) - (Math.PI * (parseFloat(data.pliegues.muslo) || 0) / 10);
  const cgForearm = parseFloat(data.perimetros.antebrazo) || 0; // Not usually corrected
  
  const sumGirths = cgArm + cgForearm + cgThigh + cgCalf;
  const zMuscular = ((sumGirths * hScale) - 207.21) / 22.66; // Phantom values for sum of 4 girths
  const muscular = (zMuscular * 5.4 + 25.4) / Math.pow(hScale, 3); // Approximation constants

  // 3. Masa Ósea (Bone Mass) - uses bone breadths
  const sumBreadths = (parseFloat(data.diametros.humero) || 0) + (parseFloat(data.diametros.fémur) || 0);
  const zOsea = ((sumBreadths * hScale) - 16.36) / 1.48; // Approximation for humerus + femur breadth
  const osea = (zOsea * 1.34 + 6.4) / Math.pow(hScale, 3);

  // 4. Masa Residual (Residual/Organs) - uses weight and height parameters (usually chest depth/breadth, but we estimate)
  // Simplified derivation: Residual is often ~24% of phantom mass, adjusted.
  // Using generic Kerr residual approximation lacking transverse chest data:
  const residual = (weight * 0.24); 

  // 5. Masa Piel (Skin Mass) - relies on surface area
  const surfaceArea = (71.84 * Math.pow(weight, 0.425) * Math.pow(height, 0.725)) / 10000; // Du Bois formula
  const piel = surfaceArea * 2.07; // 2.07 kg/m2 skin constant

  // Structured Mass (Sum of parts might not exactly equal total weight due to fractionation)
  const totalCalculatedWeight = adiposa + muscular + osea + residual + piel;
  
  // Normalize to 100% of ACTUAL weight if desired, but classical 5C shows structural weight diff.
  // We will display the exact raw mass but the % based on Actual Weight.
  return {
    adiposa: Math.max(0, adiposa),
    muscular: Math.max(0, muscular),
    osea: Math.max(0, osea),
    residual: Math.max(0, residual),
    piel: Math.max(0, piel),
    totalCalculated: totalCalculatedWeight
  };
};

export default function Nutricional5CV1Page() {
  const initialData = {
    peso: "72.5",
    altura: "170",
    pliegues: {
      triceps: "3", subescapular: "3", biceps: "4", suprailiaco: "5",
      supraespinal: "4", abdominal: "4", muslo: "3", pantorrilla: "4"
    },
    perimetros: { brazo: "4", antebrazo: "5", muslo: "5", pantorrilla: "3" },
    diametros: { humero: "3", fémur: "4" }
  };

  const [formData, setFormData] = useState(initialData);
  const [activeResults, setActiveResults] = useState<any>(calculate5C(initialData));

  const handleInputChange = (category: string, field: string, value: string) => {
    // Only allow numbers and decimals
    const sanitizedValue = value.replace(/[^0-9.]/g, '');
    
    if (category === 'main') {
      setFormData(prev => ({ ...prev, [field]: sanitizedValue }));
    } else {
      setFormData(prev => ({
        ...prev,
        [category]: {
          ...(prev as any)[category],
          [field]: sanitizedValue
        }
      }));
    }
  };

  const handleCalculate = (e: React.MouseEvent) => {
    e.preventDefault();
    setActiveResults(calculate5C(formData));
  };

  const getCompData = (val: number | undefined) => {
    const weight = parseFloat(formData.peso) || 0;
    if (!activeResults || val === undefined || isNaN(val) || !weight) return { value: "0", percent: "0", numVal: 0 };
    return {
      value: val.toFixed(1),
      percent: ((val / weight) * 100).toFixed(1),
      numVal: val
    };
  };

  const adiposaData = getCompData(activeResults?.adiposa);
  const muscularData = getCompData(activeResults?.muscular);
  const residualData = getCompData(activeResults?.residual);
  const oseaData = getCompData(activeResults?.osea);
  const pielData = getCompData(activeResults?.piel);

  const components = [
    { label: "Masa Adiposa", ...adiposaData, color: "#f97316" },
    { label: "Masa Muscular", ...muscularData, color: "#ef4444" },
    { label: "Masa Residual", ...residualData, color: "#3b82f6" },
    { label: "Masa Ósea", ...oseaData, color: "#6b7280" },
    { label: "Masa Piel", ...pielData, color: "#f97316" },
  ];

  return (
    <div className={styles.container}>
      <div className={`${styles.card} ${styles.topSection}`}>
        <div className={styles.selectWrapper}>
          <label className={styles.label}>Seleccionar Jugador</label>
          <select className={styles.select} defaultValue="Julian">
            <option value="Julian">Julián Álvarez - DC</option>
            <option value="Lionel">Lionel Messi - ED</option>
            <option value="Emiliano">Emiliano Martínez - POR</option>
          </select>
        </div>
      </div>

      <div className={styles.mainGrid}>
        <div className={styles.formColumn}>
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>
              <User size={18} /> Datos Corporales Esenciales
            </h2>
            <div className={styles.inputGrid2}>
              <div className={styles.inputGroup}>
                <label className={styles.label}>Peso Corporal Total (kg)</label>
                <input 
                  type="text" 
                  className={styles.input} 
                  placeholder="72.5" 
                  value={formData.peso}
                  onChange={(e) => handleInputChange('main', 'peso', e.target.value)}
                />
              </div>
              <div className={styles.inputGroup}>
                <label className={styles.label}>Altura (cm)</label>
                <input 
                  type="text" 
                  className={styles.input} 
                  placeholder="170" 
                  value={formData.altura}
                  onChange={(e) => handleInputChange('main', 'altura', e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Pliegues Cutáneos (mm)</h2>
            <div className={styles.inputGrid4}>
              {[
                { id: 'triceps', label: 'Tríceps' },
                { id: 'subescapular', label: 'Subescapular' },
                { id: 'biceps', label: 'Bíceps' },
                { id: 'suprailiaco', label: 'Suprailiaco' },
                { id: 'supraespinal', label: 'Supraespinal' },
                { id: 'abdominal', label: 'Abdominal' },
                { id: 'muslo', label: 'Muslo' },
                { id: 'pantorrilla', label: 'Pantorrilla' },
              ].map(field => (
                <div className={styles.inputGroup} key={field.id}>
                  <label className={styles.label}>{field.label}</label>
                  <input 
                    type="text" 
                    className={styles.input} 
                    value={(formData.pliegues as any)[field.id]}
                    onChange={(e) => handleInputChange('pliegues', field.id, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Perímetros/Circunferencias (cm)</h2>
            <div className={styles.inputGrid4}>
              {[
                { id: 'brazo', label: 'Brazo Relajado' },
                { id: 'antebrazo', label: 'Antebrazo' },
                { id: 'muslo', label: 'Muslo' },
                { id: 'pantorrilla', label: 'Pantorrilla' },
              ].map(field => (
                <div className={styles.inputGroup} key={field.id}>
                  <label className={styles.label}>{field.label}</label>
                  <input 
                    type="text" 
                    className={styles.input} 
                    value={(formData.perimetros as any)[field.id]}
                    onChange={(e) => handleInputChange('perimetros', field.id, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Diámetros Óseos (cm)</h2>
            <div className={styles.inputGrid2}>
              {[
                { id: 'humero', label: 'Biepicondíleo Húmero (Codo)' },
                { id: 'fémur', label: 'Bifemoral (Rodilla)' },
              ].map(field => (
                <div className={styles.inputGroup} key={field.id}>
                  <label className={styles.label}>{field.label}</label>
                  <input 
                    type="text" 
                    className={styles.input} 
                    value={(formData.diametros as any)[field.id]}
                    onChange={(e) => handleInputChange('diametros', field.id, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className={styles.buttonGroup}>
            <button className={styles.btnPrimary} onClick={handleCalculate}>
              <TrendingUp size={18} /> Calcular Componentes
            </button>
            <button className={styles.btnSecondary}>
              <Save size={18} /> Guardar Evaluación
            </button>
          </div>
        </div>

        <div className={styles.reportColumn}>
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Reporte de 5 Componentes</h2>
            <div className={styles.progressContainer}>
              {components.map((comp, idx) => (
                <div className={styles.progressSection} key={idx}>
                  <div className={styles.progressHeader}>
                    <span>{comp.label}</span>
                    <span className={styles.progressValue}>
                      {comp.value} kg ({comp.percent}%)
                    </span>
                  </div>
                  <div className={styles.progressTrack}>
                    <div 
                      className={styles.progressFill} 
                      style={{ 
                        width: comp.percent !== 'NaN' ? `${Math.min(100, Math.max(0, parseFloat(comp.percent)))}%` : '0%',
                        backgroundColor: comp.color 
                      }} 
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Distribución Visual</h2>
            <div className={styles.distributionChart}>
              {components.map((comp, idx) => (
                <div className={styles.distBarCol} key={idx}>
                  <div className={styles.distValue}>{comp.value} {comp.value !== 'NaN' && 'kg'}</div>
                  <div className={styles.distTrack}>
                    <div 
                      className={styles.distFill} 
                      style={{ 
                        height: comp.percent !== 'NaN' ? `${Math.max(2, parseFloat(comp.percent))}%` : '2px', 
                        backgroundColor: comp.color 
                      }} 
                    />
                  </div>
                  <div className={styles.distLabel}>{comp.label.replace('Masa ', '')}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
