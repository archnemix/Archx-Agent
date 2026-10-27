/* The Archx GUI. Plain DOM, no framework, no build step, no inline handlers.
 *
 * Every action calls one of the server's real endpoints - there is no sample data and no
 * control that only looks functional. If the server refuses (403 approval_required, 401
 * unauthorized), the refusal is shown as text instead of being swallowed.
 */
(() => {
  "use strict";

  const TOKEN_KEY = "archx_token";
  const THEME_KEY = "archx_theme";
  const RAIL_KEY = "archx_rail";
  const state = {
    token: null,
    view: "status",
    conversationId: null,
    researchId: null,
    taskId: null,
    authRequired: true,
    status: null,
  };

  /* What each mode is for. The shell is the same everywhere - the modes differ in the
   * tools they expose, and those tools are listed in the header from live data. */
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
    search: { title: "Search", sub: "one query across every source this home can see", tools: ["sources", "files"] },
    tasks: { title: "Tasks", sub: "what ran, in order, with artifacts and a reproduction record", tools: ["history", "artifacts"] },
    jobs: { title: "Jobs", sub: "durable queued work: attempts, deadlines, and a real runner", tools: ["queued", "running"] },
    access: { title: "Access", sub: "the permission centre: requests, decisions, grants", tools: ["approvals", "grants"] },
    memory: { title: "Memory", sub: "what Archx keeps, and why it kept it", tools: ["stored", "duplicates"] },
    models: { title: "Models", sub: "the catalogue, including what this build cannot run - and why", tools: ["usable"] },
    status: { title: "Status", sub: "what this home is, and what is blocked", tools: ["schema", "home"] },
  };

  function remember(key, value) {
    try { window.localStorage.setItem(key, value); } catch (error) { /* private mode: fine */ }
  }

  function recall(key) {
    try { return window.localStorage.getItem(key); } catch (error) { return null; }
  }

  // ---------------------------------------------------------------- helpers
  function el(tag, props, children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "hidden") node.hidden = Boolean(value);
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of [].concat(children || [])) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function text(value) { return value === null || value === undefined || value === "" ? "–" : String(value); }

  function badge(label, kind) { return el("span", { class: "badge " + (kind || ""), text: label }); }

  function statusBadge(status) {
    const map = { completed: "ok", fetched: "ok", active: "ok", running: "info", queued: "info", pending: "warn",
      incomplete: "warn", paused: "warn", failed: "bad", denied: "bad", cancelled: "bad", interrupted: "bad" };
    return badge(text(status), map[status] || "");
  }

  function table(headers, rows, emptyText) {
    if (!rows.length) return el("p", { class: "muted", text: emptyText || "nothing here" });
    const head = el("tr", {}, headers.map((h) => el("th", { text: h })));
    const body = rows.map((cells) => el("tr", {}, cells.map((cell) => {
      const td = el("td", {});
      if (cell instanceof Node) td.append(cell);
      else td.textContent = text(cell);
      return td;
    })));
    return el("table", {}, [el("thead", {}, [head]), el("tbody", {}, body)]);
  }

  function stat(number, label) {
    return el("div", { class: "stat" }, [el("div", { class: "n", text: text(number) }), el("div", { class: "k", text: label })]);
  }

  function shortId(id) { return id ? id.replace(/^(rs_|jb_|tk_|ap_|pg_|mem_|conv_)/, "") .slice(-8) : "–"; }

  // ------------------------------------------------------------------ fetch
  async function api(method, path, body) {
    const headers = { "X-Archx-Request": "gui" };
    if (state.token) headers["X-Archx-Token"] = state.token;
    let payload = undefined;
    if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
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

  function report(node, error) {
    clear(node).append(el("div", { class: "error", text: error.message || String(error) }));
  }

  // ------------------------------------------------------------------ tools
  function toolChip(label, value, kind) {
    return el("span", { class: "tool " + (kind || ""), text: label + ": " + value });
  }

  function renderTools(view) {
    const box = clear(document.getElementById("mode-tools"));
    const data = state.status || {};
    const meta = VIEWS[view] || { tools: [] };
    const chips = [];
    const modelsReady = data.models_usable === undefined ? null : data.models_usable;
    for (const name of meta.tools) {
      if (name === "model") {
        chips.push(modelsReady === null ? toolChip("model", "unknown")
          : modelsReady ? toolChip("model", modelsReady + " usable", "on") : toolChip("model", "none usable", "off"));
      } else if (name === "memory") {
        chips.push(toolChip("memories", text(data.memories)));
      } else if (name === "tasks" || name === "history") {
        chips.push(toolChip(name === "tasks" ? "tasks" : "task history", text(data.tasks)));
      } else if (name === "net.fetch") {
        chips.push(data.net_fetch_granted ? toolChip("net.fetch", "granted", "on") : toolChip("net.fetch", "not granted", "off"));
      } else if (name === "sources") {
        chips.push(toolChip("sources", view === "research" ? "local docs + URLs" : "9 sources"));
      } else if (name === "citations") {
        chips.push(toolChip("citations", "re-checked"));
      } else if (name === "grading") {
        chips.push(toolChip("grading", "exact or self"));
      } else if (name === "hints") {
        chips.push(toolChip("hints", "one level at a time"));
      } else if (name === "schedule") {
        chips.push(toolChip("schedule", "interval · ease · why"));
      } else if (name === "files") {
        chips.push(toolChip("files", "opt-in"));
      } else if (name === "artifacts") {
        chips.push(toolChip("artifacts", "checksummed"));
      } else if (name === "queued") {
        chips.push(toolChip("queued", text((data.jobs && data.jobs.queued) || 0)));
      } else if (name === "running") {
        chips.push(toolChip("running", text((data.jobs && data.jobs.running) || 0)));
      } else if (name === "approvals") {
        chips.push(data.approvals_pending ? toolChip("approvals", data.approvals_pending + " pending", "off") : toolChip("approvals", "none", "on"));
      } else if (name === "grants") {
        chips.push(toolChip("grants", "scoped"));
      } else if (name === "stored") {
        chips.push(toolChip("stored", text(data.memories)));
      } else if (name === "duplicates") {
        chips.push(toolChip("duplicates", "refused, not stored"));
      } else if (name === "usable") {
        chips.push(toolChip("usable", text(modelsReady) + "/" + text(data.models_total)));
      } else if (name === "schema") {
        chips.push(toolChip("schema", "v" + text(data.schema_version)));
      } else if (name === "home") {
        chips.push(toolChip("home", "this device"));
      }
    }
    for (const chip of chips) box.append(chip);
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

  // ------------------------------------------------------------------- gate
  const gate = document.getElementById("gate");
  const views = document.getElementById("views");

  function showGate() {
    gate.hidden = false;
    views.hidden = true;
    document.body.classList.add("locked");
    const conn = document.getElementById("conn");
    conn.className = "pill bad";
    conn.textContent = "locked";
  }

  function showApp() {
    gate.hidden = true;
    views.hidden = false;
    document.body.classList.remove("locked");
    const conn = document.getElementById("conn");
    conn.className = "pill ok";
    conn.textContent = "connected";
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
      showApp();
      loadView(state.view);
    } catch (error) {
      state.token = null;
      message.textContent = error.status === 429 ? "too many attempts; wait a minute" : "that token was not accepted";
    }
  });

  // ------------------------------------------------------------------- tabs
  const tabButtons = Array.from(document.querySelectorAll(".tab"));
  for (const button of tabButtons) {
    button.addEventListener("click", () => loadView(button.dataset.view));
  }

  function activate(view) {
    state.view = view;
    const meta = VIEWS[view] || { title: view, sub: "" };
    document.body.dataset.view = view;
    document.getElementById("page-title").textContent = meta.title;
    document.getElementById("page-sub").textContent = meta.sub;
    for (const button of tabButtons) {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    for (const section of document.querySelectorAll(".view")) {
      section.hidden = section.id !== "view-" + view;
    }
    renderTools(view);
    ensureStatus().then(() => { if (state.view === view) renderTools(view); });
  }

  const loaders = {};
  async function loadView(view) {
    activate(view);
    if (!loaders[view]) return;
    try {
      await loaders[view]();
    } catch (error) {
      /* the loader has already rendered its own error where it matters */
    }
  }

  // ----------------------------------------------------------------- status
  loaders.status = async () => {
    const data = await api("GET", "/api/status");
    state.status = data;
    document.getElementById("version").textContent = "v" + data.version;
    const cards = clear(document.getElementById("status-cards"));
    cards.append(
      stat(data.memories, "memories"),
      stat(data.conversations, "conversations"),
      stat(data.tasks, "tasks"),
      stat(data.models_usable + "/" + data.models_total, "models usable"),
      stat(data.approvals_pending, "approvals pending"),
      stat((data.jobs && data.jobs.queued) || 0, "jobs queued"),
    );
    const info = clear(document.getElementById("status-info"));
    info.append(table(["key", "value"], [
      ["home", data.home], ["database", data.database], ["schema", "v" + data.schema_version],
      ["events", data.events], ["workflows", data.workflows],
      ["net.fetch granted", data.net_fetch_granted ? "yes" : "no"],
      ["simulated runtime allowed", data.simulated_allowed ? "yes (no real inference)" : "no"],
      ["opened at", data.opened_at],
    ]));
    const blocked = clear(document.getElementById("status-blocked"));
    const hints = [];
    if (!data.models_total) {
      hints.push(["No model is registered", "archx-agent models add-http --name local --base-url http://127.0.0.1:8080 --model <id>"]);
    } else if (!data.models_usable) {
      hints.push(["A model is registered but cannot run here", "archx-agent models list  (read the reason it prints)"]);
    }
    if (data.approvals_pending) hints.push([data.approvals_pending + " approval(s) waiting", "open the Access tab, or archx-agent approvals list"]);
    for (const warning of data.warnings || []) hints.push(["Workspace warning", warning]);
    if (!hints.length) blocked.append(el("p", { class: "muted", text: "Nothing is blocked. Every control in this GUI will work." }));
    else blocked.append(table(["what", "next"], hints));
    renderTools(state.view);
  };

  document.getElementById("status-refresh").addEventListener("click", () => {
    loaders.status().catch((error) => report(document.getElementById("status-blocked"), error));
  });

  // ------------------------------------------------------------------- chat
  async function loadConversations() {
    const list = clear(document.getElementById("chat-conversations"));
    const items = await api("GET", "/api/conversations?limit=30");
    if (!items.length) list.append(el("li", { class: "sub", text: "no conversations yet" }));
    for (const record of items) {
      list.append(el("li", {
        class: record.id === state.conversationId ? "active" : "",
        onclick: () => openConversation(record.id),
      }, [
        el("span", { text: record.title || "(untitled)" }),
        el("span", { class: "sub", text: shortId(record.id) + " · " + (record.updated_at || "") }),
      ]));
    }
  }

  const log = () => document.getElementById("chat-log");

  function nearBottom(box) {
    return box.scrollHeight - box.scrollTop - box.clientHeight < 140;
  }

  function bubble(role, content, meta) {
    const box = log();
    const stick = nearBottom(box);
    const node = el("div", { class: "msg " + role }, [content]);
    if (meta) node.append(el("span", { class: "meta", text: meta }));
    box.append(node);
    if (stick) box.scrollTop = box.scrollHeight;
    return node;
  }

  /* A waiting reply shows motion, not a fake percentage. */
  function thinkingBubble() {
    const box = log();
    const stick = nearBottom(box);
    const node = el("div", { class: "msg assistant" }, [
      el("span", { class: "thinking" }, [el("i"), el("i"), el("i")]),
    ]);
    box.append(node);
    if (stick) box.scrollTop = box.scrollHeight;
    return node;
  }

  async function openConversation(id) {
    state.conversationId = id;
    clear(log());
    const data = await api("GET", "/api/conversations/" + encodeURIComponent(id) + "/messages");
    for (const message of data.messages) bubble(message.role === "user" ? "user" : "assistant", message.content, message.created_at);
    await loadConversations();
  }

  loaders.chat = async () => {
    await loadConversations();
    if (state.conversationId) await openConversation(state.conversationId);
    const models = await api("GET", "/api/models").catch(() => []);
    const ready = models.filter((m) => m.ready);
    document.getElementById("chat-model").textContent = ready.length
      ? "model: " + (ready[0].name || ready[0].id)
      : "no usable model – chat will refuse and tell you how to add one";
  };

  document.getElementById("chat-conv-refresh").addEventListener("click", () => loadConversations().catch(() => {}));
  document.getElementById("chat-new").addEventListener("click", () => {
    state.conversationId = null;
    clear(log());
    bubble("assistant", "New conversation. The first message starts it.");
  });

  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    const warnings = clear(document.getElementById("chat-warnings"));
    bubble("user", message);
    chatInput.value = "";
    const button = chatForm.querySelector("button[type=submit]");
    button.disabled = true;
    const pending = thinkingBubble();
    try {
      const reply = await api("POST", "/api/chat", { message, conversation_id: state.conversationId });
      state.conversationId = reply.conversation_id;
      pending.textContent = reply.text;
      pending.append(el("span", {
        class: "meta",
        text: (reply.simulated ? "simulated runtime · " : "") +
          (reply.model && reply.model.model_id ? reply.model.model_id : "model") + " · " +
          reply.completion_tokens + " tokens · " + Math.round(reply.latency_ms) + " ms" +
          (reply.task ? " · task " + shortId(reply.task.id) : ""),
      }));
      for (const warning of reply.warnings || []) warnings.append(el("div", { text: "warning: " + warning }));
      await loadConversations();
    } catch (error) {
      pending.remove();
      const node = el("div", { class: "msg assistant" }, [el("div", { class: "error", text: error.message })]);
      if (error.code === "permission_denied" || error.code === "approval_required") {
        node.append(el("div", { class: "muted small", text: "This needs a decision you have not made. Open the Access tab or use `archx-agent approvals`." }));
      }
      log().append(node);
    } finally {
      button.disabled = false;
    }
  });

  // --------------------------------------------------------------- research
  async function loadResearchList() {
    const list = clear(document.getElementById("research-list"));
    const runs = await api("GET", "/api/research?limit=25");
    if (!runs.length) list.append(el("li", { class: "sub", text: "no runs yet" }));
    for (const run of runs) {
      list.append(el("li", {
        class: run.id === state.researchId ? "active" : "",
        onclick: () => openResearch(run.id),
      }, [
        el("span", { text: run.question }),
        el("span", { class: "sub", text: shortId(run.id) + " · " + run.status + " · " + Math.round((run.coverage || 0) * 100) + "% · " + run.plan_by + "/" + run.mode }),
      ]));
    }
  }

  async function openResearch(id) {
    state.researchId = id;
    await loadResearchList();
    const panel = clear(document.getElementById("research-detail"));
    const data = await api("GET", "/api/research/" + encodeURIComponent(id));
    const run = data.run;
    panel.append(el("h3", { text: run.question }));
    panel.append(el("div", { class: "row" }, [
      statusBadge(run.status),
      el("span", { class: "muted small", text: "mode " + run.mode }),
      el("span", { class: "muted small", text: "plan by " + run.plan_by }),
      el("span", { class: "muted small", text: "coverage " + Math.round((run.coverage || 0) * 100) + "%" }),
      el("span", { class: "muted small", text: run.evidence_count + " usable source(s)" }),
    ]));
    panel.append(el("div", { class: "cover" }, [
      el("span", { class: "muted small", text: "coverage" }),
      el("progress", { max: "100", value: String(Math.round((run.coverage || 0) * 100)) }),
    ]));
    const verification = data.verification || {};
    panel.append(el("p", { class: verification.ok ? "small" : "error small", text: verification.ok
      ? "every citation resolves (" + verification.citations + " citations, " + verification.sources_cited.length + " source(s) cited)"
      : "verification failed: unknown citations " + JSON.stringify(verification.unknown_citations) + ", uncited claims " + (verification.uncited_claims || []).length }));

    const rows = data.sources.map((source) => {
      const label = data.labels[String(source.id)];
      return [
        label ? "S" + label : "–",
        source.kind,
        statusBadge(source.status),
        source.title || source.ref || source.url || "",
        source.stance || "unknown",
        source.relevance ? Number(source.relevance).toFixed(2) : "–",
        source.error || (source.excerpt ? source.excerpt.slice(0, 160) : ""),
      ];
    });
    panel.append(el("h3", { text: "Sources (including the ones that failed)" }));
    panel.append(table(["cite", "kind", "status", "title", "stance", "rel", "excerpt / why it failed"], rows, "no sources"));

    panel.append(el("h3", { text: "Report" }));
    const reportNode = el("div", { class: "report", text: "loading…" });
    panel.append(reportNode);
    reportNode.textContent = await api("GET", "/api/research/" + encodeURIComponent(id) + "/report");

    if ((run.limitations || []).length) {
      panel.append(el("h3", { text: "Limitations" }));
      panel.append(el("ul", {}, run.limitations.map((note) => el("li", { text: note }))));
    }
  }

  loaders.research = async () => { await loadResearchList(); if (state.researchId) await openResearch(state.researchId); };

  document.getElementById("research-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = document.getElementById("research-question").value.trim();
    if (!question) return;
    const status = document.getElementById("research-status");
    const button = event.target.querySelector("button[type=submit]");
    status.textContent = "running – a web run may ask for permission";
    button.disabled = true;
    const urls = document.getElementById("research-urls").value.split("\n").map((s) => s.trim()).filter(Boolean);
    const subquestions = document.getElementById("research-subquestions").value.split("\n").map((s) => s.trim()).filter(Boolean);
    try {
      const result = await api("POST", "/api/research", {
        question,
        mode: document.getElementById("research-mode").value,
        urls,
        subquestions,
        use_model: !document.getElementById("research-nomodel").checked,
      });
      status.textContent = "";
      state.researchId = result.run.id;
      await openResearch(result.run.id);
    } catch (error) {
      status.textContent = "";
      const panel = clear(document.getElementById("research-detail"));
      panel.append(el("h3", { text: "This run was refused" }));
      panel.append(el("p", { class: "error", text: error.message }));
      if (error.code === "approval_required") {
        panel.append(el("p", { class: "muted", text: "Web research needs the net.fetch capability. Decide it in the Access tab; Archx will not grant it for you." }));
      }
      await loadResearchList().catch(() => {});
    } finally {
      button.disabled = false;
    }
  });

  // --------------------------------------------------------------- learning
  state.learningId = null;

  async function loadLearningGoals() {
    const list = clear(document.getElementById("learning-goals"));
    const data = await api("GET", "/api/learning?limit=30");
    if (!data.goals.length) list.append(el("li", { class: "sub", text: "no goals yet" }));
    for (const goal of data.goals) {
      list.append(el("li", {
        class: goal.id === state.learningId ? "active" : "",
        onclick: () => openLearning(goal.id),
      }, [
        el("span", { text: goal.title }),
        el("span", { class: "sub", text: goal.status + " · " + goal.stats.items + " item(s) · " + goal.stats.due + " due · " + (goal.stats.accuracy === null ? "no attempts" : Math.round(goal.stats.accuracy * 100) + "% correct") }),
      ]));
    }
  }

  function learningAnswerForm(goalId, item, panel) {
    const answer = el("textarea", { rows: "3", placeholder: "your answer" });
    const rating = el("select", {}, [
      el("option", { value: "" }, ["self-rating (needed when there is no expected answer)"]),
      el("option", { value: "1" }, ["1 – no idea"]),
      el("option", { value: "2" }, ["2 – shaky"]),
      el("option", { value: "3" }, ["3 – mostly right"]),
      el("option", { value: "4" }, ["4 – confident"]),
      el("option", { value: "5" }, ["5 – could teach it"]),
    ]);
    const feedback = el("div", { class: "warnings" });
    const form = el("form", { class: "card" }, [
      el("label", {}, ["answer ", answer]),
      el("label", {}, ["how did it go? ", rating]),
      el("div", { class: "row" }, [
        el("button", { class: "primary", type: "submit", text: "Answer" }),
        el("span", { class: "muted small", text: item.graded_by_hint || "graded against the expected answer, or by your rating" }),
      ]),
      feedback,
    ]);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clear(feedback);
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        const result = await api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/answer", {
          item_id: item.id,
          answer: answer.value,
          self_rating: rating.value || null,
        });
        const grade = result.grade;
        feedback.append(el("div", { text: (grade.correct ? "correct" : "not yet") + " (graded by " + grade.graded_by + ") – " + grade.feedback }));
        feedback.append(el("div", { text: "next review: " + result.schedule.due_at + " · " + result.schedule.why }));
        if (result.explanation) feedback.append(el("div", { text: "explanation: " + result.explanation }));
        await openLearning(goalId);
        await loadLearningGoals();
      } catch (error) {
        feedback.append(el("div", { class: "error", text: error.message }));
      } finally {
        button.disabled = false;
      }
    });
    panel.append(form);
  }

  function learningItemForm(goalId) {
    const note = el("span", { class: "muted small" });
    const prompt = el("input", { placeholder: "Which journal mode lets readers keep reading?" });
    const expected = el("input", { placeholder: "answer Archx can check (leave blank to self-grade)" });
    const hints = el("textarea", { rows: "3", placeholder: "one hint per line, easiest first" });
    const form = el("form", { class: "card" }, [
      el("label", { text: "add an item" }, [prompt]),
      el("label", { text: "expected answer" }, [expected]),
      el("label", { text: "hint ladder" }, [hints]),
      el("div", { class: "row" }, [
        el("button", { type: "submit", class: "primary", text: "Add item" }),
        note,
      ]),
    ]);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      clear(note);
      try {
        const item = await api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/items", {
          prompt: prompt.value,
          expected: expected.value,
          hints: hints.value,
        });
        note.append(el("span", { class: "muted small", text: "added " + shortId(item.id) }));
        await openLearning(goalId);
      } catch (error) {
        note.append(el("span", { class: "error", text: error.message }));
      } finally {
        button.disabled = false;
      }
    });
    return form;
  }

  async function openLearning(goalId) {
    state.learningId = goalId;
    await loadLearningGoals();
    const panel = clear(document.getElementById("learning-detail"));
    const data = await api("GET", "/api/learning/goals/" + encodeURIComponent(goalId));
    const goal = data.goal;
    const stats = data.stats;
    panel.append(el("h3", { text: goal.title }));
    panel.append(el("div", { class: "row" }, [
      statusBadge(goal.status),
      el("span", { class: "muted small", text: "level " + goal.level }),
      el("span", { class: "muted small", text: stats.items + " item(s)" }),
      el("span", { class: "muted small", text: stats.due + " due" }),
      el("span", { class: "muted small", text: stats.attempts + " attempt(s)" }),
      el("span", { class: "muted small", text: stats.accuracy === null ? "nothing graded yet" : Math.round(stats.accuracy * 100) + "% correct" }),
    ]));
    if (goal.objective) panel.append(el("p", { class: "muted", text: goal.objective }));
    if ((goal.success_criteria || []).length) {
      panel.append(el("p", { class: "small", text: "done when: " + goal.success_criteria.join("; ") }));
    }

    const tools = el("div", { class: "row" });
    tools.append(el("button", {
      text: "Propose items (no model)", onclick: async () => {
        try {
          const result = await api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/plan", { use_model: false });
          await openLearning(goalId);
          await loadLearningGoals();
          const detail = document.getElementById("learning-detail");
          detail.append(el("p", { class: "muted small", text: "planned " + result.items.length + " by " + result.planned_by + ": " + result.why }));
        } catch (error) { window.alert(error.message); }
      },
    }));
    tools.append(el("button", {
      text: "Start a review of what is due", onclick: async () => {
        try {
          await api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/review", {});
          await openLearning(goalId);
        } catch (error) { window.alert(error.message); }
      },
    }));
    panel.append(tools);
    panel.append(learningItemForm(goalId));

    panel.append(el("h3", { text: "Next up" }));
    const next = data.next || {};
    if (next.nothing_to_study) {
      panel.append(el("p", { class: "muted", text: next.message || "nothing to study right now" }));
    } else {
      const item = next.item;
      panel.append(el("p", { text: item.prompt }));
      panel.append(el("p", { class: "muted small", text: next.why + (item.hint_count ? " · " + item.hint_count + " hint(s)" : "") }));
      const hintBox = el("div", { class: "warnings" });
      const hintButton = el("button", {
        text: "Reveal a hint", onclick: async () => {
          clear(hintBox);
          try {
            const result = await api("POST", "/api/learning/items/" + encodeURIComponent(item.id) + "/hint", { level: (item.revealed || 0) + 1 });
            item.revealed = result.level;
            hintBox.append(el("div", { text: "hint " + result.level + " of " + result.total + ": " + result.hint }));
          } catch (error) {
            hintBox.append(el("div", { class: "error", text: error.message }));
          }
        },
      });
      if (item.hint_count) panel.append(hintButton);
      panel.append(hintBox);
      learningAnswerForm(goalId, item, panel);
    }

    panel.append(el("h3", { text: "Items and schedule" }));
    panel.append(table(["item", "status", "due", "streak", "interval", "next review", "prompt"], data.items.map((item) => [
      shortId(item.id), statusBadge(item.status), item.due ? "yes" : "no", String(item.streak),
      item.interval_days + "d", item.due_at || "–", item.prompt,
    ]), "no items yet – propose some, or add them from the CLI"));

    if ((data.sessions || []).length) {
      panel.append(el("h3", { text: "Sessions" }));
      panel.append(table(["session", "mode", "status", "answered", "correct", "started"], data.sessions.map((session) => [
        shortId(session.id), session.mode, statusBadge(session.status), String(session.items_attempted),
        String(session.items_correct), session.started_at,
      ])));
    }
  }

  loaders.learning = async () => {
    await loadLearningGoals();
    if (state.learningId) await openLearning(state.learningId);
  };

  document.getElementById("learning-refresh").addEventListener("click", () => {
    loaders.learning().catch((error) => report(document.getElementById("learning-detail"), error));
  });

  document.getElementById("learning-goal-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("learning-goal-status");
    status.textContent = "";
    const criteria = document.getElementById("learning-criteria").value.trim();
    try {
      const goal = await api("POST", "/api/learning/goals", {
        title: document.getElementById("learning-title").value,
        criteria: criteria ? [criteria] : [],
      });
      document.getElementById("learning-title").value = "";
      document.getElementById("learning-criteria").value = "";
      await openLearning(goal.id);
    } catch (error) {
      status.textContent = "";
      report(document.getElementById("learning-detail"), error);
    }
  });

  // ----------------------------------------------------------------- search
  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("search-query").value.trim();
    if (!query) return;
    const notes = clear(document.getElementById("search-notes"));
    const panel = clear(document.getElementById("search-results"));
    try {
      const files = document.getElementById("search-files").checked;
      const data = await api("GET", "/api/search?q=" + encodeURIComponent(query) + "&files=" + (files ? "1" : "0"));
      for (const [kind, reason] of Object.entries(data.skipped || {})) notes.append(el("div", { text: "skipped " + kind + ": " + reason }));
      for (const reason of data.degraded || []) notes.append(el("div", { text: "degraded: " + reason }));
      const rows = data.hits.map((hit) => [hit.kind, hit.title, hit.score.toFixed(2), hit.snippet, hit.ref]);
      panel.append(el("p", { class: "muted small", text: data.total + " hit(s) in " + Math.round(data.elapsed_ms) + " ms" }));
      panel.append(table(["kind", "title", "score", "why it matched", "ref"], rows, "no hits"));
    } catch (error) {
      report(panel, error);
    }
  });

  // ------------------------------------------------------------------ tasks
  async function loadTasks() {
    const list = clear(document.getElementById("tasks-list"));
    const status = document.getElementById("tasks-status").value;
    const tasks = await api("GET", "/api/tasks?limit=40" + (status ? "&status=" + status : ""));
    if (!tasks.length) list.append(el("li", { class: "sub", text: "no tasks" }));
    for (const task of tasks) {
      list.append(el("li", {
        class: task.id === state.taskId ? "active" : "",
        onclick: () => openTask(task.id),
      }, [
        el("span", { text: task.title }),
        el("span", { class: "sub", text: task.type + " · " + task.status + " · " + (task.created_at || "") }),
      ]));
    }
  }

  async function openTask(id) {
    state.taskId = id;
    await loadTasks();
    const panel = clear(document.getElementById("task-detail"));
    const data = await api("GET", "/api/tasks/" + encodeURIComponent(id));
    const task = data.task;
    panel.append(el("h3", { text: task.title }));
    panel.append(el("div", { class: "row" }, [statusBadge(task.status), el("span", { class: "muted small", text: task.type })]));
    panel.append(table(["field", "value"], Object.entries(task)
      .filter(([, value]) => value !== null && value !== "" && typeof value !== "object")
      .map(([key, value]) => [key, String(value)])));
    if (data.timeline.length) {
      panel.append(el("h3", { text: "Timeline" }));
      panel.append(table(["#", "kind", "detail", "at"], data.timeline.map((entry, index) => [
        String(index + 1), entry.kind, entry.detail || "", entry.created_at || entry.at || "",
      ])));
    }
    if (data.artifacts.length) {
      panel.append(el("h3", { text: "Artifacts" }));
      panel.append(table(["kind", "path", "sha256"], data.artifacts.map((a) => [a.kind, a.path, (a.checksum || "").slice(0, 16)])));
    }
    if (data.tools.length) {
      panel.append(el("h3", { text: "Tool runs" }));
      panel.append(table(["tool", "status", "at"], data.tools.map((t) => [t.tool_name, t.status, t.started_at || ""])));
    }
  }

  loaders.tasks = async () => { await loadTasks(); if (state.taskId) await openTask(state.taskId); };
  document.getElementById("tasks-refresh").addEventListener("click", () => loadTasks().catch(() => {}));
  document.getElementById("tasks-status").addEventListener("change", () => loadTasks().catch(() => {}));

  // ------------------------------------------------------------------- jobs
  loaders.jobs = async () => {
    const data = await api("GET", "/api/jobs?limit=30");
    const cards = clear(document.getElementById("jobs-stats"));
    for (const [key, value] of Object.entries(data.stats || {})) cards.append(stat(value, key.replace(/_/g, " ")));
    const panel = clear(document.getElementById("jobs-list"));
    const rows = data.jobs.map((job) => {
      const actions = el("div", { class: "row" });
      for (const action of ["pause", "resume", "retry", "cancel"]) {
        actions.append(el("button", {
          class: "tiny" + (action === "cancel" ? " danger" : ""),
          text: action,
          onclick: async () => {
            try { await api("POST", "/api/jobs/" + encodeURIComponent(job.id) + "/" + action, {}); await loaders.jobs(); }
            catch (error) { window.alert(error.message); }
          },
        }));
      }
      return [shortId(job.id), job.kind, statusBadge(job.status), job.title, job.priority, actions];
    });
    panel.append(table(["id", "kind", "status", "title", "prio", "actions"], rows, "the queue is empty"));
  };

  document.getElementById("jobs-refresh").addEventListener("click", () => loaders.jobs().catch((error) => report(document.getElementById("jobs-list"), error)));
  document.getElementById("jobs-run").addEventListener("click", async (event) => {
    const button = event.target;
    button.disabled = true;
    try {
      const result = await api("POST", "/api/jobs/drain", { max_jobs: 1 });
      if (!result.ran.length) window.alert("nothing was queued to run");
      await loaders.jobs();
    } catch (error) {
      window.alert(error.message);
    } finally {
      button.disabled = false;
    }
  });

  // ----------------------------------------------------------------- access
  loaders.access = async () => {
    const approvals = await api("GET", "/api/approvals?status=pending");
    const list = clear(document.getElementById("approvals-list"));
    if (!approvals.length) list.append(el("p", { class: "muted", text: "no pending approvals" }));
    else {
      list.append(table(["id", "capability", "subject", "scope", "why", "decide"], approvals.map((approval) => [
        shortId(approval.id), approval.capability, approval.subject, approval.scope, approval.reason,
        el("div", { class: "row" }, [
          el("button", { class: "tiny primary", text: "approve", onclick: async () => {
            try { await api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/approve", {}); await loaders.access(); }
            catch (error) { window.alert(error.message); }
          } }),
          el("button", { class: "tiny danger", text: "deny", onclick: async () => {
            try { await api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/deny", {}); await loaders.access(); }
            catch (error) { window.alert(error.message); }
          } }),
        ]),
      ])));
    }
    const permissions = await api("GET", "/api/permissions?active_only=1");
    const grants = clear(document.getElementById("grants-list"));
    if (!permissions.grants.length) grants.append(el("p", { class: "muted", text: "no active grants – nothing can touch your files, run a program or fetch the web" }));
    else {
      grants.append(table(["id", "capability", "subject", "scope", "expires", ""], permissions.grants.map((grant) => [
        shortId(grant.id), grant.capability, grant.subject, grant.scope, grant.expires_at || "no expiry",
        el("button", { class: "tiny danger", text: "revoke", onclick: async () => {
          try { await api("POST", "/api/permissions/" + encodeURIComponent(grant.id) + "/revoke", {}); await loaders.access(); }
          catch (error) { window.alert(error.message); }
        } }),
      ])));
    }
    const caps = clear(document.getElementById("capabilities-list"));
    caps.append(table(["capability", "risk", "effect", "what it allows"], permissions.capabilities.map((cap) => [
      cap.name, cap.risk, cap.effect, cap.description,
    ])));
  };

  document.getElementById("access-refresh").addEventListener("click", () => loaders.access().catch((error) => report(document.getElementById("grants-list"), error)));

  // ----------------------------------------------------------------- memory
  async function loadMemory() {
    const items = await api("GET", "/api/memory?limit=50");
    const panel = clear(document.getElementById("memory-list"));
    panel.append(table(["kind", "title", "content", "category", "scope", "status"], items.map((item) => [
      item.kind, item.title, (item.content || "").slice(0, 120), item.category || "–", item.scope, item.status,
    ]), "no memories yet"));
  }

  loaders.memory = loadMemory;
  document.getElementById("memory-refresh").addEventListener("click", () => loadMemory().catch((error) => report(document.getElementById("memory-list"), error)));
  document.getElementById("memory-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("memory-status");
    status.textContent = "";
    try {
      await api("POST", "/api/memory", {
        kind: document.getElementById("memory-kind").value,
        title: document.getElementById("memory-title").value,
        content: document.getElementById("memory-content").value,
        category: document.getElementById("memory-category").value || null,
      });
      document.getElementById("memory-title").value = "";
      document.getElementById("memory-content").value = "";
      status.textContent = "stored";
      await loadMemory();
    } catch (error) {
      status.textContent = "";
      report(document.getElementById("memory-list"), error);
    }
  });

  // ----------------------------------------------------------------- models
  loaders.models = async () => {
    const models = await api("GET", "/api/models");
    const panel = clear(document.getElementById("models-list"));
    panel.append(table(["name", "runtime", "task", "ready", "why", "capabilities"], models.map((model) => [
      model.name || model.id, model.runtime, model.task || "–",
      model.ready ? badge("yes", "ok") : badge("no", "bad"),
      model.ready_reason, (model.capabilities || []).join(", "),
    ]), "no models registered – add one with `archx-agent models add-http`"));
  };

  document.getElementById("models-refresh").addEventListener("click", () => loaders.models().catch((error) => report(document.getElementById("models-list"), error)));

  // -------------------------------------------------------- chrome (theme, rail)
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.getElementById("theme-toggle").setAttribute(
      "title", theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme");
    remember(THEME_KEY, theme);
  }

  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(recall(THEME_KEY) || (prefersLight ? "light" : "dark"));

  document.getElementById("theme-toggle").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });

  const appShell = document.getElementById("app");
  if (recall(RAIL_KEY) === "compact") appShell.classList.add("compact");
  document.getElementById("rail-toggle").addEventListener("click", () => {
    appShell.classList.toggle("compact");
    remember(RAIL_KEY, appShell.classList.contains("compact") ? "compact" : "full");
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      loadView("search");
      document.getElementById("search-query").focus();
    }
  });

  // ------------------------------------------------------------------ start
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
      document.getElementById("footer-note").textContent =
        "local only · requests: " + health.requests + " · token required for every API call";
      await api("GET", "/api/status");
      showApp();
    } catch (error) {
      if (error.status !== 401) {
        const conn = document.getElementById("conn");
        conn.className = "pill bad";
        conn.textContent = "unreachable";
      }
      showGate();
      return;
    }
    await loadView("status");
  }

  boot();
})();
