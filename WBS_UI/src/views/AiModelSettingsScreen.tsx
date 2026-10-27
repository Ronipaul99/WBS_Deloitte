import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../services/apiClient';
import { defaultModelSettings, llmApi } from '../services/llmApi';
import type { ApprovedEndpoint, ConnectionTest, ModelConnection, ModelProfile, ModelSettings } from '../services/llmApi';
import './AiModelSettingsScreen.css';

const providers = { openai: 'OpenAI · Responses', anthropic: 'Claude · Messages', openai_compatible: 'Custom / Llama · Chat Completions' };
export default function AiModelSettingsScreen({ tenantId }: { tenantId: string }) {
  const [connections, setConnections] = useState<ModelConnection[]>([]);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [endpoints, setEndpoints] = useState<ApprovedEndpoint[]>([]);
  const [connection, setConnection] = useState<ModelConnection | null>(null);
  const [profile, setProfile] = useState<ModelProfile | null>(null);
  const [name, setName] = useState('');
  const [provider, setProvider] = useState('openai_compatible');
  const [approval, setApproval] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [secret, setSecret] = useState('');
  const [replace, setReplace] = useState(false);
  const [profileName, setProfileName] = useState('');
  const [connectionId, setConnectionId] = useState('');
  const [modelId, setModelId] = useState('');
  const [settings, setSettings] = useState<ModelSettings>(defaultModelSettings);
  const [test, setTest] = useState<ConnectionTest | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  async function load(signal?: AbortSignal) {
    const [c, p, e] = await Promise.all([llmApi.connections(tenantId, signal), llmApi.profiles(tenantId, signal), llmApi.endpoints(tenantId, signal)]);
    if (!signal?.aborted && mounted.current) { setConnections(c); setProfiles(p); setEndpoints(e); setConnection(old => old ? c.find(item => item.id === old.id) ?? old : null); setProfile(old => old ? p.find(item => item.id === old.id) ?? old : null); }
  }
  useEffect(() => {
    const controller = new AbortController();
    mounted.current = true;
    void load(controller.signal).catch(() => {
      if (!controller.signal.aborted) setError('AI model management is unavailable. Ask an administrator to check server configuration.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { mounted.current = false; controller.abort(); };
    // The parent keys this screen by tenant, clearing all transient form state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);
  useEffect(() => {
    if (!test || !['queued', 'running'].includes(test.state)) return;
    const controller = new AbortController(); let count = 0;
    const timer = window.setInterval(() => {
      if (++count > 60) { window.clearInterval(timer); setNotice('Polling paused. Use Refresh to check again.'); return; }
      void llmApi.testStatus(tenantId, test.connection_id, test.id, controller.signal).then(result => {
        if (!controller.signal.aborted) { setTest(result); if (!['queued', 'running'].includes(result.state)) void load(controller.signal).catch(() => { if (!controller.signal.aborted) setError('Settings refresh is unavailable.'); }); }
      }).catch(() => { if (!controller.signal.aborted) { window.clearInterval(timer); setError('Test status is unavailable. Refresh to retry.'); } });
    }, 2000);
    return () => { controller.abort(); window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, test?.id, test?.state]);

  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); if (mounted.current) { setSecret(''); setReplace(false); setNotice('Saved.'); await load(); } }
    catch (reason) { if (mounted.current) setError(reason instanceof ApiError && reason.status === 409 ? 'Settings changed or qualification is missing. Refresh and review before trying again.' : 'Operation unavailable. Check permissions, approved endpoint, server keys and test authorization.'); }
    finally { if (mounted.current) setBusy(false); }
  }
  function editConnection(c: ModelConnection | null) {
    setConnection(c); setName(c?.name ?? ''); setProvider(c?.provider ?? 'openai_compatible');
    setApproval(c?.endpoint.approval_id ?? ''); setEnabled(c?.enabled ?? false);
    setSecret(''); setReplace(false);
  }
  function editProfile(p: ModelProfile | null) {
    setProfile(p); setProfileName(p?.name ?? ''); setConnectionId(p?.connection_id ?? '');
    setModelId(p?.model_id ?? ''); setSettings({ ...defaultModelSettings, ...p?.settings }); setConsent(false);
  }
  function saveConnection(event: FormEvent) {
    event.preventDefault();
    if (replace && !secret) { setError('Enter a replacement API key, or turn off Replace API key to preserve it.'); return; }
    void act(async () => {
      const result = await llmApi.saveConnection(tenantId, connection?.id ?? null, {
        name, ...(connection ? { expected_revision: connection.revision } : { provider }),
        approval_id: approval, enabled, ...(replace ? { credential: { action: 'replace', secret } } : {}),
      });
      if (mounted.current) editConnection(result);
    });
  }
  function saveProfile(event: FormEvent) {
    event.preventDefault();
    void act(async () => {
      const result = await llmApi.saveProfile(tenantId, profile?.id ?? null, {
        name: profileName, model_id: modelId, settings,
        ...(profile ? { expected_revision: profile.revision } : { connection_id: connectionId }),
      });
      if (mounted.current) editProfile(result);
    });
  }
  const selectedConnection = connections.find(c => c.id === connectionId);
  const cap = profile?.capabilities;
  const numeric = (key: keyof ModelSettings, label: string, min: number, max: number) => <label>{label}<input type="number" min={min} max={max} required value={String(settings[key])} onChange={e => setSettings({ ...settings, [key]: Number(e.target.value) })} /></label>;
  return <section className="ai-models" aria-labelledby="ai-model-settings-title">
    <header><div><p className="ai-eyebrow">TENANT SETTINGS</p><h1 id="ai-model-settings-title">AI Models</h1><p>Manage approved connections and exact model profiles.</p></div><button disabled={busy} onClick={() => void act(async () => { await load(); if (test) setTest(await llmApi.testStatus(tenantId, test.connection_id, test.id)); })}>Refresh</button></header>
    <p className="ai-info">Connection tests send synthetic data only. No source PDF is sent. Localhost refers to the worker on Oracle, not your Mac. Summary generation remains separate.</p>
    {loading && <p role="status">Loading AI model settings…</p>}
    {error && <p role="alert" className="ai-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <div className="ai-columns">
      <section><h2>Provider connections</h2><button onClick={() => editConnection(null)}>New connection</button>
        <ul>{connections.map(c => <li key={c.id}><button onClick={() => editConnection(c)}>{c.name}</button><span>{c.provider} · {c.enabled ? 'Enabled' : 'Disabled'} · {c.configured ? 'Key configured' : 'Key missing'}</span></li>)}</ul>
        <form onSubmit={saveConnection} autoComplete="off"><fieldset disabled={busy}>
          <label>Connection name<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
          <label>Provider / API format<select value={provider} disabled={!!connection} onChange={e => { setProvider(e.target.value); setApproval(''); }}>{Object.entries(providers).map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label>
          <label>Approved endpoint<select required value={approval} onChange={e => setApproval(e.target.value)}><option value="">Choose an approved destination</option>{endpoints.filter(e => e.providers.includes(provider)).map(e => <option key={e.id} value={e.id}>https://{e.host}:{e.port}{e.path_prefix} · {e.auth_scheme}</option>)}</select></label>
          <label className="ai-check"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />Enable connection</label>
          <label className="ai-check"><input type="checkbox" checked={replace} onChange={e => { setReplace(e.target.checked); setSecret(''); }} />Replace API key</label>
          {replace && <label>New API key<input type="password" autoComplete="new-password" required maxLength={8192} value={secret} onChange={e => setSecret(e.target.value)} /></label>}
          <small>Saved keys are never shown. Leaving replacement off preserves the current key.</small>
          <div className="ai-actions"><button type="submit">Save connection</button><button type="button" onClick={() => editConnection(null)}>Cancel connection edit</button></div>
          {connection && <div className="ai-actions">{(['rotate', 'clear', 'disable'] as const).map(action => <button key={action} type="button" onClick={() => { if (action === 'clear' && !window.confirm('Remove this saved credential and disable the connection?')) return; void act(async () => { editConnection(await llmApi.credential(tenantId, connection.id, { expected_revision: connection.revision, change: { action } })); }); }}>{action === 'rotate' ? 'Rotate encryption' : action === 'clear' ? 'Clear credential' : 'Disable connection'}</button>)}</div>}
        </fieldset></form>
      </section>
      <section><h2>Model profiles</h2><button onClick={() => editProfile(null)}>New profile</button>
        <ul>{profiles.map(p => <li key={p.id}><button onClick={() => editProfile(p)}>{p.name}{p.is_default ? ' · Default' : ''}</button><span>{p.model_id} · {p.availability ?? (p.usable ? 'Usable' : p.qualification === 'pending' ? 'Unverified' : 'Unavailable / disabled')} · Last qualification: {p.tested_at ? new Date(p.tested_at).toLocaleString() : 'Never'}</span></li>)}</ul>
        <form onSubmit={saveProfile}><fieldset disabled={busy}>
          <label>Profile name<input required maxLength={160} value={profileName} onChange={e => setProfileName(e.target.value)} /></label>
          <label>Connection<select required disabled={!!profile} value={connectionId} onChange={e => setConnectionId(e.target.value)}><option value="">Choose connection</option>{connections.map(c => <option key={c.id} value={c.id}>{c.name} · {c.endpoint.host}</option>)}</select></label>
          <label>Exact model ID<input required maxLength={160} value={modelId} onChange={e => setModelId(e.target.value)} /></label>
          <small>Enter a model ID manually if discovery is unavailable. Limits below are configured ceilings until qualified.</small>
          <div className="ai-fields">{numeric('context_tokens', 'Configured context ceiling', 512, 1000000)}{numeric('output_tokens', 'Output ceiling', 8, 8192)}{numeric('timeout_seconds', 'Timeout seconds', 1, 600)}{numeric('max_calls', 'Run call ceiling', 1, 120)}{numeric('max_total_tokens', 'Run token ceiling', 512, 1000000)}</div>
          <label>Run cost ceiling USD (optional)<input type="number" min="0" max="100" step="0.01" value={settings.max_cost_usd ?? ''} onChange={e => setSettings({ ...settings, max_cost_usd: e.target.value || null })} /></label>
          <label>Transient attempt ceiling<input type="number" required min="1" max="8" value={settings.retry.max_attempts} onChange={e => setSettings({ ...settings, retry: { ...settings.retry, max_attempts: Number(e.target.value) } })} /></label>
          <p>Concurrency: 1. Probes make one attempt per case and do not repair. Ambiguous submissions are not automatically retried.</p>
          <label>Output format<select value={settings.output_mode} onChange={e => setSettings({ ...settings, output_mode: e.target.value })}><option value="validated_json">Validated JSON</option>{cap?.json_schema === 'supported' && <option value="native_json_schema">Native JSON schema</option>}</select></label>
          <label>Tool mode<select value={settings.tool_mode} onChange={e => setSettings({ ...settings, tool_mode: e.target.value })}><option value="none">None</option><option value="json_actions">Validated JSON actions</option>{cap?.native_tools === 'supported' && <option value="native">Native tools</option>}</select></label>
          {cap?.temperature === 'supported' && <label>Temperature<input type="number" min="0" max="1" step="0.1" value={settings.temperature ?? ''} onChange={e => setSettings({ ...settings, temperature: e.target.value === '' ? null : Number(e.target.value) })} /></label>}
          {selectedConnection?.provider === 'openai_compatible' && <label>Token limit dialect<select value={settings.options.compatible_token_parameter} onChange={e => setSettings({ ...settings, options: { compatible_token_parameter: e.target.value } })}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>}
          <div className="ai-actions"><button type="submit">Save profile</button><button type="button" onClick={() => editProfile(null)}>Cancel profile edit</button></div>
        </fieldset></form>
        {profile && selectedConnection && <div className="ai-test-controls">
          <p>Test destination: {selectedConnection.provider} at https://{selectedConnection.endpoint.host}. There is no automatic fallback.</p>
          <label className="ai-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />I understand this synthetic test may incur a small inference charge.</label>
          <div className="ai-actions">{['probe', 'discovery'].map(operation => <button key={operation} disabled={!consent || busy || !!test && ['queued', 'running'].includes(test.state)} onClick={() => void act(async () => { setTest(await llmApi.test(tenantId, selectedConnection, profile, operation)); })}>{operation === 'probe' ? 'Test model on worker' : 'Discover model IDs'}</button>)}</div>
          <div className="ai-actions"><button disabled={busy} onClick={() => void act(() => llmApi.state(tenantId, profile, true, false))}>Enable profile</button><button disabled={busy} onClick={() => void act(() => llmApi.state(tenantId, profile, true, true))}>Make default</button><button disabled={busy} onClick={() => void act(() => llmApi.state(tenantId, profile, false, false))}>Disable profile</button></div>
        </div>}
        {test && <div role="status" aria-live="polite"><strong>Worker test: {test.state}</strong><p>{test.error_code ?? (test.result.origin === 'synthetic_fixture' ? 'Synthetic fixture result; does not enable a live profile.' : 'Only current worker qualification can enable a profile.')}</p>{test.result.report?.model_ids?.map(id => <code key={id}>{id} </code>)}</div>}
      </section>
    </div>
  </section>;
}
