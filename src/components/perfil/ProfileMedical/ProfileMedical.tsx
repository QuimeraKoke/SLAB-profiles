import React from 'react';
import { Plus, CheckSquare, Search, ChevronDown, Calendar, Activity } from 'lucide-react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip, AreaChart, Area,
  BarChart, Bar, Cell
} from 'recharts';
import styles from './ProfileMedical.module.css';
import CollapsibleSection from '@/components/common/CollapsibleSection/CollapsibleSection';

const injuries = [
  { zona: 'Pierna / Tendón de Aquiles', musculo: 'Derecho', tipo: 'Lesión tendón / Rotura', causa: 'Sobrecarga', rec: '-', exp: 'Entrenamiento', plesion: '23-12-2024', palta: '17-01-2025', dias: 28, estado: 'ALTA' },
  { zona: 'Muslo', musculo: 'Izquierdo', tipo: 'Rotura muscular / Desgarro', causa: 'Sobrecarga', rec: '-', exp: 'Partido', plesion: '03-05-2025', palta: '13-06-2025', dias: 18, estado: 'ALTA' },
  { zona: 'Pierna / Tendón de Aquiles', musculo: 'Izquierdo', tipo: 'Rotura muscular / Desgarro', causa: 'Sobrecarga', rec: '-', exp: 'Partido', plesion: '15-06-2025', palta: '30-06-2025', dias: 15, estado: 'ALTA' },
  { zona: 'Pierna / Tendón de Aquiles', musculo: 'Izquierdo', tipo: 'Rotura muscular / Desgarro', causa: 'Sobrecarga', rec: '✓', exp: 'Partido', plesion: '17-07-2025', palta: '07-08-2025', dias: 21, estado: 'ALTA' },
  { zona: 'Muslo', musculo: 'Derecho', tipo: 'Rotura muscular / Desgarro', causa: 'Sobrecarga', rec: '-', exp: 'Partido', plesion: '05-09-2026', palta: '-', dias: '-', estado: 'LESIONADO' },
];

const examData = [
  { date: '08-19', ck: 950 },
  { date: '08-25', ck: 550 },
  { date: '08-31', ck: 580 },
  { date: '09-02', ck: 900 },
  { date: '09-07', ck: 250 },
  { date: '09-11', ck: 202 },
];

const wellnessData = [
  { name: 'Sueño', val: 3.89, color: '#60a5fa' },
  { name: 'Estrés', val: 3.74, color: '#fbbf24' },
  { name: 'Fatiga', val: 3.94, color: '#f87171' },
  { name: 'Dolor Muscular', val: 3.98, color: '#a78bfa' },
];

// Placeholder component for BodyMap using pure CSS blocks
const BodyMapPlaceholder = () => {
  return (
    <div style={{ position: 'relative', width: 140, height: 320, margin: '0 auto' }}>
      {/* Head */}
      <div style={{ position: 'absolute', top: 0, left: 50, width: 40, height: 40, borderRadius: '50%', backgroundColor: '#86efac' }} />
      {/* Torso */}
      <div style={{ position: 'absolute', top: 45, left: 40, width: 60, height: 90, backgroundColor: '#86efac' }} />
      {/* Arms top */}
      <div style={{ position: 'absolute', top: 45, left: 20, width: 15, height: 60, backgroundColor: '#86efac' }} />
      <div style={{ position: 'absolute', top: 45, right: 20, width: 15, height: 60, backgroundColor: '#86efac' }} />
      {/* Arms bottom */}
      <div style={{ position: 'absolute', top: 110, left: 20, width: 15, height: 50, backgroundColor: '#86efac' }} />
      <div style={{ position: 'absolute', top: 110, right: 20, width: 15, height: 50, backgroundColor: '#86efac' }} />
      {/* Thighs */}
      <div style={{ position: 'absolute', top: 140, left: 40, width: 25, height: 70, backgroundColor: '#fde047' }} />
      <div style={{ position: 'absolute', top: 140, right: 40, width: 25, height: 70, backgroundColor: '#fde047' }} /> {/* Right thigh has 1 lesion */}
      {/* Calves */}
      <div style={{ position: 'absolute', top: 215, left: 40, width: 25, height: 70, backgroundColor: '#fca5a5' }} /> {/* Left calf has 2+ lesiones */}
      <div style={{ position: 'absolute', top: 215, right: 40, width: 25, height: 70, backgroundColor: '#fde047' }} />
      {/* Feet */}
      <div style={{ position: 'absolute', top: 290, left: 40, width: 25, height: 15, backgroundColor: '#86efac' }} />
      <div style={{ position: 'absolute', top: 290, right: 40, width: 25, height: 15, backgroundColor: '#86efac' }} />
    </div>
  );
};

