import { test, expect, type Page } from '@playwright/test'

type Role = 'admin' | 'manager'
type MockProfile = { id: number; email: string; ruolo: Role; ruolo_dettagliato: string; location_id: number | null; tenant_id: number }

function profileFor(email: string): MockProfile {
  if (email.includes('manager')) {
    // Intentionally misleading descriptive label: must NEVER elevate privileges.
    return { id: 2, email, ruolo: 'manager', ruolo_dettagliato: 'admin', location_id: 1, tenant_id: 1 }
  }
  return { id: 1, email, ruolo: 'admin', ruolo_dettagliato: 'admin', location_id: null, tenant_id: 1 }
}

async function mockIsolatedBackend(page: Page) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = {}
    let status = 200
    if (path === '/api/v1/settings/company/') {
      body = { company_name: 'PRICE SENTINEL CI', app_subtitle: 'Synthetic UI test' }
    } else if (path === '/api/v1/auth/login') {
      const req = JSON.parse(route.request().postData() || '{}')
      const role: Role = String(req.email).includes('manager') ? 'manager' : 'admin'
      body = { access_token: role + '-ci-only-mock-token', ...profileFor(String(req.email)) }
    } else if (path === '/api/v1/auth/me') {
      const token = route.request().headers()['authorization'] || ''
      body = profileFor(token.includes('manager') ? 'manager@synthetic.test' : 'admin@synthetic.test')
    } else if (path === '/api/v1/intelligence/kpi') {
      body = { euro_recuperati: 0, euro_in_contestazione: 0, euro_a_rischio: 0, euro_attesa_manager: 0 }
    } else if (path === '/api/v1/intelligence/efficiency-leaderboard' || path === '/api/v1/intelligence/variance-loss') {
      body = []
    } else if (path === '/api/v1/ordini/notifications/feed') {
      body = { count: 0, notifications: [] }
    } else if (path === '/api/v1/feedbacks/pending-count') {
      body = { pending_count: 0 }
    } else if (path === '/api/v1/product-identity/match-candidates/work-queue') {
      body = { summary: { work_items: 0, invoice_lines: 0, weak_candidates_hidden: 0 }, items: [] }
    } else if (path === '/api/v1/auth/logout') {
      status = 204
    } else if (path === '/api/v1/listino/import-multi-supplier') {
      const dryRun = new URL(route.request().url()).searchParams.get('dry_run')
      body = dryRun === 'true'
        ? { mode: 'dry_run', preview_token: 'signed-synthetic-preview-token', total_rows: 12, valid_records: 11, suppliers_detected: ['MARR', 'DAC'], errors_count: 0, errors: [], records_preview: [{ sku_interno: 'POMODORI', descrizione: 'Pomodori pelati', unita_misura: 'Kg', prezzi: { MARR: '2.50', DAC: '2.70' }, confronti: [{ fornitore: 'MARR', prezzo_corrente: '2.40', unita_corrente: 'Kg', prezzo_proposto: '2.50', unita_proposta: 'Kg', delta_unitario: '0.10', delta_percentuale: '4.17', decorrenza_proposta: '2026-10-14', scadenza_proposta: '2026-11-12', stato: 'revisione' }, { fornitore: 'DAC', prezzo_corrente: null, unita_corrente: null, prezzo_proposto: '2.70', unita_proposta: 'Kg', delta_unitario: null, delta_percentuale: null, decorrenza_proposta: '2026-10-14', scadenza_proposta: '2026-11-12', stato: 'nuovo accordo' }] }], records_preview_truncated: false }
        : { total_rows: 12, suppliers_detected: ['MARR', 'DAC'], inserted: 11, updated: 0, skipped_duplicates: 0 }
    }
    await route.fulfill({ status, contentType: 'application/json', body: status === 204 ? '' : JSON.stringify(body) })
  })
}

async function login(page: Page, email: string) {
  await page.goto('/')
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await page.locator('input[type="email"]').fill(email)
  await page.locator('input[type="password"]').fill('ci-only-not-a-real-password')
  await page.getByRole('button', { name: 'Accedi', exact: true }).click()
  await expect(page.locator('aside.sidebar')).toBeAttached()
}

test.beforeEach(async ({ page }) => {
  await mockIsolatedBackend(page)
})

test('admin can log in and render the main dashboard without API errors', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await login(page, 'admin@synthetic.test')
  await expect(page.locator('.sidebar-nav')).toContainText('Panoramica')
  await expect(page.getByText('Dati dashboard non disponibili')).toHaveCount(0)
  await expect(page.getByText('Caricamento profilo…')).toHaveCount(0)
  await expect(page.locator('.header-title')).toBeVisible()
  const pageFitsViewport = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
  expect(pageFitsViewport, 'the application should not introduce page-level horizontal scrolling').toBe(true)
  expect(errors).toEqual([])
})

