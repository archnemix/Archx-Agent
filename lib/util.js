'use strict';

/* Tiny terminal coloring + helpers (no deps). */

const isTTY = process.stdout.isTTY && !process.env.NO_COLOR;
const wrap = (code) => (s) => (isTTY ? `\x1b[${code}m${s}\x1b[0m` : String(s));

const c = {
  bold: wrap(1),
  dim: wrap(2),
  red: wrap(31),
  green: wrap(32),
  yellow: wrap(33),
  blue: wrap(34),
  magenta: wrap(35),
  cyan: wrap(36),
};

const LOGO = `
 ███  ████   ████ █   █ █   █    ███   ████ █████ █   █ █████
█   █ █   █ █     █   █  █ █    █   █ █     █     ██  █   █
█████ ████  █     █████   █     █████ █  ██ ████  █ █ █   █
█   █ █  █  █     █   █  █ █    █   █ █   █ █     █  ██   █
█   █ █   █  ████ █   █ █   █   █   █  ████ █████ █   █   █  `;

function openBrowser(url) {
  const { spawn } = require('child_process');
  const cmds = {
    darwin: ['open', [url]],
    win32: ['cmd', ['/c', 'start', '""', url]],
  };
  const [cmd, args] = cmds[process.platform] || ['xdg-open', [url]];
  try {
    const child = spawn(cmd, args, { stdio: 'ignore', detached: true });
    child.on('error', () => {});
    child.unref();
    return true;
  } catch {
    return false;
  }
}

/** Normalize a user-supplied OpenAI-compatible base URL. */
function normalizeBaseUrl(raw) {
  let base = String(raw || '').trim().replace(/\/+$/, '');
  if (!base) throw new Error('Base URL is required.');
  if (!/^https?:\/\//i.test(base)) base = 'https://' + base;
  let u;
  try {
    u = new URL(base);
  } catch {
    throw new Error(`"${raw}" is not a valid URL.`);
  }
  if (!u.pathname || u.pathname === '/') u.pathname = '/v1';
  else if (!/\/v\d+$/.test(u.pathname)) u.pathname = u.pathname + '/v1';
  return u.toString().replace(/\/+$/, '');
}

function maskKey(key) {
  if (!key) return '';
  const k = String(key);
  if (k.length <= 8) return k.slice(0, 2) + '••••';
  return k.slice(0, 4) + '••••••••' + k.slice(-4);
}

module.exports = { c, LOGO, openBrowser, normalizeBaseUrl, maskKey };
