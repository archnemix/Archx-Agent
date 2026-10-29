#!/usr/bin/env bash
# Build artifacts and prove the installed wheel works without the source checkout or dependencies.
# Prerequisite: python -m pip install build wheel 'setuptools>=68'
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ARCHX_PY:-$HERE/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python)"
WORK="$(mktemp -d /tmp/archx-release-check-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
"$PY" -m build --no-isolation --outdir "$WORK/packages" "$HERE"
"$PY" -m venv "$WORK/env"
"$WORK/env/bin/python" -m pip install --no-index --no-deps "$WORK"/packages/*.whl
(
  cd "$WORK"
  "$WORK/env/bin/python" -m pip check
  "$WORK/env/bin/archx-agent" --home "$WORK/home" info --json > "$WORK/status.json"
  "$WORK/env/bin/archx-agent" --home "$WORK/home" automation list --json
  "$WORK/env/bin/archx-agent" --home "$WORK/home" scene list --json
  "$WORK/env/bin/python" - <<'PY'
from archx_agent.application.workspace import open_workspace
from archx_agent.interfaces.gui.server import ASSETS, GuiApi
from archx_agent.managers.schema import SCHEMA_VERSION
for name in ('index.html', 'app.js', 'style.css'):
    assert (ASSETS / name).is_file(), name
with open_workspace(home='wheel-smoke-home') as ws:
    assert ws.store.schema_version() == SCHEMA_VERSION
    assert GuiApi(ws, token='wheel-check').page().body.lower().startswith(b'<!doctype html>')
print('release check: wheel installs without runtime dependencies; CLI, schema and packaged GUI assets verified')
PY
)
