import { expect, test } from '@playwright/test'

const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
]

for (const viewport of viewports) {
  test(`${viewport.name} dashboard layout`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/')

    await expect(page.getByRole('heading', { name: 'Good afternoon, Rohan' })).toBeVisible()
    await expect(page.getByText('Workstream progress')).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(hasHorizontalOverflow).toBe(false)

    if (viewport.name === 'mobile') {
      await page.getByRole('button', { name: 'Open navigation' }).click()
      await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible()
      await page.getByRole('button', { name: 'Close navigation' }).click()
      await page.waitForTimeout(250)
    }

    await page.screenshot({
      path: `test-results/${viewport.name}-dashboard.png`,
      fullPage: true,
    })
  })
}
