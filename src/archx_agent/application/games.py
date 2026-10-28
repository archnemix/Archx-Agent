"""Three small games, as pure rules.

No workspace, no database, no model: :func:`rules_for` returns an object that can build a board,
list the moves that are legal *there*, apply one, and say whether the game is over. Everything
above this module - the record, the CLI, the page, the engine - is a caller, which is what makes
the games testable without a home directory and makes "the rules decide" a fact rather than a hope.

The rules are the only authority on legality. A move that a player, an engine or a model proposes
goes through :meth:`GameRules.apply` like any other, and comes back either a new board or a reason
it was refused. Nothing here knows how to take a move back.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from archx_agent.helpers.exceptions import ValidationError

BOARD_EMPTY = "."


@dataclass
class MoveResult:
    """What came of one proposed move: the new state, or the reason there is none."""

    legal: bool
    state: dict[str, Any]
    notation: str = ""
    reason: str | None = None
    over: bool = False
    winner: str | None = None


class GameRules:
    """The shared shape. Subclasses implement the four things that make a game a game."""

    name: str = "game"
    players: tuple[str, str] = ("one", "two")
    move_hint: str = ""

    def initial(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def render(self, state: dict[str, Any]) -> str:
        raise NotImplementedError

    def legal_moves(self, state: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def apply(self, state: dict[str, Any], move: str) -> MoveResult:
        raise NotImplementedError

    # -- shared ------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return False

    def turn(self, state: dict[str, Any]) -> str:
        return str(state.get("turn") or self.players[0])

    def outcome(self, state: dict[str, Any]) -> dict[str, Any]:
        """``{"over": bool, "winner": str | None, "reason": str}`` - the board decides, not the CLI."""
        used = state.get("moves", 0)
        if state.get("winner"):
            return {"over": True, "winner": state["winner"], "reason": "won"}
        if state.get("draw") or self._is_draw(state, used):
            return {"over": True, "winner": None, "reason": "draw"}
        return {"over": False, "winner": None, "reason": "in progress"}

    def _is_draw(self, state: dict[str, Any], used: int) -> bool:
        return False


# --------------------------------------------------------------------------
# tic-tac-toe
# --------------------------------------------------------------------------
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def _winner_of(cells: list[str]) -> str | None:
    for a, b, c in LINES:
        if cells[a] != BOARD_EMPTY and cells[a] == cells[b] == cells[c]:
            return cells[a]
    return None


class TicTacToe(GameRules):
    name = "tictactoe"
    players = ("X", "O")
    move_hint = "a square, 1-9 (top-left is 1)"

    def initial(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"cells": [BOARD_EMPTY] * 9, "turn": "X", "moves": 0, "winner": None, "draw": False}

    def render(self, state: dict[str, Any]) -> str:
        cells = state["cells"]
        rows = [
            " " + " | ".join(str(i + 1) if cells[i] == BOARD_EMPTY else cells[i] for i in row)
            for row in ((0, 1, 2), (3, 4, 5), (6, 7, 8))
        ]
        return "\n---+---+---\n".join(rows)

    def legal_moves(self, state: dict[str, Any]) -> list[str]:
        if self.outcome(state)["over"]:
            return []
        return [str(i + 1) for i, cell in enumerate(state["cells"]) if cell == BOARD_EMPTY]

    def apply(self, state: dict[str, Any], move: str) -> MoveResult:
        text = str(move).strip()
        over = self.outcome(state)
        if over["over"]:
            return MoveResult(False, state, reason="the game is over", **{"over": True,
                                                                        "winner": over["winner"]})
        if not text.isdigit() or not 1 <= int(text) <= 9:
            return MoveResult(False, state, reason=f"{move!r} is not a square; {self.move_hint}")
        index = int(text) - 1
        if state["cells"][index] != BOARD_EMPTY:
            return MoveResult(False, state, reason=f"square {text} is taken")
        player = self.turn(state)
        cells = list(state["cells"])
        cells[index] = player
        new = {**state, "cells": cells, "turn": "O" if player == "X" else "X",
               "moves": int(state.get("moves", 0)) + 1}
        winner = _winner_of(cells)
        if winner:
            new["winner"] = winner
        elif all(cell != BOARD_EMPTY for cell in cells):
            new["draw"] = True
        outcome = self.outcome(new)
        return MoveResult(True, new, notation=f"{text}", over=outcome["over"],
                          winner=outcome["winner"])


# --------------------------------------------------------------------------
# nim
# --------------------------------------------------------------------------
class Nim(GameRules):
    name = "nim"
    players = ("you", "them")
    move_hint = "HEAP,TAKE - for example 2,1 takes one from heap 2"

    def initial(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config or {}
        heaps = config.get("heaps") or [3, 4, 5]
        limit = int(config.get("max_take") or 3)
        if not heaps or any(int(heap) <= 0 for heap in heaps):
            raise ValidationError("every nim heap needs at least one token")
        return {"heaps": [int(heap) for heap in heaps], "max_take": limit, "turn": "you",
                "moves": 0, "winner": None, "draw": False}

    def render(self, state: dict[str, Any]) -> str:
        width = max(len(str(len(state["heaps"]))), 5)
        lines = []
        for index, heap in enumerate(state["heaps"], start=1):
            lines.append(f"heap {index:>{width}}: " + "|" * heap + f" ({heap})")
        return "\n".join(lines)

    def legal_moves(self, state: dict[str, Any]) -> list[str]:
        if self.outcome(state)["over"]:
            return []
        moves = []
        for index, heap in enumerate(state["heaps"], start=1):
            for take in range(1, min(int(state["max_take"]), heap) + 1):
                moves.append(f"{index},{take}")
        return moves

    def apply(self, state: dict[str, Any], move: str) -> MoveResult:
        over = self.outcome(state)
        if over["over"]:
            return MoveResult(False, state, reason="the game is over", **{"over": True,
                                                                        "winner": over["winner"]})
        if move not in self.legal_moves(state):
            return MoveResult(
                False, state, reason=f"{move!r} is not legal; {self.move_hint}",
            )
        heap_text, _, take_text = str(move).partition(",")
        heap_index, take = int(heap_text) - 1, int(take_text)
        heaps = list(state["heaps"])
        heaps[heap_index] -= take
        player = self.turn(state)
        new = {**state, "heaps": heaps, "turn": "them" if player == "you" else "you",
               "moves": int(state.get("moves", 0)) + 1}
        if not any(heaps):
            new["winner"] = player
        outcome = self.outcome(new)
        return MoveResult(True, new, notation=f"{heap_index + 1},{take}",
                          over=outcome["over"], winner=outcome["winner"])


# --------------------------------------------------------------------------
# connect four
# --------------------------------------------------------------------------
C4_COLUMNS, C4_ROWS = 7, 6


def _c4_cell(board: list[list[str]], column: int, row: int) -> str:
    """A cell, or "" off the board - a column that has not reached that row is still off it."""
    if not (0 <= column < C4_COLUMNS and 0 <= row < len(board[column])):
        return ""
    return board[column][row]


def _c4_won(board: list[list[str]], column: int, row: int, player: str) -> bool:
    """Is `player` four-in-a-row through this cell? The cell itself has to be theirs."""
    if _c4_cell(board, column, row) != player:
        return False
    for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count = 1
        for sign in (1, -1):
            step = 1
            while _c4_cell(board, column + dc * step * sign, row + dr * step * sign) == player:
                count += 1
                step += 1
        if count >= 4:
            return True
    return False


class ConnectFour(GameRules):
    name = "connect4"
    players = ("R", "Y")
    move_hint = "a column, 1-7; the disc falls"

    def initial(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"board": [[] for _ in range(C4_COLUMNS)], "turn": "R", "moves": 0,
                "winner": None, "draw": False}

    def render(self, state: dict[str, Any]) -> str:
        board = state["board"]
        lines = []
        for row in range(C4_ROWS - 1, -1, -1):
            cells = []
            for column in range(C4_COLUMNS):
                cells.append(board[column][row] if row < len(board[column]) else ".")
            lines.append(" " + " ".join(cells))
        lines.append(" " + " ".join(str(i + 1) for i in range(C4_COLUMNS)))
        return "\n".join(lines)

    def legal_moves(self, state: dict[str, Any]) -> list[str]:
        if self.outcome(state)["over"]:
            return []
        return [str(i + 1) for i, column in enumerate(state["board"]) if len(column) < C4_ROWS]

    def apply(self, state: dict[str, Any], move: str) -> MoveResult:
        over = self.outcome(state)
        if over["over"]:
            return MoveResult(False, state, reason="the game is over", **{"over": True,
                                                                        "winner": over["winner"]})
        text = str(move).strip()
        if not text.isdigit() or not 1 <= int(text) <= C4_COLUMNS:
            return MoveResult(False, state, reason=f"{move!r} is not a column; {self.move_hint}")
        column = int(text) - 1
        if len(state["board"][column]) >= C4_ROWS:
            return MoveResult(False, state, reason=f"column {text} is full")
        board = [list(heap) for heap in state["board"]]
        player = self.turn(state)
        board[column].append(player)
        row = len(board[column]) - 1
        new = {**state, "board": board, "turn": "Y" if player == "R" else "R",
               "moves": int(state.get("moves", 0)) + 1}
        if _c4_won(board, column, row, player):
            new["winner"] = player
        elif all(len(column_) == C4_ROWS for column_ in board):
            new["draw"] = True
        outcome = self.outcome(new)
        return MoveResult(True, new, notation=f"{column + 1}",
                          over=outcome["over"], winner=outcome["winner"])


GAMES = {"tictactoe": TicTacToe, "nim": Nim, "connect4": ConnectFour}


def rules_for(name: str) -> GameRules:
    key = str(name or "").strip().lower()
    if key not in GAMES:
        raise ValidationError(f"unknown game {name!r} (built in: {', '.join(sorted(GAMES))})")
    return GAMES[key]()


# --------------------------------------------------------------------------
# the engine: rules-based, deterministic, and never allowed to cheat
# --------------------------------------------------------------------------
class Engine:
    """A player that only ever proposes a legal move, because it picks from the legal list."""

    def __init__(self, rules: GameRules, *, seed: int | None = None) -> None:
        self.rules = rules
        self.random = random.Random(seed)

    def choose(self, state: dict[str, Any]) -> str:
        legal = self.rules.legal_moves(state)
        if not legal:
            raise ValidationError("there are no legal moves; the game is over")
        if self.rules.name == "tictactoe":
            return _ttt_choose(state, self.rules.turn(state))
        if self.rules.name == "nim":
            return _nim_choose(state)
        if self.rules.name == "connect4":
            return _c4_choose(state, self.rules.turn(state))
        return self.random.choice(legal)


def _ttt_choose(state: dict[str, Any], player: str) -> str:
    """Perfect play: win if you can, block if you must, otherwise take the best empty square."""
    cells = list(state["cells"])
    other = "O" if player == "X" else "X"

    def winning_move(mark: str) -> str | None:
        for index, cell in enumerate(cells):
            if cell != BOARD_EMPTY:
                continue
            trial = list(cells)
            trial[index] = mark
            if _winner_of(trial) == mark:
                return str(index + 1)
        return None

    move = winning_move(player) or winning_move(other)
    if move:
        return move
    for index in (4, 0, 2, 6, 8, 1, 3, 5, 7):  # centre, corners, edges
        if cells[index] == BOARD_EMPTY:
            return str(index + 1)
    raise ValidationError("no legal move")  # pragma: no cover - the caller checked


def _nim_choose(state: dict[str, Any]) -> str:
    """Normal-play nim: leave a zero XOR if possible, otherwise take one."""
    heaps = [int(heap) for heap in state["heaps"]]
    limit = int(state["max_take"])
    xor = 0
    for heap in heaps:
        xor ^= heap
    if xor:
        for index, heap in enumerate(heaps, start=1):
            target = heap ^ xor
            take = heap - target
            if 1 <= take <= min(limit, heap):
                return f"{index},{take}"
    for index, heap in enumerate(heaps, start=1):
        if heap:
            return f"{index},1"
    raise ValidationError("no legal move")  # pragma: no cover


def _c4_choose(state: dict[str, Any], player: str) -> str:
    """Two plies of looking ahead: win now, block a win, otherwise expand from the middle."""
    board = [list(column) for column in state["board"]]
    other = "Y" if player == "R" else "R"

    def wins_now(column: int, mark: str) -> bool:
        if len(board[column]) >= C4_ROWS:
            return False
        trial = [list(heap) for heap in board]
        trial[column].append(mark)
        return _c4_won(trial, column, len(trial[column]) - 1, mark)

    order = sorted(range(C4_COLUMNS), key=lambda column: abs(3 - column))
    for column in order:
        if wins_now(column, player):
            return str(column + 1)
    for column in order:
        if wins_now(column, other):
            return str(column + 1)
    for column in order:
        if len(board[column]) < C4_ROWS:
            return str(column + 1)
    raise ValidationError("no legal move")  # pragma: no cover
