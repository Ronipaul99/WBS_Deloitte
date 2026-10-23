import { apiRequest } from './apiClient';

export interface AccountSession {
  id: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  current: boolean;
}

interface MessageResponse {
  message: string;
}

export function getSessions(): Promise<AccountSession[]> {
  return apiRequest<AccountSession[]>('/auth/sessions');
}

export function revokeSession(sessionId: string): Promise<MessageResponse> {
  return apiRequest<MessageResponse>(`/auth/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<MessageResponse> {
  return apiRequest<MessageResponse>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function logoutAll(): Promise<MessageResponse> {
  return apiRequest<MessageResponse>('/auth/logout-all', { method: 'POST' });
}
