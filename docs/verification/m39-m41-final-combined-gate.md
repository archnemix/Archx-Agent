# Historical verification: M39–M41 final combined gate

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

## M39–M41 final combined gate

Local full suite: **1951 passed in 486.57 seconds**. M40 tests: 17; M41 hardening regressions: 8.
M39 acceptance: 59/59; M40 acceptance: 34/34; GUI smoke: 20 tabs; clean-wheel/sdist build and
installation check: passed with no runtime dependencies. Final combined CI is pending.

CI #25 is green and independently verified the real official bpy 4.2 / Cycles CPU render:
64×64 PNG, 4897 bytes, SHA-256
`c157d34edbb959f8194117dc220b515b6bd5f750154ea5cb39337c34cd509570`. This uses Blender itself,
not the argv-only stand-in. Native libraries were installed on the CI runner; bpy cannot load in
this sandbox due to missing X11/OpenGL libraries. The desktop Blender binary is not in the tested
matrix. Release scope and operator caveats: `docs/RELEASE.md`.


### Final result — M39–M41 closed within documented scope

CI #26 `40914694127`, head `48dd607`, published evidence
`ci/runs/20261029T164537Z-48dd607`: **success, 24/24 logged steps**.

| Gate | Result |
|---|---|
| Full suite | 1951 passed, 2 third-party deprecation warnings, 536.36 s |
| Stress/hostile-client | 91 passed |
| CLI/GUI/SQLite integration | 11 passed |
| Acceptances M31–M40 | 48, 53, 69, 88, 72, 57, 71, 65, 59, 34 — all passed |
| Actual Blender | official bpy 4.2 / Cycles CPU, 64×64 PNG, 4883 bytes |
| Render SHA-256 | ffe179acb67b8ab98b66feee3e6012151ea3a03292fa2e394e82ec87ea215e1f |
| Release check | wheel/sdist built; isolated dependency-free install; CLI/schema/GUI passed |
| Model/SDK gates | all green, including actual Ollama daemon and public tunnel |
| Local GUI smoke | 20 tabs, forms post, no page errors |

No M01–M41 milestone remains open. M39 excludes other renderer/platform combinations and async
rendering; M40 excludes cron/cloud triggers; M41 is source/wheel readiness rather than published
installers or a security certification. Scope and operator checklist: `docs/RELEASE.md`.
