"""Stable repository paths shared by suites regardless of their folder depth."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "tests"
SRC = REPO_ROOT / "src"
