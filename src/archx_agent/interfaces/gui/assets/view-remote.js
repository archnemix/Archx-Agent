/* remote view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------ remote
  // The page's claim is the two hashes: what the worker said, and what this machine measured. They
  // are shown as separate rows because the interesting case is the one where they disagree.
  async function loadRemote() {
    shared.state.remote = shared.state.remote || {};
    const payload = await shared.api("GET", "/api/remote/jobs");
    const stats = payload.stats || {};
    const summary = shared.clear(document.getElementById("remote-stats"));
    summary.append(shared.el("p", { class: "small", text: (stats.jobs || 0) + " job(s) · " + (stats.attempts || 0) + " attempt(s) · " + (stats.unverified || 0) + " unverified" }));
    summary.append(shared.el("p", { class: "small dim", text: (stats.enabled ? "dispatch is on" : "dispatch is off") + " · endpoint " + (stats.endpoint || "(none)") + " · " + (stats.protocol || "") }));

    const list = shared.clear(document.getElementById("remote-jobs"));
    if (!payload.jobs.length) list.append(shared.el("li", { class: "dim small", text: "no remote jobs yet" }));
    for (const job of payload.jobs) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.remote.id === job.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: job.kind + " · " + shared.shortId(job.id) }),
        shared.el("span", { class: "s", text: job.status + " · " + (job.endpoint || "not sent") }),
      ]);
      button.addEventListener("click", () => openRemoteJob(job.id).catch((error) => shared.report(document.getElementById("remote-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return payload;
  }

  async function openRemoteJob(jobId) {
    const panel = shared.clear(document.getElementById("remote-detail"));
    shared.state.remote = shared.state.remote || {};
    shared.state.remote.id = jobId;
    const job = await shared.api("GET", "/api/remote/jobs/" + jobId);

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: job.kind + " · " + shared.shortId(job.id) }),
      shared.statusBadge(job.status),
    ]));
    panel.append(shared.el("p", { class: "small", text: job.sentence }));

    const chips = shared.el("div", { class: "row" }, [
      shared.toolChip("dataset", job.dataset_id ? shared.shortId(job.dataset_id) : "–"),
      shared.toolChip("endpoint", job.endpoint || "not sent"),
      shared.toolChip("approved", job.approved_by || "no"),
    ]);
    panel.append(chips);

    panel.append(shared.table(["claim", "value"], [
      ["bundle sha256", String(job.bundle_sha256 || "–").slice(0, 24) + "…"],
      ["bundle path", job.bundle_path || "–"],
      ["endpoint said", job.claimed_sha256 || "–"],
      ["measured here", job.received_sha256 || "–"],
      ["artifact", job.artifact_path || "–"],
      ["machine", job.machine || "–"],
      ["protocol", job.protocol || "–"],
      ["note", job.verify_note || "–"],
    ]));

    if ((job.reasons || []).length) {
      const card = shared.el("div", { class: "card" });
      card.append(shared.el("div", { class: "card-head" }, [
        shared.el("h3", { text: "Not sent, and why" }),
        shared.el("p", { class: "hint", text: "Nothing left this machine. Each line below is a condition that is not met." }),
      ]));
      for (const reason of job.reasons) card.append(shared.el("p", { class: "small", text: "· " + reason }));
      panel.append(card);
    }

    const metrics = (job.outputs && job.outputs.metrics) || {};
    const rows = shared.metricRows(metrics);
    if (rows.length) panel.append(shared.table(["split", "metric", "value"], rows));

    const actions = shared.el("div", { class: "row" });
    const addAction = (label, path, body) => {
      const button = shared.el("button", { type: "button", class: "btn", text: label });
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await shared.api("POST", "/api/remote/jobs/" + jobId + path, body);
          await openRemoteJob(jobId);
        } catch (error) {
          shared.report(panel, error);
        } finally {
          button.disabled = false;
        }
      });
      actions.append(button);
    };
    if (!job.approved_by) addAction("Approve", "/approve", {});
    if (job.status === "draft" || job.status === "refused" || job.status === "failed") addAction("Dispatch", "/dispatch", {});
    if (job.status === "dispatched" || job.status === "running") addAction("Collect", "/collect", {});
    if (job.status === "received" || job.status === "verified") addAction("Verify again", "/verify", {});
    panel.append(actions);

    if ((job.attempts || []).length) {
      panel.append(shared.table(["when", "action", "status", "detail"], job.attempts.map((attempt) => [
        attempt.created_at, attempt.action, attempt.status, attempt.detail || "–",
      ])));
    }
  }

  shared.loaders.remote = async () => {
    await loadRemote();
    if (shared.state.remote && shared.state.remote.id) await openRemoteJob(shared.state.remote.id);
  };

  document.getElementById("remote-refresh").addEventListener("click", () => {
    shared.loaders.remote().catch((error) => shared.report(document.getElementById("remote-detail"), error));
  });

  document.getElementById("remote-export-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("remote-export-status");
    status.textContent = "";
    try {
      const job = await shared.api("POST", "/api/remote/export", {
        dataset: document.getElementById("remote-dataset").value.trim(),
        order: Number(document.getElementById("remote-order").value || 2),
      });
      status.textContent = "bundled " + job.records + " record(s), " + job.chars + " characters";
      await loadRemote();
      await openRemoteJob(job.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
