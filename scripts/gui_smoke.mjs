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
// Follow the page order so this checks the exact scripts users receive.
const script = [...html.matchAll(/<script src="\/([^"/]+\.js)"><\/script>/g)]
  .map((match) => readFileSync(`${ROOT}/${match[1]}`, "utf8")).join("\n");
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
  "GET /api/training/runs/tj_demo": {
    id: "tj_demo", method: "ngram", kind: "ngram", status: "completed", base_model: null,
    dataset_id: "ds_demo", config: { order: 2, seed: 0 }, preflight: { checks: [
      { check: "dataset", ok: true, detail: "dataset 'ds_demo' exists" },
      { check: "manifest", ok: true, detail: "the files on disk still produce the recorded manifest" },
    ] },
    metrics: { train: { perplexity: 2.5811, records: 3 }, val: { perplexity: 6.5897, records: 3 } },
    checkpoints: [], seed: 0, artifact_path: "tj_demo.model.json",
    artifact_sha256: "0a93cbd8ece429dc51055e4f0a42570ccfefec0b3d13583f800688ed029c7516",
    refusal: null, version_id: "v1", notes: "", started_at: "2026-10-28T10:00:00Z",
    completed_at: "2026-10-28T10:00:00Z", error: null, task_id: null,
    created_at: "2026-10-28T10:00:00Z", metric_rows: [], reasons: [],
    sentence: "ngram trained on ds_demo and wrote tj_demo.model.json",
  },
  "GET /api/training/runs": {
    runs: [
      { id: "tj_demo", method: "ngram", kind: "ngram", status: "completed", base_model: null,
        dataset_id: "ds_demo", config: {}, preflight: {}, metrics: {}, checkpoints: [], seed: 0,
        artifact_path: "tj_demo.model.json", artifact_sha256: "0a93", refusal: null,
        version_id: "v1", notes: "", started_at: null, completed_at: null, error: null,
        task_id: null, created_at: "2026-10-28T10:00:00Z" },
      { id: "tj_refused", method: "lora", kind: "lora", status: "refused", base_model: null,
        dataset_id: "ds_demo", config: {}, preflight: {}, metrics: {}, checkpoints: [], seed: 0,
        artifact_path: null, artifact_sha256: null,
        refusal: "training is off: `archx-agent config set training.enabled true`; no adapter in this build can fine-tune anything",
        version_id: null, notes: "", started_at: null, completed_at: null, error: null,
        task_id: null, created_at: "2026-10-28T10:00:00Z" },
    ],
    stats: { jobs: 2, by_status: { completed: 1, refused: 1 }, metrics: 6,
             methods: ["ngram", "centroid", "lora", "qlora", "full"],
             runnable: ["ngram", "centroid"], finetune: ["lora", "qlora", "full"],
             can_finetune: false },
    methods: ["ngram", "centroid", "lora", "qlora", "full"],
  },
  "POST /api/training/runs": {
    id: "tj_new", method: "ngram", status: "refused",
    reasons: ["training is off", "no adapter in this build can fine-tune anything"],
    sentence: "ngram was refused before it started",
  },
  // remote: two hashes that agree, and an endpoint that is named
  "GET /api/remote/jobs/rj_demo": {
    id: "rj_demo", provider: "worker", kind: "training", status: "verified",
    dataset_id: "ds_demo", endpoint: "http://127.0.0.1:9001", machine: "box",
    protocol: "archx-remote/1",
    bundle_sha256: "ea35ae177c0aed3c60fa748f4e7c35761612898519f56eb7400784fea29f5dd5",
    bundle_path: "code.bundle.json",
    claimed_sha256: "8974207343b5330b33523079ffd245ae80842225d1413ddf623549d1cb96c65d",
    received_sha256: "8974207343b5330b33523079ffd245ae80842225d1413ddf623549d1cb96c65d",
    artifact_path: "rj_demo.remote.json", verified_at: "2026-10-28T10:00:00Z",
    verify_note: "the artifact on disk still hashes to what was received",
    remote_job_id: "rj_worker_1", received_at: "2026-10-28T10:00:00Z", refusal: null,
    config: {}, estimate: {}, actual: { records: 8, seconds: 0.001 },
    outputs: { artifact_kind: "ngram", metrics: { train: { perplexity: 2.8928, records: 5 } } },
    approved_by: "user:cli", created_at: "2026-10-28T10:00:00Z",
    completed_at: "2026-10-28T10:00:00Z", error: null, task_id: null,
    sentence: "http://127.0.0.1:9001 computed this from bundle ea35ae177c0a and the artifact's hash was checked here",
    attempts: [
      { id: "ra_1", job_id: "rj_demo", action: "dispatch", status: "ok", detail: "accepted as rj_worker_1",
        endpoint: "http://127.0.0.1:9001", created_at: "2026-10-28T10:00:00Z", metadata: {} },
    ],
    reasons: [],
  },
  // exec: one local run, and a backend that is not usable here
  "GET /api/exec/runs/xr_demo": {
    id: "xr_demo", target_id: "xt_local", kind: "local", command: "echo hello",
    invocation: "echo hello", cwd: ".", status: "ok", exit_code: 0, duration_ms: 3.1,
    stdout: "hello\n", stderr: "", stdout_path: "xr_demo.stdout.txt", stderr_path: null,
    truncated: false, detached: false, note: "ran on this machine", remote_job_id: null,
    task_id: null, started_at: "2026-10-29T10:00:00Z", ended_at: "2026-10-29T10:00:00Z",
    sentence: "`echo hello` ran on this machine and exited 0", reasons: [],
  },
  "GET /api/automations": { automations: [{ id: "au_demo", name: "backup", enabled: false, schedule: { mode: "interval", seconds: 60 }, next_run_at: "2026-10-30T00:00:00Z" }], runs: [] },
  "POST /api/automations/tick": { dispatched: [], refused: [] },
  "POST /api/automations/au_demo/enable": { id: "au_demo", enabled: true },
  "POST /api/automations": { id: "au_demo", enabled: false },
  "GET /api/scenes/sc_demo": { id: "sc_demo", name: "demo", measured: { triangles: 12, volume: 8 },
    objects_detail: [{ name: "cube", primitive: "cube", triangles: 12, watertight: true }], outputs: [], drifted: false },
  "GET /api/scenes": { scenes: [{ id: "sc_demo", name: "demo", triangles: 12 }], stats: {} },
  "POST /api/scenes/sc_demo/add": { id: "sc_demo", name: "demo" },
  "POST /api/scenes/sc_demo/preview": { svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>' },
  "POST /api/scenes/sc_demo/render": { status: "refused", reasons: ["no Blender binary configured"] },
  "POST /api/scenes": { id: "sc_demo", name: "demo" },
  "GET /api/exec/runs": {
    runs: [
      { id: "xr_demo", kind: "local", command: "echo hello", status: "ok", exit_code: 0,
        started_at: "2026-10-29T10:00:00Z" },
      { id: "xr_refused", kind: "docker", command: "python3 -V", status: "refused", exit_code: null,
        started_at: "2026-10-29T10:00:00Z" },
    ],
    stats: { targets: 2, runs: 2, files: 1, conflicts: 0, by_kind: { local: 1, docker: 1 },
             enabled: true, default_target: "local" },
  },
  "GET /api/exec/targets": {
    probes: [
      { kind: "local", available: true, summary: "this machine", why_not: [], enable: null,
        isolation: "capability grants only", this_machine: "Linux" },
      { kind: "docker", available: false, summary: "a container per command",
        why_not: ["the docker CLI is not on PATH here, so no container can be started"],
        enable: "install Docker", isolation: "a container", this_machine: "Linux" },
    ],
    targets: [
      { id: "xt_local", kind: "local", name: "local", status: "probed", endpoint: null,
        spec: {}, refusal: null, created_at: "2026-10-29T10:00:00Z", last_probe_at: null },
      { id: "xt_docker", kind: "docker", name: "docker", status: "refused", endpoint: null,
        spec: {}, refusal: "the docker CLI is not on PATH here, so no container can be started",
        created_at: "2026-10-29T10:00:00Z", last_probe_at: null },
    ],
    stats: { targets: 2, runs: 2, files: 1, conflicts: 0, by_kind: {}, enabled: true,
             default_target: "local" },
  },
  "POST /api/exec/runs": {
    id: "xr_new", kind: "local", command: "echo hi", status: "ok", exit_code: 0,
    sentence: "`echo hi` ran on this machine and exited 0", reasons: [], stdout: "hi",
  },
  "GET /api/remote/jobs": {
    jobs: [
      { id: "rj_demo", provider: "worker", kind: "training", status: "verified", dataset_id: "ds_demo",
        endpoint: "http://127.0.0.1:9001", bundle_sha256: "ea35", created_at: "2026-10-28T10:00:00Z" },
      { id: "rj_refused", provider: "worker", kind: "training", status: "refused", dataset_id: "ds_demo",
        endpoint: "http://127.0.0.1:9001", bundle_sha256: "bb11", created_at: "2026-10-28T10:00:00Z" },
    ],
    stats: { jobs: 2, by_status: { verified: 1, refused: 1 }, attempts: 3, unverified: 0,
             protocol: "archx-remote/1", enabled: true, endpoint: "http://127.0.0.1:9001",
             statuses: ["draft", "dispatched", "running", "received", "verified", "failed", "refused"] },
    attempts: [],
  },
  "POST /api/remote/export": {
    id: "rj_new", records: 8, chars: 308,
    bundle_sha256: "ea35ae177c0aed3c60fa748f4e7c35761612898519f56eb7400784fea29f5dd5",
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
window.TextDecoder = TextDecoder;
let streamScenario = null;

/* a fetch that answers from the table above and records what the page asked for */
window.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, "");
  calls.push(`${method} ${path}`);
  if (path === "/api/chat/stream" && streamScenario) {
    const scenario = streamScenario;
    let read = 0;
    return { ok: true, status: 200, body: scenario === "no-reader" ? null : { getReader: () => ({ read: async () => {
      read += 1;
      if (read === 1) return { done: false, value: new TextEncoder().encode('event: chunk\ndata: {"text":"partial reply"}\n\n') };
      if (scenario === "throws") throw new Error("connection lost");
      if (scenario === "complete" && read === 2) return { done: false, value: new TextEncoder().encode('event: done\ndata: {"conversation_id":"conv_stream","text":"complete reply","completion_tokens":2,"latency_ms":10}\n\n') };
      return { done: true };
    } }) } };
  }
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
assert(doc.querySelectorAll(".tab").length === 20, "expected twenty mode tabs");
assert(doc.getElementById("view-code"), "the coding view is missing");
assert(doc.getElementById("view-experiments"), "the experiments view is missing");
assert(doc.getElementById("view-play"), "the play view is missing");
assert(doc.getElementById("view-voice"), "the voice view is missing");
assert(doc.getElementById("view-data"), "the datasets view is missing");
assert(doc.getElementById("view-train"), "the training view is missing");
assert(doc.getElementById("view-remote"), "the remote view is missing");
assert(doc.getElementById("view-exec"), "the execution view is missing");
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

// train: the metrics are shown, and the refusal is a card rather than a disabled button
doc.querySelector('[data-view="train"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#train-runs .list-item").length === 2, "the run list did not render");
assert(doc.getElementById("train-stats").textContent.includes("2 run"), "the run stats did not render");
doc.querySelector("#train-runs .list-item").click();
await tick();
await tick();
await tick();
assert(calls.includes("GET /api/training/runs/tj_demo"), `the run was never opened: ${JSON.stringify(calls.slice(-4))}`);
const trainPanel = doc.getElementById("train-detail").textContent;
assert(trainPanel.includes("perplexity"), "the metric name is not shown");
assert(trainPanel.includes("6.5897"), "the validation value is not shown");
assert(trainPanel.includes("the files on disk still produce the recorded manifest"), "the preflight checks are not shown");

doc.getElementById("train-method").value = "lora";
doc.getElementById("train-dataset").value = "ds_demo";
doc.getElementById("train-run-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
await tick();
assert(calls.includes("POST /api/training/runs"), `the run form never posted: ${JSON.stringify(calls.slice(-4))}`);
assert(doc.getElementById("train-run-status").textContent.includes("refused"), "a refusal must be reported as one");

// remote: both hashes on screen, and an action that is limited to what the row allows
doc.querySelector('[data-view="remote"]').click();
await tick();
await tick();
assert(doc.querySelectorAll("#remote-jobs .list-item").length === 2, "the remote list did not render");
assert(doc.getElementById("remote-stats").textContent.includes("2 job"), "the remote stats did not render");
doc.querySelector("#remote-jobs .list-item").click();
await tick();
await tick();
await tick();
assert(calls.includes("GET /api/remote/jobs/rj_demo"), `the remote job was never opened: ${JSON.stringify(calls.slice(-4))}`);
const remotePanel = doc.getElementById("remote-detail").textContent;
assert(remotePanel.includes("measured here"), "the measured hash row is missing");
assert(remotePanel.includes("8974207343b5330b33523079ff"), "the artifact hash is not shown");
assert(remotePanel.includes("perplexity"), "the worker's metrics are not shown");
assert(remotePanel.includes("the artifact on disk still hashes to what was received"), "the verify note is not shown");

doc.getElementById("remote-dataset").value = "ds_demo";
doc.getElementById("remote-export-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
await tick();
assert(calls.includes("POST /api/remote/export"), `the export form never posted: ${JSON.stringify(calls.slice(-4))}`);
assert(doc.getElementById("remote-export-status").textContent.includes("bundled"), "the export was not reported");

// exec: where a command ran is on the row, and an unusable backend is named rather than hidden
doc.querySelector('[data-view="exec"]').click();
await tick();
await tick();
assert(calls.includes("GET /api/exec/targets"), `the exec panel never asked for targets: ${JSON.stringify(calls.slice(-4))}`);
assert(doc.querySelectorAll("#exec-runs .list-item").length === 2, "the run list did not render");
const probes = doc.getElementById("exec-probes").textContent;
assert(probes.includes("docker"), "an unusable backend is not listed");
assert(probes.includes("docker CLI is not on PATH"), "an unusable backend does not say why");
assert(doc.getElementById("exec-target").options.length >= 1, "the target picker is empty");
doc.querySelector("#exec-runs .list-item").click();
await tick();
await tick();
await tick();
assert(calls.includes("GET /api/exec/runs/xr_demo"), `the run was never opened: ${JSON.stringify(calls.slice(-4))}`);
const execPanel = doc.getElementById("exec-detail").textContent;
assert(execPanel.includes("ran on this machine"), "the run sentence is not shown");
assert(execPanel.includes("echo hello"), "the command is not shown");

doc.getElementById("exec-cmdline").value = "echo hi";
doc.getElementById("exec-run-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
await tick();
assert(calls.includes("POST /api/exec/runs"), `the exec form never posted: ${JSON.stringify(calls.slice(-4))}`);
assert(doc.getElementById("exec-run-status").textContent.includes("exit"), "the exit code is not reported");

// Scene UI: measured geometry, safe image preview, edits and recorded renderer refusal.
doc.querySelector('[data-view="scenes"]').click();
await tick(); await tick();
assert(doc.querySelectorAll("#scenes-list .list-item").length === 1, "scene list did not render");
doc.querySelector("#scenes-list .list-item").click();
await tick(); await tick();
assert(doc.getElementById("scene-detail").textContent.includes("12"), "scene metrics missing");
doc.getElementById("scene-add-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick(); await tick(); await tick();
assert(calls.includes("POST /api/scenes/sc_demo/add"), "scene add did not post");
Array.from(doc.querySelectorAll("#scene-detail button")).find(button => button.textContent === "preview").click();
await tick(); await tick(); await tick();
assert(doc.querySelector("#scene-detail img"), "wireframe image missing");
Array.from(doc.querySelectorAll("#scene-detail button")).find(button => button.textContent === "render").click();
await tick(); await tick(); await tick();
assert(doc.getElementById("scenes-status").textContent.includes("refused"), "render refusal hidden");

doc.querySelector('[data-view="automations"]').click();
await tick(); await tick();
assert(doc.getElementById("automations-list").textContent.includes("disabled"), "automation state hidden");
doc.querySelector("#automations-list button").click();
await tick(); await tick();
assert(calls.includes("POST /api/automations/au_demo/enable"), "automation enable did not post");
doc.getElementById("automations-tick").click();
await tick(); await tick();
assert(calls.includes("POST /api/automations/tick"), "automation tick did not post");

// Uncertain SSE completion must never turn into a second POST.
for (const scenario of ["missing-done", "throws", "no-reader", "complete"]) {
  streamScenario = scenario;
  const start = calls.length;
  doc.getElementById("chat-input").value = "one logical turn";
  doc.getElementById("chat-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  // A second, nonempty draft while the first request awaits data must be preserved.
  doc.getElementById("chat-input").value = "second while pending";
  doc.getElementById("chat-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await tick(); await tick(); await tick();
  const requests = calls.slice(start);
  assert(requests.filter(call => call === "POST /api/chat/stream").length === 1, scenario + ": concurrent submit duplicated the turn");
  assert(!requests.includes("POST /api/chat"), scenario + ": uncertain stream was automatically resent");
  assert(!doc.querySelector("#chat-form button[type=submit]").disabled, scenario + ": composer stayed disabled");
  assert(doc.getElementById("chat-input").value === "second while pending", scenario + ": ignored submit consumed the next draft");
  if (scenario === "complete") assert(doc.getElementById("chat-log").textContent.includes("complete reply"), "successful stream missing");
  else assert(doc.getElementById("chat-log").textContent.includes("partial reply") || scenario === "no-reader", "partial output lost");
}
streamScenario = null;

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
console.log("smoke ok: 20 tabs, 4 gate rows, code, experiment, play, voice, dataset, training, remote and exec panels render, forms post, 4 chat stream completion/failure scenarios prevent duplicate POST, no page errors");
