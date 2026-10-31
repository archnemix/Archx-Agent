'use strict';

/* Keep browser-only message fields in the existing metadata column, no schema reset. */
function serializeMessageMeta(message) {
  const meta = { ...(message.meta || {}) };
  if (Array.isArray(message.tools) || message.errorMessage) {
    meta._archxMessage = {
      tools: Array.isArray(message.tools) ? message.tools : [],
      errorMessage: typeof message.errorMessage === 'string' ? message.errorMessage : '',
    };
  }
  return meta;
}
function restoreMessageMeta(stored) {
  const { _archxMessage: extra, ...meta } = stored || {};
  return {
    meta,
    tools: Array.isArray(extra?.tools) ? extra.tools : [],
    errorMessage: typeof extra?.errorMessage === 'string' ? extra.errorMessage : '',
  };
}
module.exports = { serializeMessageMeta, restoreMessageMeta };
