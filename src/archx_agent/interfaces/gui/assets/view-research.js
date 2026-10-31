/* research view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // ----------------------------------------------------------------- research
  function researchItem(run) {
    return shared.el("li", {
      class: "list-item" + (run.id === shared.state.researchId ? " active" : ""),
      onclick: () => openResearch(run.id),
    }, [
      shared.el("span", { class: "t", text: run.question }),
      shared.el("span", {
        class: "s",
        text: (run.closed ? "done · " : "") + run.status + " · "
          + Math.round((run.coverage || 0) * 100) + "% coverage · "
          + run.plan_by + "/" + run.mode + " · " + shared.shortId(run.id),
      }),
    ]);
  }

  async function loadResearchList() {
    const list = shared.clear(document.getElementById("research-list"));
    const runs = await shared.api("GET", "/api/research?limit=30");
    if (!runs.length) {
      list.append(shared.el("li", { class: "list-empty", text: "no runs yet" }));
      return runs;
    }
    for (const run of runs) list.append(researchItem(run));
    return runs;
  }

  async function openResearch(id) {
    shared.state.researchId = id;
    await loadResearchList();
    const panel = shared.clear(document.getElementById("research-detail"));
    const data = await shared.api("GET", "/api/research/" + encodeURIComponent(id));
    const run = data.run;
    const verification = data.verification || {};
    const coverage = Math.round((run.coverage || 0) * 100);

    panel.append(shared.el("div", { class: "research-run-head" }, [
      shared.el("div", {}, [
        shared.el("h2", { text: run.question }),
        shared.el("div", { class: "goal-meta" }, [
          shared.statusBadge(run.status),
          shared.el("span", { text: "mode " + run.mode }),
          shared.el("span", { text: "plan by " + run.plan_by }),
          shared.el("span", { text: run.evidence_count + " usable source(s)" }),
          shared.el("span", { text: shared.shortId(run.id) }),
          run.closed ? shared.el("span", { class: "tag ok", text: "done " + shared.stamp(run.closed_at) }) : null,
          run.closed && run.closed_note ? shared.el("span", { text: run.closed_note }) : null,
        ]),
      ]),
      shared.el("div", { class: "row" }, [
        run.closed
          ? shared.el("button", {
            class: "btn tiny",
            type: "button",
            title: "Put this question back on the list",
            onclick: async () => {
              try {
                await shared.api("POST", "/api/research/" + encodeURIComponent(id) + "/reopen", {});
                shared.toast("Reopened", "the run is open again", "ok");
                await openResearch(id);
                await loadResearchList();
              } catch (error) { shared.toast("Could not reopen", error.message, "err"); }
            },
          }, ["reopen"])
          : shared.el("button", {
            class: "btn tiny primary",
            type: "button",
            title: "Mark this question done",
            onclick: async () => {
              const answer = await shared.ask({
                title: "Mark this question done?",
                text: "Closure is your call, not a coverage threshold: this records that you are finished with the question, whatever the run found. You can reopen it.",
                okLabel: "Mark complete",
                kind: "primary",
                note: true,
              });
              if (!answer) return;
              try {
                await shared.api("POST", "/api/research/" + encodeURIComponent(id) + "/close", { note: answer.note });
                shared.toast("Marked complete", "the run is closed; `research reopen` undoes it", "ok");
                await openResearch(id);
                await loadResearchList();
              } catch (error) { shared.toast("Could not close the run", error.message, "err"); }
            },
          }, [shared.svgIcon("check"), "mark complete"]),
        shared.el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => shared.api("GET", "/api/research/" + encodeURIComponent(id) + "/report")
            .then((reportText) => shared.copyText(reportText, "report copied"))
            .catch((error) => shared.toast("Could not copy the report", error.message, "err")),
        }, [shared.svgIcon("copy"), "copy report"]),
        shared.el("button", {
          class: "btn tiny",
          type: "button",
          onclick: () => shared.api("GET", "/api/research/" + encodeURIComponent(id) + "/report")
            .then((reportText) => shared.downloadText("research-" + shared.shortId(id) + ".md", reportText, "text/markdown;charset=utf-8"))
            .catch((error) => shared.toast("Could not save the report", error.message, "err")),
        }, [shared.svgIcon("download"), "save .md"]),
      ]),
    ]));

    panel.append(shared.el("div", { class: "coverage" }, [
      shared.el("span", { class: "small dim", text: "coverage" }),
      shared.el("progress", { class: "bar", max: "100", value: String(Math.max(0, Math.min(100, coverage))) }),
      shared.el("span", { class: "pct", text: coverage + "%" }),
    ]));

    panel.append(shared.el("p", { class: verification.ok ? "small dim" : "callout warn" }, [
      verification.ok
        ? "every citation resolves (" + verification.citations + " citation(s), " + (verification.sources_cited || []).length + " source(s) cited)"
        : "verification failed: unknown citations " + JSON.stringify(verification.unknown_citations)
          + ", uncited claims " + (verification.uncited_claims || []).length,
    ]));

    panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Sources" }), shared.el("p", { text: "including the ones that failed" })])]));
    panel.append(shared.table(
      ["cite", "kind", "status", "title", "stance", "rel", "excerpt / why it failed"],
      data.sources.map((source) => {
        const label = data.labels[String(source.id)];
        return [
          label ? "S" + label : "–",
          source.kind,
          shared.statusBadge(source.status),
          source.title || source.ref || source.url || "",
          source.stance || "unknown",
          source.relevance ? Number(source.relevance).toFixed(2) : "–",
          source.error || (source.excerpt ? source.excerpt.slice(0, 180) : ""),
        ];
      }),
      "no sources",
    ));

    panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Report" })])]));
    const reportBox = shared.el("div", { class: "panel" });
    reportBox.append(shared.el("p", { class: "loading" }, [shared.el("span", { class: "spinner" }), "reading the report"]));
    panel.append(reportBox);
    try {
      const reportText = await shared.api("GET", "/api/research/" + encodeURIComponent(id) + "/report");
      shared.clear(reportBox);
      reportBox.append(...shared.renderMarkdown(reportText));
    } catch (error) {
      shared.report(reportBox, error);
    }

    if ((run.limitations || []).length) {
      panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Limitations" }), shared.el("p", { text: "what this run did not do" })])]));
      panel.append(shared.el("ul", { class: "criteria" }, run.limitations.map((note) => shared.el("li", { text: note }))));
    }
  }

  shared.loaders.research = async () => {
    await loadResearchList();
    if (shared.state.researchId) await openResearch(shared.state.researchId);
  };

  document.getElementById("research-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = document.getElementById("research-question").value.trim();
    if (!question) return;
    const status = document.getElementById("research-status");
    const button = event.target.querySelector("button[type=submit]");
    status.textContent = "running – a web run may ask for permission";
    button.disabled = true;
    const lines = (id) => document.getElementById(id).value.split("\n").map((line) => line.trim()).filter(Boolean);
    try {
      const result = await shared.api("POST", "/api/research", {
        question,
        mode: document.getElementById("research-mode").value,
        urls: lines("research-urls"),
        subquestions: lines("research-subquestions"),
        use_model: !document.getElementById("research-nomodel").checked,
      });
      status.textContent = "finished · " + result.run.status;
      shared.state.researchId = result.run.id;
      await openResearch(result.run.id);
      shared.invalidateStatus();
    } catch (error) {
      status.textContent = "";
      const panel = shared.clear(document.getElementById("research-detail"));
      panel.append(shared.el("h2", { text: "This run was refused" }));
      shared.report(panel, error);
      await loadResearchList().catch(() => {});
    } finally {
      button.disabled = false;
    }
  });

});
