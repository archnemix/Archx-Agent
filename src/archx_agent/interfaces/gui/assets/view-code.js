/* code view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // --------------------------------------------------------------------- code
  // A session is a directory, and this panel is deliberately a small editor and a console -
  // not an IDE. Everything it does is one API call the CLI can also make, so nothing here is
  // a capability the app does not otherwise have.
  async function loadCodeSessions() {
    const list = shared.clear(document.getElementById("code-sessions"));
    const data = await shared.api("GET", "/api/code/sessions");
    shared.state.code = shared.state.code || {};
    if (!data.sessions.length) {
      list.append(shared.el("li", { class: "dim small", text: "no sessions yet" }));
    }
    for (const session of data.sessions) {
      const stats = session.stats || {};
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.code.id === session.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: session.title }),
        shared.el("span", {
          class: "s",
          text: session.status + " · " + stats.changes + " edit(s) · " + stats.runs + " run(s)",
        }),
      ]);
      button.addEventListener("click", () => openCode(session.id).catch((error) => shared.report(document.getElementById("code-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return data;
  }

  function codeToolbar(session) {
    const card = shared.el("div", { class: "card" });
    card.append(shared.el("div", { class: "card-head" }, [
      shared.el("h3", { text: "The runner" }),
      shared.el("p", { class: "hint", text: "A command runs in the session root. It needs shell.run; a refusal names the approval and starts nothing." }),
    ]));

    const commandInput = shared.el("input", { id: "code-command", type: "text", placeholder: "python -m pytest -q" });
    const runButton = shared.el("button", { type: "button", class: "btn primary", text: "Run" });
    const testButton = shared.el("button", { type: "button", class: "btn", text: "Run the test check" });
    const output = shared.el("pre", { id: "code-output", class: "code-output" });
    card.append(shared.el("label", { class: "field" }, ["Command", commandInput]));
    card.append(shared.el("div", { class: "row between" }, [runButton, testButton]));

    async function execute(promise) {
      shared.clear(output);
      output.append(shared.el("span", { class: "loading", text: "running…" }));
      try {
        const run = await promise;
        shared.clear(output);
        const head = shared.el("div", { class: "callout " + (run.status === "passed" ? "ok" : "warn") }, [
          shared.el("b", { text: run.status }),
          " exit " + run.exit_code + " in " + Math.round(run.duration_ms || 0) + " ms",
          run.check_name ? " · check " + run.check_name : "",
        ]);
        output.append(head);
        if (run.stdout) output.append(shared.el("div", { class: "mono", text: run.stdout }));
        if (run.stderr) output.append(shared.el("div", { class: "mono warn-text", text: run.stderr }));
        if (run.artifact_id) output.append(shared.el("div", { class: "small dim", text: "output kept as " + run.artifact_id }));
        await openCode(session.id);
        const again = document.getElementById("code-output");
        if (again) { shared.clear(again); again.append(head); }
      } catch (error) {
        shared.clear(output);
        shared.report(output, error);
      }
    }

    runButton.addEventListener("click", () => {
      const command = commandInput.value.trim();
      if (!command) return;
      execute(shared.api("POST", "/api/code/sessions/" + session.id + "/run", { command }));
    });
    testButton.addEventListener("click", () => {
      execute(shared.api("POST", "/api/code/sessions/" + session.id + "/test", { check: "test" }));
    });
    return card;
  }

  function codeEditor(session) {
    const card = shared.el("div", { class: "card" });
    card.append(shared.el("div", { class: "card-head" }, [
      shared.el("h3", { text: "The editor" }),
      shared.el("p", { class: "hint", text: "Reading needs fs.read and saving needs fs.write. A save records a diff and attaches it to this session's task." }),
    ]));
    const pathInput = shared.el("input", { id: "code-path", type: "text", placeholder: "hello.py" });
    const textarea = shared.el("textarea", { id: "code-file", class: "code-editor", spellcheck: "false", rows: "10" });
    const readButton = shared.el("button", { type: "button", class: "btn", text: "Read" });
    const saveButton = shared.el("button", { type: "button", class: "btn primary", text: "Save" });
    const deleteButton = shared.el("button", { type: "button", class: "btn danger", text: "Delete" });
    const note = shared.el("span", { class: "hint" });

    card.append(shared.el("label", { class: "field" }, ["Path", pathInput]));
    card.append(textarea);
    card.append(shared.el("div", { class: "row between" }, [readButton, saveButton, deleteButton, note]));

    readButton.addEventListener("click", async () => {
      const path = pathInput.value.trim();
      if (!path) return;
      try {
        const file = await shared.api("GET", "/api/code/sessions/" + session.id + "/file?path=" + encodeURIComponent(path));
        textarea.value = file.content || "";
        note.textContent = file.truncated ? "truncated at the tool limit" : (file.total_lines + " line(s)");
      } catch (error) {
        shared.report(note, error);
      }
    });
    saveButton.addEventListener("click", async () => {
      const path = pathInput.value.trim();
      if (!path) return;
      try {
        const change = await shared.api("POST", "/api/code/sessions/" + session.id + "/write", { path, content: textarea.value });
        note.textContent = change.action + " " + change.path + " +" + change.added + "/-" + change.removed;
        await openCode(session.id);
      } catch (error) {
        shared.report(note, error);
      }
    });
    deleteButton.addEventListener("click", async () => {
      const path = pathInput.value.trim();
      if (!path) return;
      const sure = await shared.ask({
        title: "Delete " + path + "?",
        text: "The diff stays in the session record; the file does not come back.",
        okLabel: "Delete",
      });
      if (!sure) return;
      try {
        await shared.api("POST", "/api/code/sessions/" + session.id + "/delete", { path });
        textarea.value = "";
        await openCode(session.id);
      } catch (error) {
        shared.report(note, error);
      }
    });
    return card;
  }

  async function openCode(sessionId) {
    const panel = shared.clear(document.getElementById("code-detail"));
    shared.state.code = shared.state.code || {};
    shared.state.code.id = sessionId;
    const shown = await shared.api("GET", "/api/code/sessions/" + sessionId);
    const session = shown.session;
    const stats = shown.stats || {};

    const diffButton = shared.el("button", { type: "button", class: "btn", text: "Diff" });
    diffButton.addEventListener("click", async () => {
      try {
        const patch = await shared.api("GET", "/api/code/sessions/" + sessionId + "/diff");
        const box = document.getElementById("code-patch");
        box.textContent = patch.patch || "this session made no changes";
      } catch (error) {
        shared.report(panel, error);
      }
    });
    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: session.title }),
      shared.el("div", { class: "row" }, [shared.statusBadge(session.status), diffButton]),
    ]));

    panel.append(shared.el("p", { class: "small dim", text: session.root + " · task " + (session.task_id || "-") }));
    panel.append(shared.el("div", { class: "row" }, [
      shared.toolChip("edits", stats.changes + " (+" + stats.added + "/-" + stats.removed + ")"),
      shared.toolChip("runs", String(stats.runs) + (stats.failed ? " · " + stats.failed + " not passed" : "")),
      shared.toolChip("checks", "archx.checks.json"),
    ]));

    panel.append(codeEditor(session));
    panel.append(codeToolbar(session));
    panel.append(shared.el("pre", { id: "code-patch", class: "code-output dim", text: "press Diff for the session's whole patch" }));

    if (shown.changes.length) {
      panel.append(shared.el("div", {}, [shared.el("h3", { text: "Edits" })]));
      panel.append(shared.table(["action", "path", "lines", "when", "artifact"], shown.changes.map((change) => [
        change.action, change.path, "+" + change.added + "/-" + change.removed,
        shared.stamp(change.created_at), change.artifact_id ? shared.shortId(change.artifact_id) : "-",
      ])));
    }
    if (shown.runs.length) {
      panel.append(shared.el("div", {}, [shared.el("h3", { text: "The ledger" })]));
      panel.append(shared.table(["command", "status", "exit", "ms", "when"], shown.runs.map((run) => [
        (run.check_name ? "[" + run.check_name + "] " : "") + run.command,
        shared.statusBadge(run.status), shared.text(run.exit_code), shared.text(Math.round(run.duration_ms || 0)),
        shared.stamp(run.created_at),
      ])));
    }
    if (!session.open) {
      panel.append(shared.el("div", { class: "callout warn", text: "This session is closed. The record stays readable; open a new one to keep working." }));
    } else {
      const closeButton = shared.el("button", { type: "button", class: "btn", text: "Close session" });
      closeButton.addEventListener("click", async () => {
        try {
          await shared.api("POST", "/api/code/sessions/" + sessionId + "/close", {});
          await loadCodeSessions();
          await openCode(sessionId);
        } catch (error) {
          shared.report(panel, error);
        }
      });
      panel.append(shared.el("div", { class: "row" }, [closeButton]));
    }
    await loadCodeSessions();
  }

  shared.loaders.code = async () => {
    await loadCodeSessions();
    if (shared.state.code && shared.state.code.id) await openCode(shared.state.code.id);
  };

  document.getElementById("code-refresh").addEventListener("click", () => {
    shared.loaders.code().catch((error) => shared.report(document.getElementById("code-detail"), error));
  });

  document.getElementById("code-open-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("code-open-status");
    status.textContent = "";
    try {
      const session = await shared.api("POST", "/api/code/sessions", {
        root: document.getElementById("code-root").value.trim() || null,
        title: document.getElementById("code-title").value.trim() || null,
      });
      document.getElementById("code-title").value = "";
      await openCode(session.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
