import { useState, useEffect } from 'react';
import { User, Shield, Database, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';
import { API_BASE, getHeaders } from '../api';

interface UserInfo {
  id: number;
  email: string;
  ruolo: string;
  attivo: boolean;
}

export default function SettingsPage() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [dbStats, setDbStats] = useState<any>(null);
  const [message] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const headers = getHeaders();

  useEffect(() => {
    const controller = new AbortController();
    loadUsers(controller.signal);
    loadDbStats(controller.signal);
    return () => controller.abort();
  }, []);

  async function loadUsers(signal?: AbortSignal) {
    try {
      const res = await fetch(`${API_BASE}/utenti/`, { headers, signal });
      const data = await res.json();
      if (Array.isArray(data)) setUsers(data);
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  }

  async function loadDbStats(signal?: AbortSignal) {
    try {
      const res = await fetch(`${API_BASE}/health`, { headers, signal });
      const data = await res.json();
      setDbStats(data);
    } catch (e: any) {
      if (e.name !== 'AbortError') console.error(e);
    }
  }

  function handleLogout() {
    localStorage.removeItem('token');
    window.location.reload();
  }

  const cardStyle: React.CSSProperties = {
    padding: '24px', borderRadius: '12px',
    background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)'
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '900px' }}>

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
        <button className="btn" onClick={() => loadDbStats()} style={{ marginTop: '16px', gap: '8px', background: 'transparent', border: '1px solid var(--border-glass)' }}>
          <RefreshCw size={14} /> Aggiorna Stato
        </button>
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
