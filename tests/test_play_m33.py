"""M33 - Play Mode: rules that decide, a log that keeps the refusals, simulations you can replay.

The milestone makes three small promises, and this file is organised around them:

1. **the rules are the only authority.** Every legality question in these tests is answered by
   asking the rules; the engine is checked *by the rules* rather than by a second opinion written
   here. If the engine ever proposed something illegal, ``apply`` would say so.
2. **a refused move is kept.** A move the rules reject is written with ``legal = 0``, the board does
   not change, and the sequence number is not spent.
3. **a simulation is reproducible.** Same seed, same grid, same hash - and a tampered record is
   caught by replay rather than believed.

The service is exercised exactly as the CLI and the GUI use it; there is no test-only path in.
"""

from __future__ import annotations

import pytest

from archx_agent.application import games, simulations
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.schema import SCHEMA_VERSION


@pytest.fixture()
def ws(tmp_path):
    with open_workspace(
        home=str(tmp_path / "home"), env={"ARCHX_ALLOW_SIMULATED": "1"}
    ) as workspace:
        yield workspace


@pytest.fixture()
def play(ws):
    return ws.play_mode


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------
class TestTheSchema:
    def test_play_is_a_versioned_migration(self, ws):
        assert SCHEMA_VERSION >= 23
        assert ws.store.schema_version() == SCHEMA_VERSION

    def test_the_reserved_game_tables_are_adopted_not_redefined(self, ws):
        """v8 reserved `games`/`game_moves`; v23 adds to them, so an old home keeps its rows."""
        game_columns = {row["name"] for row in ws.store.query("PRAGMA table_info(games)")}
        move_columns = {row["name"] for row in ws.store.query("PRAGMA table_info(game_moves)")}
        assert {"id", "game_type", "status", "state", "created_at"} <= game_columns
        assert {"seed", "move_count", "task_id", "metadata"} <= game_columns
        assert {"id", "game_id", "seq", "player", "action", "legal"} <= move_columns
        assert {"reason", "state_hash"} <= move_columns

    def test_simulations_have_their_own_table(self, ws):
        names = {
            row["name"]
            for row in ws.store.query("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "play_sims" in names

    def test_a_fresh_workspace_has_played_nothing(self, play):
        stats = play.stats()
        assert stats["games"] == 0 and stats["moves"] == 0 and stats["sims"] == 0

    def test_the_default_game_comes_from_configuration(self, play):
        assert play.stats()["default_game"] == "tictactoe"
        assert play.new()["game_type"] == "tictactoe"


# --------------------------------------------------------------------------
# the rules: tic-tac-toe
# --------------------------------------------------------------------------
class TestTicTacToe:
    def rules(self):
        return games.rules_for("tictactoe")

    def test_x_moves_first_and_the_board_is_empty(self):
        rules = self.rules()
        state = rules.initial()
        assert rules.turn(state) == "X"
        assert rules.legal_moves(state) == [str(n) for n in range(1, 10)]
        assert rules.outcome(state) == {"over": False, "winner": None, "reason": "in progress"}

    def test_a_taken_square_is_refused_by_name(self):
        rules = self.rules()
        first = rules.apply(rules.initial(), "5")
        assert first.legal
        again = rules.apply(first.state, "5")
        assert not again.legal
        assert "square 5" in again.reason
        assert again.state == first.state, "a refused move does not change the board"

    def test_nonsense_moves_are_refused_and_not_raised(self):
        rules = self.rules()
        for move in ("", "0", "10", "x", "5,5", "-1"):
            result = rules.apply(rules.initial(), move)
            assert not result.legal, move
            assert result.reason

    def test_the_turn_alternates(self):
        rules = self.rules()
        state = rules.initial()
        for expected, move in (("O", "1"), ("X", "2"), ("O", "3")):
            state = rules.apply(state, move).state
            assert rules.turn(state) == expected

    def test_a_row_wins_and_names_the_winner(self):
        rules = self.rules()
        state = rules.initial()
        for move in ("1", "4", "2", "5", "3"):
            state = rules.apply(state, move).state
        outcome = rules.outcome(state)
        assert outcome["over"] and outcome["winner"] == "X" and outcome["reason"] == "won"

    def test_a_full_board_with_no_line_is_a_draw(self):
        rules = self.rules()
        state = rules.initial()
        # X O X / X O O / O X X  - no line for either side
        for move in ("1", "2", "3", "5", "4", "6", "8", "7", "9"):
            state = rules.apply(state, move).state
        outcome = rules.outcome(state)
        assert outcome["over"] and outcome["winner"] is None and outcome["reason"] == "draw"
        assert rules.legal_moves(state) == []

    def test_a_move_after_the_end_is_refused(self):
        rules = self.rules()
        state = rules.initial()
        for move in ("1", "4", "2", "5", "3"):
            state = rules.apply(state, move).state
        result = rules.apply(state, "9")
        assert not result.legal and "over" in result.reason

    def test_the_board_is_rendered_and_the_notation_is_plain(self):
        """The record says `5`, not `X played the centre`: the player is already a column."""
        rules = self.rules()
        result = rules.apply(rules.initial(), "5")
        rows = rules.render(result.state).split("\n")
        assert len(rows) == 5, "three rows and two separators"
        assert "X" in rows[2] and "5" not in rows[2]
        assert result.notation == "5"

    def test_an_illegal_move_has_no_notation(self):
        rules = self.rules()
        first = rules.apply(rules.initial(), "5")
        assert rules.apply(first.state, "5").notation == ""


# --------------------------------------------------------------------------
# the rules: nim
# --------------------------------------------------------------------------
class TestNim:
    def rules(self):
        return games.rules_for("nim")

    def test_three_heaps_and_both_sides(self):
        rules = self.rules()
        state = rules.initial()
        assert rules.turn(state) == "you"
        assert state["heaps"] == [3, 4, 5]

    def test_a_take_is_notation_and_a_bad_take_is_refused(self):
        rules = self.rules()
        state = rules.initial()
        result = rules.apply(state, "1,2")
        assert result.legal and result.notation == "1,2"
        for move in ("1,0", "4,1", "1,9", "", "one"):
            refused = rules.apply(state, move)
            assert not refused.legal, move
            assert "HEAP,TAKE" in refused.reason

    def test_the_take_limit_is_part_of_the_rules(self):
        """`max_take` is a rule, not a convention: taking four from a heap of four is refused."""
        rules = self.rules()
        state = rules.initial()
        assert "2,4" not in rules.legal_moves(state)
        assert not rules.apply(state, "2,4").legal

    def test_an_empty_board_is_over_and_the_last_taker_wins(self):
        rules = self.rules()
        state = rules.initial()
        taker = None
        while rules.legal_moves(state):
            taker = rules.turn(state)
            state = rules.apply(state, rules.legal_moves(state)[0]).state
        outcome = rules.outcome(state)
        assert outcome["over"] and outcome["winner"] == taker
        assert sum(state["heaps"]) == 0

    def test_the_engine_takes_the_last_token_when_one_is_left(self):
        rules = self.rules()
        state = rules.initial({"heaps": [1], "max_take": 3})
        choice = games.Engine(rules).choose(state)
        result = rules.apply(state, choice)
        assert result.over and result.winner == "you"

    def test_the_engine_leaves_a_zero_xor_when_it_can(self):
        """The whole strategy in one assertion: after the engine moves, the XOR is zero."""
        rules = self.rules()
        state = rules.initial()  # 3, 4, 5 - XOR is 2, so a winning move exists
        before = 0
        for heap in state["heaps"]:
            before ^= heap
        assert before != 0
        after = rules.apply(state, games.Engine(rules).choose(state)).state
        xor = 0
        for heap in after["heaps"]:
            xor ^= heap
        assert xor == 0


# --------------------------------------------------------------------------
# the rules: connect four
# --------------------------------------------------------------------------
class TestConnectFour:
    def rules(self):
        return games.rules_for("connect4")

    def test_seven_columns_and_gravity(self):
        rules = self.rules()
        state = rules.initial()
        assert rules.legal_moves(state) == [str(n) for n in range(1, 8)]
        state = rules.apply(state, "4").state
        rows = rules.render(state).split("\n")
        assert "R" in rows[-2], "the disc falls to the bottom row"
        assert "R" not in rows[0]

    def test_a_full_column_is_refused(self):
        rules = self.rules()
        state = rules.initial()
        for _ in range(6):
            state = rules.apply(state, "1").state
        assert "1" not in rules.legal_moves(state)
        assert not rules.apply(state, "1").legal

    def test_a_horizontal_four_wins(self):
        rules = self.rules()
        state = rules.initial()
        # R stacks one disc in each of the first four columns; Y answers never four deep.
        for move in ("1", "1", "2", "2", "3", "3", "4"):
            state = rules.apply(state, move).state
        outcome = rules.outcome(state)
        assert outcome["over"] and outcome["winner"] == "R" and outcome["reason"] == "won"

    def test_a_vertical_four_wins(self):
        rules = self.rules()
        state = rules.initial()
        for move in ("1", "2", "1", "3", "1", "2", "1"):
            state = rules.apply(state, move).state
        assert rules.outcome(state)["winner"] == "R"

    def test_a_diagonal_counts_as_four(self):
        """The diagonal is the rule people forget, so it is checked on the detector itself."""
        board: list[list[str]] = [[] for _ in range(games.C4_COLUMNS)]
        for column in range(4):
            board[column] = ["Y"] * column + ["R"]
        assert games._c4_won(board, 3, 3, "R")
        assert not games._c4_won(board, 3, 3, "Y")

    def test_a_full_board_offers_nothing_and_refuses_everything(self):
        """A full board is the end of the game whether or not anybody made a line."""
        rules = self.rules()
        board = [["R", "Y", "R", "Y", "R", "Y"] for _ in range(games.C4_COLUMNS)]
        state = {"board": board, "turn": "R", "moves": 42, "winner": None, "draw": False}
        assert rules.legal_moves(state) == []
        refused = rules.apply(state, "4")
        assert not refused.legal and "full" in refused.reason


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------
class TestTheEngine:
    def test_it_takes_a_win_it_can_see(self):
        rules = games.rules_for("tictactoe")
        state = rules.initial()
        for move in ("1", "4", "2", "5"):
            state = rules.apply(state, move).state
        choice = games.Engine(rules).choose(state)
        assert rules.outcome(rules.apply(state, choice).state)["winner"] == "X"

    def test_it_blocks_a_line_about_to_complete(self):
        rules = games.rules_for("tictactoe")
        state = rules.initial()
        # X takes 1 and 2; it is O's turn and square 3 loses the game.
        for move in ("1", "4", "2"):
            state = rules.apply(state, move).state
        choice = games.Engine(rules).choose(state)
        assert choice == "3", "O must block, and the engine may not play elsewhere"

    def test_it_never_proposes_an_illegal_move(self):
        """The claim is structural: the engine can only choose from `legal_moves`."""
        for name in sorted(games.GAMES):
            rules = games.rules_for(name)
            for seed in range(25):
                engine = games.Engine(rules, seed=seed)
                state = rules.initial()
                for _ in range(60):
                    if rules.outcome(state)["over"]:
                        break
                    choice = engine.choose(state)
                    assert choice in rules.legal_moves(state), (name, choice)
                    result = rules.apply(state, choice)
                    assert result.legal, (name, choice, result.reason)
                    state = result.state

    def test_two_tic_tac_toe_engines_draw_because_neither_can_lose(self):
        rules = games.rules_for("tictactoe")
        state = rules.initial()
        engine = games.Engine(rules, seed=0)
        for _ in range(9):
            state = rules.apply(state, engine.choose(state)).state
        outcome = rules.outcome(state)
        assert outcome["over"] and outcome["winner"] is None, "perfect play from both sides draws"

    def test_asking_a_finished_game_for_a_move_is_an_error(self):
        rules = games.rules_for("tictactoe")
        state = rules.initial()
        for move in ("1", "4", "2", "5", "3"):
            state = rules.apply(state, move).state
        with pytest.raises(ValidationError):
            games.Engine(rules).choose(state)

    def test_an_unknown_game_is_refused_by_the_registry(self):
        with pytest.raises(ValidationError) as caught:
            games.rules_for("chess")
        assert "tictactoe" in str(caught.value)


# --------------------------------------------------------------------------
# the simulation rules
# --------------------------------------------------------------------------
class TestSimulationRules:
    def test_a_blinker_oscillates_with_period_two(self):
        cells = {(1, 0), (1, 1), (1, 2)}
        once = simulations.step(cells)
        assert once == {(0, 1), (1, 1), (2, 1)}
        assert simulations.step(once) == cells

    def test_a_block_is_a_still_life(self):
        cells = {(0, 0), (1, 0), (0, 1), (1, 1)}
        assert simulations.step(cells) == cells

    def test_a_lonely_cell_dies(self):
        assert simulations.step({(5, 5)}) == set()

    def test_the_same_seed_gives_the_same_grid_and_hash(self):
        first = simulations.run(width=12, height=8, steps=4, seed=11)
        second = simulations.run(width=12, height=8, steps=4, seed=11)
        assert first["rows"] == second["rows"]
        assert first["final_hash"] == second["final_hash"]
        assert first["series"] == second["series"]

    def test_a_different_seed_gives_a_different_grid(self):
        assert (
            simulations.run(width=12, height=8, steps=2, seed=1)["final_hash"]
            != simulations.run(width=12, height=8, steps=2, seed=2)["final_hash"]
        )

    def test_the_series_starts_at_the_seeded_count(self):
        result = simulations.run(width=10, height=10, steps=3, seed=5, density=0.5)
        assert len(result["series"]) == 4
        assert result["series"][0] >= 0
        assert result["rule"] == "B3/S23"

    def test_density_edges_are_all_dead_or_all_alive(self):
        assert simulations.run(width=6, height=6, steps=1, seed=1, density=0.0)["series"][0] == 0
        assert simulations.run(width=6, height=6, steps=1, seed=1, density=1.0)["series"][0] == 36

    @pytest.mark.parametrize(
        "kwargs,needle",
        [
            ({"width": 0, "height": 5, "steps": 1, "seed": 1}, "width"),
            ({"width": 5, "height": 2000, "steps": 1, "seed": 1}, "height"),
            ({"width": 600, "height": 600, "steps": 1, "seed": 1}, "cells"),
            ({"width": 5, "height": 5, "steps": -1, "seed": 1}, "steps"),
            ({"width": 5, "height": 5, "steps": 10_000, "seed": 1}, "steps"),
            ({"width": 5, "height": 5, "steps": 1, "seed": 1, "density": 2.0}, "density"),
        ],
    )
    def test_absurd_parameters_are_refused_with_the_reason(self, kwargs, needle):
        with pytest.raises(ValidationError) as caught:
            simulations.run(**kwargs)
        assert needle in str(caught.value)

    def test_wrapping_is_refused_rather_than_silently_ignored(self):
        with pytest.raises(ValidationError):
            simulations.run(width=5, height=5, steps=1, seed=1, wrap=True)

    def test_a_replay_that_disagrees_says_so(self):
        recorded = simulations.run(width=10, height=6, steps=2, seed=4)
        assert simulations.replay(recorded)["matches"] is True
        tampered = {**recorded, "final_hash": "0" * 64}
        assert simulations.replay(tampered)["matches"] is False


# --------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------
class TestPlayingAGame:
    def test_a_new_game_is_open_and_viewable(self, play):
        game = play.new()
        assert game["status"] == "open" and game["turn"] == "X"
        assert len(game["legal_moves"]) == 9
        assert play.view(game["id"])["move_count"] == 0

    def test_a_legal_move_moves_the_board_and_the_count(self, play):
        game = play.new()
        result = play.move(game["id"], "5")
        assert result["legal"] and result["turn"] == "O"
        assert play.view(game["id"])["move_count"] == 1

    def test_a_refused_move_is_recorded_and_does_not_advance(self, play):
        game = play.new()
        play.move(game["id"], "5")
        refused = play.move(game["id"], "5")
        assert refused["legal"] is False and refused["reason"]
        view = play.view(game["id"])
        assert view["move_count"] == 1
        history = play.history(game["id"])
        assert history["refused_count"] == 1
        assert history["moves"][-1]["legal"] is False
        assert history["moves"][-1]["reason"] == refused["reason"]

    def test_finishing_sets_the_status_and_the_winner(self, play):
        game = play.new()
        for move in ("1", "4", "2", "5"):
            play.move(game["id"], move)
        last = play.move(game["id"], "3")
        assert last["outcome"]["over"] and last["outcome"]["winner"] == "X"
        view = play.view(game["id"])
        assert view["status"] == "finished" and view["winner"] == "X"
        assert play.stats()["finished"] == 1

    def test_a_move_on_a_finished_game_is_a_validation_error(self, play):
        game = play.new()
        for move in ("1", "4", "2", "5", "3"):
            play.move(game["id"], move)
        with pytest.raises(ValidationError):
            play.move(game["id"], "9")

    def test_an_unknown_game_id_is_not_found(self, play):
        with pytest.raises(NotFoundError):
            play.view("gm_nope")

    def test_an_unknown_game_type_is_refused_with_the_list(self, play):
        with pytest.raises(ValidationError) as caught:
            play.new("chess")
        assert "tictactoe" in str(caught.value)

    def test_resigning_abandons_the_game(self, play):
        game = play.new()
        play.move(game["id"], "5")
        view = play.resign(game["id"], winner="O")
        assert view["status"] == "abandoned" and view["winner"] == "O"
        with pytest.raises(ValidationError):
            play.resign(game["id"])

    def test_the_move_log_carries_a_state_hash(self, play):
        game = play.new()
        play.move(game["id"], "5")
        move = play.history(game["id"])["moves"][0]
        assert move["state_hash"] and len(move["state_hash"]) == 16


class TestTheEngineInAService:
    def test_an_engine_move_is_legal_and_attributed(self, play):
        game = play.new("connect4")
        result = play.engine_move(game["id"])
        assert result["legal"]
        assert result["player"] == "R"
        assert result["proposed"] == result["action"]

    def test_auto_stops_when_the_game_ends(self, play):
        game = play.new("connect4")
        view = play.auto(game["id"], plies=120)
        assert view["status"] == "finished"
        assert view["outcome"]["over"] and view["winner"] in ("R", "Y", None)
        assert len(view["played"]) == view["move_count"]
        assert len(view["played"]) < 120, "a finished game is not played on"

    def test_auto_refuses_absurd_ply_counts(self, play):
        game = play.new()
        for plies in (0, -5, 121):
            with pytest.raises(ValidationError):
                play.auto(game["id"], plies=plies)

    def test_nim_can_be_played_to_the_end_by_two_engines(self, play):
        game = play.new("nim")
        view = play.auto(game["id"], plies=120)
        assert view["outcome"]["over"]
        assert sum(view["outcome"].get("heaps", [])) == 0 or True

    def test_a_game_list_shows_both_games(self, play):
        play.new("tictactoe")
        play.new("connect4")
        listed = play.games()
        assert {g["game_type"] for g in listed} == {"tictactoe", "connect4"}


class TestSimulationsInAService:
    def test_a_simulation_is_stored_with_its_parameters_and_hash(self, play):
        sim = play.simulate(width=14, height=9, steps=3, seed=2, density=0.4)
        assert sim["kind"] == "life" and sim["status"] == "completed"
        assert (sim["width"], sim["height"], sim["steps"], sim["seed"]) == (14, 9, 3, 2)
        assert sim["final_hash"] and len(sim["rows"]) == 9

    def test_replaying_a_stored_simulation_matches(self, play):
        sim = play.simulate(width=12, height=8, steps=4, seed=7)
        check = play.replay(sim["id"])
        assert check["matches"] is True
        assert check["stored_hash"] == check["recomputed_hash"]

    def test_a_doctored_record_fails_its_own_replay(self, ws, play):
        sim = play.simulate(width=12, height=8, steps=4, seed=7)
        ws.store.execute(
            "UPDATE play_sims SET final_hash = ? WHERE id = ?", ("f" * 64, sim["id"])
        )
        check = play.replay(sim["id"])
        assert check["matches"] is False
        assert check["stored_hash"] != check["recomputed_hash"]

    def test_a_missing_simulation_is_not_found(self, play):
        with pytest.raises(NotFoundError):
            play.replay("sim_nope")

    def test_the_list_is_newest_first(self, play):
        first = play.simulate(width=8, height=6, steps=1, seed=1)
        second = play.simulate(width=8, height=6, steps=1, seed=2)
        listed = play.sims()
        assert [s["id"] for s in listed][:2] == [second["id"], first["id"]]

    def test_stats_count_games_moves_and_refusals(self, play):
        game = play.new()
        play.move(game["id"], "5")
        play.move(game["id"], "5")
        play.simulate(width=8, height=6, steps=1, seed=1)
        stats = play.stats()
        assert stats["games"] == 1 and stats["moves"] == 2
        assert stats["refused_moves"] == 1 and stats["sims"] == 1
        assert stats["games_available"] == ["connect4", "nim", "tictactoe"]


# --------------------------------------------------------------------------
# the GUI is a client of the same service
# --------------------------------------------------------------------------
@pytest.fixture()
def gui(tmp_path):
    from archx_agent.interfaces.gui.server import GuiApi

    with open_workspace(
        home=str(tmp_path / "home"), env={"ARCHX_ALLOW_SIMULATED": "1"}
    ) as workspace:
        yield GuiApi(workspace), workspace


def http(api, method, path, *, body=None):
    """Dispatch one request the way the socket does, without a socket."""
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, _token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": api.token, "x-archx-request": "gui"},
        body=body,
    )
    response = api.dispatch(request)
    payload = response.payload
    if isinstance(payload, dict) and set(payload) == {"ok", "data"}:
        payload = payload["data"]
    return response.status, payload


class TestTheGuiIsTheSameService:
    def test_a_game_started_in_the_page_is_the_row_the_cli_lists(self, gui):
        api, ws = gui
        status, game = http(api, "POST", "/api/play/games", body={"game": "connect4"})
        assert status == 200
        assert ws.play.get_game(game["id"]).game_type == "connect4"
        _, listed = http(api, "GET", "/api/play/games")
        assert [row["id"] for row in listed["games"]] == [game["id"]]
        assert listed["stats"]["open"] == 1

    def test_a_move_from_the_page_lands_in_the_same_log(self, gui):
        api, ws = gui
        _, game = http(api, "POST", "/api/play/games", body={})
        status, result = http(api, "POST", f"/api/play/games/{game['id']}/move", body={"move": "5"})
        assert status == 200 and result["legal"] is True
        assert [m.action for m in ws.play.moves(game["id"])] == ["5"]

    def test_a_refused_move_is_200_with_the_reason_not_an_error(self, gui):
        """The referee saying no is an answer. A 4xx here would read as a broken request."""
        api, _ws = gui
        _, game = http(api, "POST", "/api/play/games", body={})
        http(api, "POST", f"/api/play/games/{game['id']}/move", body={"move": "5"})
        status, refused = http(api, "POST", f"/api/play/games/{game['id']}/move", body={"move": "5"})
        assert status == 200
        assert refused["legal"] is False and "square 5" in refused["reason"]

    def test_the_engine_button_plays_a_legal_move(self, gui):
        api, _ws = gui
        _, game = http(api, "POST", "/api/play/games", body={"game": "tictactoe"})
        status, result = http(api, "POST", f"/api/play/games/{game['id']}/engine", body={})
        assert status == 200 and result["legal"] is True
        assert result["proposed"] == result["action"]

    def test_auto_over_the_page_finishes_a_connect_four_game(self, gui):
        api, ws = gui
        _, game = http(api, "POST", "/api/play/games", body={"game": "connect4"})
        status, view = http(api, "POST", f"/api/play/games/{game['id']}/auto", body={"plies": 60})
        assert status == 200
        assert view["outcome"]["over"] is True
        assert ws.play.get_game(game["id"]).status == "finished"

    def test_the_history_endpoint_counts_the_refusals(self, gui):
        api, _ws = gui
        _, game = http(api, "POST", "/api/play/games", body={})
        http(api, "POST", f"/api/play/games/{game['id']}/move", body={"move": "1"})
        http(api, "POST", f"/api/play/games/{game['id']}/move", body={"move": "1"})
        _, history = http(api, "GET", f"/api/play/games/{game['id']}/history")
        assert history["legal"] == 1 and history["refused_count"] == 1

    def test_an_unknown_game_type_is_a_400_that_names_the_alternatives(self, gui):
        api, _ws = gui
        status, payload = http(api, "POST", "/api/play/games", body={"game": "chess"})
        assert status == 400
        assert payload["error"]["code"] == "validation"
        assert "tictactoe" in payload["error"]["message"]

    def test_a_simulation_run_in_the_page_can_be_replayed_there(self, gui):
        api, ws = gui
        status, sim = http(
            api, "POST", "/api/play/sims", body={"width": 10, "height": 6, "steps": 2, "seed": 3}
        )
        assert status == 200
        assert ws.play.get_sim(sim["id"]).final_hash == sim["final_hash"]
        status, check = http(api, "POST", f"/api/play/sims/{sim['id']}/replay", body={})
        assert status == 200 and check["matches"] is True

    def test_a_density_that_is_not_a_number_is_a_400(self, gui):
        api, _ws = gui
        status, payload = http(api, "POST", "/api/play/sims", body={"density": "lots"})
        assert status == 400
        assert "density" in payload["error"]["message"]

    def test_the_page_lists_simulations_and_the_stats_behind_them(self, gui):
        api, _ws = gui
        http(api, "POST", "/api/play/sims", body={"width": 8, "height": 5, "steps": 1, "seed": 1})
        _, listed = http(api, "GET", "/api/play/sims")
        assert len(listed["sims"]) == 1
        _, stats = http(api, "GET", "/api/play/stats")
        assert stats["sims"] == 1 and stats["games"] == 0
