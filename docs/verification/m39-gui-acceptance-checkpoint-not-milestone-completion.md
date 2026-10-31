# Historical verification: M39 GUI/acceptance checkpoint (not milestone completion)

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## M39 GUI/acceptance checkpoint (not milestone completion)

Local results after adding the Scenes tab and authenticated API:

```text
pytest: 1894 passed in 506.58s
tests/test_scenes_m39.py: 26 passed
acceptance_m39.sh: 49 checks passed, 0 failed
gui_smoke.mjs: 19 tabs, including Scenes; forms post; no page errors
```

The acceptance script invokes the installed CLI, inspects OBJ/STL/SVG/script output bytes and
hashes independently, corrupts an export to make verification fail, repairs it, checks duplicate
creation preserves the scene, and runs a stand-in Blender from a path containing spaces. The
stand-in records its received argv and exits zero without producing a PNG; that must be a failed
render, not a success. This is invocation evidence, **not evidence of an actual Blender render**.
The workflow runs this acceptance as `scenes-acceptance`; run #22 is green (21 steps), with
1894 tests on the runner and 49/49 scene checks. Evidence is in `docs/ci/`.


### M39 document validation follow-up

Local full suite: **1921 passed in 506.96 seconds**. Scene tests: **53 passed**; CLI acceptance
remains **49 checks passed, 0 failed**. Added cases cover corrupt document shape, numeric types,
camera degeneracy, invalid primitive additions with unchanged file/rows, and geometry budgets
validated without generating meshes. This code follows green CI #22; its own CI result is pending.


### M39 task linkage checkpoint

Validation CI #23 (`17a4253`) is green: **1921 tests, 21 steps**, including 49 scene acceptance
checks; evidence refreshed in `docs/ci/`. Task linkage was added after that run:

```text
full suite: 1926 passed in 463.12s
scene tests: 58 passed
M39 acceptance: 59 checks passed, 0 failed
GUI smoke: 19 tabs, forms post, no page errors
```

New tests check document/export artifact hashes, missing-task refusal before file creation,
render-refusal timeline entries without changing parent task state, attachment failure preserving
the output ledger, and a stand-in writer's output attached to the same task as the execution run.
The stand-in is not evidence of a real Blender render. Task-linkage CI result is pending.


