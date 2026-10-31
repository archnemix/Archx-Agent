/* models view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- models
  /* The consent ladder is not decoration: each rung posts the same call the CLI makes, and
   * the next render reads the answer back from the server. Nothing here flips a flag locally. */
  const GATE_ACTIONS = {
    consent_policy: {
      label: "Allow cloud routing",
      run: (model) => shared.api("POST", "/api/settings/model.local_only", { value: false }),
      done: "Cloud routing allowed. This home may now talk to the endpoints you registered.",
    },
    provider: {
      label: "Register the provider",
      run: (model) => shared.api("POST", "/api/models/" + encodeURIComponent(model.id) + "/provider", {}),
      done: "Provider registered. Its privacy terms still need your answer.",
    },
    privacy: {
      label: "Confirm what leaves the device",
      // A provider's terms are the user's to state; guessing them here would be a fake answer.
      run: (model) => shared.api("POST", "/api/providers/" + encodeURIComponent(model.provider_id) + "/privacy", {
        data_leaves_device: true,
        training_use: "unknown",
        retention: "unknown",
      }),
      done: "Recorded: prompts leave this device and the provider's training use is unknown.",
    },
    consent: {
      label: "Record consent",
      run: (model) => shared.api("POST", "/api/providers/" + encodeURIComponent(model.provider_id) + "/consent",
        { note: "consent recorded in the GUI" }),
      done: "Consent recorded, with a timestamp.",
    },
  };

  function gateRow(model, gate) {
    const action = GATE_ACTIONS[gate.key];
    // privacy and consent belong to a provider row; without one there is nothing to POST to
    const needsProvider = gate.key === "privacy" || gate.key === "consent";
    const blocked = needsProvider && !model.provider_id;
    const control = gate.ok || !action || blocked ? null : shared.el("button", {
      class: "btn tiny",
      type: "button",
      onclick: async (event) => {
        if (gate.key === "privacy") {
          const sure = await shared.ask({
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
          shared.toast("Done", action.done, "ok");
          await shared.loaders.models();
          shared.invalidateStatus();
        } catch (error) {
          button.disabled = false;
          shared.toast("Refused", error.message, "err");
        }
      },
    }, [action.label]);
    return shared.el("div", { class: "rung" + (gate.ok ? " rung-ok" : "") }, [
      shared.el("span", { class: "rung-dot", "aria-hidden": "true" }),
      shared.el("div", { class: "rung-body" }, [
        shared.el("div", { class: "rung-label", text: gate.label }),
        shared.el("div", { class: "rung-detail", text: gate.detail }),
      ]),
      control,
    ]);
  }

  function modelCard(model) {
    const caps = (model.capabilities || []).map((cap) => shared.el("span", { class: "tag", text: cap }));
    return shared.el("div", { class: "card model-card" }, [
      shared.el("div", { class: "row between" }, [
        shared.el("div", {}, [
          shared.el("div", { class: "model-name", text: model.name || model.id }),
          shared.el("span", {
            class: "model-backend",
            text: (model.provider || "?") + " · " + model.runtime +
              ((model.facts || {}).sdk ? " · " + model.facts.sdk + " SDK" : ""),
          }),
        ]),
        shared.el("div", { class: "row" }, [
          model.ready ? shared.badge("ready", "ok") : shared.badge("blocked", "bad"),
          shared.el("button", {
            class: "btn tiny",
            type: "button",
            title: "Send one small prompt and record the measurement",
            onclick: async (event) => {
              const button = event.currentTarget;
              button.disabled = true;
              button.textContent = "testing…";
              try {
                const probe = await shared.api("POST", "/api/models/" + encodeURIComponent(model.id) + "/probe",
                  { capability: "chat" });
                const result = probe.result || {};
                if (result.outcome === "passed") {
                  shared.toast("Probe passed", result.detail, "ok");
                } else {
                  shared.toast("Probe failed", result.detail || "the model did not answer", "err");
                }
                await shared.loaders.models();
              } catch (error) {
                shared.toast("Probe failed", error.message, "err");
              } finally {
                button.disabled = false;
                button.textContent = "test chat";
              }
            },
          }, ["test chat"]),
        ]),
      ]),
      shared.el("p", { class: "ready-reason", text: model.ready_reason }),
      caps.length ? shared.el("div", { class: "row caps" }, caps) : null,
      shared.el("div", { class: "rungs" }, (model.gates || []).map((gate) => gateRow(model, gate))),
    ]);
  }

  shared.loaders.models = async () => {
    await loadSdkOptions();
    const models = await shared.api("GET", "/api/models");
    const panel = shared.clear(document.getElementById("models-list"));
    if (!models.length) {
      panel.append(shared.el("p", { class: "muted-box", text: "No model is registered yet. Connect Gemini above, or add a local endpoint with `archx-agent models add-http`." }));
      return;
    }
    for (const model of models) panel.append(modelCard(model));
  };

  document.getElementById("models-refresh").addEventListener("click", () => {
    shared.loaders.models().catch((error) => shared.report(document.getElementById("models-list"), error));
  });

  /* The transport picker lists the vendor SDKs that are actually importable in this
   * interpreter, with the ones that are not marked rather than hidden: "install this to use
   * it" is more useful than an option that silently disappears. */
  let sdkOptions = null;
  async function loadSdkOptions() {
    if (sdkOptions) return sdkOptions;
    const sdks = await shared.api("GET", "/api/sdks").catch(() => []);
    sdkOptions = sdks;
    const picker = document.getElementById("models-transport");
    const credential = document.getElementById("models-credential");
    for (const sdk of sdks) {
      picker.append(shared.el("option", {
        value: sdk.key,
        text: sdk.label + " — the official " + sdk.package + " SDK" + (sdk.installed ? "" : " (not installed)"),
      }));
    }
    picker.addEventListener("change", () => {
      const chosen = sdks.find((sdk) => sdk.key === picker.value);
      credential.setAttribute("placeholder", chosen ? "secret://env/" + chosen.env_var : "secret://env/GEMINI_API_KEY");
    });
    return sdkOptions;
  }

  document.getElementById("models-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("models-status");
    const button = event.target.querySelector("button[type=submit]");
    status.textContent = "registering…";
    button.disabled = true;
    try {
      const created = await shared.api("POST", "/api/models", {
        name: document.getElementById("models-name").value,
        model: document.getElementById("models-model").value,
        transport: document.getElementById("models-transport").value,
        credential_ref: document.getElementById("models-credential").value,
        base_url: document.getElementById("models-base").value,
      });
      document.getElementById("models-credential").value = "";
      status.textContent = created.ready ? "ready: " + created.ready_reason : created.ready_reason;
      shared.toast("Model registered", created.name + " · " + created.runtime, "ok");
      await shared.loaders.models();
      shared.invalidateStatus();
    } catch (error) {
      status.textContent = "";
      shared.toast("Could not register", error.message, "err");
    } finally {
      button.disabled = false;
    }
  });

});
