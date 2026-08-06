import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, FileSpreadsheet, LayoutDashboard, Settings, FileUp, FileText, Lock, Mail, Grid, Tag, BarChart2, Menu, X, Award, TrendingUp, EyeOff, Percent, Layers, GitCompareArrows, HandCoins, BellRing, ListChecks, ChevronDown } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Dashboard from './components/Dashboard'
import ValidationRoom from './components/ValidationRoom'
import PriceListManager from './components/PriceListManager'
import ManualUpload from './components/ManualUpload'
import FattureList from './components/FattureList'
import SettingsPage from './components/SettingsPage'
import OrderOptimizer from './components/OrderOptimizer'
import SkuManager from './components/SkuManager'
import SentinelCopilot from './components/SentinelCopilot'
import ProductConsumptionReport from './components/ProductConsumptionReport'
import CrossSupplierMatrix from './components/CrossSupplierMatrix'
import TopProductsPriceList from './components/TopProductsPriceList'
import PriceTrendAnalyzer from './components/PriceTrendAnalyzer'
import ExcludedProducts from './components/ExcludedProducts'
import CommercialAgreements from './components/CommercialAgreements'
import ProductIdentityManager from './components/ProductIdentityManager'
import OrderReconciliations from './components/OrderReconciliations'
import DisputeManagement from './components/DisputeManagement'
import OperationalAlerts from './components/OperationalAlerts'
import ClientOnboarding from './components/ClientOnboarding'
import { API_BASE, fetchWithAuth, getHeaders } from './api'

type UserProfile = {
  id: number
  email: string
  ruolo: 'admin' | 'manager'
  location_id?: number | null
}

type NavItem = {
  id: string
  label: string
  icon: LucideIcon
  adminOnly?: boolean
}

type NavSection = {
  id: string
  label: string
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    id: 'operations',
    label: 'Operatività',
    items: [
      { id: 'upload', label: 'Carica fatture', icon: FileUp },
      { id: 'fatture', label: 'Registro fatture', icon: FileText },
      { id: 'validation', label: 'Anomalie da validare', icon: AlertTriangle },
      { id: 'reconciliations', label: 'Riconciliazioni', icon: GitCompareArrows },
      { id: 'disputes', label: 'Contestazioni', icon: HandCoins },
      { id: 'monitor', label: 'Monitor operativo', icon: BellRing },
    ],
  },
  {
    id: 'purchasing',
    label: 'Acquisti',
    items: [
      { id: 'listini', label: 'Listini master', icon: FileSpreadsheet, adminOnly: true },
      { id: 'accordicommerciali', label: 'Accordi commerciali', icon: Percent, adminOnly: true },
    ],
  },
  {
    id: 'analytics',
    label: 'Analisi',
    items: [
      { id: 'topproducts', label: 'Top prodotti', icon: Award, adminOnly: true },
      { id: 'crosssupplier', label: 'Comparazione fornitori', icon: Grid, adminOnly: true },
      { id: 'productconsumption', label: 'Consumi per prodotto', icon: BarChart2, adminOnly: true },
      { id: 'priceanalysis', label: 'Oscillazioni prezzi', icon: TrendingUp },
    ],
  },
  {
    id: 'catalog',
    label: 'Catalogo',
    items: [
      { id: 'productidentity', label: 'Prodotti e alias', icon: Layers, adminOnly: true },
      { id: 'skumanager', label: 'Gestione SKU', icon: Tag, adminOnly: true },
      { id: 'excludedproducts', label: 'Prodotti esclusi', icon: EyeOff, adminOnly: true },
    ],
  },
  {
    id: 'administration',
    label: 'Amministrazione',
    items: [
      { id: 'onboarding', label: 'Configurazione sede', icon: ListChecks, adminOnly: true },
      { id: 'settings', label: 'Impostazioni', icon: Settings, adminOnly: true },
    ],
  },
]

