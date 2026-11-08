import React, { useState } from 'react';
import { 
  ShieldAlert, Server, Users, FileText, ShoppingCart, 
  Euro, Key, Lock, RefreshCw, CheckCircle2, AlertCircle, Plus, 
  Trash2, LogIn, ArrowLeft, Copy, Check, ShieldCheck
} from 'lucide-react';
import { API_BASE, clearSession } from '../api';

interface TenantItem {
  id: number;
  slug: string;
  company_name: string;
  admin_email: string;
  frontend_port: number;
  backend_port: number;
  db_port: number;
  access_url?: string | null;
  status: string;
  created_at?: string | null;
  invoices_count: number;
  orders_count: number;
  users_count: number;
  spend_volume: number;
  admin_active: boolean;
}

interface OverviewStats {
  total_tenants: number;
  total_invoices: number;
  total_orders: number;
  total_users: number;
  total_locations: number;
  total_spend_volume: number;
  system_status: string;
  timestamp: string;
  database_connected: boolean;
}

export default function GodModeControlRoom({ onExit }: { onExit?: () => void }) {
  // Never embed, prefill, cache, or accept SuperAdmin secrets via the URL.
  const [tokenInput, setTokenInput] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Data states
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [tenants, setTenants] = useState<TenantItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newCompanyName, setNewCompanyName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newAdminEmail, setNewAdminEmail] = useState('');
  const [newAdminPassword, setNewAdminPassword] = useState('');
  const [creatingTenant, setCreatingTenant] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Reset password modal
  const [resetModalTenant, setResetModalTenant] = useState<TenantItem | null>(null);
  const [newPasswordValue, setNewPasswordValue] = useState('');
  const [resettingPassword, setResettingPassword] = useState(false);

  // Copied toast
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const godHeaders = {
    'Content-Type': 'application/json',
    'x-god-token': tokenInput.trim()
  };

  const verifyAndLoadData = async (tokenToUse: string) => {
    setLoading(true);
    setAuthError(null);
    try {
      const authRes = await fetch(`${API_BASE}/god/auth`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: tokenToUse.trim() })
      });

      if (!authRes.ok) {
        throw new Error('Master Token non valido o accesso negato');
      }

      setIsAuthenticated(true);

      // Load data
      await loadGodData(tokenToUse.trim());
    } catch (err: any) {
      setIsAuthenticated(false);
      setAuthError(err.message || 'Errore di autenticazione God Mode');
    } finally {
      setLoading(false);
    }
  };

  const loadGodData = async (activeToken?: string) => {
    const t = activeToken || tokenInput.trim();
    const h = { 'Content-Type': 'application/json', 'x-god-token': t };
    setRefreshing(true);
    try {
      const [overRes, tenRes] = await Promise.all([
        fetch(`${API_BASE}/god/overview`, { headers: h }),
        fetch(`${API_BASE}/god/tenants`, { headers: h })
      ]);

      if (overRes.ok) {
        setOverview(await overRes.json());
      }
      if (tenRes.ok) {
        setTenants(await tenRes.json());
      }
    } catch (err) {
      console.error('Error fetching god mode data', err);
    } finally {
      setRefreshing(false);
    }
  };

  const handleCreateTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError(null);
    if (!newCompanyName.trim() || !newSlug.trim() || !newAdminEmail.trim() || !newAdminPassword.trim()) {
      setModalError('Compila tutti i campi obbligatori.');
      return;
    }

    setCreatingTenant(true);
    try {
      const res = await fetch(`${API_BASE}/god/tenants`, {
        method: 'POST',
        headers: godHeaders,
        body: JSON.stringify({
          company_name: newCompanyName.trim(),
          slug: newSlug.trim().toLowerCase(),
          admin_email: newAdminEmail.trim(),
          admin_password: newAdminPassword.trim()
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile creare la nuova istanza.');
      }

      setMessage({ text: `Azienda "${newCompanyName}" attivata con successo!`, type: 'success' });
      setShowCreateModal(false);
      setNewCompanyName('');
      setNewSlug('');
      setNewAdminEmail('');
      setNewAdminPassword('');
      loadGodData();
    } catch (err: any) {
      setModalError(err.message || 'Errore durante la creazione.');
    } finally {
      setCreatingTenant(false);
    }
  };

  const handleImpersonate = async (tenant: TenantItem) => {
    try {
      const res = await fetch(`${API_BASE}/god/tenants/${tenant.id}/impersonate`, {
        method: 'POST',
        headers: godHeaders
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile impersonare l\'amministratore.');
      }

      const loginData = await res.json();
      // Salva token nella sessione principale e ricarica. Un token di rinnovo
      // precedente riporterebbe alla sessione originale al primo rinnovo.
      clearSession();
      localStorage.setItem('token', loginData.access_token);
      localStorage.setItem('impersonated_from_god', 'true');
      window.location.href = '/';
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore impersonazione.', type: 'error' });
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetModalTenant || !newPasswordValue.trim()) return;

    setResettingPassword(true);
    try {
      const res = await fetch(`${API_BASE}/god/tenants/${resetModalTenant.id}/reset-password`, {
        method: 'POST',
        headers: godHeaders,
        body: JSON.stringify({ new_password: newPasswordValue.trim() })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Errore durante il reset password.');
      }

      setMessage({ text: `Password per "${resetModalTenant.admin_email}" aggiornata con successo a "${newPasswordValue.trim()}".`, type: 'success' });
      setResetModalTenant(null);
      setNewPasswordValue('');
    } catch (err: any) {
      alert(err.message || 'Errore durante il reset password.');
    } finally {
      setResettingPassword(false);
    }
  };

  const handleDeleteTenant = async (tenant: TenantItem) => {
    if (tenant.id === 1) {
      alert('Non è possibile eliminare l\'istanza principale di default (ID 1).');
      return;
    }
    if (!window.confirm(`Sei sicuro di voler revocare ed eliminare l'istanza "${tenant.company_name}" (${tenant.slug})?`)) return;

    try {
      const res = await fetch(`${API_BASE}/god/tenants/${tenant.id}`, {
        method: 'DELETE',
        headers: godHeaders
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Impossibile eliminare l\'azienda.');
      }

      setMessage({ text: `Azienda "${tenant.company_name}" rimossa con successo.`, type: 'success' });
      loadGodData();
    } catch (err: any) {
      setMessage({ text: err.message || 'Errore eliminazione.', type: 'error' });
    }
  };

  const copyCredentials = (tenant: TenantItem) => {
    const text = `Piattaforma: ${window.location.origin}\nAzienda: ${tenant.company_name}\nEmail Admin: ${tenant.admin_email}`;
    navigator.clipboard.writeText(text);
    setCopiedId(tenant.id);
    setTimeout(() => setCopiedId(null), 2500);
  };

  // Se non autenticato, mostra il terminale di sblocco con Secret Master Key
  if (!isAuthenticated) {
    return (
      <div style={{
        minHeight: '100vh',
        background: 'var(--bg-app)',
        color: 'var(--text-primary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        fontFamily: 'var(--font-family)'
      }}>
        <div style={{
          width: '100%',
          maxWidth: '440px',
          background: 'var(--bg-card)',
          border: '1px solid var(--crit-border)',
          borderRadius: 'var(--radius-lg)',
          padding: '36px 32px',
          boxShadow: 'var(--shadow-pop)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center'
        }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: 'var(--radius-lg)',
            background: 'var(--crit-bg)',
            color: 'var(--crit)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '20px',
            border: '1px solid var(--crit-border)'
          }}>
            <ShieldAlert size={32} />
          </div>

          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, margin: '0 0 6px', letterSpacing: '-0.02em', color: 'var(--crit)' }}>
            GOD MODE CONTROL ROOM
          </h2>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: '0 0 24px' }}>
            Accesso riservato SuperAdmin per la supervisione globale multi-tenant e gestione istanze.
          </p>

          <form onSubmit={(e) => { e.preventDefault(); verifyAndLoadData(tokenInput); }} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {authError && (
              <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'var(--crit-bg)', border: '1px solid var(--crit-border)', color: 'var(--crit)', fontSize: '0.8rem', textAlign: 'left' }}>
                ⚠️ {authError}
              </div>
            )}

            <div style={{ textAlign: 'left' }}>
              <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 600 }}>
                MASTER SECRET TOKEN
              </label>
              <div style={{ position: 'relative' }}>
                <Key size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  type="password"
                  value={tokenInput}
                  onChange={e => setTokenInput(e.target.value)}
                  placeholder="Inserisci Master Token..."
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '12px 12px 12px 38px',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--line-strong)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                    fontSize: '0.9rem',
                    outline: 'none'
                  }}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: '10px',
                background: 'var(--crit)',
                color: 'var(--bg-app)',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.9rem',
                cursor: 'pointer',
                boxShadow: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
            >
              {loading ? <RefreshCw size={16} className="animate-spin" /> : <Lock size={16} />}
              {loading ? 'Verifica in corso...' : 'Sblocca Control Room God Mode'}
            </button>

            {onExit && (
              <button
                type="button"
                onClick={onExit}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '0.8rem', cursor: 'pointer', marginTop: '4px' }}
              >
                ← Torna alla piattaforma standard
              </button>
            )}
          </form>
        </div>
      </div>
    );
  }

  // Dashboard God Mode SuperAdmin
  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-app)',
      color: 'var(--text-primary)',
      padding: '28px',
      fontFamily: 'var(--font-family)'
    }}>
      <div style={{ maxWidth: '1300px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        {/* TOP BAR */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
          paddingBottom: '20px',
          borderBottom: '1px solid var(--line)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'var(--crit-bg)',
              color: 'var(--crit)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid var(--crit-border)'
            }}>
              <ShieldAlert size={24} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
                  SUPERADMIN GOD MODE
                </h1>
                <span style={{ padding: '3px 10px', borderRadius: '999px', fontSize: '0.72rem', fontWeight: 700, background: 'var(--crit-bg)', color: 'var(--crit)', border: '1px solid var(--crit-border)' }}>
                  ● LIVE CONTROL ACTIVE
                </span>
              </div>
              <p style={{ margin: '2px 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Supervisione globale cross-tenant, gestione istanze isolate, telemetria e switch operatore.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              onClick={() => loadGodData()}
              disabled={refreshing}
              style={{
                padding: '8px 14px',
                borderRadius: '8px',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--line-strong)',
                color: 'var(--text-primary)',
                fontSize: '0.82rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              Aggiorna Telemetria
            </button>

            {onExit ? (
              <button
                onClick={onExit}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  background: 'var(--accent-bg)',
                  border: '1px solid var(--accent-border)',
                  color: 'var(--accent-text)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                <ArrowLeft size={14} /> Torna all'App
              </button>
            ) : (
              <a
                href="/"
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  background: 'var(--accent-bg)',
                  border: '1px solid var(--accent-border)',
                  color: 'var(--accent-text)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  textDecoration: 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                <ArrowLeft size={14} /> Torna all'App
              </a>
            )}
          </div>
        </div>

        {message && (
          <div style={{
            padding: '12px 16px',
            borderRadius: '10px',
            background: message.type === 'success' ? 'var(--ok-bg)' : 'var(--crit-bg)',
            border: `1px solid ${message.type === 'success' ? 'var(--ok-border)' : 'var(--crit-border)'}`,
            color: message.type === 'success' ? 'var(--ok)' : 'var(--crit)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            {message.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
            <span>{message.text}</span>
          </div>
        )}

        {/* EXECUTIVE KPI RIBBON */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px'
        }}>
          <div style={{ padding: '20px', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Server size={16} color="var(--accent-text)" /> AZIENDE / TENANT
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
              {overview?.total_tenants || tenants.length}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--ok)', marginTop: '4px' }}>
              100% Spazio e Dati Isolati
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <FileText size={16} color="var(--info)" /> FATTURE GLOBALI
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
              {overview?.total_invoices || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Totale documenti nel sistema
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <ShoppingCart size={16} color="var(--ok)" /> ORDINI TRACCIATI
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
              {overview?.total_orders || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Ordini d'acquisto emessi
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Users size={16} color="var(--warn)" /> OPERATORI / ADMIN
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
              {overview?.total_users || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Account attivi nel network
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)', border: '1px solid var(--line)' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Euro size={16} color="var(--ok)" /> VOLUME TRANSATO
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 600, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--ok)' }}>
              € {((overview?.total_spend_volume || 0) / 1000).toFixed(1)}k
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Imponibile complessivo
            </div>
          </div>
        </div>

        {/* TENANTS & CLIENT COMPANIES MANAGEMENT PANEL */}
        <div style={{
          padding: '24px',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card)',
          border: '1px solid var(--line)',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Server size={20} color="var(--crit)" /> Gestione Istanze Aziendali Clienti
              </h2>
              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Tutte le aziende clienti che utilizzano la piattaforma in modalità multi-tenant isolata.
              </p>
            </div>

            <button
              onClick={() => {
                setNewCompanyName('');
                setNewSlug('');
                setNewAdminEmail('');
                setNewAdminPassword('');
                setModalError(null);
                setShowCreateModal(true);
              }}
              style={{
                padding: '10px 18px',
                borderRadius: '10px',
                background: 'var(--crit)',
                color: 'var(--bg-app)',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: 'none'
              }}
            >
              <Plus size={16} /> Nuova Istanza Azienda
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {tenants.map(t => (
              <div
                key={t.id}
                style={{
                  padding: '18px 20px',
                  borderRadius: '12px',
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--line)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '16px'
                }}
              >
                {/* INFO AZIENDA */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '14px', minWidth: '260px' }}>
                  <div style={{
                    width: '46px',
                    height: '46px',
                    borderRadius: '12px',
                    background: t.id === 1 ? 'var(--accent-bg)' : 'var(--ok-bg)',
                    color: t.id === 1 ? 'var(--accent-text)' : 'var(--ok)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '1.2rem',
                    fontWeight: 700
                  }}>
                    {t.id === 1 ? '👑' : '🏢'}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ fontSize: '1.05rem', color: 'var(--text-primary)' }}>{t.company_name}</strong>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '6px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        background: t.id === 1 ? 'var(--accent-bg)' : 'var(--ok-bg)',
                        color: t.id === 1 ? 'var(--accent-text)' : 'var(--ok)'
                      }}>
                        {t.id === 1 ? 'Principale (Root)' : `Tenant #${t.id}`}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '4px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      <span>Slug: <code style={{ color: 'var(--text-primary)' }}>{t.slug}</code></span>
                      <span>•</span>
                      <span>Admin: <strong style={{ color: 'var(--text-primary)' }}>{t.admin_email}</strong></span>
                    </div>
                  </div>
                </div>

                {/* METRICHE AZIENDA */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '20px', fontSize: '0.8rem' }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '1rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{t.invoices_count}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Fatture</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '1rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{t.orders_count}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Ordini</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '1rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{t.users_count}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Utenti</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 600, color: 'var(--ok)', fontSize: '1rem', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>€ {t.spend_volume.toLocaleString('it-IT', { minimumFractionDigits: 2 })}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Imponibile</div>
                  </div>
                </div>

                {/* PULSANTI CONTROLLO & AZIONI */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <button
                    onClick={() => handleImpersonate(t)}
                    title="Accedi direttamente a questa azienda come amministratore"
                    style={{
                      padding: '8px 14px',
                      borderRadius: '8px',
                      background: 'var(--accent-bg)',
                      border: '1px solid var(--accent-border)',
                      color: 'var(--accent-text)',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px'
                    }}
                  >
                    <LogIn size={14} /> Accedi / Impersona
                  </button>

                  <button
                    onClick={() => copyCredentials(t)}
                    title="Copia credenziali di accesso per il cliente"
                    style={{
                      padding: '8px 12px',
                      borderRadius: '8px',
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--line-strong)',
                      color: copiedId === t.id ? 'var(--ok)' : 'var(--text-secondary)',
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    {copiedId === t.id ? <Check size={14} /> : <Copy size={14} />}
                    {copiedId === t.id ? 'Copiato!' : 'Credenziali'}
                  </button>

                  <button
                    onClick={() => {
                      setResetModalTenant(t);
                      setNewPasswordValue('');
                    }}
                    title="Resetta password admin di questa azienda"
                    style={{
                      padding: '8px 12px',
                      borderRadius: '8px',
                      background: 'var(--warn-bg)',
                      border: '1px solid var(--warn-border)',
                      color: 'var(--warn)',
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <Key size={14} /> Password
                  </button>

                  {t.id !== 1 && (
                    <button
                      onClick={() => handleDeleteTenant(t)}
                      title="Elimina azienda"
                      style={{
                        padding: '8px 10px',
                        borderRadius: '8px',
                        background: 'var(--crit-bg)',
                        border: '1px solid var(--crit-border)',
                        color: 'var(--crit)',
                        cursor: 'pointer'
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* SYSTEM STATUS & TELEMETRY FOOTER */}
        <div style={{
          padding: '18px 22px',
          borderRadius: '12px',
          background: 'var(--bg-inset)',
          border: '1px solid var(--line)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          fontSize: '0.78rem',
          color: 'var(--text-secondary)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={16} color="var(--ok)" />
            <span>Database PostgreSQL: <strong>Connesso & Operativo</strong></span>
            <span>•</span>
            <span>Isolamento Multi-Tenant: <strong>Attivo con scoping row-level</strong></span>
          </div>
          <div>
            Ultima telemetria: <strong>{new Date().toLocaleTimeString('it-IT')}</strong>
          </div>
        </div>

      </div>

      {/* MODAL CREA NUOVA AZIENDA CLIENTE */}
      {showCreateModal && (
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
          <div style={{
            width: '100%',
            maxWidth: '500px',
            background: 'var(--bg-card)',
            border: '1px solid var(--line-strong)',
            borderRadius: 'var(--radius-lg)',
            padding: '28px',
            boxShadow: 'var(--shadow-pop)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                <Plus size={20} color="var(--crit)" /> Attiva Nuova Istanza Azienda
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateTenant} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Nome Azienda / Ragione Sociale</label>
                <input
                  type="text"
                  placeholder="Es. Bar la sosta / Ristorante Marechiaro"
                  value={newCompanyName}
                  onChange={e => {
                    setNewCompanyName(e.target.value);
                    if (!newSlug) {
                      setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, ''));
                    }
                  }}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Slug Identificativo Univoco</label>
                <input
                  type="text"
                  placeholder="Es. barlasosta"
                  value={newSlug}
                  onChange={e => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Email Amministratore</label>
                <input
                  type="email"
                  placeholder="Es. ilaria@bar.it"
                  value={newAdminEmail}
                  onChange={e => setNewAdminEmail(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>Password Iniziale</label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={newAdminPassword}
                  onChange={e => setNewAdminPassword(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                  required
                />
              </div>

              {modalError && (
                <div style={{ padding: '10px 12px', borderRadius: '8px', background: 'var(--crit-bg)', color: 'var(--crit)', fontSize: '0.8rem' }}>
                  {modalError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  style={{ padding: '10px 16px', borderRadius: '8px', background: 'transparent', border: '1px solid var(--line-strong)', color: 'var(--text-secondary)', cursor: 'pointer' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={creatingTenant}
                  style={{
                    padding: '10px 18px',
                    borderRadius: '8px',
                    background: 'var(--crit)',
                    border: 'none',
                    color: 'var(--bg-app)',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }}
                >
                  {creatingTenant ? 'Attivazione...' : 'Crea e Abilita Azienda'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL RESET PASSWORD */}
      {resetModalTenant && (
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
          <div style={{
            width: '100%',
            maxWidth: '440px',
            background: 'var(--bg-card)',
            border: '1px solid var(--warn-border)',
            borderRadius: 'var(--radius-lg)',
            padding: '26px',
            boxShadow: 'var(--shadow-pop)'
          }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '1.15rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Key size={18} color="var(--warn)" /> Reset Password Admin
            </h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 16px' }}>
              Imposta una nuova password per l'amministratore di <strong>{resetModalTenant.company_name}</strong> ({resetModalTenant.admin_email}).
            </p>

            <form onSubmit={handleResetPassword} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <input
                type="text"
                placeholder="Nuova password..."
                value={newPasswordValue}
                onChange={e => setNewPasswordValue(e.target.value)}
                style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'var(--bg-inset)', border: '1px solid var(--line)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }}
                required
              />

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
                <button
                  type="button"
                  onClick={() => setResetModalTenant(null)}
                  style={{ padding: '8px 14px', borderRadius: '8px', background: 'transparent', border: '1px solid var(--line-strong)', color: 'var(--text-secondary)', cursor: 'pointer' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={resettingPassword}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '8px',
                    background: 'var(--warn)',
                    border: 'none',
                    color: 'var(--bg-app)',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }}
                >
                  {resettingPassword ? 'Salvataggio...' : 'Conferma Nuova Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
