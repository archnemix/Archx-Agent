#!/usr/bin/env bash
# M33 acceptance: Play Mode, driven the way a person would use it.
#
# The claims being checked are the ones that would be easy to fake:
#   * the rules are the only authority: an illegal move is refused by name, exit 2, written down
#     with legal = 0, and the board does not move;
#   * the engine cannot cheat: every move it proposes is one the rules list, checked by asking the
#     rules on random positions rather than by trusting the engine;
#   * the move log keeps the refusals, so "2 accepted, 1 refused" is a query and not a re-parse;
#   * a simulation records its parameters and a hash of the grid, and `play replay` recomputes from
#     the parameters alone - a doctored row fails its own check;
#   * the page is a client of the same service: a game started there is the row the CLI lists.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ARCHX_CLI:-$HERE/.venv/bin/archx-agent}"
[ -x "$CLI" ] || CLI="$(command -v archx-agent)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="${1:-$(mktemp -d /tmp/archx-m33-XXXXXX)}"
HOME_DIR="$WORK/home"
LAB="$WORK/lab"
export ARCHX_PATHS_HOME="$HOME_DIR"
export ARCHX_TOOLS_ROOTS="$LAB"
export ARCHX_ALLOW_SIMULATED=1
mkdir -p "$HOME_DIR" "$LAB"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
TOKEN="m33-acceptance-token"
BASE="http://127.0.0.1:$PORT"
FAILURES=0
CHECKS=()
GUI_PID=""

