/* chat view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // --------------------------------------------------------------------- chat
  const log = () => document.getElementById("chat-log");
  const chatInput = () => document.getElementById("chat-input");
  let navigationVersion = 0;

  function nearBottom(box) { return box.scrollHeight - box.scrollTop - box.clientHeight < 160; }

  function scrollDown(box, force) {
    if (force || nearBottom(box)) box.scrollTop = box.scrollHeight;
  }

  function avatarFor(role) {
    return shared.el("div", { class: "avatar", "aria-hidden": "true", text: role === "user" ? "YOU" : "AX" });
  }

  /* One transcript row: avatar, role, body, and actions that appear on hover or focus. */
  function addMessage(role, content, meta) {
    const box = log();
    const plain = typeof content === "string" ? content : null;
    const contentNode = shared.el("div", { class: "msg-content" });
    if (plain === null) contentNode.append(content);
    else contentNode.append(...shared.renderMarkdown(plain));

    const actions = shared.el("div", { class: "msg-actions" }, [
      shared.iconButton("copy", "Copy this message", () => shared.copyText(
        contentNode.textContent,
        "message copied",
      )),
    ]);

    const row = shared.el("div", { class: "msg-row" }, [
      shared.el("div", { class: "msg " + role }, [
        avatarFor(role),
        shared.el("div", { class: "msg-body" }, [
          shared.el("div", { class: "msg-head" }, [
            shared.el("span", { class: "msg-role", text: role === "user" ? "You" : "Archx" }),
            meta ? shared.el("span", { class: "msg-meta", text: meta }) : null,
          ]),
          contentNode,
          actions,
        ]),
      ]),
    ]);
    box.append(row);
    scrollDown(box, false);
    return { row, content: contentNode, actions, body: row.querySelector(".msg-body") };
  }

  function setReasoning(node, text, streaming = false) {
    let details = node.body.querySelector(".model-reasoning");
    if (!text) { if (details) details.remove(); return; }
    if (!details) {
      details = shared.el("details", { class: "model-reasoning" }, [
        shared.el("summary"), shared.el("pre", { class: "reasoning-text" }),
      ]);
      node.body.insertBefore(details, node.content);
    }
    details.querySelector("summary").textContent = streaming ? "Thinking · model output" : "Model thinking";
    // Provider text is data, never executable HTML; don't disclose invented reasoning.
    details.querySelector("pre").textContent = text;
  }

  function chatWelcome() {
    const box = shared.clear(log());
    const prompts = [
      ["Explain sqlite locking", "Explain how sqlite locking works, and when a writer blocks a reader."],
      ["Compare two approaches", "Compare SQLite and PostgreSQL for a small local-first application."],
      ["Help me plan", "Help me break a large project into practical, testable steps."],
      ["Draft a checklist", "Draft a checklist for releasing a local-first CLI, with the checks I would have to run."],
    ];
    box.append(shared.el("div", { class: "empty" }, [
      shared.el("div", { class: "empty-mark", text: "AX" }),
      shared.el("h2", { text: "What should we work on?" }),
      shared.el("p", { text: "Ask a question, explore an idea, or work through a problem. Choose your model above." }),
      shared.el("div", { class: "chips" }, prompts.map(([label, prompt]) => shared.el("button", {
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
    const list = shared.clear(document.getElementById("chat-conversations"));
    const items = await shared.api("GET", "/api/conversations?limit=40");
    if (!items.length) {
      list.append(shared.el("li", { class: "list-empty", text: "no conversations yet" }));
      return;
    }
    for (const record of items) {
      list.append(shared.el("li", {
        class: "list-item" + (record.id === shared.state.conversationId ? " active" : ""),
        tabindex: "0", role: "button",
        onkeydown: event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.currentTarget.click(); } },
        onclick: () => openConversation(record.id).catch(error => shared.toast("Could not open conversation", error.message, "err")),
      }, [
        shared.el("span", { class: "t", text: record.title || "(untitled)" }),
        shared.el("span", { class: "s", text: shared.stamp(record.updated_at) }),
      ]));
    }
  }

  async function openConversation(id) {
    if (submitting) return;
    if (shared.state.view !== "chat") {
      shared.state.conversationId = id;
      document.querySelector('[data-view="chat"]').click();
      return;
    }
    const version = ++navigationVersion;
    const data = await shared.api("GET", "/api/conversations/" + encodeURIComponent(id) + "/messages");
    if (version !== navigationVersion || submitting) return;
    shared.state.conversationId = id;
    shared.state.chatModelId = data.model_id || null;
    if (data.model_id) document.getElementById("chat-model").value = data.model_id;
    shared.clear(log());
    document.getElementById("chat-diagnostics").hidden = true;
    document.getElementById("app").classList.remove("sidebar-open");
    if (shared.state.view !== "chat") document.querySelector('[data-view="chat"]').click();
    if (!data.messages.length) chatWelcome();
    for (const message of data.messages) {
      const role = message.role === "user" ? "user" : "assistant";
      const node = addMessage(role, message.content, shared.stamp(message.created_at));
      if (role === "assistant") setReasoning(node, message.reasoning);
    }
    scrollDown(log(), true);
    await loadConversations();
  }

  async function loadModelBadge() {
    const models = await shared.api("GET", "/api/models");
    const node = shared.clear(document.getElementById("chat-model"));
    node.append(shared.el("option", { value: "", text: "Automatic routing" }));
    for (const model of models) node.append(shared.el("option", {
      value: model.id, disabled: !model.ready,
      text: (model.name || model.id) + (model.simulated ? " · simulated" : "") + (!model.ready ? " · unavailable" : ""),
    }));
    node.value = shared.state.chatModelId || "";
    document.getElementById("chat-routing-status").textContent = models.some(model => model.ready)
      ? "Enter to send · Shift+Enter for a new line"
      : "No usable model. Open Models to configure one.";
  }
  document.getElementById("chat-model").addEventListener("change", event => {
    shared.state.chatModelId = event.target.value || null;
  });

  shared.loaders.chat = async () => {
    if (submitting) return;
    await loadConversations();
    if (shared.state.conversationId) await openConversation(shared.state.conversationId);
    else if (!log().childElementCount) chatWelcome();
    await loadModelBadge();
  };

  document.getElementById("chat-conv-refresh").addEventListener("click", () => {
    loadConversations().catch((error) => shared.toast("Could not list conversations", error.message, "err"));
  });

  document.getElementById("chat-new").addEventListener("click", () => {
    if (submitting) return;
    navigationVersion++;
    shared.state.conversationId = null;
    document.getElementById("chat-diagnostics").hidden = true;
    if (shared.state.view !== "chat") document.querySelector('[data-view="chat"]').click();
    document.getElementById("app").classList.remove("sidebar-open");
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

  let submitting = false;
  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    const input = chatInput();
    const message = input.value.trim();
    if (!message) return;
    submitting = true;
    navigationVersion++;
    const warnings = shared.clear(document.getElementById("chat-warnings"));
    const diagnostics = document.getElementById("chat-diagnostics");
    diagnostics.hidden = true;
    diagnostics.open = false;
    if (log().querySelector(".empty")) shared.clear(log());
    addMessage("user", message, "now");
    input.value = "";
    autogrow();
    const button = chatForm.querySelector("button[type=submit]");
    button.disabled = true;
    shared.setConn("busy", "generating");
    document.getElementById("chat-model").disabled = true;
    document.getElementById("chat-new").disabled = true;
    const pending = addMessage("assistant", "Waiting for the model…", "generating").row;
    // the reply is painted as it arrives; `node` is created on the first chunk
    let node = null;
    let streamed = "";
    let reasoning = "";
    const ensureNode = () => {
      if (!node) { pending.remove(); node = addMessage("assistant", "", "generating…"); }
      return node;
    };
    const paintReasoning = piece => {
      reasoning += piece;
      setReasoning(ensureNode(), reasoning, true);
      scrollDown(log(), false);
    };
    const paint = (piece) => {
      streamed += piece;
      if (!node) {
        pending.remove();
        node = addMessage("assistant", streamed, "streaming…");
      } else {
        shared.clear(node.content);
        node.content.append(...shared.renderMarkdown(streamed));
        scrollDown(log(), false);
      }
    };
    try {
      const reply = await shared.chatStream(message, shared.state.conversationId, paint, paintReasoning, shared.state.chatModelId);
      if (!reply) {
        throw new Error("Stream ended without a final result. The turn may already be stored. Refresh conversation history before retrying; the message was not resent.");
      }
      shared.state.conversationId = reply.conversation_id;
      const actualModel = reply.model && (reply.model.model_id || reply.model.id);
      if (actualModel) {
        shared.state.chatModelId = actualModel;
        document.getElementById("chat-model").value = actualModel;
      }
      pending.remove();
      const model = reply.model && (reply.model.name || reply.model.model_id);
      const meta = [
        reply.simulated ? "simulated" : null,
        model,
        reply.completion_tokens + " tokens",
        Math.round(reply.latency_ms) + " ms",
        reply.task ? "task " + shared.shortId(reply.task.id) : null,
      ].filter(Boolean).join(" · ");
      if (node) {
        // replace the streamed copy with the recorded reply, so the page shows what was stored
        shared.clear(node.content);
        node.content.append(...shared.renderMarkdown(reply.text));
        const head = node.row.querySelector(".msg-head");
        const stampNode = head && head.querySelector(".msg-meta");
        if (stampNode) stampNode.textContent = meta;
        else if (head) head.append(shared.el("span", { class: "msg-meta", text: meta }));
      } else {
        node = addMessage("assistant", reply.text, meta);
      }
      setReasoning(node, reply.reasoning || "");
      for (const warning of reply.warnings || []) {
        warnings.append(shared.el("div", { class: "diagnostic-note", text: warning }));
      }
      diagnostics.hidden = !warnings.childElementCount;
      shared.setConn("ok", "connected");
      await loadConversations();
      shared.invalidateStatus();
    } catch (error) {
      pending.remove();
      if (node) {
        const stamp = node.row.querySelector(".msg-meta");
        if (stamp) stamp.textContent = "incomplete — refresh history";
        node.content.append(shared.el("div", { class: "callout warn", text: "Completion is unconfirmed. No automatic retry was sent. Refresh history before retrying." }));
      }
      loadConversations().catch(() => {});
      shared.setConn("bad", "unconfirmed");
      const errorNode = addMessage("assistant", "", null);
      errorNode.content.append(shared.el("div", { class: "callout danger" }, [
        shared.el("strong", { text: error.message }),
        error.code ? shared.el("div", { class: "small", text: "code: " + error.code }) : null,
        error.code === "permission_denied" || error.code === "approval_required"
          ? shared.el("div", { class: "small", text: "Decide it in Access, or run `archx-agent approvals`." })
          : null,
      ]));
    } finally {
      submitting = false;
      button.disabled = false;
      document.getElementById("chat-model").disabled = false;
      document.getElementById("chat-new").disabled = false;
    }
  });

});
