/* exec view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- exec
  // Two claims on this page: every row says *where* the command ran, and every backend this machine
  // cannot use is listed with the reason instead of being hidden from the picker.
  async function loadExec() {
    shared.state.exec = shared.state.exec || {};
    const payload = await shared.api("GET", "/api/exec/targets");
    const stats = payload.stats || {};
    const summary = shared.clear(document.getElementById("exec-stats"));
    summary.append(shared.el("p", { class: "small", text: (stats.targets || 0) + " target(s) · " + (stats.runs || 0) + " run(s) · " + (stats.files || 0) + " file(s) · " + (stats.conflicts || 0) + " conflict(s)" }));
    summary.append(shared.el("p", { class: "small dim", text: (stats.enabled ? "execution is on" : "execution is off") + " · default " + (stats.default_target || "local") }));

    const select = document.getElementById("exec-target");
    const current = select.value;
    shared.clear(select);
    const usable = [];
    for (const target of payload.targets) usable.push({ value: target.name, label: target.name + " (" + target.kind + ")" });
    if (!usable.length) usable.push({ value: "local", label: "local (this machine)" });
    for (const option of usable) {
      const node = shared.el("option", { value: option.value, text: option.label });
      select.append(node);
    }
    if (current) select.value = current;

    const probes = shared.clear(document.getElementById("exec-probes"));
    for (const probe of payload.probes) {
      const row = shared.el("p", { class: "small" + (probe.available ? "" : " dim") }, [
        shared.el("strong", { text: probe.kind + ": " }),
        document.createTextNode(probe.available ? "available" : "not here - " + (probe.why_not || []).join("; ")),
      ]);
      probes.append(row);
    }

    const runs = await shared.api("GET", "/api/exec/runs");
    const list = shared.clear(document.getElementById("exec-runs"));
    if (!runs.runs.length) list.append(shared.el("li", { class: "dim small", text: "nothing has run yet" }));
    for (const run of runs.runs) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.exec.id === run.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: run.command.slice(0, 40) }),
        shared.el("span", { class: "s", text: run.kind + " · " + run.status + " · exit " + run.exit_code }),
      ]);
      button.addEventListener("click", () => openExecRun(run.id).catch((error) => shared.report(document.getElementById("exec-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return payload;
  }

  async function openExecRun(runId) {
    const panel = shared.clear(document.getElementById("exec-detail"));
    shared.state.exec = shared.state.exec || {};
    shared.state.exec.id = runId;
    const run = await shared.api("GET", "/api/exec/runs/" + runId);
    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: run.kind + " · " + shared.shortId(run.id) }),
      shared.statusBadge(run.status),
    ]));
    panel.append(shared.el("p", { class: "small", text: run.sentence }));
    panel.append(shared.table(["field", "value"], [
      ["command", run.command],
      ["invocation", run.invocation || "–"],
      ["cwd", run.cwd || "–"],
      ["exit", String(run.exit_code)],
      ["duration", String(run.duration_ms || "–") + " ms"],
      ["note", run.note || "–"],
    ]));
    for (const reason of run.reasons || []) panel.append(shared.el("p", { class: "small", text: "· " + reason }));
    for (const stream of ["stdout", "stderr"]) {
      const text = (run[stream] || "").trim();
      if (!text) continue;
      const card = shared.el("div", { class: "card" }, [
        shared.el("div", { class: "card-head" }, [shared.el("h3", { text: stream })]),
      ]);
      for (const line of text.split("\n").slice(0, 40)) card.append(shared.el("p", { class: "small mono", text: line }));
      panel.append(card);
    }
  }

  shared.loaders.exec = async () => {
    await loadExec();
    if (shared.state.exec && shared.state.exec.id) await openExecRun(shared.state.exec.id);
  };

  document.getElementById("exec-refresh").addEventListener("click", () => {
    shared.loaders.exec().catch((error) => shared.report(document.getElementById("exec-detail"), error));
  });

  document.getElementById("exec-run-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("exec-run-status");
    status.textContent = "";
    try {
      const run = await shared.api("POST", "/api/exec/runs", {
        cmdline: document.getElementById("exec-cmdline").value.trim(),
        target: document.getElementById("exec-target").value,
      });
      status.textContent = run.status + " · exit " + run.exit_code;
      await loadExec();
      await openExecRun(run.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
