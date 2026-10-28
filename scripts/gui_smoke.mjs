/* Load the shipped page in jsdom with a fake server and prove the modes render.
 *
 * Usage:
 *   npm install --prefix /tmp/domtest jsdom
 *   ARCHX_JSDOM_DIR=/tmp/domtest node scripts/gui_smoke.mjs
 *
 * It reads the assets straight out of the repository, so it tests what is committed. jsdom is
 * deliberately *not* a project dependency: the server has no runtime dependencies, and a
 * browser-side check is only worth running where someone has installed one.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/* jsdom is not a dependency of this project. Resolve it from here, or from the directory
 * named by ARCHX_JSDOM_DIR, which is where a throwaway `npm install jsdom` would land. */
const require = createRequire(import.meta.url);
let jsdom;
try {
  jsdom = require("jsdom");
} catch {
  const fallback = join(process.env.ARCHX_JSDOM_DIR || "/tmp/domtest", "noop.js");
  try {
    jsdom = createRequire(fallback)("jsdom");
  } catch {
    console.error("jsdom is not installed. Run: npm install --prefix /tmp/domtest jsdom");
    process.exit(2);
  }
}
const { JSDOM } = jsdom;

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "archx_agent", "interfaces", "gui", "assets");
const html = readFileSync(`${ROOT}/index.html`, "utf8");
const script = readFileSync(`${ROOT}/app.js`, "utf8");
const css = readFileSync(`${ROOT}/style.css`, "utf8");

const MODELS = [
  {
    id: "mdl_gemini", name: "flash", provider: "google", runtime: "gemini",
    ready: false, ready_reason: "runtime not ready: secret reference could not be resolved",
    capabilities: ["chat"], provider_id: null,
    gates: [
      { key: "consent_policy", label: "cloud routing allowed", ok: false, detail: "model.local_only is true" },
      { key: "provider", label: "endpoint is a registered provider", ok: false, detail: "register the provider" },
      { key: "privacy", label: "privacy terms confirmed", ok: false, detail: "register the provider first" },
      { key: "consent", label: "you recorded consent", ok: false, detail: "register the provider first" },
    ],
  },
];

