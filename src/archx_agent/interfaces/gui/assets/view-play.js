/* play view: controls and API interactions. Registered before app.js; initialized by the shell. */
(window.ArchxViews ||= []).push((shared) => {
  "use strict";
  // -------------------------------------------------------------------- play
  // Two records, and the difference is the point: a game is a position plus every move that
  // produced it - including the moves the rules refused - and a simulation is a set of parameters
  // plus the hash of the grid they produced. Both are shown here from the server, never invented.
  function boardBlock(lines) {
    return shared.el("pre", { class: "board", text: Array.isArray(lines) ? lines.join("\n") : String(lines) });
  }

  function playAction(panel, label, path, body, after) {
    const button = shared.el("button", { type: "button", class: "btn", text: label });
    button.addEventListener("click", async () => {
      try {
        const result = await shared.api("POST", path, body || {});
        await after(result);
      } catch (error) {
        shared.report(panel, error);
      }
    });
    return button;
  }

  async function loadPlay() {
    shared.state.play = shared.state.play || {};
    const list = shared.clear(document.getElementById("play-games"));
    const data = await shared.api("GET", "/api/play/games");
    if (!data.games.length) list.append(shared.el("li", { class: "dim small", text: "no games yet" }));
    for (const game of data.games) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.play.id === game.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: game.game_type }),
        shared.el("span", {
          class: "s",
          text: game.status + " · " + game.move_count + " move(s)" + (game.winner ? " · " + game.winner : ""),
        }),
      ]);
      button.addEventListener("click", () => openGame(game.id).catch((error) => shared.report(document.getElementById("play-detail"), error)));
      list.append(shared.el("li", {}, [button]));
    }

    const sims = shared.clear(document.getElementById("play-sims"));
    const simData = await shared.api("GET", "/api/play/sims");
    if (!simData.sims.length) sims.append(shared.el("li", { class: "dim small", text: "no simulations yet" }));
    for (const sim of simData.sims) {
      const button = shared.el("button", { type: "button", class: "list-item" + (shared.state.play.simId === sim.id ? " active" : "") }, [
        shared.el("span", { class: "t", text: sim.width + "×" + sim.height + " · seed " + sim.seed }),
        shared.el("span", { class: "s", text: sim.steps + " step(s) · " + String(sim.final_hash || "").slice(0, 12) }),
      ]);
      button.addEventListener("click", () => openSim(sim.id).catch((error) => shared.report(document.getElementById("play-detail"), error)));
      sims.append(shared.el("li", {}, [button]));
    }
    return data;
  }

  async function openGame(gameId) {
    const panel = shared.clear(document.getElementById("play-detail"));
    shared.state.play = shared.state.play || {};
    shared.state.play.id = gameId;
    const game = await shared.api("GET", "/api/play/games/" + gameId);
    const outcome = game.outcome || {};

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: game.game_type + " · " + shared.shortId(game.id) }),
      shared.statusBadge(game.status),
    ]));
    panel.append(shared.el("div", { class: "row" }, [
      shared.toolChip("to move", game.open ? shared.text(game.turn) : "over"),
      shared.toolChip("moves", String(game.move_count)),
      shared.toolChip("result", outcome.over ? (outcome.winner || "draw") + " (" + outcome.reason + ")" : "in progress"),
    ]));
    panel.append(boardBlock(game.board));

    if (game.open) {
      const form = shared.el("form", { class: "row" });
      const input = shared.el("input", { type: "text", placeholder: game.legal_moves.length ? "one of " + game.legal_moves.slice(0, 6).join(", ") : "no moves left" });
      const status = shared.el("span", { class: "hint" });
      const submit = shared.el("button", { type: "submit", class: "btn primary", text: "Play it" });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const move = input.value.trim();
        if (!move) return;
        try {
          const result = await shared.api("POST", "/api/play/games/" + gameId + "/move", { move });
          if (!result.legal) {
            // The referee said no. That is an answer, and it was written down.
            status.textContent = "refused: " + result.reason;
            return;
          }
          await openGame(gameId);
        } catch (error) {
          status.textContent = "";
          shared.report(panel, error);
        }
      });
      form.append(input, submit, status);
      panel.append(form);

      if (game.legal_moves.length) {
        const chips = shared.el("div", { class: "row" });
        for (const move of game.legal_moves.slice(0, 12)) {
          chips.append(playAction(panel, move, "/api/play/games/" + gameId + "/move", { move }, () => openGame(gameId)));
        }
        panel.append(chips);
      }

      panel.append(shared.el("div", { class: "row" }, [
        playAction(panel, "Engine move", "/api/play/games/" + gameId + "/engine", {}, () => openGame(gameId)),
        playAction(panel, "Engine ×5", "/api/play/games/" + gameId + "/auto", { plies: 5 }, () => openGame(gameId)),
        playAction(panel, "Resign", "/api/play/games/" + gameId + "/resign", {}, () => openGame(gameId)),
      ]));
    }

    const history = await shared.api("GET", "/api/play/games/" + gameId + "/history");
    panel.append(shared.el("div", { class: "card-head" }, [
      shared.el("h3", { text: "Move log" }),
      shared.el("p", { class: "hint", text: history.refused_count + " of " + history.moves.length + " proposed move(s) were refused by the rules. They are kept: a log of only the moves that worked cannot show you that the rules held." }),
    ]));
    panel.append(shared.table(["seq", "player", "move", "legal", "why"], history.moves.map((move) => [
      shared.text(move.seq), shared.text(move.player), shared.text(move.action),
      move.legal ? "yes" : shared.el("span", { class: "dim", text: "no" }),
      move.legal ? "–" : shared.text(move.reason),
    ]), "no moves yet"));
    await loadPlay();
  }

  async function openSim(simId) {
    const panel = shared.clear(document.getElementById("play-detail"));
    shared.state.play = shared.state.play || {};
    shared.state.play.simId = simId;
    const sim = await shared.api("GET", "/api/play/sims/" + simId);

    panel.append(shared.el("div", { class: "row between" }, [
      shared.el("h2", { text: "simulation · " + shared.shortId(sim.id) }),
      shared.statusBadge(sim.status),
    ]));
    panel.append(shared.el("div", { class: "row" }, [
      shared.toolChip("size", sim.width + "×" + sim.height),
      shared.toolChip("steps", String(sim.steps)),
      shared.toolChip("seed", String(sim.seed)),
      shared.toolChip("alive", shared.text(sim.alive)),
    ]));
    panel.append(shared.el("p", { class: "small dim", text: "series: " + (sim.series || []).join(", ") }));
    panel.append(shared.el("p", { class: "small", text: "hash: " + String(sim.final_hash || "") }));
    panel.append(boardBlock((sim.rows || []).join("\n")));

    const verdict = shared.el("div", { class: "stack" });
    const replay = shared.el("button", { type: "button", class: "btn primary", text: "Replay and check the hash" });
    replay.addEventListener("click", async () => {
      try {
        const check = await shared.api("POST", "/api/play/sims/" + simId + "/replay", {});
        shared.clear(verdict);
        verdict.append(shared.el("p", {
          class: check.matches ? "small" : "small dim",
          text: check.matches
            ? "reproduced: the parameters still produce " + check.recomputed_hash.slice(0, 16) + "…"
            : "DIFFERENT: stored " + check.stored_hash.slice(0, 16) + "… but these parameters give " + check.recomputed_hash.slice(0, 16) + "…",
        }));
      } catch (error) {
        shared.report(verdict, error);
      }
    });
    panel.append(shared.el("div", { class: "row" }, [replay]));
    panel.append(verdict);
    await loadPlay();
  }

  shared.loaders.play = async () => {
    await loadPlay();
    if (shared.state.play && shared.state.play.simId) await openSim(shared.state.play.simId);
    else if (shared.state.play && shared.state.play.id) await openGame(shared.state.play.id);
  };

  document.getElementById("play-refresh").addEventListener("click", () => {
    shared.loaders.play().catch((error) => shared.report(document.getElementById("play-detail"), error));
  });

  document.getElementById("play-new-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("play-new-status");
    status.textContent = "";
    const body = { game: document.getElementById("play-game-type").value };
    const seed = document.getElementById("play-seed").value.trim();
    if (seed) body.seed = Number(seed);
    try {
      const game = await shared.api("POST", "/api/play/games", body);
      document.getElementById("play-seed").value = "";
      await openGame(game.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

  document.getElementById("play-sim-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("play-sim-status");
    status.textContent = "";
    const body = {};
    for (const name of ["width", "height", "steps", "seed"]) {
      const raw = document.getElementById("play-sim-" + name).value.trim();
      if (raw) body[name] = Number(raw);
    }
    const density = document.getElementById("play-sim-density").value.trim();
    if (density) body.density = Number(density);
    try {
      const sim = await shared.api("POST", "/api/play/sims", body);
      await openSim(sim.id);
    } catch (error) {
      shared.report(status, error);
    }
  });

});
