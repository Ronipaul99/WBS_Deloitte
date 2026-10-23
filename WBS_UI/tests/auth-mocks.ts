import type { Page } from '@playwright/test';
import { PERMISSIONS } from '../src/auth/permissions';
import type { Permission } from '../src/auth/permissions';
import type { TenantMembership } from '../src/auth/authContext';

export const VIEWER_PERMISSIONS: Permission[] = [
  PERMISSIONS.PROJECT_READ,
  PERMISSIONS.DOCUMENT_READ,
  PERMISSIONS.SUMMARY_READ,
  PERMISSIONS.TEMPLATE_READ,
  PERMISSIONS.WBS_READ,
  PERMISSIONS.VALIDATION_READ,
  PERMISSIONS.EXPORT_READ,
  PERMISSIONS.JOB_READ,
];

export const EDITOR_PERMISSIONS: Permission[] = [
  ...VIEWER_PERMISSIONS,
  PERMISSIONS.PROJECT_CREATE,
  PERMISSIONS.PROJECT_UPDATE,
  PERMISSIONS.DOCUMENT_UPLOAD,
  PERMISSIONS.SUMMARY_UPDATE,
  PERMISSIONS.SUMMARY_APPROVE,
  PERMISSIONS.TEMPLATE_MANAGE,
  PERMISSIONS.WBS_GENERATE,
  PERMISSIONS.WBS_UPDATE,
  PERMISSIONS.VALIDATION_RUN,
  PERMISSIONS.EXPORT_CREATE,
  PERMISSIONS.JOB_MANAGE,
];

export const ADMIN_PERMISSIONS: Permission[] = Object.values(PERMISSIONS);

interface AuthenticatedUserOptions {
  role?: 'VIEWER' | 'EDITOR' | 'ADMIN';
  permissions?: Permission[];
  identityProviders?: string[];
  canChangePassword?: boolean;
  canManageSessions?: boolean;
  tenants?: TenantMembership[];
}

export async function mockAuthenticatedUser(
  page: Page,
  options: AuthenticatedUserOptions = {},
): Promise<void> {
  const role = options.role ?? 'ADMIN';
  const permissions = options.permissions ?? ADMIN_PERMISSIONS;
  const identityProviders = options.identityProviders ?? ['local'];
  const canChangePassword = options.canChangePassword ?? true;
  const canManageSessions = options.canManageSessions ?? true;
  const tenants = options.tenants ?? [{
    id: '00000000-0000-0000-0000-000000000001',
    name: 'Test Workspace',
    slug: 'test',
    role,
    permissions,
  }];
  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'test-access-token', token_type: 'bearer', expires_in: 900 }),
    });
  });
  await page.route('**/api/v1/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: '00000000-0000-0000-0000-000000000001',
        email: 'planner@example.com',
        display_name: 'Test Planner',
        identity_providers: identityProviders,
        can_change_password: canChangePassword,
        can_manage_sessions: canManageSessions,
        tenants,
      }),
    });
  });
}
