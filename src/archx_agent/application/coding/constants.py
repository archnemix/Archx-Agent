"""Vocabulary and defaults for coding sessions."""

from __future__ import annotations

import re


CHECKS_FILE = "archx.checks.json"

_CHECK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
