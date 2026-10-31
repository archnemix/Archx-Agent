'use strict';

/*
 * Where Archx Agent keeps its things.
 *
 *  - pointer config (fixed, per-OS):  tells the app WHERE the data area is
 *      win   %APPDATA%\archx-agent\config.json
 *      mac   ~/Library/Application Support/archx-agent/config.json
 *      linux $XDG_CONFIG_HOME/archx-agent/config.json  (fallback ~/.config)
 *
 *  - data area (user-chosen): archx.db + media/
 */

const os = require('os');
const path = require('path');
const fs = require('fs');

function platformDirs() {
  const p = process.platform;
  if (p === 'win32') {
    const base = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
    return {
      config: path.join(base, 'archx-agent'),
      data: path.join(base, 'archx-agent', 'data'),
    };
  }
  if (p === 'darwin') {
    const base = path.join(os.homedir(), 'Library', 'Application Support', 'archx-agent');
    return { config: base, data: path.join(base, 'data') };
  }
  const cfgBase = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config');
  const dataBase = process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share');
  return {
    config: path.join(cfgBase, 'archx-agent'),
    data: path.join(dataBase, 'archx-agent'),
  };
}

const configPath = () => path.join(platformDirs().config, 'config.json');

/**
 * The manifest lives in a FIXED, non-movable location next to the pointer
 * config — it is the map of the world, so it must survive every data-area
 * migration untouched and always be findable at exactly one path.
 */
const manifestPath = () => path.join(platformDirs().config, 'manifest.json');

/** @returns {{dataDir: string|null, chosenAt?: string}|null} */
function readPointer() {
  try {
    const j = JSON.parse(fs.readFileSync(configPath(), 'utf8'));
    if (j && (typeof j.dataDir === 'string' || j.dataDir === null)) return j;
    return null;
  } catch {
    return null;
  }
}

function writePointer(dataDir) {
  const p = configPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = p + '.tmp';
  fs.writeFileSync(
    tmp,
    JSON.stringify({ version: 1, dataDir, chosenAt: new Date().toISOString() }, null, 2)
  );
  fs.renameSync(tmp, p);
}

module.exports = { platformDirs, configPath, manifestPath, readPointer, writePointer };
