import React from 'react';
import { 
  ChevronDown, Calendar, LineChart as LineChartIcon, Activity, Variable,
  TrendingUp, TrendingDown, AlertTriangle 
} from 'lucide-react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip,
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis 
} from 'recharts';
import styles from './ProfilePerformance.module.css';
import CollapsibleSection from '@/components/common/CollapsibleSection/CollapsibleSection';

const lineData = [
  { date: '08-11', val: 9000 }, { date: '08-18', val: 12000 },
  { date: '08-25', val: 11000 }, { date: '08-28', val: 12500 },
  { date: '09-01', val: 12000 }, { date: '09-08', val: 11000 },
  { date: '09-15', val: 9000 }, { date: '09-24', val: 10500 },
  { date: '09-29', val: 8000 }, { date: '10-06', val: 5000 },
  { date: '10-09', val: 11500 }, { date: '10-13', val: 10000 },
  { date: '10-20', val: 12500 }, { date: '11-03', val: 11000 },
  { date: '11-10', val: 7000 }, { date: '11-20', val: 8000 },
  { date: '11-27', val: 11500 }, { date: '12-04', val: 5000 },
  { date: '12-11', val: 10500 }, { date: '12-18', val: 11000 }
];

const radarData = [
  { subject: 'V.Max', A: 120, B: 60, fullMark: 150 },
  { subject: 'HIAA', A: 98, B: 110, fullMark: 150 },
  { subject: 'HMLD', A: 86, B: 130, fullMark: 150 },
  { subject: 'Acc/Dec', A: 99, B: 80, fullMark: 150 },
  { subject: 'Sprint', A: 85, B: 90, fullMark: 150 },
  { subject: 'PLoad', A: 65, B: 85, fullMark: 150 },
  { subject: 'Distancia', A: 130, B: 100, fullMark: 150 },
];

