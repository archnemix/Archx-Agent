/*
 * A stand-in LLM provider.
 *
 * The app talks to real endpoints over three different wire protocols.  Tests
 * must never touch the internet, so this server speaks all three (OpenAI,
 * Anthropic, Gemini) and lets a test pick what the next answer looks like.
 *
 *   POST /control/scenario  { mode, chunks, delayMs, failFirst }
 *   POST /control/reset
 *
 * Mounted paths:
 *   /v1/*            OpenAI-compatible (chat, models)
 *   /anthropic/v1/*  Anthropic Messages API
 *   /gemini/v1beta/* Google Generative Language API
 */
import http from 'node:http';

const SCENARIO_DEFAULT = {
  // "ok" | "fail" | "flaky" (fails once, then succeeds) | "slow"
  mode: 'ok',
  chunks: ['Hello ', 'from ', 'the ', 'mock ', 'provider.'],
  delayMs: 12,
  failStatus: 429,
};

let scenario = { ...SCENARIO_DEFAULT };
let flakyUsed = false;

const json = (res, status, body) => {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(payload),
  });
  res.end(payload);
};

const sseOpen = (res) => {
  res.writeHead(200, {
    'content-type': 'text/event-stream',
    'cache-control': 'no-cache',
    connection: 'keep-alive',
  });
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readBody(req) {
  const parts = [];
  for await (const part of req) parts.push(part);
  if (!parts.length) return {};
  try {
    return JSON.parse(Buffer.concat(parts).toString('utf8'));
  } catch {
    return {};
  }
}

/** Should this request fail on purpose? Consumes the "flaky" budget once. */
function takeFailure() {
  if (scenario.mode === 'fail') return true;
  if (scenario.mode === 'flaky' && !flakyUsed) {
    flakyUsed = true;
    return true;
  }
  return false;
}

async function openAiChat(req, res) {
  const body = await readBody(req);
  if (takeFailure()) {
    return json(res, scenario.failStatus, {
      error: { message: 'mock upstream failure', type: 'rate_limit_error' },
    });
  }
  const wantsReasoning = /reason/.test(JSON.stringify(body.messages || []));

  if (!body.stream) {
    return json(res, 200, {
      id: 'cmpl-mock',
      object: 'chat.completion',
      model: body.model,
      choices: [
        {
          index: 0,
          message: {
            role: 'assistant',
            content: scenario.chunks.join(''),
            reasoning_content: wantsReasoning ? 'I checked the request first.' : undefined,
          },
          finish_reason: 'stop',
        },
      ],
      usage: { prompt_tokens: 9, completion_tokens: 7, total_tokens: 16 },
    });
  }

  sseOpen(res);
  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
  send({ choices: [{ index: 0, delta: { role: 'assistant' } }] });
  if (wantsReasoning) {
    for (const piece of ['Thinking', ' about', ' the', ' request.']) {
      send({ choices: [{ index: 0, delta: { reasoning_content: piece } }] });
      await sleep(scenario.delayMs);
    }
  }
  for (const piece of scenario.chunks) {
    send({ choices: [{ index: 0, delta: { content: piece } }] });
    await sleep(scenario.delayMs);
  }
  send({ choices: [{ index: 0, delta: {}, finish_reason: 'stop' }], usage: { total_tokens: 16 } });
  res.write('data: [DONE]\n\n');
  res.end();
}

async function anthropicMessages(req, res) {
  const body = await readBody(req);
  if (takeFailure()) {
    return json(res, scenario.failStatus, {
      type: 'error',
      error: { type: 'rate_limit_error', message: 'mock upstream failure' },
    });
  }
  const text = scenario.chunks.join('');

  if (!body.stream) {
    return json(res, 200, {
      id: 'msg_mock',
      type: 'message',
      role: 'assistant',
      model: body.model,
      content: [{ type: 'text', text }],
      stop_reason: 'end_turn',
      usage: { input_tokens: 9, output_tokens: 7 },
    });
  }

  sseOpen(res);
  const send = (type, data) => res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
  send('message_start', {
    type: 'message_start',
    message: { id: 'msg_mock', role: 'assistant', model: body.model, content: [] },
  });
  send('content_block_start', { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } });
  for (const piece of scenario.chunks) {
    send('content_block_delta', {
      type: 'content_block_delta',
      index: 0,
      delta: { type: 'text_delta', text: piece },
    });
    await sleep(scenario.delayMs);
  }
  send('content_block_stop', { type: 'content_block_stop', index: 0 });
  send('message_stop', { type: 'message_stop' });
  res.end();
}