const calls = [];
const routes = {
  "GET /api/status": {
    schema_version: 20, home: "/home/user/.archx-demo", memories: 3, tasks: 4,
    models_total: 1, models_usable: 0, approvals_pending: 0, schema: 20,
    research: { runs: 1 }, jobs: { queued: 0 }, version: "0.30.0",
  },
  "GET /api/models": MODELS,
  "GET /api/providers": [],
  "GET /api/sdks": [
    { key: "openai", label: "OpenAI", package: "openai", env_var: "OPENAI_API_KEY", installed: true },
    { key: "anthropic", label: "Anthropic", package: "anthropic", env_var: "ANTHROPIC_API_KEY", installed: false },
  ],
  // order matters: the lookup is a prefix match, so the session detail comes before the list
  "GET /api/code/sessions/cs_demo": {
    session: {
      id: "cs_demo", title: "demo", root: "/tmp/smoke", status: "open", open: true,
      task_id: "tk_demo", created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z",
      closed_at: null, note: null, metadata: {},
    },
    changes: [
      { id: "cc_1", path: "hello.py", action: "modify", added: 1, removed: 1, diff: "--- a/hello.py",
        artifact_id: "ar_1", created_at: "2026-10-28T10:01:00Z" },
    ],
    runs: [
      { id: "cr_1", command: "echo hi", status: "passed", exit_code: 0, duration_ms: 12,
        check_name: null, created_at: "2026-10-28T10:02:00Z" },
    ],
    stats: { changes: 1, added: 1, removed: 1, runs: 1, failed: 0 },
    task: null,
  },
  "GET /api/code/sessions": {
    sessions: [
      {
        id: "cs_demo", title: "demo", root: "/tmp/smoke", status: "open", open: true,
        task_id: "tk_demo", created_at: "2026-10-28T10:00:00Z",
        stats: { changes: 1, added: 1, removed: 1, runs: 1, failed: 0 },
      },
    ],
    roots: ["/tmp/smoke"],
    stats: { sessions: 1, open: 1, changes: 1, runs: 1, failed_runs: 0 },
  },
  "GET /api/experiments/xp_demo": {
    experiment: {
      id: "xp_demo", name: "sorting", hypothesis: "bigger n sorts more", command: "python bench.py {n}",
      root: "/tmp/smoke", status: "open", open: true, params: [{ name: "n", default: 100, description: "" }],
      param_names: ["n"], metrics_source: { kind: "stdout-json" },
      created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", metadata: {},
    },
    runs: [
      { id: "xr_1", experiment_id: "xp_demo", command: "python bench.py 100", status: "passed",
        params: { n: "100" }, exit_code: 0, duration_ms: 20, metrics: { sorted: 10000 },
        metrics_error: null, task_id: "tk_x", tool_run_id: null, artifact_id: null, seed: null,
        note: null, created_at: "2026-10-28T10:02:00Z" },
      { id: "xr_2", experiment_id: "xp_demo", command: "python bench.py 200", status: "failed",
        params: { n: "200" }, exit_code: 1, duration_ms: 30, metrics: {},
        metrics_error: "the last line of stdout is not valid JSON", task_id: "tk_x",
        tool_run_id: null, artifact_id: null, seed: null, note: null,
        created_at: "2026-10-28T10:03:00Z" },
    ],
    metric_names: ["sorted"],
    stats: { runs: 2, by_status: { passed: 1, failed: 1 }, with_metrics: 1, without_metrics: 1 },
  },
  "GET /api/experiments": {
    experiments: [
      {
        id: "xp_demo", name: "sorting", hypothesis: "bigger n sorts more", command: "python bench.py {n}",
        root: "/tmp/smoke", status: "open", open: true, params: [{ name: "n", default: 100, description: "" }],
        param_names: ["n"], metrics_source: { kind: "stdout-json" },
        created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", metadata: {},
        stats: { runs: 2, failed: 1 },
      },
    ],
    roots: ["/tmp/smoke"],
    stats: { experiments: 1, open: 1, runs: 2, failed_runs: 1, metrics: 1 },
  },
  "POST /api/experiments": {
    id: "xp_new", name: "smoke", hypothesis: null, command: "python bench.py {n}", root: "/tmp/smoke",
    status: "open", open: true, params: [{ name: "n", default: 100, description: "" }],
    param_names: ["n"], metrics_source: { kind: "none" },
    created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", metadata: {},
  },
  "GET /api/play/games/gm_demo/history": {
    id: "gm_demo", game_type: "tictactoe", status: "open", winner: null,
    moves: [
      { id: 1, game_id: "gm_demo", seq: 1, player: "X", action: "1", legal: true, reason: null,
        state_hash: "abc1234567890123", created_at: "2026-10-28T10:00:00Z" },
      { id: 2, game_id: "gm_demo", seq: 1, player: "O", action: "1", legal: false,
        reason: "square 1 is taken", state_hash: null, created_at: "2026-10-28T10:01:00Z" },
    ],
    legal: 1, refused_count: 1,
  },
  "GET /api/play/games/gm_demo": {
    id: "gm_demo", game_type: "tictactoe", status: "open", open: true, turn: "O",
    board: " X | 2 | 3\n---+---+---\n 4 | 5 | 6\n---+---+---\n 7 | 8 | 9",
    legal_moves: ["2", "3", "4", "5", "6", "7", "8", "9"],
    outcome: { over: false, winner: null, reason: "in progress" },
    moves: [
      { id: 1, game_id: "gm_demo", seq: 1, player: "X", action: "1", legal: true, reason: null,
        state_hash: "abc1234567890123", created_at: "2026-10-28T10:00:00Z" },
      { id: 2, game_id: "gm_demo", seq: 1, player: "O", action: "1", legal: false,
        reason: "square 1 is taken", state_hash: null, created_at: "2026-10-28T10:01:00Z" },
    ],
    move_count: 1, winner: null, seed: null, created_at: "2026-10-28T10:00:00Z",
  },
  "GET /api/play/games": {
    games: [
      { id: "gm_demo", game_type: "tictactoe", status: "open", open: true, move_count: 1,
        winner: null, seed: null, created_at: "2026-10-28T10:00:00Z" },
    ],
    stats: { games: 1, open: 1, finished: 0, moves: 2, refused_moves: 1, sims: 1 },
    games_available: ["connect4", "nim", "tictactoe"],
  },
  "POST /api/play/games": {
    id: "gm_new", game_type: "connect4", status: "open", open: true, turn: "R",
    board: ". . . . . . .",
    legal_moves: ["1", "2", "3", "4", "5", "6", "7"],
    outcome: { over: false, winner: null, reason: "in progress" },
    moves: [], move_count: 0, winner: null, seed: null, created_at: "2026-10-28T10:00:00Z",
  },
  "POST /api/play/sims": {
    id: "sim_new", kind: "life", width: 8, height: 4, steps: 2, seed: 1, density: 0.3,
    status: "completed", final_hash: "deadbeefdeadbeef", alive: 3, series: [4, 3, 3],
    rows: ["........", "..##....", "..#.....", "........"], task_id: null,
    created_at: "2026-10-28T10:00:00Z", completed_at: "2026-10-28T10:00:00Z", metadata: {},
  },
  "GET /api/play/sims/sim_demo": {
    id: "sim_demo", kind: "life", width: 8, height: 4, steps: 2, seed: 1, density: 0.3,
    status: "completed", final_hash: "deadbeefdeadbeef", alive: 3, series: [4, 3, 3],
    rows: ["........", "..##....", "..#.....", "........"], task_id: null,
    created_at: "2026-10-28T10:00:00Z", completed_at: "2026-10-28T10:00:00Z", metadata: {},
  },
  "GET /api/play/sims": {
    sims: [
      { id: "sim_demo", kind: "life", width: 8, height: 4, steps: 2, seed: 1, density: 0.3,
        status: "completed", final_hash: "deadbeefdeadbeef", alive: 3, series: [4, 3, 3],
        rows: [], task_id: null, created_at: "2026-10-28T10:00:00Z",
        completed_at: "2026-10-28T10:00:00Z", metadata: {} },
    ],
    stats: { games: 1, open: 1, finished: 0, moves: 2, refused_moves: 1, sims: 1 },
  },
  "GET /api/voice/assets/ma_demo": {
    id: "ma_demo", kind: "image", format: "png", path: "pixel.png",
    sha256: "aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666aaaa7777bbbb8888",
    bytes: 76, width: 12, height: 8, duration_ms: null, sample_rate: null, channels: null,
    bits_per_sample: null, name_claim: "jpg", name_mismatch: "the name says 'jpg' but the bytes are png",
    facts: { details: { bit_depth: 8 }, notes: [], hash_scope: "whole file" },
    task_id: null, created_at: "2026-10-28T10:00:00Z", metadata: {},
    transcripts: [],
    attempts: [
      { id: "va_1", asset_id: "ma_demo", action: "probe", status: "completed", reason: null,
        engine: "fs.probe", chars: null, task_id: null, created_at: "2026-10-28T10:00:00Z",
        metadata: {} },
    ],
    described: "png image, 12x8, 76 bytes",
  },
  "GET /api/voice/assets": {
    assets: [
      { id: "ma_demo", kind: "image", format: "png", path: "pixel.png",
        sha256: "aaaa1111", bytes: 76, width: 12, height: 8, duration_ms: null, sample_rate: null,
        channels: null, bits_per_sample: null, name_claim: "jpg",
        name_mismatch: "the name says 'jpg' but the bytes are png", facts: {}, task_id: null,
        created_at: "2026-10-28T10:00:00Z", metadata: {} },
    ],
    roots: ["/tmp/smoke"],
    stats: { assets: 1, images: 1, audio: 0, audio_ms: 0, mislabelled: 1, transcripts: 0,
             attempts: 1, refused: 0, can_transcribe: false, can_speak: false },
  },
  "POST /api/voice/probe": {
    id: "ma_new", kind: "audio", format: "wav", path: "tone.wav",
    sha256: "beef", bytes: 1644, width: null, height: null, duration_ms: 100, sample_rate: 8000,
    channels: 1, bits_per_sample: 16, name_claim: "wav", name_mismatch: null,
    facts: { details: {}, notes: [], hash_scope: "whole file" }, task_id: null,
    created_at: "2026-10-28T10:00:00Z", metadata: {}, transcripts: [], attempts: [],
    described: "wav audio, 100 ms, 8000 Hz 1 ch 16-bit, 1644 bytes",
  },
  // the mock matches routes by prefix, so the specific paths are listed before the collection
  "GET /api/datasets/ds_demo/records?limit=100": {
    dataset_id: "ds_demo",
    records: [
      { id: "dr_1", dataset_id: "ds_demo", seq: 0, path: "corpus/a.txt",
        sha256: "aaaa", bytes: 33, kind: "text", chars: 33, lines: 2, split: "train",
        status: "kept", reason: null, label: null, created_at: "2026-10-28T10:00:00Z",
        metadata: {} },
      { id: "dr_2", dataset_id: "ds_demo", seq: 1, path: "corpus/copy_a.txt",
        sha256: "aaaa", bytes: 33, kind: "text", chars: 33, lines: 2, split: null,
        status: "dropped",
        reason: "the same content is already in the dataset from an earlier path: corpus/a.txt",
        label: null, created_at: "2026-10-28T10:00:00Z", metadata: {} },
    ],
  },
  "GET /api/datasets/ds_demo": {
    id: "ds_demo", name: "corpus", source: '["corpus"]', status: "split", revision: null,
    license: "CC-BY-4.0", format: "jsonl", record_count: 3, dropped_count: 2, path: null,
    checksum: "bbccf9613487622568379a498326ca7a323b14dc0d5f2ee9a7908c51642f49a9",
    seed: "m35", splits: { by_split: { train: 2, val: 1 } }, task_id: null,
    created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", metadata: {},
    counts: { kept: 3, dropped: 2, by_split: { train: 2, val: 1 } },
    sources: ["corpus"], license_note: "declared by the user: CC-BY-4.0",
    transforms: [
      { id: 1, dataset_id: "ds_demo", seq: 1, kind: "scan", config: {}, records_in: 0,
        records_out: 5, report: {}, output_path: null, input_checksum: null,
        output_checksum: null, created_at: "2026-10-28T10:00:00Z" },
      { id: 2, dataset_id: "ds_demo", seq: 2, kind: "clean", config: {}, records_in: 5,
        records_out: 3, report: {}, output_path: null, input_checksum: null,
        output_checksum: null, created_at: "2026-10-28T10:01:00Z" },
    ],
  },
  "GET /api/datasets": {
    datasets: [
      { id: "ds_demo", name: "corpus", source: '["corpus"]', status: "split", revision: null,
        license: "CC-BY-4.0", format: "jsonl", record_count: 3, dropped_count: 2, path: null,
        checksum: null, seed: "m35", splits: {}, task_id: null,
        created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", metadata: {} },
    ],
    roots: ["/tmp/smoke"],
    stats: { datasets: 1, records: 5, kept: 3, dropped: 2, bytes_kept: 120, by_status: { split: 1 } },
  },
  "GET /api/conversations": [],
  "GET /api/tasks": [],
  "GET /api/tools": [],
  "GET /api/memory": [],
  "GET /api/jobs": { jobs: [], stats: {}, queue: [] },
  "GET /api/permissions": { grants: [], pending: [], capabilities: [] },
  "GET /api/research": [],
  "GET /api/learning/goals": [],
  "GET /api/search?q=": { results: [] },
  "POST /api/code/sessions": {
    id: "cs_new", title: "smoke", root: "/tmp/smoke", status: "open", open: true,
    task_id: "tk_new", created_at: "2026-10-28T10:00:00Z",
    stats: { changes: 0, added: 0, removed: 0, runs: 0, failed: 0 },
  },
  "POST /api/models": {
    id: "mdl_gemini", name: "flash", provider: "google", runtime: "gemini",
    ready: false, ready_reason: "runtime not ready: GEMINI_API_KEY is not set",
    capabilities: ["chat"], provider_id: null,
    gates: MODELS[0].gates,
  },
};

const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://127.0.0.1:8765/" });
const { window } = dom;

/* a fetch that answers from the table above and records what the page asked for */
window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, "");
  calls.push(`${method} ${path}`);
  const key = Object.keys(routes).find((route) => `${method} ${path}`.startsWith(route));
  if (!key) {
    return { ok: false, status: 404, json: async () => ({ ok: false, error: { message: "no route" } }) };
  }
  return {
    ok: true, status: 200,
    json: async () => ({ ok: true, data: routes[key] }),
    headers: new Map([["content-type", "application/json"]]),
  };
};
window.localStorage.setItem("archx_token", "smoke-token");
window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
window.scrollTo = () => {};

