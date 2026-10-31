'use strict';

/**
 * Provider adapter registry.
 *
 * Each adapter owns the wire protocol for model discovery and chat. The server
 * never needs to know whether a provider is OpenAI-compatible, Anthropic-native,
 * Gemini-native, or another future protocol; it only selects the adapter by id.
 */

const adapters = new Map();

function registerProviderAdapter(id, adapter) {
  const name = String(id || '').trim().toLowerCase();
  if (!name) throw new Error('Provider adapter id is required.');
  if (!adapter || typeof adapter.listModels !== 'function' || typeof adapter.chatCompletion !== 'function') {
    throw new Error(`Provider adapter “${name}” must implement listModels() and chatCompletion().`);
  }
  adapters.set(name, Object.freeze({ id: name, ...adapter }));
  return adapters.get(name);
}

function getProviderAdapter(id = 'openai-compatible') {
  const name = String(id || 'openai-compatible').trim().toLowerCase() || 'openai-compatible';
  const adapter = adapters.get(name);
  if (!adapter) throw new Error(`Unknown provider adapter “${name}”.`);
  return adapter;
}

function listProviderAdapters() {
  return [...adapters.values()].map((adapter) => adapter.id);
}

/* Built-in adapters are registered on module load. Additional adapters can
   register themselves without changing server/proxy code. The order here is
   the order shown in the UI's adapter dropdown. */
registerProviderAdapter('openai-compatible', require('./openai-compatible.js'));
registerProviderAdapter('anthropic', require('./anthropic.js'));
registerProviderAdapter('gemini', require('./gemini.js'));
registerProviderAdapter('nvidia-nim', require('./nvidia-nim.js'));

module.exports = { getProviderAdapter, listProviderAdapters, registerProviderAdapter };
