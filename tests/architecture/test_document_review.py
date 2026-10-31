"""The document inventory must distinguish stale guidance from preserved history."""

from __future__ import annotations

import importlib

import pytest

from tests.paths import REPO_ROOT


@pytest.fixture
def reviewer(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    return importlib.import_module("review_documents")


def test_current_guide_detects_old_file_that_became_package(reviewer, tmp_path):
    (tmp_path / "src/archx_agent/managers/models").mkdir(parents=True)
    doc = tmp_path / "guide.md"
    doc.write_text("# Current guide\nUse `managers/models.py`.\n")
    kind, issues = reviewer.review_text(doc, tmp_path)
    assert kind == "current guide/status"
    assert any("stale source reference managers/models.py" in issue for issue in issues)


def test_history_preserves_old_source_paths_but_checks_links(reviewer, tmp_path):
    doc = tmp_path / "reports/old.md"
    doc.parent.mkdir()
    doc.write_text(
        "# Historical checkpoint\nHistorical report: `tests/old.py`\n[bad](missing.md)\n"
    )
    kind, issues = reviewer.review_text(doc, tmp_path)
    assert kind == "historical checkpoint"
    assert len(issues) == 1 and "missing link target" in issues[0]


def test_current_guide_skips_transcript_code_fences(reviewer, tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("# Current guide\n```text\n`tests/not-a-file.py`\n```\n")
    assert reviewer.review_text(doc, tmp_path)[1] == []


def test_archived_doc_requires_explicit_history_context(reviewer, tmp_path):
    doc = tmp_path / "verification/old.md"
    doc.parent.mkdir()
    doc.write_text("# Checkpoint\nAll tests pass.\n")
    assert (
        "missing historical-evidence context" in reviewer.review_text(doc, tmp_path)[1]
    )
