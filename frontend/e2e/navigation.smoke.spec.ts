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
  expect(errors).toEqual([])
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
