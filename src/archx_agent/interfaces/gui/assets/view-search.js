/* search view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ------------------------------------------------------------------- search
  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = document.getElementById("search-query").value.trim();
    if (!query) return;
    const notes = shared.clear(document.getElementById("search-notes"));
    const panel = shared.clear(document.getElementById("search-results"));
    panel.append(shared.el("p", { class: "loading" }, [shared.el("span", { class: "spinner" }), "searching"]));
    try {
      const files = document.getElementById("search-files").checked;
      const data = await shared.api("GET", "/api/search?q=" + encodeURIComponent(query) + "&files=" + (files ? "1" : "0"));
      shared.clear(panel);
      for (const [kind, reason] of Object.entries(data.skipped || {})) {
        notes.append(shared.el("div", { class: "callout warn", text: "skipped " + kind + ": " + reason }));
      }
      for (const reason of data.degraded || []) notes.append(shared.el("div", { class: "callout warn", text: "degraded: " + reason }));
      panel.append(shared.el("p", { class: "small dim", text: data.total + " hit(s) in " + Math.round(data.elapsed_ms) + " ms" }));
      panel.append(shared.table(
        ["kind", "title", "score", "why it matched", "ref"],
        data.hits.map((hit) => [hit.kind, hit.title, hit.score.toFixed(2), hit.snippet, hit.ref]),
        "no hits",
      ));
    } catch (error) {
      shared.report(panel, error);
    }
  });

});
