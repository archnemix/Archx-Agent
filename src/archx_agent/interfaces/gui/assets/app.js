/* The Archx GUI.
 *
 * Plain DOM, no framework, no build step, no inline handlers, no sample data. Every button
 * calls a real endpoint; when the server refuses (401, 403 approval_required, 409), the
 * refusal is rendered where the action was taken instead of being swallowed.
 *
 * The shell is one page with ten views. The modes differ in the tools they expose - those
 * are read from /api/status and drawn as chips in the top bar, so a mode never claims a
 * capability the workspace does not have.
 */
(() => {
  "use strict";

  const TOKEN_KEY = "archx_token";
  const THEME_KEY = "archx_theme";
  const RAIL_KEY = "archx_rail";
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
    search: { title: "Search", sub: "one query across every source this home can see", tools: ["sources", "files"] },
    tasks: { title: "Tasks", sub: "what ran, in order, with artifacts and a reproduction record", tools: ["history", "artifacts"] },
    jobs: { title: "Jobs", sub: "durable queued work: attempts, deadlines, and a real runner", tools: ["queued", "running"] },
    access: { title: "Access", sub: "the permission centre: requests, decisions, grants", tools: ["approvals", "grants"] },
    memory: { title: "Memory", sub: "what Archx keeps, and why it kept it", tools: ["stored", "duplicates"] },
    models: { title: "Models", sub: "the catalogue, including what this build cannot run - and why", tools: ["usable"] },
    status: { title: "Status", sub: "what this home is, and what is blocked", tools: ["schema", "home"] },
  };

  // ------------------------------------------------------------------ storage
  function remember(key, value) {
    try { window.localStorage.setItem(key, value); } catch (error) { /* private mode: fine */ }
  }

  function recall(key) {
    try { return window.localStorage.getItem(key); } catch (error) { return null; }
  }

  // -------------------------------------------------------------- dom helpers
  function flatten(value, out) {
    if (Array.isArray(value)) {
      for (const item of value) flatten(item, out);
      return out;
    }
    out.push(value);
    return out;
  }

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
    for (const child of flatten(children || [], [])) {
      if (child === null || child === undefined || child === false || child === "") continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function text(value) { return value === null || value === undefined || value === "" ? "–" : String(value); }

  /* Icons are inline SVG built through createElementNS: the page may not load an icon font,
   * and an inline <svg> string would need innerHTML. */
  const ICONS = {
    copy: ["M9 9h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z", "M15 5H6a2 2 0 0 0-2 2v9"],
    download: ["M12 3v12", "m7 11 5 5 5-5", "M4 20h16"],
    refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
    plus: ["M12 5v14", "M5 12h14"],
    send: ["m5 12 14-7-4 7 4 7-14-7Z"],
    play: ["m8 5 11 7-11 7Z"],
    pause: ["M9 5v14", "M15 5v14"],
    stop: ["M6 6h12v12H6z"],
    retry: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
    check: ["m5 13 4 4L19 7"],
  };

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgIcon(name) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "ico");
    svg.setAttribute("aria-hidden", "true");
    for (const d of ICONS[name] || []) {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }

  function iconButton(name, label, handler, extra) {
    return el("button", {
      class: "icon-btn" + (extra ? " " + extra : ""),
      type: "button",
      title: label,
      "aria-label": label,
      onclick: handler,
    }, [svgIcon(name)]);
  }

  function badge(label, kind) { return el("span", { class: "tag " + (kind || ""), text: label }); }

  function statusBadge(status) {
    const map = {
      completed: "ok", fetched: "ok", active: "ok", ready: "ok", succeeded: "ok", mastered: "ok",
      running: "accent", queued: "accent", pending: "warn", incomplete: "warn", paused: "warn", draft: "warn",
      failed: "bad", denied: "bad", cancelled: "bad", interrupted: "bad", error: "bad",
    };
    return badge(text(status), map[status] || "");
  }

  function table(headers, rows, emptyText) {
    if (!rows || !rows.length) {
      return el("p", { class: "muted-box", text: emptyText || "nothing here" });
    }
    const head = el("tr", {}, headers.map((label) => el("th", { text: label })));
    const body = rows.map((cells) => el("tr", {}, cells.map((cell) => {
      const td = el("td", {});
      if (cell instanceof Node) td.append(cell);
      else td.textContent = text(cell);
      return td;
    })));
    const node = el("table", { class: "data" }, [el("thead", {}, [head]), el("tbody", {}, body)]);
    return el("div", { class: "table-wrap" }, [node]);
  }

  function kv(pairs) {
    return el("div", { class: "kv" }, pairs.map(([key, value]) => [
      el("div", { class: "k", text: key }),
      el("div", { text: text(value) }),
    ]));
  }

  function stat(number, label) {
    return el("div", { class: "stat" }, [
      el("div", { class: "n", text: text(number) }),
      el("div", { class: "k", text: label }),
    ]);
  }

  function shortId(id) {
    return id ? id.replace(/^(rs_|jb_|tk_|ap_|pg_|mem_|conv_|lg_|it_|ss_)/, "").slice(-8) : "–";
  }

  function stamp(value) {
    if (!value) return "";
    // "2026-10-27T09:12:04.123456+00:00" reads better as "2026-10-27 09:12"
    return String(value).replace("T", " ").replace(/\.[^ ]+/, "").replace(/([+-]\d\d:\d\d|Z)$/, "");
  }

  // ------------------------------------------------------------- clipboard/io
  function toast(title, message, kind) {
    const box = document.getElementById("toasts");
    const node = el("div", { class: "toast " + (kind || "") }, [
      el("span", { class: "toast-title", text: title }),
      message ? String(message) : null,
    ]);
    box.append(node);
    window.setTimeout(() => node.remove(), kind === "err" ? 7000 : 3400);
  }

  /* A destructive act asks first: revoking a grant or denying an approval is not undoable
   * from this page, so it is confirmed in a real dialog rather than a mouse slip. */
  let modalResolve = null;
  let modalWantsNote = false;

  /* Resolves false when dismissed, true when confirmed, or {note} when it asked for one. */
  function ask(options) {
    const modal = document.getElementById("modal");
    document.getElementById("modal-title").textContent = options.title;
    document.getElementById("modal-text").textContent = options.text || "";
    const field = document.getElementById("modal-field");
    const note = document.getElementById("modal-note");
    modalWantsNote = Boolean(options.note);
    field.hidden = !modalWantsNote;
    note.value = "";
    const ok = document.getElementById("modal-ok");
    ok.textContent = options.okLabel || "Confirm";
    ok.className = "btn " + (options.kind === "primary" ? "primary" : "danger");
    modal.hidden = false;
    (modalWantsNote ? note : ok).focus();
    return new Promise((resolve) => { modalResolve = resolve; });
  }

  function settleModal(confirmed) {
    const modal = document.getElementById("modal");
    if (modal.hidden) return;
    const note = document.getElementById("modal-note").value.trim();
    modal.hidden = true;
    const wantsNote = modalWantsNote;
    modalWantsNote = false;
    const resolve = modalResolve;
    modalResolve = null;
    if (!resolve) return;
    if (!confirmed) return resolve(false);
    return resolve(wantsNote ? { note } : true);
  }

  document.getElementById("modal-cancel").addEventListener("click", () => settleModal(false));
  document.getElementById("modal-ok").addEventListener("click", () => settleModal(true));
  document.getElementById("modal").addEventListener("click", (event) => {
    if (event.target === document.getElementById("modal")) settleModal(false);
  });

  function copyText(value, label) {
    const textValue = String(value == null ? "" : value);
    const done = () => toast("Copied", label || (textValue.length > 60 ? textValue.slice(0, 60) + "…" : textValue), "ok");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(textValue).then(done, () => fallbackCopy(textValue, done));
      return;
    }
    fallbackCopy(textValue, done);
  }

  function fallbackCopy(value, done) {
    const area = el("textarea", { class: "sr-only" });
    area.value = value;
    document.body.append(area);
    area.select();
    try { document.execCommand("copy"); done(); } catch (error) { toast("Could not copy", error.message, "err"); }
    area.remove();
  }

  function downloadText(filename, value, type) {
    const blob = new Blob([value], { type: type || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: filename });
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast("Saved", filename, "ok");
  }

  // ---------------------------------------------------------------- markdown
  /* A small, deliberate subset: headings, emphasis, inline code, fenced blocks with copy,
   * tables with copy/CSV, lists, quotes, rules and links. Everything is built as DOM nodes
   * and text nodes, so a hostile reply cannot inject markup - and the CSP would stop it
   * anyway. */
  function renderInline(parent, source) {
    let buffer = "";
    let index = 0;
    const flush = () => { if (buffer) { parent.append(document.createTextNode(buffer)); buffer = ""; } };
    while (index < source.length) {
      const char = source[index];
      if (char === "\n") { flush(); parent.append(el("br")); index += 1; continue; }
      if (char === "`") {
        const end = source.indexOf("`", index + 1);
        if (end > index + 1) {
          flush();
          parent.append(el("code", { text: source.slice(index + 1, end) }));
          index = end + 1;
          continue;
        }
      }
      if (source.startsWith("**", index)) {
        const end = source.indexOf("**", index + 2);
        if (end > index + 2) {
          flush();
          const node = el("strong");
          renderInline(node, source.slice(index + 2, end));
          parent.append(node);
          index = end + 2;
          continue;
        }
      }
      if (source.startsWith("~~", index)) {
        const end = source.indexOf("~~", index + 2);
        if (end > index + 2) {
          flush();
          const node = el("s");
          renderInline(node, source.slice(index + 2, end));
          parent.append(node);
          index = end + 2;
          continue;
        }
      }
      if (char === "*") {
        const end = source.indexOf(char, index + 1);
        if (end > index + 1) {
          flush();
          const node = el("em");
          renderInline(node, source.slice(index + 1, end));
          parent.append(node);
          index = end + 1;
          continue;
        }
      }
      if (char === "[") {
        const close = source.indexOf("](", index);
        const end = close > -1 ? source.indexOf(")", close + 2) : -1;
        if (close > index + 1 && end > close + 2) {
          const label = source.slice(index + 1, close);
          const href = source.slice(close + 2, end);
          flush();
          if (/^https?:\/\//i.test(href)) {
            parent.append(el("a", { href, target: "_blank", rel: "noopener noreferrer", text: label }));
          } else {
            parent.append(document.createTextNode(label));
          }
          index = end + 1;
          continue;
        }
      }
      buffer += char;
      index += 1;
    }
    flush();
    return parent;
  }

  function codeBlock(language, code) {
    const head = el("div", { class: "cb-head" }, [
      el("span", { class: "cb-lang", text: language || "text" }),
      el("button", { class: "cb-copy", type: "button", onclick: () => copyText(code, language + " block copied") }, [svgIcon("copy"), "copy"]),
    ]);
    return el("div", { class: "codeblock" }, [head, el("pre", {}, [el("code", { text: code })])]);
  }

  function splitRow(line) {
    let body = line.trim();
    if (body.startsWith("|")) body = body.slice(1);
    if (body.endsWith("|")) body = body.slice(0, -1);
    return body.split("|").map((cell) => cell.trim());
  }

  function isTableSeparator(line) {
    return /\|/.test(line) && /^[\s:|-]+$/.test(line) && /-/.test(line);
  }

  function markdownTable(rows) {
    const header = rows[0];
    const body = rows.slice(1);
    const toCSV = () => [header].concat(body)
      .map((cells) => cells.map((cell) => '"' + String(cell).replace(/"/g, '""') + '"').join(","))
      .join("\n");
    const wrap = el("div", { class: "table-wrap" });
    const toolbar = el("div", { class: "tw-head" }, [
      el("span", { class: "tw-label", text: header.length + " columns · " + body.length + " rows" }),
      el("div", { class: "tw-actions" }, [
        el("button", { class: "cb-copy", type: "button", onclick: () => copyText(toCSV(), "table copied as CSV") }, [svgIcon("copy"), "csv"]),
        el("button", { class: "cb-copy", type: "button", onclick: () => downloadText("archx-table.csv", toCSV(), "text/csv;charset=utf-8") }, [svgIcon("download"), "save"]),
      ]),
    ]);
    const head = el("tr", {}, header.map((label) => el("th", {}, renderInline(el("span"), label))));
    const lines = body.map((cells) => el("tr", {}, header.map((_, column) => {
      const cell = el("td");
      if (cells[column] !== undefined) renderInline(cell, cells[column]);
      return cell;
    })));
    wrap.append(toolbar, el("table", { class: "data" }, [
      el("thead", {}, [head]),
      el("tbody", {}, lines),
    ]));
    return wrap;
  }

  function renderMarkdown(source) {
    const nodes = [];
    const lines = String(source == null ? "" : source).replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    const blockStart = (line) => /^\s*(```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s)/.test(line)
      || /^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})\s*$/.test(line);

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }

      const fence = /^\s*```(\S*)\s*$/.exec(line);
      if (fence) {
        const body = [];
        index += 1;
        while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) { body.push(lines[index]); index += 1; }
        index += 1;
        nodes.push(codeBlock(fence[1], body.join("\n")));
        continue;
      }

      if (line.includes("|") && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
        const rows = [splitRow(line)];
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          rows.push(splitRow(lines[index]));
          index += 1;
        }
        nodes.push(markdownTable(rows));
        continue;
      }

      const heading = /^\s*(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        const level = Math.min(heading[1].length + 1, 5);
        const node = el("h" + level);
        renderInline(node, heading[2].replace(/\s+#+\s*$/, ""));
        nodes.push(node);
        index += 1;
        continue;
      }

      if (/^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})\s*$/.test(line)) {
        nodes.push(el("hr"));
        index += 1;
        continue;
      }

      if (/^\s*>/.test(line)) {
        const body = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) {
          body.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        nodes.push(el("blockquote", {}, renderMarkdown(body.join("\n"))));
        continue;
      }

      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const list = el(ordered ? "ol" : "ul");
        while (index < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[index])) {
          const match = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/.exec(lines[index]);
          const item = el("li");
          let content = match[1];
          index += 1;
          while (index < lines.length && lines[index].trim() && !blockStart(lines[index]) && !isTableSeparator(lines[index])) {
            content += " " + lines[index].trim();
            index += 1;
          }
          renderInline(item, content);
          list.append(item);
        }
        nodes.push(list);
        continue;
      }

      const paragraph = [];
      while (index < lines.length && lines[index].trim() && !blockStart(lines[index]) && !(lines[index].includes("|") && index + 1 < lines.length && isTableSeparator(lines[index + 1]))) {
        paragraph.push(lines[index].trim());
        index += 1;
      }
      if (!paragraph.length) { index += 1; continue; }
      const node = el("p");
      renderInline(node, paragraph.join("\n"));
      nodes.push(node);
    }
    return nodes;
  }

  // ------------------------------------------------------------------- fetch
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
    clear(node);
    node.append(el("div", { class: "callout danger" }, [
      el("strong", { text: error.message || String(error) }),
      error.code ? el("div", { class: "small", text: "code: " + error.code }) : null,
      error.code === "approval_required"
        ? el("div", { class: "small", text: "This needs a decision you have not made. Decide it in Access, or run `archx-agent approvals`." })
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
      if (error.status !== 401) toast("Could not load " + view, error.message, "err");
    }
  }

  document.getElementById("reload-view").addEventListener("click", () => loadView(state.view));

  // -------------------------------------------------------------------- tools
  function toolChip(label, value, kind) {
    return el("span", { class: "tool-chip " + (kind || "") }, [
      el("b", { text: label }),
      value,
    ]);
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
        chips.push(toolChip("sources", view === "research" ? "local docs + your URLs" : "9 sources"));
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
    info.append(kv([
      ["home", data.home],
      ["database", data.database],
      ["schema", "v" + data.schema_version],
      ["events", data.events],
      ["workflows", data.workflows],
      ["net.fetch granted", data.net_fetch_granted ? "yes" : "no"],
      ["simulated runtime", data.simulated_allowed ? "allowed (no real inference)" : "not allowed"],
      ["opened at", stamp(data.opened_at)],
    ]));
    const blocked = clear(document.getElementById("status-blocked"));
    const hints = [];
    if (!data.models_total) {
      hints.push(["No model is registered", "archx-agent models add-http --name local --base-url http://127.0.0.1:8080 --model <id>"]);
    } else if (!data.models_usable) {
      hints.push(["A model is registered but cannot run here", "archx-agent models list   (read the reason it prints)"]);
    }
    if (data.approvals_pending) hints.push([data.approvals_pending + " approval(s) waiting", "open Access, or archx-agent approvals list"]);
    for (const warning of data.warnings || []) hints.push(["Workspace warning", warning]);
    if (!hints.length) {
      blocked.append(el("p", { class: "muted-box", text: "Nothing is blocked. Every control in this GUI will work." }));
    } else {
      blocked.append(table(["what", "next"], hints));
    }
    renderTools(state.view);
  };

  document.getElementById("status-refresh").addEventListener("click", () => {
    state.status = null;
    loaders.status().catch((error) => report(document.getElementById("status-blocked"), error));
  });

  // --------------------------------------------------------------------- chat
  const log = () => document.getElementById("chat-log");
  const chatInput = () => document.getElementById("chat-input");

  function nearBottom(box) { return box.scrollHeight - box.scrollTop - box.clientHeight < 160; }

  function scrollDown(box, force) {
    if (force || nearBottom(box)) box.scrollTop = box.scrollHeight;
  }

  function avatarFor(role) {
    return el("div", { class: "avatar", "aria-hidden": "true", text: role === "user" ? "YOU" : "AX" });
  }

  /* One transcript row: avatar, role, body, and actions that appear on hover or focus. */
  function addMessage(role, content, meta) {
    const box = log();
    const plain = typeof content === "string" ? content : null;
    const contentNode = el("div", { class: "msg-content" });
    if (plain === null) contentNode.append(content);
    else contentNode.append(...renderMarkdown(plain));

    const actions = el("div", { class: "msg-actions" }, [
      iconButton("copy", "Copy this message", () => copyText(
        plain === null ? contentNode.textContent : plain,
        "message copied",
      )),
    ]);

    const row = el("div", { class: "msg-row" }, [
      el("div", { class: "msg " + role }, [
        avatarFor(role),
        el("div", { class: "msg-body" }, [
          el("div", { class: "msg-head" }, [
            el("span", { class: "msg-role", text: role === "user" ? "You" : "Archx" }),
            meta ? el("span", { class: "msg-meta", text: meta }) : null,
          ]),
          contentNode,
          actions,
        ]),
      ]),
    ]);
    box.append(row);
    scrollDown(box, false);
    return { row, content: contentNode, actions, body: row.lastChild };
  }

  function thinkingRow() {
    const box = log();
    const row = el("div", { class: "msg-row" }, [
      el("div", { class: "msg assistant" }, [
        avatarFor("assistant"),
        el("div", { class: "msg-body" }, [
          el("div", { class: "msg-head" }, [el("span", { class: "msg-role", text: "Archx" })]),
          el("div", { class: "msg-content" }, [el("span", { class: "thinking" }, [el("i"), el("i"), el("i")])]),
        ]),
      ]),
    ]);
    box.append(row);
    scrollDown(box, true);
    return row;
  }

  function chatWelcome() {
    const box = clear(log());
    const prompts = [
      ["Explain sqlite locking", "Explain how sqlite locking works, and when a writer blocks a reader."],
      ["What ran today?", "Summarise the tasks I ran today, newest first."],
      ["What do you remember?", "List what you have stored in memory about this home, with the kind of each entry."],
      ["Draft a checklist", "Draft a checklist for releasing a local-first CLI, with the checks I would have to run."],
    ];
    box.append(el("div", { class: "empty" }, [
      el("div", { class: "empty-mark", text: "AX" }),
      el("h2", { text: "What should we work on?" }),
      el("p", { text: "Every reply is recorded as a task you can replay, with the model that produced it and the tokens it cost." }),
      el("div", { class: "chips" }, prompts.map(([label, prompt]) => el("button", {
        class: "chip",
        type: "button",
        text: label,
        onclick: () => {
          const input = chatInput();
          input.value = prompt;
          input.focus();
          autogrow();
        },
      }))),
    ]));
  }

  async function loadConversations() {
    const list = clear(document.getElementById("chat-conversations"));
    const items = await api("GET", "/api/conversations?limit=40");
    if (!items.length) {
      list.append(el("li", { class: "list-empty", text: "no conversations yet" }));
      return;
    }
    for (const record of items) {
      list.append(el("li", {
        class: "list-item" + (record.id === state.conversationId ? " active" : ""),
        onclick: () => openConversation(record.id),
      }, [
        el("span", { class: "t", text: record.title || "(untitled)" }),
        el("span", { class: "s", text: stamp(record.updated_at) + " · " + shortId(record.id) }),
      ]));
    }
  }

  async function openConversation(id) {
    state.conversationId = id;
    clear(log());
    const data = await api("GET", "/api/conversations/" + encodeURIComponent(id) + "/messages");
    if (!data.messages.length) chatWelcome();
    for (const message of data.messages) {
      const role = message.role === "user" ? "user" : "assistant";
      addMessage(role, message.content, stamp(message.created_at));
    }
    scrollDown(log(), true);
    await loadConversations();
  }

  async function loadModelBadge() {
    const models = await api("GET", "/api/models").catch(() => []);
    const ready = models.filter((model) => model.ready);
    const node = document.getElementById("chat-model");
    if (ready.length) {
      const model = ready[0];
      node.textContent = (model.name || model.id) + (model.runtime ? " · " + model.runtime : "")
        + (model.simulated ? " · simulated" : "");
    } else {
      node.textContent = "no usable model – a turn will be refused, and say how to add one";
    }
  }

  loaders.chat = async () => {
    await loadConversations();
    if (state.conversationId) await openConversation(state.conversationId);
    else if (!log().childElementCount) chatWelcome();
    await loadModelBadge();
  };

  document.getElementById("chat-conv-refresh").addEventListener("click", () => {
    loadConversations().catch((error) => toast("Could not list conversations", error.message, "err"));
  });

  document.getElementById("chat-new").addEventListener("click", () => {
    state.conversationId = null;
    chatWelcome();
    chatInput().focus();
    loadConversations().catch(() => {});
  });

  /* The CSP forbids an inline style attribute, so the composer grows by rows. */
  function autogrow() {
    const input = chatInput();
    const width = input.clientWidth || 720;
    const perLine = Math.max(28, Math.floor(width / 7.6));
    const lines = input.value.split("\n").reduce((total, line) => total + Math.max(1, Math.ceil(line.length / perLine)), 0);
    input.rows = Math.max(1, Math.min(12, lines));
  }

  const chatForm = document.getElementById("chat-form");
  chatInput().addEventListener("input", autogrow);
  chatInput().addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });
  autogrow();

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = chatInput();
    const message = input.value.trim();
    if (!message) return;
    const warnings = clear(document.getElementById("chat-warnings"));
    if (log().querySelector(".empty")) clear(log());
    addMessage("user", message, "now");
    input.value = "";
    autogrow();
    const button = chatForm.querySelector("button[type=submit]");
    button.disabled = true;
    setConn("busy", "thinking");
    const pending = thinkingRow();
    try {
      const reply = await api("POST", "/api/chat", { message, conversation_id: state.conversationId });
      state.conversationId = reply.conversation_id;
      pending.remove();
      const model = reply.model && (reply.model.name || reply.model.model_id);
      const meta = [
        reply.simulated ? "simulated" : null,
        model,
        reply.completion_tokens + " tokens",
        Math.round(reply.latency_ms) + " ms",
        reply.task ? "task " + shortId(reply.task.id) : null,
      ].filter(Boolean).join(" · ");
      addMessage("assistant", reply.text, meta);
      for (const warning of reply.warnings || []) {
        warnings.append(el("div", { class: "callout warn", text: "warning: " + warning }));
      }
      setConn("ok", "connected");
      await loadConversations();
      invalidateStatus();
    } catch (error) {
      pending.remove();
      setConn("bad", "refused");
      const node = addMessage("assistant", "", null);
      node.content.append(el("div", { class: "callout danger" }, [
        el("strong", { text: error.message }),
        error.code ? el("div", { class: "small", text: "code: " + error.code }) : null,
        error.code === "permission_denied" || error.code === "approval_required"
          ? el("div", { class: "small", text: "Decide it in Access, or run `archx-agent approvals`." })
          : null,
      ]));
    } finally {
      button.disabled = false;
    }
  });

  // ----------------------------------------------------------------- research
  function researchItem(run) {
    return el("li", {
      class: "list-item" + (run.id === state.researchId ? " active" : ""),
      onclick: () => openResearch(run.id),
    }, [
      el("span", { class: "t", text: run.question }),
      el("span", {
        class: "s",
        text: (run.closed ? "done · " : "") + run.status + " · "
          + Math.round((run.coverage || 0) * 100) + "% coverage · "
          + run.plan_by + "/" + run.mode + " · " + shortId(run.id),
      }),
    ]);
  }

  async function loadResearchList() {
    const list = clear(document.getElementById("research-list"));
    const runs = await api("GET", "/api/research?limit=30");
    if (!runs.length) {
      list.append(el("li", { class: "list-empty", text: "no runs yet" }));
      return runs;
    }
    for (const run of runs) list.append(researchItem(run));
    return runs;
  }

  async function openResearch(id) {
    state.researchId = id;
    await loadResearchList();
    const panel = clear(document.getElementById("research-detail"));
    const data = await api("GET", "/api/research/" + encodeURIComponent(id));
    const run = data.run;
    const verification = data.verification || {};
    const coverage = Math.round((run.coverage || 0) * 100);

    panel.append(el("div", { class: "research-run-head" }, [
      el("div", {}, [
        el("h2", { text: run.question }),
        el("div", { class: "goal-meta" }, [
          statusBadge(run.status),
          el("span", { text: "mode " + run.mode }),
          el("span", { text: "plan by " + run.plan_by }),
          el("span", { text: run.evidence_count + " usable source(s)" }),
          el("span", { text: shortId(run.id) }),
          run.closed ? el("span", { class: "tag ok", text: "done " + stamp(run.closed_at) }) : null,
          run.closed && run.closed_note ? el("span", { text: run.closed_note }) : null,
        ]),
      ]),
      el("div", { class: "row" }, [
        run.closed
          ? el("button", {
            class: "btn tiny",
            type: "button",
            title: "Put this question back on the list",
            onclick: async () => {
              try {
                await api("POST", "/api/research/" + encodeURIComponent(id) + "/reopen", {});
                toast("Reopened", "the run is open again", "ok");
                await openResearch(id);
                await loadResearchList();
              } catch (error) { toast("Could not reopen", error.message, "err"); }
            },
          }, ["reopen"])
          : el("button", {
            class: "btn tiny primary",
            type: "button",
            title: "Mark this question done",
            onclick: async () => {
              const answer = await ask({
                title: "Mark this question done?",
                text: "Closure is your call, not a coverage threshold: this records that you are finished with the question, whatever the run found. You can reopen it.",
                okLabel: "Mark complete",
                kind: "primary",
                note: true,
              });
              if (!answer) return;
              try {
                await api("POST", "/api/research/" + encodeURIComponent(id) + "/close", { note: answer.note });
                toast("Marked complete", "the run is closed; `research reopen` undoes it", "ok");
                await openResearch(id);
                await loadResearchList();
              } catch (error) { toast("Could not close the run", error.message, "err"); }
            },
          }, [svgIcon("check"), "mark complete"]),
        el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => api("GET", "/api/research/" + encodeURIComponent(id) + "/report")
            .then((reportText) => copyText(reportText, "report copied"))
            .catch((error) => toast("Could not copy the report", error.message, "err")),
        }, [svgIcon("copy"), "copy report"]),
        el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => api("GET", "/api/research/" + encodeURIComponent(id) + "/report")
            .then((reportText) => downloadText("research-" + shortId(id) + ".md", reportText, "text/markdown;charset=utf-8"))
            .catch((error) => toast("Could not save the report", error.message, "err")),
        }, [svgIcon("download"), "save .md"]),
      ]),
    ]));

    panel.append(el("div", { class: "coverage" }, [
      el("span", { class: "small dim", text: "coverage" }),
      el("progress", { class: "bar", max: "100", value: String(Math.max(0, Math.min(100, coverage))) }),
      el("span", { class: "pct", text: coverage + "%" }),
    ]));

    panel.append(el("p", { class: verification.ok ? "small dim" : "callout warn" }, [
      verification.ok
        ? "every citation resolves (" + verification.citations + " citation(s), " + (verification.sources_cited || []).length + " source(s) cited)"
        : "verification failed: unknown citations " + JSON.stringify(verification.unknown_citations)
          + ", uncited claims " + (verification.uncited_claims || []).length,
    ]));

    panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Sources" }), el("p", { text: "including the ones that failed" })])]));
    panel.append(table(
      ["cite", "kind", "status", "title", "stance", "rel", "excerpt / why it failed"],
      data.sources.map((source) => {
        const label = data.labels[String(source.id)];
        return [
          label ? "S" + label : "–",
          source.kind,
          statusBadge(source.status),
          source.title || source.ref || source.url || "",
          source.stance || "unknown",
          source.relevance ? Number(source.relevance).toFixed(2) : "–",
          source.error || (source.excerpt ? source.excerpt.slice(0, 180) : ""),
        ];
      }),
      "no sources",
    ));

    panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Report" })])]));
    const reportBox = el("div", { class: "panel" });
    reportBox.append(el("p", { class: "loading" }, [el("span", { class: "spinner" }), "reading the report"]));
    panel.append(reportBox);
    try {
      const reportText = await api("GET", "/api/research/" + encodeURIComponent(id) + "/report");
      clear(reportBox);
      reportBox.append(...renderMarkdown(reportText));
    } catch (error) {
      report(reportBox, error);
    }

    if ((run.limitations || []).length) {
      panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Limitations" }), el("p", { text: "what this run did not do" })])]));
      panel.append(el("ul", { class: "criteria" }, run.limitations.map((note) => el("li", { text: note }))));
    }
  }

  loaders.research = async () => {
    await loadResearchList();
    if (state.researchId) await openResearch(state.researchId);
  };

  document.getElementById("research-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = document.getElementById("research-question").value.trim();
    if (!question) return;
    const status = document.getElementById("research-status");
    const button = event.target.querySelector("button[type=submit]");
    status.textContent = "running – a web run may ask for permission";
    button.disabled = true;
    const lines = (id) => document.getElementById(id).value.split("\n").map((line) => line.trim()).filter(Boolean);
    try {
      const result = await api("POST", "/api/research", {
        question,
        mode: document.getElementById("research-mode").value,
        urls: lines("research-urls"),
        subquestions: lines("research-subquestions"),
        use_model: !document.getElementById("research-nomodel").checked,
      });
      status.textContent = "finished · " + result.run.status;
      state.researchId = result.run.id;
      await openResearch(result.run.id);
      invalidateStatus();
    } catch (error) {
      status.textContent = "";
      const panel = clear(document.getElementById("research-detail"));
      panel.append(el("h2", { text: "This run was refused" }));
      report(panel, error);
      await loadResearchList().catch(() => {});
    } finally {
      button.disabled = false;
    }
  });

  // ----------------------------------------------------------------- learning
  async function loadLearningGoals() {
    const list = clear(document.getElementById("learning-goals"));
    const data = await api("GET", "/api/learning?limit=30");
    if (!data.goals.length) {
      list.append(el("li", { class: "list-empty", text: "no goals yet – create one below" }));
      return;
    }
    for (const goal of data.goals) {
      const stats = goal.stats;
      list.append(el("li", {
        class: "list-item" + (goal.id === state.learningId ? " active" : ""),
        onclick: () => openLearning(goal.id),
      }, [
        el("span", { class: "t", text: goal.title }),
        el("span", {
          class: "s",
          text: goal.status + " · " + stats.items + " item(s) · " + stats.due + " due · "
            + (stats.accuracy === null ? "no attempts" : Math.round(stats.accuracy * 100) + "% correct"),
        }),
      ]));
    }
  }

  function learningAnswerForm(goalId, item) {
    const answer = el("textarea", { rows: "3", placeholder: "your answer" });
    const rating = el("select", { class: "sel" }, [
      el("option", { value: "" }, ["self-rating (needed when there is nothing to compare against)"]),
      el("option", { value: "1" }, ["1 – no idea"]),
      el("option", { value: "2" }, ["2 – shaky"]),
      el("option", { value: "3" }, ["3 – mostly right"]),
      el("option", { value: "4" }, ["4 – confident"]),
      el("option", { value: "5" }, ["5 – could teach it"]),
    ]);
    const feedback = el("div", { class: "warnings" });
    const form = el("form", { class: "answer-form" }, [
      el("label", { class: "field" }, [el("span", { text: "Answer" }), answer]),
      el("label", { class: "field" }, [el("span", { text: "How did it go?" }), rating]),
      el("div", { class: "row between" }, [
        el("span", { class: "hint", text: item.graded_by_hint || "graded against the expected answer, or by your rating" }),
        el("button", { class: "btn primary", type: "submit" }, ["Answer"]),
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
        feedback.append(el("div", { class: "feedback" }, [
          el("span", { class: grade.correct ? "ok" : "no", text: (grade.correct ? "correct" : "not yet") + " · graded by " + grade.graded_by }),
          el("span", { class: "why", text: grade.feedback }),
          el("span", { class: "why", text: "next review " + stamp(result.schedule.due_at) + " · " + result.schedule.why }),
          result.explanation ? el("span", { class: "why", text: result.explanation }) : null,
        ]));
        await openLearning(goalId);
        await loadLearningGoals();
      } catch (error) {
        report(feedback, error);
      } finally {
        button.disabled = false;
      }
    });
    return form;
  }

  function learningItemForm(goalId) {
    const note = el("span", { class: "hint" });
    const prompt = el("input", { type: "text", placeholder: "Which journal mode lets readers keep reading?" });
    const expected = el("input", { type: "text", placeholder: "answer Archx can check (leave blank to self-grade)" });
    const hints = el("textarea", { rows: "3", placeholder: "one hint per line, easiest first" });
    const form = el("form", { class: "card" }, [
      el("div", { class: "card-head" }, [el("h3", { text: "Add an item" }), el("p", { class: "hint", text: "The ladder is revealed one rung at a time, and never before an attempt." })]),
      el("label", { class: "field" }, [el("span", { text: "Prompt" }), prompt]),
      el("label", { class: "field" }, [el("span", { text: "Expected answer" }), expected]),
      el("label", { class: "field" }, [el("span", { text: "Hint ladder" }), hints]),
      el("div", { class: "row between" }, [
        el("button", { class: "btn primary", type: "submit" }, ["Add item"]),
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
        note.textContent = "added " + shortId(item.id);
        await openLearning(goalId);
        await loadLearningGoals();
      } catch (error) {
        report(note, error);
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

    panel.append(el("div", { class: "goal-head" }, [
      el("div", {}, [
        el("h2", { text: goal.title }),
        el("div", { class: "goal-meta" }, [
          statusBadge(goal.status),
          el("span", { text: "level " + goal.level }),
          el("span", { text: stats.items + " item(s)" }),
          el("span", { text: stats.due + " due" }),
          el("span", { text: stats.attempts + " attempt(s)" }),
          el("span", { text: stats.accuracy === null ? "nothing graded yet" : Math.round(stats.accuracy * 100) + "% correct" }),
        ]),
      ]),
      el("div", { class: "row" }, [
        el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/plan", { use_model: false })
            .then((result) => {
              toast("Planned", result.items.length + " item(s) by " + result.planned_by, "ok");
              return openLearning(goalId);
            })
            .then(loadLearningGoals)
            .catch((error) => toast("Could not plan items", error.message, "err")),
        }, [svgIcon("plus"), "propose items"]),
        el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => api("POST", "/api/learning/goals/" + encodeURIComponent(goalId) + "/review", {})
            .then(() => openLearning(goalId))
            .catch((error) => toast("Could not start a review", error.message, "err")),
        }, [svgIcon("play"), "start review"]),
      ]),
    ]));

    if (goal.objective) panel.append(el("p", { class: "small dim", text: goal.objective }));
    if ((goal.success_criteria || []).length) {
      panel.append(el("ul", { class: "criteria" }, goal.success_criteria.map((line) => el("li", { text: line }))));
    }

    const next = data.next || {};
    const nextCard = el("div", { class: "next-card" });
    if (next.nothing_to_study) {
      nextCard.append(el("p", { class: "why", text: next.message || "nothing to study right now" }));
    } else {
      const item = next.item;
      const ladder = el("div", { class: "ladder" });
      const hintBox = el("div", { class: "warnings" });
      nextCard.append(el("p", { class: "why", text: next.why + (item.hint_count ? " · " + item.hint_count + " hint(s)" : "") }));
      nextCard.append(el("p", { class: "question", text: item.prompt }));
      if (item.hint_count) {
        nextCard.append(el("div", { class: "row" }, [
          el("button", {
            class: "btn tiny",
            type: "button",
            onclick: async (event) => {
              const button = event.currentTarget;
              button.disabled = true;
              try {
                const result = await api("POST", "/api/learning/items/" + encodeURIComponent(item.id) + "/hint", { level: (item.revealed || 0) + 1 });
                item.revealed = result.level;
                ladder.append(el("div", { class: "rung" }, [
                  el("span", { class: "lvl", text: "hint " + result.level + "/" + result.total }),
                  el("span", { text: result.hint }),
                ]));
                if (result.level >= result.total) button.disabled = true;
              } catch (error) {
                report(hintBox, error);
              } finally {
                button.disabled = false;
              }
            },
          }, ["Reveal a hint"]),
          el("span", { class: "hint", text: "one level at a time" }),
        ]));
      }
      nextCard.append(ladder, hintBox, learningAnswerForm(goalId, item));
    }
    panel.append(nextCard);

    panel.append(el("div", { class: "section-head" }, [
      el("div", {}, [el("h2", { text: "Items and schedule" }), el("p", { text: "the arithmetic this goal is on" })]),
    ]));
    panel.append(table(
      ["item", "status", "due", "streak", "interval", "next review", "prompt"],
      data.items.map((item) => [
        shortId(item.id), statusBadge(item.status), item.due ? "yes" : "no", String(item.streak),
        item.interval_days + "d", stamp(item.due_at), item.prompt,
      ]),
      "no items yet – propose some, or add one below",
    ));

    if ((data.sessions || []).length) {
      panel.append(el("div", { class: "section-head" }, [
        el("div", {}, [el("h2", { text: "Sessions" })]),
      ]));
      panel.append(table(["session", "mode", "status", "answered", "correct", "started"], data.sessions.map((session) => [
        shortId(session.id), session.mode, statusBadge(session.status), String(session.items_attempted),
        String(session.items_correct), stamp(session.started_at),
      ])));
    }

    panel.append(learningItemForm(goalId));
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
      report(document.getElementById("learning-detail"), error);
    }
  });

  // ------------------------------------------------------------------- search
  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("search-query").value.trim();
    if (!query) return;
    const notes = clear(document.getElementById("search-notes"));
    const panel = clear(document.getElementById("search-results"));
    panel.append(el("p", { class: "loading" }, [el("span", { class: "spinner" }), "searching"]));
    try {
      const files = document.getElementById("search-files").checked;
      const data = await api("GET", "/api/search?q=" + encodeURIComponent(query) + "&files=" + (files ? "1" : "0"));
      clear(panel);
      for (const [kind, reason] of Object.entries(data.skipped || {})) {
        notes.append(el("div", { class: "callout warn", text: "skipped " + kind + ": " + reason }));
      }
      for (const reason of data.degraded || []) notes.append(el("div", { class: "callout warn", text: "degraded: " + reason }));
      panel.append(el("p", { class: "small dim", text: data.total + " hit(s) in " + Math.round(data.elapsed_ms) + " ms" }));
      panel.append(table(
        ["kind", "title", "score", "why it matched", "ref"],
        data.hits.map((hit) => [hit.kind, hit.title, hit.score.toFixed(2), hit.snippet, hit.ref]),
        "no hits",
      ));
    } catch (error) {
      report(panel, error);
    }
  });

  // -------------------------------------------------------------------- tasks
  async function loadTasks() {
    const list = clear(document.getElementById("tasks-list"));
    const status = document.getElementById("tasks-status").value;
    const tasks = await api("GET", "/api/tasks?limit=50" + (status ? "&status=" + encodeURIComponent(status) : ""));
    if (!tasks.length) {
      list.append(el("li", { class: "list-empty", text: "no tasks" }));
      return;
    }
    for (const task of tasks) {
      list.append(el("li", {
        class: "list-item" + (task.id === state.taskId ? " active" : ""),
        onclick: () => openTask(task.id),
      }, [
        el("span", { class: "t", text: task.title }),
        el("span", { class: "s", text: task.type + " · " + task.status + " · " + stamp(task.created_at) }),
      ]));
    }
  }

  async function openTask(id) {
    state.taskId = id;
    await loadTasks();
    const panel = clear(document.getElementById("task-detail"));
    const data = await api("GET", "/api/tasks/" + encodeURIComponent(id));
    const task = data.task;
    panel.append(el("div", { class: "goal-head" }, [
      el("div", {}, [
        el("h2", { text: task.title }),
        el("div", { class: "goal-meta" }, [
          statusBadge(task.status),
          el("span", { text: task.type }),
          el("span", { text: shortId(task.id) }),
          el("span", { text: stamp(task.created_at) }),
        ]),
      ]),
    ]));
    panel.append(kv(Object.entries(task)
      .filter(([, value]) => value !== null && value !== "" && typeof value !== "object")
      .map(([key, value]) => [key, String(value)])));
    if (data.timeline.length) {
      panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Timeline" })])]));
      panel.append(table(["#", "kind", "detail", "at"], data.timeline.map((entry, index) => [
        String(index + 1), entry.kind, entry.detail || "", stamp(entry.created_at || entry.at),
      ])));
    }
    if (data.artifacts.length) {
      panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Artifacts" }), el("p", { text: "with the checksum that proves they are the same bytes" })])]));
      panel.append(table(["kind", "path", "sha256"], data.artifacts.map((artifact) => [
        artifact.kind, artifact.path, (artifact.checksum || "").slice(0, 16),
      ])));
    }
    if (data.tools.length) {
      panel.append(el("div", { class: "section-head" }, [el("div", {}, [el("h2", { text: "Tool runs" })])]));
      panel.append(table(["tool", "status", "at"], data.tools.map((tool) => [
        tool.tool_name, statusBadge(tool.status), stamp(tool.started_at),
      ])));
    }
  }

  loaders.tasks = async () => {
    await loadTasks();
    if (state.taskId) await openTask(state.taskId);
  };

  document.getElementById("tasks-refresh").addEventListener("click", () => {
    loaders.tasks().catch((error) => report(document.getElementById("task-detail"), error));
  });

  document.getElementById("tasks-status").addEventListener("change", () => {
    loadTasks().catch((error) => toast("Could not filter tasks", error.message, "err"));
  });

  // --------------------------------------------------------------------- jobs
  const JOB_ACTIONS = [
    ["pause", "pause", "pause"],
    ["resume", "play", "resume"],
    ["retry", "retry", "retry"],
    ["cancel", "stop", "cancel"],
  ];

  loaders.jobs = async () => {
    const data = await api("GET", "/api/jobs?limit=40");
    const cards = clear(document.getElementById("jobs-stats"));
    for (const [key, value] of Object.entries(data.stats || {})) {
      cards.append(stat(value, key.replace(/_/g, " ")));
    }
    const panel = clear(document.getElementById("jobs-list"));
    const rows = data.jobs.map((job) => {
      const actions = el("div", { class: "job-actions" }, JOB_ACTIONS.map(([action, icon, label]) => el("button", {
        class: "btn tiny" + (action === "cancel" ? " danger" : ""),
        type: "button",
        title: label + " this job",
        onclick: async () => {
          if (action === "cancel") {
            const sure = await ask({
              title: "Cancel this job?",
              text: job.title + " will stop at the next safe point and the job becomes terminal.",
              okLabel: "Cancel the job",
            });
            if (!sure) return;
          }
          try {
            await api("POST", "/api/jobs/" + encodeURIComponent(job.id) + "/" + action, {});
            await loaders.jobs();
            invalidateStatus();
          } catch (error) {
            toast("Could not " + action + " the job", error.message, "err");
          }
        },
      }, [svgIcon(icon), label])));
      return [shortId(job.id), job.kind, statusBadge(job.status), job.title, job.priority, actions];
    });
    panel.append(table(["id", "kind", "status", "title", "prio", "actions"], rows, "the queue is empty"));
  };

  document.getElementById("jobs-refresh").addEventListener("click", () => {
    loaders.jobs().catch((error) => report(document.getElementById("jobs-list"), error));
  });

  document.getElementById("jobs-run").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api("POST", "/api/jobs/drain", { max_jobs: 1 });
      if (!result.ran.length) toast("Nothing queued", "there was no claimable job to run");
      else toast("Ran a job", result.ran[0].title || result.ran[0].id, "ok");
      await loaders.jobs();
      invalidateStatus();
    } catch (error) {
      toast("Could not run a job", error.message, "err");
    } finally {
      button.disabled = false;
    }
  });

  // ------------------------------------------------------------------- access
  loaders.access = async () => {
    const approvals = await api("GET", "/api/approvals?status=pending");
    const list = clear(document.getElementById("approvals-list"));
    if (!approvals.length) {
      list.append(el("p", { class: "muted-box", text: "no pending approvals" }));
    } else {
      list.append(table(["id", "capability", "subject", "scope", "why", "decide"], approvals.map((approval) => [
        shortId(approval.id), approval.capability, approval.subject, approval.scope, approval.reason,
        el("div", { class: "row" }, [
          el("button", {
            class: "btn tiny primary",
            type: "button",
            onclick: async () => {
              try {
                await api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/approve", {});
                toast("Approved", approval.capability + " for " + approval.subject, "ok");
                await loaders.access();
                invalidateStatus();
              } catch (error) { toast("Could not approve", error.message, "err"); }
            },
          }, ["approve"]),
          el("button", {
            class: "btn tiny danger",
            type: "button",
            onclick: async () => {
              const sure = await ask({
                title: "Deny this request?",
                text: approval.capability + " for " + approval.subject + " will not be granted. The request stays in the record as denied.",
                okLabel: "Deny",
              });
              if (!sure) return;
              try {
                await api("POST", "/api/approvals/" + encodeURIComponent(approval.id) + "/deny", {});
                toast("Denied", approval.capability + " was not granted", "warn");
                await loaders.access();
                invalidateStatus();
              } catch (error) { toast("Could not deny", error.message, "err"); }
            },
          }, ["deny"]),
        ]),
      ])));
    }

    const permissions = await api("GET", "/api/permissions?active_only=1");
    const grants = clear(document.getElementById("grants-list"));
    if (!permissions.grants.length) {
      grants.append(el("p", { class: "muted-box", text: "no active grants – nothing can touch your files, run a program or fetch the web" }));
    } else {
      grants.append(table(["id", "capability", "subject", "scope", "expires", ""], permissions.grants.map((grant) => [
        shortId(grant.id), grant.capability, grant.subject, grant.scope, grant.expires_at ? stamp(grant.expires_at) : "no expiry",
        el("button", {
          class: "btn tiny danger",
          type: "button",
          onclick: async () => {
            const sure = await ask({
              title: "Revoke this grant?",
              text: grant.capability + " for " + grant.subject + " stops working immediately. Anything mid-flight that needed it will fail and say so.",
              okLabel: "Revoke",
            });
            if (!sure) return;
            try {
              await api("POST", "/api/permissions/" + encodeURIComponent(grant.id) + "/revoke", {});
              toast("Revoked", grant.capability + " for " + grant.subject, "ok");
              await loaders.access();
              invalidateStatus();
            } catch (error) { toast("Could not revoke", error.message, "err"); }
          },
        }, ["revoke"]),
      ])));
    }

    const caps = clear(document.getElementById("capabilities-list"));
    caps.append(table(["capability", "risk", "effect", "what it allows"], permissions.capabilities.map((cap) => [
      cap.name, badge(cap.risk, cap.risk === "high" ? "bad" : cap.risk === "medium" ? "warn" : ""), cap.effect, cap.description,
    ])));
  };

  document.getElementById("access-refresh").addEventListener("click", () => {
    loaders.access().catch((error) => report(document.getElementById("grants-list"), error));
  });

  // ------------------------------------------------------------------- memory
  async function loadMemory() {
    const items = await api("GET", "/api/memory?limit=60");
    const panel = clear(document.getElementById("memory-list"));
    panel.append(table(
      ["kind", "title", "content", "category", "scope", "status"],
      items.map((item) => [
        badge(item.kind, "accent"), item.title, (item.content || "").slice(0, 140),
        item.category || "–", item.scope, item.status,
      ]),
      "no memories yet",
    ));
  }

  loaders.memory = loadMemory;
  document.getElementById("memory-refresh").addEventListener("click", () => {
    loadMemory().catch((error) => report(document.getElementById("memory-list"), error));
  });

  document.getElementById("memory-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("memory-status");
    status.textContent = "";
    try {
      const stored = await api("POST", "/api/memory", {
        kind: document.getElementById("memory-kind").value,
        title: document.getElementById("memory-title").value,
        content: document.getElementById("memory-content").value,
        category: document.getElementById("memory-category").value || null,
      });
      document.getElementById("memory-title").value = "";
      document.getElementById("memory-content").value = "";
      status.textContent = "stored " + shortId(stored.id);
      toast("Memory stored", shortId(stored.id), "ok");
      await loadMemory();
      invalidateStatus();
    } catch (error) {
      status.textContent = "";
      report(document.getElementById("memory-list"), error);
    }
  });

  // ------------------------------------------------------------------- models
  /* The consent ladder is not decoration: each rung posts the same call the CLI makes, and
   * the next render reads the answer back from the server. Nothing here flips a flag locally. */
  const GATE_ACTIONS = {
    consent_policy: {
      label: "Allow cloud routing",
      run: (model) => api("POST", "/api/settings/model.local_only", { value: false }),
      done: "Cloud routing allowed. This home may now talk to the endpoints you registered.",
    },
    provider: {
      label: "Register the provider",
      run: (model) => api("POST", "/api/models/" + encodeURIComponent(model.id) + "/provider", {}),
      done: "Provider registered. Its privacy terms still need your answer.",
    },
    privacy: {
      label: "Confirm what leaves the device",
      // A provider's terms are the user's to state; guessing them here would be a fake answer.
      run: (model) => api("POST", "/api/providers/" + encodeURIComponent(model.provider_id) + "/privacy", {
        data_leaves_device: true,
        training_use: "unknown",
        retention: "unknown",
      }),
      done: "Recorded: prompts leave this device and the provider's training use is unknown.",
    },
    consent: {
      label: "Record consent",
      run: (model) => api("POST", "/api/providers/" + encodeURIComponent(model.provider_id) + "/consent",
        { note: "consent recorded in the GUI" }),
      done: "Consent recorded, with a timestamp.",
    },
  };

  function gateRow(model, gate) {
    const action = GATE_ACTIONS[gate.key];
    // privacy and consent belong to a provider row; without one there is nothing to POST to
    const needsProvider = gate.key === "privacy" || gate.key === "consent";
    const blocked = needsProvider && !model.provider_id;
    const control = gate.ok || !action || blocked ? null : el("button", {
      class: "btn tiny",
      type: "button",
      onclick: async (event) => {
        if (gate.key === "privacy") {
          const sure = await ask({
            title: "Send prompts to " + (model.provider || "this provider") + "?",
            text: "Confirming this records that prompts and replies leave this machine and that the provider's training use is unknown. Only say yes if that is what you want.",
            okLabel: "Yes, data leaves this device",
          });
          if (!sure) return;
        }
        const button = event.currentTarget;
        button.disabled = true;
        try {
          await action.run(model);
          toast("Done", action.done, "ok");
          await loaders.models();
          invalidateStatus();
        } catch (error) {
          button.disabled = false;
          toast("Refused", error.message, "err");
        }
      },
    }, [action.label]);
    return el("div", { class: "rung" + (gate.ok ? " rung-ok" : "") }, [
      el("span", { class: "rung-dot", "aria-hidden": "true" }),
      el("div", { class: "rung-body" }, [
        el("div", { class: "rung-label", text: gate.label }),
        el("div", { class: "rung-detail", text: gate.detail }),
      ]),
      control,
    ]);
  }

  function modelCard(model) {
    const caps = (model.capabilities || []).map((cap) => el("span", { class: "tag", text: cap }));
    return el("div", { class: "card model-card" }, [
      el("div", { class: "row between" }, [
        el("div", {}, [
          el("div", { class: "model-name", text: model.name || model.id }),
          el("span", { class: "model-backend", text: (model.provider || "?") + " · " + model.runtime }),
        ]),
        el("div", { class: "row" }, [
          model.ready ? badge("ready", "ok") : badge("blocked", "bad"),
          el("button", {
            class: "btn tiny",
            type: "button",
            title: "Send one small prompt and record the measurement",
            onclick: async (event) => {
              const button = event.currentTarget;
              button.disabled = true;
              button.textContent = "testing…";
              try {
                const probe = await api("POST", "/api/models/" + encodeURIComponent(model.id) + "/probe",
                  { capability: "chat" });
                const result = probe.result || {};
                if (result.outcome === "passed") {
                  toast("Probe passed", result.detail, "ok");
                } else {
                  toast("Probe failed", result.detail || "the model did not answer", "err");
                }
                await loaders.models();
              } catch (error) {
                toast("Probe failed", error.message, "err");
              } finally {
                button.disabled = false;
                button.textContent = "test chat";
              }
            },
          }, ["test chat"]),
        ]),
      ]),
      el("p", { class: "ready-reason", text: model.ready_reason }),
      caps.length ? el("div", { class: "row caps" }, caps) : null,
      el("div", { class: "rungs" }, (model.gates || []).map((gate) => gateRow(model, gate))),
    ]);
  }

  loaders.models = async () => {
    const models = await api("GET", "/api/models");
    const panel = clear(document.getElementById("models-list"));
    if (!models.length) {
      panel.append(el("p", { class: "muted-box", text: "No model is registered yet. Connect Gemini above, or add a local endpoint with `archx-agent models add-http`." }));
      return;
    }
    for (const model of models) panel.append(modelCard(model));
  };

  document.getElementById("models-refresh").addEventListener("click", () => {
    loaders.models().catch((error) => report(document.getElementById("models-list"), error));
  });

  document.getElementById("models-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("models-status");
    const button = event.target.querySelector("button[type=submit]");
    status.textContent = "registering…";
    button.disabled = true;
    try {
      const created = await api("POST", "/api/models", {
        name: document.getElementById("models-name").value,
        model: document.getElementById("models-model").value,
        credential_ref: document.getElementById("models-credential").value,
        base_url: document.getElementById("models-base").value,
      });
      document.getElementById("models-credential").value = "";
      status.textContent = created.ready ? "ready: " + created.ready_reason : created.ready_reason;
      toast("Model registered", created.name + " · " + created.runtime, "ok");
      await loaders.models();
      invalidateStatus();
    } catch (error) {
      status.textContent = "";
      toast("Could not register", error.message, "err");
    } finally {
      button.disabled = false;
    }
  });

  // -------------------------------------------------------- chrome (theme, rail)
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const order = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    document.getElementById("theme-toggle").setAttribute("title", "Theme: " + theme + " (switch to " + order + ")");
    document.getElementById("theme-toggle").setAttribute("aria-label", "Theme: " + theme + ", switch to " + order);
    remember(THEME_KEY, theme);
  }

  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(THEMES.includes(recall(THEME_KEY)) ? recall(THEME_KEY) : (prefersLight ? "light" : "dark"));

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "dark";
    applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
  });

  if (recall(RAIL_KEY) === "compact") appShell.classList.add("compact");
  document.getElementById("rail-toggle").addEventListener("click", () => {
    appShell.classList.toggle("compact");
    const compact = appShell.classList.contains("compact");
    remember(RAIL_KEY, compact ? "compact" : "full");
    document.getElementById("rail-toggle").setAttribute("title", compact ? "Expand the sidebar" : "Collapse the sidebar");
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") settleModal(false);
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
