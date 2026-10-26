import { expect, test } from '@playwright/test'
import { mockAuthenticatedUser } from './auth-mocks'
import { scannedPdfBuffer, textPdfBuffer } from './pdf-fixtures'
import { createProjectAndOpenWbs, mockWorkflowApi } from './workflow-mocks'

test('processes the required project document without a reference template', async ({ page }) => {
  await mockAuthenticatedUser(page)
  const state = await mockWorkflowApi(page)
  await page.goto('/')
  await createProjectAndOpenWbs(page)

  const generateButton = page.getByRole('button', { name: 'Process Document' })
  await expect(generateButton).toBeDisabled()

  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/octet-stream',
    buffer: textPdfBuffer(),
  })

  await expect(generateButton).toBeEnabled()
  await generateButton.click()

  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible()
  await expect(page.getByText('project-scope.pdf')).toBeVisible()
  await expect(page.getByText('WBS Reference Template')).toHaveCount(0)
  expect(state.ingestionStarts).toBe(1)
  expect(state.summaryStarts).toBe(0)
})

test('selects a scanned PDF through drag and drop', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page)
  await page.goto('/')
  await createProjectAndOpenWbs(page)

  const bytes = scannedPdfBuffer().toString('base64')
  const dataTransfer = await page.evaluateHandle((base64) => {
    const binary = window.atob(base64)
    const data = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const transfer = new DataTransfer()
    transfer.items.add(new File([data], 'scanned.scope.pdf', { type: 'application/pdf' }))
    return transfer
  }, bytes)
  await page.getByRole('button', { name: 'Upload project scope document' }).dispatchEvent(
    'drop',
    { dataTransfer },
  )
  await dataTransfer.dispose()

  await expect(page.getByText('scanned.scope.pdf')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Process Document' })).toBeEnabled()
})

test('shows a stable safe PDF upload error', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page, {
    documentUploadError: {
      code: 'PDF_ENCRYPTED',
      message: 'provider response that the UI must not render',
      status: 422,
    },
  })
  await page.goto('/')
  await createProjectAndOpenWbs(page)
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'encrypted.pdf',
    mimeType: 'application/pdf',
    buffer: textPdfBuffer(),
  })

  await page.getByRole('button', { name: 'Process Document' }).click()

  await expect(page.getByText('Password-protected PDFs are not supported.')).toBeVisible()
  await expect(page.getByText('provider response that the UI must not render')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Process Document' })).toBeEnabled()
})

test('blocks duplicate submission while a document upload is active', async ({ page }) => {
  await mockAuthenticatedUser(page)
  const state = await mockWorkflowApi(page, { documentUploadDelayMs: 300 })
  await page.goto('/')
  await createProjectAndOpenWbs(page)
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: textPdfBuffer(),
  })
  const generateButton = page.getByRole('button', { name: 'Process Document' })

  await generateButton.evaluate((button: HTMLButtonElement) => {
    button.click()
    button.click()
  })

  await expect(page.getByRole('button', { name: 'Starting processing...' })).toBeDisabled()
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible()
  expect(state.documentUploads).toBe(1)
  expect(state.ingestionStarts).toBe(1)
})

test('recovers the action state after an aborted upload request', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page, { abortDocumentUpload: true })
  await page.goto('/')
  await createProjectAndOpenWbs(page)
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: textPdfBuffer(),
  })

  await page.getByRole('button', { name: 'Process Document' }).click()

  await expect(page.getByText('The document upload could not be completed. Please try again.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Process Document' })).toBeEnabled()
})

test('does not advertise or accept legacy document formats', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page)
  await page.goto('/')
  await createProjectAndOpenWbs(page)
  const projectInput = page.locator('input[type="file"]').first()
  const templateInput = page.locator('input[type="file"]').nth(1)

  await expect(projectInput).toHaveAttribute('accept', '.pdf,.docx,.xlsx,.csv')
  await expect(templateInput).toHaveAttribute('accept', '.xlsx,.csv,.xml')
  await projectInput.setInputFiles({
    name: 'legacy.doc',
    mimeType: 'application/msword',
    buffer: Buffer.from('legacy'),
  })
  await expect(page.getByText(/Unsupported file format \(\.doc\)/)).toBeVisible()
  await projectInput.setInputFiles({
    name: 'legacy.xls',
    mimeType: 'application/vnd.ms-excel',
    buffer: Buffer.from('legacy'),
  })
  await expect(page.getByText(/Unsupported file format \(\.xls\)/)).toBeVisible()
})

for (const fixture of [
  { name: 'scope.pdf', mimeType: 'application/pdf' },
  { name: 'scope.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
  { name: 'scope.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
  { name: 'scope.csv', mimeType: 'text/csv' },
]) {
  test(`accepts ${fixture.name.split('.').pop()?.toUpperCase()} from the project-document picker`, async ({ page }) => {
    await mockAuthenticatedUser(page)
    await mockWorkflowApi(page)
    await page.goto('/')
    await createProjectAndOpenWbs(page)

    await page.locator('input[type="file"]').first().setInputFiles({
      ...fixture,
      buffer: Buffer.from('synthetic project scope'),
    })

    await expect(page.getByText(fixture.name)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Process Document' })).toBeEnabled()
  })
}

test('rejects a project document above the browser convenience limit', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page)
  await page.goto('/')
  await createProjectAndOpenWbs(page)

  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'oversized.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(25 * 1024 * 1024 + 1),
  })

  await expect(page.getByText('File exceeds maximum upload size of 25MB.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Process Document' })).toBeDisabled()
})

test('opens the project picker from the keyboard', async ({ page }) => {
  await mockAuthenticatedUser(page)
  await mockWorkflowApi(page)
  await page.goto('/')
  await createProjectAndOpenWbs(page)

  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Upload project scope document' }).focus()
  await page.keyboard.press('Enter')
  await (await chooser).setFiles({
    name: 'keyboard.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('item,scope\n1,synthetic'),
  })

  await expect(page.getByText('keyboard.csv')).toBeVisible()
})
