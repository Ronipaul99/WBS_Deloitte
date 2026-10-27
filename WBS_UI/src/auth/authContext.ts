import { createContext, useContext } from 'react';
import type { Permission } from './permissions';

export interface TenantMembership {
  id: string;
  name: string;
  slug: string;
  role: string | null;
  permissions: Permission[];
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  identity_providers: string[];
  can_change_password: boolean;
  can_manage_sessions: boolean;
  tenants: TenantMembership[];
}

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  activeTenant: TenantMembership | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  logoutAll: () => Promise<void>;
  refreshUser: () => Promise<CurrentUser>;
  selectTenant: (tenant: TenantMembership | null) => void;
  can: (permission: Permission) => boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider.');
  return context;
}
