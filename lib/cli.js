'use strict';

const path = require('path');
const readline = require('readline');
const { c, LOGO, openBrowser } = require('./util.js');
const { platformDirs, readPointer, writePointer } = require('./paths.js');
const pkg = require('../package.json');

const HELP = `
${c.bold('archx-agent')} — local web UI for any OpenAI-compatible LLM endpoint,
with a data area you choose yourself (chats, keys, models, settings).

${c.bold('Usage')}
  archx-agent webui [options]        Start the local web UI
  archx-agent help                   Show this help
  archx-agent version                Show the installed version

${c.bold('Options')}
  -p, --port <port>        Port to bind             (default: 4173, auto-increments if busy)
  -H, --host <host>        Host to bind             (default: 127.0.0.1 — localhost only)
      --no-open            Do not auto-open the browser
      --data-dir <path>    Use / create this data area (chats, keys, models, settings)
      --no-store           Run memory-only (nothing persisted, like v1.0)
      --choose-storage     Re-run the first-start storage chooser even if already configured
      --base-url <url>     Set the endpoint           (or env ARCHX_BASE_URL / OPENAI_BASE_URL)
      --key <key>          Set the API key            (or env ARCHX_API_KEY / OPENAI_API_KEY)
      --model <id>         Preferred model id         (or env ARCHX_MODEL)
  -h, --help               Show this help

${c.bold('Examples')}
  archx-agent webui
  archx-agent webui --port 8080
  archx-agent webui --data-dir D:\\LLM\\archx-data
  archx-agent webui --base-url https://api.groq.com/openai/v1 --key gsk_...

${c.bold('Storage')}
  On first start you are asked where chats, API keys, model lists and settings
  should live. Changing the area later (Settings → Storage in the UI, or
  --data-dir) copies everything to the new place first, verifies the copy,
  switches the default, and only then removes the originals.
`;

let sharedRl = null;
let stdinEof = false;
const lineQueue = [];
let lineWaiter = null;

function ensureRl() {
  if (sharedRl) return;
  sharedRl = readline.createInterface({ input: process.stdin, output: process.stdout });
  // queue lines that arrive before a question is asked (readline itself drops them)
  sharedRl.on('line', (l) => {
    const t = (l || '').trim();
    if (lineWaiter) {
      const w = lineWaiter;
      lineWaiter = null;
      w(t);
    } else {
      lineQueue.push(t);
    }
  });
  sharedRl.on('close', () => {
    stdinEof = true;
    if (lineWaiter) {
      const w = lineWaiter;
      lineWaiter = null;
      w(null);
    }
  });
}

function ask(question) {
  ensureRl();
  process.stdout.write(question);
  if (lineQueue.length) {
    const v = lineQueue.shift();
    process.stdout.write(v + '\n'); // echo pre-buffered input for readability
    return Promise.resolve(v);
  }
  if (stdinEof) return Promise.resolve(null);
  return new Promise((resolve) => {
    lineWaiter = resolve;
  });
}
function closeAsk() {
  if (sharedRl) {
    sharedRl.close();
    sharedRl = null;
  }
  lineWaiter = null;
  lineQueue.length = 0;
}