export default function ProfileMedical() {
  return (
    <div className={styles.container}>
      
      {/* Top Row */}
      <div className={styles.topRow}>
        <div className={styles.card}>
          <div className={styles.sectionTitle}>
            <Plus size={16} /> HISTORIAL DE LESIONES
          </div>
          <div className={styles.tableWrapper}>
            <table className={styles.injuryTable}>
              <thead>
                <tr>
                  <th>ZONA</th>
                  <th>MÚSCULO</th>
                  <th>TIPO</th>
                  <th>CAUSA</th>
                  <th>RECURRENCIA</th>
                  <th>EXPOSICIÓN</th>
                  <th>P. LESIÓN</th>
                  <th>P. ALTA</th>
                  <th>DÍAS</th>
                  <th>ESTADO</th>
                </tr>
              </thead>
              <tbody>
                {injuries.map((inj, idx) => (
                  <tr key={idx}>
                    <td className={styles.zonedCell}>{inj.zona}</td>
                    <td>{inj.musculo}</td>
                    <td>{inj.tipo}</td>
                    <td>{inj.causa}</td>
                    <td>{inj.rec}</td>
                    <td>{inj.exp}</td>
                    <td>{inj.plesion}</td>
                    <td>{inj.palta}</td>
                    <td style={{fontWeight: 700, color: '#111827'}}>{inj.dias}</td>
                    <td>
                      <span className={`${styles.statusPill} ${inj.estado === 'ALTA' ? styles.statusAlta : styles.statusLesionado}`}>
                        {inj.estado}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.sectionTitle}>
            MAPA DE LESIONES
          </div>
          <div className={styles.bodyMapContainer}>
            <div className={styles.bodyMapLegend}>
              <div className={styles.legendIndicator}>
                <div className={`${styles.legendBox} ${styles.boxGreen}`}></div> Sin lesión
              </div>
              <div className={styles.legendIndicator}>
                <div className={`${styles.legendBox} ${styles.boxYellow}`}></div> 1 lesión
              </div>
              <div className={styles.legendIndicator}>
                <div className={`${styles.legendBox} ${styles.boxRed}`}></div> 2+ lesiones
              </div>
            </div>
            
            <BodyMapPlaceholder />

          </div>
        </div>
      </div>

      {/* Middle Row: Exámenes */}
      <CollapsibleSection title="Exámenes" icon={CheckSquare}>
        <div className={styles.splitRow}>
          <div>
            <div className={styles.leftColumnTitle}>ÚLTIMO RESULTADO</div>
            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div>
                  <div className={styles.metricName}>Densidad Urinaria</div>
                  <div className={styles.metricSub}>2024-09-08 · mg/dL</div>
                </div>
                <div className={styles.metricValBlue}>1.006</div>
              </div>
            </div>
            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div>
                  <div className={styles.metricName}>CK</div>
                  <div className={styles.metricSub}>2024-09-11 · MO+2</div>
                </div>
                <div className={styles.metricValBlue}>202</div>
              </div>
            </div>
          </div>
          
          <div>
            <div className={styles.chartHeader}>
              <div className={styles.metricName}>Evolución</div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button className={styles.selectInput}>
                  CK <ChevronDown size={14} />
                </button>
                <button className={styles.selectInput}>
                  <Calendar size={14} /> 01-08-2024 - 30-09-2024 <ChevronDown size={14} />
                </button>
              </div>
            </div>
            <div className={styles.chartContainer}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={examData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorCk" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} dy={10} />
                  <YAxis tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Area type="monotone" dataKey="ck" stroke="#3b82f6" fillOpacity={1} fill="url(#colorCk)" strokeWidth={2} activeDot={{ r: 6 }} dot={{ r: 4, fill: "#3b82f6", strokeWidth: 0 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* Bottom Row: Wellness */}
      <CollapsibleSection title="Wellness" icon={Search}>
        <div className={styles.splitRow}>
          <div>
            <div className={styles.leftColumnTitle}>PROMEDIOS GENERALES</div>
            
            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div className={styles.metricName}>Sueño</div>
                <div className={styles.metricValNormal}>3.89</div>
              </div>
              <div className={styles.metricSub}>
                Últimos 3: 4, 4, 4 <span className={styles.metricDiff}>▲ 2% vs promedio</span>
              </div>
            </div>

            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div className={styles.metricName}>Estrés</div>
                <div className={styles.metricValNormal} style={{color: '#fbbf24'}}>3.74</div>
              </div>
              <div className={styles.metricSub}>
                Últimos 3: 4, 4, 4 <span className={styles.metricDiff}>▲ 7% vs promedio</span>
              </div>
            </div>

            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div className={styles.metricName}>Fatiga</div>
                <div className={styles.metricValNormal} style={{color: '#f87171'}}>3.94</div>
              </div>
              <div className={styles.metricSub}>
                Últimos 3: 4, 4, 4 <span className={styles.metricDiff}>▲ 2% vs promedio</span>
              </div>
            </div>

            <div className={styles.metricItem}>
              <div className={styles.metricValRow}>
                <div className={styles.metricName}>Dolor Muscular</div>
                <div className={styles.metricValNormal} style={{color: '#a78bfa'}}>3.98</div>
              </div>
              <div className={styles.metricSub}>
                Últimos 3: 4, 4, 4 <span className={styles.metricDiff}>▲ 1% vs promedio</span>
              </div>
            </div>

          </div>
          
          <div style={{ display: 'flex', alignItems: 'flex-end', height: 250 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={wellnessData} margin={{ top: 20, right: 30, left: -20, bottom: 5 }} barSize={100} barGap={20} barCategoryGap={30}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                <XAxis dataKey="name" tick={{fontSize: 10, fill: '#6b7280'}} axisLine={false} tickLine={false} dy={10} />
                <YAxis domain={[0, 7]} ticks={[0, 1, 2, 3, 4, 5, 6, 7]} tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} label={{ value: 'Escala 1-7', angle: -90, position: 'insideLeft', offset: 15, style: { fontSize: '10px', fill: '#9ca3af'} }} />
                <Tooltip cursor={{fill: 'transparent'}} />
                <Bar dataKey="val" radius={[4, 4, 4, 4]}>
                  {wellnessData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </CollapsibleSection>

    </div>
  );
}
