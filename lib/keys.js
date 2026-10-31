'use strict';

/*
 * API-key encryption at rest.
 *
 * The wrap key is NEVER stored. It is re-derived on every launch from stable
 * machine identity (the parts that survive CPU/RAM/GPU swaps):
 *   - OS machine id:  /etc/machine-id (Linux)
 *                     HKLM\...\Cryptography\MachineGuid (Windows)
 *                     IOPlatformUUID (macOS)
 *   - plus platform, kernel release, arch, home dir, username
 * and stretched with scrypt. Keys are AES-256-GCM encrypted in the data area
 * and only decrypted in RAM while a request is in flight.
 *
 * Honest threat model: this stops casual theft / disk scraping / data-area
 * copies from yielding plaintext keys. A determined local malware that can
 * also read this package's source could re-derive the same key — for real
 * protection use a hardware-backed store; this is defence-in-depth.
 * If the fingerprint ever changes (OS reinstall), decryption fails gracefully
 * and the UI asks for the key again instead of crashing.
 */

const crypto = require('crypto');
const os = require('os');
const fs = require('fs');
const { execSync } = require('child_process');

function machineId() {
  const p = process.platform;
  try {
    if (p === 'linux') {
      for (const f of ['/etc/machine-id', '/var/lib/dbus/machine-id']) {
        if (fs.existsSync(f)) {
          const v = fs.readFileSync(f, 'utf8').trim();
          if (v) return v;
        }
      }
    }
    if (p === 'win32') {
      const out = execSync('reg query "HKLM\\SOFTWARE\\Microsoft\\Cryptography" /v MachineGuid', {
        encoding: 'utf8',
        windowsHide: true,
        timeout: 5000,
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      const m = /MachineGuid\s+REG_SZ\s+(\S+)/.exec(out);
      if (m) return m[1];
    }
    if (p === 'darwin') {
      const out = execSync('ioreg -rd1 -c IOPlatformExpertDevice', {
        encoding: 'utf8',
        timeout: 5000,
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      const m = /"IOPlatformUUID"\s*=\s*"([^"]+)"/.exec(out);
      if (m) return m[1];
    }
  } catch {
    /* fall through to the weaker-but-stable subset */
  }
  return null;
}

function fingerprint(override) {
  if (override) return override;
  let user = '';
  try {
    user = os.userInfo().username;
  } catch { /* ignore */ }
  return [
    process.platform,
    os.release(),
    os.arch(),
    os.homedir(),
    user,
    machineId() || 'no-machine-id',
  ].join('|');
}

let cached = null;
let cachedLog = null;

/** Detailed-log key: derived only in RAM from machine-bound identity plus a
 * separate domain separator. Nothing for this key is persisted to disk. */
function detailedLogKey() {
  if (cachedLog) return cachedLog;
  const material = crypto
    .createHash('sha256')
    .update('archx-agent:detailed-logs:v1|')
    .update(machineId() || 'no-machine-id')
    .update('|')
    .update(fingerprint())
    .digest();
  cachedLog = crypto.scryptSync(material, 'archx-agent-logwrap-v1', 32);
  return cachedLog;
}

function wrapKey(fpOverride) {
  if (cached && !fpOverride) return cached;
  const k = crypto.scryptSync(fingerprint(fpOverride), 'archx-agent-keywrap-v1', 32);
  if (!fpOverride) cached = k;
  return k;
}

function encrypt(plaintext, fpOverride) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', wrapKey(fpOverride), iv);
  const ct = Buffer.concat([c.update(String(plaintext), 'utf8'), c.final()]);
  return {
    v: 1,
    alg: 'aes-256-gcm',
    iv: iv.toString('base64'),
    tag: c.getAuthTag().toString('base64'),
    ct: ct.toString('base64'),
  };
}

function decrypt(cipher, fpOverride) {
  if (!cipher || cipher.v !== 1 || cipher.alg !== 'aes-256-gcm') {
    throw new Error('Unsupported key cipher.');
  }
  const d = crypto.createDecipheriv('aes-256-gcm', wrapKey(fpOverride), Buffer.from(cipher.iv, 'base64'));
  d.setAuthTag(Buffer.from(cipher.tag, 'base64'));
  return Buffer.concat([d.update(Buffer.from(cipher.ct, 'base64')), d.final()]).toString('utf8');
}

function encryptDetailed(value) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', detailedLogKey(), iv);
  const plaintext = typeof value === 'string' ? value : JSON.stringify(value);
  const ct = Buffer.concat([c.update(plaintext, 'utf8'), c.final()]);
  return { v: 1, alg: 'aes-256-gcm', mode: 'detailed', iv: iv.toString('base64'), tag: c.getAuthTag().toString('base64'), ct: ct.toString('base64') };
}

function decryptDetailed(cipher) {
  if (!cipher || cipher.v !== 1 || cipher.alg !== 'aes-256-gcm' || cipher.mode !== 'detailed') {
    throw new Error('Unsupported detailed log cipher.');
  }
  const d = crypto.createDecipheriv('aes-256-gcm', detailedLogKey(), Buffer.from(cipher.iv, 'base64'));
  d.setAuthTag(Buffer.from(cipher.tag, 'base64'));
  return Buffer.concat([d.update(Buffer.from(cipher.ct, 'base64')), d.final()]).toString('utf8');
}

module.exports = { encrypt, decrypt, encryptDetailed, decryptDetailed, fingerprint, machineId };
