import { apiRequest } from './apiClient';

export type MembershipRole = 'ADMIN' | 'EDITOR' | 'VIEWER';

export interface TenantMember {
  user_id: string;
  email: string;
  display_name: string;
  role: MembershipRole;
  status: 'ACTIVE' | 'INACTIVE';
  joined_at: string;
}

export interface TenantInvitation {
  id: string;
  email: string;
  role: MembershipRole;
  status: 'PENDING';
  expires_at: string;
  created_at: string;
  invited_by_user_id: string;
}

export interface MemberListResponse {
  members: TenantMember[];
  invitations: TenantInvitation[];
  total_members: number;
  total_invitations: number;
  offset: number;
  limit: number;
}

export interface InvitationAcceptanceResponse {
  message: string;
  account_created: boolean;
  tenant_id: string;
  tenant_name: string;
  role: MembershipRole;
}

export function getTenantMembers(
  tenantId: string,
  search: string,
  offset: number,
  limit: number,
): Promise<MemberListResponse> {
  const query = new URLSearchParams({
    search,
    offset: String(offset),
    limit: String(limit),
  });
  return apiRequest<MemberListResponse>(`/tenants/${tenantId}/members?${query}`);
}

export function inviteTenantMember(
  tenantId: string,
  email: string,
  role: MembershipRole,
): Promise<TenantInvitation> {
  return apiRequest<TenantInvitation>(`/tenants/${tenantId}/invitations`, {
    method: 'POST',
    body: JSON.stringify({ email, role }),
  });
}

export function resendTenantInvitation(
  tenantId: string,
  invitationId: string,
): Promise<TenantInvitation> {
  return apiRequest<TenantInvitation>(
    `/tenants/${tenantId}/invitations/${invitationId}/resend`,
    { method: 'POST' },
  );
}

export function revokeTenantInvitation(
  tenantId: string,
  invitationId: string,
): Promise<void> {
  return apiRequest<void>(`/tenants/${tenantId}/invitations/${invitationId}`, {
    method: 'DELETE',
  });
}

export function updateTenantMemberRole(
  tenantId: string,
  userId: string,
  role: MembershipRole,
): Promise<TenantMember> {
  return apiRequest<TenantMember>(`/tenants/${tenantId}/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

export function removeTenantMember(tenantId: string, userId: string): Promise<void> {
  return apiRequest<void>(`/tenants/${tenantId}/members/${userId}`, {
    method: 'DELETE',
  });
}

export function acceptTenantInvitation(
  token: string,
  setup?: { displayName: string; password: string },
): Promise<InvitationAcceptanceResponse> {
  return apiRequest<InvitationAcceptanceResponse>('/auth/accept-invitation', {
    method: 'POST',
    body: JSON.stringify({
      token,
      ...(setup
        ? { display_name: setup.displayName, password: setup.password }
        : {}),
    }),
  });
}