async function chooseStorage(opts) {
  const dirs = platformDirs();
  if (opts.noStore) return null;
  if (opts.dataDir) return path.resolve(process.cwd(), opts.dataDir);
  const pointer = readPointer();
  if (pointer && !opts.chooseStorage) return pointer.dataDir;

  if (!process.stdin.isTTY) return dirs.data;

  console.log(c.cyan(LOGO));
  console.log(`  ${c.bold('Archx Agent')} ${c.dim('v' + pkg.version)} — first-start setup`);
  console.log('');
  console.log('  Where should your data live (SQLite database, API keys, settings and assets)?');
  console.log('');
  console.log(`    ${c.bold('1')}  Default location      ${c.dim(dirs.data)}`);
  console.log(`    ${c.bold('2')}  Custom folder…`);
  console.log(`    ${c.bold('3')}  This folder (opt-in)  ${c.dim(path.join(process.cwd(), '.archx-agent'))}`);
  console.log(`    ${c.bold('4')}  Nowhere (memory-only, everything gone on restart)`);
  console.log('');
  for (;;) {
    const a = await ask(`  Choose [1-4] ${c.dim('(default 1)')}: `);
    if (a === null) return dirs.data; // stdin closed → safe default
    const choice = a === '' ? '1' : a;
    if (choice === '1') return dirs.data;
    if (choice === '2') {
      const p = await ask('  Path to the data folder: ');
      if (p === null) return dirs.data;
      if (p) return path.resolve(process.cwd(), p);
      continue;
    }
    if (choice === '3') return path.join(process.cwd(), '.archx-agent');
    if (choice === '4') return null;
    console.log(c.red('  Please answer 1, 2, 3 or 4.'));
  }
}
function parseArgs(argv) {
  const opts = {
    command: null,
    port: parseInt(process.env.ARCHX_PORT || '', 10) || 4173,
    host: process.env.ARCHX_HOST || '127.0.0.1',
    open: true,
    dataDir: process.env.ARCHX_DATA_DIR || null,
    noStore: false,
    chooseStorage: false,
    baseUrl: process.env.ARCHX_BASE_URL || process.env.OPENAI_BASE_URL || null,
    apiKey: process.env.ARCHX_API_KEY || process.env.OPENAI_API_KEY || null,
    model: process.env.ARCHX_MODEL || null,
  };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      const v = argv[++i];
      if (v === undefined) throw new Error(`Missing value for ${a}`);
      return v;
    };
    switch (a) {
      case '-h':
      case '--help':
      case 'help':
        opts.command = 'help';
        break;
      case '-v':
      case '--version':
      case 'version':
        opts.command = 'version';
        break;
      case 'webui':
      case 'ui':
      case 'serve':
        opts.command = opts.command || 'webui';
        break;
      case '-p':
      case '--port':
        opts.port = parseInt(next(), 10);
        break;
      case '-H':
      case '--host':
        opts.host = next();
        break;
      case '--no-open':
        opts.open = false;
        break;
      case '--open':
        opts.open = true;
        break;
      case '--data-dir':
        opts.dataDir = next();
        break;
      case '--no-store':
        opts.noStore = true;
        break;
      case '--choose-storage':
        opts.chooseStorage = true;
        break;
      case '--base-url':
      case '--baseurl':
        opts.baseUrl = next();
        break;
      case '--key':
      case '--api-key':
        opts.apiKey = next();
        break;
      case '--model':
        opts.model = next();
        break;
      default:
        if (a.startsWith('-')) throw new Error(`Unknown option: ${a}`);
        positional.push(a);
    }
  }
  if (!opts.command) opts.command = positional[0] || null;
  if (!Number.isFinite(opts.port) || opts.port < 1 || opts.port > 65535) {
    throw new Error(`Invalid port: ${opts.port}`);
  }
  return opts;
}

