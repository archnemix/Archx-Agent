/*
 * Read a streamed /api/chat response the way the browser does.
 *
 * The front-end parses `data:` lines and accumulates `choices[0].delta.content`.
 * Reproducing that here keeps the API tests honest: they verify the bytes the
 * UI would actually receive, not just the final JSON.
 */
export async function streamChat(baseUrl, body) {
  const t0 = Date.now();
  const res = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...body, stream: true }),
  });

  const events = [];
  let content = '';
  let reasoning = '';
  let firstDeltaMs = null;
  let meta = null;
  let errorEvent = null;

  if (!res.ok && !(res.headers.get('content-type') || '').includes('text/event-stream')) {
    const text = await res.text();
    return { status: res.status, content, reasoning, events, meta, errorEvent: null, error: text, firstDeltaMs, ms: Date.now() - t0 };
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      let event;
      try {
        event = JSON.parse(payload);
      } catch {
        continue;
      }
      events.push(event);
      if (event.error) {
        errorEvent = event.error;
        continue;
      }
      if (event.object === 'archx.meta' || event.object === 'archx.profile') {
        meta = { ...(meta || {}), ...event };
        continue;
      }
      const delta = event.choices && event.choices[0] && event.choices[0].delta;
      if (!delta) continue;
      if (typeof delta.content === 'string' && delta.content) {
        if (firstDeltaMs === null) firstDeltaMs = Date.now() - t0;
        content += delta.content;
      }
      if (typeof delta.reasoning_content === 'string') {
        if (firstDeltaMs === null) firstDeltaMs = Date.now() - t0;
        reasoning += delta.reasoning_content;
      }
    }
  }

  // The final frame frequently arrives without a trailing newline; parse it
  // rather than dropping the last (often most important) event.
  const tail = buffer.trim();
  if (tail.startsWith('data:')) {
    const payload = tail.slice(5).trim();
    if (payload && payload !== '[DONE]') {
      try {
        const event = JSON.parse(payload);
        events.push(event);
        if (event.error) errorEvent = event.error;
        else if (event.object === 'archx.meta' || event.object === 'archx.profile') meta = { ...(meta || {}), ...event };
        else {
          const delta = event.choices && event.choices[0] && event.choices[0].delta;
          if (delta && typeof delta.content === 'string') content += delta.content;
        }
      } catch {
        /* truncated tail — ignore */
      }
    }
  }

  return { status: res.status, content, reasoning, events, meta, errorEvent, firstDeltaMs, ms: Date.now() - t0 };
}

/** Non-streaming call, used where speed matters more than timing. */
export async function plainChat(baseUrl, body) {
  const res = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...body, stream: false }),
  });
  const json = await res.json().catch(() => null);
  return { status: res.status, json };
}
