/* data view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- data
  // A dataset is four claims held together: what went in, what was removed and why, which split
  // each record is in, and a hash over the manifest. The page shows all four - including the
  // dropped records, because "why is this file not in my dataset" is the first question anyone asks.
  async function loadDatasets() {
    shared.state.data = shared.state.data || {};
    const payload = await shared.api("GET", "/api/datasets");
    const stats = shared.clear(document.getElementById("data-stats"));
    const summary = payload.stats || {};
    stats.append(shared.el("p", { class: "small", text: (summary.datasets || 0) + " dataset(s) · " + (summary.records || 0) + " candidate(s) · " + (summary.kept || 0) + " kept" }));
    stats.append(shared.el("p", { class: "small dim", text: (summary.dropped || 0) + " dropped, each with its reason kept" }));

    const list = shared.clear(document.getElementById("data-list"));
    if (!payload.datasets.length) list.append(shared.el("li", { class: "dim small", text: "no datasets yet" }));
    for (const dataset of payload.datasets) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.data.id === dataset.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: dataset.name }),
        shared.el("span", { class: "s", text: dataset.status + " · " + (dataset.record_count ?? 0) + " kept · " + (dataset.dropped_count || 0) + " dropped" }),
      ]);
      button.addEventListener("click", () => openDataset(dataset.id).catch((error) => shared.report(document.getElementById("data-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return payload;
  }

  function datasetAction(panel, label, path, body, after, primary) {
    const button = shared.el("button", { type: "button", class: "btn" + (primary ? " primary" : ""), text: label });
    const outcome = shared.el("p", { class: "small dim" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      outcome.textContent = "";
      try {
        await shared.api("POST", path, body || {});
        if (after) await after();
      } catch (error) {
        shared.report(outcome, error);
      } finally {
        button.disabled = false;
      }
    });
    panel.append(button);
    return { button, outcome };
  }

  async function openDataset(datasetId) {
    const panel = shared.clear(document.getElementById("data-detail"));
    shared.state.data = shared.state.data || {};
    shared.state.data.id = datasetId;
    const dataset = await shared.api("GET", "/api/datasets/" + datasetId);
    const counts = dataset.counts || {};

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: dataset.name + " · " + shared.shortId(dataset.id) }),
      shared.statusBadge(dataset.status),
    ]));
    panel.append(shared.el("p", { class: "small", text: (counts.kept || 0) + " kept, " + (counts.dropped || 0) + " dropped · license " + dataset.license }));
    panel.append(shared.el("p", { class: "small dim", text: dataset.license_note }));

    const chips = shared.el("div", { class: "row" }, [
      shared.toolChip("sources", String((dataset.sources || []).length)),
      shared.toolChip("seed", dataset.seed || "–"),
    ]);
    for (const [split, count] of Object.entries(counts.by_split || {})) chips.append(shared.toolChip(split, String(count)));
    if (dataset.checksum) chips.append(shared.toolChip("manifest", String(dataset.checksum).slice(0, 12) + "…"));
    panel.append(chips);

    const actions = shared.el("div", { class: "row" });
    const refresh = async () => { await openDataset(datasetId); };
    const scan = datasetAction(actions, "Scan", "/api/datasets/" + datasetId + "/scan", {}, refresh, !counts.kept && !counts.dropped);
    const clean = datasetAction(actions, "Clean", "/api/datasets/" + datasetId + "/clean", { dedupe: true, normalize: true }, refresh);
    const split = datasetAction(actions, "Split", "/api/datasets/" + datasetId + "/split", { seed: dataset.seed || "0" }, refresh);
    const build = datasetAction(actions, "Build", "/api/datasets/" + datasetId + "/build", {}, refresh);
    panel.append(actions);
    panel.append(shared.el("p", { class: "hint", text: "Scan measures every candidate (needs fs.read). Clean removes copies and short files, and keeps the reason. Split follows from each record's own hash, so it does not move. Build writes the JSONL export and records the manifest hash." }));

    const verify = shared.el("div", { class: "stack" });
    const verifyButton = shared.el("button", { type: "button", class: "btn", text: "Verify against the files" });
    verifyButton.addEventListener("click", async () => {
      shared.clear(verify);
      try {
        const result = await shared.api("GET", "/api/datasets/" + datasetId + "/verify");
        verify.append(shared.el("p", { class: "small", text: result.agrees ? "the files still produce the recorded manifest" : "the dataset no longer matches its manifest: " + result.note }));
        verify.append(shared.el("p", { class: "small dim", text: "stored " + (result.stored_checksum || "(none)").slice(0, 24) + "…" }));
        verify.append(shared.el("p", { class: "small dim", text: "recomputed " + String(result.recomputed_checksum).slice(0, 24) + "…" }));
        for (const difference of result.differences || []) {
          verify.append(shared.el("p", { class: "small", text: difference.kind + ": " + difference.path }));
        }
      } catch (error) {
        shared.report(verify, error);
      }
    });
    panel.append(shared.el("div", { class: "row" }, [verifyButton]));
    panel.append(verify);

    if ((dataset.transforms || []).length) {
      panel.append(shared.table(["step", "records in", "records out", "when"], dataset.transforms.map((step) => [
        step.kind, shared.text(step.records_in), shared.text(step.records_out), step.created_at,
      ])));
    }

    const records = await shared.api("GET", "/api/datasets/" + datasetId + "/records?limit=100");
    panel.append(shared.table(["status", "split", "path", "chars", "why"], (records.records || []).map((record) => [
      shared.statusBadge(record.status), record.split || "–", record.path,
      shared.text(record.chars), record.reason || "–",
    ]), "no candidates yet - scan the dataset"));
  }

  shared.loaders.data = async () => {
    await loadDatasets();
    if (shared.state.data && shared.state.data.id) await openDataset(shared.state.data.id);
  };

  document.getElementById("data-refresh").addEventListener("click", () => {
    shared.loaders.data().catch((error) => shared.report(document.getElementById("data-detail"), error));
  });

  document.getElementById("data-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("data-create-status");
    status.textContent = "";
    const name = document.getElementById("data-name").value.trim();
    const sources = document.getElementById("data-sources").value.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!name || !sources.length) { status.textContent = "a name and at least one source"; return; }
    try {
      const dataset = await shared.api("POST", "/api/datasets", {
        name, sources, license: document.getElementById("data-license").value.trim() || null,
      });
      document.getElementById("data-name").value = "";
      document.getElementById("data-sources").value = "";
      document.getElementById("data-license").value = "";
      await openDataset(dataset.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