test('comparative price import previews data and requires explicit confirmation before writes', async ({ page }) => {
  const dryRunModes: string[] = []
  await page.route('**/api/v1/listino/import-multi-supplier**', async route => {
    dryRunModes.push(new URL(route.request().url()).searchParams.get('dry_run') || '')
    const dryRun = new URL(route.request().url()).searchParams.get('dry_run') === 'true'
    if (!dryRun) {
      const sent = route.request().postData() || ''
      expect(sent).toContain('signed-synthetic-preview-token')
      expect(sent).toContain('confirm_import')
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dryRun
      ? { mode: 'dry_run', preview_token: 'signed-synthetic-preview-token', total_rows: 12, valid_records: 11, suppliers_detected: ['MARR', 'DAC'], errors_count: 0, errors: [], records_preview: [{ sku_interno: 'POMODORI', descrizione: 'Pomodori pelati', unita_misura: 'Kg', prezzi: { MARR: '2.50', DAC: '2.70' }, confronti: [{ fornitore: 'MARR', prezzo_corrente: '2.40', unita_corrente: 'Kg', prezzo_proposto: '2.50', unita_proposta: 'Kg', delta_unitario: '0.10', delta_percentuale: '4.17', decorrenza_proposta: '2026-10-14', scadenza_proposta: '2026-11-12', stato: 'revisione' }, { fornitore: 'DAC', prezzo_corrente: null, unita_corrente: null, prezzo_proposto: '2.70', unita_proposta: 'Kg', delta_unitario: null, delta_percentuale: null, decorrenza_proposta: '2026-10-14', scadenza_proposta: '2026-11-12', stato: 'nuovo accordo' }] }], records_preview_truncated: false }
      : { total_rows: 12, suppliers_detected: ['MARR', 'DAC'], inserted: 11, updated: 0, skipped_duplicates: 0 }) })
  })
  await login(page, 'admin@synthetic.test')
  if (page.viewportSize()?.width && page.viewportSize()!.width <= 768) {
    await page.locator('.hamburger-btn').click()
  }
  await page.locator('.sidebar-nav').getByText('Listini master', { exact: true }).click()
  await page.getByRole('button', { name: 'Listino Comparativo' }).click()
  await page.locator('#fileInputMulti').setInputFiles({ name: 'comparativo.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('synthetic') })
  await page.getByRole('button', { name: 'Mostra anteprima' }).click()
  await expect(page.getByRole('region', { name: 'Anteprima importazione comparativa' })).toContainText('MARR, DAC')
  await expect(page.getByRole('region', { name: 'Anteprima importazione comparativa' })).toContainText('Pomodori pelati')
  const confirmButton = page.getByRole('button', { name: 'Conferma e importa' })
  await expect(confirmButton).toBeDisabled()
  await expect(confirmButton).toHaveCSS('opacity', '0.55')
  await expect(confirmButton).toHaveCSS('cursor', 'not-allowed')
  expect(dryRunModes).toEqual(['true'])
  await page.getByRole('checkbox', { name: /Ho verificato prezzo pattuito, proposta, delta/ }).check()
  await page.getByRole('button', { name: 'Conferma e importa' }).click()
  await expect(page.getByText(/Importato con successo/)).toBeVisible()
  expect(dryRunModes).toEqual(['true', 'false'])
})

test('manager with forged descriptive admin label never sees admin-only navigation', async ({ page }) => {
  await login(page, 'manager@synthetic.test')
  await expect(page.locator('.sidebar-nav')).not.toContainText('Panoramica')
  await expect(page.locator('.sidebar-nav')).not.toContainText('Carica fatture')
  await expect(page.locator('.sidebar-nav')).not.toContainText('Impostazioni')
  await expect(page.locator('.sidebar-nav')).toContainText('Registro ordini')
  await expect(page.locator('.profile-info')).not.toContainText('Amministratore')
})

test('responsive main navigation can be opened at the mobile viewport', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile viewport only')
  await login(page, 'admin@synthetic.test')
  const menu = page.locator('.hamburger-btn')
  await expect(menu).toBeVisible()
  await menu.click()
  await expect(page.locator('.sidebar-nav')).toBeVisible()
  await expect(page.locator('.sidebar-nav')).toContainText('Panoramica')
})


