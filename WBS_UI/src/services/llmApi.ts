import { apiRequest } from './apiClient';

export interface ApprovedEndpoint {
  id: string; host: string; port: number; path_prefix: string;
  auth_scheme: string; providers: string[];
}
export interface ModelConnection {
  id: string; name: string; provider: string; protocol: string; revision: number;
  enabled: boolean; configured: boolean;
  endpoint: { approval_id: string; host: string; port: number; path_prefix: string };
}
export interface ModelSettings {
  context_tokens: number; output_tokens: number; temperature: number | null;
  output_mode: string; tool_mode: string; concurrency: number; timeout_seconds: number;
  max_calls: number; max_total_tokens: number; max_cost_usd: string | null;
  options: { compatible_token_parameter: string };
  retry: { max_attempts: number; allow_format_repair: boolean; retry_statuses: number[];
    retry_before_submit: boolean; retry_ambiguous_submission: boolean;
    base_delay_seconds: number; max_delay_seconds: number };
  allowed_workflows: string[];
}
export interface ModelProfile {
  id: string; name: string; connection_id: string; revision: number; version: number;
  model_id: string; provider: string; enabled: boolean; is_default: boolean; usable: boolean;
  qualification: string; tested_at: string | null; settings: ModelSettings;
  availability?: 'usable' | 'disabled' | 'unverified' | 'stale';
  capabilities: { temperature: string; native_tools: string; json_schema: string };
  candidate_fingerprint?: string;
}
export interface ConnectionTest {
  id: string; connection_id: string; profile_id: string;
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'unavailable';
  error_code: string | null; result: { origin?: string; report?: { model_ids?: string[] } };
  calls_reserved: number; tokens_reserved: number;
}
const base = (tenant: string) => `/tenants/${encodeURIComponent(tenant)}/llm`;
export const llmApi = {
  endpoints: (t: string, signal?: AbortSignal) => apiRequest<ApprovedEndpoint[]>(`${base(t)}/endpoints`, { signal }),
  connections: (t: string, signal?: AbortSignal) => apiRequest<ModelConnection[]>(`${base(t)}/connections`, { signal }),
  profiles: (t: string, signal?: AbortSignal) => apiRequest<ModelProfile[]>(`${base(t)}/profiles`, { signal }),
  catalog: (t: string, signal?: AbortSignal) => apiRequest<ModelProfile[]>(`${base(t)}/usable-profiles`, { signal }),
  saveConnection: (t: string, id: string | null, body: unknown) => apiRequest<ModelConnection>(`${base(t)}/connections${id ? `/${id}` : ''}`, { method: id ? 'PATCH' : 'POST', body: JSON.stringify(body) }),
  credential: (t: string, id: string, body: unknown) => apiRequest<ModelConnection>(`${base(t)}/connections/${id}/credentials/rotate`, { method: 'POST', body: JSON.stringify(body) }),
  saveProfile: (t: string, id: string | null, body: unknown) => apiRequest<ModelProfile>(`${base(t)}/profiles${id ? `/${id}` : ''}`, { method: id ? 'PATCH' : 'POST', body: JSON.stringify(body) }),
  state: (t: string, p: ModelProfile, enabled: boolean, isDefault: boolean) => apiRequest<ModelProfile>(`${base(t)}/profiles/${p.id}/state`, { method: 'POST', body: JSON.stringify({ expected_revision: p.revision, enabled, is_default: isDefault }) }),
  test: (t: string, c: ModelConnection, p: ModelProfile, operation = 'probe') => apiRequest<ConnectionTest>(`${base(t)}/connections/${c.id}/test`, { method: 'POST', body: JSON.stringify({ profile_id: p.id, expected_profile_revision: p.revision, expected_connection_revision: c.revision, acknowledge_cost: true, operation, plan: { cases: ['authentication', 'model_access', 'structured_output', 'usage', 'token_limit', ...(p.settings.temperature !== null ? ['temperature'] : []), ...(p.settings.tool_mode === 'native' ? ['native_tools'] : [])] } }) }),
  testStatus: (t: string, connectionId: string, id: string, signal?: AbortSignal) => apiRequest<ConnectionTest>(`${base(t)}/connections/${connectionId}/tests/${id}`, { signal }),
};
export { defaultModelSettings } from './llmModelDefaults';
