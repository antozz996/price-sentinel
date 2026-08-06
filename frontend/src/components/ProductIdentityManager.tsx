import { useState, useEffect } from 'react'
import { Plus, Search, Tag, ShieldAlert, Sparkles, Check, X, RefreshCw, Layers, Edit } from 'lucide-react'
import { API_BASE, getHeaders } from '../api'

interface Product {
  id: number
  sku_interno: string | null
  canonical_name: string
  order_name: string | null
  brand: string | null
  category: string | null
  subcategory: string | null
  variant: string | null
  volume_ml: number | null
  weight_g: number | null
  unit_count: number
  supplier_pack_sizes: number[]
  container_type: string | null
  comparison_unit: string
  is_commodity: boolean
  is_active: boolean
}

interface Alias {
  id: number
  supplier_id: number
  product_id: number | null
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

interface WorkQueueCandidate {
  candidate_id: number
  product_id: number
  sku_interno: string | null
  canonical_name: string
  score: number
  reason_json: Record<string, boolean | number | string>
}

interface WorkQueueItem {
  work_key: string
  supplier_id: number
  supplier_name: string
  supplier_code: string | null
  raw_description: string
  normalized_description: string
  occurrence_count: number
  invoice_count: number
  invoice_line_ids: number[]
  latest_invoice_date: string
  candidate_records: number
  recommendation: 'associate_existing' | 'create_canonical'
  best_candidate: WorkQueueCandidate | null
  alternatives: WorkQueueCandidate[]
  suggested_product: {
    canonical_name: string
    category: string | null
    volume_ml: number | null
    weight_g: number | null
    unit_count: number
    container_type: string | null
    comparison_unit: string
  }
}

interface WorkQueueResponse {
  summary: {
    work_items: number
    invoice_lines: number
    reliable_suggestions: number
    probable_new_products: number
    weak_candidates_hidden: number
  }
  items: WorkQueueItem[]
}

export default function ProductIdentityManager() {
  const [activeSubTab, setActiveSubTab] = useState<'products' | 'candidates' | 'import'>('products')
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [aliases, setAliases] = useState<Alias[]>([])
  const [workQueue, setWorkQueue] = useState<WorkQueueResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Import State
  const [suppliers, setSuppliers] = useState<any[]>([])
  const [importSupplierId, setImportSupplierId] = useState<string>('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importResult, setImportResult] = useState<any | null>(null)
  const [importLoading, setImportLoading] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importDryRun, setImportDryRun] = useState(true)
  const [createMissingProducts, setCreateMissingProducts] = useState(false)
  const [previewFilter, setPreviewFilter] = useState('all')

  // Search & Filters
  const [productSearch, setProductSearch] = useState('')
  const [candidateSearch, setCandidateSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [queueFilter, setQueueFilter] = useState<'all' | 'new' | 'review'>('all')
  const [selectedWorkItem, setSelectedWorkItem] = useState<WorkQueueItem | null>(null)
  const [resolutionMode, setResolutionMode] = useState<'create_canonical' | 'associate_existing' | 'ignore'>('create_canonical')
  const [resolutionLoading, setResolutionLoading] = useState(false)
  const [resolutionError, setResolutionError] = useState<string | null>(null)
  const [selectedExistingProductId, setSelectedExistingProductId] = useState('')
  const [existingProductSearch, setExistingProductSearch] = useState('')
  const [quickProductForm, setQuickProductForm] = useState({
    canonical_name: '',
    category: '',
    subcategory: '',
    comparison_unit: 'piece'
  })
  const [selectedProductIds, setSelectedProductIds] = useState<number[]>([])
  const [bulkCategoryAction, setBulkCategoryAction] = useState<'keep' | 'set' | 'clear'>('keep')
  const [bulkSubcategoryAction, setBulkSubcategoryAction] = useState<'keep' | 'set' | 'clear'>('keep')
  const [bulkCategory, setBulkCategory] = useState('')
  const [bulkSubcategory, setBulkSubcategory] = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkMessage, setBulkMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

  // Modals / Forms
  const [showProductModal, setShowProductModal] = useState(false)
  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [productForm, setProductForm] = useState({
    sku_interno: '',
    canonical_name: '',
    order_name: '',
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

  useEffect(() => {
    if (selectedProduct) {
      fetchAliases(selectedProduct.id)
    } else {
      setAliases([])
    }
  }, [selectedProduct])

  const handleImportSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importSupplierId || !importFile) return

    if (!importDryRun && createMissingProducts) {
      const confirmed = window.confirm(
        'IMPORTAZIONE PRIMO LISTINO\n\nLe righe senza corrispondenza esatta creeranno nuovi prodotti canonici. ' +
        'Non verranno effettuati abbinamenti fuzzy automatici. Vuoi procedere?'
      )
      if (!confirmed) return
    }
    
    setImportLoading(true)
    setImportError(null)
    setImportResult(null)
    
    const formData = new FormData()
    formData.append('file', importFile)
    
    try {
      const headers = getHeaders()
      const fetchHeaders: any = { ...headers }
      delete fetchHeaders['Content-Type']

      const query = new URLSearchParams({
        dry_run: String(importDryRun),
        create_missing_products: String(createMissingProducts)
      })
      const res = await fetch(`${API_BASE}/product-identity/import-supplier-list/${importSupplierId}?${query}`, {
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
      const res = await fetch(`${API_BASE}/match-candidates/work-queue`, { headers: getHeaders() })
      if (!res.ok) throw new Error("Errore nel recupero della coda prodotti")
      const data = await res.json()
      setWorkQueue(data)
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
        order_name: productForm.order_name || null,
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

  const openWorkResolution = (
    item: WorkQueueItem,
    mode: 'create_canonical' | 'associate_existing' | 'ignore'
  ) => {
    setSelectedWorkItem(item)
    setResolutionMode(mode)
    setResolutionError(null)
    setSelectedExistingProductId(mode === 'associate_existing' && item.best_candidate
      ? String(item.best_candidate.product_id)
      : '')
    setExistingProductSearch('')
    setQuickProductForm({
      canonical_name: item.suggested_product.canonical_name,
      category: item.suggested_product.category || '',
      subcategory: '',
      comparison_unit: item.suggested_product.comparison_unit || 'piece'
    })
  }

  const resolveWorkItem = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedWorkItem) return
    if (resolutionMode === 'associate_existing' && !selectedExistingProductId) {
      setResolutionError('Seleziona il prodotto canonico da associare.')
      return
    }
    if (resolutionMode === 'create_canonical' && !quickProductForm.canonical_name.trim()) {
      setResolutionError('Inserisci il nome canonico del prodotto.')
      return
    }

    const payload: Record<string, unknown> = {
      invoice_line_ids: selectedWorkItem.invoice_line_ids,
      action: resolutionMode
    }
    if (resolutionMode === 'associate_existing') {
      payload.product_id = Number(selectedExistingProductId)
    }
    if (resolutionMode === 'create_canonical') {
      payload.canonical_data = {
        ...selectedWorkItem.suggested_product,
        canonical_name: quickProductForm.canonical_name.trim(),
        category: quickProductForm.category.trim() || null,
        subcategory: quickProductForm.subcategory.trim() || null,
        comparison_unit: quickProductForm.comparison_unit
      }
    }

    setResolutionLoading(true)
    setResolutionError(null)
    try {
      const res = await fetch(`${API_BASE}/match-candidates/work-queue/resolve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      if (!res.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message
        throw new Error(detail || 'Impossibile risolvere il prodotto')
      }
      setSelectedWorkItem(null)
      await Promise.all([fetchCandidates(), fetchProducts()])
    } catch (err: any) {
      setResolutionError(err.message)
    } finally {
      setResolutionLoading(false)
    }
  }

  const openEditProduct = (product: Product) => {
    setEditingProduct(product)
    setProductForm({
      sku_interno: product.sku_interno || '',
      canonical_name: product.canonical_name,
      order_name: product.order_name || '',
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

  const toggleProductSelection = (productId: number) => {
    if (!selectedProductIds.includes(productId) && selectedProductIds.length >= 1000) {
      setBulkMessage({ type: 'error', text: 'Puoi modificare al massimo 1.000 prodotti per operazione.' })
      return
    }
    setSelectedProductIds(current => (
      current.includes(productId) ? current.filter(id => id !== productId) : [...current, productId]
    ))
    setBulkMessage(null)
  }

  const handleBulkClassificationUpdate = async () => {
    setBulkMessage(null)

    if (selectedProductIds.length === 0) {
      setBulkMessage({ type: 'error', text: 'Seleziona almeno un prodotto.' })
      return
    }
    if (bulkCategoryAction === 'keep' && bulkSubcategoryAction === 'keep') {
      setBulkMessage({ type: 'error', text: 'Scegli almeno una modifica da applicare.' })
      return
    }
    if (bulkCategoryAction === 'set' && !bulkCategory.trim()) {
      setBulkMessage({ type: 'error', text: 'Inserisci la nuova categoria.' })
      return
    }
    if (bulkSubcategoryAction === 'set' && !bulkSubcategory.trim()) {
      setBulkMessage({ type: 'error', text: 'Inserisci la nuova sottocategoria.' })
      return
    }

    const changes: string[] = []
    if (bulkCategoryAction === 'set') changes.push(`categoria “${bulkCategory.trim()}”`)
    if (bulkCategoryAction === 'clear') changes.push('rimozione categoria')
    if (bulkSubcategoryAction === 'set') changes.push(`sottocategoria “${bulkSubcategory.trim()}”`)
    if (bulkSubcategoryAction === 'clear') changes.push('rimozione sottocategoria')

    if (!window.confirm(`Applicare ${changes.join(' e ')} a ${selectedProductIds.length} prodotti?`)) return

    const payload: { product_ids: number[], category?: string | null, subcategory?: string | null } = {
      product_ids: selectedProductIds
    }
    if (bulkCategoryAction === 'set') payload.category = bulkCategory.trim()
    if (bulkCategoryAction === 'clear') payload.category = null
    if (bulkSubcategoryAction === 'set') payload.subcategory = bulkSubcategory.trim()
    if (bulkSubcategoryAction === 'clear') payload.subcategory = null

    setBulkLoading(true)
    try {
      const res = await fetch(`${API_BASE}/products/bulk-classification`, {
        method: 'PATCH',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      })
      const data = await res.json()
      if (!res.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message
        throw new Error(detail || 'Errore durante la modifica massiva')
      }

      const updatedById = new Map<number, Product>(data.products.map((product: Product) => [product.id, product]))
      setProducts(current => current.map(product => updatedById.get(product.id) || product))
      setSelectedProduct(current => current ? updatedById.get(current.id) || current : null)
      setSelectedProductIds([])
      setBulkCategoryAction('keep')
      setBulkSubcategoryAction('keep')
      setBulkCategory('')
      setBulkSubcategory('')
      setBulkMessage({ type: 'success', text: `${data.updated_count} prodotti aggiornati correttamente.` })
    } catch (err: any) {
      setBulkMessage({ type: 'error', text: err.message })
    } finally {
      setBulkLoading(false)
    }
  }

  const filteredProducts = products.filter(p => {
    const matchesSearch = p.canonical_name.toLowerCase().includes(productSearch.toLowerCase()) ||
      (p.order_name || '').toLowerCase().includes(productSearch.toLowerCase()) ||
      (p.sku_interno || '').toLowerCase().includes(productSearch.toLowerCase())
    const matchesCategory = !categoryFilter || p.category === categoryFilter
    return matchesSearch && matchesCategory
  })

  const availableCategories = Array.from(new Set(products.map(product => product.category).filter(Boolean) as string[])).sort()
  const availableSubcategories = Array.from(new Set(products.map(product => product.subcategory).filter(Boolean) as string[])).sort()
  const visibleProductIds = filteredProducts.map(product => product.id)
  const allVisibleProductsSelected = visibleProductIds.length > 0 && visibleProductIds.every(id => selectedProductIds.includes(id))

  const filteredWorkItems = (workQueue?.items || []).filter(item => {
    const search = candidateSearch.toLowerCase()
    const matchesSearch = item.raw_description.toLowerCase().includes(search)
      || item.supplier_name.toLowerCase().includes(search)
      || (item.supplier_code || '').toLowerCase().includes(search)
    const matchesType = queueFilter === 'all'
      || (queueFilter === 'new' && item.recommendation === 'create_canonical')
      || (queueFilter === 'review' && item.recommendation === 'associate_existing')
    return matchesSearch && matchesType
  })

  const filteredExistingProducts = products.filter(product => {
    const search = existingProductSearch.toLowerCase()
    return product.is_active && (
      product.canonical_name.toLowerCase().includes(search)
      || (product.sku_interno || '').toLowerCase().includes(search)
    )
  }).slice(0, 50)
  const selectedExistingProduct = products.find(product => String(product.id) === selectedExistingProductId)
  const matchingExistingProducts = selectedExistingProduct
    && !filteredExistingProducts.some(product => product.id === selectedExistingProduct.id)
    ? [selectedExistingProduct, ...filteredExistingProducts]
    : filteredExistingProducts

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
            <Sparkles size={18} /> Prodotti da classificare ({workQueue?.summary.work_items || 0})
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
                    order_name: '',
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
                {availableCategories.map(category => (
                  <option key={category} value={category} style={{ background: '#13131c' }}>{category}</option>
                ))}
              </select>
            </div>

            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '14px',
              padding: '16px',
              border: '1px solid rgba(59,130,246,0.25)',
              borderRadius: '10px',
              background: 'rgba(59,130,246,0.06)'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700 }}>
                    <Tag size={17} color="var(--accent-blue)" /> Modifica massiva etichette e categorie
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px' }}>
                    {selectedProductIds.length} prodotti selezionati · massimo 1.000 per operazione
                  </div>
                </div>
                {selectedProductIds.length > 0 && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      setSelectedProductIds([])
                      setBulkMessage(null)
                    }}
                    style={{ padding: '7px 11px', fontSize: '0.8rem' }}
                  >
                    Deseleziona tutto
                  </button>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', alignItems: 'end' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                  Azione categoria
                  <select
                    value={bulkCategoryAction}
                    onChange={e => setBulkCategoryAction(e.target.value as 'keep' | 'set' | 'clear')}
                    style={{ padding: '9px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                  >
                    <option value="keep">Non modificare</option>
                    <option value="set">Imposta</option>
                    <option value="clear">Rimuovi</option>
                  </select>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                  Nuova categoria
                  <input
                    type="text"
                    list="bulk-category-options"
                    maxLength={100}
                    disabled={bulkCategoryAction !== 'set'}
                    value={bulkCategory}
                    onChange={e => setBulkCategory(e.target.value)}
                    placeholder="Es. beverage"
                    style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                  />
                  <datalist id="bulk-category-options">
                    {availableCategories.map(category => <option key={category} value={category} />)}
                  </datalist>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                  Azione sottocategoria
                  <select
                    value={bulkSubcategoryAction}
                    onChange={e => setBulkSubcategoryAction(e.target.value as 'keep' | 'set' | 'clear')}
                    style={{ padding: '9px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                  >
                    <option value="keep">Non modificare</option>
                    <option value="set">Imposta</option>
                    <option value="clear">Rimuovi</option>
                  </select>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                  Nuova sottocategoria
                  <input
                    type="text"
                    list="bulk-subcategory-options"
                    maxLength={100}
                    disabled={bulkSubcategoryAction !== 'set'}
                    value={bulkSubcategory}
                    onChange={e => setBulkSubcategory(e.target.value)}
                    placeholder="Es. bibite gassate"
                    style={{ padding: '9px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                  />
                  <datalist id="bulk-subcategory-options">
                    {availableSubcategories.map(subcategory => <option key={subcategory} value={subcategory} />)}
                  </datalist>
                </label>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={bulkLoading || selectedProductIds.length === 0}
                  onClick={handleBulkClassificationUpdate}
                  style={{ padding: '10px 14px', justifyContent: 'center', whiteSpace: 'nowrap' }}
                >
                  {bulkLoading ? <RefreshCw className="animate-spin" size={16} /> : <Tag size={16} />}
                  Applica
                </button>
              </div>

              {bulkMessage && (
                <div style={{
                  padding: '9px 11px',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: bulkMessage.type === 'success' ? 'var(--status-green)' : 'var(--status-red)',
                  background: bulkMessage.type === 'success' ? 'rgba(16,185,129,0.08)' : 'var(--status-red-bg)'
                }}>
                  {bulkMessage.text}
                </div>
              )}
            </div>

            {loading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><RefreshCw className="animate-spin" /></div>
            ) : (
              <div className="table-responsive">
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: '38px' }}>
                        <input
                          type="checkbox"
                          aria-label="Seleziona tutti i prodotti visibili"
                          checked={allVisibleProductsSelected}
                          onChange={() => {
                            setSelectedProductIds(current => allVisibleProductsSelected
                              ? current.filter(id => !visibleProductIds.includes(id))
                              : Array.from(new Set([...current, ...visibleProductIds])).slice(0, 1000)
                            )
                            setBulkMessage(null)
                          }}
                          style={{ width: '16px', height: '16px', accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
                        />
                      </th>
                      <th>SKU Interno</th>
                      <th>Nome Canonico</th>
                      <th>Categoria</th>
                      <th>Formato / Volume</th>
                      <th>Confezione fornitore</th>
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
                        <td onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            aria-label={`Seleziona ${p.canonical_name}`}
                            checked={selectedProductIds.includes(p.id)}
                            onChange={() => toggleProductSelection(p.id)}
                            style={{ width: '16px', height: '16px', accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
                          />
                        </td>
                        <td><code style={{ color: 'var(--accent-blue)' }}>{p.sku_interno || 'N/D'}</code></td>
                        <td style={{ fontWeight: 600 }}>{p.canonical_name}{p.order_name && <div style={{ color: '#6ee7b7', fontSize: '0.72rem', marginTop: 3 }}>Ordine: {p.order_name}</div>}</td>
                        <td>
                          <span className="badge" style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)' }}>
                            {p.category || 'Senza categoria'}
                          </span>
                          {p.subcategory && <div style={{ marginTop: '4px', color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{p.subcategory}</div>}
                        </td>
                        <td>{p.volume_ml ? `${p.volume_ml} ml` : p.weight_g ? `${p.weight_g} g` : 'N/D'}</td>
                        <td>
                          {p.supplier_pack_sizes?.length
                            ? p.supplier_pack_sizes.map(size => `x${size}`).join(' / ')
                            : 'N/D'}
                        </td>
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
                        <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '40px' }}>
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
                      pack_qty: selectedProduct.supplier_pack_sizes?.[0]?.toString() || '',
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

      {/* VIEW: Smart product work queue */}
      {activeSubTab === 'candidates' && (
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0 }}>Inbox prodotti da classificare</h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: '6px 0 0' }}>
              Una decisione per prodotto: tutte le righe identiche vengono risolte insieme e memorizzate per le fatture future.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
            {[
              ['Decisioni reali', workQueue?.summary.work_items || 0, 'var(--accent-blue)'],
              ['Righe risolte insieme', workQueue?.summary.invoice_lines || 0, 'white'],
              ['Nuovi prodotti probabili', workQueue?.summary.probable_new_products || 0, 'var(--status-orange)'],
              ['Suggerimenti affidabili', workQueue?.summary.reliable_suggestions || 0, 'var(--status-green)']
            ].map(([label, value, color]) => (
              <div key={String(label)} style={{ padding: '14px', borderRadius: '10px', background: 'rgba(255,255,255,0.025)', border: '1px solid var(--border-glass)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{label}</div>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: String(color), marginTop: '3px' }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
              <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input
                type="text"
                placeholder="Cerca descrizione, codice o fornitore..."
                value={candidateSearch}
                onChange={e => setCandidateSearch(e.target.value)}
                style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px 10px 38px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white', outline: 'none' }}
              />
            </div>
            {[
              ['all', 'Tutti'],
              ['new', 'Nuovi probabili'],
              ['review', 'Da confermare']
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`btn ${queueFilter === value ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setQueueFilter(value as 'all' | 'new' | 'review')}
                style={{ padding: '9px 12px' }}
              >
                {label}
              </button>
            ))}
          </div>

          {(workQueue?.summary.weak_candidates_hidden || 0) > 0 && (
            <div style={{ padding: '10px 12px', borderRadius: '8px', background: 'rgba(16,185,129,0.07)', color: 'var(--status-green)', fontSize: '0.8rem' }}>
              <strong>{workQueue?.summary.weak_candidates_hidden}</strong> falsi suggerimenti sotto soglia nascosti automaticamente.
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {filteredWorkItems.map(item => (
              <div key={item.work_key} style={{ padding: '18px', border: '1px solid var(--border-glass)', borderRadius: '12px', background: 'rgba(255,255,255,0.018)', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '18px', alignItems: 'center' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 750, fontSize: '1rem' }}>{item.raw_description}</span>
                    <span className="badge" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)' }}>
                      {item.occurrence_count} {item.occurrence_count === 1 ? 'riga' : 'righe'} · {item.invoice_count} {item.invoice_count === 1 ? 'fattura' : 'fatture'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '7px', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                    <span>{item.supplier_name}</span>
                    {item.supplier_code && <><span>•</span><span>Codice: <code>{item.supplier_code}</code></span></>}
                    <span>•</span>
                    <span>Ultima fattura: {new Date(item.latest_invoice_date).toLocaleDateString('it-IT')}</span>
                  </div>

                  {item.best_candidate ? (
                    <div style={{ marginTop: '11px', padding: '9px 11px', borderRadius: '8px', background: 'rgba(16,185,129,0.07)', color: 'var(--status-green)', fontSize: '0.82rem' }}>
                      <Check size={14} style={{ verticalAlign: '-2px', marginRight: '6px' }} />
                      Possibile corrispondenza: <strong>{item.best_candidate.canonical_name}</strong> · {item.best_candidate.score.toFixed(0)}%
                    </div>
                  ) : (
                    <div style={{ marginTop: '11px', padding: '9px 11px', borderRadius: '8px', background: 'rgba(245,158,11,0.07)', color: 'var(--status-orange)', fontSize: '0.82rem' }}>
                      Nessuna corrispondenza affidabile: probabile nuovo prodotto. I suggerimenti casuali non vengono mostrati.
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end', maxWidth: '440px' }}>
                  <button type="button" className="btn btn-secondary" onClick={() => openWorkResolution(item, 'ignore')} style={{ padding: '9px 11px', color: 'var(--text-secondary)' }}>
                    <X size={15} /> Ignora
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={() => openWorkResolution(item, 'associate_existing')} style={{ padding: '9px 12px' }}>
                    <Search size={15} /> Associa esistente
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => openWorkResolution(item, item.best_candidate ? 'associate_existing' : 'create_canonical')}
                    style={{ padding: '9px 13px' }}
                  >
                    {item.best_candidate ? <><Check size={15} /> Conferma suggerimento</> : <><Plus size={15} /> Crea e risolvi</>}
                  </button>
                </div>
              </div>
            ))}

            {filteredWorkItems.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px', background: 'rgba(255,255,255,0.01)', borderRadius: '12px' }}>
                Nessun prodotto da classificare con i filtri selezionati.
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

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '4px 0' }}>
                <input
                  type="checkbox"
                  id="importDryRunCheckbox"
                  checked={importDryRun}
                  onChange={e => setImportDryRun(e.target.checked)}
                  style={{ width: '16px', height: '16px', accentColor: 'var(--accent-blue)' }}
                />
                <label htmlFor="importDryRunCheckbox" style={{ fontSize: '0.85rem', color: 'white', fontWeight: 500, cursor: 'pointer' }}>
                  Modalità prova / dry run (simulazione)
                </label>
              </div>

              <div style={{ padding: '12px', border: '1px solid rgba(59,130,246,0.25)', borderRadius: '8px', background: 'rgba(59,130,246,0.06)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <input
                    type="checkbox"
                    id="createMissingProductsCheckbox"
                    checked={createMissingProducts}
                    onChange={e => setCreateMissingProducts(e.target.checked)}
                    style={{ width: '16px', height: '16px', marginTop: '2px', accentColor: 'var(--accent-blue)' }}
                  />
                  <label htmlFor="createMissingProductsCheckbox" style={{ fontSize: '0.85rem', color: 'white', fontWeight: 600, cursor: 'pointer' }}>
                    Primo listino: crea i prodotti mancanti
                    <span style={{ display: 'block', marginTop: '5px', color: 'var(--text-secondary)', fontWeight: 400, lineHeight: 1.4 }}>
                      Usa il nome esatto del fornitore. Prezzo unitario e confezione restano separati; nessun abbinamento simile viene approvato automaticamente.
                    </span>
                  </label>
                </div>
              </div>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={importLoading || !importSupplierId || !importFile}
                style={{ padding: '12px', justifyContent: 'center' }}
              >
                {importLoading ? (
                  <>
                    <RefreshCw className="animate-spin" size={18} /> {importDryRun ? 'Simulazione in corso...' : 'Importazione in corso...'}
                  </>
                ) : (
                  importDryRun ? 'Simula Importazione (Dry Run)' : 'Avvia Importazione Reale'
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
                  {importResult.dry_run && (
                    <div style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', padding: '10px 14px', borderRadius: '8px', color: '#60a5fa', fontSize: '0.85rem', fontWeight: 500 }}>
                      <strong>SIMULAZIONE ATTIVA:</strong> Nessun record è stato realmente modificato o creato nel database.
                    </div>
                  )}
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
                    <div style={{ background: 'rgba(59,130,246,0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(59,130,246,0.15)' }}>
                      <span style={{ fontSize: '0.8rem', color: '#60a5fa' }}>
                        Prodotti {importResult.dry_run ? 'da creare (simulati)' : 'creati'}
                      </span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#60a5fa' }}>{importResult.prodotti_creati || 0}</div>
                    </div>
                    <div style={{ background: 'rgba(59,130,246,0.03)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(59,130,246,0.1)' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Prodotti esatti riutilizzati</span>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{importResult.prodotti_riutilizzati || 0}</div>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    <div>Alias Creati: <strong>{importResult.alias_approvati_creati}</strong></div>
                    <div>Alias Esistenti: <strong>{importResult.alias_gia_esistenti_riconosciuti}</strong></div>
                    <div>Prezzi Creati: <strong>{importResult.prezzi_nuovi_creati}</strong></div>
                    <div>Prezzi Invariati: <strong>{importResult.prezzi_invariati}</strong></div>
                    <div>Prezzi Storicizzati: <strong>{importResult.prezzi_storicizzati}</strong></div>
                  </div>

                  {importResult.match_candidates_creati > 0 && importResult.dry_run && (
                    <div style={{ background: 'rgba(255, 200, 0, 0.05)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255, 200, 0, 0.1)' }}>
                      <span style={{ fontSize: '0.85rem', color: '#ffb700' }}>
                        Simulazione: nessun candidato è stato salvato. Per il primo listino attiva “crea i prodotti mancanti” e ripeti prima la prova.
                      </span>
                    </div>
                  )}

                  {importResult.match_candidates_creati > 0 && !importResult.dry_run && (
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
            <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Anteprima Importazione (Top 20)</h4>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('all')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'all' ? 'var(--accent-blue)' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'all' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Tutti
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('new_product')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'new_product' ? 'var(--accent-blue)' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'new_product' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Nuovi prodotti
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('matched')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'matched' ? 'var(--accent-blue)' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'matched' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Matched (Auto)
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('parking')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'parking' ? 'var(--accent-blue)' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'parking' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Parking Area
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('errors')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'errors' ? 'var(--status-red)' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'errors' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Errori/Avvisi
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('low_score')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'low_score' ? '#ff9900' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'low_score' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Score Basso (&lt;70%)
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('no_price')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'no_price' ? '#9d4edd' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'no_price' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Senza Prezzo (€0)
                  </button>
                  <button
                    type="button"
                    onClick={() => setPreviewFilter('no_pack')}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      background: previewFilter === 'no_pack' ? '#06d6a0' : 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '6px',
                      color: previewFilter === 'no_pack' ? 'white' : 'var(--text-secondary)',
                      cursor: 'pointer'
                    }}
                  >
                    Senza Pack (x1)
                  </button>
                </div>
              </div>
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
                    {importResult.preview
                      .filter((p: any) => {
                        if (previewFilter === 'matched') return ['auto_match', 'exact_product'].includes(p.match_status);
                        if (previewFilter === 'new_product') return p.match_status === 'new_product';
                        if (previewFilter === 'parking') return p.match_status === 'parking';
                        if (previewFilter === 'errors') return p.warning && p.warning.length > 0;
                        if (previewFilter === 'low_score') return p.score < 70;
                        if (previewFilter === 'no_price') return p.price === 0 || !p.price;
                        if (previewFilter === 'no_pack') return p.pack_qty === null || p.pack_qty === undefined || p.pack_qty === 1;
                        return true;
                      })
                      .map((p: any, idx: number) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--border-glass)' }}>
                        <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{p.row_index}</td>
                        <td style={{ padding: '10px' }}><code>{p.supplier_code || '-'}</code></td>
                        <td style={{ padding: '10px' }}>{p.raw_description}</td>
                        <td style={{ padding: '10px', textAlign: 'right', fontWeight: 600 }}>€ {p.price.toFixed(2)}</td>
                        <td style={{ padding: '10px', color: 'var(--text-secondary)' }}>{p.uom} (x{p.pack_qty})</td>
                        <td style={{ padding: '10px' }}>
                          {p.match_status === 'new_product' ? (
                            <span style={{ color: '#60a5fa', background: 'rgba(59,130,246,0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }}>
                              Nuovo prodotto ({p.matched_sku})
                            </span>
                          ) : ['auto_match', 'exact_product'].includes(p.match_status) ? (
                            <span style={{ color: 'var(--status-green)', background: 'rgba(0, 200, 100, 0.1)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem' }} title={p.match_reason === 'existing_alias' ? 'Matched via existing alias' : 'Matched via score threshold'}>
                              Auto ({p.matched_sku}) {p.score ? `(Score ${p.score.toFixed(0)}%)` : ''}
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

      {/* MODAL: Smart work queue resolution */}
      {selectedWorkItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
          <div className="glass-panel" style={{ width: '100%', maxWidth: '650px', maxHeight: '90vh', overflowY: 'auto', padding: '28px', display: 'flex', flexDirection: 'column', gap: '18px', border: '1px solid rgba(255,255,255,0.1)' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.2rem' }}>
                {resolutionMode === 'create_canonical' && 'Crea prodotto e memorizza alias'}
                {resolutionMode === 'associate_existing' && 'Associa a un prodotto esistente'}
                {resolutionMode === 'ignore' && 'Ignora questo articolo'}
              </h3>
              <p style={{ margin: '7px 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                <strong style={{ color: 'white' }}>{selectedWorkItem.raw_description}</strong><br />
                Una sola conferma risolverà {selectedWorkItem.occurrence_count} {selectedWorkItem.occurrence_count === 1 ? 'riga' : 'righe'} e insegnerà il riconoscimento per il futuro.
              </p>
            </div>

            <form onSubmit={resolveWorkItem} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {resolutionMode === 'create_canonical' && (
                <>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Nome canonico
                    <input
                      autoFocus
                      required
                      maxLength={255}
                      value={quickProductForm.canonical_name}
                      onChange={e => setQuickProductForm({ ...quickProductForm, canonical_name: e.target.value })}
                      style={{ padding: '11px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                    />
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      Categoria
                      <input
                        list="quick-product-categories"
                        maxLength={100}
                        value={quickProductForm.category}
                        onChange={e => setQuickProductForm({ ...quickProductForm, category: e.target.value })}
                        placeholder="Es. monouso, pulizia, beverage"
                        style={{ padding: '11px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                      />
                      <datalist id="quick-product-categories">
                        {availableCategories.map(category => <option key={category} value={category} />)}
                        <option value="monouso" /><option value="pulizia" /><option value="packaging" />
                      </datalist>
                    </label>
                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      Sottocategoria facoltativa
                      <input
                        maxLength={100}
                        value={quickProductForm.subcategory}
                        onChange={e => setQuickProductForm({ ...quickProductForm, subcategory: e.target.value })}
                        style={{ padding: '11px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                      />
                    </label>
                  </div>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Unità di confronto
                    <select
                      value={quickProductForm.comparison_unit}
                      onChange={e => setQuickProductForm({ ...quickProductForm, comparison_unit: e.target.value })}
                      style={{ padding: '11px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                    >
                      <option value="piece">Pezzo</option>
                      <option value="box">Confezione / scatola</option>
                      <option value="liter">Litro</option>
                      <option value="kg">Chilogrammo</option>
                      <option value="bottle">Bottiglia</option>
                    </select>
                  </label>
                </>
              )}

              {resolutionMode === 'associate_existing' && (
                <>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Cerca prodotto
                    <div style={{ position: 'relative' }}>
                      <Search size={15} style={{ position: 'absolute', left: '11px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                      <input
                        autoFocus
                        value={existingProductSearch}
                        onChange={e => setExistingProductSearch(e.target.value)}
                        placeholder="Nome canonico o SKU..."
                        style={{ width: '100%', boxSizing: 'border-box', padding: '11px 11px 11px 35px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                      />
                    </div>
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Prodotto canonico
                    <select
                      required
                      size={Math.min(8, Math.max(3, matchingExistingProducts.length))}
                      value={selectedExistingProductId}
                      onChange={e => setSelectedExistingProductId(e.target.value)}
                      style={{ padding: '8px', minHeight: '120px', background: '#13131c', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'white' }}
                    >
                      {matchingExistingProducts.map(product => (
                        <option key={product.id} value={product.id}>
                          {product.canonical_name} {product.sku_interno ? `· ${product.sku_interno}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}

              {resolutionMode === 'ignore' && (
                <div style={{ padding: '13px', borderRadius: '8px', background: 'rgba(245,158,11,0.08)', color: 'var(--status-orange)', fontSize: '0.85rem' }}>
                  Le {selectedWorkItem.occurrence_count} righe saranno contrassegnate come “nessun match”. Non verrà creato alcun prodotto o alias.
                </div>
              )}

              {resolutionError && (
                <div style={{ padding: '10px', borderRadius: '8px', background: 'var(--status-red-bg)', color: 'var(--status-red)', fontSize: '0.82rem' }}>
                  {resolutionError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '4px' }}>
                <button type="button" className="btn btn-secondary" disabled={resolutionLoading} onClick={() => setSelectedWorkItem(null)}>Annulla</button>
                <button type="submit" className="btn btn-primary" disabled={resolutionLoading}>
                  {resolutionLoading ? <RefreshCw className="animate-spin" size={16} /> : <Check size={16} />}
                  {resolutionMode === 'create_canonical' && `Crea e risolvi ${selectedWorkItem.occurrence_count}`}
                  {resolutionMode === 'associate_existing' && `Associa e risolvi ${selectedWorkItem.occurrence_count}`}
                  {resolutionMode === 'ignore' && `Ignora ${selectedWorkItem.occurrence_count}`}
                </button>
              </div>
            </form>
          </div>
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
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Nome rapido ordine (facoltativo)</label>
                <input
                  type="text"
                  maxLength={120}
                  placeholder="es. GUANTI"
                  value={productForm.order_name}
                  onChange={e => setProductForm({ ...productForm, order_name: e.target.value })}
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
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Unità base canonica (normalmente 1)</label>
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