const errors = [];
window.addEventListener("error", (event) => errors.push(event.message));
window.console.error = (...args) => errors.push(args.join(" "));

window.eval(script);

const tick = () => new Promise((resolve) => setTimeout(resolve, 60));
await tick();
await tick();
await tick();

const doc = window.document;
const problems = [];

function assert(condition, message) {
  if (!condition) problems.push(message);
}

// the shell
assert(doc.querySelectorAll(".tab").length === 15, "expected fifteen mode tabs");
assert(doc.getElementById("view-code"), "the coding view is missing");
assert(doc.getElementById("view-experiments"), "the experiments view is missing");
assert(doc.getElementById("view-play"), "the play view is missing");
assert(doc.getElementById("view-voice"), "the voice view is missing");
assert(doc.getElementById("view-data"), "the datasets view is missing");
assert(doc.getElementById("view-chat"), "chat view is missing");

// every refresh button answers a click without throwing
for (const node of doc.querySelectorAll("[id$='-refresh']")) node.click();
await tick();
await tick();

// models: the ladder must render one row per gate, with the actions that are possible
doc.querySelector('[data-view="models"]').click();
await tick();
await tick();

const gates = doc.querySelectorAll(".rung");
assert(gates.length === 4, `expected four gate rows, saw ${gates.length}: ${[...doc.querySelectorAll(".rung-label")].map((n) => n.textContent).join(" | ")}`);
assert(doc.querySelectorAll(".rung-ok").length === 0, "no rung should look passed here");
const rungLabels = [...doc.querySelectorAll(".rung-label")].map((n) => n.textContent);
assert(rungLabels.includes("cloud routing allowed"), "the first rung must be labelled");
const buttons = [...doc.querySelectorAll(".rung .btn")].map((n) => n.textContent);
assert(buttons.includes("Allow cloud routing"), `no consent-policy control: ${JSON.stringify(buttons)}`);
assert(buttons.includes("Register the provider"), `no provider control: ${JSON.stringify(buttons)}`);
// privacy and consent need a provider id, so they must not offer a dead button
assert(!buttons.includes("Record consent"), "consent cannot be offered before a provider exists");

