/* voice view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- voice
  // Three honest things on one page: measurements taken from the bytes, transcripts that name their
  // author, and a refusal that lists every missing link instead of a spinner that never resolves.
  function kindChip(kind) {
    return shared.toolChip(kind, kind === "image" ? "pixels" : kind === "audio" ? "samples" : "text");
  }

  async function loadVoice() {
    shared.state.voice = shared.state.voice || {};
    const data = await shared.api("GET", "/api/voice/assets");
    const stats = shared.clear(document.getElementById("voice-stats"));
    const summary = data.stats || {};
    stats.append(shared.el("p", { class: "small", text: summary.assets + " measured · " + (summary.transcripts || 0) + " transcript(s) · " + (summary.refused || 0) + " refused attempt(s)" }));
    stats.append(shared.el("p", { class: "small dim", text: summary.can_transcribe ? "speech-to-text: ready" : "speech-to-text: not available (ask the panel why)" }));

    const list = shared.clear(document.getElementById("voice-assets"));
    if (!data.assets.length) list.append(shared.el("li", { class: "dim small", text: "nothing measured yet" }));
    for (const asset of data.assets) {
      const size = asset.width ? asset.width + "×" + asset.height : asset.duration_ms !== null && asset.duration_ms !== undefined ? asset.duration_ms + " ms" : "";
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.voice.id === asset.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: asset.format + (size ? " · " + size : "") }),
        shared.el("span", { class: "s", text: asset.kind + " · " + asset.path + (asset.name_mismatch ? " · mislabelled" : "") }),
      ]);
      button.addEventListener("click", () => openAsset(asset.id).catch((error) => shared.report(document.getElementById("voice-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }
    return data;
  }

  async function openAsset(assetId) {
    const panel = shared.clear(document.getElementById("voice-detail"));
    shared.state.voice = shared.state.voice || {};
    shared.state.voice.id = assetId;
    const asset = await shared.api("GET", "/api/voice/assets/" + assetId);

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: asset.format + " · " + shared.shortId(asset.id) }),
      shared.statusBadge(asset.kind),
    ]));
    panel.append(shared.el("p", { class: "small", text: asset.described }));
    panel.append(shared.el("p", { class: "small dim", text: asset.path + " · sha256 " + String(asset.sha256).slice(0, 24) + "…" }));

    if (asset.name_mismatch) {
      // The name disagreed with the bytes. Both are kept, and the disagreement is the headline.
      panel.append(shared.el("p", { class: "small", text: "the name disagrees with the bytes: " + asset.name_mismatch }));
    }
    for (const note of (asset.facts && asset.facts.notes) || []) {
      panel.append(shared.el("p", { class: "small dim", text: "note: " + note }));
    }

    const chips = shared.el("div", { class: "row" }, [kindChip(asset.kind), shared.toolChip("bytes", String(asset.bytes))]);
    if (asset.width) chips.append(shared.toolChip("size", asset.width + "×" + asset.height));
    if (asset.duration_ms !== null && asset.duration_ms !== undefined) chips.append(shared.toolChip("duration", asset.duration_ms + " ms"));
    if (asset.sample_rate) chips.append(shared.toolChip("rate", asset.sample_rate + " Hz"));
    panel.append(chips);

    if (asset.audio) {
      const outcome = shared.el("div", { class: "stack" });
      const transcribe = shared.el("button", { type: "button", class: "btn", text: "Ask for words" });
      transcribe.addEventListener("click", async () => {
        try {
          const result = await shared.api("POST", "/api/voice/assets/" + assetId + "/transcribe", {});
          shared.clear(outcome);
          outcome.append(shared.el("p", { class: "small", text: "refused (attempt " + shared.shortId(result.attempt_id) + "):" }));
          for (const reason of result.reasons || []) outcome.append(shared.el("p", { class: "small dim", text: "· " + reason }));
          if (result.fix) outcome.append(shared.el("p", { class: "small", text: result.fix }));
          await openAsset(assetId);
        } catch (error) {
          shared.report(outcome, error);
        }
      });
      panel.append(shared.el("div", { class: "row" }, [transcribe]));
      panel.append(outcome);
    }

    const words = shared.el("form", { class: "card" });
    words.append(shared.el("div", { class: "card-head" }, [
      shared.el("h3", { text: "Words a person wrote" }),
      shared.el("p", { class: "hint", text: "This build cannot recognise speech. What it can keep is a transcript you type, recorded as yours." }),
    ]));
    const text = shared.el("textarea", { rows: "3", placeholder: "what the recording says" });
    const status = shared.el("span", { class: "hint" });
    const save = shared.el("button", { type: "submit", class: "btn primary", text: "Record as mine" });
    words.addEventListener("submit", async (event) => {
      event.preventDefault();
      status.textContent = "";
      try {
        await shared.api("POST", "/api/voice/assets/" + assetId + "/transcripts", { text: text.value });
        text.value = "";
        await openAsset(assetId);
      } catch (error) {
        shared.report(status, error);
      }
    });
    words.append(shared.el("label", { class: "field" }, ["Transcript", text]), shared.el("div", { class: "row between" }, [save, status]));
    panel.append(words);

    panel.append(shared.table(["source", "chars", "words"], (asset.transcripts || []).map((row) => [
      shared.statusBadge(row.source), text(row.chars), row.text.slice(0, 80),
    ]), "no words recorded"));

    if ((asset.attempts || []).length) {
      panel.append(shared.table(["when", "action", "status", "why"], asset.attempts.map((attempt) => [
        attempt.created_at, attempt.action, shared.statusBadge(attempt.status), (attempt.reason || "–").slice(0, 90),
      ])));
    }
    await loadVoice();
  }

  shared.loaders.voice = async () => {
    await loadVoice();
    if (shared.state.voice && shared.state.voice.id) await openAsset(shared.state.voice.id);
  };

  document.getElementById("voice-refresh").addEventListener("click", () => {
    shared.loaders.voice().catch((error) => shared.report(document.getElementById("voice-detail"), error));
  });

  document.getElementById("voice-probe-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("voice-probe-status");
    status.textContent = "";
    try {
      const asset = await shared.api("POST", "/api/voice/probe", { path: document.getElementById("voice-path").value.trim() });
      document.getElementById("voice-path").value = "";
      await openAsset(asset.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

  document.getElementById("voice-say-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("voice-say-status");
    status.textContent = "";
    const words = document.getElementById("voice-say-text").value.trim();
    if (!words) return;
    try {
      const result = await shared.api("POST", "/api/voice/say", { text: words });
      status.textContent = "refused: " + (result.reasons || []).length + " reason(s), recorded as " + shared.shortId(result.attempt_id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
