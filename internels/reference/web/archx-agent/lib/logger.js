'use strict';

const keys = require('./keys.js');

class Logger {
  constructor(store, modeProvider) {
    this.store = store || null;
    this.modeProvider = modeProvider || (() => 'simple');
  }

  setStore(store) { this.store = store || null; }
  setDir() {}
  mode() { return this.modeProvider() === 'detailed-encrypted' ? 'detailed-encrypted' : 'simple'; }

  log(entry, detail) {
    if (!this.store?.dir) return;
    try {
      const envelope = { ts: new Date().toISOString(), ...entry };
      if (this.mode() === 'detailed-encrypted') envelope.detail = detail === undefined ? envelope.detail : detail;
      this.store.appendLog(envelope, this.mode());
    } catch {}
  }

  wipe() { this.store?.clearLogs(); }
}

module.exports = { Logger };
