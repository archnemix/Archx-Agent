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
  "GET /api/conversations": [],
  "GET /api/tasks": [],
  "GET /api/tools": [],
  "GET /api/memory": [],
  "GET /api/jobs": { jobs: [], stats: {}, queue: [] },
  "GET /api/permissions": { grants: [], pending: [], capabilities: [] },
  "GET /api/research": [],
  "GET /api/learning/goals": [],
  "GET /api/search?q=": { results: [] },
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
assert(doc.querySelectorAll(".tab").length === 10, "expected ten mode tabs");
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
form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
await tick();
assert(calls.includes("POST /api/models"), `the form never posted: ${JSON.stringify(calls.slice(-6))}`);
assert(doc.getElementById("models-credential").value === "", "the reference field must be cleared after use");

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
console.log("smoke ok: 10 tabs, 4 gate rows, form posts, no page errors");
