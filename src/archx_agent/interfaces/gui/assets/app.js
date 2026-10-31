/* The Archx GUI.
 *
 * Plain DOM, no framework, no build step, no inline handlers, no sample data. Every button
 * calls a real endpoint; when the server refuses (401, 403 approval_required, 409), the
 * refusal is rendered where the action was taken instead of being swallowed.
 *
 * The shell is one page with a view per mode. The modes differ in the tools they expose - those
 * are read from /api/status and drawn as chips in the top bar, so a mode never claims a
 * capability the workspace does not have.
 */
(() => {
  "use strict";

  // Explicit shared bindings keep view files independent without a framework or build step.
  const shared = {};

  const TOKEN_KEY = "archx_token";
  const THEME_KEY = "archx_theme";
  const THEMES = ["dark", "light", "soft"];

  const state = {
    token: null,
    view: "chat",
    conversationId: null,
    researchId: null,
    taskId: null,
    learningId: null,
    status: null,
  };

  /* What each mode is for, and the tools it leans on. `tools` is not decoration: renderTools()
   * turns each name into a chip whose value comes from the live workspace. */
  const VIEWS = {
    chat: {
      title: "Chat",
      sub: "one turn at a time · every reply is a task, with the model that produced it",
      tools: ["model", "memory", "tasks"],
    },
    research: {
      title: "Research",
      sub: "a plan that names its author, sources it actually read, citations it re-checks",
      tools: ["net.fetch", "sources", "citations"],
    },
    learning: {
      title: "Learning",
      sub: "goals with criteria, a hint ladder, and a schedule that shows its arithmetic",
      tools: ["grading", "hints", "schedule"],
    },
    code: {
      title: "Code",
      sub: "edit, run and test a directory · every step is a grant, and every command is recorded",
      tools: ["shell.run", "diffs", "checks", "artifacts"],
    },
    play: {
      title: "Play",
      sub: "games the rules referee and simulations you can replay · a refused move is kept, with its reason",
      tools: ["rules", "engine", "replay"],
    },
    voice: {
      title: "Voice",
      sub: "what a file is, measured from its bytes · a transcript says who wrote it · what cannot be heard is said out loud",
      tools: ["fs.read", "measure", "transcripts"],
    },
    data: {
      title: "Data",
      sub: "candidates measured, removals kept with their reason, splits that do not move · the manifest is a claim you can re-check",
      tools: ["fs.read", "manifest", "splits"],
    },
    train: {
      title: "Train",
      sub: "two trainers that run here · metrics as rows · a fine-tune refused by name, never faked",
      tools: ["fs.read", "metrics", "artifact"],
    },
    remote: {
      title: "Remote",
      sub: "a bundle with digests · an endpoint that computed it · a hash re-checked on arrival",
      tools: ["fs.write", "bundle_sha256", "verified"],
    },
    automations: {
      title: "Automations", sub: "durable triggers · explicit ticks · permission checked at execution",
      tools: ["schedule", "fs.probe", "jobs", "shell.run"],
    },
    scenes: {
      title: "Scenes",
      sub: "Build and measure meshes. A wireframe is not a Blender render.",
      tools: ["Create scene", "Add/remove primitive", "Measure", "Verify hashes", "Export OBJ/STL/SVG/script", "Local Blender render"],
    },
    exec: {
      title: "Exec",
      sub: "a command, the environment it ran in, and a hash per file that crossed the boundary",
      tools: ["shell.run", "targets", "ledger"],
    },
    experiments: {
      title: "Experiments",
      sub: "declared commands, declared parameters, and a comparison that says what it could not rank",
      tools: ["shell.run", "metrics", "runs"],
    },
    search: { title: "Search", sub: "one query across every source this home can see", tools: ["sources", "files"] },
    tasks: { title: "Tasks", sub: "what ran, in order, with artifacts and a reproduction record", tools: ["history", "artifacts"] },
    jobs: { title: "Jobs", sub: "durable queued work: attempts, deadlines, and a real runner", tools: ["queued", "running"] },
    access: { title: "Access", sub: "the permission centre: requests, decisions, grants", tools: ["approvals", "grants"] },
    memory: { title: "Memory", sub: "what Archx keeps, and why it kept it", tools: ["stored", "duplicates"] },
    models: { title: "Models", sub: "the catalogue, including what this build cannot run - and why", tools: ["usable"] },
    status: { title: "Status", sub: "what this home is, and what is blocked", tools: ["schema", "home"] },
  };

  // ------------------------------------------------------------------- fetch
  /* A chat reply arrives over time, so the page asks for it as server-sent events and paints
   * each piece as it lands. `EventSource` cannot POST, so this reads the body of a fetch
   * response directly. Resolves to the recorded reply (the `done` frame), or null when the
   * transport has no reader. An uncertain completion must never replay the POST. */
  async function chatStream(message, conversationId, onChunk, onReasoning, modelId) {
    const headers = { "X-Archx-Request": "gui", "Content-Type": "application/json" };
    if (state.token) headers["X-Archx-Token"] = state.token;
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers,
      credentials: "same-origin",
      body: JSON.stringify({ message, conversation_id: conversationId, model_id: modelId || null }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const error = new Error((data && data.error && data.error.message) || "HTTP " + response.status);
      error.status = response.status;
      error.code = data && data.error && data.error.code;
      throw error;
    }
    if (!response.body || typeof response.body.getReader !== "function") return null;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let final = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut = buffer.indexOf("\n\n");
      while (cut >= 0) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        let event = "message";
        let data = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) {
          const payload = JSON.parse(data);
          if (event === "chunk") onChunk(payload.text || "");
          else if (event === "reasoning" && onReasoning) onReasoning(payload.text || "");
          else if (event === "done") final = payload;
          else if (event === "error") {
            const error = new Error(payload.message || "the turn failed");
            error.code = payload.code;
            throw error;
          }
        }
        cut = buffer.indexOf("\n\n");
      }
    }
    return final;
  }

  async function api(method, path, body) {
    const headers = { "X-Archx-Request": "gui" };
    if (state.token) headers["X-Archx-Token"] = state.token;
    let payload;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const response = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
    const type = response.headers.get("content-type") || "";
    if (!type.includes("json")) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.text();
    }
    const data = await response.json().catch(() => ({ ok: false, error: { message: "unreadable response" } }));
    if (!response.ok || data.ok === false) {
      const error = new Error((data.error && data.error.message) || ("HTTP " + response.status));
      error.status = response.status;
      error.code = data.error && data.error.code;
      error.data = data.error && data.error.data;
      if (response.status === 401) showGate();
      throw error;
    }
    return data.data;
  }

  /* A refusal is shown where the action was taken, with the code that explains it. */
  function report(node, error) {
    shared.clear(node);
    node.append(shared.el("div", { class: "callout danger" }, [
      shared.el("strong", { text: error.message || String(error) }),
      error.code ? shared.el("div", { class: "small", text: "code: " + error.code }) : null,
      error.code === "approval_required"
        ? shared.el("div", { class: "small", text: "This needs a decision you have not made. Decide it in Access, or run `archx-agent approvals`." })
        : null,
    ]));
  }

  // -------------------------------------------------------------------- shell
  const gate = document.getElementById("gate");
  const views = document.getElementById("views");
  const appShell = document.getElementById("app");
  const tabButtons = Array.from(document.querySelectorAll(".tab"));

  function setConn(kind, label) {
    const conn = document.getElementById("conn");
    conn.className = "conn-state" + (kind ? " " + kind : "");
    conn.textContent = label;
  }

  function showGate() {
    gate.hidden = false;
    views.hidden = true;
    setConn("bad", "locked");
  }

  function showApp() {
    gate.hidden = true;
    views.hidden = false;
    setConn("ok", "connected");
  }

  document.getElementById("gate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("gate-token");
    const message = document.getElementById("gate-error");
    message.textContent = "";
    const candidate = input.value.trim();
    if (!candidate) return;
    state.token = candidate;
    try {
      await api("POST", "/api/session", { token: candidate });
      sessionStorage.setItem(TOKEN_KEY, candidate);
      input.value = "";
      invalidateStatus();
      showApp();
      await loadView(state.view);
    } catch (error) {
      state.token = null;
      message.textContent = error.status === 429 ? "too many attempts; wait a minute" : "that token was not accepted";
    }
  });

  for (const button of tabButtons) {
    button.addEventListener("click", () => loadView(button.dataset.view));
  }

  function activate(view) {
    state.view = view;
    appShell.classList.remove("sidebar-open");
    for (const id of ["chat-sidebar-toggle", "workspace-sidebar-toggle"]) document.getElementById(id).setAttribute("aria-expanded", "false");
    const selectedTab = Array.from(tabButtons).find(button => button.dataset.view === view);
    if (selectedTab && selectedTab.closest("details")) selectedTab.closest("details").open = true;
    const meta = VIEWS[view] || { title: view, sub: "", tools: [] };
    document.body.dataset.view = view;
    document.getElementById("crumb-view").textContent = meta.title;
    document.title = meta.title + " · Archx Agent";
    for (const button of tabButtons) {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    for (const section of document.querySelectorAll(".page")) {
      section.hidden = section.id !== "view-" + view;
    }
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", "#" + view);
    }
    renderTools(view);
    ensureStatus().then(() => { if (state.view === view) renderTools(view); });
  }

  const loaders = {};
  async function loadView(view) {
    if (!VIEWS[view]) view = "chat";
    activate(view);
    if (!loaders[view]) return;
    try {
      await loaders[view]();
    } catch (error) {
      if (error.status !== 401) shared.toast("Could not load " + view, error.message, "err");
    }
  }

  document.getElementById("reload-view").addEventListener("click", () => loadView(state.view));

  // -------------------------------------------------------------------- tools
  function toolChip(label, value, kind) {
    return shared.el("span", { class: "tool-chip " + (kind || "") }, [
      shared.el("b", { text: label }),
      value,
    ]);
  }

  function renderTools(view) {
    const box = shared.clear(document.getElementById("mode-tools"));
    const data = state.status || {};
    const meta = VIEWS[view] || { tools: [] };
    const chips = [];
    const modelsReady = data.models_usable === undefined ? null : data.models_usable;
    for (const name of meta.tools) {
      if (name === "model") {
        chips.push(modelsReady === null ? toolChip("model", "unknown")
          : modelsReady ? toolChip("model", modelsReady + " usable", "on") : toolChip("model", "none usable", "off"));
      } else if (name === "memory") {
        chips.push(toolChip("memories", shared.text(data.memories)));
      } else if (name === "tasks" || name === "history") {
        chips.push(toolChip(name === "tasks" ? "tasks" : "task history", shared.text(data.tasks)));
      } else if (name === "net.fetch") {
        chips.push(data.net_fetch_granted ? toolChip("net.fetch", "granted", "on") : toolChip("net.fetch", "not granted", "off"));
      } else if (name === "sources") {
        chips.push(toolChip("sources", view === "research" ? "local docs + your URLs" : "9 sources"));
      } else if (name === "citations") {
        chips.push(toolChip("citations", "re-checked"));
      } else if (name === "grading") {
        chips.push(toolChip("grading", "exact or self"));
      } else if (name === "hints") {
        chips.push(toolChip("hints", "one level at a time"));
      } else if (name === "schedule") {
        chips.push(toolChip("schedule", "interval · ease · why"));
      } else if (name === "shell.run") {
        chips.push(toolChip("shell.run", "needs a grant"));
      } else if (name === "diffs") {
        chips.push(toolChip("diffs", "as artifacts"));
      } else if (name === "checks") {
        chips.push(toolChip("checks", "from the project"));
      } else if (name === "files") {
        chips.push(toolChip("files", "opt-in"));
      } else if (name === "artifacts") {
        chips.push(toolChip("artifacts", "checksummed"));
      } else if (name === "queued") {
        chips.push(toolChip("queued", shared.text((data.jobs && data.jobs.queued) || 0)));
      } else if (name === "running") {
        chips.push(toolChip("running", shared.text((data.jobs && data.jobs.running) || 0)));
      } else if (name === "approvals") {
        chips.push(data.approvals_pending ? toolChip("approvals", data.approvals_pending + " pending", "off") : toolChip("approvals", "none", "on"));
      } else if (name === "grants") {
        chips.push(toolChip("grants", "scoped"));
      } else if (name === "stored") {
        chips.push(toolChip("stored", shared.text(data.memories)));
      } else if (name === "duplicates") {
        chips.push(toolChip("duplicates", "refused, not stored"));
      } else if (name === "usable") {
        chips.push(toolChip("usable", shared.text(modelsReady) + "/" + shared.text(data.models_total)));
      } else if (name === "schema") {
        chips.push(toolChip("schema", "v" + shared.text(data.schema_version)));
      } else if (name === "home") {
        chips.push(toolChip("home", "this device"));
      }
    }
    for (const chip of chips) box.append(chip);
  }

  function invalidateStatus() {
    state.status = null;
    ensureStatus().then(() => renderTools(state.view));
  }

  let statusPending = null;
  async function ensureStatus() {
    if (state.status) return state.status;
    if (!statusPending) {
      statusPending = api("GET", "/api/status")
        .then((data) => { state.status = data; return data; })
        .catch(() => null)
        .finally(() => { statusPending = null; });
    }
    return statusPending;
  }

  // ------------------------------------------------------------------- status
  loaders.status = async () => {
    const data = await api("GET", "/api/status");
    state.status = data;
    document.getElementById("version").textContent = "v" + data.version;
    const cards = shared.clear(document.getElementById("status-cards"));
    cards.append(
      shared.stat(data.memories, "memories"),
      shared.stat(data.conversations, "conversations"),
      shared.stat(data.tasks, "tasks"),
      shared.stat(data.models_usable + "/" + data.models_total, "models usable"),
      shared.stat(data.approvals_pending, "approvals pending"),
      shared.stat((data.jobs && data.jobs.queued) || 0, "jobs queued"),
    );
    const info = shared.clear(document.getElementById("status-info"));
    info.append(shared.kv([
      ["home", data.home],
      ["database", data.database],
      ["schema", "v" + data.schema_version],
      ["events", data.events],
      ["workflows", data.workflows],
      ["net.fetch granted", data.net_fetch_granted ? "yes" : "no"],
      ["simulated runtime", data.simulated_allowed ? "allowed (no real inference)" : "not allowed"],
      ["opened at", shared.stamp(data.opened_at)],
    ]));
    const blocked = shared.clear(document.getElementById("status-blocked"));
    const hints = [];
    if (!data.models_total) {
      hints.push(["No model is registered", "archx-agent models add-http --name local --base-url http://127.0.0.1:8080 --model <id>"]);
    } else if (!data.models_usable) {
      hints.push(["A model is registered but cannot run here", "archx-agent models list   (read the reason it prints)"]);
    }
    if (data.approvals_pending) hints.push([data.approvals_pending + " approval(s) waiting", "open Access, or archx-agent approvals list"]);
    for (const warning of data.warnings || []) hints.push(["Workspace warning", warning]);
    if (!hints.length) {
      blocked.append(shared.el("p", { class: "muted-box", text: "No workspace-wide block detected. Individual actions may still need permission or optional tools." }));
    } else {
      blocked.append(shared.table(["what", "next"], hints));
    }
    renderTools(state.view);
  };

  document.getElementById("status-refresh").addEventListener("click", () => {
    state.status = null;
    loaders.status().catch((error) => report(document.getElementById("status-blocked"), error));
  });

  Object.defineProperty(shared, "state", { get: () => state });
  Object.defineProperty(shared, "chatStream", { get: () => chatStream });
  Object.defineProperty(shared, "api", { get: () => api });
  Object.defineProperty(shared, "report", { get: () => report });
  Object.defineProperty(shared, "setConn", { get: () => setConn });
  Object.defineProperty(shared, "loaders", { get: () => loaders });
  Object.defineProperty(shared, "toolChip", { get: () => toolChip });
  Object.defineProperty(shared, "invalidateStatus", { get: () => invalidateStatus });

  for (const initialize of window.ArchxViews || []) initialize(shared);
  delete window.ArchxViews;

  // -------------------------------------------------------- chrome (theme, rail)
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const order = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    document.getElementById("theme-toggle").setAttribute("title", "Theme: " + theme + " (switch to " + order + ")");
    document.getElementById("theme-toggle").setAttribute("aria-label", "Theme: " + theme + ", switch to " + order);
    shared.remember(THEME_KEY, theme);
  }

  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(THEMES.includes(shared.recall(THEME_KEY)) ? shared.recall(THEME_KEY) : (prefersLight ? "light" : "dark"));

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "dark";
    applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
  });

  const mobileSidebarButton = document.getElementById("chat-sidebar-toggle");
  document.getElementById("rail-toggle").addEventListener("click", () => {
    appShell.classList.remove("sidebar-open");
    for (const toggle of [mobileSidebarButton, document.getElementById("workspace-sidebar-toggle")]) toggle.setAttribute("aria-expanded", "false");
  });
  for (const button of [mobileSidebarButton, document.getElementById("workspace-sidebar-toggle")]) {
    button.addEventListener("click", () => {
      const open = appShell.classList.toggle("sidebar-open");
      for (const toggle of [mobileSidebarButton, document.getElementById("workspace-sidebar-toggle")]) toggle.setAttribute("aria-expanded", String(open));
    });
  }
  document.querySelector(".main").addEventListener("click", event => {
    if (appShell.classList.contains("sidebar-open") && window.matchMedia("(max-width: 760px)").matches) {
      event.preventDefault(); event.stopPropagation();
      appShell.classList.remove("sidebar-open");
      for (const toggle of [mobileSidebarButton, document.getElementById("workspace-sidebar-toggle")]) toggle.setAttribute("aria-expanded", "false");
    }
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      appShell.classList.remove("sidebar-open");
      for (const toggle of [mobileSidebarButton, document.getElementById("workspace-sidebar-toggle")]) toggle.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") shared.settleModal(false);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      loadView("search");
      document.getElementById("search-query").focus();
    }
  });

  // -------------------------------------------------------------------- start
  function readTokenFromUrl() {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("token");
    if (!token) return;
    sessionStorage.setItem(TOKEN_KEY, token);
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + (url.search ? url.search : "") + url.hash);
  }

  async function boot() {
    readTokenFromUrl();
    state.token = sessionStorage.getItem(TOKEN_KEY);
    try {
      const health = await api("GET", "/api/health");
      document.getElementById("version").textContent = "v" + health.version;
      document.getElementById("footer-note").textContent = "local only · " + health.requests + " request(s) served · every API call needs the token";
      await api("GET", "/api/status");
      showApp();
    } catch (error) {
      if (error.status !== 401) setConn("bad", "unreachable");
      showGate();
      return;
    }
    const wanted = (window.location.hash || "").replace(/^#/, "");
    await loadView(VIEWS[wanted] ? wanted : "chat");
  }

  boot();
})();
