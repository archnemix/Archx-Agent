"""HTTP endpoints for play. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import re


from typing import Any


from urllib.parse import unquote


from archx_agent.application import games as games_module


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class PlayRoutes:
    @route("GET", "/api/play/games", "Games, with the counts that make them readable.")
    def get_play_games(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        status = request.q("status")
        if status not in (None, "", "open", "finished", "abandoned"):
            raise ApiError(
                400, "validation", "status must be open, finished or abandoned"
            )
        games = self.ws.play_mode.games(
            status=status or None, limit=request.q_int("limit", 20)
        )
        return {
            "games": games,
            "stats": self.ws.play_mode.stats(),
            "games_available": sorted(games_module.GAMES),
        }

    @route(
        "POST", "/api/play/games", "Start a game; the rules build the initial board."
    )
    def post_play_game(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        seed = request.payload().get("seed")
        if seed is not None and not isinstance(seed, int):
            raise ApiError(400, "validation", "seed must be an integer")
        return self.ws.play_mode.new(request.text("game", required=False), seed=seed)

    @route(
        "GET",
        "/api/play/games/{game_id}",
        "The board, whose turn it is, and the legal moves.",
    )
    def get_play_game(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.view(
            unquote(match.group("game_id")), limit=request.q_int("moves", 12)
        )

    @route(
        "POST",
        "/api/play/games/{game_id}/move",
        "Propose a move; the rules accept it or say why not.",
    )
    def post_play_move(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        # A refused move is an answer, not a malformed request: 200 with `legal: false` and the
        # reason, so the page can show the referee saying no instead of an error banner.
        return self.ws.play_mode.move(
            unquote(match.group("game_id")),
            request.text("move", required=True) or "",
        )

    @route(
        "POST",
        "/api/play/games/{game_id}/engine",
        "Let the built-in engine play one move.",
    )
    def post_play_engine(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        seed = request.payload().get("seed")
        if seed is not None and not isinstance(seed, int):
            raise ApiError(400, "validation", "seed must be an integer")
        return self.ws.play_mode.engine_move(unquote(match.group("game_id")), seed=seed)

    @route(
        "POST", "/api/play/games/{game_id}/auto", "Let the engine play several moves."
    )
    def post_play_auto(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        plies = request.payload().get("plies", 1)
        if not isinstance(plies, int) or isinstance(plies, bool):
            raise ApiError(400, "validation", "plies must be an integer")
        return self.ws.play_mode.auto(unquote(match.group("game_id")), plies=plies)

    @route(
        "POST",
        "/api/play/games/{game_id}/resign",
        "Abandon a game; the moves stay readable.",
    )
    def post_play_resign(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.play_mode.resign(
            unquote(match.group("game_id")),
            winner=request.text("winner", required=False),
        )

    @route(
        "GET",
        "/api/play/games/{game_id}/history",
        "Every move, including the refused ones.",
    )
    def get_play_history(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.play_mode.history(unquote(match.group("game_id")))

    @route("GET", "/api/play/sims", "Recorded simulations, with their hashes.")
    def get_play_sims(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        sims = self.ws.play_mode.sims(limit=request.q_int("limit", 20))
        return {"sims": sims, "stats": self.ws.play_mode.stats()}

    @route(
        "POST", "/api/play/sims", "Run a deterministic simulation and record its hash."
    )
    def post_play_sim(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        numbers: dict[str, int] = {}
        for name, default in (
            ("width", 40),
            ("height", 20),
            ("steps", 20),
            ("seed", 0),
        ):
            value = request.payload().get(name, default)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ApiError(400, "validation", f"{name} must be an integer")
            numbers[name] = value
        density = request.payload().get("density", 0.3)
        if not isinstance(density, (int, float)) or isinstance(density, bool):
            raise ApiError(400, "validation", "density must be a number")
        return self.ws.play_mode.simulate(density=float(density), **numbers)

    @route(
        "GET",
        "/api/play/sims/{sim_id}",
        "One simulation: parameters, series, final grid.",
    )
    def get_play_sim(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.sim_view(unquote(match.group("sim_id")))

    @route(
        "POST",
        "/api/play/sims/{sim_id}/replay",
        "Recompute the simulation and check its hash.",
    )
    def post_play_replay(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        return self.ws.play_mode.replay(unquote(match.group("sim_id")))

    @route(
        "GET", "/api/play/stats", "Games, moves, refusals and simulations in this home."
    )
    def get_play_stats(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        return self.ws.play_mode.stats()
