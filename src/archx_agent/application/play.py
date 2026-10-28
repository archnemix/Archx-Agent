"""Play Mode: games and simulations you can check.

Why a game belongs in an agent
------------------------------
A game is the smallest honest test of agency there is. The rules are public, the state is small,
and "did the agent play well" is answerable without an opinion. Three things make that true here:

* **the rules are the only authority.** :mod:`archx_agent.application.games` decides what is legal,
  and this service never second-guesses it. The engine can only choose from ``legal_moves``, so a
  model that "cheats" is not possible by construction - not by review.
* **a refused move is evidence, not an error to hide.** When a proposed move is illegal it is
  written to ``game_moves`` with ``legal = 0`` and the reason, and the board does not move. A play
  log that only contains the moves that worked cannot show you that the rules held.
* **a simulation is reproducible.** ``play sim`` records the parameters and a hash of the final
  grid; ``play sim replay`` recomputes from the parameters alone and says whether the hash still
  matches. A record that cannot be replayed is a picture, not a result.

What this module does *not* claim: that the engine plays perfectly at connect four (it does not; it
is two plies deep), or that a simulation proves anything. It claims that what is stored is what
happened, and that the rules were asked rather than assumed.
"""

from __future__ import annotations

from typing import Any

from archx_agent.application import games as games_module
from archx_agent.application import simulations
from archx_agent.helpers.exceptions import ValidationError
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.play import Game

#: How many plies a single ``auto`` call may run before it stops and says so. An unbounded loop is
#: how a "let the engine play itself" feature turns into a hung terminal.
MAX_AUTO_PLIES = 120


