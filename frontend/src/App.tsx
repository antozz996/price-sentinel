import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, FileSpreadsheet, LayoutDashboard, Settings, FileUp } from 'lucide-react'
import Dashboard from './components/Dashboard'
import ValidationRoom from './components/ValidationRoom'
import PriceListManager from './components/PriceListManager'
import ManualUpload from './components/ManualUpload'
import { API_BASE } from './api'

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [isAuth, setIsAuth] = useState(false)

  useEffect(() => {
    async function autoLogin() {
      try {
        const res = await fetch(`${API_BASE}/auth/login`, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'bypass-tunnel-reminder': 'true'
          },
          body: JSON.stringify({ email: 'admin@pricesentinel.it', password: 'admin2025!' })
        });
        const data = await res.json();
        if (data.access_token) {
          localStorage.setItem('token', data.access_token);
          setIsAuth(true);
        }
      } catch (err) {
        console.error('Auto-login failed', err);
      }
    }
    
    if (!localStorage.getItem('token')) {
      autoLogin();
    } else {
      setIsAuth(true);
    }
  }, []);

  const renderContent = () => {
    if (!isAuth) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>Autenticazione in corso...</div>;
    
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'validation': return <ValidationRoom />;
      case 'listini': return <PriceListManager />;
      case 'upload': return <ManualUpload />;
      default: return <Dashboard />;
    }
  }

  const getHeaderInfo = () => {
    switch (activeTab) {
      case 'dashboard': return { title: 'Intelligence Overview', sub: 'Business Insights & KPI del Gruppo' };
      case 'validation': return { title: 'Stanza di Validazione', sub: 'Controllo anomalie e gestione rincari' };
      case 'listini': return { title: 'Gestione Listini Master', sub: 'Importazione e versioning prezzi concordati' };
      case 'upload': return { title: 'Carica Fatture', sub: 'Ingestione manuale file XML e archivi ZIP' };
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
        </nav>
        
        <div style={{ marginTop: 'auto' }}>
          <button className="btn" style={{ width: '100%', justifyContent: 'flex-start', background: 'transparent', border: 'none', color: 'var(--text-secondary)' }}>
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

