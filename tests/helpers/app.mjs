/*
 * Boot the real app in a throwaway data area.
 *
 * Each test file gets its own SQLite database and its own OS-assigned port,
 * so `node --test` can run files in parallel and nothing leaks between them.
 * The pointer config lives under XDG_CONFIG_HOME too — a test run must never
 * touch the developer's real chat history.
 */
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';

const APP_ROOT = path.resolve(import.meta.dirname, '..', '..');

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

async function waitForHealth(baseUrl, child, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = 'no answer yet';
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`app exited early with code ${child.exitCode}`);
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) return await res.json();
    } catch (error) {
      lastError = error.message;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`app did not become healthy in ${timeoutMs} ms (${lastError})`);
}

export async function startApp(extraEnv = {}) {
  const sandbox = await mkdtemp(path.join(tmpdir(), 'archx-test-'));
  const dataDir = path.join(sandbox, 'data');
  const configHome = path.join(sandbox, 'config');
  const port = await freePort();
  const logs = [];

  const child = spawn(process.execPath, ['bin/archx-agent.js', 'webui', '--no-open'], {
    cwd: APP_ROOT,
    env: {
      ...process.env,
      ARCHX_HOST: '127.0.0.1',
      ARCHX_PORT: String(port),
      ARCHX_DATA_DIR: dataDir,
      XDG_CONFIG_HOME: configHome,
      XDG_DATA_HOME: path.join(sandbox, 'share'),
      ARCHX_NO_BANNER: '1',
      ...extraEnv,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  child.stdout.on('data', (buf) => logs.push(buf.toString()));
  child.stderr.on('data', (buf) => logs.push(buf.toString()));

  const baseUrl = `http://127.0.0.1:${port}`;
  const health = await waitForHealth(baseUrl, child).catch(async (error) => {
    child.kill('SIGKILL');
    await rm(sandbox, { recursive: true, force: true });
    throw new Error(`${error.message}\n--- app log ---\n${logs.join('')}`);
  });

  return {
    baseUrl,
    dataDir,
    configHome,
    health,
    logs: () => logs.join(''),
    async stop() {
      child.kill('SIGTERM');
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          child.kill('SIGKILL');
          resolve();
        }, 4000);
        child.on('exit', () => {
          clearTimeout(timer);
          resolve();
        });
      });
      await rm(sandbox, { recursive: true, force: true });
    },
  };
}

/** Small fetch wrapper: keeps tests free of repeated boilerplate. */
export function client(baseUrl) {
  const call = async (method, route, body) => {
    const res = await fetch(baseUrl + route, {
      method,
      headers: body === undefined ? {} : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      /* non-JSON bodies are reported through .text below */
    }
    return { status: res.status, headers: res.headers, json, text };
  };

  return {
    get: (route) => call('GET', route),
    post: (route, body = {}) => call('POST', route, body),
    patch: (route, body = {}) => call('PATCH', route, body),
    del: (route) => call('DELETE', route),
    state: async () => (await call('GET', '/api/state')).json,
    /** Registers a provider pointed at the mock and pins a model as active. */
    async addProvider({ name = 'Mock Provider', baseUrl, adapter = 'openai-compatible', model }) {
      const created = await call('POST', '/api/providers', { name, baseUrl, adapter, apiKey: 'sk-mock-key' });
      if (created.status !== 200) throw new Error(`provider create failed: ${created.status} ${created.text}`);
      const id = created.json.provider.id;
      if (model) {
        const models = await call('POST', `/api/providers/${id}/models`);
        if (models.status !== 200) throw new Error(`model discovery failed: ${models.text}`);
        await call('PATCH', `/api/providers/${id}`, {
          models: { catalog: [model], catalogInitialized: true, selectionMode: 'checklist' },
        });
        await call('POST', '/api/active', { providerId: id, model });
      }
      return id;
    },
  };
}
