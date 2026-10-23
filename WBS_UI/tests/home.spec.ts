import { expect, test } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';

const projects = [
  {
    id: '10000000-0000-0000-0000-000000000001',
    tenant_id: '00000000-0000-0000-0000-000000000001',
    name: 'Smart Office Fit-Out',
    description: 'Technology-enabled workplace delivery',
    status: 'active',
    created_at: '2026-10-20T10:00:00Z',
    updated_at: '2026-10-22T15:30:00Z',
  },
  {
    id: '10000000-0000-0000-0000-000000000002',
    tenant_id: '00000000-0000-0000-0000-000000000001',
    name: 'Regional Data Centre',
    description: null,
    status: 'active',
    created_at: '2026-10-18T10:00:00Z',
    updated_at: '2026-10-21T13:15:00Z',
  },
];

test('home is the first authenticated tab and shows live workspace projects', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/tenants/*/projects/*/wbs/versions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: '70000000-0000-0000-0000-000000000002',
        tenant_id: projects[0].tenant_id,
        project_id: projects[0].id,
        generation_job_id: null,
        version_number: 2,
        status: 'DRAFT',
        tree: [{ id: 'phase-1', name: 'Delivery', children: [{ id: 'wp-1', name: 'Install' }] }],
        scope_coverage: { overallScore: 92 },
        created_at: '2026-10-23T09:00:00Z',
        updated_at: '2026-10-23T09:00:00Z',
      },
      {
        id: '70000000-0000-0000-0000-000000000001',
        tenant_id: projects[0].tenant_id,
        project_id: projects[0].id,
        generation_job_id: null,
        version_number: 1,
        status: 'DRAFT',
        tree: [{ id: 'phase-1', name: 'Delivery' }],
        scope_coverage: { overallScore: 84 },
        created_at: '2026-10-22T09:00:00Z',
        updated_at: '2026-10-22T09:00:00Z',
      },
    ]),
  }));
  await page.route('**/api/v1/tenants/*/projects', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as { name: string; description: string | null };
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          ...projects[0],
          id: '10000000-0000-0000-0000-000000000003',
          name: payload.name,
          description: payload.description,
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(projects),
    });
  });

  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Home' })).toHaveClass(/app-nav-button-active/);
  await expect(page.getByRole('heading', { name: 'Welcome back, Test' })).toBeVisible();
  await expect(page.getByText('Smart Office Fit-Out')).toBeVisible();
  await expect(page.getByText('Regional Data Centre')).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Workspace overview' }).getByText('2', { exact: true }),
  ).toBeVisible();

  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create a project' })).toBeVisible();
  await page.getByLabel('Project name').fill('New Office Campus');
  await page.getByLabel('Description Optional').fill('New workspace delivery');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'New Office Campus' })).toBeVisible();
  await expect(page.getByText('New workspace delivery')).toBeVisible();
  await expect(page.getByText('WBS version 2')).toBeVisible();
  await expect(page.getByText('WBS version 1')).toBeVisible();
  await expect(page.getByText('92%')).toBeVisible();
  await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create Work Breakdown Structure' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New Office Campus', exact: true })).toBeVisible();
});

test('home empty state stays usable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/tenants/*/projects', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'No projects yet' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create first project' })).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