// the connect form posts the same shape the API test asserts
const form = doc.getElementById("models-form");
doc.getElementById("models-name").value = "flash";
doc.getElementById("models-model").value = "gemini-2.0-flash";
doc.getElementById("models-credential").value = "secret://env/GEMINI_API_KEY";
assert(doc.querySelectorAll("#models-transport option").length >= 2, "the transport picker never filled");
form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/models"), `the form never posted: ${JSON.stringify(calls.slice(-6))}`);
assert(doc.getElementById("models-credential").value === "", "the reference field must be cleared after use");

// code: the panel lists sessions, opens one, and shows the ledger it read from the server
doc.querySelector('[data-view="code"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#code-sessions .list-item").length === 1, "the session list did not render");
doc.querySelector("#code-sessions .list-item").click();
await tick();
await tick();
assert(calls.includes("GET /api/code/sessions/cs_demo"), `the session was never opened: ${JSON.stringify(calls.slice(-4))}`);
assert(doc.getElementById("code-file"), "the editor did not render");
assert(doc.getElementById("code-command"), "the runner did not render");
const ledger = doc.getElementById("code-detail").textContent;
assert(ledger.includes("hello.py"), "the edit is not shown");
assert(ledger.includes("echo hi"), "the recorded command is not shown");

doc.getElementById("code-root").value = "/tmp/smoke";
doc.getElementById("code-title").value = "smoke";
doc.getElementById("code-open-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/code/sessions"), `the open form never posted: ${JSON.stringify(calls.slice(-4))}`);

