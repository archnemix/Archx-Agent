"""Play command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    play = sub.add_parser(
        "play",
        help="Play Mode: board games the rules referee, and simulations you can replay",
    )
    pl_sub = play.add_subparsers(dest="play_command", required=True)
    pl_new = pl_sub.add_parser("new", help="start a game (default: play.default_game)")
    pl_new.add_argument(
        "game",
        nargs="?",
        choices=["tictactoe", "connect4", "nim"],
        help="which game (default: play.default_game)",
    )
    pl_new.add_argument(
        "--seed", type=int, help="recorded with the game, for the engine's choices"
    )
    pl_show = pl_sub.add_parser(
        "show", help="the board, whose turn it is, and the legal moves"
    )
    pl_show.add_argument("game")
    pl_show.add_argument(
        "--moves", type=int, default=8, help="how many recent moves to show"
    )
    pl_move = pl_sub.add_parser(
        "move", help="propose a move; the rules accept it or say why not"
    )
    pl_move.add_argument("game")
    pl_move.add_argument("move")
    pl_engine = pl_sub.add_parser(
        "engine", help="let the built-in engine play the side to move"
    )
    pl_engine.add_argument("game")
    pl_engine.add_argument("--seed", type=int, help="override the game's recorded seed")
    pl_auto = pl_sub.add_parser(
        "auto", help="let the engine play several plies, stopping at the end"
    )
    pl_auto.add_argument("game")
    pl_auto.add_argument(
        "--plies", type=int, default=1, help="how many moves (default 1)"
    )
    pl_auto.add_argument("--seed", type=int)
    pl_resign = pl_sub.add_parser(
        "resign", help="abandon a game (the moves stay readable)"
    )
    pl_resign.add_argument("game")
    pl_resign.add_argument("--winner", help="who is credited with the win, if anyone")
    pl_hist = pl_sub.add_parser(
        "history", help="every move, including the ones the rules refused"
    )
    pl_hist.add_argument("game")
    pl_list = pl_sub.add_parser("list", help="games, newest first")
    pl_list.add_argument("--status", choices=["open", "finished", "abandoned"])
    pl_list.add_argument("--limit", type=int, default=20)
    pl_sim = pl_sub.add_parser(
        "sim", help="run a deterministic simulation and record its hash"
    )
    pl_sim.add_argument("--width", type=int, default=40)
    pl_sim.add_argument("--height", type=int, default=20)
    pl_sim.add_argument("--steps", type=int, default=20)
    pl_sim.add_argument("--seed", type=int, default=0)
    pl_sim.add_argument("--density", type=float, default=0.3)
    pl_sim.add_argument(
        "--no-board",
        dest="board",
        action="store_false",
        help="do not print the final grid",
    )
    pl_sims = pl_sub.add_parser("sims", help="recorded simulations, newest first")
    pl_sims.add_argument("--limit", type=int, default=20)
    pl_replay = pl_sub.add_parser(
        "replay", help="recompute a simulation and check its hash"
    )
    pl_replay.add_argument("sim")
    pl_sub.add_parser("stats", help="game, move and simulation counts")


def cmd_play(args: argparse.Namespace) -> int:
    """`play ...` - games the rules referee, and simulations that can be replayed.

    Exit codes: 0 the move was accepted (or the command succeeded), 1 the replay disagreed with
    the record, 2 the rules refused the move or the arguments made no sense. A refused move is an
    answer, not a crash: it is printed with the reason and written to the log like any other.
    """
    command = args.play_command
    try:
        with _workspace(args) as ws:
            service = ws.play_mode

            if command == "new":
                view = service.new(args.game, seed=args.seed)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(f"started {view['id']}  {view['game_type']}")
                emit("")
                emit(view["board"])
                emit("")
                emit(f"  to move   {view['turn']}")
                emit(
                    f"  moves     {', '.join(view['legal_moves'][:12])}"
                    + (" ..." if len(view["legal_moves"]) > 12 else "")
                )
                emit(f"  next      archx-agent play move {view['id']} <MOVE>")
                return EXIT_OK

            if command == "show":
                view = service.view(args.game, limit=args.moves)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(view["board"])
                emit("")
                emit(
                    f"  game      {view['id']}  {view['game_type']}  ({view['status']})"
                )
                emit(f"  to move   {view['turn'] or '-'}")
                emit(f"  moves     {view['move_count']}")
                if view["legal_moves"]:
                    emit(f"  legal     {', '.join(view['legal_moves'][:14])}")
                outcome = view["outcome"]
                if outcome["over"]:
                    emit(
                        f"  result    {outcome['winner'] or 'draw'} ({outcome['reason']})"
                    )
                if view["moves"]:
                    emit("")
                    for move in view["moves"]:
                        mark = "" if move["legal"] else f"   refused: {move['reason']}"
                        emit(
                            f"  {move['seq']:>3}  {move['player']:<4} {move['action']}{mark}"
                        )
                return EXIT_OK

            if command == "move":
                result = service.move(args.game, args.move)
                if args.json:
                    emit_json(result)
                    return EXIT_OK if result["legal"] else EXIT_USAGE
                if not result["legal"]:
                    emit(f"refused: {result['reason']}")
                    emit(f"  game      {result['game_id']}  (the board did not change)")
                    emit(f"  to move   {result['turn']}")
                    return EXIT_USAGE
                emit(result["board"])
                emit("")
                emit(f"  played    {result['player']} {result['action']}")
                if result["outcome"]["over"]:
                    emit(
                        f"  result    {result['outcome']['winner'] or 'draw'}"
                        f" ({result['outcome']['reason']})"
                    )
                else:
                    emit(f"  to move   {result['turn']}")
                return EXIT_OK

            if command == "engine":
                result = service.engine_move(args.game, seed=args.seed)
                if args.json:
                    emit_json(result)
                    return EXIT_OK
                emit(f"engine plays {result['action']} as {result['player']}")
                emit("")
                emit(result["board"])
                if result["outcome"]["over"]:
                    emit("")
                    emit(
                        f"  result    {result['outcome']['winner'] or 'draw'}"
                        f" ({result['outcome']['reason']})"
                    )
                else:
                    emit("")
                    emit(f"  to move   {result['turn']}")
                return EXIT_OK

            if command == "auto":
                view = service.auto(args.game, plies=args.plies, seed=args.seed)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                for move in view["played"]:
                    emit(f"  {move['player']} {move['action']}")
                emit("")
                emit(view["board"])
                emit("")
                emit(
                    f"  played    {len(view['played'])} move(s)  total {view['move_count']}"
                )
                outcome = view["outcome"]
                if outcome["over"]:
                    emit(
                        f"  result    {outcome['winner'] or 'draw'} ({outcome['reason']})"
                    )
                else:
                    emit(f"  to move   {view['turn']}")
                return EXIT_OK

            if command == "resign":
                view = service.resign(args.game, winner=args.winner)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(f"abandoned {view['id']}")
                if view["winner"]:
                    emit(f"  winner    {view['winner']}")
                emit(
                    "  the moves are still there: archx-agent play history "
                    f"{view['id']}"
                )
                return EXIT_OK

            if command == "history":
                history = service.history(args.game)
                if args.json:
                    emit_json(history)
                    return EXIT_OK
                emit(f"{history['id']}  {history['game_type']}  ({history['status']})")
                emit(f"  accepted  {history['legal']}")
                emit(f"  refused   {history['refused_count']}")
                if history["moves"]:
                    emit("")
                    rows = [
                        [
                            m["seq"],
                            m["player"],
                            m["action"],
                            "yes" if m["legal"] else "no",
                            m["reason"] or "",
                            m["created_at"],
                        ]
                        for m in history["moves"]
                    ]
                    emit(table(rows, ["seq", "player", "move", "legal", "why", "when"]))
                return EXIT_OK

            if command == "list":
                games = service.games(status=args.status, limit=args.limit)
                if args.json:
                    emit_json(games)
                    return EXIT_OK
                if not games:
                    emit("no games yet (archx-agent play new)")
                    return EXIT_OK
                rows = [
                    [
                        g["id"],
                        g["game_type"],
                        g["status"],
                        g["winner"] or "-",
                        g["move_count"],
                        g["created_at"],
                    ]
                    for g in games
                ]
                emit(
                    table(rows, ["id", "game", "status", "winner", "moves", "created"])
                )
                return EXIT_OK

            if command == "sim":
                sim = service.simulate(
                    width=args.width,
                    height=args.height,
                    steps=args.steps,
                    seed=args.seed,
                    density=args.density,
                )
                if args.json:
                    emit_json(sim)
                    return EXIT_OK
                emit(
                    f"ran {sim['id']}  {sim['kind']}  {sim['width']}x{sim['height']}"
                    f"  {sim['steps']} step(s)  seed {sim['seed']}"
                )
                emit(f"  rule      {sim['metadata'].get('rule', '-')}")
                emit(f"  alive     {sim['alive']}")
                emit(
                    f"  series    {', '.join(str(n) for n in sim['series'][:14])}"
                    + (" ..." if len(sim["series"]) > 14 else "")
                )
                emit(f"  hash      {sim['final_hash']}")
                if args.board:
                    emit("")
                    for line in sim["rows"]:
                        emit("  " + line)
                emit("")
                emit(f"  check     archx-agent play replay {sim['id']}")
                return EXIT_OK

            if command == "sims":
                sims = service.sims(limit=args.limit)
                if args.json:
                    emit_json(sims)
                    return EXIT_OK
                if not sims:
                    emit("no simulations yet (archx-agent play sim)")
                    return EXIT_OK
                rows = [
                    [
                        s["id"],
                        s["kind"],
                        f"{s['width']}x{s['height']}",
                        s["steps"],
                        s["seed"],
                        s["alive"],
                        (s["final_hash"] or "-")[:12],
                        s["created_at"],
                    ]
                    for s in sims
                ]
                emit(
                    table(
                        rows,
                        [
                            "id",
                            "kind",
                            "size",
                            "steps",
                            "seed",
                            "alive",
                            "hash",
                            "created",
                        ],
                    )
                )
                return EXIT_OK

            if command == "replay":
                check = service.replay(args.sim)
                if args.json:
                    emit_json(check)
                    return EXIT_OK if check["matches"] else EXIT_ERROR
                emit(
                    f"{check['id']}  {check['width']}x{check['height']}  {check['steps']} step(s)"
                    f"  seed {check['seed']}"
                )
                emit(f"  stored      {check['stored_hash']}")
                emit(f"  recomputed  {check['recomputed_hash']}")
                if check["matches"]:
                    emit("  verdict     reproduced")
                    return EXIT_OK
                emit(
                    "  verdict     DIFFERENT - the record does not describe these parameters"
                )
                return EXIT_ERROR

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(
                    f"games       {data['games']} ({data['open']} open, "
                    f"{data['finished']} finished)"
                )
                emit(
                    f"moves       {data['moves']} ({data['refused_moves']} refused by the rules)"
                )
                emit(f"sims        {data['sims']}")
                emit(
                    f"built in    {', '.join(data['games_available'])}"
                    f"  (default: {data['default_game']})"
                )
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)

    return fail(f"unknown play command: {command}", EXIT_USAGE)
