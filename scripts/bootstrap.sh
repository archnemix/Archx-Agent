#!/usr/bin/env bash
# Create the local development environment.
#
# The virtualenv is intentionally *not* committed (.venv is git-ignored); this script
# is the reproducible replacement for it. Run it after cloning.
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -e .
./.venv/bin/python -m pip install --quiet pytest
./.venv/bin/archx-agent --version
echo "ready: ./.venv/bin/python -m pytest -q"
