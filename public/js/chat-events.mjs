/* Read the application SSE contract once. A missing final marker is not success. */
export async function readChatStream(body, cb = {}) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let out = '';
  let finished = false;
  function consume(frame) {
    const payload = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n').trim();
    if (!payload) return;
    if (payload === '[DONE]') { finished = true; return; }
    let event;
    try { event = JSON.parse(payload); }
    catch { throw new Error('The provider sent a malformed stream event.'); }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('Invalid stream event.');
    if (event.error) throw new Error(event.error.message || 'Provider stream error.');
    if (event.tool) { cb.onTool?.(event.tool); return; }
    if (typeof event.object === 'string' && event.object.startsWith('archx.')) {
      cb.onMeta?.(event); return;
    }
    const delta = event.choices?.[0]?.delta;
    if (!delta) return;
    if (typeof delta.content === 'string') { out += delta.content; cb.onDelta?.(delta.content); }
    const reasoning = delta.reasoning_content ?? delta.reasoning ?? delta.thinking;
    if (typeof reasoning === 'string' && reasoning) cb.onReasoning?.(reasoning);
  }
  function drain(atEnd = false) {
    buffer = buffer.replace(/\r\n/g, '\n');
    let cut;
    while (!finished && (cut = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, cut); buffer = buffer.slice(cut + 2); consume(frame);
    }
    if (atEnd && !finished && buffer.trim()) { consume(buffer); buffer = ''; }
  }
  try {
    while (!finished) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (buffer.length > 2 * 1024 * 1024) throw new Error('Stream event exceeds the size limit.');
      drain(done);
      if (done) break;
    }
    if (!finished) {
      const error = new Error('Completion is unconfirmed: the stream ended without its final marker. Partial output was kept; no retry was sent.');
      error.code = 'stream_incomplete';
      throw error;
    }
    return out;
  } finally {
    try { await reader.cancel(); } catch { /* An interrupted body may already be closed. */ }
    reader.releaseLock();
  }
}
