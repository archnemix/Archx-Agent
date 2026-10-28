"""Rows for Play Mode: games and their moves, and the simulations that were run.

Two records, and the difference between them is the point:

``games`` / ``game_moves``
    A game is a state, and every move that produced it - *including the moves that were refused*.
    An illegal move is stored with ``legal = 0`` and the reason, because "the model proposed this
    and the rules said no" is exactly the thing a play mode has to be able to show. The state
    column holds the board as JSON, and a move row carries the hash of the state it produced, so a
    replay can compare positions and not only the final answer.

``play_sims``
    A simulation is deterministic: width, height, steps, seed, density in; a series and a hash of
    the final grid out. The hash is what makes "the same seed gives the same result" checkable
    rather than a claim.

Both tables were reserved by the v8 schema (``games``/``game_moves``) or added in v23
(``play_sims``); the games tables are adopted with ``ALTER TABLE`` so a home that already has them
keeps what it has.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.helpers.timeutil import iso_now, new_id

from .base import BaseManager

PLAY_TABLES = ("games", "game_moves", "play_sims")

GAME_STATUSES = ("open", "finished", "abandoned")
SIM_STATUSES = ("completed", "failed")


@dataclass
class Game:
    id: str
    game_type: str
    status: str
    state: dict[str, Any]
    created_at: str
    updated_at: str
    config: dict[str, Any] = field(default_factory=dict)
    winner: str | None = None
    seed: int | None = None
    move_count: int = 0
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.status == "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_type": self.game_type,
            "status": self.status,
            "open": self.open,
            "state": dict(self.state),
            "config": dict(self.config),
            "winner": self.winner,
            "seed": self.seed,
            "move_count": self.move_count,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class GameMove:
    id: int
    game_id: str
    seq: int
    player: str
    action: str
    created_at: str
    legal: bool = True
    reason: str | None = None
    state_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "seq": self.seq,
            "player": self.player,
            "action": self.action,
            "legal": self.legal,
            "reason": self.reason,
            "state_hash": self.state_hash,
            "created_at": self.created_at,
        }


@dataclass
class Simulation:
    id: str
    kind: str
    width: int
    height: int
    steps: int
    seed: int
    density: float
    status: str
    created_at: str
    final_hash: str | None = None
    alive: int | None = None
    series: list[int] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)
    task_id: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "seed": self.seed,
            "density": self.density,
            "status": self.status,
            "final_hash": self.final_hash,
            "alive": self.alive,
            "series": list(self.series),
            "rows": list(self.rows),
            "task_id": self.task_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }


def _loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - a hand-edited row
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _game_from_row(row: Mapping[str, Any]) -> Game:
    return Game(
        id=row["id"],
        game_type=row["game_type"],
        status=row["status"],
        state=_loads(row["state"], {}),
        config=_loads(row["config"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        winner=row["winner"],
        seed=row["seed"],
        move_count=int(row["move_count"] or 0),
        task_id=row["task_id"],
        metadata=_loads(row["metadata"], {}),
    )


def _move_from_row(row: Mapping[str, Any]) -> GameMove:
    return GameMove(
        id=int(row["id"]),
        game_id=row["game_id"],
        seq=int(row["seq"]),
        player=row["player"],
        action=row["action"],
        created_at=row["created_at"],
        legal=bool(row["legal"]),
        reason=row["reason"],
        state_hash=row["state_hash"],
    )


def _sim_from_row(row: Mapping[str, Any]) -> Simulation:
    return Simulation(
        id=row["id"],
        kind=row["kind"],
        width=int(row["width"]),
        height=int(row["height"]),
        steps=int(row["steps"]),
        seed=int(row["seed"]),
        density=float(row["density"]),
        status=row["status"],
        final_hash=row["final_hash"],
        alive=row["alive"],
        series=_loads(row["series"], []),
        rows=_loads(row["rows"], []),
        task_id=row["task_id"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        metadata=_loads(row["metadata"], {}),
    )


class PlayManager(BaseManager):
    """Rows for games, their moves and the simulations."""

    tables = PLAY_TABLES

    def register_handlers(self) -> None:
        self.coordinator.register("play.game", self._apply_game)
        self.coordinator.register("play.game_update", self._apply_game_update)
        self.coordinator.register("play.move", self._apply_move)
        self.coordinator.register("play.sim", self._apply_sim)

    # -- write handlers ---------------------------------------------------
    def _apply_game(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        game = payload["game"]
        tx.execute(
            "INSERT INTO games(id, game_type, status, state, config, created_at, updated_at,"
            " winner, seed, move_count, task_id, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                game["id"], game["game_type"], game["status"], json_text(game["state"]),
                json_text(game.get("config") or {}), game["created_at"], game["updated_at"],
                game.get("winner"), game.get("seed"), int(game.get("move_count") or 0),
                game.get("task_id"), json_text(game.get("metadata") or {}),
            ),
        )
        return {"id": game["id"]}

    def _apply_game_update(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        game_id = payload["id"]
        fields = dict(payload.get("fields") or {})
        allowed = {"status", "state", "winner", "move_count", "updated_at", "metadata", "task_id"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValidationError(f"cannot update game field(s): {', '.join(unknown)}")
        for key in ("state", "metadata"):
            if key in fields:
                fields[key] = json_text(fields[key] or {})
        if not fields:
            return {"id": game_id, "changed": 0}
        assignments = ", ".join(f"{name} = ?" for name in fields)
        tx.execute(f"UPDATE games SET {assignments} WHERE id = ?", (*fields.values(), game_id))
        return {"id": game_id, "changed": len(fields)}

    def _apply_move(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        move = payload["move"]
        tx.execute(
            "INSERT INTO game_moves(game_id, seq, player, action, created_at, legal, reason,"
            " state_hash) VALUES (?,?,?,?,?,?,?,?)",
            (
                move["game_id"], int(move["seq"]), move["player"], str(move["action"]),
                move["created_at"], 1 if move.get("legal") else 0, move.get("reason"),
                move.get("state_hash"),
            ),
        )
        return {"seq": move["seq"]}

    def _apply_sim(self, tx, payload: dict[str, Any]) -> dict[str, Any]:
        sim = payload["sim"]
        tx.execute(
            "INSERT INTO play_sims(id, kind, width, height, steps, seed, density, status,"
            " final_hash, alive, series, rows, task_id, created_at, completed_at, metadata)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sim["id"], sim["kind"], int(sim["width"]), int(sim["height"]), int(sim["steps"]),
                int(sim["seed"]), float(sim["density"]), sim["status"], sim.get("final_hash"),
                sim.get("alive"), json_text(sim.get("series") or []),
                json_text(sim.get("rows") or []), sim.get("task_id"), sim["created_at"],
                sim.get("completed_at"), json_text(sim.get("metadata") or {}),
            ),
        )
        return {"id": sim["id"]}

    # -- games ------------------------------------------------------------
    def create_game(
        self,
        game_type: str,
        *,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        seed: int | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Game:
        now = iso_now()
        game = Game(
            id=new_id("gm_"),
            game_type=game_type,
            status="open",
            state=state,
            config=dict(config or {}),
            created_at=now,
            updated_at=now,
            seed=seed,
            task_id=task_id,
            metadata=dict(metadata or {}),
        )
        self._write("play.game", {"game": game.to_dict()})
        self.trace(
            "play", "play.game", status="ok", task_id=task_id,
            payload={"game_id": game.id, "game_type": game_type, "seed": seed},
        )
        return game

    def update_game(self, game_id: str, **fields: Any) -> Game:
        self.get_game(game_id)
        self._write(
            "play.game_update",
            {"id": game_id, "fields": {**fields, "updated_at": iso_now()}},
        )
        return self.get_game(game_id)

    def record_move(
        self,
        game_id: str,
        *,
        seq: int,
        player: str,
        action: str,
        legal: bool = True,
        reason: str | None = None,
        state_hash: str | None = None,
    ) -> GameMove:
        game = self.get_game(game_id)
        if seq < 1:
            raise ValidationError("a move needs a sequence number of at least 1")
        self._write(
            "play.move",
            {
                "move": {
                    "game_id": game_id, "seq": int(seq), "player": player,
                    "action": str(action)[:200], "legal": bool(legal), "reason": reason,
                    "state_hash": state_hash, "created_at": iso_now(),
                }
            },
        )
        row = self.store.query_one(
            "SELECT * FROM game_moves WHERE game_id = ? AND seq = ? ORDER BY id DESC LIMIT 1",
            (game_id, int(seq)),
        )
        self.trace(
            "play", "play.move", status="ok" if legal else "error", task_id=game.task_id,
            payload={
                "game_id": game_id, "seq": int(seq), "player": player, "action": str(action)[:200],
                "legal": bool(legal), "reason": reason,
            },
        )
        return _move_from_row(row) if row else GameMove(
            id=0, game_id=game_id, seq=int(seq), player=player, action=str(action),
            created_at=iso_now(), legal=legal, reason=reason, state_hash=state_hash,
        )

    def get_game(self, game_id: str) -> Game:
        row = self.store.query_one("SELECT * FROM games WHERE id = ?", (game_id,))
        if row is None:
            raise NotFoundError(f"no such game: {game_id}")
        return _game_from_row(row)

    def find_game(self, game_id: str) -> Game | None:
        row = self.store.query_one("SELECT * FROM games WHERE id = ?", (game_id,))
        return _game_from_row(row) if row else None

    def games(
        self, *, status: str | None = None, game_type: str | None = None, limit: int = 50
    ) -> list[Game]:
        sql = "SELECT * FROM games"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if game_type:
            clauses.append("game_type = ?")
            params.append(game_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_game_from_row(row) for row in self.store.query(sql, params)]

    def moves(self, game_id: str) -> list[GameMove]:
        rows = self.store.query(
            "SELECT * FROM game_moves WHERE game_id = ? ORDER BY seq, id", (game_id,)
        )
        return [_move_from_row(row) for row in rows]

    # -- simulations ------------------------------------------------------
    def create_sim(
        self,
        kind: str,
        *,
        width: int,
        height: int,
        steps: int,
        seed: int,
        density: float,
        final_hash: str | None = None,
        alive: int | None = None,
        series: list[int] | None = None,
        rows: list[str] | None = None,
        status: str = "completed",
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Simulation:
        if status not in SIM_STATUSES:
            raise ValidationError(f"unknown simulation status: {status}")
        now = iso_now()
        sim = Simulation(
            id=new_id("sim_"),
            kind=kind,
            width=int(width),
            height=int(height),
            steps=int(steps),
            seed=int(seed),
            density=float(density),
            status=status,
            final_hash=final_hash,
            alive=alive,
            series=list(series or []),
            rows=list(rows or []),
            task_id=task_id,
            created_at=now,
            completed_at=now if status == "completed" else None,
            metadata=dict(metadata or {}),
        )
        self._write("play.sim", {"sim": sim.to_dict()})
        self.trace(
            "play", "play.sim", status="ok", task_id=task_id,
            payload={
                "sim_id": sim.id, "kind": kind, "seed": int(seed),
                "final_hash": final_hash, "alive": alive,
            },
        )
        return sim

    def get_sim(self, sim_id: str) -> Simulation:
        row = self.store.query_one("SELECT * FROM play_sims WHERE id = ?", (sim_id,))
        if row is None:
            raise NotFoundError(f"no such simulation: {sim_id}")
        return _sim_from_row(row)

    def sims(self, *, kind: str | None = None, limit: int = 50) -> list[Simulation]:
        sql = "SELECT * FROM play_sims"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        return [_sim_from_row(row) for row in self.store.query(sql, params)]

    # -- counts -----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return {
            "games": self.table_count("games"),
            "open": int(self.store.scalar("SELECT COUNT(*) FROM games WHERE status = 'open'") or 0),
            "finished": int(
                self.store.scalar("SELECT COUNT(*) FROM games WHERE status = 'finished'") or 0
            ),
            "moves": self.table_count("game_moves"),
            "refused_moves": int(
                self.store.scalar("SELECT COUNT(*) FROM game_moves WHERE legal = 0") or 0
            ),
            "sims": self.table_count("play_sims"),
        }
