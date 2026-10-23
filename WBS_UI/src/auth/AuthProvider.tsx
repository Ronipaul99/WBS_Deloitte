import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  apiRequest,
  clearAccessToken,
  loginRequest,
  logoutRequest,
  refreshAccessToken,
  setAuthenticationLostHandler,
  setAuthorizationDeniedHandler,
} from '../services/apiClient';
import {
  changePassword as changePasswordRequest,
  logoutAll as logoutAllRequest,
} from '../services/accountSecurity';
import { AuthContext } from './authContext';
import type {
  AuthContextValue,
  AuthStatus,
  CurrentUser,
  TenantMembership,
} from './authContext';
import type { Permission } from './permissions';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeTenant, setActiveTenant] = useState<TenantMembership | null>(null);

  const clearAuthentication = useCallback(() => {
    clearAccessToken();
    setUser(null);
    setActiveTenant(null);
    setStatus('unauthenticated');
  }, []);

  useEffect(() => {
    setAuthenticationLostHandler(clearAuthentication);
    return () => setAuthenticationLostHandler(null);
  }, [clearAuthentication]);

  const loadUser = useCallback(async () => {
    const currentUser = await apiRequest<CurrentUser>('/me');
    setUser(currentUser);
    setActiveTenant((selected) => {
      const refreshedSelection = selected
        ? currentUser.tenants.find((tenant) => tenant.id === selected.id)
        : null;
      return refreshedSelection
        ?? (currentUser.tenants.length === 1 ? currentUser.tenants[0] : null);
    });
    setStatus('authenticated');
    return currentUser;
  }, []);

  useEffect(() => {
    setAuthorizationDeniedHandler(() => {
      void loadUser().catch(() => undefined);
    });
    return () => setAuthorizationDeniedHandler(null);
  }, [loadUser]);

  useEffect(() => {
    let mounted = true;
    const bootstrap = async () => {
      await refreshAccessToken();
      try {
        const currentUser = await apiRequest<CurrentUser>('/me');
        if (!mounted) return;
        setUser(currentUser);
        setActiveTenant(currentUser.tenants.length === 1 ? currentUser.tenants[0] : null);
        setStatus('authenticated');
      } catch {
        if (!mounted) return;
        clearAuthentication();
      }
    };
    void bootstrap();
    return () => {
      mounted = false;
    };
  }, [clearAuthentication]);

  const login = useCallback(async (email: string, password: string) => {
    await loginRequest(email, password);
    await loadUser();
  }, [loadUser]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } catch {
      // Local credentials are still cleared if the API is temporarily unavailable.
    } finally {
      clearAuthentication();
    }
  }, [clearAuthentication]);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await changePasswordRequest(currentPassword, newPassword);
    clearAuthentication();
  }, [clearAuthentication]);

  const logoutAll = useCallback(async () => {
    await logoutAllRequest();
    clearAuthentication();
  }, [clearAuthentication]);

  const can = useCallback(
    (permission: Permission) => activeTenant?.permissions.includes(permission) ?? false,
    [activeTenant],
  );

  const value = useMemo<AuthContextValue>(() => ({
    status,
    user,
    activeTenant,
    login,
    logout,
    changePassword,
    logoutAll,
    refreshUser: loadUser,
    selectTenant: setActiveTenant,
    can,
  }), [activeTenant, can, changePassword, loadUser, login, logout, logoutAll, status, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

