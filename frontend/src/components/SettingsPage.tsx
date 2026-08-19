import { useState, useEffect } from 'react';
import { User, Shield, Database, RefreshCw, CheckCircle2, AlertCircle, Building2, Plus, ToggleLeft, ToggleRight, MapPin, Trash2, Pencil } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface UserInfo {
  id: number;
  email: string;
  nome_completo?: string | null;
  ruolo: string;
  ruolo_dettagliato?: string | null;
  settore_abilitato?: string | null;
  location_id?: number | null;
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

  const [editingLocId, setEditingLocId] = useState<number | null>(null);
  const [editLocNome, setEditLocNome] = useState('');
  const [editLocTipo, setEditLocTipo] = useState('');

  // User / Operator Management Modal State
  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [userEmail, setUserEmail] = useState('');
  const [userPassword, setUserPassword] = useState('');
  const [userNome, setUserNome] = useState('');
  const [userRuoloDettagliato, setUserRuoloDettagliato] = useState('responsabile_beverage');
  const [userSettori, setUserSettori] = useState<string[]>(['Beverage']);
  const [userLocationId, setUserLocationId] = useState<number | ''>('');
  const [submittingUser, setSubmittingUser] = useState(false);

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
        method: 'PUT',
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
    if (!window.confirm("Archiviare questo fornitore? Sparirà dalle funzioni operative, mentre fatture, ordini e prezzi storici resteranno disponibili.")) {
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

      setMessage({ text: 'Fornitore archiviato correttamente. Lo storico è stato conservato.', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'eliminazione.', type: 'error' });
    }
  };

  // Operator / User Management Handlers
  const handleOpenCreateUser = () => {
    setEditingUserId(null);
    setUserEmail('');
    setUserPassword('');
    setUserNome('');
    setUserRuoloDettagliato('responsabile_beverage');
    setUserSettori(['Beverage']);
    setUserLocationId('');
    setShowUserModal(true);
  };

  const handleOpenEditUser = (u: UserInfo) => {
    setEditingUserId(u.id);
    setUserEmail(u.email);
    setUserPassword('');
    setUserNome(u.nome_completo || '');
    setUserRuoloDettagliato(u.ruolo_dettagliato || (u.ruolo === 'admin' ? 'admin' : 'manager_sede'));
    
    const rawSec = u.settore_abilitato;
    if (!rawSec || rawSec === 'all') {
      setUserSettori(['Beverage', 'Materiali di consumo', 'Food']);
    } else {
      setUserSettori(rawSec.split(',').map(s => s.trim()).filter(Boolean));
    }

    setUserLocationId(u.location_id || '');
    setShowUserModal(true);
  };

  const handleSaveUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userEmail) return;

    if (userSettori.length === 0 && userRuoloDettagliato.startsWith('responsabile_')) {
      alert('Seleziona almeno un settore abilitato per questo responsabile.');
      return;
    }

    setSubmittingUser(true);
    try {
      const baseRuolo = userRuoloDettagliato === 'admin' ? 'admin' : 'manager';
      const isAll = userSettori.length === 3 || userSettori.length === 0;
      const payload: any = {
        email: userEmail.trim(),
        nome_completo: userNome.trim() || null,
        ruolo: baseRuolo,
        ruolo_dettagliato: userRuoloDettagliato,
        settore_abilitato: isAll ? 'all' : userSettori.join(','),
        location_id: userLocationId ? Number(userLocationId) : null,
      };

      if (userPassword) {
        payload.password = userPassword;
      }

      const url = editingUserId ? `${API_BASE}/utenti/${editingUserId}` : `${API_BASE}/utenti/`;
      const method = editingUserId ? 'PATCH' : 'POST';

      const res = await fetch(url, {
        method,
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Errore durante il salvataggio dell\'operatore.');
      }

      setMessage({
        text: editingUserId ? 'Operatore aggiornato con successo!' : 'Nuovo operatore creato con successo!',
        type: 'success'
      });
      setShowUserModal(false);
      loadData();
    } catch (err: any) {
      alert(err.message || 'Errore durante il salvataggio.');
    } finally {
      setSubmittingUser(false);
    }
  };

  const handleToggleUserStatus = async (u: UserInfo) => {
    try {
      const res = await fetch(`${API_BASE}/utenti/${u.id}`, {
        method: 'PATCH',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ attivo: !u.attivo })
      });
      if (res.ok) {
        loadData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteUser = async (userId: number) => {
    if (!window.confirm("Sei sicuro di voler eliminare o disattivare questo operatore?")) return;
    try {
      const res = await fetch(`${API_BASE}/utenti/${userId}`, {
        method: 'DELETE',
        headers
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile eliminare l\'operatore.');
      }
      setMessage({ text: 'Operatore rimosso/disattivato con successo.', type: 'success' });
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
                    title="Archivia fornitore"
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

      {/* Users & Operators Management */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h3 style={{ margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Shield size={20} color="var(--accent-blue)" /> Gestione Utenti & Operatori di Settore
            </h3>
            <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Crea e gestisci le credenziali di accesso per i responsabili di reparto (Beverage, Food, Materiali) e manager di sede.
            </p>
          </div>
          <button
            className="btn btn-primary"
            onClick={handleOpenCreateUser}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px', fontSize: '0.85rem' }}
          >
            <Plus size={16} /> Nuovo Operatore
          </button>
        </div>

        {/* User Cards Grid / List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {users.map(u => {
            const locObj = locations.find(l => l.id === u.location_id);
            const isAdm = u.ruolo === 'admin' || u.ruolo_dettagliato === 'admin';
            const isBev = u.ruolo_dettagliato === 'responsabile_beverage';
            const isMat = u.ruolo_dettagliato === 'responsabile_materiali';
            const isFood = u.ruolo_dettagliato === 'responsabile_food';
            const isMgr = u.ruolo_dettagliato === 'manager_sede';

            const roleBadgeBg = isAdm ? 'rgba(239,68,68,0.15)' : isBev ? 'rgba(59,130,246,0.15)' : isMat ? 'rgba(16,185,129,0.15)' : isFood ? 'rgba(245,158,11,0.15)' : 'rgba(168,85,247,0.15)';
            const roleBadgeColor = isAdm ? '#ef4444' : isBev ? '#60a5fa' : isMat ? '#34d399' : isFood ? '#fbbf24' : '#c084fc';
            const roleLabel = isAdm ? '👑 Amministratore' : isBev ? '🍹 Resp. Beverage' : isMat ? '📦 Resp. Materiali' : isFood ? '🍽️ Resp. Food' : isMgr ? '🏢 Store Manager' : '👤 Operatore';

            return (
              <div
                key={u.id}
                style={{
                  ...cardStyle,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '16px',
                  padding: '16px 20px',
                  border: u.attivo ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(239,68,68,0.2)',
                  opacity: u.attivo ? 1 : 0.6
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flex: 1, minWidth: '220px' }}>
                  <div style={{
                    width: '42px',
                    height: '42px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: roleBadgeBg,
                    color: roleBadgeColor,
                    fontWeight: 800,
                    fontSize: '1rem'
                  }}>
                    {u.nome_completo ? u.nome_completo[0].toUpperCase() : u.email[0].toUpperCase()}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ fontSize: '0.95rem', color: 'white' }}>
                        {u.nome_completo || u.email.split('@')[0]}
                      </strong>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '6px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        background: roleBadgeBg,
                        color: roleBadgeColor
                      }}>
                        {roleLabel}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '4px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      <span>✉️ {u.email}</span>
                      <span>•</span>
                      <span>
                        📍 {locObj ? locObj.nome_struttura : 'Tutte le sedi'}
                      </span>
                      {u.settore_abilitato && (
                        <>
                          <span>•</span>
                          <span style={{ color: '#93c5fd', fontWeight: 600 }}>
                            {u.settore_abilitato === 'all'
                              ? '🌐 Tutti i settori'
                              : u.settore_abilitato.split(',').map(s => {
                                  const tr = s.trim();
                                  if (tr === 'Beverage') return '🍹 Beverage';
                                  if (tr === 'Materiali di consumo') return '📦 Materiali';
                                  if (tr === 'Food') return '🍽️ Food';
                                  return tr;
                                }).join(' • ')}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* Right controls: Active status and actions */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <button
                    type="button"
                    onClick={() => handleToggleUserStatus(u)}
                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                    title={u.attivo ? "Disattiva account" : "Attiva account"}
                  >
                    {u.attivo ? (
                      <ToggleRight size={28} color="#10b981" />
                    ) : (
                      <ToggleLeft size={28} color="#6b7280" />
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => handleOpenEditUser(u)}
                    className="btn"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)', padding: '6px 10px', fontSize: '0.8rem' }}
                  >
                    <Pencil size={14} /> Modifica
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDeleteUser(u.id)}
                    className="btn"
                    style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', color: '#ef4444', padding: '6px 10px', fontSize: '0.8rem' }}
                    title="Elimina utente"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* User Creation / Edit Modal */}
      {showUserModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.75)',
          backdropFilter: 'blur(6px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{ width: '100%', maxWidth: '540px', padding: '28px', borderRadius: '16px', border: '1px solid var(--border-glass)', maxHeight: '90vh', overflowY: 'auto' }}>
            <h3 style={{ margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <User size={20} color="var(--accent-blue)" /> {editingUserId ? "Modifica Operatore" : "Nuovo Operatore di Settore"}
            </h3>

            <form onSubmit={handleSaveUser} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Nome e Cognome *</label>
                <input
                  type="text"
                  required
                  placeholder="Es. Mario Rossi"
                  value={userNome}
                  onChange={e => setUserNome(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Email di Accesso *</label>
                <input
                  type="email"
                  required
                  placeholder="Es. beverage.playa@pricesentinel.it"
                  value={userEmail}
                  onChange={e => setUserEmail(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  {editingUserId ? "Nuova Password (lascia vuoto per non modificare)" : "Password Iniziale *"}
                </label>
                <input
                  type="password"
                  required={!editingUserId}
                  placeholder={editingUserId ? "••••••••" : "Almeno 6 caratteri"}
                  value={userPassword}
                  onChange={e => setUserPassword(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Ruolo Operativo *</label>
                <select
                  value={userRuoloDettagliato}
                  onChange={e => {
                    const val = e.target.value;
                    setUserRuoloDettagliato(val);
                    if (val === 'responsabile_beverage') setUserSettori(['Beverage']);
                    else if (val === 'responsabile_materiali') setUserSettori(['Materiali di consumo']);
                    else if (val === 'responsabile_food') setUserSettori(['Food']);
                    else if (val === 'admin' || val === 'manager_sede') setUserSettori(['Beverage', 'Materiali di consumo', 'Food']);
                  }}
                  style={{ width: '100%', padding: '10px 12px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                >
                  <option value="responsabile_beverage">🍹 Responsabile Beverage</option>
                  <option value="responsabile_materiali">📦 Responsabile Materiali</option>
                  <option value="responsabile_food">🍽️ Responsabile Food</option>
                  <option value="manager_sede">🏢 Store Manager / Sede</option>
                  <option value="admin">👑 Amministratore / Direzione</option>
                </select>
              </div>

              {/* Multi-Sector Checkboxes */}
              <div style={{ padding: '12px 14px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <label style={{ fontSize: '0.82rem', color: 'white', fontWeight: 700 }}>
                    Settori Merci Abilitati (Spunta i settori) *
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      if (userSettori.length === 3) setUserSettori([]);
                      else setUserSettori(['Beverage', 'Materiali di consumo', 'Food']);
                    }}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--accent-blue)',
                      fontSize: '0.75rem',
                      cursor: 'pointer',
                      fontWeight: 600,
                      padding: 0
                    }}
                  >
                    {userSettori.length === 3 ? 'Deseleziona tutti' : 'Seleziona tutti'}
                  </button>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {[
                    { id: 'Beverage', label: 'Beverage', icon: '🍹', desc: 'Vini, distillati, birre, analcolici e sciroppi', color: '#60a5fa' },
                    { id: 'Materiali di consumo', label: 'Materiali di consumo', icon: '📦', desc: 'Packaging, monouso, sacchetti e detergenti', color: '#10b981' },
                    { id: 'Food', label: 'Food', icon: '🍽️', desc: 'Alimentari, freschi, secchi e surgelati', color: '#f59e0b' }
                  ].map(cat => {
                    const isChecked = userSettori.includes(cat.id);
                    return (
                      <div
                        key={cat.id}
                        onClick={() => {
                          if (isChecked) {
                            setUserSettori(userSettori.filter(s => s !== cat.id));
                          } else {
                            setUserSettori([...userSettori, cat.id]);
                          }
                        }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '10px 14px',
                          borderRadius: '8px',
                          border: isChecked ? `1.5px solid ${cat.color}` : '1px solid var(--border-glass)',
                          background: isChecked ? `${cat.color}15` : 'rgba(0,0,0,0.2)',
                          cursor: 'pointer',
                          transition: 'all 0.15s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '1.2rem' }}>{cat.icon}</span>
                          <div>
                            <div style={{ fontWeight: 700, color: isChecked ? 'white' : 'var(--text-secondary)', fontSize: '0.86rem' }}>
                              {cat.label}
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                              {cat.desc}
                            </div>
                          </div>
                        </div>

                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {}}
                          style={{
                            width: '18px',
                            height: '18px',
                            accentColor: cat.color,
                            cursor: 'pointer'
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Sede Assegnata</label>
                <select
                  value={userLocationId}
                  onChange={e => setUserLocationId(e.target.value === '' ? '' : Number(e.target.value))}
                  style={{ width: '100%', padding: '10px 12px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                >
                  <option value="">Tutte le sedi (Accesso Globale)</option>
                  {locations.map(loc => (
                    <option key={loc.id} value={loc.id}>
                      {loc.nome_struttura} ({loc.piva_riferimento})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button
                  type="button"
                  onClick={() => setShowUserModal(false)}
                  className="btn"
                  style={{ background: 'transparent', border: '1px solid var(--border-glass)' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={submittingUser}
                  className="btn btn-primary"
                >
                  {submittingUser ? 'Salvataggio...' : (editingUserId ? 'Salva Modifiche' : 'Crea Operatore')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Account Logout */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <User size={20} /> Account Corrente
        </h3>
        <button className="btn" onClick={handleLogout} style={{ background: 'rgba(239,68,68,0.15)', border: 'none', color: '#ef4444', gap: '8px' }}>
          Disconnetti
        </button>
      </div>
    </div>
  );
}
