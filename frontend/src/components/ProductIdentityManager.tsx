import { useState, useEffect } from 'react'
import { Plus, Search, Tag, ShieldAlert, Sparkles, Check, X, RefreshCw, Layers, Edit } from 'lucide-react'
import { API_BASE, getHeaders } from '../api'

interface Product {
  id: number
  sku_interno: string | null
  canonical_name: string
  brand: string | null
  category: string | null
  subcategory: string | null
  variant: string | null
  volume_ml: number | null
  weight_g: number | null
  unit_count: number
  container_type: string | null
  comparison_unit: string
  is_commodity: boolean
  is_active: boolean
}

interface Alias {
  id: number
  supplier_id: number
  product_id: number
  supplier_code: string | null
  raw_description: string
  normalized_description: string
  ean: string | null
  pack_qty: number | null
  volume_ml: number | null
  weight_g: number | null
  container_type: string | null
  status: string
  confidence_score: number
  source: string
}

interface MatchCandidate {
  id: number
  invoice_line_id: number | null
  product_id: number
  source_type: string
  source_id: number | null
  supplier_id: number | null
  raw_description: string | null
  normalized_description: string | null
  score: number
  reason_json: any | null
  block_flag: boolean
  status: string
  created_at: string
}

export default function ProductIdentityManager() {
  const [activeSubTab, setActiveSubTab] = useState<'products' | 'candidates' | 'import'>('products')
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [aliases, setAliases] = useState<Alias[]>([])
  const [candidates, setCandidates] = useState<MatchCandidate[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Import State
  const [suppliers, setSuppliers] = useState<any[]>([])
  const [importSupplierId, setImportSupplierId] = useState<string>('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importResult, setImportResult] = useState<any | null>(null)
  const [importLoading, setImportLoading] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)

  // Search & Filters
  const [productSearch, setProductSearch] = useState('')
  const [candidateSearch, setCandidateSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')

  // Modals / Forms
  const [showProductModal, setShowProductModal] = useState(false)
  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [productForm, setProductForm] = useState({
    sku_interno: '',
    canonical_name: '',
    brand: '',
    category: 'monouso',
    subcategory: '',
    variant: '',
    volume_ml: '',
    weight_g: '',
    unit_count: '1',
    container_type: '',
    comparison_unit: 'piece',
    is_commodity: false,
    is_active: true
  })

  const [showAliasModal, setShowAliasModal] = useState(false)
  const [aliasForm, setAliasForm] = useState({
    supplier_id: '',
    supplier_code: '',
    raw_description: '',
    ean: '',
    pack_qty: '',
    volume_ml: '',
    weight_g: '',
    container_type: '',
    status: 'approved'
  })

  useEffect(() => {
    fetchProducts()
    fetchCandidates()
    fetchSuppliers()
  }, [])

  const fetchSuppliers = async () => {
    try {
      const res = await fetch(`${API_BASE}/fornitori`, { headers: getHeaders() })
      if (!res.ok) throw new Error("Errore caricamento fornitori")
      const data = await res.json()
      setSuppliers(data)
    } catch (err) {
      console.error(err)
    }
  }

  const handleImportSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importSupplierId || !importFile) return
    
    setImportLoading(true)
    setImportError(null)
    setImportResult(null)
    
    const formData = new FormData()
    formData.append('file', importFile)
    
    try {
      const headers = getHeaders()
      const fetchHeaders: any = { ...headers }
      delete fetchHeaders['Content-Type']
      
      const res = await fetch(`${API_BASE}/product-identity/import-supplier-list/${importSupplierId}`, {
        method: 'POST',
        headers: fetchHeaders,
        body: formData
      })
      
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || "Errore durante l'importazione del listino")
      }
      
      setImportResult(data)
      fetchProducts()
    } catch (err: any) {
      setImportError(err.message)
    } finally {
      setImportLoading(false)
    }
  }

  useEffect(() => {
    if (selectedProduct) {
      fetchAliases(selectedProduct.id)
    } else {
      setAliases([])
    }
  }, [selectedProduct])

  const fetchProducts = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/products`, { headers: getHeaders() })
      if (!res.ok) throw new Error("Errore nel recupero dei prodotti")
      const data = await res.json()
      setProducts(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchAliases = async (productId: number) => {
    try {
      const res = await fetch(`${API_BASE}/products/${productId}/aliases`, { headers: getHeaders() })
      if (!res.ok) throw new Error("Errore nel recupero degli alias")
      const data = await res.json()
      setAliases(data)
    } catch (err: any) {
      console.error(err.message)
    }
  }

  const fetchCandidates = async () => {
    try {
      const res = await fetch(`${API_BASE}/match-candidates`, { headers: getHeaders() })
      if (!res.ok) throw new Error("Errore nel recupero dei candidati")
      const data = await res.json()
      setCandidates(data)
    } catch (err: any) {
      console.error(err.message)
    }
  }

  const handleProductSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const payload = {
        ...productForm,
        volume_ml: productForm.volume_ml ? parseInt(productForm.volume_ml) : null,
        weight_g: productForm.weight_g ? parseInt(productForm.weight_g) : null,
        unit_count: parseInt(productForm.unit_count) || 1,
        brand: productForm.brand || null,
        sku_interno: productForm.sku_interno || null,
        subcategory: productForm.subcategory || null,
        variant: productForm.variant || null,
        container_type: productForm.container_type || null
      }

      let res
      if (editingProduct) {
        res = await fetch(`${API_BASE}/products/${editingProduct.id}`, {
          method: 'PATCH',
          headers: getHeaders(),
          body: JSON.stringify(payload)
        })
      } else {
        res = await fetch(`${API_BASE}/products`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify(payload)
        })
      }

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Errore nel salvataggio del prodotto")
      }

      setShowProductModal(false)
      setEditingProduct(null)
      fetchProducts()
    } catch (err: any) {
      alert(err.message)
    }
  }

  const handleAliasSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedProduct) return
    try {
      const payload = {
        ...aliasForm,
        supplier_id: parseInt(aliasForm.supplier_id),
        pack_qty: aliasForm.pack_qty ? parseInt(aliasForm.pack_qty) : null,
        volume_ml: aliasForm.volume_ml ? parseInt(aliasForm.volume_ml) : null,
        weight_g: aliasForm.weight_g ? parseInt(aliasForm.weight_g) : null,
        supplier_code: aliasForm.supplier_code || null,
        ean: aliasForm.ean || null,
        container_type: aliasForm.container_type || null
      }

      const res = await fetch(`${API_BASE}/products/${selectedProduct.id}/aliases`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      })

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Errore nella creazione dell'alias")
      }

      setShowAliasModal(false)
      fetchAliases(selectedProduct.id)
    } catch (err: any) {
      alert(err.message)
    }
  }

  const handleApproveCandidate = async (candidateId: number) => {
    if (!confirm("Sei sicuro di voler approvare questo matching e creare l'alias corrispondente?")) return
    try {
      const res = await fetch(`${API_BASE}/match-candidates/${candidateId}/approve`, {
        method: 'POST',
        headers: getHeaders()
      })
      if (!res.ok) throw new Error("Errore nell'approvazione del candidato")
      fetchCandidates()
      fetchProducts()
    } catch (err: any) {
      alert(err.message)
    }
  }

  const handleRejectCandidate = async (candidateId: number) => {
    if (!confirm("Rifiutare questo matching manderà l'articolo in Parking Area. Continuare?")) return
    try {
      const res = await fetch(`${API_BASE}/match-candidates/${candidateId}/reject`, {
        method: 'POST',
        headers: getHeaders()
      })
      if (!res.ok) throw new Error("Errore nel rifiuto del candidato")
      fetchCandidates()
    } catch (err: any) {
      alert(err.message)
    }
  }

  const openEditProduct = (product: Product) => {
    setEditingProduct(product)
    setProductForm({
      sku_interno: product.sku_interno || '',
      canonical_name: product.canonical_name,
      brand: product.brand || '',
      category: product.category || 'monouso',
      subcategory: product.subcategory || '',
      variant: product.variant || '',
      volume_ml: product.volume_ml?.toString() || '',
      weight_g: product.weight_g?.toString() || '',
      unit_count: product.unit_count.toString(),
      container_type: product.container_type || '',
      comparison_unit: product.comparison_unit,
      is_commodity: product.is_commodity,
      is_active: product.is_active
    })
    setShowProductModal(true)
  }

  const filteredProducts = products.filter(p => {
    const matchesSearch = p.canonical_name.toLowerCase().includes(productSearch.toLowerCase()) ||
      (p.sku_interno || '').toLowerCase().includes(productSearch.toLowerCase())
    const matchesCategory = !categoryFilter || p.category === categoryFilter
    return matchesSearch && matchesCategory
  })

  const filteredCandidates = candidates.filter(c => {
    return (c.raw_description || '').toLowerCase().includes(candidateSearch.toLowerCase())
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '30px', minHeight: '80vh' }}>
      
      {/* Sub Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border-glass)', paddingBottom: '2px', gap: '20px' }}>
        <button
          className={`tab-btn ${activeSubTab === 'products' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('products')}
          style={{
            background: 'none',
            border: 'none',
            borderBottom: activeSubTab === 'products' ? '2px solid var(--accent-blue)' : '2px solid transparent',
            color: activeSubTab === 'products' ? 'white' : 'var(--text-secondary)',
            padding: '10px 16px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '0.95rem',
            transition: 'all 0.3s'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Layers size={18} /> Catalogo Canonico & Alias
          </div>
        </button>
        <button
          className={`tab-btn ${activeSubTab === 'candidates' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('candidates')}
          style={{
            background: 'none',
            border: 'none',
            borderBottom: activeSubTab === 'candidates' ? '2px solid var(--accent-blue)' : '2px solid transparent',
            color: activeSubTab === 'candidates' ? 'white' : 'var(--text-secondary)',
            padding: '10px 16px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '0.95rem',
            transition: 'all 0.3s'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={18} /> Match Candidates ({candidates.length})
          </div>
        </button>
        <button
          className={`tab-btn ${activeSubTab === 'import' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('import')}
          style={{
            background: 'none',
            border: 'none',
            borderBottom: activeSubTab === 'import' ? '2px solid var(--accent-blue)' : '2px solid transparent',
            color: activeSubTab === 'import' ? 'white' : 'var(--text-secondary)',
            padding: '10px 16px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '0.95rem',
            transition: 'all 0.3s'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Plus size={18} /> Import Listino Fornitore
          </div>
        </button>
      </div>

      {error && (
        <div style={{ background: 'var(--status-red-bg)', color: 'var(--status-red)', padding: '16px', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <ShieldAlert size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* VIEW: Products & Aliases */}
      {activeSubTab === 'products' && (
        <div style={{ display: 'grid', gridTemplateColumns: selectedProduct ? '1.5fr 1fr' : '1fr', gap: '30px', transition: 'all 0.3s' }}>
          
          {/* Products List Panel */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>Prodotti Canonici</h3>
              
              <button 
                className="btn btn-primary" 
                onClick={() => {
                  setEditingProduct(null)
                  setProductForm({
                    sku_interno: '',
                    canonical_name: '',
                    brand: '',
                    category: 'monouso',
                    subcategory: '',
                    variant: '',
                    volume_ml: '',
                    weight_g: '',
                    unit_count: '1',
                    container_type: '',
                    comparison_unit: 'piece',
                    is_commodity: false,
                    is_active: true
                  })
                  setShowProductModal(true)
                }}
                style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
              >
                <Plus size={16} /> Aggiungi Prodotto
              </button>
            </div>

            {/* Search and Filters */}
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ position: 'relative', flex: 1, minWidth: '200px' }}>
                <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                <input
                  type="text"
                  placeholder="Cerca per nome o SKU..."
                  value={productSearch}
                  onChange={e => setProductSearch(e.target.value)}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '10px 12px 10px 38px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid var(--border-glass)',
                    borderRadius: '8px',
                    color: 'white',
                    outline: 'none',
                    fontSize: '0.9rem'
                  }}
                />
              </div>

              <select
                value={categoryFilter}
                onChange={e => setCategoryFilter(e.target.value)}
                style={{
                  padding: '10px 16px',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '8px',
                  color: 'white',
                  outline: 'none',
                  cursor: 'pointer'
                }}
              >
                <option value="" style={{ background: '#13131c' }}>Tutte le Categorie</option>
                <option value="acqua" style={{ background: '#13131c' }}>Acqua</option>
                <option value="soft_drink" style={{ background: '#13131c' }}>Soft Drink</option>
                <option value="monouso" style={{ background: '#13131c' }}>Monouso</option>
                <option value="vino" style={{ background: '#13131c' }}>Vino</option>
                <option value="spirits" style={{ background: '#13131c' }}>Spirits</option>
                <option value="food" style={{ background: '#13131c' }}>Food</option>
              </select>
            </div>

            {loading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><RefreshCw className="animate-spin" /></div>
            ) : (
              <div className="table-responsive">
                <table className="table">
                  <thead>
                    <tr>
                      <th>SKU Interno</th>
                      <th>Nome Canonico</th>
                      <th>Categoria</th>
                      <th>Formato / Volume</th>
                      <th>Unità Conf</th>
                      <th style={{ textAlign: 'right' }}>Azioni</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredProducts.map(p => (
                      <tr 
                        key={p.id}
                        onClick={() => setSelectedProduct(p)}
                        style={{ 
                          cursor: 'pointer', 
                          background: selectedProduct?.id === p.id ? 'rgba(59, 130, 246, 0.08)' : '',
                          borderLeft: selectedProduct?.id === p.id ? '3px solid var(--accent-blue)' : ''
                        }}
                      >
                        <td><code style={{ color: 'var(--accent-blue)' }}>{p.sku_interno || 'N/D'}</code></td>
                        <td style={{ fontWeight: 600 }}>{p.canonical_name}</td>
                        <td>
                          <span className="badge" style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)' }}>
                            {p.category}
                          </span>
                        </td>
                        <td>{p.volume_ml ? `${p.volume_ml} ml` : p.weight_g ? `${p.weight_g} g` : 'N/D'}</td>
                        <td>x{p.unit_count}</td>
                        <td style={{ textAlign: 'right' }} onClick={e => e.stopPropagation()}>
                          <button 
                            className="btn btn-secondary" 
                            onClick={() => openEditProduct(p)}
                            style={{ padding: '6px 10px' }}
                          >
                            <Edit size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {filteredProducts.length === 0 && (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px' }}>
                          Nessun prodotto trovato.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Aliases Panel (details of selected product) */}
          {selectedProduct && (
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', animation: 'fadeIn 0.3s' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Tag size={16} color="var(--accent-blue)" />
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase' }}>Alias Approvati</span>
                  </div>
                  <h4 style={{ fontSize: '1.1rem', fontWeight: 700, margin: '4px 0 0 0' }}>{selectedProduct.canonical_name}</h4>
                </div>

                <button 
                  className="btn btn-secondary" 
                  onClick={() => {
                    setAliasForm({
                      supplier_id: '',
                      supplier_code: '',
                      raw_description: '',
                      ean: '',
                      pack_qty: selectedProduct.unit_count.toString(),
                      volume_ml: selectedProduct.volume_ml?.toString() || '',
                      weight_g: selectedProduct.weight_g?.toString() || '',
                      container_type: selectedProduct.container_type || '',
                      status: 'approved'
                    })
                    setShowAliasModal(true)
                  }}
                  style={{ padding: '8px 12px', fontSize: '0.85rem' }}
                >
                  <Plus size={14} /> Nuovo Alias
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {aliases.map(a => (
                  <div key={a.id} className="glass-panel" style={{ padding: '16px', background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{a.raw_description}</span>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <span>Cod: <code>{a.supplier_code || 'N/D'}</code></span>
                        <span>•</span>
                        <span>EAN: {a.ean || 'N/D'}</span>
                        {a.pack_qty && (
                          <>
                            <span>•</span>
                            <span>Pack: x{a.pack_qty}</span>
                          </>
                        )}
                      </div>
                    </div>

                    <span className="badge" style={{ 
                      background: a.status === 'approved' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                      color: a.status === 'approved' ? 'var(--status-green)' : 'var(--status-red)',
                      border: a.status === 'approved' ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid rgba(239, 68, 68, 0.2)'
                    }}>
                      {a.status}
                    </span>
                  </div>
                ))}

                {aliases.length === 0 && (
                  <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px', background: 'rgba(255,255,255,0.01)', borderRadius: '10px' }}>
                    Nessun alias censito per questo prodotto.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* VIEW: Match Candidates */}
      {activeSubTab === 'candidates' && (
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>Richieste di Associazione Pendenti</h3>
          </div>

          <div style={{ position: 'relative', width: '100%' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <input
              type="text"
              placeholder="Cerca per descrizione articolo fornitore..."
              value={candidateSearch}
              onChange={e => setCandidateSearch(e.target.value)}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px 10px 38px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                color: 'white',
                outline: 'none',
                fontSize: '0.9rem'
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {filteredCandidates.map(c => {
              const matchedProd = products.find(p => p.id === c.product_id)
              const reason = typeof c.reason_json === 'string' ? JSON.parse(c.reason_json) : c.reason_json

              return (
                <div key={c.id} className="glass-panel" style={{ padding: '20px', border: '1px solid rgba(255,255,255,0.05)', display: 'grid', gridTemplateColumns: '1fr auto', gap: '20px', alignItems: 'center' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{ fontWeight: 700, fontSize: '1.05rem', color: 'white' }}>{c.raw_description}</span>
                      <span className="badge" style={{
                        background: c.score >= 90 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                        color: c.score >= 90 ? 'var(--status-green)' : 'var(--status-orange)',
                        fontSize: '0.8rem',
                        fontWeight: 700
                      }}>
                        Confidenza: {c.score.toFixed(0)}%
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                      <span>Sorgente: <strong style={{ color: 'white' }}>{c.source_type}</strong></span>
                      <span>•</span>
                      <span>Associazione proposta con:</span>
                      <code style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>{matchedProd?.canonical_name || 'Prodotto sconosciuto'}</code>
                    </div>

                    {/* Breakdown Reasons */}
                    {reason && (
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                        {reason.brand_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Brand Ok</span>}
                        {reason.category_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Categoria Ok</span>}
                        {reason.volume_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Volume Ok</span>}
                        {reason.weight_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Peso Ok</span>}
                        {reason.pack_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Pack Ok</span>}
                        {reason.container_match && <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)', fontSize: '0.7rem' }}>Contenitore Ok</span>}
                        {c.block_flag && <span className="badge" style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--status-red)', fontSize: '0.7rem' }}>Bloccato</span>}
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button 
                      className="btn btn-secondary" 
                      onClick={() => handleRejectCandidate(c.id)}
                      style={{ color: 'var(--status-red)', borderColor: 'rgba(239,68,68,0.2)', padding: '10px 14px' }}
                    >
                      <X size={16} /> Rifiuta
                    </button>
                    <button 
                      className="btn btn-primary" 
                      onClick={() => handleApproveCandidate(c.id)}
                      style={{ padding: '10px 14px' }}
                    >
                      <Check size={16} /> Approva Match
                    </button>
                  </div>
                </div>
              )
            })}

            {filteredCandidates.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px', background: 'rgba(255,255,255,0.01)', borderRadius: '12px' }}>
                Nessuna richiesta di associazione pendente al momento. Ottimo lavoro!
              </div>
            )}
          </div>
        </div>
      )}

      {/* VIEW: Import Listino */}
      {activeSubTab === 'import' && (
        <div className="glass-panel" style={{ padding: '30px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 8px 0' }}>Importazione Listino Fornitore (Excel)</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
              Carica un file Excel con il listino concordato di un fornitore. Il sistema riconoscerà automaticamente le colonne principali (prezzo, descrizione, confezione, codice) e proverà ad abbinare i prodotti.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '30px' }}>
            <form onSubmit={handleImportSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Seleziona Fornitore</label>
                <select
                  required
                  value={importSupplierId}
                  onChange={e => setImportSupplierId(e.target.value)}
                  style={{ padding: '12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                >
                  <option value="" style={{ background: '#13131c' }}>-- Seleziona Fornitore --</option>
                  {suppliers.map(s => (
                    <option key={s.id} value={s.id} style={{ background: '#13131c' }}>
                      {s.nome_azienda} (ID: {s.id})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>File Excel (.xlsx)</label>
                <input
                  required
                  type="file"
                  accept=".xlsx"
                  onChange={e => setImportFile(e.target.files?.[0] || null)}
                  style={{ padding: '12px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                />
              </div>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={importLoading || !importSupplierId || !importFile}
                style={{ padding: '12px', justifyContent: 'center' }}
              >
                {importLoading ? (
                  <>
                    <RefreshCw className="animate-spin" size={18} /> Importazione in corso...
                  </>
                ) : (
                  'Avvia Importazione'
                )}
              </button>
              
              {importError && (
                <div style={{ background: 'var(--status-red-bg)', color: 'var(--status-red)', padding: '12px', borderRadius: '8px', fontSize: '0.85rem' }}>
                  {importError}
                </div>
              )}
            </form>

            <div style={{ borderLeft: '1px solid var(--border-glass)', paddingLeft: '30px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {importResult ? (
                <>
                  <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Risultato Elaborazione</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '8px', border: '1px solid var(--border-glass)' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Righe Lette</span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{importResult.righe_totali_lette}</div>
                    </div>
                    <div style={{ background: 'rgba(0, 200, 100, 0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(0, 200, 100, 0.1)' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--status-green)' }}>Righe Importate (Matched)</span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--status-green)' }}>{importResult.righe_importate}</div>
                    </div>
                    <div style={{ background: 'rgba(255, 200, 0, 0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255, 200, 0, 0.1)' }}>
                      <span style={{ fontSize: '0.8rem', color: '#ffb700' }}>Match Candidates (Parking Area)</span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#ffb700' }}>{importResult.match_candidates_creati}</div>
                    </div>
                    <div style={{ background: 'rgba(255, 0, 0, 0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255, 0, 0, 0.1)' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--status-red)' }}>Righe Scartate/Errori</span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--status-red)' }}>{importResult.righe_scartate}</div>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    <div>Alias Creati: <strong>{importResult.alias_approvati_creati}</strong></div>
                    <div>Alias Esistenti: <strong>{importResult.alias_gia_esistenti_riconosciuti}</strong></div>
                    <div>Prezzi Creati: <strong>{importResult.prezzi_nuovi_creati}</strong></div>
                    <div>Prezzi Invariati: <strong>{importResult.prezzi_invariati}</strong></div>
                    <div>Prezzi Storicizzati: <strong>{importResult.prezzi_storicizzati}</strong></div>
                  </div>

                  {importResult.match_candidates_creati > 0 && (
                    <div style={{ background: 'rgba(255, 200, 0, 0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255, 200, 0, 0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.85rem', color: '#ffb700' }}>Ci sono {importResult.match_candidates_creati} nuovi candidati da abbinare manualmente.</span>
                      <button className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.8rem' }} onClick={() => {
                        fetchCandidates();
                        setActiveSubTab('candidates');
                      }}>
                        Risolvi Ora
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontSize: '0.9rem', textAlign: 'center', border: '1px dashed var(--border-glass)', borderRadius: '12px', padding: '40px' }}>
                  Seleziona un fornitore e carica il file Excel per avviare l'importazione.
                </div>
              )}
            </div>
          </div>

          {importResult?.preview?.length > 0 && (
            <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Anteprima Importazione (Top 20)</h4>
              <div style={{ overflowX: 'auto', border: '1px solid var(--border-glass)', borderRadius: '8px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid var(--border-glass)', textAlign: 'left' }}>
                      <th style={{ padding: '10px' }}>Riga</th>
                      <th style={{ padding: '10px' }}>Codice</th>
                      <th style={{ padding: '10px' }}>Descrizione</th>
                      <th style={{ padding: '10px', textAlign: 'right' }}>Prezzo</th>
                      <th style={{ padding: '10px' }}>UM/Pack</th>
                      <th style={{ padding: '10px' }}>Matching</th>
                      <th style={{ padding: '10px' }}>Esito Prezzo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.preview.map((p: any, idx: number) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--border-glass)' }}>
                        <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{p.row_index}</td>
                        <td style={{ padding: '10px' }}><code>{p.supplier_code || '-'}</code></td>
                        <td style={{ padding: '10px' }}>{p.raw_description}</td>
                        <td style={{ padding: '10px', textAlign: 'right', fontWeight: 600 }}>€ {p.price.toFixed(2)}</td>
                        <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{p.uom} (x{p.pack_qty})</td>
                        <td style={{ padding: '10px' }}>
                          {p.match_status === 'auto_match' ? (
                            <span style={{ color: 'var(--status-green)', background: 'rgba(0, 200, 100, 0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                              Auto ({p.matched_sku})
                            </span>
                          ) : (
                            <span style={{ color: '#ffb700', background: 'rgba(255, 200, 0, 0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                              Parking (Score {p.score.toFixed(0)}%)
                            </span>
                          )}
                        </td>
                        <td style={{ padding: '10px', color: p.price_outcome === 'created' ? 'var(--status-green)' : p.price_outcome === 'updated' ? '#ffb700' : 'var(--text-secondary)' }}>
                          {p.price_outcome || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {importResult?.errori_parsing?.length > 0 && (
            <div style={{ border: '1px solid rgba(255,0,0,0.2)', background: 'rgba(255,0,0,0.02)', borderRadius: '8px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <h4 style={{ margin: 0, color: 'var(--status-red)', fontSize: '0.9rem', fontWeight: 600 }}>Errori e Segnalazioni</h4>
              <div style={{ maxHeight: '150px', overflowY: 'auto', fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {importResult.errori_parsing.map((err: string, idx: number) => (
                  <div key={idx}>• {err}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* MODAL: Add/Edit Product */}
      {showProductModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="glass-panel" style={{ width: '90%', maxWidth: '600px', padding: '30px', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 50px rgba(0,0,0,0.6)' }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>
              {editingProduct ? 'Modifica Prodotto Canonico' : 'Nuovo Prodotto Canonico'}
            </h3>

            <form onSubmit={handleProductSubmit} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>SKU Interno (opzionale)</label>
                <input
                  type="text"
                  placeholder="es. BICCHIERE_CAFFE"
                  value={productForm.sku_interno}
                  onChange={e => setProductForm({ ...productForm, sku_interno: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Nome Canonico</label>
                <input
                  type="text"
                  required
                  placeholder="es. Bicchiere caffè"
                  value={productForm.canonical_name}
                  onChange={e => setProductForm({ ...productForm, canonical_name: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Brand (opzionale)</label>
                <input
                  type="text"
                  value={productForm.brand}
                  onChange={e => setProductForm({ ...productForm, brand: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Categoria</label>
                <select
                  value={productForm.category}
                  onChange={e => setProductForm({ ...productForm, category: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                >
                  <option value="acqua" style={{ background: '#13131c' }}>Acqua</option>
                  <option value="soft_drink" style={{ background: '#13131c' }}>Soft Drink</option>
                  <option value="monouso" style={{ background: '#13131c' }}>Monouso</option>
                  <option value="vino" style={{ background: '#13131c' }}>Vino</option>
                  <option value="spirits" style={{ background: '#13131c' }}>Spirits</option>
                  <option value="food" style={{ background: '#13131c' }}>Food</option>
                </select>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Volume (ml)</label>
                <input
                  type="number"
                  placeholder="es. 80"
                  value={productForm.volume_ml}
                  onChange={e => setProductForm({ ...productForm, volume_ml: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Peso (g)</label>
                <input
                  type="number"
                  placeholder="es. 500"
                  value={productForm.weight_g}
                  onChange={e => setProductForm({ ...productForm, weight_g: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Pezzi per Confezione</label>
                <input
                  type="number"
                  value={productForm.unit_count}
                  onChange={e => setProductForm({ ...productForm, unit_count: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Unità di Misura Confronto</label>
                <select
                  value={productForm.comparison_unit}
                  onChange={e => setProductForm({ ...productForm, comparison_unit: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                >
                  <option value="piece" style={{ background: '#13131c' }}>Pezzo (piece)</option>
                  <option value="liter" style={{ background: '#13131c' }}>Litro (liter)</option>
                  <option value="kg" style={{ background: '#13131c' }}>Chilogrammo (kg)</option>
                  <option value="bottle" style={{ background: '#13131c' }}>Bottiglia (bottle)</option>
                  <option value="box" style={{ background: '#13131c' }}>Cassa/Scatola (box)</option>
                </select>
              </div>

              <div style={{ gridColumn: 'span 2', display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '16px' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setShowProductModal(false)}>Annulla</button>
                <button type="submit" className="btn btn-primary">Salva Prodotto</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Add Alias */}
      {showAliasModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="glass-panel" style={{ width: '90%', maxWidth: '500px', padding: '30px', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid rgba(255,255,255,0.1)' }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>Crea Alias Fornitore</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>Mappa una descrizione fornitore a questo prodotto canonico.</p>

            <form onSubmit={handleAliasSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Fornitore ID</label>
                <input
                  type="number"
                  required
                  placeholder="ID del fornitore"
                  value={aliasForm.supplier_id}
                  onChange={e => setAliasForm({ ...aliasForm, supplier_id: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Codice Articolo Fornitore (opzionale)</label>
                <input
                  type="text"
                  placeholder="Codice del fornitore"
                  value={aliasForm.supplier_code}
                  onChange={e => setAliasForm({ ...aliasForm, supplier_code: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Descrizione Articolo Fornitore</label>
                <input
                  type="text"
                  required
                  placeholder="Es. BICCHIERE CAFFE BIANCO x100"
                  value={aliasForm.raw_description}
                  onChange={e => setAliasForm({ ...aliasForm, raw_description: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Pezzi per Confezione (Alias)</label>
                <input
                  type="number"
                  placeholder="Es. 100"
                  value={aliasForm.pack_qty}
                  onChange={e => setAliasForm({ ...aliasForm, pack_qty: e.target.value })}
                  style={{ padding: '10px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setShowAliasModal(false)}>Annulla</button>
                <button type="submit" className="btn btn-primary">Salva Alias</button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  )
}
