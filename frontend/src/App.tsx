import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, FileSpreadsheet, LayoutDashboard, Settings, FileUp, FileText, Lock, Mail, Grid, Tag, BarChart2, Menu, X, Award, TrendingUp, EyeOff, Percent, Layers, GitCompareArrows, HandCoins, BellRing, ListChecks, ChevronDown, Boxes, ShoppingCart, Bell, ClipboardList, PackageCheck, Star } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Dashboard from './components/Dashboard'
import ValidationRoom from './components/ValidationRoom'
import PriceListManager from './components/PriceListManager'
import ManualUpload from './components/ManualUpload'
import FattureList from './components/FattureList'
import SettingsPage from './components/SettingsPage'
import SkuManager from './components/SkuManager'
import ProductConsumptionReport from './components/ProductConsumptionReport'
import SmartPriceSheet from './components/SmartPriceSheet'
import TopProductsPriceList from './components/TopProductsPriceList'
import PriceTrendAnalyzer from './components/PriceTrendAnalyzer'
import ExcludedProducts from './components/ExcludedProducts'
import CommercialAgreements from './components/CommercialAgreements'
import ProductIdentityManager from './components/ProductIdentityManager'
import CategorySupplierManager from './components/CategorySupplierManager'
import OrderReconciliations from './components/OrderReconciliations'
import DisputeManagement from './components/DisputeManagement'
import OperationalAlerts from './components/OperationalAlerts'
import ClientOnboarding from './components/ClientOnboarding'
import SectorOrderBuilder from './components/SectorOrderBuilder'
import OrderRegistry from './components/OrderRegistry'
import GoodsReceipt from './components/GoodsReceipt'
import ProductReviewPage from './components/ProductReviewPage'
import NotificationCenterModal from './components/NotificationCenterModal'
import GodModeControlRoom from './components/GodModeControlRoom'
import { API_BASE, fetchWithAuth, getHeaders } from './api'