// experiments: the panel lists them, opens one, and shows what it could not read
doc.querySelector('[data-view="experiments"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#experiments-list .list-item").length === 1, "the experiment list did not render");
doc.querySelector("#experiments-list .list-item").click();
await tick();
await tick();
assert(calls.includes("GET /api/experiments/xp_demo"), `the experiment was never opened: ${JSON.stringify(calls.slice(-4))}`);
const expPanel = doc.getElementById("experiment-detail").textContent;
assert(expPanel.includes("python bench.py {n}"), "the command is not shown");
assert(expPanel.includes("sorted=10000"), "the metric is not shown");
assert(expPanel.includes("not read:"), "a run without metrics must say why, not show zeroes");
assert(doc.getElementById("experiment-name"), "the declare form did not render");

doc.getElementById("experiment-name").value = "smoke";
doc.getElementById("experiment-command").value = "python bench.py {n}";
doc.getElementById("experiment-params").value = "n=100";
doc.getElementById("experiment-create-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/experiments"), `the declare form never posted: ${JSON.stringify(calls.slice(-4))}`);

// play: a game renders with its board and its log, a refused move keeps its reason, and a
// simulation shows the hash it claims to have reproduced
doc.querySelector('[data-view="play"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#play-games .list-item").length === 1, "the game list did not render");
assert(doc.querySelectorAll("#play-sims .list-item").length === 1, "the simulation list did not render");
doc.querySelector("#play-games .list-item").click();
await tick();
await tick();
assert(calls.includes("GET /api/play/games/gm_demo"), `the game was never opened: ${JSON.stringify(calls.slice(-4))}`);
const playPanel = doc.getElementById("play-detail");
assert(playPanel.textContent.includes("square 1 is taken"), "a refused move must keep its reason");
assert(playPanel.querySelector(".board"), "the board did not render");
assert(playPanel.textContent.includes("1 of 2 proposed move(s)"), "the refusal count is not shown");

doc.getElementById("play-game-type").value = "connect4";
doc.getElementById("play-new-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/play/games"), `the new-game form never posted: ${JSON.stringify(calls.slice(-4))}`);

