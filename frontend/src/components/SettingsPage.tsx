import { useState, useEffect } from 'react';
import { User, Shield, Database, RefreshCw, CheckCircle2, AlertCircle, Building2, Plus, ToggleLeft, ToggleRight, MapPin, Trash2, Pencil, Phone, MessageSquare, X, Key, Lock } from 'lucide-react';
import { API_BASE, getHeaders, logoutSession, storeSession } from '../api';

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
  telefono_contatto?: string | null;
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
  const [fornTelefono, setFornTelefono] = useState('');

  // Edit fornitore modal state
  const [showEditFornModal, setShowEditFornModal] = useState(false);
  const [editingForn, setEditingForn] = useState<FornitoreItem | null>(null);
  const [editFornNome, setEditFornNome] = useState('');
  const [editFornPiva, setEditFornPiva] = useState('');
  const [editFornEmail, setEditFornEmail] = useState('');
  const [editFornTelefono, setEditFornTelefono] = useState('');
  const [submittingEditForn, setSubmittingEditForn] = useState(false);

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

  // Company / White-Label Settings State
  const [companyName, setCompanyName] = useState('Price Sentinel');
  const [companySubtitle, setCompanySubtitle] = useState('Audit & Purchasing Platform');
  const [companySupportEmail, setCompanySupportEmail] = useState('support@pricesentinel.it');
  const [companyCurrency, setCompanyCurrency] = useState('€');
  const [savingCompany, setSavingCompany] = useState(false);

  const headers = getHeaders();

  const loadData = async (signal?: AbortSignal) => {
    try {
      const [usersRes, statsRes, locRes, fornRes, compRes] = await Promise.all([
        fetch(`${API_BASE}/utenti/`, { headers, signal }),
        fetch(`${API_BASE}/health`, { headers, signal }),
        fetch(`${API_BASE}/location/`, { headers, signal }),
        fetch(`${API_BASE}/fornitori/`, { headers, signal }),
        fetch(`${API_BASE}/settings/company/`, { headers, signal })
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

      if (compRes.ok) {
        const cData = await compRes.json();
        if (cData.company_name) setCompanyName(cData.company_name);
        if (cData.app_subtitle !== undefined) setCompanySubtitle(cData.app_subtitle || '');
        if (cData.support_email !== undefined) setCompanySupportEmail(cData.support_email || '');
        if (cData.currency_symbol) setCompanyCurrency(cData.currency_symbol);
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller.signal);
    return () => controller.abort();
  // Initial settings bootstrap; saves invoke reload explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const parseApiError = async (res: Response, defaultMsg: string): Promise<string> => {
    try {
      const text = await res.text();
      try {
        const data = JSON.parse(text);
        if (typeof data.detail === 'string') return data.detail;
        if (Array.isArray(data.detail)) return data.detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
        if (data.message) return data.message;
      } catch {
        if (text && text.length < 200 && !text.includes('<!DOCTYPE') && !text.includes('Internal Server Error')) {
          return text;
        }
      }
    } catch {
      // fallback
    }
    return defaultMsg;
  };

  const handleCreateLocation = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanNome = locNome.trim();
    const cleanPiva = locPiva.trim().toUpperCase();
    if (!cleanNome || !cleanPiva) {
      setMessage({ text: 'Compila tutti i campi obbligatori per la sede ricevente.', type: 'error' });
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
          nome_struttura: cleanNome,
          piva_riferimento: cleanPiva,
          tipologia: locTipo
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, 'Impossibile creare la location.');
        throw new Error(errorDetail);
      }

      setMessage({ text: `Sede Ricevente "${cleanNome}" aggiunta correttamente!`, type: 'success' });
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
        const errorDetail = await parseApiError(res, 'Impossibile eliminare la sede.');
        throw new Error(errorDetail);
      }

      setMessage({ text: 'Sede Ricevente eliminata con successo!', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'eliminazione.', type: 'error' });
    }
  };

  const handleUpdateLocation = async (locationId: number) => {
    const cleanNome = editLocNome.trim();
    if (!cleanNome) {
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
          nome_struttura: cleanNome,
          tipologia: editLocTipo
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, 'Impossibile aggiornare la sede.');
        throw new Error(errorDetail);
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
    const cleanNome = fornNome.trim();
    const cleanPiva = fornPiva.trim().toUpperCase();
    if (!cleanNome || !cleanPiva) {
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
          nome_azienda: cleanNome,
          partita_iva: cleanPiva,
          email_contatto: fornEmail.trim() !== '' ? fornEmail.trim() : null,
          telefono_contatto: fornTelefono.trim() !== '' ? fornTelefono.trim() : null,
          attivo_whitelist: true
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, 'Impossibile creare il fornitore.');
        throw new Error(errorDetail);
      }

      setMessage({ text: `Fornitore "${cleanNome}" aggiunto in Whitelist correttamente!`, type: 'success' });
      setFornNome('');
      setFornPiva('');
      setFornEmail('');
      setFornTelefono('');
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante la creazione.', type: 'error' });
    } finally {
      setSubmittingForn(false);
    }
  };

  const handleOpenEditFornitore = (f: FornitoreItem) => {
    setEditingForn(f);
    setEditFornNome(f.nome_azienda);
    setEditFornPiva(f.partita_iva);
    setEditFornEmail(f.email_contatto || '');
    setEditFornTelefono(f.telefono_contatto || '');
    setShowEditFornModal(true);
  };

  const handleSaveEditFornitore = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingForn) return;
    const cleanNome = editFornNome.trim();
    const cleanPiva = editFornPiva.trim().toUpperCase();
    if (!cleanNome || !cleanPiva) {
      setMessage({ text: 'Nome azienda e Partita IVA sono obbligatori.', type: 'error' });
      return;
    }

    setSubmittingEditForn(true);
    try {
      const res = await fetch(`${API_BASE}/fornitori/${editingForn.id}`, {
        method: 'PUT',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          nome_azienda: cleanNome,
          partita_iva: cleanPiva,
          email_contatto: editFornEmail.trim() !== '' ? editFornEmail.trim() : null,
          telefono_contatto: editFornTelefono.trim() !== '' ? editFornTelefono.trim() : null
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, "Impossibile aggiornare il fornitore.");
        throw new Error(errorDetail);
      }

      setMessage({ text: `Fornitore "${cleanNome}" aggiornato con successo!`, type: 'success' });
      setShowEditFornModal(false);
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante il salvataggio del fornitore.', type: 'error' });
    } finally {
      setSubmittingEditForn(false);
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
        const errorDetail = await parseApiError(res, 'Impossibile eliminare il fornitore.');
        throw new Error(errorDetail);
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
        const errorDetail = await parseApiError(res, 'Errore durante il salvataggio dell\'operatore.');
        throw new Error(errorDetail);
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
        const errorDetail = await parseApiError(res, 'Impossibile eliminare l\'operatore.');
        throw new Error(errorDetail);
      }
      setMessage({ text: 'Operatore rimosso/disattivato con successo.', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante l\'eliminazione.', type: 'error' });
    }
  };

  const handleSaveCompanySettings = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyName.trim()) return;
    setSavingCompany(true);
    try {
      const res = await fetch(`${API_BASE}/settings/company/`, {
        method: 'PUT',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          company_name: companyName.trim(),
          app_subtitle: companySubtitle.trim() || null,
          support_email: companySupportEmail.trim() || null,
          currency_symbol: companyCurrency.trim() || '€'
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, 'Impossibile salvare il branding aziendale.');
        throw new Error(errorDetail);
      }

      setMessage({ text: 'Branding e profilo aziendale salvati con successo!', type: 'success' });
      loadData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore durante il salvataggio.', type: 'error' });
    } finally {
      setSavingCompany(false);
    }
  };

  // Password Change State & Handler
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const [pwdMessage, setPwdMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwdMessage(null);

    if (!currentPassword.trim() || !newPassword.trim()) {
      setPwdMessage({ text: 'Compila tutti i campi della password.', type: 'error' });
      return;
    }

    if (newPassword !== confirmPassword) {
      setPwdMessage({ text: 'La nuova password e la conferma non coincidono.', type: 'error' });
      return;
    }

    if (newPassword.trim().length < 12) {
      setPwdMessage({ text: 'La nuova password deve contenere almeno 12 caratteri.', type: 'error' });
      return;
    }

    setChangingPassword(true);
    try {
      const res = await fetch(`${API_BASE}/auth/change-password`, {
        method: 'POST',
        headers: {
          ...headers,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      });

      if (!res.ok) {
        const errorDetail = await parseApiError(res, 'Errore durante la modifica della password.');
        throw new Error(errorDetail);
      }

      storeSession(await res.json());
      setPwdMessage({ text: 'Password aggiornata con successo!', type: 'success' });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setPwdMessage({ text: err.message || 'Errore durante il cambio password.', type: 'error' });
    } finally {
      setChangingPassword(false);
    }
  };

  async function handleLogout() {
    await logoutSession();
    window.location.reload();
  }

  const cardStyle: React.CSSProperties = {
    padding: '24px', borderRadius: 'var(--radius-lg)',
    background: 'var(--bg-card)', border: '1px solid var(--line)'
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '1100px' }}>

      {message && (
        <div style={{
          padding: '12px 16px', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px',
          background: message.type === 'success' ? 'var(--ok-bg)' : 'var(--crit-bg)',
          color: message.type === 'success' ? 'var(--ok)' : 'var(--crit)'
        }}>
          {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
          {message.text}
        </div>
      )}

      {/* WHITE-LABEL & COMPANY BRANDING PANEL */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h3 style={{ margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Building2 size={20} color="var(--accent-blue)" /> Profilo Azienda & White-Label
            </h3>
            <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Personalizza il nome del tuo gruppo aziendale, il payoff e i contatti visualizzati nell'interfaccia.
            </p>
          </div>
        </div>

        <form onSubmit={handleSaveCompanySettings} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px', alignItems: 'flex-end', background: 'var(--bg-inset)', padding: '16px', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Nome Azienda / Gruppo</label>
            <input
              type="text"
              required
              placeholder="es. Price Sentinel / Playa Group"
              value={companyName}
              onChange={e => setCompanyName(e.target.value)}
              style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Sottotitolo / Payoff Piattaforma</label>
            <input
              type="text"
              placeholder="es. Audit & Purchasing Platform"
              value={companySubtitle}
              onChange={e => setCompanySubtitle(e.target.value)}
              style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Email Supporto & Assistenza</label>
            <input
              type="email"
              placeholder="es. supporto@tuogruppo.it"
              value={companySupportEmail}
              onChange={e => setCompanySupportEmail(e.target.value)}
              style={{ padding: '9px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
            />
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '90px' }}>
              <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Valuta</label>
              <input
                type="text"
                value={companyCurrency}
                onChange={e => setCompanyCurrency(e.target.value)}
                style={{ padding: '9px 12px', textAlign: 'center', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              disabled={savingCompany}
              style={{ flex: 1, height: '38px', alignSelf: 'flex-end', fontSize: '0.85rem', fontWeight: 700 }}
            >
              {savingCompany ? 'Salvataggio...' : 'Salva Branding'}
            </button>
          </div>
        </form>
      </div>

      {/* ANAGRAFICHE MANAGEMENT PANEL */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px' }}>
        
        {/* Card Locations / Sedi Riceventi */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <MapPin size={20} color="var(--accent-blue)" /> Sedi Gruppo (Partite IVA Riceventi)
          </h3>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Inserisci le P.IVA del tuo gruppo aziendale. Le fatture XML caricate che hanno queste P.IVA come Ricevente/Cessionario verranno importate ed associate alla sede.
          </p>

          <form onSubmit={handleCreateLocation} style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--bg-inset)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="text"
                placeholder="Nome Struttura..."
                value={locNome}
                onChange={e => setLocNome(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              />
              <input
                type="text"
                maxLength={11}
                placeholder="Partita IVA (11 cifre)..."
                value={locPiva}
                onChange={e => setLocPiva(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <select
                value={locTipo}
                onChange={e => setLocTipo(e.target.value)}
                style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              >
                <option value="balneare" style={{ background: 'var(--bg-card)' }}>Tipologia: Balneare / Eventi</option>
                <option value="ristorante" style={{ background: 'var(--bg-card)' }}>Tipologia: Ristorante / Food</option>
                <option value="discoteca" style={{ background: 'var(--bg-card)' }}>Tipologia: Discoteca / Club</option>
                <option value="evento" style={{ background: 'var(--bg-card)' }}>Tipologia: Evento / Altro</option>
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
                <div key={loc.id} style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '12px 16px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
                    <input 
                      type="text"
                      value={editLocNome}
                      onChange={e => setEditLocNome(e.target.value)}
                      style={{ flex: 2, padding: '6px 10px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.8rem' }}
                    />
                    <select 
                      value={editLocTipo}
                      onChange={e => setEditLocTipo(e.target.value)}
                      style={{ flex: 1, padding: '6px 10px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.8rem', outline: 'none' }}
                    >
                      <option value="balneare" style={{ background: 'var(--bg-card)' }}>Balneare</option>
                      <option value="ristorante" style={{ background: 'var(--bg-card)' }}>Ristorante</option>
                      <option value="discoteca" style={{ background: 'var(--bg-card)' }}>Discoteca</option>
                      <option value="evento" style={{ background: 'var(--bg-card)' }}>Evento</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>P.IVA: {loc.piva_riferimento}</span>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button 
                        onClick={() => setEditingLocId(null)}
                        className="btn"
                        style={{ padding: '4px 10px', fontSize: '0.75rem', background: 'transparent', border: '1px solid var(--line)' }}
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
                <div key={loc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{loc.nome_struttura}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>P.IVA: {loc.piva_riferimento}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '0.7rem', padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--accent-bg)', color: 'var(--accent-text)', textTransform: 'capitalize' }}>
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
                      style={{ background: 'transparent', border: 'none', color: 'var(--crit)', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', transition: 'opacity 0.2s', opacity: 0.8 }}
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

          <form onSubmit={handleCreateFornitore} style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--bg-inset)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="text"
                placeholder="Ragione Sociale..."
                value={fornNome}
                onChange={e => setFornNome(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
                required
              />
              <input
                type="text"
                placeholder="P.IVA Fornitore..."
                value={fornPiva}
                onChange={e => setFornPiva(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
                required
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="email"
                placeholder="Email Contatto (Opzionale)..."
                value={fornEmail}
                onChange={e => setFornEmail(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              />
              <input
                type="tel"
                placeholder="Tel / WhatsApp (es. +39 340...)..."
                value={fornTelefono}
                onChange={e => setFornTelefono(e.target.value)}
                style={{ padding: '8px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontSize: '0.85rem' }}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="submit"
                disabled={submittingForn}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '0 20px', height: '36px', fontSize: '0.85rem' }}
              >
                <Plus size={14} /> {submittingForn ? 'Emissione...' : 'Aggiungi Fornitore'}
              </button>
            </div>
          </form>

          {/* List Fornitori */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '260px', overflowY: 'auto', paddingRight: '4px' }}>
            {fornitori.map(f => (
              <div key={f.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: 'var(--bg-inset)', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)', gap: '10px' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span>{f.nome_azienda}</span>
                    {f.telefono_contatto ? (
                      <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: '999px', background: 'var(--ok-bg)', color: 'var(--ok)', border: '1px solid var(--ok-border)', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                        <MessageSquare size={11} /> {f.telefono_contatto}
                      </span>
                    ) : (
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        (Nessun tel/WA)
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '3px' }}>
                    <span>P.IVA: <strong>{f.partita_iva}</strong></span>
                    {f.email_contatto && <span>• ✉️ {f.email_contatto}</span>}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  <button
                    onClick={() => handleOpenEditFornitore(f)}
                    className="btn"
                    style={{ background: 'var(--bg-elevated)', border: '1px solid var(--line)', padding: '5px 9px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                    title="Modifica recapiti e telefono WhatsApp"
                  >
                    <Pencil size={13} /> Modifica
                  </button>

                  <button
                    onClick={() => handleToggleWhitelist(f.id)}
                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                    title={f.attivo_whitelist ? "Disattiva whitelist" : "Attiva whitelist"}
                  >
                    {f.attivo_whitelist ? (
                      <ToggleRight size={26} color="var(--ok)" />
                    ) : (
                      <ToggleLeft size={26} color="var(--text-muted)" />
                    )}
                  </button>
                  <button 
                    onClick={() => handleDeleteFornitore(f.id)}
                    style={{ background: 'transparent', border: 'none', color: 'var(--crit)', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center', transition: 'opacity 0.2s', opacity: 0.8 }}
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
            <div style={{ fontWeight: 600, color: dbStats?.status === 'healthy' ? 'var(--ok)' : 'var(--crit)' }}>
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
        <button className="btn" onClick={() => loadData()} style={{ marginTop: '16px', gap: '8px', background: 'transparent', border: '1px solid var(--line)' }}>
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

            const roleBadgeBg = isAdm ? 'var(--crit-bg)' : isBev ? 'var(--accent-bg)' : isMat ? 'var(--ok-bg)' : isFood ? 'var(--warn-bg)' : 'var(--info-bg)';
            const roleBadgeColor = isAdm ? 'var(--crit)' : isBev ? 'var(--accent-text)' : isMat ? 'var(--ok)' : isFood ? 'var(--warn)' : 'var(--info)';
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
                  border: u.attivo ? '1px solid var(--line)' : '1px solid var(--crit-border)',
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
                    fontWeight: 700,
                    fontSize: '1rem'
                  }}>
                    {u.nome_completo ? u.nome_completo[0].toUpperCase() : u.email[0].toUpperCase()}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                        {u.nome_completo || u.email.split('@')[0]}
                      </strong>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '999px',
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
                          <span style={{ color: 'var(--accent-text)', fontWeight: 600 }}>
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
                      <ToggleRight size={28} color="var(--ok)" />
                    ) : (
                      <ToggleLeft size={28} color="var(--text-muted)" />
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => handleOpenEditUser(u)}
                    className="btn"
                    style={{ background: 'var(--bg-elevated)', border: '1px solid var(--line)', padding: '6px 10px', fontSize: '0.8rem' }}
                  >
                    <Pencil size={14} /> Modifica
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDeleteUser(u.id)}
                    className="btn"
                    style={{ background: 'var(--crit-bg)', border: '1px solid var(--crit-border)', color: 'var(--crit)', padding: '6px 10px', fontSize: '0.8rem' }}
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
          background: 'var(--bg-overlay)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{ width: '100%', maxWidth: '540px', padding: '28px', borderRadius: 'var(--radius-lg)', border: '1px solid var(--line)', maxHeight: '90vh', overflowY: 'auto' }}>
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
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
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
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
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
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
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
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                >
                  <option value="responsabile_beverage">🍹 Responsabile Beverage</option>
                  <option value="responsabile_materiali">📦 Responsabile Materiali</option>
                  <option value="responsabile_food">🍽️ Responsabile Food</option>
                  <option value="manager_sede">🏢 Store Manager / Sede</option>
                  <option value="admin">👑 Amministratore / Direzione</option>
                </select>
              </div>

              {/* Multi-Sector Checkboxes */}
              <div style={{ padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'var(--bg-inset)', border: '1px solid var(--line)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <label style={{ fontSize: '0.82rem', color: 'var(--text-primary)', fontWeight: 700 }}>
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
                    { id: 'Beverage', label: 'Beverage', icon: '🍹', desc: 'Vini, distillati, birre, analcolici e sciroppi', color: '#7cb0ff' },
                    { id: 'Materiali di consumo', label: 'Materiali di consumo', icon: '📦', desc: 'Packaging, monouso, sacchetti e detergenti', color: '#4cc38a' },
                    { id: 'Food', label: 'Food', icon: '🍽️', desc: 'Alimentari, freschi, secchi e surgelati', color: '#e8b04a' }
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
                          borderRadius: 'var(--radius-md)',
                          border: isChecked ? `1px solid ${cat.color}` : '1px solid var(--line)',
                          background: isChecked ? `${cat.color}15` : 'var(--bg-inset)',
                          cursor: 'pointer',
                          transition: 'all 0.15s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '1.2rem' }}>{cat.icon}</span>
                          <div>
                            <div style={{ fontWeight: 700, color: isChecked ? 'var(--text-primary)' : 'var(--text-secondary)', fontSize: '0.86rem' }}>
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
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
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
                  style={{ background: 'transparent', border: '1px solid var(--line)' }}
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

      {/* Modal Modifica Fornitore (Telefono WhatsApp, Email, Nome) */}
      {showEditFornModal && editingForn && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'var(--bg-overlay)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '520px',
            background: 'var(--bg-card)',
            border: '1px solid var(--line-strong)',
            borderRadius: 'var(--radius-lg)',
            padding: '28px',
            boxShadow: 'var(--shadow-pop)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                <Building2 size={22} color="var(--primary-color)" /> Modifica Fornitore & WhatsApp
              </h3>
              <button
                type="button"
                onClick={() => setShowEditFornModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveEditFornitore} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Ragione Sociale</label>
                <input
                  type="text"
                  value={editFornNome}
                  onChange={e => setEditFornNome(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Partita IVA</label>
                <input
                  type="text"
                  value={editFornPiva}
                  onChange={e => setEditFornPiva(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Email Contatto Reclami / Ordini</label>
                <input
                  type="email"
                  placeholder="es. ordini@fornitore.it"
                  value={editFornEmail}
                  onChange={e => setEditFornEmail(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                />
              </div>

              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'var(--ok)', fontWeight: 600, marginBottom: '4px' }}>
                  <Phone size={14} /> Numero di Telefono / WhatsApp per Ordini
                </label>
                <input
                  type="tel"
                  placeholder="Es. +39 340 1234567 oppure 3401234567"
                  value={editFornTelefono}
                  onChange={e => setEditFornTelefono(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', background: 'var(--ok-bg)', border: '1px solid var(--ok-border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                />
                <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px', display: 'block' }}>
                  Quando i responsabili elaborano un ordine, il pulsante <strong>"Invia su WhatsApp"</strong> aprirà direttamente la chat con questo numero precompilando l'ordine.
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button
                  type="button"
                  onClick={() => setShowEditFornModal(false)}
                  className="btn"
                  style={{ background: 'transparent', border: '1px solid var(--line)' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={submittingEditForn}
                  className="btn btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  {submittingEditForn ? 'Salvataggio...' : 'Salva Modifiche Fornitore'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* SICUREZZA & CAMBIO PASSWORD */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Key size={20} color="var(--accent-blue)" /> Sicurezza & Cambio Password
        </h3>
        <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          Modifica la password di accesso per il tuo account operatore.
        </p>

        {pwdMessage && (
          <div style={{
            padding: '10px 14px', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px',
            background: pwdMessage.type === 'success' ? 'var(--ok-bg)' : 'var(--crit-bg)',
            color: pwdMessage.type === 'success' ? 'var(--ok)' : 'var(--crit)',
            fontSize: '0.85rem'
          }}>
            {pwdMessage.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            {pwdMessage.text}
          </div>
        )}

        <form onSubmit={handleChangePassword} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', alignItems: 'flex-end' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Password Attuale
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input
                type="password"
                required
                placeholder="••••••••"
                value={currentPassword}
                onChange={e => setCurrentPassword(e.target.value)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 12px 10px 36px',
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Nuova Password
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input
                type="password"
                required
                placeholder="••••••••"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 12px 10px 36px',
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Conferma Nuova Password
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input
                type="password"
                required
                placeholder="••••••••"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 12px 10px 36px',
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem'
                }}
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={changingPassword}
              className="btn btn-primary"
              style={{
                width: '100%',
                padding: '11px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                fontSize: '0.85rem'
              }}
            >
              <Key size={16} />
              {changingPassword ? 'Aggiornamento...' : 'Aggiorna Password'}
            </button>
          </div>
        </form>
      </div>

      {/* Account Logout */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <User size={20} /> Account Corrente
        </h3>
        <button className="btn" onClick={handleLogout} style={{ background: 'var(--crit-bg)', border: 'none', color: 'var(--crit)', gap: '8px' }}>
          Disconnetti
        </button>
      </div>
    </div>
  );
}
