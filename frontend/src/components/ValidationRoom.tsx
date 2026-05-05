import { useEffect, useState } from 'react';
import { AnomalieAPI, Anomalia } from '../api';
import { Clock } from 'lucide-react';

export default function ValidationRoom() {
  const [anomalie, setAnomalie] = useState<Anomalia[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAnomalie = async () => {
    try {
      setLoading(true);
      const data = await AnomalieAPI.list('da_verificare');
      setAnomalie(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnomalie();
  }, []);

  const handleAzione = async (id: number, azione: any) => {
    try {
      await AnomalieAPI.azioneManager(id, azione, 'Azione rapida da Dashboard');
      // Rimuovi dalla lista dopo l'azione
      setAnomalie(prev => prev.filter(a => a.id !== id));
    } catch (err) {
      alert("Errore durante l'azione: " + err);
    }
  };

  if (loading) return <div>Caricamento anomalie...</div>;

  return (
    <div className="glass-panel" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h3>Anomalie da Validare ({anomalie.length})</h3>
        <button className="btn" onClick={fetchAnomalie}><Clock size={16}/> Refresh</button>
      </div>

      <div style={{ width: '100%', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <th style={{ padding: '12px' }}>Fornitore / Articolo</th>
              <th style={{ padding: '12px' }}>Prezzo Fattura</th>
              <th style={{ padding: '12px' }}>Prezzo Listino</th>
              <th style={{ padding: '12px' }}>Delta</th>
              <th style={{ padding: '12px', textAlign: 'right' }}>Azione</th>
            </tr>
          </thead>
          <tbody>
            {anomalie.length === 0 && (
              <tr><td colSpan={5} style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>Ottimo lavoro! Nessuna anomalia pendente.</td></tr>
            )}
            {anomalie.map((ano) => (
              <tr key={ano.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <td style={{ padding: '16px 12px' }}>
                    <div style={{ fontWeight: 600 }}>ID Anomalia #{ano.id}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Riga Fattura: {ano.riga_fattura_id}</div>
                </td>
                <td style={{ padding: '16px 12px' }}>€ {Number(ano.prezzo_fatturato_snapshot).toFixed(2)}</td>
                <td style={{ padding: '16px 12px' }}>€ {Number(ano.prezzo_listino_snapshot).toFixed(2)}</td>
                <td style={{ padding: '16px 12px' }}>
                  <span className="badge badge-red">+ € {Number(ano.delta_prezzo).toFixed(2)}</span>
                </td>
                <td style={{ padding: '16px 12px', textAlign: 'right' }}>
                  <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    <button className="btn btn-primary" onClick={() => handleAzione(ano.id, 'accetta')} style={{ padding: '6px 12px', background: 'var(--status-green)', borderColor: 'var(--status-green)' }}>
                      Accetta
                    </button>
                    <button className="btn" onClick={() => handleAzione(ano.id, 'segnala')} style={{ color: 'var(--status-red)', background: 'var(--status-red-bg)', borderColor: 'rgba(239, 68, 68, 0.2)', padding: '6px 12px' }}>
                      Segnala
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
