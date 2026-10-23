import { expect, test } from '@playwright/test'
import { mockAuthenticatedUser } from './auth-mocks'
import { mockWorkflowApi } from './workflow-mocks'

test('generates a draft when only the required project document is uploaded', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page)
  await page.goto('/')

  const generateButton = page.getByRole('button', { name: 'Generate Draft WBS' })
  await expect(generateButton).toBeDisabled()

  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('project scope'),
  })

  await expect(generateButton).toBeEnabled()
  await generateButton.click()

  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible()
  await expect(page.getByText('project-scope.pdf')).toBeVisible()
  await expect(page.getByText('WBS Reference Template')).toHaveCount(0)
})
