/* Shared DOM, storage, dialogs and Markdown rendering. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
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

  Object.defineProperty(shared, "remember", { get: () => remember });
  Object.defineProperty(shared, "recall", { get: () => recall });
  Object.defineProperty(shared, "el", { get: () => el });
  Object.defineProperty(shared, "clear", { get: () => clear });
  Object.defineProperty(shared, "text", { get: () => text });
  Object.defineProperty(shared, "svgIcon", { get: () => svgIcon });
  Object.defineProperty(shared, "iconButton", { get: () => iconButton });
  Object.defineProperty(shared, "badge", { get: () => badge });
  Object.defineProperty(shared, "statusBadge", { get: () => statusBadge });
  Object.defineProperty(shared, "table", { get: () => table });
  Object.defineProperty(shared, "kv", { get: () => kv });
  Object.defineProperty(shared, "stat", { get: () => stat });
  Object.defineProperty(shared, "shortId", { get: () => shortId });
  Object.defineProperty(shared, "stamp", { get: () => stamp });
  Object.defineProperty(shared, "toast", { get: () => toast });
  Object.defineProperty(shared, "ask", { get: () => ask });
  Object.defineProperty(shared, "settleModal", { get: () => settleModal });
  Object.defineProperty(shared, "copyText", { get: () => copyText });
  Object.defineProperty(shared, "downloadText", { get: () => downloadText });
  Object.defineProperty(shared, "renderMarkdown", { get: () => renderMarkdown });
});
