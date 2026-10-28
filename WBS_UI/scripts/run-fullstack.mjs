import { randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const uiDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const rootDir = resolve(uiDir, '..');
const backendDir = join(rootDir, 'backend');
const runId = `${Date.now().toString(36)}${randomBytes(4).toString('hex')}`;
const postgresPassword = randomBytes(32).toString('base64url');
const runtimeDir = resolve(rootDir, '.fullstack-runtime', runId);
const statePath = join(runtimeDir, 'state.json');
const uploadRoot = join(runtimeDir, 'uploads');
const artifactDir = join(runtimeDir, 'artifacts');
const preservedArtifactDir = resolve(uiDir, 'test-results-fullstack', runId);
const apiPort = Number(process.env.FULLSTACK_API_PORT ?? 8011);
const uiPort = Number(process.env.FULLSTACK_UI_PORT ?? 5187);
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const uiOrigin = `http://127.0.0.1:${uiPort}`;
const viteEntry = join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js');
const playwrightEntry = join(uiDir, 'node_modules', '@playwright', 'test', 'cli.js');
const localPython = process.platform === 'win32'
  ? join(backendDir, '.venv', 'Scripts', 'python.exe')
  : join(backendDir, '.venv', 'bin', 'python');
const pythonCommand = existsSync(localPython)
  ? localPython
  : (process.platform === 'win32' ? 'python' : 'python3');
const documentWorkflows = process.argv.includes('--document-workflows');
const children = [];
let composeStarted = false;
let cleaning = false;

function safeRemove(path) {
  const target = resolve(path);
  const safeRoot = resolve(rootDir, '.fullstack-runtime');
  if (target !== safeRoot && !target.startsWith(`${safeRoot}${sep}`)) {
    throw new Error(`Refusing to remove path outside ${safeRoot}`);
  }
  rmSync(target, { recursive: true, force: true });
}

function preserveSanitizedArtifacts(source, destination) {
  if (!existsSync(source)) return;
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    const sourcePath = join(source, entry.name);
    const destinationPath = join(destination, entry.name);
    if (entry.isDirectory()) {
      preserveSanitizedArtifacts(sourcePath, destinationPath);
      continue;
    }
    if (!entry.name.endsWith('.png') && !entry.name.startsWith('sanitized-network-summary')) {
      continue;
    }
    mkdirSync(destination, { recursive: true });
    copyFileSync(sourcePath, destinationPath);
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? rootDir,
    env: options.env ?? process.env,
    stdio: 'inherit',
    shell: false,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with code ${result.status}`);
}

function start(command, args, cwd, env) {
  const child = spawn(command, args, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
    shell: false,
  });
  const prefix = args.some((argument) => String(argument).includes('uvicorn')) ? '[api]' : '[ui]';
  child.stdout.on('data', (chunk) => process.stdout.write(`${prefix} ${chunk}`));
  child.stderr.on('data', (chunk) => process.stderr.write(`${prefix} ${chunk}`));
  children.push(child);
  return child;
}

async function waitFor(url, label, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Service is still starting.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 300));
  }
  throw new Error(`${label} did not become ready at ${url}`);
}

async function assertPortAvailable(port, label) {
  await new Promise((resolvePromise, reject) => {
    const server = createServer();
    server.once('error', (error) => reject(
      new Error(`${label} test port ${port} is unavailable: ${error.message}`),
    ));
    server.listen(port, '127.0.0.1', () => {
      server.close((error) => error ? reject(error) : resolvePromise());
    });
  });
}

function stopWindowsPort(port) {
  const command = `$connection = Get-NetTCPConnection -State Listen -LocalPort ${port} `
    + '-ErrorAction SilentlyContinue; if ($connection) { $connection | '
    + 'Select-Object -ExpandProperty OwningProcess -Unique | '
    + 'ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }';
  spawnSync(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', command],
    { stdio: 'ignore' },
  );
}

async function stopChild(child) {
  if (!child) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill.exe', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    try {
      child.kill();
    } catch {
      // The process may already have exited.
    }
  } else {
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  }
}

async function cleanup() {
  if (cleaning) return;
  cleaning = true;
  for (const child of children.reverse()) await stopChild(child);
  if (process.platform === 'win32') {
    stopWindowsPort(apiPort);
    stopWindowsPort(uiPort);
  }
  if (composeStarted) {
    spawnSync(
      'docker',
      [
        'compose', '-p', `wbsfullstack${runId}`, '-f', 'docker-compose.fullstack.yml',
        'down', '--volumes', '--remove-orphans',
      ],
      {
        cwd: backendDir,
        env: { ...process.env, FULLSTACK_POSTGRES_PASSWORD: postgresPassword },
        stdio: 'inherit',
      },
    );
  }
  safeRemove(runtimeDir);
}

process.once('SIGINT', () => void cleanup().finally(() => process.exit(130)));
process.once('SIGTERM', () => void cleanup().finally(() => process.exit(143)));

function databaseConfiguration() {
  if (process.argv.includes('--sqlite-smoke') || process.env.FULLSTACK_SQLITE_SMOKE === 'true') {
    const sqlitePath = join(runtimeDir, '.fullstack-smoke.db').replaceAll('\\', '/');
    return { url: `sqlite+aiosqlite:///${sqlitePath}`, usesCompose: false };
  }
  if (process.env.FULLSTACK_DATABASE_URL) {
    const acknowledgement = 'I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE';
    if (process.env.FULLSTACK_DATABASE_DISPOSABLE_ACK !== acknowledgement) {
      throw new Error('Set FULLSTACK_DATABASE_DISPOSABLE_ACK for the isolated database.');
    }
    let databaseName = '';
    try {
      const parsed = new URL(process.env.FULLSTACK_DATABASE_URL);
      databaseName = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).at(-1) ?? '');
    } catch {
      throw new Error('FULLSTACK_DATABASE_URL must be a valid PostgreSQL URL.');
    }
    if (databaseName.toLowerCase() !== 'wbs_fullstack') {
      throw new Error('FULLSTACK_DATABASE_URL must name a wbs_fullstack database.');
    }
    return { url: process.env.FULLSTACK_DATABASE_URL, usesCompose: false };
  }
  const docker = spawnSync('docker', ['--version'], { stdio: 'ignore' });
  if (docker.status !== 0) {
    throw new Error(
      'Docker is required for PostgreSQL tests. Use test:e2e:fullstack:smoke only for a local SQLite smoke run.',
    );
  }
  const port = process.env.FULLSTACK_POSTGRES_PORT ?? '55432';
  return {
    url: `postgresql+asyncpg://wbs_fullstack:${encodeURIComponent(postgresPassword)}@127.0.0.1:${port}/wbs_fullstack`,
    usesCompose: true,
  };
}