type UserProfile = {
  id: number
  email: string
  nome_completo?: string | null
  ruolo: 'admin' | 'manager'
  ruolo_dettagliato?: string | null
  settore_abilitato?: string | null
  location_id?: number | null
  tenant_id?: number | null
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
      { id: 'upload', label: 'Carica fatture', icon: FileUp, adminOnly: true },
      { id: 'fatture', label: 'Registro fatture', icon: FileText },
      { id: 'validation', label: 'Anomalie da validare', icon: AlertTriangle, adminOnly: true },
      { id: 'reconciliations', label: 'Riconciliazioni', icon: GitCompareArrows, adminOnly: true },
      { id: 'disputes', label: 'Contestazioni', icon: HandCoins, adminOnly: true },
      { id: 'monitor', label: 'Monitor operativo', icon: BellRing, adminOnly: true },
    ],
  },
  {
    id: 'purchasing',
    label: 'Acquisti',
    items: [
      { id: 'sectororders', label: 'Sviluppo ordini settore', icon: ShoppingCart },
      { id: 'goodsreceipt', label: 'Ricezione merci', icon: PackageCheck },
      { id: 'orderregistry', label: 'Registro ordini', icon: ClipboardList },
      { id: 'productreviews', label: 'Recensioni prodotti', icon: Star },
      { id: 'listini', label: 'Listini master', icon: FileSpreadsheet, adminOnly: true },
      { id: 'accordicommerciali', label: 'Accordi commerciali', icon: Percent, adminOnly: true },
    ],
  },
  {
    id: 'analytics',
    label: 'Analisi',
    items: [
      { id: 'topproducts', label: 'Top prodotti', icon: Award, adminOnly: true },
      { id: 'crosssupplier', label: 'Listino Smart', icon: Grid },
      { id: 'productconsumption', label: 'Consumi per prodotto', icon: BarChart2, adminOnly: true },
      { id: 'priceanalysis', label: 'Oscillazioni prezzi', icon: TrendingUp },
    ],
  },
  {
    id: 'catalog',
    label: 'Catalogo',
    items: [
      { id: 'categories', label: 'Categorie e fornitori', icon: Boxes, adminOnly: true },
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

export function isItemPermitted(item: NavItem, profile: UserProfile | null): boolean {
  if (!profile) return false;
  if (profile.ruolo === 'admin' || profile.ruolo_dettagliato === 'admin') return true;

  const det = profile.ruolo_dettagliato || 'manager_sede';
  if (det.startsWith('responsabile_')) {
    return (
      item.id === 'sectororders' ||
      item.id === 'orderregistry' ||
      item.id === 'goodsreceipt' ||
      item.id === 'productreviews' ||
      item.id === 'fatture' ||
      item.id === 'crosssupplier' ||
      item.id === 'priceanalysis'
    );
  }

  // Manager di sede vedono le funzioni operative non adminOnly
  return !item.adminOnly;
}

export default function App() {
  const [isGodMode, setIsGodMode] = useState(() => {
    return window.location.pathname === '/god' || window.location.hash === '#god' || window.location.search.includes('page=god') || window.location.search.includes('god=1');
  });

  const [activeTab, setActiveTab] = useState('dashboard')
  const [isAuth, setIsAuth] = useState(false)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    operations: true,
    purchasing: true,
    analytics: false,
    catalog: false,
    administration: false,
  })

  useEffect(() => {
    const handleUrlChange = () => {
      setIsGodMode(
        window.location.pathname === '/god' || 
        window.location.hash === '#god' || 
        window.location.search.includes('page=god') || 
        window.location.search.includes('god=1')
      );
    };
    window.addEventListener('hashchange', handleUrlChange);
    window.addEventListener('popstate', handleUrlChange);
    return () => {
      window.removeEventListener('hashchange', handleUrlChange);
      window.removeEventListener('popstate', handleUrlChange);
    };
  }, []);

  // Notification center & order redirect state
  const [notificationModalOpen, setNotificationModalOpen] = useState(false);
  const [pendingFeedbacksCount, setPendingFeedbacksCount] = useState(0);
  const [recentOrdersCount, setRecentOrdersCount] = useState(0);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);

  // White-Label & Company Branding
  const [companySettings, setCompanySettings] = useState<{
    company_name: string;
    app_subtitle?: string | null;
    primary_color?: string;
    support_email?: string | null;
    currency_symbol?: string;
  }>({
    company_name: 'PRICE SENTINEL',
    app_subtitle: 'Audit & Purchasing Platform',
    primary_color: '#3b82f6',
    currency_symbol: '€',
  });

  useEffect(() => {
    fetch(`${API_BASE}/settings/company/`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (d && d.company_name) setCompanySettings(d);
      })
      .catch(() => {});
  }, [activeTab]);

  const loadNotificationStats = async () => {
    try {
      const [feedRes, ordRes] = await Promise.all([
        fetch(`${API_BASE}/feedbacks/pending-count`, { headers: getHeaders() }),
        fetch(`${API_BASE}/ordini/notifications/feed?limit=10`, { headers: getHeaders() })
      ]);

      if (feedRes.ok) {
        const feedData = await feedRes.json();
        setPendingFeedbacksCount(feedData.count || 0);
      }
      if (ordRes.ok) {
        const ordData = await ordRes.json();
        setRecentOrdersCount(ordData.count || 0);
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (isAuth) {
      loadNotificationStats();
      const interval = setInterval(loadNotificationStats, 20000);
      return () => clearInterval(interval);
    }
  }, [isAuth]);

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
        if (!cancelled) {
          const prof = data as UserProfile;
          setProfile(prof);
          if (prof.ruolo_dettagliato && prof.ruolo_dettagliato.startsWith('responsabile_')) {
            setActiveTab('sectororders');
            setOpenSections({
              operations: true,
              purchasing: true,
              analytics: true,
              catalog: false,
              administration: false
            });
          }
        }
      })
      .catch(() => {
        if (!cancelled) setProfile(null)
      })

    return () => {
      cancelled = true
    }
  }, [isAuth])

  useEffect(() => {
    if (profile) {
      const isAdm = profile.ruolo === 'admin' || profile.ruolo_dettagliato === 'admin';
      const det = profile.ruolo_dettagliato || 'manager_sede';
      if (det.startsWith('responsabile_')) {
        if (activeTab !== 'sectororders' && activeTab !== 'orderregistry' && activeTab !== 'crosssupplier' && activeTab !== 'fatture' && activeTab !== 'priceanalysis') {
          setActiveTab('sectororders');
        }
      } else if (!isAdm && (activeTab === 'dashboard' || activeTab === 'settings' || activeTab === 'listini' || activeTab === 'onboarding')) {
        setActiveTab('validation');
      }
    }
  }, [activeTab, profile]);

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
      const devEmail = (import.meta as any).env?.VITE_DEV_EMAIL;
      const devPassword = (import.meta as any).env?.VITE_DEV_PASSWORD;

      if ((import.meta as any).env?.DEV && devEmail && devPassword) {
        try {
          const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ email: devEmail, password: devPassword })
          });
          if (res.ok) {
            const data = await res.json();
            localStorage.setItem('token', data.access_token);
            setIsAuth(true);
            setProfile({
              id: 1,
              email: devEmail,
              nome_completo: data.nome_completo,
              ruolo: data.ruolo,
              ruolo_dettagliato: data.ruolo_dettagliato,
              settore_abilitato: data.settore_abilitato,
              location_id: data.location_id
            });
            return;
          }
        } catch {
          // fallback to manual token check
        }
      }

      const token = localStorage.getItem('token')
      if (token) {
        setIsAuth(true)
      }
    }
    autoLogin()
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoginError(null)
    setLoggingIn(true)

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Credenziali non valide')
      }

      const data = await res.json()
      localStorage.setItem('token', data.access_token)
      setIsAuth(true)
      const userProf: UserProfile = {
        id: data.id || 0,
        email: email,
        nome_completo: data.nome_completo,
        ruolo: data.ruolo,
        ruolo_dettagliato: data.ruolo_dettagliato,
        settore_abilitato: data.settore_abilitato,
        location_id: data.location_id
      };
      setProfile(userProf);

      if (data.ruolo_dettagliato && data.ruolo_dettagliato.startsWith('responsabile_')) {
        setActiveTab('sectororders');
        setOpenSections({
          operations: true,
          purchasing: true,
          analytics: true,
          catalog: false,
          administration: false
        });
      } else {
        setActiveTab(data.ruolo === 'admin' ? 'dashboard' : 'validation');
      }
    } catch (err: any) {
      setLoginError(err.message || 'Errore durante l\'accesso')
    } finally {
      setLoggingIn(false)
    }
  }

  const getRoleLabel = () => {
    if (!profile) return 'Operatore';
    if (profile.ruolo === 'admin' || profile.ruolo_dettagliato === 'admin') return '👑 Amministratore';
    if (profile.ruolo_dettagliato === 'responsabile_beverage') return '🍹 Resp. Beverage';
    if (profile.ruolo_dettagliato === 'responsabile_materiali') return '📦 Resp. Materiali';
    if (profile.ruolo_dettagliato === 'responsabile_food') return '🍽️ Resp. Food';
    if (profile.ruolo_dettagliato === 'manager_sede') return '🏢 Store Manager';
    return '👤 Operatore';
  };

  const renderContent = () => {
    if (isGodMode || activeTab === 'god') {
      return (
        <GodModeControlRoom
          onExit={() => {
            setIsGodMode(false);
            setActiveTab('dashboard');
            if (window.location.hash === '#god') {
              window.location.hash = '';
            }
            if (window.location.pathname === '/god') {
              window.history.pushState({}, '', '/');
            }
          }}
        />
      );
    }

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
              <h2 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '8px', letterSpacing: '-0.03em' }}>{companySettings.company_name}</h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{companySettings.app_subtitle || 'Accedi con le tue credenziali operatore'}</p>
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
                    placeholder="email@pricesentinel.it"
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
      case 'crosssupplier': return <SmartPriceSheet isAdmin={profile.ruolo === 'admin'} />;
      case 'productconsumption': return <ProductConsumptionReport />;
      case 'priceanalysis': return <PriceTrendAnalyzer />;
      case 'sectororders': return <SectorOrderBuilder userProfile={profile} />;
      case 'goodsreceipt': return <GoodsReceipt userProfile={profile} />;
      case 'orderregistry': return (
        <OrderRegistry
          isAdmin={profile.ruolo === 'admin' || profile.ruolo_dettagliato === 'admin'}
          selectedOrderId={selectedOrderId}
          onOrderClose={() => setSelectedOrderId(null)}
        />
      );
      case 'productreviews': return <ProductReviewPage userProfile={profile} />;
      case 'ordini': return <SectorOrderBuilder userProfile={profile} />;
      case 'skumanager': return <SkuManager />;
      case 'categories': return <CategorySupplierManager />;
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

  const getAccountDisplayName = () => {
    if (profile?.tenant_id === 2 || profile?.nome_completo?.toLowerCase().includes('bar la sosta') || profile?.email?.toLowerCase().includes('bar.it')) {
      return 'Bar la sosta';
    }
    if (profile?.nome_completo && !profile.nome_completo.toLowerCase().includes('amministratore principale')) {
      return profile.nome_completo.replace(/^Admin\s+/i, '');
    }
    return companySettings.company_name || 'Aura Network';
  };

  const accountName = getAccountDisplayName();

  const getHeaderInfo = () => {
    switch (activeTab) {
      case 'dashboard': return { title: `Panoramica - ${accountName}`, sub: `Indicatori economici e operativi di ${accountName}` };
      case 'upload': return { title: 'Carica Fatture', sub: 'Ingestione manuale file XML e archivi ZIP' };
      case 'fatture': return { title: 'Registro Fatture', sub: 'Visualizza, filtra e gestisci tutte le fatture' };
      case 'validation': return { title: 'Anomalie da validare', sub: 'Controllo anomalie e gestione rincari' };
      case 'listini': return { title: 'Gestione Listini Master', sub: 'Importazione e versioning prezzi concordati' };
      case 'topproducts': return { title: 'Top prodotti', sub: 'Analizza prezzi e volumi dei prodotti più acquistati' };
      case 'crosssupplier': return { title: 'Listino Smart', sub: 'Prezzi, qualità fornitori e regole di acquisto in un’unica matrice' };
      case 'productconsumption': return { title: 'Analisi Consumi per Prodotto', sub: 'Rapporto di consumo aggregato e andamento storico dei volumi di acquisto' };
      case 'priceanalysis': return { title: 'Analisi Oscillazioni Prezzi', sub: 'Confronta l\'andamento storico e le oscillazioni dei prezzi di acquisto' };
      case 'sectororders': return { title: 'Sviluppo Ordini Settore', sub: 'Compilazione fabbisogno per responsabili, assegnazione fornitori e invio WhatsApp' };
      case 'goodsreceipt': return { title: 'Ricezione & Scarico Merci', sub: 'Controllo quantitativo merci consegnate vs ordinate e segnalazione difformità' };
      case 'orderregistry': return { title: 'Registro Ordini', sub: 'Storico e consultazione ordini d\'acquisto, articoli e comunicazioni WhatsApp' };
      case 'productreviews': return { title: 'Recensioni & Qualità Prodotti', sub: 'Valutazione gradimento, resa qualitativa e segnalazioni per esclusione' };
      case 'ordini': return { title: 'Sviluppo Ordini Settore', sub: 'Compilazione fabbisogno per responsabili, assegnazione fornitori e invio WhatsApp' };
      case 'skumanager': return { title: 'Gestione SKU', sub: 'Organizza e rinomina gli SKU interni del catalogo' };
      case 'categories': return { title: 'Categorie & Fornitori', sub: 'Catalogo categorie merci e mappatura settori fornitori' };
      case 'productidentity': return { title: 'Prodotti e alias', sub: 'Gestione catalogo canonico, alias e proposte di matching' };
      case 'reconciliations': return { title: 'Riconciliazioni ordini', sub: 'Confronto ordine, ricezione e fattura con revisione manuale' };
      case 'disputes': return { title: 'Contestazioni e recuperi', sub: 'Comunicazioni fornitori, risposte e note di credito tracciate' };
      case 'monitor': return { title: 'Monitor operativo', sub: 'Scadenze, anomalie importanti e integrazioni da verificare' };
      case 'onboarding': return { title: 'Configurazione sede', sub: 'Attivazione guidata e soglie esplicite per ogni sede' };
      case 'excludedproducts': return { title: 'Prodotti Esclusi', sub: 'Gestisci la blacklist globale dei prodotti da escludere dalle analisi' };
      case 'accordicommerciali': return { title: 'Accordi Commerciali (PFA)', sub: 'Rientri di fine anno, volumi d\'acquisto e calcolo prezzi netti' };
      case 'settings': return { title: 'Impostazioni', sub: 'Configurazione sistema e gestione utenti' };
      default: return { title: accountName, sub: 'Audit System' };
    }
  }

  const info = getHeaderInfo();

  const isSectorResp = profile?.ruolo_dettagliato && profile.ruolo_dettagliato.startsWith('responsabile_');

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
            <h2 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 700, letterSpacing: '0.5px' }}>
              {accountName.toUpperCase()}
            </h2>
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
          {!isSectorResp && (profile?.ruolo === 'admin' || profile?.ruolo_dettagliato === 'admin') && (
            <button
              className={`sidebar-nav-item ${activeTab === 'dashboard' ? 'is-active' : ''}`}
              onClick={() => { setActiveTab('dashboard'); setMobileSidebarOpen(false); }}
            >
              <LayoutDashboard size={18} /> Panoramica - {accountName}
            </button>
          )}

          {NAV_SECTIONS.map(section => {
            const visibleItems = section.items.filter(item => isItemPermitted(item, profile))
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
            <span style={{ fontWeight: 700, color: 'white' }}>{getRoleLabel()}</span>
            <small>{profile?.nome_completo || profile?.email || 'Profilo in caricamento…'}</small>
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
            <button
              type="button"
              onClick={() => setNotificationModalOpen(true)}
              title="Centro Notifiche: Nuovi Ordini & Segnalazioni"
              style={{
                position: 'relative',
                background: (pendingFeedbacksCount > 0 || recentOrdersCount > 0) ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255,255,255,0.03)',
                border: pendingFeedbacksCount > 0 ? '1px solid rgba(239, 68, 68, 0.4)' : (recentOrdersCount > 0 ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid var(--border-glass)'),
                borderRadius: '10px',
                width: '40px',
                height: '40px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: pendingFeedbacksCount > 0 ? '#ef4444' : (recentOrdersCount > 0 ? '#60a5fa' : 'var(--text-secondary)'),
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              <Bell size={18} />
              {(pendingFeedbacksCount > 0 || recentOrdersCount > 0) && (
                <span style={{
                  position: 'absolute',
                  top: '-4px',
                  right: '-4px',
                  background: pendingFeedbacksCount > 0 ? '#ef4444' : '#3b82f6',
                  color: 'white',
                  fontSize: '0.68rem',
                  fontWeight: 800,
                  borderRadius: '10px',
                  padding: '1px 5px',
                  boxShadow: pendingFeedbacksCount > 0 ? '0 0 10px rgba(239, 68, 68, 0.8)' : '0 0 10px rgba(59, 130, 246, 0.8)'
                }}>
                  {pendingFeedbacksCount + recentOrdersCount}
                </span>
              )}
            </button>

            <div className="profile-info" style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 600, color: 'white' }}>{getRoleLabel()}</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{profile?.nome_completo || profile?.email || 'Profilo in caricamento…'}</div>
            </div>
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'var(--bg-glass)', border: '1px solid var(--border-glass)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, color: 'var(--accent-blue)' }}>
              {profile?.nome_completo ? profile.nome_completo.charAt(0).toUpperCase() : (profile?.email?.charAt(0).toUpperCase() || '…')}
            </div>
          </div>
        </header>

        {/* Dynamic Content */}
        <div style={{ position: 'relative', zIndex: 1 }}>
          {renderContent()}
        </div>
      </main>

      {/* Notification Center Modal */}
      <NotificationCenterModal
        isOpen={notificationModalOpen}
        onClose={() => setNotificationModalOpen(false)}
        onViewOrder={(orderId) => {
          setSelectedOrderId(orderId);
          setActiveTab('orderregistry');
        }}
        onViewReviews={() => setActiveTab('productreviews')}
        onViewReceipt={() => setActiveTab('goodsreceipt')}
        onRefreshCounts={loadNotificationStats}
      />
    </div>
  )
}
