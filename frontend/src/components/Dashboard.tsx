import { BarChart3, TrendingUp, ShieldCheck, AlertCircle } from 'lucide-react';
import { useState, useEffect } from 'react';
import { fetchWithAuth } from '../api';

interface KPI {
  euro_recuperati: number;
  euro_in_contestazione: number;
  euro_a_rischio: number;
  euro_attesa_manager: number;
}

export default function Dashboard() {
  const [kpi, setKpi] = useState<KPI | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadKPI() {
      try {
        const data = await fetchWithAuth('/intelligence/kpi');
        setKpi(data);
      } catch (error) {
        console.error("Error loading KPI", error);
      } finally {
        setLoading(false);
      }
    }
    loadKPI();
  }, []);

  if (loading) return <div style={{ color: 'var(--text-secondary)' }}>Caricamento Intelligence...</div>;

  const cards = [
    { title: 'Euro Recuperati', value: `€ ${Number(kpi?.euro_recuperati || 0).toFixed(2)}`, icon: <TrendingUp color="#10b981" />, bg: 'var(--status-green-bg)' },
    { title: 'In Contestazione', value: `€ ${Number(kpi?.euro_in_contestazione || 0).toFixed(2)}`, icon: <ShieldCheck color="#3b82f6" />, bg: 'rgba(59, 130, 246, 0.1)' },
    { title: 'Valore a Rischio', value: `€ ${Number(kpi?.euro_a_rischio || 0).toFixed(2)}`, icon: <AlertCircle color="#ef4444" />, bg: 'var(--status-red-bg)' },
    { title: 'Attesa Manager', value: `€ ${Number(kpi?.euro_attesa_manager || 0).toFixed(2)}`, icon: <BarChart3 color="#f59e0b" />, bg: 'var(--status-yellow-bg)' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '20px' }}>
      {cards.map((card, i) => (
        <div key={i} className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 500 }}>{card.title}</span>
            <div style={{ padding: '8px', borderRadius: '10px', background: card.bg }}>{card.icon}</div>
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700 }}>{card.value}</div>
        </div>
      ))}
      
      {/* Grafico Placeholder / Mock */}
      <div className="glass-panel" style={{ gridColumn: '1 / -1', padding: '24px', height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
         [ Visualizzazione Trend Risparmi Mensili - In Sviluppo ]
      </div>
    </div>
  );
}
