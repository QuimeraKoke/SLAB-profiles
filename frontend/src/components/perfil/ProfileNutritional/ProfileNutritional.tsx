import React, { useState } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip,
  PieChart, Pie, Cell,
  BarChart, Bar, Legend as RechartsLegend
} from 'recharts';
import { ChevronDown, PieChart as PieChartIcon, Activity, Edit3, Plus } from 'lucide-react';
import styles from './ProfileNutritional.module.css';
import CollapsibleSection from '@/components/common/CollapsibleSection/CollapsibleSection';

// Mock Data
const evoData = [
  { variable: 'Peso (kg)', v1: 69.80, v2: 68.25, d2: 'down', v3: 70.30, d3: 'up', v2d: 0.76, v3d: 2.05 },
  { variable: 'Estatura (cm)', v1: 172.20, v2: 172.20, d2: 'neutral', v3: 172.20, d3: 'neutral', v2d: 0, v3d: 0 },
  { variable: 'M. adiposa (kg)', v1: 11.41, v2: 11.87, d2: 'up', v3: 12.39, d3: 'up', v2d: 0.46, v3d: 0.52 },
  { variable: 'M. muscular (kg)', v1: 36.18, v2: 35.43, d2: 'down', v3: 36.24, d3: 'up', v2d: 0.75, v3d: 0.81 },
  { variable: 'M. ósea (kg)', v1: 8.70, v2: 8.57, d2: 'down', v3: 8.86, d3: 'up', v2d: 0.13, v3d: 0.29 },
  { variable: 'M. piel (kg)', v1: 3.76, v2: 3.69, d2: 'down', v3: 3.86, d3: 'up', v2d: 0.07, v3d: 0.17 },
  { variable: 'M. residual (kg)', v1: 8.95, v2: 8.68, d2: 'down', v3: 8.94, d3: 'up', v2d: 0.27, v3d: 0.26 },
  { variable: 'Suma 6 pl. (mm)', v1: 10.10, v2: 9.80, d2: 'down', v3: 6.80, d3: 'down', v2d: 0.30, v3d: 3.00 },
  { variable: 'Suma 8 pl. (mm)', v1: 39.80, v2: 33.50, d2: 'down', v3: 34.20, d3: 'up', v2d: 6.30, v3d: 0.70 },
];

const lineData = [
  { date: '08-08', val: 67.5 }, { date: '14-11', val: 69.2 },
  { date: '21-12', val: 69.4 }, { date: '11-02', val: 69.1 },
  { date: '25-04', val: 68.9 }, { date: '19-06', val: 69.8 },
  { date: '15-07', val: 69.0 }, { date: '07-09', val: 70.3 },
  { date: '12-11', val: 70.5 }
];

const PIE_COLORS = {
  muscular: '#3b82f6', // blue
  adiposa: '#f97316',  // orange
  osea: '#10b981',     // green
  residual: '#fbbf24', // yellow
  piel: '#8b5cf6'      // purple
};

const pieData1 = [
  { name: 'M. muscular', value: 51.6, color: PIE_COLORS.muscular },
  { name: 'M. adiposa', value: 17.6, color: PIE_COLORS.adiposa },
  { name: 'M. ósea', value: 12.6, color: PIE_COLORS.osea },
  { name: 'M. residual', value: 12.7, color: PIE_COLORS.residual },
  { name: 'M. piel', value: 5.5, color: PIE_COLORS.piel },
];

const barDataKg = [
  { date: '07-09', adiposa: 11.41, muscular: 36.18 },
  { date: '10-10', adiposa: 11.87, muscular: 35.43 },
  { date: '12-11', adiposa: 12.39, muscular: 36.24 },
];

const barDataPerc = [
  { date: '07-09', adiposa: 16.3, muscular: 51.8 },
  { date: '10-10', adiposa: 17.4, muscular: 51.9 },
  { date: '12-11', adiposa: 17.6, muscular: 51.6 },
];

