/* automations view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- automations
  async function loadAutomations() {
    const data = await shared.api("GET", "/api/automations");
    const list = shared.clear(document.getElementById("automations-list"));
    for (const item of data.automations) {
      const card = shared.el("div", { class: "card" }, [shared.el("h3", { text: item.name }),
        shared.el("p", { text: (item.enabled ? "enabled" : "disabled") + " · " + JSON.stringify(item.schedule) }),
        shared.el("p", { text: "Next: " + (item.next_run_at || "file change") })]);
      const action = item.enabled ? "disable" : "enable";
      const button = shared.el("button", { type: "button", text: action });
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await shared.api("POST", "/api/automations/" + encodeURIComponent(item.id) + "/" + action, {}); await loadAutomations(); }
        catch (error) { shared.report(document.getElementById("automations-status"), error); button.disabled = false; }
      });
      card.append(button); list.append(card);
    }
    document.getElementById("automations-runs").textContent = JSON.stringify(data.runs, null, 2);
  }
  shared.loaders.automations = loadAutomations;
  document.getElementById("automations-refresh").addEventListener("click", () => loadAutomations().catch(error => shared.report(document.getElementById("automations-status"), error)));
  document.getElementById("automations-tick").addEventListener("click", async () => {
    try {
      const result = await shared.api("POST", "/api/automations/tick", {});
      await loadAutomations(); document.getElementById("automations-status").textContent = JSON.stringify(result);
    } catch (error) { shared.report(document.getElementById("automations-status"), error); }
  });
  document.getElementById("automation-create-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const mode = document.getElementById("automation-mode").value;
      const value = document.getElementById("automation-trigger").value;
      const payload = { name: document.getElementById("automation-name").value.trim(), command: JSON.parse(document.getElementById("automation-command").value) };
      payload[mode] = mode === "interval" ? Number(value) : value;
      await shared.api("POST", "/api/automations", payload); await loadAutomations();
    } catch (error) { shared.report(document.getElementById("automations-status"), error); }
  });

});
