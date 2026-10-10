import { BarChart3, TrendingUp, ShieldCheck, AlertCircle, Award, Target, ArrowUpRight, Percent } from 'lucide-react';
import { useState, useEffect } from 'react';
import { fetchWithAuth } from '../api';

interface KPI {
  euro_recuperati: number;
  euro_in_contestazione: number;
  euro_a_rischio: number;
  euro_attesa_manager: number;
}

interface LeaderboardItem {
  rank: number;
  medal: string;
  location_id: number;
  nome_struttura: string;
  totali: number;
  ottimali: number;
  score: number;
}

interface VarianceLossItem {
  sku_interno: string;
  prodotto_nome: string;
  fornitore_nome: string;
  numero_acquisti: number;
  quantita_totale: number;
  prezzo_minimo: number;
  prezzo_medio: number;
  spreco_totale: number;
}

export default function Dashboard() {
  const [kpi, setKpi] = useState<KPI | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardItem[]>([]);
  const [varianceLoss, setVarianceLoss] = useState<VarianceLossItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    async function loadData() {
      setLoading(true);
      setLoadError(null);
      try {
        const [kpiData, leaderboardData, varianceData] = await Promise.all([
          fetchWithAuth('/intelligence/kpi', { signal: controller.signal }),
          fetchWithAuth('/intelligence/efficiency-leaderboard', { signal: controller.signal }),
          fetchWithAuth('/intelligence/variance-loss', { signal: controller.signal })
        ]);
        setKpi(kpiData);
        if (Array.isArray(leaderboardData)) {
          setLeaderboard(leaderboardData);
        }
        if (Array.isArray(varianceData)) {
          setVarianceLoss(varianceData);
        }
      } catch (error: any) {
        if (error.name !== 'AbortError') {
          console.error("Error loading Dashboard data", error);
          setLoadError("Impossibile caricare gli indicatori economici. Controlla la connessione API e riprova.");
        }
      } finally {
        setLoading(false);
      }
    }
    loadData();
    return () => controller.abort();
  }, [retryCount]);

  if (loading) return <div style={{ color: 'var(--text-secondary)', padding: '24px' }}>Caricamento Intelligence...</div>;
  if (loadError) {
    return (
      <div className="glass-panel" role="alert" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <h3 style={{ margin: 0 }}>Dati dashboard non disponibili</h3>
        <p style={{ color: 'var(--text-secondary)', margin: 0 }}>{loadError}</p>
        <button className="btn btn-primary" onClick={() => setRetryCount(count => count + 1)} style={{ alignSelf: 'flex-start' }}>Riprova</button>
      </div>
    );
  }

  // Current open disputed amount is not a monthly or annualized rate.
  const openRiskAmount = kpi?.euro_a_rischio || 0;

  const cards = [
    { 
      title: 'Euro Recuperati (NC)', 
      value: `€ ${Number(kpi?.euro_recuperati || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 
      icon: <TrendingUp color="#10b981" size={20} />, 
      bg: 'var(--status-green-bg)',
      subtitle: 'Contestazioni risolte con successo'
    },
    { 
      title: 'In Reclamo', 
      value: `€ ${Number(kpi?.euro_in_contestazione || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 
      icon: <ShieldCheck color="#3b82f6" size={20} />, 
      bg: 'rgba(59, 130, 246, 0.1)',
      subtitle: 'Contenziosi aperti con i fornitori'
    },
    { 
      title: 'Spreco Mensile Rilevato', 
      value: `€ ${Number(kpi?.euro_a_rischio || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 
      icon: <AlertCircle color="#ef4444" size={20} />, 
      bg: 'var(--status-red-bg)',
      subtitle: 'Rincari da verificare questo mese'
    },
    { 
      title: 'Attesa Validazione', 
      value: `€ ${Number(kpi?.euro_attesa_manager || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 
      icon: <BarChart3 color="#f59e0b" size={20} />, 
      bg: 'var(--status-yellow-bg)',
      subtitle: 'Anomalie pendenti dai manager'
    },
  ];

  return (
    <div className="dashboard-container" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* KPI Cards Grid */}
      <div className="dashboard-kpi-grid">
        {cards.map((card, i) => (
          <div key={i} className="glass-panel hover-glow" style={{ position: 'relative', overflow: 'hidden', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: '12px', transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)', cursor: 'default' }}>
            <div style={{ position: 'absolute', top: 0, left: 0, width: '4px', height: '100%', background: card.bg.replace('0.1', '1').replace('bg', 'color') }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{card.title}</span>
              <div style={{ padding: '8px', borderRadius: '10px', background: card.bg, backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{card.icon}</div>
            </div>
            <div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, letterSpacing: '-0.5px', marginBottom: '2px', wordBreak: 'break-word' }}>{card.value}</div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>{card.subtitle}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Analytics Main Section */}
      <div className="dashboard-analytics-grid">
        
        {/* Leaderboard Panel */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Award color="var(--accent-blue)" size={20} />
              <h4 style={{ margin: 0, fontWeight: 600, fontSize: '1rem' }}>Classifica Efficienza Acquisti</h4>
            </div>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.05)', padding: '4px 8px', borderRadius: '12px', whiteSpace: 'nowrap' }}>
              Target: &lt; 5% Min Storico
            </span>
          </div>

          <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
            <table style={{ width: '100%', minWidth: '420px', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-secondary)', fontSize: '0.78rem', textAlign: 'left' }}>
                  <th style={{ padding: '10px 8px', width: '60px' }}>Rank</th>
                  <th style={{ padding: '10px 8px' }}>Locale</th>
                  <th style={{ padding: '10px 8px' }}>Acquisti Ottimali</th>
                  <th style={{ padding: '10px 8px', textAlign: 'right' }}>Score Efficienza</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                      Nessun dato di efficienza disponibile.
                    </td>
                  </tr>
                ) : (
                  leaderboard.map((item) => (
                    <tr key={item.location_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.88rem' }}>
                      <td style={{ padding: '12px 8px', fontWeight: 'bold' }}>
                        <span style={{ fontSize: '1.1rem' }}>{item.medal}</span>
                      </td>
                      <td style={{ padding: '12px 8px', fontWeight: 500 }}>{item.nome_struttura}</td>
                      <td style={{ padding: '12px 8px', color: 'var(--text-secondary)' }}>
                        {item.ottimali} / {item.totali}
                      </td>
                      <td style={{ padding: '12px 8px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                          <span style={{ fontWeight: 700, fontSize: '0.95rem', color: item.score >= 80 ? '#10b981' : (item.score >= 50 ? '#f59e0b' : '#ef4444') }}>
                            {item.score.toFixed(1)}%
                          </span>
                          <div style={{ width: '80px', height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.05)' }}>
                            <div style={{ 
                              width: `${item.score}%`, 
                              height: '100%', 
                              background: item.score >= 80 ? 'linear-gradient(90deg, #059669, #10b981)' : (item.score >= 50 ? 'linear-gradient(90deg, #d97706, #f59e0b)' : 'linear-gradient(90deg, #dc2626, #ef4444)'),
                              boxShadow: item.score >= 80 ? '0 0 10px rgba(16, 185, 129, 0.5)' : 'none',
                              borderRadius: '3px'
                            }}/>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Projection and Optimization Panel */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <Target color="#ef4444" size={20} />
              <h4 style={{ margin: 0, fontWeight: 600, fontSize: '1rem' }}>Impatto Sprechi Proiettato</h4>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(239, 68, 68, 0.02))', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '18px 20px', borderRadius: '14px', position: 'relative', overflow: 'hidden', boxShadow: 'inset 0 0 20px rgba(239, 68, 68, 0.05)' }}>
                <div style={{ position: 'absolute', right: '-20px', top: '-20px', opacity: 0.05, transform: 'scale(2)' }}>
                  <AlertCircle size={100} color="#ef4444" />
                </div>
                <div style={{ fontSize: '0.75rem', color: 'rgba(239, 68, 68, 0.9)', fontWeight: 700, letterSpacing: '0.5px', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ef4444', display: 'inline-block', boxShadow: '0 0 10px #ef4444' }}></span>
                  VALORE A RISCHIO RILEVATO
                </div>
                <div style={{ fontSize: '2rem', fontWeight: 800, color: '#ef4444', letterSpacing: '-0.5px', textShadow: '0 0 20px rgba(239, 68, 68, 0.3)', wordBreak: 'break-word' }}>
                  € {Number(openRiskAmount).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '8px', lineHeight: 1.4 }}>
                  Somma delle anomalie attualmente contestate. Non rappresenta una proiezione annuale.
                </div>
              </div>

              <div className="dashboard-subcards-row">
                <div className="glass-panel" style={{ padding: '12px 14px', flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Baseline Prezzo</span>
                  <span style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.2 }}>Coalesce LAG/Listino</span>
                </div>
                <div className="glass-panel" style={{ padding: '12px 14px', flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Verifica risparmio</span>
                  <span style={{ fontSize: '0.95rem', fontWeight: 600, color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    Dati in verifica <ArrowUpRight size={15}/>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Percent size={14} color="var(--accent-blue)" style={{ flexShrink: 0 }} />
            <span>Il risparmio effettivo sarà disponibile dopo la verifica degli acquisti e dei listini.</span>
          </div>
        </div>

      </div>

      {/* Analisi Sprechi & Varianza Section */}
      <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <TrendingUp color="#ef4444" size={20} />
            <h4 style={{ margin: 0, fontWeight: 600, fontSize: '1rem' }}>Analisi Varianza & Sprechi (Perdite)</h4>
          </div>
          <span style={{ fontSize: '0.72rem', color: '#ef4444', background: 'rgba(239, 68, 68, 0.1)', padding: '4px 10px', borderRadius: '12px', fontWeight: 600, whiteSpace: 'nowrap' }}>
            Top Prodotti Fuori-Prezzo
          </span>
        </div>

        <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
          <table style={{ width: '100%', minWidth: '560px', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-secondary)', fontSize: '0.78rem', textAlign: 'left' }}>
                <th style={{ padding: '10px 8px' }}>Prodotto</th>
                <th style={{ padding: '10px 8px' }}>Fornitore</th>
                <th style={{ padding: '10px 8px', textAlign: 'center' }}>N. Acquisti</th>
                <th style={{ padding: '10px 8px', textAlign: 'right' }}>Prezzo Minimo</th>
                <th style={{ padding: '10px 8px', textAlign: 'right' }}>Prezzo Medio</th>
                <th style={{ padding: '10px 8px', textAlign: 'right' }}>Spreco Totale (YTD)</th>
              </tr>
            </thead>
            <tbody>
              {varianceLoss.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    Nessuna perdita per varianza rilevata sui prodotti mappati. Ottimo lavoro!
                  </td>
                </tr>
              ) : (
                varianceLoss.map((item) => (
                  <tr key={item.sku_interno} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', fontSize: '0.88rem' }}>
                    <td style={{ padding: '12px 8px', fontWeight: 500 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <span>{item.prodotto_nome}</span>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{item.sku_interno}</span>
                      </div>
                    </td>
                    <td style={{ padding: '12px 8px', color: 'var(--text-secondary)' }}>{item.fornitore_nome}</td>
                    <td style={{ padding: '12px 8px', textAlign: 'center' }}>{item.numero_acquisti}</td>
                    <td style={{ padding: '12px 8px', textAlign: 'right', color: '#10b981', fontWeight: 500 }}>
                      € {item.prezzo_minimo.toFixed(2)}
                    </td>
                    <td style={{ padding: '12px 8px', textAlign: 'right', color: '#ef4444' }}>
                      € {item.prezzo_medio.toFixed(2)}
                    </td>
                    <td style={{ padding: '12px 8px', textAlign: 'right' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem', color: '#ef4444', textShadow: '0 0 10px rgba(239,68,68,0.2)' }}>
                          -€ {item.spreco_totale.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <div style={{ width: '100px', height: '5px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '3px', overflow: 'hidden', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                          <div style={{ 
                            width: `${Math.min(100, (item.spreco_totale / (Math.max(...varianceLoss.map(v => v.spreco_totale)) || 1)) * 100)}%`, 
                            height: '100%', 
                            background: 'linear-gradient(90deg, #dc2626, #ef4444)',
                            boxShadow: '0 0 10px rgba(239, 68, 68, 0.4)',
                            borderRadius: '3px'
                          }}/>
                        </div>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
