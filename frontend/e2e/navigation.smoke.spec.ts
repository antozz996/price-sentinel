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
        ? { mode: 'dry_run', total_rows: 12, valid_records: 11, suppliers_detected: ['MARR', 'DAC'], errors_count: 0, errors: [], records_preview: [{ sku_interno: 'POMODORI', descrizione: 'Pomodori pelati', unita_misura: 'Kg', prezzi: { MARR: '2.50', DAC: '2.70' } }], records_preview_truncated: false }
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
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dryRun
      ? { mode: 'dry_run', total_rows: 12, valid_records: 11, suppliers_detected: ['MARR', 'DAC'], errors_count: 0, errors: [], records_preview: [{ sku_interno: 'POMODORI', descrizione: 'Pomodori pelati', unita_misura: 'Kg', prezzi: { MARR: '2.50', DAC: '2.70' } }], records_preview_truncated: false }
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
  await expect(page.getByRole('button', { name: 'Conferma e importa' })).toBeDisabled()
  expect(dryRunModes).toEqual(['true'])
  await page.getByRole('checkbox', { name: /Ho verificato righe e fornitori/ }).check()
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