doc.querySelector("#play-sims .list-item").click();
await tick();
await tick();
assert(calls.includes("GET /api/play/sims/sim_demo"), `the simulation was never opened: ${JSON.stringify(calls.slice(-4))}`);
const simPanel = doc.getElementById("play-detail");
assert(simPanel.textContent.includes("deadbeefdeadbeef"), "the simulation hash is not shown");

doc.getElementById("play-sim-seed").value = "2";
doc.getElementById("play-sim-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/play/sims"), `the simulation form never posted: ${JSON.stringify(calls.slice(-4))}`);

// voice: the measurement and the disagreement with the file name are both on screen
doc.querySelector('[data-view="voice"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#voice-assets .list-item").length === 1, "the media list did not render");
assert(doc.getElementById("voice-stats").textContent.includes("1 measured"), "the stats line did not render");
doc.querySelector("#voice-assets .list-item").click();
await tick();
await tick();
assert(calls.includes("GET /api/voice/assets/ma_demo"), `the asset was never opened: ${JSON.stringify(calls.slice(-4))}`);
const voicePanel = doc.getElementById("voice-detail").textContent;
assert(voicePanel.includes("png image, 12x8, 76 bytes"), "the measurement is not shown");
assert(voicePanel.includes("the name disagrees with the bytes"), "a mislabelled file must say so");
assert(voicePanel.includes("Words a person wrote"), "the human-transcript form is missing");

doc.getElementById("voice-path").value = "tone.wav";
doc.getElementById("voice-probe-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/voice/probe"), `the probe form never posted: ${JSON.stringify(calls.slice(-4))}`);

// data: the kept record, and the dropped one with the rule that dropped it, are both on screen
doc.querySelector('[data-view="data"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#data-list .list-item").length === 1, "the dataset list did not render");
assert(doc.getElementById("data-stats").textContent.includes("1 dataset"), "the dataset stats did not render");
doc.querySelector("#data-list .list-item").click();
await tick();
await tick();
await tick();
assert(calls.includes("GET /api/datasets/ds_demo"), `the dataset was never opened: ${JSON.stringify(calls.slice(-4))}`);
const dataPanel = doc.getElementById("data-detail").textContent;
assert(dataPanel.includes("3 kept, 2 dropped"), "the counts are not shown");
assert(dataPanel.includes("declared by the user: CC-BY-4.0"), "the license provenance is not shown");
assert(dataPanel.includes("corpus/copy_a.txt"), "a dropped record must stay visible");
assert(dataPanel.includes("already in the dataset from an earlier path"), "the drop reason must be shown");

doc.getElementById("data-name").value = "second";
doc.getElementById("data-sources").value = "notes/";
doc.getElementById("data-create-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/datasets"), `the create form never posted: ${JSON.stringify(calls.slice(-4))}`);

// no inline style attributes were produced, and no inline handlers leaked into the markup
assert(!/style="/.test(doc.body.innerHTML), "inline style attribute produced");
assert(!/onclick="/.test(doc.body.innerHTML), "inline handler produced");
assert(errors.length === 0, `page errors: ${JSON.stringify(errors.slice(0, 3))}`);
assert(/\.rung-dot/.test(css), "the rung marker has no rule");

if (problems.length) {
  console.error("SMOKE FAILED");
  for (const problem of problems) console.error(" - " + problem);
  process.exit(1);
}
console.log("smoke ok: 15 tabs, 4 gate rows, code, experiment, play, voice and dataset panels render, forms post, no page errors");
