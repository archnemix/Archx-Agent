/* train view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- train
  // The honest half of this page is the refusal card: a fine-tune does not get a spinner or a
  // greyed-out button, it gets every missing link listed in order and a row in the table.
  async function loadTraining() {
    shared.state.train = shared.state.train || {};
    const payload = await shared.api("GET", "/api/training/runs");
    const stats = payload.stats || {};
    const summary = shared.clear(document.getElementById("train-stats"));
    summary.append(shared.el("p", { class: "small", text: (stats.jobs || 0) + " run(s) · " + (stats.metrics || 0) + " metric row(s)" }));
    summary.append(shared.el("p", { class: "small dim", text: "can fine-tune: " + (stats.can_finetune ? "yes" : "no") + " · runnable: " + (stats.runnable || []).join(", ") }));

    const list = shared.clear(document.getElementById("train-runs"));
    if (!payload.runs.length) list.append(shared.el("li", { class: "dim small", text: "no runs yet" }));
    for (const run of payload.runs) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.train.id === run.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: run.method }),
        shared.el("span", { class: "s", text: run.status + " · " + shared.shortId(run.id) }),
      ]);
      button.addEventListener("click", () => openRun(run.id).catch((error) => shared.report(document.getElementById("train-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return payload;
  }

  function metricRows(metrics) {
    const rows = [];
    for (const [split, values] of Object.entries(metrics || {})) {
      for (const [name, value] of Object.entries(values)) {
        rows.push([split, name, value === null ? "not measurable" : String(value)]);
      }
    }
    return rows;
  }

  async function openRun(jobId) {
    const panel = shared.clear(document.getElementById("train-detail"));
    shared.state.train = shared.state.train || {};
    shared.state.train.id = jobId;
    const run = await shared.api("GET", "/api/training/runs/" + jobId);

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: run.method + " · " + shared.shortId(run.id) }),
      shared.statusBadge(run.status),
    ]));
    panel.append(shared.el("p", { class: "small", text: run.sentence }));

    const chips = shared.el("div", { class: "row" }, [
      shared.toolChip("dataset", run.dataset_id ? shared.shortId(run.dataset_id) : "–"),
      shared.toolChip("seed", String(run.seed)),
    ]);
    if (run.artifact_sha256) chips.append(shared.toolChip("artifact", String(run.artifact_sha256).slice(0, 12) + "…"));
    panel.append(chips);

    if ((run.reasons || []).length) {
      const card = shared.el("div", { class: "card" });
      card.append(shared.el("div", { class: "card-head" }, [
        shared.el("h3", { text: "Refused, and why" }),
        shared.el("p", { class: "hint", text: "Nothing was trained. Each link below is missing on this machine." }),
      ]));
      for (const reason of run.reasons) card.append(shared.el("p", { class: "small", text: "· " + reason }));
      panel.append(card);
    }

    const rows = metricRows(run.metrics);
    if (rows.length) panel.append(shared.table(["split", "metric", "value"], rows));
    else if (run.status === "completed") panel.append(shared.el("p", { class: "small dim", text: "this run recorded no metrics" }));

    const checks = (run.preflight && run.preflight.checks) || [];
    if (checks.length) {
      panel.append(shared.table(["check", "ok", "detail"], checks.map((check) => [
        check.check, check.ok ? "yes" : "no", check.detail,
      ])));
    }
  }

  shared.loaders.train = async () => {
    await loadTraining();
    if (shared.state.train && shared.state.train.id) await openRun(shared.state.train.id);
  };

  document.getElementById("train-refresh").addEventListener("click", () => {
    shared.loaders.train().catch((error) => shared.report(document.getElementById("train-detail"), error));
  });

  document.getElementById("train-run-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("train-run-status");
    status.textContent = "";
    try {
      const run = await shared.api("POST", "/api/training/runs", {
        method: document.getElementById("train-method").value,
        dataset: document.getElementById("train-dataset").value.trim(),
        seed: Number(document.getElementById("train-seed").value || 0),
      });
      status.textContent = run.status === "completed"
        ? "completed; the metrics are rows"
        : run.status + ": " + ((run.reasons || []).length) + " reason(s), recorded";
      await openRun(run.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

  Object.defineProperty(shared, "metricRows", { get: () => metricRows });
});
