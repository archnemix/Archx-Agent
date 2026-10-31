# Play Mode

Play Mode is three small games and one small simulation, chosen because they can be *checked*.
There is no claim here that an agent plays well; the claim is that the rules decide, the record
keeps what the rules refused, and a simulation can be replayed from its parameters alone.

```bash
archx-agent play new connect4                     # the rules build the board
archx-agent play move gm_… 4                      # the rules accept it, or say why not
archx-agent play engine gm_…                      # the built-in engine plays one move
archx-agent play auto gm_… --plies 40             # …or several, stopping when the game ends
archx-agent play show gm_…                        # board, turn, legal moves, recent log
archx-agent play history gm_…                     # every move, including the refused ones
archx-agent play sim --width 40 --height 20 --steps 20 --seed 1
archx-agent play replay sim_…                     # recompute and compare the hash
```

The same actions are on the **Play** page of the GUI, and both go through
`PlayService` - the page has no privileges the command line does not have.

## 1. The rules are the only authority

`src/archx_agent/application/games.py` holds the games as pure objects. Each one can build its
initial state, render it, list the moves that are legal *there*, apply one, and say whether the
game is over:

```python
rules = games.rules_for("tictactoe")      # or "nim", "connect4"
state = rules.initial()
result = rules.apply(state, "5")
result.legal       # True
result.state       # the new board - or the old one, when the move was refused
result.reason      # why not, in words a person can act on
result.notation    # what goes in the log: "5", "2,1" (heap,take), "4" (column)
```

Nothing above the rules decides legality. The mover - a person, the engine, or a model - proposes
a string, and `apply` answers. That is why the engine *cannot* cheat: not because it was written
carefully, but because it chooses from `legal_moves(state)` and every choice goes through the same
`apply` a person's move does. `scripts/acceptance_m33.sh` proves it by playing sixty games and
asking the rules about every single move.

| game | players | move | over when |
|------|---------|------|-----------|
| `tictactoe` | `X`, `O` | a square, `1`-`9` (top-left is 1) | a line, or a full board |
| `connect4` | `R`, `Y` | a column, `1`-`7`; the disc falls | four in a line, or a full board |
| `nim` | `you`, `them` | `HEAP,TAKE`, e.g. `2,1` | every heap empty (normal play: last taker wins) |

## 2. A refused move is evidence, not an error to hide

A play log that contains only the moves that worked cannot show you that the rules held. So a
refused move is written to `game_moves` too:

* `legal = 0`, with the rules' own reason in `reason`;
* the board does not change, and `games.move_count` does not advance;
* the refusal is numbered from the move count, so a refusal and the move that follows it share a
  sequence number. The log reads in order and nothing is invented to keep the numbers tidy;
* `play history` counts both, and the page shows the refusals in the same table.

Over HTTP a refusal is a `200` with `"legal": false` and the reason, not a `4xx`: the referee
saying no is an answer to a well-formed request. The CLI exits `2`, because a shell script wants
to know that nothing happened.

## 3. The engine, and what it does not claim

`games.Engine(rules, seed=…)` is deterministic and picks only from the legal list:

* **tic-tac-toe** - perfect play: win if it can, block if it must, then centre, corners, edges. Two
  engines draw, because neither can lose.
* **nim** - normal-play strategy: leave a zero XOR when a legal move allows it, otherwise take one.
* **connect four** - two plies: win now, block a win, otherwise expand from the middle column.

Two plies is not good play, and the docs say so rather than implying otherwise. What the engine
guarantees is legality and reproducibility; strength is a separate question that this milestone
does not answer.

## 4. A simulation is a record, not a picture

`play sim` runs Conway's life with a fixed rule (`B3/S23`) over a grid seeded from a number, and
stores the parameters, the population series, the final grid and a sha256 of that grid as text:

```bash
$ archx-agent play sim --width 16 --height 10 --steps 6 --seed 3
ran sim_…  life  16x10  6 step(s)  seed 3
  rule      B3/S23
  alive     42
  series    48, 51, 44, …
  hash      c7a1c58f58a7ebc6…
  check     archx-agent play replay sim_…
```

`play replay` recomputes from `width`, `height`, `steps`, `seed` and `density` and compares the
hash. Edit one character of the stored hash and the replay disagrees - exit `1`, and both hashes
printed:

```
  stored      d57357c0d2ce2ca6…
  recomputed  9c5512ab449f0f0c…
  verdict     DIFFERENT - the record does not describe these parameters
```

That is the whole point of storing a hash instead of a screenshot: a record that cannot be
replayed is a claim, and this one can be checked in a second.

Parameters are validated rather than clipped: at most 1000 per side, at most 250 000 cells, at
most 5000 steps, density in `[0, 1]`. A wrapping (toroidal) rule is refused with *"wrapping needs
a torus rule that this build does not have yet"* rather than silently ignored.

## 5. What is stored

| table | one row per | notes |
|-------|-------------|-------|
| `games` | a game | `state` is JSON; `status` is `open` / `finished` / `abandoned`; `winner`, `seed`, `move_count` |
| `game_moves` | a proposed move | `legal`, `reason`, and `state_hash` (16 hex chars) of the position it produced |
| `play_sims` | a simulation | parameters, `series`, `rows`, `final_hash`, `alive` |

`games` and `game_moves` were reserved by the v8 schema and unused until now; schema **v23** adopts
them with `ALTER TABLE` (so a home that already has rows keeps them) and adds `play_sims`. The
reasoning is the same as M32's: a reserved table is not a free table, so it is extended rather than
redefined under anyone.

## 6. Tests and acceptance

* `tests/features/test_play_m33.py` - 77 tests: the rules of all three games (illegal moves, terminals,
  draws), the engine checked against the rules on 25 seeds per game, the simulation rules
  (blinker, block, lonely cell, determinism, tampered hash), the service (refusals recorded, the
  sequence not spent, resign, auto stopping at the end), and the GUI returning the same rows.
* `scripts/acceptance_m33.sh` - 69 checks over the CLI and a real GUI socket, including a doctored
  hash failing its own replay.
* `scripts/gui_smoke.mjs` - the Play panel renders in jsdom: the Play panel renders among the tabs (13 then, 14 since M34), a refused move keeps its
  reason, a simulation shows its hash.
