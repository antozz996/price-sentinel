import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, FileSpreadsheet, LayoutDashboard, Settings, FileUp, FileText, Lock, Mail, Grid } from 'lucide-react'
import Dashboard from './components/Dashboard'
import ValidationRoom from './components/ValidationRoom'
import PriceListManager from './components/PriceListManager'
import ManualUpload from './components/ManualUpload'
import FattureList from './components/FattureList'
import SettingsPage from './components/SettingsPage'
import CrossLocationMatrix from './components/CrossLocationMatrix'
import { API_BASE, getHeaders } from './api'

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [isAuth, setIsAuth] = useState(false)

  // Login form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)

  useEffect(() => {
    // Listen for unauthorized 401 events from fetchWithAuth
    const handleUnauthorized = () => {
      setIsAuth(false);
    };
    window.addEventListener('unauthorized', handleUnauthorized);
    return () => window.removeEventListener('unauthorized', handleUnauthorized);
  }, []);

  useEffect(() => {
    async function autoLogin() {
      // Check if we are in DEV and have the DEV login credentials set in env
      const devEmail = (import.meta as any).env?.VITE_DEV_EMAIL;
      const devPassword = (import.meta as any).env?.VITE_DEV_PASSWORD;

      if ((import.meta as any).env?.DEV && devEmail && devPassword) {
        try {
          const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ email: devEmail, password: devPassword })
          });
          const data = await res.json();
          if (res.ok && data.access_token) {
            localStorage.setItem('token', data.access_token);
            setIsAuth(true);
          }
        } catch (err) {
          console.error('DEV Auto-login failed', err);
        }
      }
    }
    
    if (!localStorage.getItem('token')) {
      autoLogin();
    } else {
      setIsAuth(true);
    }
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoggingIn(true);
    setLoginError(null);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok && data.access_token) {
        localStorage.setItem('token', data.access_token);
        setIsAuth(true);
      } else {
        setLoginError(data.detail || 'Email o password errati.');
      }
    } catch (err) {
      setLoginError('Impossibile connettersi al server.');
    } finally {
      setLoggingIn(false);
    }
  };

  const renderContent = () => {
    if (!isAuth) {
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          background: 'radial-gradient(circle at center, #13131c 0%, #0a0a0f 100%)',
          padding: '20px',
          width: '100vw',
          position: 'fixed',
          top: 0,
          left: 0,
          zIndex: 9999
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '420px',
            padding: '40px',
            display: 'flex',
            boxSizing: 'border-box',
            flexDirection: 'column',
            gap: '24px',
            boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
            border: '1px solid rgba(255,255,255,0.06)'
          }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{
                display: 'inline-flex',
                padding: '12px',
                borderRadius: '12px',
                background: 'rgba(59, 130, 246, 0.1)',
                color: 'var(--accent-blue)',
                marginBottom: '16px',
                border: '1px solid rgba(59, 130, 246, 0.2)'
              }}>
                <Activity size={32} />
              </div>
              <h2 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '8px', letterSpacing: '-0.03em' }}>Price Sentinel</h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Accedi al portale di audit fatture</p>
            </div>

            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {loginError && (
                <div style={{
                  padding: '12px',
                  borderRadius: '8px',
                  background: 'var(--status-red-bg)',
                  color: 'var(--status-red)',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  fontSize: '0.85rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <AlertTriangle size={16} />
                  {loginError}
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Email</label>
                <div style={{ position: 'relative' }}>
                  <Mail size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                  <input
                    type="email"
                    required
                    placeholder="admin@pricesentinel.it"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '12px 12px 12px 38px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
                      outline: 'none',
                      fontSize: '0.9rem',
                      transition: 'var(--transition-smooth)'
                    }}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Password</label>
                <div style={{ position: 'relative' }}>
                  <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                  <input
                    type="password"
                    required
                    placeholder="••••••••"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '12px 12px 12px 38px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      color: 'white',
                      outline: 'none',
                      fontSize: '0.9rem',
                      transition: 'var(--transition-smooth)'
                    }}
                  />
                </div>
              </div>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={loggingIn}
                style={{
                  width: '100%',
                  padding: '14px',
                  fontSize: '0.95rem',
                  justifyContent: 'center',
                  marginTop: '10px'
                }}
              >
                {loggingIn ? 'Accesso in corso...' : 'Accedi'}
              </button>
            </form>
          </div>
        </div>
      );
    }
    
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'upload': return <ManualUpload />;
      case 'fatture': return <FattureList />;
      case 'validation': return <ValidationRoom />;
      case 'listini': return <PriceListManager />;
      case 'crosslocation': return <CrossLocationMatrix />;
      case 'settings': return <SettingsPage />;
      default: return <Dashboard />;
    }
  }

  const getHeaderInfo = () => {
    switch (activeTab) {
      case 'dashboard': return { title: 'Intelligence Overview', sub: 'Business Insights & KPI del Gruppo' };
      case 'upload': return { title: 'Carica Fatture', sub: 'Ingestione manuale file XML e archivi ZIP' };
      case 'fatture': return { title: 'Registro Fatture', sub: 'Visualizza, filtra e gestisci tutte le fatture' };
      case 'validation': return { title: 'Stanza di Validazione', sub: 'Controllo anomalie e gestione rincari' };
      case 'listini': return { title: 'Gestione Listini Master', sub: 'Importazione e versioning prezzi concordati' };
      case 'crosslocation': return { title: 'Analisi Comparativa Sedi', sub: 'Matrice comparativa prezzi d\'acquisto e Vendor Passport' };
      case 'settings': return { title: 'Impostazioni', sub: 'Configurazione sistema e gestione utenti' };
      default: return { title: 'Price Sentinel', sub: 'Audit System' };
    }
  }

  const info = getHeaderInfo();

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div style={{ marginBottom: '40px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Activity color="white" size={20} />
          </div>
          <h2 style={{ fontSize: '1.2rem', margin: 0, fontWeight: 700, letterSpacing: '1px' }}>PRICE SENTINEL</h2>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <button 
            className={`btn ${activeTab === 'dashboard' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('dashboard')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'dashboard' ? '' : 'transparent', border: 'none' }}
          >
            <LayoutDashboard size={18} /> Overview
          </button>
          
          <button 
            className={`btn ${activeTab === 'upload' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('upload')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'upload' ? '' : 'transparent', border: 'none' }}
          >
            <FileUp size={18} /> Carica Fatture
          </button>

          <button 
            className={`btn ${activeTab === 'fatture' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('fatture')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'fatture' ? '' : 'transparent', border: 'none' }}
          >
            <FileText size={18} /> Registro Fatture
          </button>

          <button 
            className={`btn ${activeTab === 'validation' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('validation')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'validation' ? '' : 'transparent', border: 'none' }}
          >
            <AlertTriangle size={18} /> Validazione
            <span className="badge badge-red" style={{ marginLeft: 'auto' }}>!</span>
          </button>
          
          <button 
            className={`btn ${activeTab === 'listini' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('listini')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'listini' ? '' : 'transparent', border: 'none' }}
          >
            <FileSpreadsheet size={18} /> Listini Master
          </button>

          <button 
            className={`btn ${activeTab === 'crosslocation' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('crosslocation')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'crosslocation' ? '' : 'transparent', border: 'none' }}
          >
            <Grid size={18} /> Analisi Incrociata
          </button>
        </nav>
        
        <div style={{ marginTop: 'auto' }}>
          <button 
            className={`btn ${activeTab === 'settings' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('settings')}
            style={{ width: '100%', justifyContent: 'flex-start', background: activeTab === 'settings' ? '' : 'transparent', border: 'none', color: activeTab === 'settings' ? 'white' : 'var(--text-secondary)' }}
          >
            <Settings size={18} /> Settings
          </button>
        </div>
      </aside>

      {/* Main UI Area */}
      <main className="main-content">
        {/* Background glow effects */}
        <div style={{ position: 'absolute', top: '-10%', right: '-5%', width: '400px', height: '400px', background: 'var(--accent-blue)', filter: 'blur(150px)', opacity: 0.15, pointerEvents: 'none', borderRadius: '50%' }}></div>
        <div style={{ position: 'absolute', bottom: '-10%', left: '20%', width: '300px', height: '300px', background: 'var(--status-red)', filter: 'blur(150px)', opacity: 0.1, pointerEvents: 'none', borderRadius: '50%' }}></div>

        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '40px', position: 'relative', zIndex: 1 }}>
          <div>
            <h1 style={{ fontSize: '2rem', marginBottom: '8px' }}>{info.title}</h1>
            <p style={{ color: 'var(--text-secondary)' }}>{info.sub}</p>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 600 }}>C.E.O. Direction</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>admin@pricesentinel.it</div>
            </div>
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'var(--bg-glass)', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              A
            </div>
          </div>
        </header>

        {/* Dynamic Content */}
        <div style={{ position: 'relative', zIndex: 1 }}>
          {renderContent()}
        </div>
      </main>
    </div>
  )
}
