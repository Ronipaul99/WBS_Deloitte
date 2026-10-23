const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000/api/v1'
).replace(/\/$/, '');

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let authenticationLostHandler: (() => void) | null = null;
let authorizationDeniedHandler: (() => void) | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly fieldErrors: Record<string, string> = {},
    public readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
  }
}

function requestHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }
  return headers;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let message = 'The request could not be completed.';
  const fieldErrors: Record<string, string> = {};
  try {
    const body = (await response.json()) as {
      detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
    };
    if (typeof body.detail === 'string') {
      message = body.detail;
    } else if (Array.isArray(body.detail)) {
      for (const issue of body.detail) {
        const field = issue.loc?.slice(1).join('.') || 'request';
        if (issue.msg) fieldErrors[field] = issue.msg;
      }
      message = Object.values(fieldErrors)[0] ?? 'Some submitted fields are invalid.';
    }
  } catch {
    // The response did not contain a JSON error body.
  }
  const rawRetryAfter = response.headers.get('Retry-After');
  const retryAfter = rawRetryAfter ? Number.parseInt(rawRetryAfter, 10) : Number.NaN;
  return new ApiError(
    message,
    response.status,
    fieldErrors,
    Number.isFinite(retryAfter) ? retryAfter : null,
  );
}

export function clearAccessToken(): void {
  accessToken = null;
}

export function enterpriseSignInUrl(): string {
  const url = new URL(`${API_BASE_URL}/auth/sso/start`, window.location.origin);
  url.searchParams.set('return_path', '/sso/callback');
  return url.toString();
}

export function setAuthenticationLostHandler(handler: (() => void) | null): void {
  authenticationLostHandler = handler;
}

export function setAuthorizationDeniedHandler(handler: (() => void) | null): void {
  authorizationDeniedHandler = handler;
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
          accessToken = null;
          return false;
        }
        const body = (await response.json()) as { access_token: string };
        accessToken = body.access_token;
        return true;
      } catch {
        accessToken = null;
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
  retryAfterRefresh = true,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: requestHeaders(init),
  });

  if (response.status === 401 && retryAfterRefresh && await refreshAccessToken()) {
    return apiRequest<T>(path, init, false);
  }
  if (response.status === 401) {
    accessToken = null;
    authenticationLostHandler?.();
  }
  if (response.status === 403 && path !== '/me') authorizationDeniedHandler?.();
  if (!response.ok) throw await errorFromResponse(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function fileNameFromDisposition(value: string | null): string | null {
  if (!value) return null;
  const encoded = value.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) return decodeURIComponent(encoded).replace(/[\\/]/g, '_');
  const basic = value.match(/filename="?([^";]+)"?/i)?.[1];
  return basic ? basic.replace(/[\\/]/g, '_') : null;
}

export async function apiDownload(
  path: string,
  allowedContentTypes: string[],
  init?: RequestInit,
  retryAfterRefresh = true,
  fallbackFileName = 'wbs-export',
): Promise<{ blob: Blob; fileName: string }> {
  const apiBase = new URL(API_BASE_URL, window.location.origin);
  const requestUrl = new URL(path, `${apiBase.origin}/`);
  const protectedPathPrefix = `${apiBase.pathname.replace(/\/$/, '')}/`;
  if (requestUrl.origin !== apiBase.origin || !requestUrl.pathname.startsWith(protectedPathPrefix)) {
    throw new ApiError('The API returned an untrusted export download URL.', 502);
  }
  const response = await fetch(requestUrl, {
    ...init,
    credentials: 'include',
    headers: requestHeaders(init),
  });
  if (response.status === 401 && retryAfterRefresh && await refreshAccessToken()) {
    return apiDownload(path, allowedContentTypes, init, false, fallbackFileName);
  }
  if (response.status === 401) {
    accessToken = null;
    authenticationLostHandler?.();
  }
  if (response.status === 403) authorizationDeniedHandler?.();
  if (!response.ok) throw await errorFromResponse(response);

  const contentType = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() ?? '';
  if (!allowedContentTypes.includes(contentType)) {
    throw new ApiError('The export response had an unexpected file type.', 502);
  }
  const fileName = fileNameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackFileName;
  return { blob: await response.blob(), fileName };
}

export async function loginRequest(email: string, password: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  const body = (await response.json()) as { access_token: string };
  accessToken = body.access_token;
}

export async function forgotPasswordRequest(email: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/auth/forgot-password`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  const body = (await response.json()) as { message: string };
  return body.message;
}

export async function resetPasswordRequest(
  token: string,
  newPassword: string,
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/auth/reset-password`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  const body = (await response.json()) as { message: string };
  return body.message;
}

export async function logoutRequest(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
  } finally {
    accessToken = null;
  }
}