class PlayService:
    """Games and simulations, backed by the rules in :mod:`application.games`."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.play

    def rules(self, game_type: str):
        try:
            return games_module.rules_for(game_type)
        except KeyError as exc:
            known = ", ".join(sorted(games_module.GAMES))
            raise ValidationError(f"unknown game: {game_type} (known: {known})") from exc

    def _game(self, game_id: str) -> Game:
        return self.manager.get_game(game_id)

    # -- games ------------------------------------------------------------
    def new(self, game_type: str | None = None, *, seed: int | None = None) -> dict[str, Any]:
        name = game_type or self.ws.config.get("play.default_game", "tictactoe")
        rules = self.rules(name)
        game = self.manager.create_game(
            rules.name, state=rules.initial(), seed=seed, metadata={"rule": getattr(rules, "RULE", "")}
        )
        return self.view(game.id)

    def view(self, game_id: str, *, limit: int = 20) -> dict[str, Any]:
        game = self._game(game_id)
        rules = self.rules(game.game_type)
        state = game.state
        outcome = rules.outcome(state)
        return {
            "id": game.id,
            "game_type": game.game_type,
            "status": game.status,
            "open": game.open,
            "turn": None if outcome["over"] else rules.turn(state),
            "board": rules.render(state),
            "legal_moves": [] if outcome["over"] else rules.legal_moves(state),
            "outcome": outcome,
            "moves": [m.to_dict() for m in self.manager.moves(game.id)[-int(limit):]],
            "move_count": game.move_count,
            "winner": game.winner,
            "seed": game.seed,
            "created_at": game.created_at,
        }

    def move(
        self, game_id: str, action: str, *, player: str | None = None, note: str | None = None
    ) -> dict[str, Any]:
        """Apply a move. An illegal move is recorded and the board does not change."""
        game = self._game(game_id)
        rules = self.rules(game.game_type)
        state = game.state
        if not game.open:
            raise ValidationError(f"game {game.id} is {game.status}; start a new one with `play new`")
        outcome = rules.outcome(state)
        if outcome["over"]:
            self.manager.update_game(game.id, status="finished", winner=outcome["winner"])
            raise ValidationError(f"the game is over: {outcome['reason']}")
        who = player or rules.turn(state)
        result = rules.apply(state, action)
        seq = game.move_count + 1
        if not result.legal:
            self.manager.record_move(
                game.id, seq=seq, player=who, action=str(action), legal=False, reason=result.reason
            )
            return {
                "legal": False,
                "reason": result.reason,
                "game_id": game.id,
                "player": who,
                "action": str(action),
                "turn": rules.turn(state),
                "board": rules.render(state),
                "outcome": outcome,
            }
        finished = rules.outcome(result.state)
        self.manager.record_move(
            game.id,
            seq=seq,
            player=who,
            action=result.notation,
            legal=True,
            state_hash=_hash_state(result.state),
        )
        self.manager.update_game(
            game.id,
            state=result.state,
            move_count=seq,
            status="finished" if finished["over"] else "open",
            winner=finished["winner"],
        )
        return {
            "legal": True,
            "reason": result.reason,
            "game_id": game.id,
            "player": who,
            "action": result.notation,
            "note": note,
            "board": rules.render(result.state),
            "turn": None if finished["over"] else rules.turn(result.state),
            "outcome": finished,
        }

    def engine_move(self, game_id: str, *, seed: int | None = None) -> dict[str, Any]:
        """Let the built-in engine play the side to move - always a legal move, by construction."""
        game = self._game(game_id)
        rules = self.rules(game.game_type)
        if not game.open:
            raise ValidationError(f"game {game.id} is {game.status}; start a new one with `play new`")
        if rules.outcome(game.state)["over"]:
            raise ValidationError("the game is over")
        choice = games_module.Engine(rules, seed=game.seed if seed is None else seed).choose(
            game.state
        )
        player = rules.turn(game.state)
        result = self.move(game.id, choice, player=player, note="engine")
        result["proposed"] = choice
        result["player"] = player
        return result

    def auto(self, game_id: str, *, plies: int = 1, seed: int | None = None) -> dict[str, Any]:
        """Play ``plies`` engine moves, stopping early when the game ends."""
        if plies < 1:
            raise ValidationError("plies must be at least 1")
        if plies > MAX_AUTO_PLIES:
            raise ValidationError(f"at most {MAX_AUTO_PLIES} plies per call")
        played: list[dict[str, Any]] = []
        for _ in range(int(plies)):
            game = self._game(game_id)
            if not game.open or self.rules(game.game_type).outcome(game.state)["over"]:
                break
            played.append(self.engine_move(game_id, seed=seed))
        view = self.view(game_id)
        view["played"] = played
        return view

    def resign(self, game_id: str, *, winner: str | None = None) -> dict[str, Any]:
        game = self._game(game_id)
        if not game.open:
            raise ValidationError(f"game {game.id} is already {game.status}")
        self.manager.update_game(game.id, status="abandoned", winner=winner)
        return self.view(game_id)

    def games(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [g.to_dict() for g in self.manager.games(status=status, limit=limit)]

    def history(self, game_id: str) -> dict[str, Any]:
        game = self._game(game_id)
        moves = self.manager.moves(game.id)
        return {
            "id": game.id,
            "game_type": game.game_type,
            "status": game.status,
            "winner": game.winner,
            "moves": [m.to_dict() for m in moves],
            "refused": [m.to_dict() for m in moves if not m.legal],
            "legal": sum(1 for m in moves if m.legal),
            "refused_count": sum(1 for m in moves if not m.legal),
        }

    # -- simulations ------------------------------------------------------
    def simulate(
        self,
        *,
        width: int = 40,
        height: int = 20,
        steps: int = 20,
        seed: int = 0,
        density: float = 0.3,
    ) -> dict[str, Any]:
        result = simulations.run(
            width=width, height=height, steps=steps, seed=seed, density=density
        )
        sim = self.manager.create_sim(
            "life",
            width=result["width"],
            height=result["height"],
            steps=result["steps"],
            seed=result["seed"],
            density=result["density"],
            final_hash=result["final_hash"],
            alive=result["alive"],
            series=result["series"],
            rows=result["rows"],
            metadata={"rule": result["rule"]},
        )
        return self.sim_view(sim.id)

    def sim_view(self, sim_id: str) -> dict[str, Any]:
        sim = self.manager.get_sim(sim_id)
        return sim.to_dict()

    def replay(self, sim_id: str) -> dict[str, Any]:
        """Recompute a simulation from its parameters and check the stored hash."""
        sim = self.manager.get_sim(sim_id)
        if not sim.final_hash:
            raise ValidationError(f"simulation {sim.id} has no hash to check")
        again = simulations.replay(sim.to_dict())
        return {
            "id": sim.id,
            "matches": again["matches"],
            "stored_hash": sim.final_hash,
            "recomputed_hash": again["final_hash"],
            "width": sim.width,
            "height": sim.height,
            "steps": sim.steps,
            "seed": sim.seed,
            "density": sim.density,
        }

    def sims(self, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.manager.sims(kind=kind, limit=limit)]

    def get_sim(self, sim_id: str):
        return self.manager.get_sim(sim_id)

    # -- summary ----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        counts = self.manager.stats()
        counts["games_available"] = sorted(games_module.GAMES)
        counts["default_game"] = self.ws.config.get("play.default_game", "tictactoe")
        return counts


def _hash_state(state: dict[str, Any]) -> str:
    """A hash of the position, so a replay can compare a move and not only the final answer."""
    import hashlib
    import json

    payload = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]

