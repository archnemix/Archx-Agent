'use strict';

const { getProviderAdapter, listProviderAdapters } = require('./providers/index.js');
const { ProxyError } = require('./providers/proxy-error.js');
const { normalizeBaseUrl } = require('./util.js');

function adapterFor(providerOrId) {
  const id = typeof providerOrId === 'string' ? providerOrId : providerOrId?.adapter;
  return getProviderAdapter(id || 'openai-compatible');
}

async function listModels(opts = {}) {
  return adapterFor(opts).listModels(opts);
}

async function chatCompletion(opts, cb = {}) {
  return adapterFor(opts).chatCompletion(opts, cb);
}

async function generateImage(opts = {}) {
  const ad = adapterFor(opts);
  if (typeof ad.generateImage !== 'function') throw new ProxyError('This provider adapter does not support image generation.', 501);
  return ad.generateImage(opts);
}

async function speech(opts = {}) {
  const ad = adapterFor(opts);
  if (typeof ad.speech !== 'function') throw new ProxyError('This provider adapter does not support text-to-speech.', 501);
  return ad.speech(opts);
}

async function transcribe(opts = {}) {
  const ad = adapterFor(opts);
  if (typeof ad.transcribe !== 'function') throw new ProxyError('This provider adapter does not support transcription.', 501);
  return ad.transcribe(opts);
}

module.exports = { listModels, chatCompletion, generateImage, speech, transcribe, ProxyError, normalizeBaseUrl, listProviderAdapters };
