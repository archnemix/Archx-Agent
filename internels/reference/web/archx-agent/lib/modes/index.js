'use strict';

const modes = new Map();

function registerMode(mode) {
  if (!mode || typeof mode.id !== 'string' || typeof mode.prepareRequest !== 'function') {
    throw new Error('A mode must define id and prepareRequest().');
  }
  if (modes.has(mode.id)) throw new Error(`Mode “${mode.id}” is already registered.`);
  modes.set(mode.id, Object.freeze({
    id: mode.id,
    name: mode.name || mode.id,
    description: mode.description || '',
    capabilities: mode.capabilities || {},
    prepareRequest: mode.prepareRequest,
  }));
  return modes.get(mode.id);
}

function getMode(id) {
  return modes.get(id) || null;
}

function listModes() {
  return [...modes.values()].map(({ prepareRequest, ...view }) => view);
}

registerMode(require('./simple-chat.js'));

module.exports = { registerMode, getMode, listModes };