export default function ProfilePerformance() {
  return (
    <div className={styles.container}>
      
      {/* Top Section */}
      <div>
        <div className={styles.topSectionTitle}>VARIABLES - ÚLTIMO PARTIDO</div>
        <div className={styles.topRow}>
          
          <div className={styles.metricsGrid}>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>DISTANCIA TOTAL</div>
              <div className={styles.metricValue}>11.798 <span className={styles.metricUnit}>m</span></div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 2.3% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>V.MAX 85-95</div>
              <div className={styles.metricValue}>3</div>
              <div className={`${styles.metricChange} ${styles.changeDown}`}>
                <TrendingDown size={12} /> 76.9% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>HIAA</div>
              <div className={styles.metricValue}>274</div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 12.3% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>HMLD</div>
              <div className={styles.metricValue}>3.173 <span className={styles.metricUnit}>m</span></div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 8.2% vs anterior
              </div>
            </div>

            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>ACC/DEC &gt;3</div>
              <div className={styles.metricValue}>214</div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 3.8% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>HSR &gt;19.8</div>
              <div className={styles.metricValue}>1.423 <span className={styles.metricUnit}>m</span></div>
              <div className={`${styles.metricChange} ${styles.changeDown}`}>
                <TrendingDown size={12} /> 6.3% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>SPRINT &gt;25</div>
              <div className={styles.metricValue}>93 <span className={styles.metricUnit}>m</span></div>
              <div className={`${styles.metricChange} ${styles.changeDown}`}>
                <TrendingDown size={12} /> 33.1% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>V.MAX KM/H</div>
              <div className={styles.metricValue}>52,2 <span className={styles.metricUnit}>km/h</span></div>
              <div className={`${styles.metricChange} ${styles.changeDown}`}>
                <TrendingDown size={12} /> 0.6% vs anterior
              </div>
            </div>

            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>M/MIN</div>
              <div className={styles.metricValue}>245 <span className={styles.metricUnit}>m/min</span></div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 6.1% vs anterior
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricTitle}>PLAYER LOAD</div>
              <div className={styles.metricValue}>190 <span className={styles.metricUnit}>AU</span></div>
              <div className={`${styles.metricChange} ${styles.changeUp}`}>
                <TrendingUp size={12} /> 0.5% vs anterior
              </div>
            </div>
            {/* 2 empty spots in the 4-column grid for row 3, which is fine it creates negative space */}
          </div>

          <div className={styles.chartCard} style={{ padding: 16 }}>
            <div className={styles.chartHeader} style={{ marginBottom: 12 }}>
              <div className={styles.chartTitle} style={{ fontSize: '0.75rem' }}>Evolución variable</div>
              <div className={styles.selectGroup}>
                <button className={styles.selectInput}>
                  Distancia total (m) <ChevronDown size={12} />
                </button>
                <button className={styles.selectInput}>
                  <Calendar size={12} /> 01-01-2025 - 01-10-2025 <ChevronDown size={12} />
                </button>
              </div>
            </div>
            <div style={{ height: 200, width: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={lineData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#9ca3af' }} axisLine={false} tickLine={false} dy={8} />
                  <YAxis tick={{ fontSize: 9, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="val" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: '#ef4444', strokeWidth: 1, stroke: '#3b82f6' }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>

      {/* Middle Section: Carga de Entrenamiento */}
      <CollapsibleSection 
        title="Carga de Entrenamiento" 
        icon={Activity}
        controls={
          <>
            <button className={styles.selectInput}>
              Distancia total (m) <ChevronDown size={12} />
            </button>
            <button className={styles.selectInput}>
              2025-05-25 <ChevronDown size={12} />
            </button>
            <button className={styles.selectInput}>
              x2 días <ChevronDown size={12} />
            </button>
            <button className={styles.btnPrimary}>Actualizar</button>
          </>
        }
      >
        <div className={styles.emptyChartBox}>
          <div className={styles.emptyChartLabel}>
            Partido: 2025-05-25 - Variable: Distancia total
          </div>
        </div>
      </CollapsibleSection>

      {/* Bottom Section: Carga Diaria */}
      <CollapsibleSection
        title="Carga Diaria"
        icon={LineChartIcon}
        controls={
          <>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#4b5563'}}>
              Fecha A: 27-03-2025 <Calendar size={12} style={{marginRight:8, marginLeft:4}} />
              Fecha B: 31-05-2025 <Calendar size={12} style={{marginRight:8, marginLeft:4}} />
            </div>
            <button className={styles.btnPrimary}>Comparar</button>
          </>
        }
      >
        <div className={styles.dailyLoadGrid}>
          <div>
            <div className={styles.dateOptions}>
              <div>
                <span className={styles.dateTag}>
                  <LineChartIcon size={14} /> Fecha A: 2025-03-27 - Partido
                </span>
              </div>
              <div>
                <span className={styles.dateTag}>
                  <LineChartIcon size={14} /> Fecha B: 2025-05-31 - Partido
                </span>
              </div>
            </div>

            <div className={styles.alertBox}>
              <AlertTriangle size={16} /> V.Max diferencia del 82% entre fechas
            </div>
            <div className={styles.alertBox}>
              <AlertTriangle size={16} /> Sprint diferencia del 70% entre fechas
            </div>
          </div>

          <div className={styles.radarArea}>
            <div className={styles.radarLegend}>
              <div className={styles.legendItem}>
                <div style={{ width: 10, height: 10, border: '2px solid #3b82f6', backgroundColor: 'transparent' }}></div>
                Fecha A (2025-03-27)
              </div>
              <div className={styles.legendItem}>
                <div style={{ width: 10, height: 10, border: '2px solid #10b981', backgroundColor: '#d1fae5' }}></div>
                Fecha B (2025-05-31)
              </div>
            </div>
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="80%" data={radarData}>
                <PolarGrid stroke="#e5e7eb" />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: '#4b5563', fontWeight: 600 }} />
                <PolarRadiusAxis angle={30} domain={[0, 150]} tick={false} axisLine={false} />
                <Radar name="Fecha A" dataKey="A" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.1} strokeWidth={2} />
                <Radar name="Fecha B" dataKey="B" stroke="#10b981" fill="#10b981" fillOpacity={0.4} strokeWidth={2} />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </CollapsibleSection>

    </div>
  );
}