async function geminiContent(req, res, model, stream) {
  if (takeFailure()) {
    return json(res, scenario.failStatus, {
      error: { code: scenario.failStatus, message: 'mock upstream failure', status: 'RESOURCE_EXHAUSTED' },
    });
  }
  const text = scenario.chunks.join('');

  if (!stream) {
    return json(res, 200, {
      candidates: [{ content: { role: 'model', parts: [{ text }] }, finishReason: 'STOP' }],
      usageMetadata: { promptTokenCount: 9, candidatesTokenCount: 7, totalTokenCount: 16 },
    });
  }

  sseOpen(res);
  for (const piece of scenario.chunks) {
    res.write(`data: ${JSON.stringify({ candidates: [{ content: { role: 'model', parts: [{ text: piece }] } }] })}\n\n`);
    await sleep(scenario.delayMs);
  }
  res.write(`data: ${JSON.stringify({ candidates: [{ finishReason: 'STOP' }], usageMetadata: { totalTokenCount: 16 } })}\n\n`);
  res.end();
}

const MODEL_LIST_OPENAI = [
  { id: 'mock-chat', object: 'model', created: 1, owned_by: 'mock' },
  { id: 'mock-reasoner', object: 'model', created: 1, owned_by: 'mock' },
  { id: 'mock-broken', object: 'model', created: 1, owned_by: 'mock' },
];

const MODEL_LIST_GEMINI = {
  models: [
    {
      name: 'models/mock-gemini',
      displayName: 'Mock Gemini',
      supportedGenerationMethods: ['generateContent', 'countTokens'],
    },
    {
      name: 'models/mock-embedding',
      displayName: 'Mock Embedding',
      supportedGenerationMethods: ['embedContent'],
    },
  ],
};

export function createMockUpstream() {
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://mock');
    const path = url.pathname;

    if (path === '/control/scenario' && req.method === 'POST') {
      scenario = { ...SCENARIO_DEFAULT, ...(await readBody(req)) };
      flakyUsed = false;
      return json(res, 200, { ok: true, scenario });
    }
    if (path === '/control/reset' && req.method === 'POST') {
      scenario = { ...SCENARIO_DEFAULT };
      flakyUsed = false;
      return json(res, 200, { ok: true });
    }
    if (path === '/control/echo' && req.method === 'POST') {
      // Lets an API test inspect exactly what the app forwarded upstream.
      const body = await readBody(req);
      scenario = { ...SCENARIO_DEFAULT, mode: 'ok', chunks: [JSON.stringify(body)] };
      return json(res, 200, { ok: true });
    }

    // ---- OpenAI-compatible -------------------------------------------------
    if (path === '/v1/models') return json(res, 200, { object: 'list', data: MODEL_LIST_OPENAI });
    if (path === '/v1/chat/completions' && req.method === 'POST') return openAiChat(req, res);

    // ---- Anthropic ---------------------------------------------------------
    if (path === '/anthropic/v1/models') {
      return json(res, 200, { data: [{ id: 'mock-claude', type: 'model' }], has_more: false });
    }
    if (path === '/anthropic/v1/messages' && req.method === 'POST') return anthropicMessages(req, res);

    // ---- Gemini ------------------------------------------------------------
    if (path === '/gemini/v1beta/models') return json(res, 200, MODEL_LIST_GEMINI);
    const gem = path.match(/^\/gemini\/v1beta\/models\/([^:]+):(streamGenerateContent|generateContent)$/);
    if (gem) return geminiContent(req, res, gem[1], gem[2] === 'streamGenerateContent');

    json(res, 404, { error: { message: `mock upstream has no route ${req.method} ${path}` } });
  });

  return {
    server,
    listen() {
      return new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => resolve(server.address().port));
      });
    },
    close() {
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

// `node tests/mock-upstream/server.mjs` runs it standalone (handy for poking
// at the UI by hand without spending real provider credits).
if (import.meta.url === `file://${process.argv[1]}`) {
  const mock = createMockUpstream();
  const port = await mock.listen();
  console.log(`mock upstream listening on http://127.0.0.1:${port}`);
}
