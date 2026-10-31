/* memory view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- memory
  async function loadMemory() {
    const items = await shared.api("GET", "/api/memory?limit=60");
    const panel = shared.clear(document.getElementById("memory-list"));
    panel.append(shared.table(
      ["kind", "title", "content", "category", "scope", "status"],
      items.map((item) => [
        shared.badge(item.kind, "accent"), item.title, (item.content || "").slice(0, 140),
        item.category || "–", item.scope, item.status,
      ]),
      "no memories yet",
    ));
  }

  shared.loaders.memory = loadMemory;
  document.getElementById("memory-refresh").addEventListener("click", () => {
    loadMemory().catch((error) => shared.report(document.getElementById("memory-list"), error));
  });

  document.getElementById("memory-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("memory-status");
    status.textContent = "";
    try {
      const stored = await shared.api("POST", "/api/memory", {
        kind: document.getElementById("memory-kind").value,
        title: document.getElementById("memory-title").value,
        content: document.getElementById("memory-content").value,
        category: document.getElementById("memory-category").value || null,
      });
      document.getElementById("memory-title").value = "";
      document.getElementById("memory-content").value = "";
      status.textContent = "stored " + shared.shortId(stored.id);
      shared.toast("Memory stored", shared.shortId(stored.id), "ok");
      await loadMemory();
      shared.invalidateStatus();
    } catch (error) {
      status.textContent = "";
      shared.report(document.getElementById("memory-list"), error);
    }
  });

});