test('supplier offer preview finds an exact custom Sheet header without selecting calculated columns', async ({ page }, testInfo) => {
  const supplierName = 'FORNITORE TEST'
  const request = {
    id: 7,
    supplier_id: 1,
    supplier_name: supplierName,
    request_type: 'new_listino',
    status: 'submitted',
    created_at: '2026-10-19T12:00:00Z',
    expires_at: '2026-11-02T12:00:00Z',
    submitted_at: '2026-10-19T12:30:00Z',
    validita_inviata_da: '2026-10-19',
    validita_inviata_a: '2026-10-26',
    items: [{
      id: 71,
      sku_interno: 'CI-SKU-71',
      descrizione: 'PRODOTTO DI PROVA',
      prezzo_corrente: null,
      unita_corrente: null,
      prezzo_inviato: '4.2500',
      unita_inviata: 'BT',
      non_trattato: false,
      nota_fornitore: null,
      esito: 'nuova_offerta',
    }],
  }

  await page.addInitScript(() => {
    localStorage.setItem('ps.santo-graal.url', 'https://docs.google.com/spreadsheets/d/ci-synthetic-sheet/edit')
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/fornitori/') {
      await route.fulfill({ json: [{ id: 1, nome_azienda: supplierName }] })
    } else if (path === '/api/v1/categories/matrix') {
      await route.fulfill({ json: { categories: [{ nome: 'Beverage', is_active: true }], suppliers: [] } })
    } else if (path === '/api/v1/supplier-price-forms/' || path === '/api/v1/supplier-price-forms/7') {
      await route.fulfill({ json: path.endsWith('/1') ? request : [request] })
    } else {
      await route.fallback()
    }
  })
  await page.route('https://accounts.google.com/gsi/client', route => route.fulfill({
    status: 200,
    contentType: 'application/javascript',
    body: `window.google={accounts:{oauth2:{initTokenClient:({callback})=>({requestAccessToken:()=>callback({access_token:'ci-synthetic-token'})})}}};`,
  }))
  const sheetWrites: Array<{ method: string; body: unknown }> = []
  await page.route('https://sheets.googleapis.com/**', async route => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET, POST, OPTIONS',
          'access-control-allow-headers': 'Authorization, Content-Type',
        },
        body: '',
      })
      return
    }
    if (url.pathname.endsWith('/values:batchUpdate')) {
      sheetWrites.push({ method: route.request().method(), body: route.request().postDataJSON() })
      await route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' }, json: { totalUpdatedCells: 1 } })
      return
    }
    if (url.pathname.endsWith('/values:batchGet')) {
      const beverageHeader = ['Prodotto', 'Unità', 'NAVAS', 'ORIZZONTI', '3F', 'PASCARELLA', "CASA D'AMBRA", supplierName, 'MIGLIOR FORNITORE']
      const beverageRow = ['PRODOTTO DI PROVA', 'BT', '5.98', '', '', '', '', '', '3F']
      const ranges = ["'Carne'!A1:L1000", "'Pesce'!A1:L1000", "'Varie'!A1:L1000", "'BEVERAGE'!A1:L1000", "'COMPARAZIONE MATERIALI'!A1:N1000", "'FRUTTA E VERDURA'!A1:J1000"]
      await route.fulfill({
        status: 200,
        headers: { 'access-control-allow-origin': '*' },
        json: {
          valueRanges: ranges.map((range, index) => ({
            range,
            values: index === 3 ? [beverageHeader, beverageRow] : [],
          })),
        },
      })
      return
    }
    await route.fulfill({
      status: 200,
      headers: { 'access-control-allow-origin': '*' },
      json: { properties: { title: 'santo graal' }, sheets: [{ properties: { title: 'BEVERAGE' } }] },
    })
  })

  await login(page, 'admin@synthetic.test')
  if (page.viewportSize()?.width && page.viewportSize()!.width <= 768) {
    await page.locator('.hamburger-btn').click()
  }
  await page.locator('.sidebar-nav').getByText('Moduli fornitori', { exact: true }).click()
  await page.getByRole('button', { name: 'Dettaglio' }).click()
  await page.getByRole('button', { name: 'Prepara anteprima Sheet' }).click()

  await expect(page.getByText("'BEVERAGE'!H2")).toBeVisible()
  await expect(page.getByText('Pronto alla conferma')).toBeVisible()
  await expect(page.getByText("'BEVERAGE'!I2")).toHaveCount(0)
  expect(sheetWrites).toEqual([])

  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: 'Conferma e scrivi nello Sheet' }).click()
  await expect(page.getByText('Scritto', { exact: true })).toBeVisible()
  expect(sheetWrites).toEqual([{
    method: 'POST',
    body: {
      valueInputOption: 'USER_ENTERED',
      data: [{ range: "'BEVERAGE'!H2", values: [[4.25]] }],
    },
  }])
})
