/* tasks view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- tasks
  async function loadTasks() {
    const list = shared.clear(document.getElementById("tasks-list"));
    const status = document.getElementById("tasks-status").value;
    const tasks = await shared.api("GET", "/api/tasks?limit=50" + (status ? "&status=" + encodeURIComponent(status) : ""));
    if (!tasks.length) {
      list.append(shared.el("li", { class: "list-empty", text: "no tasks" }));
      return;
    }
    for (const task of tasks) {
      list.append(shared.el("li", {
        class: "list-item" + (task.id === shared.state.taskId ? " active" : ""),
        onclick: () => openTask(task.id),
      }, [
        shared.el("span", { class: "t", text: task.title }),
        shared.el("span", { class: "s", text: task.type + " · " + task.status + " · " + shared.stamp(task.created_at) }),
      ]));
    }
  }

  async function openTask(id) {
    shared.state.taskId = id;
    await loadTasks();
    const panel = shared.clear(document.getElementById("task-detail"));
    const data = await shared.api("GET", "/api/tasks/" + encodeURIComponent(id));
    const task = data.task;
    panel.append(shared.el("div", { class: "goal-head" }, [
      shared.el("div", {}, [
        shared.el("h2", { text: task.title }),
        shared.el("div", { class: "goal-meta" }, [
          shared.statusBadge(task.status),
          shared.el("span", { text: task.type }),
          shared.el("span", { text: shared.shortId(task.id) }),
          shared.el("span", { text: shared.stamp(task.created_at) }),
        ]),
      ]),
    ]));
    panel.append(shared.kv(Object.entries(task)
      .filter(([, value]) => value !== null && value !== "" && typeof value !== "object")
      .map(([key, value]) => [key, String(value)])));
    if (data.timeline.length) {
      panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Timeline" })])]));
      panel.append(shared.table(["#", "kind", "detail", "at"], data.timeline.map((entry, index) => [
        String(index + 1), entry.kind, entry.detail || "", shared.stamp(entry.created_at || entry.at),
      ])));
    }
    if (data.artifacts.length) {
      panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Artifacts" }), shared.el("p", { text: "with the checksum that proves they are the same bytes" })])]));
      panel.append(shared.table(["kind", "path", "sha256"], data.artifacts.map((artifact) => [
        artifact.kind, artifact.path, (artifact.checksum || "").slice(0, 16),
      ])));
    }
    if (data.tools.length) {
      panel.append(shared.el("div", { class: "section-head" }, [shared.el("div", {}, [shared.el("h2", { text: "Tool runs" })])]));
      panel.append(shared.table(["tool", "status", "at"], data.tools.map((tool) => [
        tool.tool_name, shared.statusBadge(tool.status), shared.stamp(tool.started_at),
      ])));
    }
  }

  shared.loaders.tasks = async () => {
    await loadTasks();
    if (shared.state.taskId) await openTask(shared.state.taskId);
  };

  document.getElementById("tasks-refresh").addEventListener("click", () => {
    shared.loaders.tasks().catch((error) => shared.report(document.getElementById("task-detail"), error));
  });

  document.getElementById("tasks-status").addEventListener("change", () => {
    loadTasks().catch((error) => shared.toast("Could not filter tasks", error.message, "err"));
  });

});
