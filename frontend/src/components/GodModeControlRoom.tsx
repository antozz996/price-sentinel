import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, Server, Users, FileText, ShoppingCart, 
  Euro, Key, Lock, RefreshCw, CheckCircle2, AlertCircle, Plus, 
  Trash2, LogIn, ArrowLeft, Copy, Check, ShieldCheck
} from 'lucide-react';
import { API_BASE } from '../api';

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
  // Token state: check url param or sessionStorage or default
  const [tokenInput, setTokenInput] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('token') || sessionStorage.getItem('god_mode_token') || 'sentinel_god_master_key_2026';
  });
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

      sessionStorage.setItem('god_mode_token', tokenToUse.trim());
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

  useEffect(() => {
    if (tokenInput) {
      verifyAndLoadData(tokenInput);
    }
  }, []);

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
      // Salva token nella sessione principale e ricarica
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
        background: 'radial-gradient(circle at center, #111827 0%, #030712 100%)',
        color: '#f3f4f6',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        fontFamily: 'Inter, system-ui, sans-serif'
      }}>
        <div style={{
          width: '100%',
          maxWidth: '440px',
          background: 'rgba(17, 24, 39, 0.8)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: '20px',
          padding: '36px 32px',
          boxShadow: '0 25px 50px -12px rgba(239, 68, 68, 0.25)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center'
        }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: '16px',
            background: 'rgba(239, 68, 68, 0.15)',
            color: '#ef4444',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '20px',
            border: '1px solid rgba(239, 68, 68, 0.3)'
          }}>
            <ShieldAlert size={32} />
          </div>

          <h2 style={{ fontSize: '1.5rem', fontWeight: 800, margin: '0 0 6px', letterSpacing: '-0.02em', color: '#f87171' }}>
            GOD MODE CONTROL ROOM
          </h2>
          <p style={{ fontSize: '0.82rem', color: '#9ca3af', margin: '0 0 24px' }}>
            Accesso riservato SuperAdmin per la supervisione globale multi-tenant e gestione istanze.
          </p>

          <form onSubmit={(e) => { e.preventDefault(); verifyAndLoadData(tokenInput); }} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {authError && (
              <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.2)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#ef4444', fontSize: '0.8rem', textAlign: 'left' }}>
                ⚠️ {authError}
              </div>
            )}

            <div style={{ textAlign: 'left' }}>
              <label style={{ display: 'block', fontSize: '0.78rem', color: '#9ca3af', marginBottom: '6px', fontWeight: 600 }}>
                MASTER SECRET TOKEN
              </label>
              <div style={{ position: 'relative' }}>
                <Key size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#6b7280' }} />
                <input
                  type="password"
                  value={tokenInput}
                  onChange={e => setTokenInput(e.target.value)}
                  placeholder="Inserisci Master Token..."
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '12px 12px 12px 38px',
                    background: 'rgba(0, 0, 0, 0.5)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '10px',
                    color: 'white',
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
                background: 'linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)',
                color: 'white',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.9rem',
                cursor: 'pointer',
                boxShadow: '0 4px 14px rgba(239, 68, 68, 0.4)',
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
                style={{ background: 'transparent', border: 'none', color: '#6b7280', fontSize: '0.8rem', cursor: 'pointer', marginTop: '4px' }}
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
      background: '#090d16',
      color: '#f3f4f6',
      padding: '28px',
      fontFamily: 'Inter, system-ui, sans-serif'
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
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(239, 68, 68, 0.15)',
              color: '#ef4444',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid rgba(239, 68, 68, 0.3)'
            }}>
              <ShieldAlert size={24} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h1 style={{ fontSize: '1.4rem', fontWeight: 800, margin: 0, letterSpacing: '-0.02em', color: 'white' }}>
                  SUPERADMIN GOD MODE
                </h1>
                <span style={{ padding: '3px 10px', borderRadius: '12px', fontSize: '0.72rem', fontWeight: 800, background: 'rgba(239, 68, 68, 0.2)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.4)' }}>
                  ● LIVE CONTROL ACTIVE
                </span>
              </div>
              <p style={{ margin: '2px 0 0', fontSize: '0.8rem', color: '#9ca3af' }}>
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
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                color: 'white',
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
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  color: '#60a5fa',
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
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.3)',
                  color: '#60a5fa',
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
            background: message.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            border: `1px solid ${message.type === 'success' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
            color: message.type === 'success' ? '#34d399' : '#f87171',
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
          <div style={{ padding: '20px', borderRadius: '14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
            <div style={{ fontSize: '0.78rem', color: '#9ca3af', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Server size={16} color="#60a5fa" /> AZIENDE / TENANT
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'white' }}>
              {overview?.total_tenants || tenants.length}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#34d399', marginTop: '4px' }}>
              100% Spazio e Dati Isolati
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: '14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
            <div style={{ fontSize: '0.78rem', color: '#9ca3af', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <FileText size={16} color="#a78bfa" /> FATTURE GLOBALI
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'white' }}>
              {overview?.total_invoices || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '4px' }}>
              Totale documenti nel sistema
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: '14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
            <div style={{ fontSize: '0.78rem', color: '#9ca3af', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <ShoppingCart size={16} color="#34d399" /> ORDINI TRACCIATI
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'white' }}>
              {overview?.total_orders || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '4px' }}>
              Ordini d'acquisto emessi
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: '14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
            <div style={{ fontSize: '0.78rem', color: '#9ca3af', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Users size={16} color="#f59e0b" /> OPERATORI / ADMIN
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'white' }}>
              {overview?.total_users || 0}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '4px' }}>
              Account attivi nel network
            </div>
          </div>

          <div style={{ padding: '20px', borderRadius: '14px', background: 'rgba(255, 255, 255, 0.03)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
            <div style={{ fontSize: '0.78rem', color: '#9ca3af', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Euro size={16} color="#10b981" /> VOLUME TRANSATO
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#34d399' }}>
              € {((overview?.total_spend_volume || 0) / 1000).toFixed(1)}k
            </div>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '4px' }}>
              Imponibile complessivo
            </div>
          </div>
        </div>

        {/* TENANTS & CLIENT COMPANIES MANAGEMENT PANEL */}
        <div style={{
          padding: '24px',
          borderRadius: '16px',
          background: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Server size={20} color="#ef4444" /> Gestione Istanze Aziendali Clienti
              </h2>
              <p style={{ margin: 0, fontSize: '0.8rem', color: '#9ca3af' }}>
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
                background: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
                color: 'white',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: '0 4px 14px rgba(239, 68, 68, 0.3)'
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
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.07)',
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
                    background: t.id === 1 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                    color: t.id === 1 ? '#60a5fa' : '#34d399',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '1.2rem',
                    fontWeight: 800
                  }}>
                    {t.id === 1 ? '👑' : '🏢'}
                  </div>

                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ fontSize: '1.05rem', color: 'white' }}>{t.company_name}</strong>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '6px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        background: t.id === 1 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                        color: t.id === 1 ? '#93c5fd' : '#6ee7b7'
                      }}>
                        {t.id === 1 ? 'Principale (Root)' : `Tenant #${t.id}`}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '4px', fontSize: '0.75rem', color: '#9ca3af' }}>
                      <span>Slug: <code style={{ color: '#f3f4f6' }}>{t.slug}</code></span>
                      <span>•</span>
                      <span>Admin: <strong style={{ color: '#e5e7eb' }}>{t.admin_email}</strong></span>
                    </div>
                  </div>
                </div>

                {/* METRICHE AZIENDA */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '20px', fontSize: '0.8rem' }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700, color: 'white', fontSize: '1rem' }}>{t.invoices_count}</div>
                    <div style={{ fontSize: '0.7rem', color: '#9ca3af' }}>Fatture</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700, color: 'white', fontSize: '1rem' }}>{t.orders_count}</div>
                    <div style={{ fontSize: '0.7rem', color: '#9ca3af' }}>Ordini</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700, color: 'white', fontSize: '1rem' }}>{t.users_count}</div>
                    <div style={{ fontSize: '0.7rem', color: '#9ca3af' }}>Utenti</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontWeight: 700, color: '#34d399', fontSize: '1rem' }}>€ {t.spend_volume.toLocaleString('it-IT', { minimumFractionDigits: 2 })}</div>
                    <div style={{ fontSize: '0.7rem', color: '#9ca3af' }}>Imponibile</div>
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
                      background: 'rgba(59, 130, 246, 0.2)',
                      border: '1px solid rgba(59, 130, 246, 0.4)',
                      color: '#93c5fd',
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
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid rgba(255, 255, 255, 0.1)',
                      color: copiedId === t.id ? '#34d399' : '#d1d5db',
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
                      background: 'rgba(245, 158, 11, 0.15)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      color: '#fbbf24',
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
                        background: 'rgba(239, 68, 68, 0.15)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        color: '#f87171',
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
          background: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          fontSize: '0.78rem',
          color: '#9ca3af'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={16} color="#34d399" />
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
          background: 'rgba(0, 0, 0, 0.8)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '500px',
            background: '#111827',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '18px',
            padding: '28px',
            boxShadow: '0 25px 50px -12px rgba(239, 68, 68, 0.35)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '1.2rem', color: 'white' }}>
                <Plus size={20} color="#ef4444" /> Attiva Nuova Istanza Azienda
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                style={{ background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateTenant} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#9ca3af', marginBottom: '4px' }}>Nome Azienda / Ragione Sociale</label>
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
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#9ca3af', marginBottom: '4px' }}>Slug Identificativo Univoco</label>
                <input
                  type="text"
                  placeholder="Es. barlasosta"
                  value={newSlug}
                  onChange={e => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#9ca3af', marginBottom: '4px' }}>Email Amministratore</label>
                <input
                  type="email"
                  placeholder="Es. ilaria@bar.it"
                  value={newAdminEmail}
                  onChange={e => setNewAdminEmail(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#9ca3af', marginBottom: '4px' }}>Password Iniziale</label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={newAdminPassword}
                  onChange={e => setNewAdminPassword(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }}
                  required
                />
              </div>

              {modalError && (
                <div style={{ padding: '10px 12px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.2)', color: '#f87171', fontSize: '0.8rem' }}>
                  {modalError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  style={{ padding: '10px 16px', borderRadius: '8px', background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: '#d1d5db', cursor: 'pointer' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={creatingTenant}
                  style={{
                    padding: '10px 18px',
                    borderRadius: '8px',
                    background: '#ef4444',
                    border: 'none',
                    color: 'white',
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
          background: 'rgba(0, 0, 0, 0.8)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '440px',
            background: '#111827',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: '16px',
            padding: '26px'
          }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '1.15rem', color: 'white', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Key size={18} color="#fbbf24" /> Reset Password Admin
            </h3>
            <p style={{ fontSize: '0.8rem', color: '#9ca3af', margin: '0 0 16px' }}>
              Imposta una nuova password per l'amministratore di <strong>{resetModalTenant.company_name}</strong> ({resetModalTenant.admin_email}).
            </p>

            <form onSubmit={handleResetPassword} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <input
                type="text"
                placeholder="Nuova password..."
                value={newPasswordValue}
                onChange={e => setNewPasswordValue(e.target.value)}
                style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }}
                required
              />

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
                <button
                  type="button"
                  onClick={() => setResetModalTenant(null)}
                  style={{ padding: '8px 14px', borderRadius: '8px', background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: '#d1d5db', cursor: 'pointer' }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={resettingPassword}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '8px',
                    background: '#f59e0b',
                    border: 'none',
                    color: '#111827',
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