export default function ProfileNutritional() {
  const [goals, setGoals] = useState([
    { id: 1, text: 'Mantener Composición Corporal', date: '08-08-2024', checked: false },
    { id: 2, text: 'Mantener Composición Corporal', date: '15-10-2024', checked: false },
    { id: 3, text: 'Mantener Composición Corporal', date: '16-11-2024', checked: false },
    { id: 4, text: 'Mantener Composición Corporal', date: '18-02-2025', checked: false },
    { id: 5, text: 'Mantener Composición Corporal', date: '18-03-2025', checked: false },
    { id: 6, text: 'Mantener Composición Corporal', date: '16-06-2025', checked: false },
    { id: 7, text: 'Mantener Composición Corporal', date: '10-08-2025', checked: false },
    { id: 8, text: 'Mantener Composición Corporal', date: '07-09-2025', checked: false },
    { id: 9, text: 'Mantener Composición Corporal', date: '10-10-2025', checked: false },
  ]);

  const [newGoalObj, setNewGoalObj] = useState('');
  const [newGoalComment, setNewGoalComment] = useState('');

  const handleAddGoal = () => {
    if (!newGoalObj.trim()) return;
    const now = new Date();
    const formattedDate = `${String(now.getDate()).padStart(2, '0')}-${String(now.getMonth()+1).padStart(2, '0')}-${now.getFullYear()}`;
    setGoals([...goals, {
      id: Date.now(),
      text: newGoalObj + (newGoalComment ? ` - ${newGoalComment}` : ''),
      date: formattedDate,
      checked: false
    }]);
    setNewGoalObj('');
    setNewGoalComment('');
  };

  const toggleGoal = (id: number) => {
    setGoals(goals.map(g => g.id === id ? { ...g, checked: !g.checked } : g));
  };

  const renderTrend = (val: number, trend: string) => {
    if (trend === 'up') return <span className={`${styles.changeIndicator} ${styles.upRed}`}>▲ {val.toFixed(2)}</span>;
    if (trend === 'down') return <span className={`${styles.changeIndicator} ${styles.downGreen}`}>▼ {val.toFixed(2)}</span>;
    return <span className={`${styles.changeIndicator} ${styles.neutral}`}>- 0</span>;
  };

  const PieLegend = () => (
    <div className={styles.pieLegend}>
      {pieData1.map((entry, index) => (
        <div key={index} className={styles.legendItem}>
          <span><span className={styles.legendColor} style={{ backgroundColor: entry.color }}></span> {entry.name}</span>
          <span>{entry.value}%</span>
        </div>
      ))}
    </div>
  );

  return (
    <div className={styles.container}>
      
      {/* Top Row */}
      <div className={styles.topRow}>
        <div className={styles.card}>
          <div className={styles.sectionTitle}>
            Evolución antropométrica — últimas 3 tomas
          </div>
          <div className={styles.tableWrapper}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>VARIABLE</th>
                  <th>07-09<br/>2025</th>
                  <th>10-10<br/>2025</th>
                  <th>12-11<br/>2025</th>
                </tr>
              </thead>
              <tbody>
                {evoData.map((row, idx) => (
                  <tr key={idx}>
                    <td className={styles.variableName}>{row.variable}</td>
                    <td>{row.v1.toFixed(2)}</td>
                    <td>{row.v2.toFixed(2)} {renderTrend(row.v2d, row.d2)}</td>
                    <td>{row.v3.toFixed(2)} {renderTrend(row.v3d, row.d3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.sectionTitle}>
            Evolución en el tiempo
            <button className={styles.selectInput}>
              Peso (kg) <ChevronDown size={14} />
            </button>
          </div>
          <div className={styles.chartContainer}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                <XAxis dataKey="date" tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} dy={10} />
                <YAxis domain={[67, 70.5]} tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                <Tooltip />
                <Line type="monotone" dataKey="val" stroke="#3b82f6" strokeWidth={2} activeDot={{ r: 6 }} dot={{ r: 4, fill: "#3b82f6", strokeWidth: 0 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Middle Row 1: Fraccionamiento 5 masas */}
      <CollapsibleSection title="Fraccionamiento 5 masas" icon={PieChartIcon}>
        <div className={styles.pieChartsGrid}>
          {/* Pie 1 */}
          <div className={styles.pieCol}>
            <div className={styles.pieTitle}>07-09-2025</div>
            <div className={styles.pieWrapper}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData1} innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value" stroke="none">
                    {pieData1.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <PieLegend />
          </div>

          {/* Pie 2 */}
          <div className={styles.pieCol}>
            <div className={styles.pieTitle}>10-10-2025</div>
            <div className={styles.pieWrapper}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData1} innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value" stroke="none">
                    {pieData1.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <PieLegend />
          </div>

          {/* Pie 3 */}
          <div className={styles.pieCol}>
            <div className={styles.pieTitle}>12-11-2025</div>
            <div className={styles.pieWrapper}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData1} innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value" stroke="none">
                    {pieData1.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <PieLegend />
          </div>
        </div>
      </CollapsibleSection>

      {/* Middle Row 2: Análisis M. adiposa y M. muscular */}
      <CollapsibleSection title="Análisis M. adiposa y M. muscular" icon={Activity}>
        <div className={styles.barChartsGrid}>
          {/* Chart KG */}
          <div>
            <div className={styles.barColTitle}>EN KILOGRAMOS</div>
            <div className={styles.barLegend}>
              <div className={styles.barLegendItem}>
                <span className={styles.barColor} style={{ backgroundColor: PIE_COLORS.adiposa }}></span> M. adiposa
              </div>
              <div className={styles.barLegendItem}>
                <span className={styles.barColor} style={{ backgroundColor: PIE_COLORS.muscular }}></span> M. muscular
              </div>
            </div>
            <div className={styles.barChartWrapper}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barDataKg} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} dy={10} />
                  <YAxis domain={[0, 40]} tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{fill: 'transparent'}} />
                  <Bar dataKey="adiposa" fill={PIE_COLORS.adiposa} radius={[4, 4, 0, 0]} barSize={40} />
                  <Bar dataKey="muscular" fill={PIE_COLORS.muscular} radius={[4, 4, 0, 0]} barSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Chart Perc */}
          <div>
            <div className={styles.barColTitle}>EN PORCENTAJE</div>
            <div className={styles.barLegend}>
              <div className={styles.barLegendItem}>
                <span className={styles.barColor} style={{ backgroundColor: '#fca5a5' }}></span> M. adiposa % {/* Lighter orange in design */}
              </div>
              <div className={styles.barLegendItem}>
                <span className={styles.barColor} style={{ backgroundColor: '#60a5fa' }}></span> M. muscular % {/* Lighter blue in design */}
              </div>
            </div>
            <div className={styles.barChartWrapper}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barDataPerc} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} dy={10} />
                  <YAxis domain={[0, 70]} ticks={[0, 10, 20, 30, 40, 50, 60, 70]} tick={{fontSize: 10, fill: '#9ca3af'}} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{fill: 'transparent'}} />
                  <Bar dataKey="adiposa" fill="#fca5a5" radius={[4, 4, 0, 0]} barSize={40} />
                  <Bar dataKey="muscular" fill="#60a5fa" radius={[4, 4, 0, 0]} barSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* Middle Row 3: Recomendaciones */}
      <CollapsibleSection title="Recomendaciones antropométricas (Kerr 1988 / Phantom)" icon={Edit3}>
        <div style={{ fontSize: '0.65rem', color: '#9ca3af', marginBottom: '8px' }}>
          Basado en método Kerr 1988 / Phantom · Último toma: 12-11-2025 · Peso: 70.3 kg · Talla: 172.2 cm
        </div>
        <div className={styles.recoList}>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Masa adiposa actual</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>12.39 kg (17.6%)</span> — Objetivo &gt; 11.95 kg (17%) <span className={`${styles.changeIndicator} ${styles.upGreen}`}>-0.44 kg</span>
            </span>
          </div>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Masa muscular actual</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>36.24 kg (51.6%)</span> — Objetivo &lt; 36.56 kg (52%) <span className={`${styles.changeIndicator} ${styles.upRed}`}>+0.32 kg</span>
            </span>
          </div>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Masa ósea actual</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>8.86 kg</span> — Ref. calculada Kerr: 8.73 kg
            </span>
          </div>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Masa residual actual</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>8.94 kg</span> — Ref. calculada Kerr: 8.95 kg
            </span>
          </div>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Masa piel actual</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>3.86 kg</span> — Ref. calculada Kerr: 3.78 kg
            </span>
          </div>
          <div className={styles.recoItem}>
            <span className={styles.recoLabel}>Suma 6 pliegues</span>
            <span className={styles.recoTarget}>
              <span className={styles.recoVal}>6.80 mm</span> — Tendencia favorable si disminuye
            </span>
          </div>
        </div>
      </CollapsibleSection>

      {/* Bottom Section: Objetivos */}
      <div className={styles.card}>
        <div className={styles.objTitle}>OBJETIVOS Y COMENTARIOS</div>
        <div className={styles.objList}>
          {goals.map((g) => (
            <div key={g.id} className={styles.objItem}>
              <input 
                type="checkbox" 
                className={styles.objCheckbox} 
                checked={g.checked} 
                onChange={() => toggleGoal(g.id)}
              />
              <div className={styles.objContent}>
                <span className={styles.objText} style={{ textDecoration: g.checked ? 'line-through' : 'none', color: g.checked ? '#9ca3af' : '#111827' }}>
                  {g.text}
                </span>
                <span className={styles.objDate}>{g.date}</span>
              </div>
            </div>
          ))}
        </div>
        <div className={styles.inputRow}>
          <input 
            type="text" 
            placeholder="Nuevo objetivo..." 
            className={styles.inputField} 
            value={newGoalObj}
            onChange={(e) => setNewGoalObj(e.target.value)}
          />
          <input 
            type="text" 
            placeholder="Comentario (opcional)" 
            className={styles.inputField} 
            value={newGoalComment}
            onChange={(e) => setNewGoalComment(e.target.value)}
          />
          <button className={styles.btnAdd} onClick={handleAddGoal}>
            <Plus size={14} /> Agregar
          </button>
        </div>
      </div>

    </div>
  );
}
