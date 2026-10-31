/* Real Chromium layout and chat contract check. Fixtures are not real model inference.
 * npm install --prefix /tmp/archx-browser playwright-core @sparticuz/chromium
 * ARCHX_GUI_URL='http://127.0.0.1:8765/?token=...' node scripts/gui_chat_browser.mjs
 */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire((process.env.ARCHX_BROWSER_DIR || "/tmp/archx-browser") + "/package.json");
const { chromium } = require("playwright-core");
const imported = require("@sparticuz/chromium");
const binary = imported.default || imported;
const browser = await chromium.launch({ executablePath: await binary.executablePath(), args: binary.args, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("console", msg => { if (msg.type() === "error") errors.push("console: " + msg.text()); });
page.on("requestfailed", req => console.error("Request failed", req.url(), req.failure()));
page.on("pageerror", error => errors.push(error.message));
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const messages = [];
const sent = [];
let failNext = false;
await page.route("**/api/models", route => route.fulfill({ json: {ok: true, data: [
  { id: "md_fixture_a", name: "UI fixture A · not real inference", ready: true },
  { id: "md_fixture_b", name: "UI fixture B · not real inference", ready: true },
] } }));
await page.route("**/api/conversations?*", route => route.fulfill({ json: {ok:true, data: messages.length ? [{ id: "cv_fixture", title: "RAM and storage", updated_at: "2026-10-31T10:00:00Z" }] : []} }));
await page.route("**/api/conversations/cv_fixture/messages", route => route.fulfill({ json: {ok:true, data: { id: "cv_fixture", model_id: "md_fixture_b", messages }} }));
await page.route("**/api/chat/stream", async route => {
  sent.push(route.request().postDataJSON());
  if (failNext) {
    return route.fulfill({ contentType: "text/event-stream", body:
      'event: reasoning\ndata: {"text":"Partial provider reasoning fixture"}\n\n' +
      'event: error\ndata: {"code":"network_failure","message":"Provider fixture interrupted"}\n\n' });
  }
  const reason = "Compare working memory with persistent storage. This is provider-output test data, not real model reasoning.";
  const answer = "## RAM and storage\n\n**RAM** holds the data a running program needs. **Storage** keeps files after the power is off.\n\n- RAM is fast and temporary.\n- SSDs and hard drives are persistent.\n\nA model file lives on disk and is loaded into RAM or VRAM for inference.";
  messages.push({ role: "user", content: sent.at(-1).message }, { role: "assistant", content: answer, reasoning: reason });
  const frames = [
    ["reasoning", { text: reason.slice(0, 24) }], ["reasoning", { text: reason.slice(24) }],
    ["chunk", { text: answer.slice(0, 22) }], ["chunk", { text: answer.slice(22) }],
    ["done", { conversation_id: "cv_fixture", text: answer, reasoning: reason, model: { model_id: "md_fixture_b", name: "UI fixture B · not real inference" }, completion_tokens: 72, latency_ms: 250, warnings: ["no embedding index is available; keyword-only memory retrieval"] }],
  ];
  await route.fulfill({ contentType: "text/event-stream", body: frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("") });
});
const out = process.env.ARCHX_SCREENSHOTS || "/tmp/archx-chat-screenshots";
mkdirSync(out, { recursive: true });
try {
  await page.goto(process.env.ARCHX_GUI_URL || "http://127.0.0.1:8765/?token=archx-redesign-preview");
  await page.locator("#chat-model option[value=md_fixture_b]").waitFor({ state: "attached" });
  await page.screenshot({ path: `${out}/desktop-welcome.png` });
  assert(await page.locator(".sidebar").isVisible(), "desktop history sidebar missing");
  assert(await page.locator(".chat-layout .picker").count() === 0, "second sidebar still exists");
  assert(!(await page.locator("#workspace-menu").evaluate(node => node.open)), "advanced tools expanded by default");
  await page.selectOption("#chat-model", "md_fixture_b");
  await page.fill("#chat-input", "What is the difference between RAM and storage?");
  await page.press("#chat-input", "Enter");
  await page.locator(".model-reasoning summary").waitFor();
  await page.waitForFunction(() => !document.querySelector("#chat-form button[type=submit]").disabled);
  assert(sent.length === 1 && sent[0].model_id === "md_fixture_b", "selected model did not reach request");
  assert(!(await page.locator("#chat-diagnostics").evaluate(node => node.open)), "diagnostics opened over conversation");
  assert(!(await page.locator(".model-reasoning").evaluate(node => node.open)), "reasoning not collapsible by default");
  const user = await page.locator(".msg.user").boundingBox();
  const assistant = await page.locator(".msg.assistant").boundingBox();
  assert(user.x > assistant.x + 50, "user message is not aligned right");
  assert(await page.locator(".msg.assistant .msg-content").textContent().then(text => !text.includes("provider-output")), "reasoning leaked into answer");
  await page.locator(".model-reasoning summary").click();
  await page.screenshot({ path: `${out}/desktop-conversation.png` });
  for (let index = 0; index < 3 && await page.locator("html").getAttribute("data-theme") !== "dark"; index++) await page.click("#theme-toggle");
  await page.waitForFunction(() => getComputedStyle(document.body).backgroundColor === "rgb(27, 29, 33)");
  await page.screenshot({ path: `${out}/desktop-dark.png` });
  await page.click("#chat-new");
  await page.locator("#chat-conversations .list-item").click();
  await page.locator(".model-reasoning summary").waitFor();
  assert(await page.locator(".reasoning-text").textContent().then(text => text.includes("provider-output")), "history lost reasoning");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click("#chat-sidebar-toggle");
  await page.locator(".sidebar").waitFor({ state: "visible" });
  await page.screenshot({ path: `${out}/mobile-conversations.png` });
  await page.click("#rail-toggle");
  await page.locator(".sidebar").waitFor({ state: "hidden" });
  await page.screenshot({ path: `${out}/mobile-chat.png` });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "mobile horizontal overflow");
  await page.click("#chat-sidebar-toggle");
  await page.locator("#workspace-menu summary").click();
  await page.locator('[data-view="memory"]').click();
  await page.locator("#view-memory").waitFor({ state: "visible" });
  await page.click("#workspace-sidebar-toggle");
  await page.locator(".sidebar").waitFor({ state: "visible" });
  await page.locator('[data-view="chat"]').click();
  await page.locator("#chat-model option[value=md_fixture_b]").waitFor({state: "attached"});
  failNext = true;
  await page.fill("#chat-input", "Trigger a provider interruption fixture");
  await page.press("#chat-input", "Enter");
  await page.getByText("Provider fixture interrupted", {exact: true}).waitFor();
  await page.waitForFunction(() => !document.querySelector("#chat-form button[type=submit]").disabled);
  assert(sent.length === 2, "failed reasoning stream was automatically replayed");
  assert((await page.locator("#chat-log").innerText()).includes("Completion is unconfirmed"), "incomplete warning hidden in diagnostics");
  assert((await page.locator(".reasoning-text").allTextContents()).some(text => text.includes("Partial provider reasoning")), "interruption lost reasoning output");
  assert(errors.length === 0, `browser errors: ${errors.join("; ")}`);
  console.log("Chromium chat check passed: model request, separate reasoning, history, collapsed diagnostics, right-aligned user, desktop/mobile drawer and tools navigation; fixtures, not real inference.");
  console.log(`Screenshots: ${out}`);
} catch (error) { console.error("Page errors:", errors); console.error((await page.locator("body").innerText()).slice(0,1800)); await page.screenshot({ path: `${out}/failure.png` }); throw error; } finally { await browser.close(); }