const ADMIN_ONLY_TABS = new Set(
  [
    ...NAV_SECTIONS.flatMap(section => section.items.filter(item => item.adminOnly).map(item => item.id)),
    // The legacy order emitter stays implemented but is intentionally absent from
    // navigation while LiquidStock remains the authoritative ordering system.
    'ordini',
  ],
)

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [isAuth, setIsAuth] = useState(false)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    operations: true,
    purchasing: false,
    analytics: false,
    catalog: false,
    administration: false,
  })

  // Login form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)

  useEffect(() => {
    // Listen for unauthorized 401 events from fetchWithAuth
    const handleUnauthorized = () => {
      setIsAuth(false);
      setProfile(null);
    };
    window.addEventListener('unauthorized', handleUnauthorized);
    return () => window.removeEventListener('unauthorized', handleUnauthorized);
  }, []);

  useEffect(() => {
    if (!isAuth) return

    let cancelled = false
    fetchWithAuth('/auth/me')
      .then(data => {
        if (!cancelled) setProfile(data as UserProfile)
      })
      .catch(() => {
        if (!cancelled) setProfile(null)
      })

    return () => {
      cancelled = true
    }
  }, [isAuth])

  useEffect(() => {
    if (profile?.ruolo === 'manager' && (activeTab === 'dashboard' || ADMIN_ONLY_TABS.has(activeTab))) {
      setActiveTab('validation')
    }
  }, [activeTab, profile])

  useEffect(() => {
    const activeSection = NAV_SECTIONS.find(section =>
      section.items.some(item => item.id === activeTab),
    )
    if (activeSection) {
      setOpenSections(current => ({ ...current, [activeSection.id]: true }))
    }
  }, [activeTab])

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
        setLoginError(
          typeof data?.detail === 'string'
            ? data.detail
            : 'Email o password non validi.',
        );
      }
    } catch {
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

    if (!profile) {
      return <div style={{ color: 'var(--text-secondary)', padding: '24px' }}>Caricamento profilo…</div>
    }
    
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'upload': return <ManualUpload isAdmin={profile.ruolo === 'admin'} />;
      case 'fatture': return <FattureList />;
      case 'validation': return <ValidationRoom />;
      case 'listini': return <PriceListManager />;
      case 'topproducts': return <TopProductsPriceList />;
      case 'crosssupplier': return <CrossSupplierMatrix />;
      case 'productconsumption': return <ProductConsumptionReport />;
      case 'priceanalysis': return <PriceTrendAnalyzer />;
      case 'ordini': return <OrderOptimizer />;
      case 'skumanager': return <SkuManager />;
      case 'productidentity': return <ProductIdentityManager />;
      case 'reconciliations': return <OrderReconciliations isAdmin={profile?.ruolo === 'admin'} />;
      case 'disputes': return <DisputeManagement />;
      case 'monitor': return <OperationalAlerts />;
      case 'onboarding': return <ClientOnboarding />;
      case 'excludedproducts': return <ExcludedProducts />;
      case 'accordicommerciali': return <CommercialAgreements />;
      case 'settings': return <SettingsPage />;
      default: return <Dashboard />;
    }
  }

  const getHeaderInfo = () => {
    switch (activeTab) {
      case 'dashboard': return { title: 'Panoramica', sub: 'Indicatori economici e operativi del gruppo' };
      case 'upload': return { title: 'Carica Fatture', sub: 'Ingestione manuale file XML e archivi ZIP' };
      case 'fatture': return { title: 'Registro Fatture', sub: 'Visualizza, filtra e gestisci tutte le fatture' };
      case 'validation': return { title: 'Anomalie da validare', sub: 'Controllo anomalie e gestione rincari' };
      case 'listini': return { title: 'Gestione Listini Master', sub: 'Importazione e versioning prezzi concordati' };
      case 'topproducts': return { title: 'Top prodotti', sub: 'Analizza prezzi e volumi dei prodotti più acquistati' };
      case 'crosssupplier': return { title: 'Comparazione Fornitori', sub: 'Matrice incrociata dei prezzi per fornitore' };
      case 'productconsumption': return { title: 'Analisi Consumi per Prodotto', sub: 'Rapporto di consumo aggregato e andamento storico dei volumi di acquisto' };
      case 'priceanalysis': return { title: 'Analisi Oscillazioni Prezzi', sub: 'Confronta l\'andamento storico e le oscillazioni dei prezzi di acquisto' };
      case 'ordini': return { title: 'Ottimizzatore Ordini d\'Acquisto', sub: 'Routing intelligente dei fornitori, blocco contratti e spesa spot' };
      case 'skumanager': return { title: 'Gestione SKU', sub: 'Organizza e rinomina gli SKU interni del catalogo' };
      case 'productidentity': return { title: 'Prodotti e alias', sub: 'Gestione catalogo canonico, alias e proposte di matching' };
      case 'reconciliations': return { title: 'Riconciliazioni ordini', sub: 'Confronto ordine, ricezione e fattura con revisione manuale' };
      case 'disputes': return { title: 'Contestazioni e recuperi', sub: 'Comunicazioni fornitori, risposte e note di credito tracciate' };
      case 'monitor': return { title: 'Monitor operativo', sub: 'Scadenze, anomalie importanti e integrazioni da verificare' };
      case 'onboarding': return { title: 'Configurazione sede', sub: 'Attivazione guidata e soglie esplicite per ogni sede' };
      case 'excludedproducts': return { title: 'Prodotti Esclusi', sub: 'Gestisci la blacklist globale dei prodotti da escludere dalle analisi' };
      case 'accordicommerciali': return { title: 'Accordi Commerciali (PFA)', sub: 'Rientri di fine anno, volumi d\'acquisto e calcolo prezzi netti' };
      case 'settings': return { title: 'Impostazioni', sub: 'Configurazione sistema e gestione utenti' };
      default: return { title: 'Price Sentinel', sub: 'Audit System' };
    }
  }

  const info = getHeaderInfo();

  return (
    <div className="app-container">
      {/* Mobile Sidebar Backdrop */}
      {mobileSidebarOpen && (
        <div 
          className="sidebar-backdrop"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Sidebar Navigation */}
      <aside className={`sidebar ${mobileSidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header" style={{ marginBottom: '24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Activity color="white" size={20} />
            </div>
            <h2 style={{ fontSize: '1.2rem', margin: 0, fontWeight: 700, letterSpacing: '1px' }}>PRICE SENTINEL</h2>
          </div>
          {/* Mobile Close Drawer Button */}
          <button
            className="mobile-sidebar-close" 
            onClick={() => setMobileSidebarOpen(false)}
            style={{ display: 'none' }}
          >
            <X size={20} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Navigazione principale">
          {profile?.ruolo === 'admin' && (
            <button
              className={`sidebar-nav-item ${activeTab === 'dashboard' ? 'is-active' : ''}`}
              onClick={() => { setActiveTab('dashboard'); setMobileSidebarOpen(false); }}
            >
              <LayoutDashboard size={18} /> Panoramica
            </button>
          )}

          {NAV_SECTIONS.map(section => {
            const visibleItems = section.items.filter(item => !item.adminOnly || profile?.ruolo === 'admin')
            if (visibleItems.length === 0) return null

            const isOpen = openSections[section.id]
            const hasActiveItem = visibleItems.some(item => item.id === activeTab)

            return (
              <div className="sidebar-section" key={section.id}>
                <button
                  className={`sidebar-section-toggle ${hasActiveItem ? 'has-active-item' : ''}`}
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={`nav-section-${section.id}`}
                  onClick={() => setOpenSections(current => ({
                    ...current,
                    [section.id]: !current[section.id],
                  }))}
                >
                  <span>{section.label}</span>
                  <ChevronDown className={isOpen ? 'is-open' : ''} size={16} />
                </button>

                {isOpen && (
                  <div className="sidebar-section-items" id={`nav-section-${section.id}`}>
                    {visibleItems.map(item => {
                      const Icon = item.icon
                      return (
                        <button
                          className={`sidebar-nav-item ${activeTab === item.id ? 'is-active' : ''}`}
                          key={item.id}
                          onClick={() => { setActiveTab(item.id); setMobileSidebarOpen(false); }}
                        >
                          <Icon size={17} /> {item.label}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user-summary">
            <span>{profile ? (profile.ruolo === 'admin' ? 'Amministratore' : 'Manager') : 'Profilo'}</span>
            <small>{profile?.email || 'Profilo in caricamento…'}</small>
          </div>
        </div>
      </aside>

      {/* Main UI Area */}
      <main className="main-content">
        {/* Background glow effects */}
        <div style={{ position: 'absolute', top: '-10%', right: '-5%', width: '400px', height: '400px', background: 'var(--accent-blue)', filter: 'blur(150px)', opacity: 0.15, pointerEvents: 'none', borderRadius: '50%' }}></div>
        <div style={{ position: 'absolute', bottom: '-10%', left: '20%', width: '300px', height: '300px', background: 'var(--status-red)', filter: 'blur(150px)', opacity: 0.1, pointerEvents: 'none', borderRadius: '50%' }}></div>

        <header className="app-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '40px', position: 'relative', zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {/* Hamburger button shown ONLY on mobile */}
            <button 
              className="hamburger-btn" 
              onClick={() => setMobileSidebarOpen(true)}
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                width: '40px',
                height: '40px',
                display: 'none',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'white',
                cursor: 'pointer',
                transition: 'var(--transition-smooth)'
              }}
            >
              <Menu size={20} />
            </button>
            
            <div>
              <h1 className="header-title" style={{ fontSize: '2rem', marginBottom: '8px' }}>{info.title}</h1>
              <p className="header-subtitle" style={{ color: 'var(--text-secondary)' }}>{info.sub}</p>
            </div>
          </div>
          
          <div className="header-profile" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div className="profile-info" style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 600 }}>{profile ? (profile.ruolo === 'admin' ? 'Amministratore' : 'Manager') : 'Profilo'}</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{profile?.email || 'Profilo in caricamento…'}</div>
            </div>
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'var(--bg-glass)', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {profile?.email?.charAt(0).toUpperCase() || '…'}
            </div>
          </div>
        </header>

        {/* Dynamic Content */}
        <div style={{ position: 'relative', zIndex: 1 }}>
          {renderContent()}
        </div>
      </main>

      {/* Global AI Copilot */}
      <SentinelCopilot />
    </div>
  )
}