say() { printf '\n### %s\n' "$*"; }
run() { printf '$ archx-agent %s\n' "$*"; "$CLI" "$@"; printf '[exit %s]\n' "$?"; }
jq_() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
check() {
  if [ "$2" = "$3" ]; then
    CHECKS+=("ok   | $1 | $2"); printf '[ok]   %s = %s\n' "$1" "$2"
  else
    CHECKS+=("FAIL | $1 | got '$2' want '$3'"); printf "[FAIL] %s: got '%s' want '%s'\n" "$1" "$2" "$3"
    FAILURES=$((FAILURES + 1))
  fi
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
get_json() { curl -s -H "X-Archx-Token: $TOKEN" "$1"; }
post_json() { curl -s -X POST -H "X-Archx-Token: $TOKEN" -H "Content-Type: application/json" -d "$2" "$1"; }
api_jsonq() { "$PY" -c "import json,sys; d=json.load(sys.stdin)['data']; print($1)"; }

dbq() { "$PY" - "$HOME_DIR/archx.db" "$1" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
print(connection.execute(sys.argv[2]).fetchone()[0])
PYEOF
}

cleanup() {
  [ -n "$GUI_PID" ] && kill "$GUI_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT

printf 'M33 acceptance on %s\n' "$WORK"
"$CLI" init >/dev/null 2>&1

say "the schema adopts the tables the earlier milestones reserved"
check "play is a versioned migration" \
  "$(dbq "SELECT COUNT(*) FROM schema_migrations WHERE version = 23")" "1"
check "games and game_moves exist" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('games','game_moves')")" "2"
check "simulations have their own table" \
  "$(dbq "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='play_sims'")" "1"
check "a fresh home has played nothing" "$("$CLI" --json play stats | jq_ "d['games']")" "0"

say "a game is a board the rules build"
GAME="$("$CLI" --json play new | jq_ "d['id']")"
check "new game is a row" "$(dbq "SELECT COUNT(*) FROM games WHERE id = '$GAME'")" "1"
check "new game is open" "$(dbq "SELECT status FROM games WHERE id = '$GAME'")" "open"
check "the default game comes from configuration" \
  "$(dbq "SELECT game_type FROM games WHERE id = '$GAME'")" "tictactoe"
check "tic-tac-toe starts with nine legal moves" \
  "$("$CLI" --json play show "$GAME" | jq_ "len(d['legal_moves'])")" "9"
check "and it is X to move" "$("$CLI" --json play show "$GAME" | jq_ "d['turn']")" "X"

say "a legal move moves the board; the log says so"
check "move accepted" "$("$CLI" --json play move "$GAME" 5 >/dev/null; echo $?)" "0"
check "move is a row" "$(dbq "SELECT COUNT(*) FROM game_moves WHERE game_id = '$GAME'")" "1"
check "the row is legal" "$(dbq "SELECT legal FROM game_moves WHERE game_id = '$GAME' AND seq = 1")" "1"
check "the row carries a state hash" \
  "$(dbq "SELECT LENGTH(state_hash) FROM game_moves WHERE game_id = '$GAME' AND seq = 1")" "16"
check "the board holds the X in the centre" \
  "$(dbq "SELECT state FROM games WHERE id = '$GAME'" | grep -c '"X"')" "1"

say "a refused move is kept, and changes nothing"
MOVE_COUNT="$(dbq "SELECT move_count FROM games WHERE id = '$GAME'")"
"$CLI" --json play move "$GAME" 5 >"$WORK/refused.json" 2>/dev/null
check "the refused move exits 2" "$?" "2"
check "it says the square is taken" \
  "$("$PY" -c "import json; print(json.load(open('$WORK/refused.json'))['reason'])")" \
  "square 5 is taken"
check "it is written down as illegal" \
  "$(dbq "SELECT legal FROM game_moves WHERE game_id = '$GAME' AND legal = 0")" "0"
check "with the reason" \
  "$(dbq "SELECT reason FROM game_moves WHERE game_id = '$GAME' AND legal = 0")" \
  "square 5 is taken"
check "the refusal is numbered from the move count, not from the log" \
  "$(dbq "SELECT seq FROM game_moves WHERE game_id = '$GAME' AND legal = 0")" "2"
check "the move count did not advance" \
  "$(dbq "SELECT move_count FROM games WHERE id = '$GAME'")" "$MOVE_COUNT"
run play history "$GAME" --json >/dev/null
check "history counts the refusal" \
  "$("$CLI" --json play history "$GAME" | jq_ "d['refused_count']")" "1"
check "history counts the acceptance" \
  "$("$CLI" --json play history "$GAME" | jq_ "d['legal']")" "1"

say "a finished game is finished"
# X already holds the centre; 4 and 6 complete the middle row.
for move in 1 4 2; do "$CLI" play move "$GAME" "$move" >/dev/null; done
"$CLI" --json play move "$GAME" 6 >/dev/null
check "the game is finished" "$(dbq "SELECT status FROM games WHERE id = '$GAME'")" "finished"
check "and it names the winner" "$(dbq "SELECT winner FROM games WHERE id = '$GAME'")" "X"
"$CLI" play move "$GAME" 9 >/dev/null 2>&1
check "a move after the end is refused" "$?" "2"
check "and is not logged" \
  "$(dbq "SELECT COUNT(*) FROM game_moves WHERE game_id = '$GAME' AND action = '9'")" "0"

say "the engine may only choose from the legal moves"
C4="$("$CLI" --json play new connect4 | jq_ "d['id']")"
check "connect four starts with seven columns" \
  "$("$CLI" --json play show "$C4" | jq_ "len(d['legal_moves'])")" "7"
printf '$ archx-agent play engine %s\n' "$C4"
"$CLI" --json play engine "$C4" >"$WORK/engine.json" 2>/dev/null
check "the engine move was accepted" \
  "$("$PY" -c "import json; print(json.load(open('$WORK/engine.json'))['legal'])")" "True"
check "it is in the log as a legal move" \
  "$(dbq "SELECT legal FROM game_moves WHERE game_id = '$C4'")" "1"
"$CLI" --json play auto "$C4" --plies 60 >/dev/null
check "playing it out finishes the game" "$(dbq "SELECT status FROM games WHERE id = '$C4'")" "finished"
check "no engine move was ever refused" \
  "$(dbq "SELECT COUNT(*) FROM game_moves WHERE game_id = '$C4' AND legal = 0")" "0"
check "the game ended inside the board" \
  "$(dbq "SELECT COUNT(*) FROM game_moves WHERE game_id = '$C4'")" "15"

say "the engine is checked against the rules, not against an opinion"
cat > "$WORK/fuzz.py" <<'PYEOF'
import random
from archx_agent.application import games

checked = 0
for name in sorted(games.GAMES):
    rules = games.rules_for(name)
    for seed in range(20):
        engine = games.Engine(rules, seed=seed)
        state = rules.initial()
        for _ in range(60):
            if rules.outcome(state)["over"]:
                break
            move = engine.choose(state)
            assert move in rules.legal_moves(state), (name, move)
            result = rules.apply(state, move)
            assert result.legal, (name, move, result.reason)
            state = result.state
            checked += 1
print(checked)
PYEOF
"$PY" "$WORK/fuzz.py" >"$WORK/fuzz.out" 2>"$WORK/fuzz.err"
check "60 games of engine play, no illegal move" "$?" "0"
check "and plenty of moves were actually checked" \
  "$("$PY" -c "print(1 if int(open('$WORK/fuzz.out').read().strip()) > 300 else 0)")" "1"

say "nim's strategy is the one it claims"
NIM="$("$CLI" --json play new nim | jq_ "d['id']")"
"$CLI" --json play engine "$NIM" >/dev/null
check "after the engine's first move the heaps XOR to zero" \
  "$("$PY" -c "
from archx_agent.application.workspace import open_workspace
import os
ws = open_workspace(home='$HOME_DIR')
heaps = ws.play.get_game('$NIM').state['heaps']
x = 0
for heap in heaps:
    x ^= heap
print(x)
ws.close()")" "0"

say "a game can be abandoned without losing its moves"
QUIT="$("$CLI" --json play new | jq_ "d['id']")"
"$CLI" play move "$QUIT" 5 >/dev/null
"$CLI" play resign "$QUIT" --winner O >/dev/null
check "resign sets the status" "$(dbq "SELECT status FROM games WHERE id = '$QUIT'")" "abandoned"
check "and the winner it was told" "$(dbq "SELECT winner FROM games WHERE id = '$QUIT'")" "O"
check "the move is still readable" \
  "$("$CLI" --json play history "$QUIT" | jq_ "d['legal']")" "1"

say "an unknown game is refused with the list"
"$CLI" play new chess >/dev/null 2>"$WORK/chess.err"
check "unknown game exits 2" "$?" "2"
check "and names what is built in" \
  "$("$PY" -c "print(1 if 'tictactoe' in open('$WORK/chess.err').read() else 0)")" "1"

say "a simulation records the parameters and the hash"
SIM="$("$CLI" --json play sim --width 16 --height 10 --steps 6 --seed 3 | jq_ "d['id']")"
HASH="$(dbq "SELECT final_hash FROM play_sims WHERE id = '$SIM'")"
check "the simulation is a row" "$(dbq "SELECT COUNT(*) FROM play_sims WHERE id = '$SIM'")" "1"
check "it kept the seed" "$(dbq "SELECT seed FROM play_sims WHERE id = '$SIM'")" "3"
check "it kept the steps" "$(dbq "SELECT steps FROM play_sims WHERE id = '$SIM'")" "6"
check "its hash is a sha256" "${#HASH}" "64"
check "the series has one entry per step plus the start" \
  "$("$CLI" --json play sims | jq_ "len(d[0]['series'])")" "7"
check "the same seed gives the same hash" \
  "$("$CLI" --json play sim --width 16 --height 10 --steps 6 --seed 3 | jq_ "d['final_hash']")" "$HASH"
check "replay reproduces it" "$("$CLI" play replay "$SIM" >/dev/null; echo $?)" "0"

say "a doctored record fails its own replay"
"$PY" - "$HOME_DIR/archx.db" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute("UPDATE play_sims SET final_hash = ?", ("0" * 64,))
connection.commit()
PYEOF
"$CLI" play replay "$SIM" >"$WORK/tampered.out" 2>&1
check "a hash that does not reproduce exits 1" "$?" "1"
check "and the page says which hash is different" \
  "$(grep -c 'DIFFERENT' "$WORK/tampered.out")" "1"
"$PY" - "$HOME_DIR/archx.db" "$HASH" <<'PYEOF'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute("UPDATE play_sims SET final_hash = ?", (sys.argv[2],))
connection.commit()
PYEOF
check "and it reproduces again once restored" "$("$CLI" play replay "$SIM" >/dev/null; echo $?)" "0"

say "absurd simulation parameters are refused, not clipped"
"$CLI" play sim --steps 99999 >/dev/null 2>&1
check "too many steps exits 2" "$?" "2"
"$CLI" play sim --width 0 >/dev/null 2>&1
check "a zero width exits 2" "$?" "2"
"$CLI" play sim --density 2 >/dev/null 2>&1
check "a density above one exits 2" "$?" "2"

say "the counts agree with the rows"
run play stats
check "games" "$("$CLI" --json play stats | jq_ "d['games']")" "$(dbq "SELECT COUNT(*) FROM games")"
check "moves" "$("$CLI" --json play stats | jq_ "d['moves']")" "$(dbq "SELECT COUNT(*) FROM game_moves")"
check "refusals" "$("$CLI" --json play stats | jq_ "d['refused_moves']")" \
  "$(dbq "SELECT COUNT(*) FROM game_moves WHERE legal = 0")"
check "simulations" "$("$CLI" --json play stats | jq_ "d['sims']")" \
  "$(dbq "SELECT COUNT(*) FROM play_sims")"

say "the page is a client of the same service"
"$CLI" gui serve --host 127.0.0.1 --port "$PORT" --token "$TOKEN" --no-open >"$WORK/gui.log" 2>&1 &
GUI_PID=$!
for _ in $(seq 1 40); do
  [ "$(status_of "$BASE/api/health")" = "200" ] && break
  sleep 0.25
done
check "the page lists the games" \
  "$(get_json "$BASE/api/play/games" | api_jsonq "len(d['games'])")" "$(dbq "SELECT COUNT(*) FROM games")"
PAGE_GAME="$(post_json "$BASE/api/play/games" '{"game":"tictactoe"}' | api_jsonq "d['id']")"
check "a game started in the page is a row" \
  "$(dbq "SELECT COUNT(*) FROM games WHERE id = '$PAGE_GAME'")" "1"
check "a move from the page is accepted" \
  "$(post_json "$BASE/api/play/games/$PAGE_GAME/move" '{"move":"5"}' | api_jsonq "d['legal']")" "True"
check "a refused move is a 200 with the reason, not an error" \
  "$(status_of -X POST -H "X-Archx-Token: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"move":"5"}' "$BASE/api/play/games/$PAGE_GAME/move")" "200"
check "and the refusal is in the log the CLI reads" \
  "$("$CLI" --json play history "$PAGE_GAME" | jq_ "d['refused_count']")" "1"
PAGE_SIM="$(post_json "$BASE/api/play/sims" '{"width":10,"height":6,"steps":2,"seed":4}' | api_jsonq "d['id']")"
check "a simulation run in the page reproduces" \
  "$(post_json "$BASE/api/play/sims/$PAGE_SIM/replay" '{}' | api_jsonq "d['matches']")" "True"
check "an unknown game is a 400 over HTTP" \
  "$(status_of -X POST -H "X-Archx-Token: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"game":"chess"}' "$BASE/api/play/games")" "400"
check "an unauthenticated call is refused" "$(status_of "$BASE/api/play/games")" "401"
check "the stats endpoint agrees with the rows" \
  "$(get_json "$BASE/api/play/stats" | api_jsonq "d['sims']")" "$(dbq "SELECT COUNT(*) FROM play_sims")"

say "the record survives a restart"
check "the finished game is still finished" \
  "$("$CLI" --json play show "$GAME" | jq_ "d['status']")" "finished"
check "the refused moves are still refused" \
  "$("$CLI" --json play history "$GAME" | jq_ "d['refused_count']")" "1"
check "the simulation still reproduces" "$("$CLI" play replay "$SIM" >/dev/null; echo $?)" "0"

printf '\nM33 acceptance: %s checks passed, %s failed\n' \
  "$((${#CHECKS[@]} - FAILURES))" "$FAILURES"
[ "$FAILURES" -eq 0 ] || exit 1