async function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    console.error(c.red(`archx-agent: ${err.message}`));
    console.error('Run `archx-agent help` for usage.');
    process.exit(1);
  }

  if (opts.command === 'version') {
    console.log(pkg.version);
    return;
  }
  if (opts.command === 'help' || !opts.command) {
    console.log(opts.command ? HELP : LOGO + '\n' + HELP);
    return;
  }
  if (opts.command !== 'webui') {
    console.error(c.red(`archx-agent: unknown command "${opts.command}"`));
    console.log(HELP);
    process.exit(1);
  }

  // storage area first (interactive on first start); switching areas always
  // goes through the fail-safe migration: copy → verify → switch → delete old
  const prev = readPointer();
  const prevDir = prev ? prev.dataDir : null;
  let desired;
  try {
    desired = await chooseStorage(opts);
  } catch (err) {
    console.error(c.red(`archx-agent: storage setup failed — ${err.message}`));
    process.exit(1);
  } finally {
    closeAsk();
  }

  const { startServer } = require('./server.js');
  const { Store } = require('./store.js');
  const keys = require('./keys.js');
  const fs = require('fs');
  let store;
  try {
    if (prevDir && prevDir !== desired) {
      // existing area → new area: fail-safe migration (copy→verify→switch→delete)
      store = new Store(prevDir);
      const report = store.migrateTo(desired);
      const note =
        `  (${(report.copied || []).length} files copied & verified` +
        ((report.removedOld || []).length ? `, ${report.removedOld.length} originals removed)` : ')');
      console.log(c.green(`  ➜ data area: ${desired || 'memory-only'}`) + c.dim(note));
    } else {
      // first start, or unchanged area: load (and v1-migrate) in place
      store = new Store(desired);
      if (!prevDir) {
        writePointer(desired); // record the first-start choice (null = memory-only)
        if (desired) fs.mkdirSync(desired, { recursive: true });
        console.log(c.green(`  ➜ data area: ${desired || 'memory-only (nothing persisted)'}`));
      }
    }
  } catch (err) {
    console.error(c.red(`archx-agent: storage migration failed — ${err.message}`));
    console.error(c.red('The previous data area is untouched and stays the default.'));
    process.exit(1);
  } finally {
    closeAsk();
  }

  // CLI/env endpoint prefill becomes (or updates) a provider, key encrypted
  if (opts.baseUrl || opts.apiKey) {
    const provs = store.state.providers.providers;
    const cleanBase = opts.baseUrl ? opts.baseUrl.replace(/\/+$/, '') : null;
    let p = cleanBase ? provs.find((x) => x.baseUrl === cleanBase) : provs[0] || null;
    if (!p && cleanBase) {
      let nm = cleanBase;
      try {
        nm = new URL(cleanBase).host;
      } catch { /* keep raw */ }
      p = {
        id: 'p-' + require('crypto').randomBytes(4).toString('hex'),
        name: nm,
        baseUrl: cleanBase,
        keyCipher: null,
        models: { hidden: [], custom: [] },
        freeOnly: false,
      };
      provs.push(p);
    }
    if (p && opts.apiKey) p.keyCipher = keys.encrypt(opts.apiKey);
    if (p) store.state.providers.active.providerId = p.id;
    store.persist('providers');
  }
  if (opts.model) {
    store.state.providers.active.model = opts.model;
    store.persist('providers');
  }

  let started;
  try {
    started = await startServer({ ...opts, store });
  } catch (err) {
    console.error(c.red(`archx-agent: could not start the webui — ${err.message}`));
    process.exit(1);
  }

  const { url } = started;
  console.log(c.cyan(LOGO));
  console.log(`  ${c.bold('Archx Agent')} ${c.dim('· webui v' + pkg.version)}`);
  console.log('');
  console.log(`  ${c.green('➜')}  Local:    ${c.bold(c.cyan(url))}`);
  console.log(`  ${c.dim('➜  Bound:    ' + opts.host + ':' + started.port)}`);
  console.log(
    `  ${c.dim('➜  Data:     ' + (store.memoryOnly ? 'memory-only (nothing persisted)' : store.dir))}`
  );
  console.log(`  ${c.dim('➜  Keys:     AES-256-GCM, wrap key derived from this machine at launch')}`);
  console.log(`  ${c.dim('➜  Journal:  ' + (store.memoryOnly ? 'disabled (memory-only)' : store.dir + require('path').sep + 'archx.db'))}`);
  console.log('');
  console.log(`  ${c.dim('Change the data area any time in Settings → Storage.')}`);
  console.log(`  ${c.dim('Stop with Ctrl+C.')}`);
  console.log('');

  if (opts.open) openBrowser(url);

  const stop = () => {
    console.log(c.dim('\narchx-agent: shutting down.'));
    started.server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 500).unref();
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

module.exports = { main, parseArgs, chooseStorage };
