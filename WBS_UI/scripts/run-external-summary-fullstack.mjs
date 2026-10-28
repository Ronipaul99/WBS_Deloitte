// Isolated Step 6 harness. No application env, database URL, ports or services are reused.
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { createServer } from 'node:net';
import { mkdirSync, writeFileSync, existsSync, rmSync, cpSync } from 'node:fs';
import { resolve, dirname, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const ui = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(ui, '..');
const backend = join(root, 'backend');
const parent = join(backend, '.data', 'external-summary-step06');
const run = `run-${Date.now()}-${randomBytes(6).toString('hex')}`;
const runtime = join(parent, run);
mkdirSync(runtime, { recursive: true });
const children = [];
let logs = '';
const secret = () => randomBytes(32).toString('base64url');
const key = secret(), token = secret(), password = secret(), tenant = randomUUID();
const inherited = Object.fromEntries(['PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'PATHEXT'].filter((k) => process.env[k]).map((k) => [k, process.env[k]]));
function sanitize(text) { for (const s of [key, token, password]) text = text.replaceAll(s, '[redacted]'); return text; }
async function port() {
  return new Promise((resolvePort, reject) => {
    const server = createServer(); server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const value = server.address().port; server.close(() => resolvePort(value)); });
  });
}
const [apiPort, fakePort, uiPort] = await Promise.all([port(), port(), port()]);
const api = `http://127.0.0.1:${apiPort}`;
const uiOrigin = `http://127.0.0.1:${uiPort}`;
const env = { ...inherited, PYTHONPATH: backend, PYTHONIOENCODING: 'utf-8',
  SUMMARY_TEST_ROOT: runtime, SUMMARY_TEST_API_PORT: String(apiPort), SUMMARY_TEST_FAKE_PORT: String(fakePort), SUMMARY_TEST_UI_PORT: String(uiPort),
  SUMMARY_TEST_UPSTREAM_KEY: key, SUMMARY_TEST_CONTROL_TOKEN: token,
  DEV_TENANT_ID: tenant,
  DEV_USER_PASSWORD: password, AUTH_JWT_SECRET: secret(), AUTH_AUDIT_SECRET: secret(),
};
function start(command, args, cwd, childEnv) {
  const child = spawn(command, args, { cwd, env: childEnv, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
  children.push(child);
  for (const stream of [child.stdout, child.stderr]) stream.on('data', (chunk) => { logs = (logs + sanitize(chunk.toString())).slice(-60000); });
  child.on('error', (error) => { logs += sanitize(error.message); });
  return child;
}
async function ready(url, child) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error('Owned test process exited before readiness');
    try { if ((await fetch(url, { signal: AbortSignal.timeout(1000) })).ok) return; } catch { /* startup */ }
    await new Promise((done) => setTimeout(done, 100));
  }
  throw new Error('Owned test process readiness timeout');
}
async function stop(child) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === 'win32') spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  else child.kill('SIGTERM');
  await Promise.race([new Promise((done) => child.once('exit', done)), new Promise((done) => setTimeout(done, 1500))]);
}
let code = 1;
let cleaning;
async function released(portNumber) {
  return new Promise((done) => {
    const server = createServer();
    server.once('error', () => done(false));
    server.listen(portNumber, '127.0.0.1', () => server.close(() => done(true)));
  });
}
function cleanup() {
  if (cleaning) return cleaning;
  cleaning = (async () => {
    for (const child of [...children].reverse()) await stop(child);
    const portsReleased = await Promise.all([apiPort, fakePort, uiPort].map(released));
    const stopped = children.every((c) => c.exitCode !== null || c.signalCode !== null || !c.pid);
    const artifacts = join(parent, 'artifacts-' + run);
    mkdirSync(artifacts, { recursive: true });
    writeFileSync(join(artifacts, 'sanitized-process.log'), logs);
    if (existsSync(join(runtime, 'artifacts'))) cpSync(join(runtime, 'artifacts'), join(artifacts, 'browser'), { recursive: true });
    const target = resolve(runtime);
    if (!target.startsWith(resolve(parent) + sep) || !run.startsWith('run-')) throw new Error('Unsafe cleanup target');
    if (stopped) rmSync(target, { recursive: true, force: true });
    if (!stopped || portsReleased.some((value) => !value)) code = 1;
    writeFileSync(join(artifacts, 'cleanup.json'), JSON.stringify({ exit_code: code, owned_pids: children.map((c) => c.pid),
      owned_ports: [apiPort, fakePort, uiPort], ports_released: portsReleased, stopped, database_and_uploads_removed: !existsSync(runtime) }));
    process.stdout.write(`Isolated summary test exit=${code}; cleanup verified=${stopped && portsReleased.every(Boolean)}; artifacts=${artifacts}\n`);
    if (code) process.stderr.write(logs.slice(-12000));
  })();
  return cleaning;
}
for (const [signal, exitCode] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  process.once(signal, () => { code = exitCode; void cleanup().finally(() => process.exit(exitCode)); });
}

try {
  const python = join(backend, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const service = start(python, ['-m', 'uvicorn', 'tests.summary_fullstack_support.server:app', '--host', '127.0.0.1', '--port', String(apiPort), '--no-access-log'], backend, env);
  await ready(api, service);
  const fake = start(python, ['-m', 'uvicorn', 'tests.summary_fullstack_support.server:fake', '--host', '127.0.0.1', '--port', String(fakePort), '--no-access-log'], backend, env);
  await ready(`http://127.0.0.1:${fakePort}`, fake);
  writeFileSync(join(runtime, 'vite.config.mts'), `import base from '../../../../WBS_UI/vite.config.ts';\nexport default {...base, envDir: ${JSON.stringify(runtime)}, cacheDir: ${JSON.stringify(join(runtime, 'vite-cache'))}};\n`);
  const client = start(process.execPath, ['node_modules/vite/bin/vite.js', '--config', join(runtime, 'vite.config.mts'), '--configLoader', 'runner', '--host', '127.0.0.1', '--port', String(uiPort), '--strictPort'], ui,
    { ...inherited, VITE_API_URL: api + '/api/v1' });
  await ready(uiOrigin, client);
  writeFileSync(join(runtime, 'playwright.config.mts'), `import {defineConfig} from '../../../../WBS_UI/node_modules/@playwright/test/index.mjs';\nexport default defineConfig({testDir:${JSON.stringify(join(ui, 'tests/fullstack'))},testMatch:'external-summary.spec.ts',outputDir:${JSON.stringify(join(runtime, 'artifacts'))},workers:1,timeout:45000,reporter:'line',use:{baseURL:${JSON.stringify(uiOrigin)},screenshot:'only-on-failure'}});\n`);
  writeFileSync(join(runtime, 'owned-processes.json'), JSON.stringify({ processes: children.map((c) => c.pid), ports: [apiPort, fakePort, uiPort] }));
  const tests = start(process.execPath, ['node_modules/@playwright/test/cli.js', 'test', '--config', join(runtime, 'playwright.config.mts')], ui,
    { ...inherited, SUMMARY_TEST_API: api, SUMMARY_TEST_TOKEN: token, SUMMARY_TEST_PASSWORD: password, SUMMARY_TEST_TENANT: tenant });
  tests.stdout.on('data', (chunk) => process.stdout.write(sanitize(chunk.toString())));
  tests.stderr.on('data', (chunk) => process.stderr.write(sanitize(chunk.toString())));
  code = await new Promise((done) => tests.once('exit', (value) => done(value ?? 1)));
} catch (error) {
  process.stderr.write(sanitize(error.message) + '\n');
} finally {
  await cleanup();
}
process.exitCode = code;
