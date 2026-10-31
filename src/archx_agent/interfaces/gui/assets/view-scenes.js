/* scenes view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- scenes
  let selectedScene = null;
  const sceneStatus = () => document.getElementById("scenes-status");
  async function loadScenes() {
    const data = await shared.api("GET", "/api/scenes");
    const list = shared.clear(document.getElementById("scenes-list"));
    for (const scene of data.scenes) {
      const button = shared.el("button", { type: "button", class: "list-item", text: scene.name + " · " + scene.triangles + " triangles" });
      button.addEventListener("click", () => openScene(scene.id).catch(error => shared.report(sceneStatus(), error)));
      list.append(shared.el("li", {}, [button]));
    }
  }
  async function sceneAction(action, payload = {}) {
    const result = await shared.api("POST", "/api/scenes/" + encodeURIComponent(selectedScene) + "/" + action, payload);
    await loadScenes();
    await openScene(selectedScene);
    sceneStatus().textContent = JSON.stringify(result, null, 2);
    return result;
  }
  async function openScene(id) {
    const data = await shared.api("GET", "/api/scenes/" + encodeURIComponent(id));
    selectedScene = id;
    const panel = shared.clear(document.getElementById("scene-detail"));
    panel.append(shared.el("h2", { text: data.name }));
    panel.append(shared.el("p", { text: "Wireframe only · local rendering requires Blender and execution permissions." }));
    panel.append(shared.el("pre", { text: JSON.stringify(data.measured, null, 2) }));
    if (data.drifted) panel.append(shared.el("p", { class: "hint", text: "Document changed since measurement. Verify before accepting a new baseline." }));
    for (const object of data.objects_detail) {
      const row = shared.el("div", { class: "card" }, [shared.el("p", { text: object.name + " · " + object.primitive + " · " + object.triangles + " triangles · " + (object.watertight ? "closed edges" : "open edges") })]);
      const remove = shared.el("button", { type: "button", text: "Remove " + object.name });
      remove.addEventListener("click", () => sceneAction("remove", { name: object.name }).catch(error => shared.report(sceneStatus(), error)));
      row.append(remove);
      panel.append(row);
    }
    for (const action of ["preview", "verify", "measure", "render"]) {
      const button = shared.el("button", { type: "button", text: action === "measure" ? "Accept measurement baseline" : action });
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await sceneAction(action);
          if (action === "preview") {
            // Image context, not inline SVG markup: scene content cannot create page scripts.
            document.getElementById("scene-detail").append(shared.el("img", {
              src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(result.svg),
              alt: "Perspective wireframe, not a render", width: "480", height: "480"
            }));
          }
        } catch (error) { shared.report(sceneStatus(), error); }
        finally { button.disabled = false; }
      });
      panel.append(button);
    }
    for (const kind of ["obj", "stl", "svg", "script"]) {
      const button = shared.el("button", { type: "button", text: "Export " + kind });
      button.addEventListener("click", () => sceneAction("export", { kind }).catch(error => shared.report(sceneStatus(), error)));
      panel.append(button);
    }
    panel.append(shared.el("pre", { text: JSON.stringify(data.outputs, null, 2) }));
    document.getElementById("scene-add-form").hidden = false;
  }
  shared.loaders.scenes = loadScenes;
  document.getElementById("scenes-refresh").addEventListener("click", () => loadScenes().catch(error => shared.report(sceneStatus(), error)));
  document.getElementById("scene-create-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const data = await shared.api("POST", "/api/scenes", { name: document.getElementById("scene-name").value.trim(), task_id: document.getElementById("scene-task").value.trim() || undefined });
      await loadScenes();
      await openScene(data.id);
    } catch (error) { shared.report(sceneStatus(), error); }
  });
  document.getElementById("scene-add-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await sceneAction("add", {
        primitive: document.getElementById("scene-primitive").value,
        name: document.getElementById("scene-object-name").value.trim() || undefined,
        params: JSON.parse(document.getElementById("scene-params").value)
      });
    } catch (error) { shared.report(sceneStatus(), error); }
  });

});
