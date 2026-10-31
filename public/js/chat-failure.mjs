/* Failures are message state, not replacement answer text. */
export function applyChatFailure(message, error, { stopped = false, elapsed = 0 } = {}) {
  message.pending = false;
  message.meta = { ...message.meta, ms: elapsed };
  if (stopped || error?.name === 'AbortError') {
    message.meta.stopped = true;
    if (!message.content) message.content = '_stopped_';
    return;
  }
  message.error = true;
  message.errorMessage = error?.message || String(error);
  message.meta.incomplete = true;
}
