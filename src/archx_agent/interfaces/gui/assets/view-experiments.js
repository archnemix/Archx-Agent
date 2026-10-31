/* experiments view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------ experiments
  // The honest bit of this panel is the fourth column: a run that produced no number says why,
  // and the comparison names the runs it could not rank instead of dropping them.
  async function loadExperiments() {
    const list = shared.clear(document.getElementById("experiments-list"));
    const data = await shared.api("GET", "/api/experiments");
    shared.state.experiments = shared.state.experiments || {};
    if (!data.experiments.length) {
      list.append(shared.el("li", { class: "dim small", text: "no experiments yet" }));
    }
    for (const experiment of data.experiments) {
      const stats = experiment.stats || { runs: 0, failed: 0 };
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.experiments.id === experiment.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: experiment.name }),
        shared.el("span", { class: "s", text: experiment.status + " · " + stats.runs + " run(s)" + (stats.failed ? " · " + stats.failed + " not passed" : "") }),
      ]);
      button.addEventListener("click", () => openExperiment(experiment.id).catch((error) => shared.report(document.getElementById("experiment-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return data;
  }

  function metricsCell(run) {
    const names = Object.keys(run.metrics || {});
    if (names.length) return names.map((name) => name + "=" + run.metrics[name]).join(", ");
    return run.metrics_error ? "not read: " + run.metrics_error : "none";
  }

  function experimentRunner(experiment, panel) {
    const card = shared.el("div", { class: "card" });
    card.append(shared.el("div", { class: "card-head" }, [
      shared.el("h3", { text: "Run it" }),
      shared.el("p", { class: "hint", text: "Overrides are optional: an empty field uses the declared default. A value has to be one shell-safe token." }),
    ]));
    const inputs = {};
    for (const param of experiment.params) {
      const input = shared.el("input", { type: "text", placeholder: param.default === null ? "no default" : String(param.default) });
      inputs[param.name] = input;
      card.append(shared.el("label", { class: "field" }, [param.name + (param.description ? " · " + param.description : ""), input]));
    }
    const timeout = shared.el("input", { type: "text", placeholder: "60" });
    card.append(shared.el("label", { class: "field" }, ["Timeout (seconds)", timeout]));
    const status = shared.el("span", { class: "hint" });
    const button = shared.el("button", { type: "submit", class: "btn primary", text: "Run" });
    button.addEventListener("click", async () => {
      status.textContent = "running…";
      const params = {};
      for (const [name, input] of Object.entries(inputs)) {
        if (input.value.trim()) params[name] = input.value.trim();
      }
      const body = { params };
      if (timeout.value.trim()) body.timeout = Number(timeout.value.trim());
      try {
        const run = await shared.api("POST", "/api/experiments/" + experiment.id + "/run", body);
        status.textContent = run.status + " · exit " + run.exit_code + " · " + Math.round(run.duration_ms || 0) + " ms";
        if (run.metrics_error) status.textContent += " · " + run.metrics_error;
        await openExperiment(experiment.id);
      } catch (error) {
        status.textContent = "";
        shared.report(card, error);
      }
    });
    card.append(shared.el("div", { class: "row between" }, [button, status]));
    return card;
  }

  async function openExperiment(experimentId) {
    const panel = shared.clear(document.getElementById("experiment-detail"));
    shared.state.experiments = shared.state.experiments || {};
    shared.state.experiments.id = experimentId;
    const shown = await shared.api("GET", "/api/experiments/" + experimentId);
    const experiment = shown.experiment;
    const stats = shown.stats || {};

    panel.append(shared.el("div", { class: "row between" }, [shared.el("h2", { text: experiment.name }), shared.statusBadge(experiment.status)]));
    if (experiment.hypothesis) panel.append(shared.el("p", { class: "small", text: "Expected: " + experiment.hypothesis }));
    panel.append(shared.el("p", { class: "small dim", text: experiment.command + " · " + experiment.root }));
    panel.append(shared.el("div", { class: "row" }, [
      shared.toolChip("runs", String(stats.runs || 0) + (stats.without_metrics ? " · " + stats.without_metrics + " without metrics" : "")),
      shared.toolChip("metrics", (shown.metric_names || []).join(", ") || "none recorded"),
      shared.toolChip("params", experiment.param_names.join(", ") || "none"),
    ]));

    if (experiment.open) panel.append(experimentRunner(experiment, panel));

    if (shown.runs.length) {
      panel.append(shared.el("div", {}, [shared.el("h3", { text: "Runs" })]));
      panel.append(shared.table(["run", "params", "status", "exit", "ms", "metrics"], shown.runs.map((run) => [
        shared.shortId(run.id), Object.entries(run.params || {}).map(([key, value]) => key + "=" + value).join(", ") || "-",
        shared.statusBadge(run.status), shared.text(run.exit_code), shared.text(Math.round(run.duration_ms || 0)), metricsCell(run),
      ])));
    }

    if (shown.metric_names.length) {
      const compareCard = shared.el("div", { class: "card" });
      compareCard.append(shared.el("div", { class: "card-head" }, [shared.el("h3", { text: "Compare" }), shared.el("p", { class: "hint", text: "Ranked on one metric. A run with no value for it is named, not silently dropped." })]));
      const select = shared.el("select", { class: "sel" });
      for (const name of shown.metric_names) select.append(shared.el("option", { value: name, text: name }));
      const minimise = shared.el("input", { type: "checkbox" });
      const output = shared.el("div", { class: "stack" });
      const compareButton = shared.el("button", { type: "button", class: "btn", text: "Compare" });
      compareButton.addEventListener("click", async () => {
        try {
          const table_ = await shared.api("GET", "/api/experiments/" + experimentId + "/compare?metric=" + encodeURIComponent(select.value) + (minimise.checked ? "&minimise=true" : ""));
          shared.clear(output);
          if (table_.best) {
            output.append(shared.el("p", { class: "small", text: "best: " + shared.shortId(table_.best.run_id) + " with " + table_.metric + "=" + table_.best.value + " (" + table_.direction + " wins)" }));
          } else {
            output.append(shared.el("p", { class: "small dim", text: "no run has a value for that metric yet" }));
          }
          for (const note of table_.notes) output.append(shared.el("p", { class: "small dim", text: "note: " + note }));
        } catch (error) {
          shared.report(output, error);
        }
      });
      compareCard.append(shared.el("div", { class: "row" }, [select, shared.el("label", { class: "small" }, [minimise, " lower is better"]), compareButton]));
      compareCard.append(output);
      panel.append(compareCard);
    }

    const actions = shared.el("div", { class: "row" });
    const toggle = shared.el("button", { type: "button", class: "btn", text: experiment.open ? "Close experiment" : "Reopen experiment" });
    toggle.addEventListener("click", async () => {
      try {
        await shared.api("POST", "/api/experiments/" + experimentId + (experiment.open ? "/close" : "/reopen"), {});
        await openExperiment(experimentId);
      } catch (error) {
        shared.report(panel, error);
      }
    });
    actions.append(toggle);
    panel.append(actions);
    await loadExperiments();
  }

  shared.loaders.experiments = async () => {
    await loadExperiments();
    if (shared.state.experiments && shared.state.experiments.id) await openExperiment(shared.state.experiments.id);
  };

  document.getElementById("experiments-refresh").addEventListener("click", () => {
    shared.loaders.experiments().catch((error) => shared.report(document.getElementById("experiment-detail"), error));
  });

  document.getElementById("experiment-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("experiment-create-status");
    status.textContent = "";
    const params = [];
    const raw = document.getElementById("experiment-params").value.trim();
    for (const piece of raw ? raw.split(",") : []) {
      const text_ = piece.trim();
      if (!text_) continue;
      const [name, ...rest] = text_.split("=");
      params.push({ name: name.trim(), default: rest.length ? rest.join("=").trim() : null });
    }
    const kind = document.getElementById("experiment-metrics").value;
    const body = {
      name: document.getElementById("experiment-name").value.trim(),
      command: document.getElementById("experiment-command").value.trim(),
      params,
      metrics: kind === "file"
        ? { kind, path: document.getElementById("experiment-metrics-path").value.trim() || "metrics.json" }
        : { kind },
    };
    try {
      const experiment = await shared.api("POST", "/api/experiments", body);
      document.getElementById("experiment-name").value = "";
      document.getElementById("experiment-command").value = "";
      document.getElementById("experiment-params").value = "";
      await openExperiment(experiment.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
