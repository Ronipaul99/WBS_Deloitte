import { expect, test } from '@playwright/test'
import { ADMIN_PERMISSIONS } from './auth-mocks'

const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
]

for (const viewport of viewports) {
  test(`${viewport.name} login layout`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401 }))
    await page.route('**/api/v1/me', (route) => route.fulfill({ status: 401 }))
    await page.goto('/')

    await expect(page.getByRole('heading', { name: 'WBS Genie' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    await expect(page.getByLabel('Email address')).toBeVisible()
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(hasHorizontalOverflow).toBe(false)
  })
}

test('signs in and renders the authenticated workspace', async ({ page }) => {
  let authenticated = false
  await page.route('**/api/v1/tenants/*/projects', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }))
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401 }))
  await page.route('**/api/v1/auth/login', async (route) => {
    authenticated = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'test-access-token', token_type: 'bearer', expires_in: 900 }),
    })
  })
  await page.route('**/api/v1/me', async (route) => {
    if (!authenticated) {
      await route.fulfill({ status: 401 })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: '00000000-0000-0000-0000-000000000001',
        email: 'planner@example.com',
        display_name: 'Test Planner',
        identity_providers: ['local'],
        can_change_password: true,
        can_manage_sessions: true,
        tenants: [{
          id: '00000000-0000-0000-0000-000000000001',
          name: 'Test Workspace',
          slug: 'test',
          role: 'ADMIN',
          permissions: ADMIN_PERMISSIONS,
        }],
      }),
    })
  })

  await page.goto('/')
  await page.getByLabel('Email address').fill('planner@example.com')
  await page.getByLabel('Password', { exact: true }).fill('a-valid-test-password')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('heading', { name: 'Welcome back, Test' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create project', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open profile menu' })).toContainText('Test Planner')
  const storedKeys = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }))
  expect(storedKeys).toEqual({ local: [], session: [] })
})
