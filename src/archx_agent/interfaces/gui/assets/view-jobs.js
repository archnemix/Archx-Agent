/* jobs view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // --------------------------------------------------------------------- jobs
  const JOB_ACTIONS = [
    ["pause", "pause", "pause"],
    ["resume", "play", "resume"],
    ["retry", "retry", "retry"],
    ["cancel", "stop", "cancel"],
  ];

  shared.loaders.jobs = async () => {
    const data = await shared.api("GET", "/api/jobs?limit=40");
    const cards = shared.clear(document.getElementById("jobs-stats"));
    for (const [key, value] of Object.entries(data.stats || {})) {
      cards.append(shared.stat(value, key.replace(/_/g, " ")));
    }
    const panel = shared.clear(document.getElementById("jobs-list"));
    const rows = data.jobs.map((job) => {
      const actions = shared.el("div", { class: "job-actions" }, JOB_ACTIONS.map(([action, icon, label]) => shared.el("button", {
        class: "btn tiny" + (action === "cancel" ? " danger" : ""),
        type: "button",
        title: label + " this job",
        onclick: async () => {
          if (action === "cancel") {
            const sure = await shared.ask({
              title: "Cancel this job?",
              text: job.title + " will stop at the next safe point and the job becomes terminal.",
              okLabel: "Cancel the job",
            });
            if (!sure) return;
          }
          try {
            await shared.api("POST", "/api/jobs/" + encodeURIComponent(job.id) + "/" + action, {});
            await shared.loaders.jobs();
            shared.invalidateStatus();
          } catch (error) {
            shared.toast("Could not " + action + " the job", error.message, "err");
          }
        },
      }, [shared.svgIcon(icon), label])));
      return [shared.shortId(job.id), job.kind, shared.statusBadge(job.status), job.title, job.priority, actions];
    });
    panel.append(shared.table(["id", "kind", "status", "title", "prio", "actions"], rows, "the queue is empty"));
  };

  document.getElementById("jobs-refresh").addEventListener("click", () => {
    shared.loaders.jobs().catch((error) => shared.report(document.getElementById("jobs-list"), error));
  });

  document.getElementById("jobs-run").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await shared.api("POST", "/api/jobs/drain", { max_jobs: 1 });
      if (!result.ran.length) shared.toast("Nothing queued", "there was no claimable job to run");
      else shared.toast("Ran a job", result.ran[0].title || result.ran[0].id, "ok");
      await shared.loaders.jobs();
      shared.invalidateStatus();
    } catch (error) {
      shared.toast("Could not run a job", error.message, "err");
    } finally {
      button.disabled = false;
    }
  });

});