let exitCode = 1;
try {
  await assertPortAvailable(apiPort, 'FastAPI');
  await assertPortAvailable(uiPort, 'Vite');
  const database = databaseConfiguration();
  mkdirSync(runtimeDir, { recursive: true });
  if (database.usesCompose) {
    composeStarted = true;
    run(
      'docker',
      [
        'compose', '-p', `wbsfullstack${runId}`, '-f', 'docker-compose.fullstack.yml',
        'up', '-d', '--wait', 'postgres-fullstack',
      ],
      {
        cwd: backendDir,
        env: { ...process.env, FULLSTACK_POSTGRES_PASSWORD: postgresPassword },
      },
    );
  }

  const environment = {
    ...process.env,
    APP_ENV: 'test',
    AUTH_MODE: 'local',
    AUTH_JWT_SECRET: randomBytes(48).toString('base64url'),
    AUTH_AUDIT_SECRET: randomBytes(48).toString('base64url'),
    AUTH_ACCESS_TOKEN_SECONDS_OVERRIDE: '5',
    AUTH_LOGIN_SUBJECT_LIMIT: '3',
    AUTH_LOGIN_IP_LIMIT: '100',
    AUTH_LOGIN_WINDOW_MINUTES: '1',
    DATABASE_URL: database.url,
    DIRECT_DATABASE_URL: database.url,
    DATABASE_USE_NULL_POOL: 'true',
    AUTO_CREATE_TABLES: 'false',
    BOOTSTRAP_DEVELOPMENT_DATA: 'false',
    TASKS_EAGER: 'true',
    DOCUMENT_WORKFLOW_RESUME_ENABLED: documentWorkflows ? 'true' : 'false',
    DOCUMENT_UPLOAD_REUSE_ENABLED: documentWorkflows ? 'true' : 'false',
    ...(documentWorkflows ? { STORAGE_BACKEND: 'local', DOCUMENT_INGESTION_ENABLED: 'false', DOCUMENT_INGESTION_LOCAL_DEVELOPMENT: 'false' } : {}),
    UPLOAD_ROOT: uploadRoot,
    CORS_ORIGINS: uiOrigin,
    PUBLIC_UI_URL: uiOrigin,
    PASSWORD_RECOVERY_ENABLED: 'true',
    TENANT_INVITATIONS_ENABLED: 'true',
    EMAIL_PROVIDER: 'test',
    EMAIL_FROM: 'no-reply@example.com',
    AUTH_COOKIE_SECURE: 'false',
    FULLSTACK_RUN_ID: runId,
    FULLSTACK_SEED_GUARD: runId,
    FULLSTACK_TEST_PASSWORD: `Fs!${randomBytes(20).toString('base64url')}9a`,
    FULLSTACK_RESET_TOKEN: randomBytes(32).toString('base64url'),
    FULLSTACK_EXPIRED_RESET_TOKEN: randomBytes(32).toString('base64url'),
    FULLSTACK_INVITATION_TOKEN: randomBytes(32).toString('base64url'),
    FULLSTACK_STATE_PATH: statePath,
    FULLSTACK_ARTIFACT_DIR: artifactDir,
    FULLSTACK_API_URL: `${apiOrigin}/api/v1`,
    FULLSTACK_UI_URL: uiOrigin,
    VITE_API_URL: `${apiOrigin}/api/v1`,
    VITE_PASSWORD_RECOVERY_ENABLED: 'true',
  };

  console.log('[fullstack] Applying migrations to the isolated database');
  run(pythonCommand, ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: backendDir,
    env: environment,
  });
  run(pythonCommand, ['-m', 'alembic', 'check'], { cwd: backendDir, env: environment });
  console.log('[fullstack] Provisioning deterministic test identities');
  run(pythonCommand, ['-m', 'app.fullstack_seed'], { cwd: backendDir, env: environment });
  if (!existsSync(statePath)) throw new Error('Full-stack seed did not produce its state manifest.');
  JSON.parse(readFileSync(statePath, 'utf8'));

  // Keep the test dependency cache independent of a running developer Vite server.
  const testViteConfig = join(runtimeDir, 'vite.config.mts');
  writeFileSync(testViteConfig,
    `import config from ${JSON.stringify(pathToFileURL(join(uiDir, 'vite.config.ts')).href)};\n`
    + `export default { ...config, cacheDir: ${JSON.stringify(join(runtimeDir, 'vite-cache'))} };\n`);

  start(
    pythonCommand,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)],
    backendDir,
    environment,
  );
  start(
    process.execPath,
    [
      viteEntry,
      '--config',
      testViteConfig,
      '--configLoader',
      'runner',
      '--mode',
      'fullstack',
      '--host',
      '127.0.0.1',
      '--port',
      String(uiPort),
      '--strictPort',
    ],
    uiDir,
    environment,
  );
  await waitFor(`${apiOrigin}/api/v1/health/ready`, 'FastAPI');
  await waitFor(uiOrigin, 'Vite');
  console.log('[fullstack] Running live Playwright suite');
  run(
    process.execPath,
    [playwrightEntry, 'test', '--config', 'playwright.fullstack.config.ts',
      ...(documentWorkflows ? ['document-workflows.spec.ts'] : [])],
    { cwd: uiDir, env: environment },
  );
  exitCode = 0;
} catch (error) {
  console.error(`[fullstack] ${error instanceof Error ? error.message : String(error)}`);
} finally {
  if (exitCode !== 0 && process.env.FULLSTACK_PRESERVE_FAILURE_ARTIFACTS === 'true') {
    preserveSanitizedArtifacts(artifactDir, preservedArtifactDir);
  }
  await cleanup();
}
process.exitCode = exitCode;
