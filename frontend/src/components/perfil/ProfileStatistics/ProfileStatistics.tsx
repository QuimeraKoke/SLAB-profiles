import React from 'react';
import { ChevronDown, Calendar } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts';
import styles from './ProfileStatistics.module.css';

const chartData = [
  { date: '06-04', minutos: 0 },
  { date: '08-11', minutos: 45 },
  { date: '08-18', minutos: 90 },
  { date: '08-25', minutos: 60 },
  { date: '08-28', minutos: 90 },
  { date: '09-01', minutos: 90 },
  { date: '09-05', minutos: 15 },
  { date: '09-08', minutos: 70 },
  { date: '09-15', minutos: 90 },
  { date: '09-24', minutos: 90 },
  { date: '09-29', minutos: 90 },
  { date: '10-06', minutos: 90 },
  { date: '10-09', minutos: 90 },
  { date: '10-13', minutos: 90 },
  { date: '10-20', minutos: 90 },
  { date: '11-03', minutos: 85 },
  { date: '11-10', minutos: 90 },
  { date: '11-20', minutos: 90 },
];

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div style={{ backgroundColor: 'white', padding: '8px 12px', border: '1px solid #e5e7eb', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
        <p style={{ margin: 0, fontSize: '12px', color: '#6b7280' }}>{label}</p>
        <p style={{ margin: 0, fontSize: '14px', fontWeight: 'bold', color: '#3b82f6' }}>{payload[0].value} minutos</p>
      </div>
    );
  }
  return null;
};

export default function ProfileStatistics() {
  return (
    <div className={styles.container}>
      {/* Top Row */}
      <div className={styles.topRow}>
        
        {/* 2x2 Grid */}
        <div className={styles.statsGrid}>
          <div className={styles.smallCard}>
            <div className={styles.cardTitle}>PARTIDOS JUGADOS</div>
            <div>
              <div className={styles.statValue}>18</div>
              <div className={styles.statSubtext}>de 18 convocatorias</div>
            </div>
          </div>
          <div className={styles.smallCard}>
            <div className={styles.cardTitle}>% MIN. JUGADOS</div>
            <div>
              <div className={`${styles.statValue} ${styles.statValueBlue}`}>83,58%</div>
              <div className={styles.statSubtext}>1.384 / 1.656 min</div>
            </div>
          </div>
          <div className={styles.smallCard}>
            <div className={styles.cardTitle}>GOLES</div>
            <div>
              <div className={styles.statValue}>2</div>
              <div className={styles.statSubtext}>Contribuciones ofensivas</div>
            </div>
          </div>
          <div className={styles.smallCard}>
            <div className={styles.cardTitle}>AMARILLAS</div>
            <div>
              <div className={`${styles.statValue} ${styles.statValueOrange}`}>2</div>
              <div className={styles.statSubtext}>Rojas <span style={{ color: '#10b981', fontWeight: 600 }}>0</span></div>
            </div>
          </div>
        </div>

        {/* Chart Area */}
        <div className={styles.card}>
          <div className={styles.chartHeader}>
            <div className={styles.chartTitle}>Evolución por partido</div>
            <div className={styles.filters}>
              <button className={styles.filterSelect}>
                Minutos <ChevronDown size={14} />
              </button>
              <button className={styles.filterSelect}>
                <Calendar size={14} /> 04-08-2024 - 28-11-2024 <ChevronDown size={14} />
              </button>
            </div>
          </div>
          <div style={{ flexGrow: 1, height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={chartData}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="colorMinutos" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                <XAxis 
                  dataKey="date" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  ticks={[0, 10, 20, 30, 40, 50, 60, 70, 80, 90]}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area 
                  type="monotone" 
                  dataKey="minutos" 
                  stroke="#3b82f6" 
                  fillOpacity={1} 
                  fill="url(#colorMinutos)" 
                  strokeWidth={2}
                  activeDot={{ r: 6, fill: "#3b82f6", stroke: "white", strokeWidth: 2 }}
                  dot={{ r: 4, fill: "#3b82f6", strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className={styles.bottomRow}>
        
        {/* Comments Section */}
        <div className={styles.card}>
          <div className={styles.commentsTitle}>Comentarios del cuerpo técnico</div>
          <div className={styles.commentList}>
            {[
              { date: '12/08/24', text: 'Muy bien en la organización del juego en el pentágono base. Le dio mucha calidad al juego y se soltó incluso por el centro. Perdió un par de balones importantes.' },
              { date: '19/08/24', text: 'Creo que tuvo pocas intervenciones pero tuvo toques de tremenda calidad que fueron claves en dos goles.' },
              { date: '27/08/24', text: 'De los más bajos, tuvo un par de pases de mucha calidad filtrando.' },
              { date: '29/08/24', text: 'Aún oscila entre grandes acciones y errores fáciles. Tiene pases filtrados muy buenos en zona media.' },
              { date: '01/09/24', text: 'Uno de los mejores, se llevó el peso del equipo y se hizo cargo del juego en el medio campo.' },
              { date: '06/09/24', text: 'Correcto partido en los minutos que pudo disputar.' },
              { date: '12/09/24', text: 'Entendió bien donde estaban los espacios y ayudó mucho a generar fútbol.' }
            ].map((comment, index) => (
              <div key={index} className={styles.commentItem}>
                <div className={styles.commentDate}>{comment.date}</div>
                <div className={styles.commentText}>{comment.text}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Word Cloud */}
        <div className={styles.card}>
          <div className={styles.commentsTitle}>Nube de palabras</div>
          <div className={styles.wordCloudArea}>
            <div className={styles.wordCloudMock}>
              <span className={styles.wordSize1}>calidad</span>
              <span className={styles.wordSize4}>ayudó</span>
              <span className={styles.wordSize2}>acciones</span>
              <span className={styles.wordSize5}>filtrados</span>
              <span className={styles.wordSize3}>juego</span>
              <span className={styles.wordSize4}>campo</span>
              <span className={styles.wordSize2}>correcto</span>
              <span className={styles.wordSize5}>errores</span>
              <span className={styles.wordSize1}>excelente</span>
              <span className={styles.wordSize3}>mucha</span>
              <span className={styles.wordSize4}>minutos</span>
              <span className={styles.wordSize5}>entregas</span>
              <span className={styles.wordSize2}>medio</span>
              <span className={styles.wordSize4}>general</span>
              <span className={styles.wordSize1}>juego</span>
              <span className={styles.wordSize3}>mucho</span>
              <span className={styles.wordSize5}>espacios</span>
              <span className={styles.wordSize4}>balones</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
