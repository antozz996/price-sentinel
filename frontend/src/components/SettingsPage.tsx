import { useState, useEffect } from 'react';
import { User, Shield, Database, RefreshCw, CheckCircle2, AlertCircle, Building2, Plus, ToggleLeft, ToggleRight, MapPin, Trash2, Pencil } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface UserInfo {
  id: number;
  email: string;
  ruolo: string;
  attivo: boolean;
}

interface LocationItem {
  id: number;
  nome_struttura: string;
  piva_riferimento: string;
  tipologia: string;
}

interface FornitoreItem {
  id: number;
  nome_azienda: string;
  partita_iva: string;
  attivo_whitelist: boolean;
  email_contatto: string | null;
}

export default function SettingsPage() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [dbStats, setDbStats] = useState<any>(null);
  const [locations, setLocations] = useState<LocationItem[]>([]);
  const [fornitori, setFornitori] = useState<FornitoreItem[]>([]);
  
  // Create forms state
  const [locNome, setLocNome] = useState('');
  const [locPiva, setLocPiva] = useState('');
  const [locTipo, setLocTipo] = useState('balneare');

  const [fornNome, setFornNome] = useState('');
  const [fornPiva, setFornPiva] = useState('');
  const [fornEmail, setFornEmail] = useState('');

  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [submittingLoc, setSubmittingLoc] = useState(false);
  const [submittingForn, setSubmittingForn] = useState(false);

  // States for database reset
  const [resetPassword, setResetPassword] = useState('');
  const [resetMessage, setResetMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [resetLoading, setResetLoading] = useState(false);

  const handleResetDatabase = async () => {
    if (!resetPassword.trim()) {
      setResetMessage({ text: 'Inserisci la password di sicurezza.', type: 'error' });
      return;
    }
    
    const confirmReset = window.confirm(
      "ATTENZIONE: Questa azione eliminerà permanentemente tutte le fatture, le righe di fattura, i listini master, le anomalie e le impostazioni del sistema. Gli account utente non verranno cancellati. Vuoi procedere?"
    );
    
    if (!confirmReset) return;
    
    setResetLoading(true);
    setResetMessage(null);
    try {
      const res = await fetch(`${API_BASE}/intelligence/reset-database`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ password: resetPassword.trim() })
      });
      
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Errore durante il ripristino del database');
      }
      
      setResetMessage({ text: 'Database svuotato con successo!', type: 'success' });
      setResetPassword('');
      loadData();
    } catch (err: any) {
      setResetMessage({ text: err.message || 'Errore di connessione', type: 'error' });
    } finally {
      setResetLoading(false);
    }
  };

  const [editingLocId, setEditingLocId] = useState<number | null>(null);
  const [editLocNome, setEditLocNome] = useState('');
  const [editLocTipo, setEditLocTipo] = useState('');

  const headers = getHeaders();

  const loadData = async (signal?: AbortSignal) => {
    try {
      const [usersRes, statsRes, locRes, fornRes] = await Promise.all([
        fetch(`${API_BASE}/utenti/`, { headers, signal }),
        fetch(`${API_BASE}/health`, { headers, signal }),
        fetch(`${API_BASE}/location/`, { headers, signal }),
        fetch(`${API_BASE}/fornitori/`, { headers, signal })
      ]);

      if (usersRes.ok) {
        const uData = await usersRes.json();
        if (Array.isArray(uData)) setUsers(uData);
      }

      if (statsRes.ok) {
        const sData = await statsRes.json();
        setDbStats(sData);
      }

      if (locRes.ok) {
        const lData = await locRes.json();
        if (Array.isArray(lData)) setLocations(lData);
      }

      if (fornRes.ok) {
        const fData = await fornRes.json();
        if (Array.isArray(fData)) setFornitori(fData);
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller.signal);
    return () => controller.abort();
  }, []);

  const handleCreateLocation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!locNome || locPiva.length !== 11) {
      setMessage({ text: 'Compila tutti i campi. La P.IVA ricevente deve essere di 11 cifre.', type: 'error' });
      return;
    }

    setSubmittingLoc(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/location/`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_struttura: locNome,
          piva_riferimento: locPiva,
          tipologia: locTipo
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Impossibile creare la location.');
      }

      setMessage({ text: `Sede Ricevente "${locNome}" aggiunta correttamente!`, type: 'success' });
      setLocNome('');
      setLocPiva('');
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante la creazione.', type: 'error' });
    } finally {
      setSubmittingLoc(false);
    }
  };

  const handleDeleteLocation = async (locationId: number) => {
    if (!window.confirm("Sei sicuro di voler eliminare questa sede? Questa azione è irreversibile.")) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/location/${locationId}`, {
        method: 'DELETE',
        headers
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Impossibile eliminare la sede.');
      }

      setMessage({ text: 'Sede Ricevente eliminata con successo!', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'eliminazione.', type: 'error' });
    }
  };

  const handleUpdateLocation = async (locationId: number) => {
    if (!editLocNome) {
      setMessage({ text: 'Il nome della struttura non può essere vuoto.', type: 'error' });
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/location/${locationId}`, {
        method: 'PATCH',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_struttura: editLocNome,
          tipologia: editLocTipo
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Impossibile aggiornare la sede.');
      }

      setMessage({ text: 'Sede aggiornata con successo!', type: 'success' });
      setEditingLocId(null);
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'aggiornamento.', type: 'error' });
    }
  };

  const handleCreateFornitore = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fornNome || !fornPiva) {
      setMessage({ text: 'Compila i campi obbligatori per il fornitore.', type: 'error' });
      return;
    }

    setSubmittingForn(true);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE}/fornitori/`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_azienda: fornNome,
          partita_iva: fornPiva,
          email_contatto: fornEmail !== '' ? fornEmail : null,
          attivo_whitelist: true
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Impossibile creare il fornitore.');
      }

      setMessage({ text: `Fornitore "${fornNome}" aggiunto in Whitelist correttamente!`, type: 'success' });
      setFornNome('');
      setFornPiva('');
      setFornEmail('');
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante la creazione.', type: 'error' });
    } finally {
      setSubmittingForn(false);
    }
  };

  const handleToggleWhitelist = async (fornitoreId: number) => {
    try {
      const res = await fetch(`${API_BASE}/fornitori/${fornitoreId}/whitelist`, {
        method: 'PATCH',
        headers
      });
      if (res.ok) {
        loadData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteFornitore = async (fornitoreId: number) => {
    if (!window.confirm("Sei sicuro di voler eliminare questo fornitore? Questa azione è irreversibile.")) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/fornitori/${fornitoreId}`, {
        method: 'DELETE',
        headers
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Impossibile eliminare il fornitore.');
      }

      setMessage({ text: 'Fornitore eliminato correttamente!', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'eliminazione.', type: 'error' });
    }
  };

  function handleLogout() {
    localStorage.removeItem('token');
    window.location.reload();
  }

  const cardStyle: React.CSSProperties = {
    padding: '24px', borderRadius: '12px',
    background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)'
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '1100px' }}>

      {message && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '10px',
          background: message.type === 'success' ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
          color: message.type === 'success' ? '#10b981' : '#ef4444'
        }}>
          {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
          {message.text}
        </div>
      )}

      {/* ANAGRAFICHE MANAGEMENT PANEL */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(480px, 1fr))', gap: '24px' }}>
        
        {/* Card Locations / Sedi Riceventi */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <MapPin size={20} color="var(--accent-blue)" /> Sedi Gruppo (Partite IVA Riceventi)
          </h3>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Inserisci le P.IVA del tuo gruppo aziendale. Le fatture XML caricate che hanno queste P.IVA come Ricevente/Cessionario verranno importate ed associate alla sede.
          </p>

          <form onSubmit={handleCreateLocation} style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(255,255,255,0.01)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.03)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="text"
                placeholder="Nome Struttura..."
                value={locNome}
                onChange={e => setLocNome(e.target.value)}
                style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              />
              <input
                type="text"
                maxLength={11}
                placeholder="Partita IVA (11 cifre)..."
                value={locPiva}
                onChange={e => setLocPiva(e.target.value)}
                style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <select
                value={locTipo}
                onChange={e => setLocTipo(e.target.value)}
                style={{ flex: 1, padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              >
                <option value="balneare" style={{ background: '#13131c' }}>Tipologia: Balneare / Eventi</option>
                <option value="ristorante" style={{ background: '#13131c' }}>Tipologia: Ristorante / Food</option>
                <option value="discoteca" style={{ background: '#13131c' }}>Tipologia: Discoteca / Club</option>
                <option value="evento" style={{ background: '#13131c' }}>Tipologia: Evento / Altro</option>
              </select>
              <button
                type="submit"
                disabled={submittingLoc}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 16px', height: '36px', fontSize: '0.85rem' }}
              >
                <Plus size={14} /> {submittingLoc ? 'Emissione...' : 'Aggiungi'}
              </button>
            </div>
          </form>

          {/* List Sedi */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto', paddingRight: '4px' }}>
            {locations.map(loc => (
              editingLocId === loc.id ? (
                <div key={loc.id} style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '12px 16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
                    <input 
                      type="text"
                      value={editLocNome}
                      onChange={e => setEditLocNome(e.target.value)}
                      style={{ flex: 2, padding: '6px 10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', fontSize: '0.8rem' }}
                    />
                    <select 
                      value={editLocTipo}
                      onChange={e => setEditLocTipo(e.target.value)}
                      style={{ flex: 1, padding: '6px 10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', fontSize: '0.8rem', outline: 'none' }}
                    >
                      <option value="balneare" style={{ background: '#13131c' }}>Balneare</option>
                      <option value="ristorante" style={{ background: '#13131c' }}>Ristorante</option>
                      <option value="discoteca" style={{ background: '#13131c' }}>Discoteca</option>
                      <option value="evento" style={{ background: '#13131c' }}>Evento</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>P.IVA: {loc.piva_riferimento}</span>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button 
                        onClick={() => setEditingLocId(null)}
                        className="btn"
                        style={{ padding: '4px 10px', fontSize: '0.75rem', background: 'transparent', border: '1px solid var(--border-glass)' }}
                      >
                        Annulla
                      </button>
                      <button 
                        onClick={() => handleUpdateLocation(loc.id)}
                        className="btn btn-primary"
                        style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                      >
                        Salva
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div key={loc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'rgba(255,255,255,0.01)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.02)' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{loc.nome_struttura}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>P.IVA: {loc.piva_riferimento}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '0.7rem', padding: '3px 8px', borderRadius: '4px', background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', textTransform: 'capitalize' }}>
                      {loc.tipologia}
                    </span>
                    
                    <button 
                      onClick={() => {
                        setEditingLocId(loc.id);
                        setEditLocNome(loc.nome_struttura);
                        setEditLocTipo(loc.tipologia);
                      }}
                      style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', transition: 'opacity 0.2s', opacity: 0.8 }}
                      title="Modifica nome o tipologia"
                      onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                      onMouseLeave={e => e.currentTarget.style.opacity = '0.8'}
                    >
                      <Pencil size={14} />
                    </button>

                    <button 
                      onClick={() => handleDeleteLocation(loc.id)}
                      style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', transition: 'opacity 0.2s', opacity: 0.8 }}
                      title="Elimina sede"
                      onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                      onMouseLeave={e => e.currentTarget.style.opacity = '0.8'}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              )
            ))}
          </div>
        </div>

        {/* Card Whitelist Fornitori */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Building2 size={20} color="var(--primary-color)" /> Fornitori in Whitelist (P.IVA Mittenti)
          </h3>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Aggiungi i fornitori abilitati del gruppo Ho.Re.Ca. Le fatture XML che hanno come Cedente/Prestatore queste P.IVA verranno catalogate in automatico.
          </p>

          <form onSubmit={handleCreateFornitore} style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(255,255,255,0.01)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.03)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="text"
                placeholder="Ragione Sociale..."
                value={fornNome}
                onChange={e => setFornNome(e.target.value)}
                style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              />
              <input
                type="text"
                placeholder="P.IVA Fornitore..."
                value={fornPiva}
                onChange={e => setFornPiva(e.target.value)}
                style={{ padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <input
                type="email"
                placeholder="Email Contatto (Opzionale)..."
                value={fornEmail}
                onChange={e => setFornEmail(e.target.value)}
                style={{ flex: 1, padding: '8px 12px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white', fontSize: '0.85rem' }}
              />
              <button
                type="submit"
                disabled={submittingForn}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '0 16px', height: '36px', fontSize: '0.85rem' }}
              >
                <Plus size={14} /> {submittingForn ? 'Emissione...' : 'Aggiungi'}
              </button>
            </div>
          </form>

          {/* List Fornitori */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto', paddingRight: '4px' }}>
            {fornitori.map(f => (
              <div key={f.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'rgba(255,255,255,0.01)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.02)' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{f.nome_azienda}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>P.IVA: {f.partita_iva} {f.email_contatto ? `| ${f.email_contatto}` : ''}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <button
                    onClick={() => handleToggleWhitelist(f.id)}
                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                    title={f.attivo_whitelist ? "Disattiva whitelist" : "Attiva whitelist"}
                  >
                    {f.attivo_whitelist ? (
                      <ToggleRight size={26} color="#10b981" />
                    ) : (
                      <ToggleLeft size={26} color="#6b7280" />
                    )}
                  </button>
                  <button 
                    onClick={() => handleDeleteFornitore(f.id)}
                    style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', transition: 'opacity 0.2s', opacity: 0.8 }}
                    title="Elimina fornitore"
                    onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                    onMouseLeave={e => e.currentTarget.style.opacity = '0.8'}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>

      {/* System Status */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Database size={20} /> Stato del Sistema
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          <div style={cardStyle}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Servizio</div>
            <div style={{ fontWeight: 600, color: dbStats?.status === 'healthy' ? '#10b981' : '#ef4444' }}>
              {dbStats?.status === 'healthy' ? '● Online' : '● Offline'}
            </div>
          </div>
          <div style={cardStyle}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Versione</div>
            <div style={{ fontWeight: 600 }}>{dbStats?.version || '—'}</div>
          </div>
          <div style={cardStyle}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Ambiente</div>
            <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>{dbStats?.environment || '—'}</div>
          </div>
        </div>
        <button className="btn" onClick={() => loadData()} style={{ marginTop: '16px', gap: '8px', background: 'transparent', border: '1px solid var(--border-glass)' }}>
          <RefreshCw size={14} /> Aggiorna Stato
        </button>
      </div>

      {/* Resetta Database */}
      <div className="glass-panel" style={{ padding: '24px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
        <h3 style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '10px', color: '#ef4444' }}>
          <AlertCircle size={20} /> Ripristino e Cancellazione Dati
        </h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0 0 16px 0', lineHeight: 1.5 }}>
          Questa operazione rimuove tutte le fatture caricate, le anomalie rilevate, i listini master concordati e le associazioni di alias. Gli account utente rimarranno intatti.
        </p>

        {resetMessage && (
          <div style={{
            padding: '12px 16px',
            borderRadius: '8px',
            background: resetMessage.type === 'success' ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
            color: resetMessage.type === 'success' ? '#10b981' : '#ef4444',
            border: `1px solid ${resetMessage.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
            marginBottom: '16px',
            fontSize: '0.85rem'
          }}>
            {resetMessage.text}
          </div>
        )}

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            type="password"
            placeholder="Inserisci la password di sicurezza..."
            value={resetPassword}
            onChange={e => setResetPassword(e.target.value)}
            style={{
              padding: '10px 14px',
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid var(--border-glass)',
              borderRadius: '8px',
              color: 'white',
              outline: 'none',
              fontSize: '0.9rem',
              flex: 1,
              minWidth: '240px'
            }}
          />
          <button
            onClick={handleResetDatabase}
            disabled={resetLoading}
            className="btn btn-primary"
            style={{
              padding: '10px 24px',
              background: '#ef4444',
              borderColor: '#ef4444',
              color: 'white',
              cursor: resetLoading ? 'not-allowed' : 'pointer'
            }}
          >
            {resetLoading ? 'Cancellazione in corso...' : 'Resetta Tutti i Dati'}
          </button>
        </div>
      </div>

      {/* Users */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Shield size={20} /> Utenti del Sistema
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {users.map(u => (
            <div key={u.id} style={{
              ...cardStyle, display: 'flex', alignItems: 'center', gap: '16px', padding: '16px 20px'
            }}>
              <div style={{
                width: '36px', height: '36px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: u.ruolo === 'admin' ? 'rgba(239,68,68,0.15)' : 'rgba(59,130,246,0.15)',
                color: u.ruolo === 'admin' ? '#ef4444' : '#3b82f6', fontWeight: 700, fontSize: '0.9rem'
              }}>
                {u.email[0].toUpperCase()}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{u.email}</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{u.ruolo}</div>
              </div>
              <span style={{
                padding: '4px 12px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: 600,
                background: u.attivo ? 'rgba(16,185,129,0.15)' : 'rgba(107,114,128,0.15)',
                color: u.attivo ? '#10b981' : '#6b7280'
              }}>
                {u.attivo ? 'Attivo' : 'Disattivato'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Account */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <User size={20} /> Account
        </h3>
        <button className="btn" onClick={handleLogout} style={{ background: 'rgba(239,68,68,0.15)', border: 'none', color: '#ef4444', gap: '8px' }}>
          Disconnetti
        </button>
      </div>
    </div>
  );
}
