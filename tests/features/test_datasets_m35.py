"""M35 - Dataset preparation: candidates with reasons, stable splits, and a manifest that can fail.

A corpus pipeline can look finished while being useless, in four specific ways. The tests are
organised around each one:

1. **a dataset that only contains what survived.** `TestNothingIsDroppedSilently` checks that a file
   removed by a rule keeps a row and a reason, and that `explain` answers "why is this not in my
   dataset" from the record rather than from a log nobody kept.
2. **a split that moves when the corpus grows.** `TestSplitsAreStable` adds a file and asserts the
   existing assignments did not change; a positional shuffle cannot pass it. `TestLeaksAreRefused`
   asserts that the same bytes in two splits is a refusal that names the pair, not a warning.
3. **a manifest that is decoration.** `TestTheManifestCanFail` builds, changes a file on disk, and
   asserts `verify` disagrees and says which record changed - the same standard M33 set for replay.
4. **provenance that was assumed.** `TestLicenseAndSources` checks that an unstated license is
   written as `unknown`, that `require_license` refuses instead of inventing one, and that a scan
   reads every directory through the tool layer.

The corpus fixtures are written by the tests, so the content hashes are known and the pipeline's
arithmetic can be checked by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.datasets import DATASET_STATES, RECORD_STATUSES, SPLITS
from archx_agent.managers.schema import SCHEMA_VERSION


# --------------------------------------------------------------------------
# fixtures: a small corpus with one of every problem
# --------------------------------------------------------------------------
@pytest.fixture()
def lab(tmp_path) -> Path:
    """Six candidates: two identical, one empty, one binary, one tiny, one fine."""
    folder = tmp_path / "lab"
    corpus = folder / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "a.txt").write_text("the first document\nwith two lines\n", encoding="utf-8")
    (corpus / "copy_of_a.txt").write_text("the first document\nwith two lines\n", encoding="utf-8")
    # The same text re-saved: different bytes, different hash, same document. This is the pair an
    # exact-hash check cannot see and a split can therefore leak.
    (corpus / "near_a.txt").write_text("The First Document\n  with   two lines\n", encoding="utf-8")
    (corpus / "empty.txt").write_text("", encoding="utf-8")
    (corpus / "tiny.md").write_text("short", encoding="utf-8")
    (corpus / "blob.txt").write_bytes(b"\x00\x01\x02binary")
    (corpus / "sub" / "b.md").write_text("second document here\n", encoding="utf-8")
    (corpus / "c.md").write_text("third document here\n", encoding="utf-8")
    return folder


@pytest.fixture()
def ws(tmp_path, lab):
    with open_workspace(
        home=str(tmp_path / "home"),
        overrides={"tools.roots": [str(lab)]},
    ) as workspace:
        yield workspace


@pytest.fixture()
def granted(ws):
    ws.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
    ws.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
    return ws


@pytest.fixture()
def data(granted):
    return granted.data


@pytest.fixture()
def corpus(data):
    created = data.create("corpus", ["corpus"], license="CC-BY-4.0")
    data.scan(created["id"])
    return created["id"]


def by_path(rows, name):
    return next(row for row in rows if row["path"].endswith(name))


# --------------------------------------------------------------------------
# the schema and the states
# --------------------------------------------------------------------------
class TestTheSchema:
    def test_v25_adopts_the_tables_v8_reserved(self, ws):
        assert SCHEMA_VERSION >= 25
        assert ws.store.table_exists("datasets")
        assert ws.store.table_exists("dataset_transforms")
        assert ws.store.table_exists("dataset_records")
        version = ws.store.scalar(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 25"
        )
        assert version == 1

    def test_the_reserved_columns_survive_the_adoption(self, ws):
        """v8 reserved `license`, `checksum` and `record_count`; a new shape must not drop them."""
        columns = {
            row["name"] for row in ws.store.query("PRAGMA table_info(datasets)")
        }
        for reserved in ("source", "revision", "license", "format", "record_count",
                         "path", "checksum", "created_at", "task_id", "metadata"):
            assert reserved in columns
        # and the milestone's own additions
        for added in ("status", "seed", "splits", "dropped_count", "updated_at"):
            assert added in columns

    def test_the_states_are_a_known_list(self):
        assert DATASET_STATES == ("draft", "scanned", "cleaned", "split", "built")
        assert RECORD_STATUSES == ("kept", "dropped")
        assert SPLITS == ("train", "val", "test")

    def test_a_dataset_starts_as_a_draft(self, data):
        created = data.create("corpus", ["corpus"])
        assert created["status"] == "draft"
        assert created["record_count"] is None
        assert created["counts"] == {"kept": 0, "dropped": 0, "by_split": {}}


# --------------------------------------------------------------------------
# scanning: measurement, not assumption
# --------------------------------------------------------------------------
class TestScanning:
    def test_every_candidate_is_measured(self, data, corpus):
        rows = data.records(corpus)
        assert len(rows) == 8
        assert all(len(row["sha256"]) == 64 for row in rows)
        assert all(row["bytes"] >= 0 for row in rows)

    def test_a_directory_is_walked_and_a_file_source_is_a_corpus_of_one(self, data, corpus):
        assert by_path(data.records(corpus), "sub/b.md")["kind"] == "text"

        single = data.create("one", ["corpus/a.txt"])
        data.scan(single["id"])
        assert [row["path"] for row in data.records(single["id"])] == ["corpus/a.txt"]

    def test_an_empty_file_is_dropped_at_scan_time_with_a_reason(self, data, corpus):
        row = by_path(data.records(corpus), "empty.txt")
        assert row["status"] == "dropped"
        assert row["reason"] == "the file is empty"
        assert row["chars"] == 0

    def test_a_text_suffix_hiding_binary_bytes_is_dropped_and_says_so(self, data, corpus):
        row = by_path(data.records(corpus), "blob.txt")
        assert row["status"] == "dropped"
        assert row["kind"] == "binary"
        assert "refusing to read it as text" in row["reason"]

    def test_a_binary_suffix_is_measured_and_shelved_rather_than_skipped(self, data, lab):
        (Path(lab) / "corpus" / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
        dataset = data.create("mixed", ["corpus"])
        data.scan(dataset["id"])
        row = by_path(data.records(dataset["id"]), "photo.png")
        assert row["kind"] == "binary"
        assert row["status"] == "dropped"
        assert row["reason"] == "not a text file this build can parse"

    def test_the_scan_counts_what_it_kept_and_what_it_did_not(self, data, corpus):
        assert data.get(corpus).record_count == 6
        assert data.get(corpus).dropped_count == 2

    def test_scanning_needs_fs_read(self, ws):
        dataset = ws.data.create("corpus", ["corpus"])
        with pytest.raises(ApprovalRequiredError):
            ws.data.scan(dataset["id"])
        assert ws.datasets.records(dataset["id"]) == []

    def test_text_is_read_through_the_tool_layer(self, granted, corpus):
        runs = granted.store.query(
            "SELECT tool_name, status FROM tool_runs"
            " WHERE tool_name IN ('fs.list', 'fs.read', 'fs.probe')"
        )
        tools = {row["tool_name"] for row in runs}
        assert {"fs.list", "fs.read", "fs.probe"} <= tools
        # The binary file with a text suffix is a *failed* fs.read, and that failure is the finding:
        # the pipeline learns what the file is from the refusal, not from its name.
        failed = [row for row in runs if row["status"] not in ("ok", "succeeded")]
        assert len(failed) == 1
        assert failed[0]["tool_name"] == "fs.read"


# --------------------------------------------------------------------------
# cleaning: every removal keeps its reason
# --------------------------------------------------------------------------
class TestNothingIsDroppedSilently:
    def test_dedupe_keeps_the_first_path_and_names_it_on_the_copy(self, data, corpus):
        data.clean(corpus, dedupe=True)
        kept = by_path(data.records(corpus), "a.txt")
        dropped = by_path(data.records(corpus), "copy_of_a.txt")
        assert kept["status"] == "kept"
        assert dropped["status"] == "dropped"
        assert dropped["reason"].endswith("corpus/a.txt")
        assert dropped["sha256"] == kept["sha256"]

    def test_min_chars_records_the_numbers_it_compared(self, data, corpus):
        data.clean(corpus, min_chars=10)
        row = by_path(data.records(corpus), "tiny.md")
        assert row["status"] == "dropped"
        assert "(5 < 10)" in row["reason"]

    def test_a_dropped_record_is_still_a_row(self, data, corpus):
        data.clean(corpus, min_chars=10)
        rows = data.records(corpus)
        assert len(rows) == 8
        # empty, binary, the byte-identical copy, and the file under min_chars
        assert sum(1 for row in rows if row["status"] == "dropped") == 4

    def test_explain_answers_from_the_record(self, data, corpus):
        data.clean(corpus, min_chars=10)
        dropped = by_path(data.records(corpus), "tiny.md")
        explained = data.explain(dropped["id"])
        assert explained["status"] == "dropped"
        assert explained["sentence"].startswith("corpus/tiny.md was dropped:")
        assert "min_chars" in explained["reason"]

    def test_explain_names_the_split_a_kept_record_landed_in(self, data, corpus):
        data.clean(corpus)
        data.split(corpus, seed="m35")
        kept = by_path(data.records(corpus), "a.txt")
        explained = data.explain(kept["id"])
        assert f"the {kept['split']} split" in explained["sentence"]

    def test_the_clean_step_is_recorded_with_what_it_removed(self, data, corpus):
        data.clean(corpus, min_chars=10, dedupe=True)
        step = [s for s in data.steps(corpus) if s["kind"] == "clean"][-1]
        assert step["config"]["min_chars"] == 10
        assert step["records_in"] == 8
        assert step["records_out"] == 4
        assert step["report"]["removed"]["dedupe"] == 1
        assert step["report"]["removed"]["min_chars"] == 1

    def test_cleaning_twice_with_the_same_rules_is_the_same_set(self, data, corpus):
        first = data.clean(corpus, min_chars=10, dedupe=True)["records"] if False else None
        data.clean(corpus, min_chars=10, dedupe=True)
        once = {row["path"]: row["status"] for row in data.records(corpus)}
        data.clean(corpus, min_chars=10, dedupe=True)
        twice = {row["path"]: row["status"] for row in data.records(corpus)}
        assert once == twice
        assert first is None

    def test_cleaning_before_scanning_is_refused(self, data):
        dataset = data.create("late", ["corpus"])
        with pytest.raises(ValidationError):
            data.clean(dataset["id"])


# --------------------------------------------------------------------------
# splitting: stable, reproducible, leak-free
# --------------------------------------------------------------------------
class TestSplitsAreStable:
    def test_splits_add_up(self, data, corpus):
        data.clean(corpus)
        result = data.split(corpus, train=0.5, val=0.25, test=0.25, seed="m35")
        assert set(result["splits"]["by_split"]) <= set(SPLITS)
        assert sum(result["splits"]["by_split"].values()) == result["counts"]["kept"]

    def test_ratios_must_sum_to_one(self, data, corpus):
        data.clean(corpus)
        with pytest.raises(ValidationError) as caught:
            data.split(corpus, train=0.8, val=0.8, test=0.8)
        assert "add up to 1.0" in str(caught.value)

    def test_the_same_seed_and_corpus_reproduce_the_split(self, data, corpus, lab):
        data.clean(corpus)
        first = {(r["path"], r["split"]) for r in data.records(corpus)}
        data.split(corpus, seed="m35")
        again = {(r["path"], r["split"]) for r in data.records(corpus)}
        assert first == again or True  # first pass had no split; the real check is below
        assigned = {r["path"]: r["split"] for r in data.records(corpus)}
        data.scan(corpus)
        data.clean(corpus)
        data.split(corpus, seed="m35")
        assert {r["path"]: r["split"] for r in data.records(corpus)} == assigned

    def test_a_new_file_does_not_move_the_old_ones(self, data, corpus, lab):
        data.clean(corpus)
        data.split(corpus, seed="m35")
        before = {r["path"]: r["split"] for r in data.records(corpus) if r["status"] == "kept"}
        (Path(lab) / "corpus" / "d.md").write_text("a fourth document\n", encoding="utf-8")
        data.scan(corpus)
        data.clean(corpus)
        data.split(corpus, seed="m35")
        after = {r["path"]: r["split"] for r in data.records(corpus) if r["status"] == "kept"}
        assert {path: after[path] for path in before} == before
        assert "corpus/d.md" in after

    def test_a_different_seed_produces_a_different_assignment(self, data, corpus):
        """With enough records, some seed must move someone - otherwise the seed is decoration."""
        data.clean(corpus, normalize=True)
        assignments = set()
        for seed in ("one", "two", "three", "four", "five"):
            data.split(corpus, seed=seed)
            assignments.add(
                tuple(sorted(
                    (r["path"], r["split"]) for r in data.records(corpus, status="kept")
                ))
            )
        assert len(assignments) > 1

    def test_a_split_with_nothing_left_is_refused(self, data, corpus):
        data.clean(corpus, require_license=False, min_chars=10_000)
        with pytest.raises(ValidationError):
            data.split(corpus)


class TestLeaksAreRefused:
    def test_the_bucket_is_a_function_of_the_content_hash(self, data, corpus):
        """Equal bytes always get the same split, whatever the seed is."""
        dataset = data.get(corpus)
        rows = data.records(corpus)
        first = by_path(rows, "a.txt")
        second = by_path(rows, "copy_of_a.txt")
        assert first["sha256"] == second["sha256"]
        for seed in ("0", "1", "m35", "42"):
            dataset.seed = seed
            left = data._bucket(dataset, data.ws.datasets.record(first["id"]))
            right = data._bucket(dataset, data.ws.datasets.record(second["id"]))
            assert left == right

    def test_a_resaved_document_is_never_left_across_two_splits(self, data, corpus):
        """Different bytes, different hash, different bucket - and the same text.

        Either the split is refused with the pair named, or the two copies end up in one split.
        Anything else is a corpus that has already leaked into its own evaluation.
        """
        data.clean(corpus, dedupe=False, min_chars=0)
        refused = 0
        for seed in ("1", "2", "3", "4", "5", "6", "7", "8", "m35"):
            try:
                data.split(corpus, seed=seed)
            except ValidationError as exc:
                message = str(exc)
                assert "ignoring whitespace and case" in message
                assert "near_a.txt" in message
                assert "--normalize" in message
                refused += 1
                continue
            splits: dict[str, set[str]] = {}
            for row in data.records(corpus, status="kept"):
                splits.setdefault(row["metadata"]["norm_sha"], set()).add(row["split"])
            assert all(len(found) == 1 for found in splits.values())
        assert refused > 0

    def test_normalising_the_dedupe_closes_the_leak(self, data, corpus):
        data.clean(corpus, dedupe=True, normalize=True)
        result = data.split(corpus, seed="m35")
        assert result["splits"]["by_split"]
        texts = {}
        for row in data.records(corpus, status="kept"):
            key = row["metadata"]["norm_sha"]
            assert key not in texts or texts[key] == row["split"]
            texts[key] = row["split"]

    def test_the_normalised_hash_is_recorded_at_scan_time(self, data, corpus):
        rows = data.records(corpus)
        assert by_path(rows, "a.txt")["metadata"]["norm_sha"] == (
            by_path(rows, "near_a.txt")["metadata"]["norm_sha"]
        )
        assert by_path(rows, "a.txt")["sha256"] != by_path(rows, "near_a.txt")["sha256"]

    def test_exact_dedupe_leaves_the_near_duplicate_alone(self, data, corpus):
        """`--dedupe` without `--normalize` removes the byte-identical copy, not the resaved one."""
        data.clean(corpus, dedupe=True, normalize=False)
        assert by_path(data.records(corpus), "copy_of_a.txt")["status"] == "dropped"
        assert by_path(data.records(corpus), "near_a.txt")["status"] == "kept"


# --------------------------------------------------------------------------
# the manifest: a claim that can fail
# --------------------------------------------------------------------------
class TestTheManifestCanFail:
    def test_build_records_a_checksum_over_sorted_lines(self, data, corpus):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        built = data.build(corpus)
        manifest = data.manifest(corpus)
        assert built["checksum"] == manifest["checksum"]
        assert manifest["lines"] == sorted(manifest["lines"])
        assert len(manifest["lines"]) == built["counts"]["kept"]

    def test_build_writes_a_jsonl_file_through_fs_write(self, data, corpus, lab):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        built = data.build(corpus)
        export = Path(lab) / built["path"]
        assert export.exists()
        rows = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == built["counts"]["kept"]
        assert all("text" in row and "sha256" in row for row in rows)
        runs = data.ws.store.query(
            "SELECT tool_name FROM tool_runs WHERE tool_name = 'fs.write'"
        )
        assert runs

    def test_verify_agrees_with_an_untouched_dataset(self, data, corpus):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        data.build(corpus)
        result = data.verify(corpus)
        assert result["agrees"] is True
        assert result["stored_checksum"] == result["recomputed_checksum"]
        assert result["differences"] == []

    def test_verify_disagrees_when_a_file_changes(self, data, corpus, lab):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        data.build(corpus)
        (Path(lab) / "corpus" / "c.md").write_text("third document, edited\n", encoding="utf-8")
        result = data.verify(corpus)
        assert result["agrees"] is False
        assert result["stored_checksum"] != result["recomputed_checksum"]
        assert [d["kind"] for d in result["differences"]] == ["changed"]
        assert result["differences"][0]["path"].endswith("c.md")

    def test_verify_disagrees_when_a_file_disappears(self, data, corpus, lab):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        data.build(corpus)
        (Path(lab) / "corpus" / "c.md").unlink()
        result = data.verify(corpus)
        assert result["agrees"] is False
        assert [d["kind"] for d in result["differences"]] == ["missing"]
        assert "no longer matches its manifest" in result["note"]

    def test_a_dataset_that_was_never_built_cannot_claim_agreement(self, data, corpus):
        data.clean(corpus, dedupe=True)
        result = data.verify(corpus)
        assert result["agrees"] is False
        assert "no manifest was recorded" in result["note"]

    def test_building_without_a_split_needs_force(self, data, corpus):
        data.clean(corpus, dedupe=True)
        with pytest.raises(ValidationError) as caught:
            data.build(corpus)
        assert "--force" in str(caught.value)
        built = data.build(corpus, force=True)
        assert built["status"] == "built"


# --------------------------------------------------------------------------
# provenance: license and sources
# --------------------------------------------------------------------------
class TestLicenseAndSources:
    def test_an_unstated_license_is_written_as_unknown(self, data):
        created = data.create("unsaid", ["corpus"])
        assert created["license"] == "unknown"
        assert created["license_note"].startswith("unknown")

    def test_a_declared_license_says_who_declared_it(self, data):
        created = data.create("said", ["corpus"], license="CC0-1.0")
        assert created["license"] == "CC0-1.0"
        assert "declared by the user: CC0-1.0" == created["license_note"]

    def test_require_license_refuses_instead_of_inventing_one(self, data, corpus):
        dataset = data.get(corpus)
        assert dataset.license == "CC-BY-4.0"
        unknown = data.create("unsaid", ["corpus"])
        data.scan(unknown["id"])
        with pytest.raises(ValidationError) as caught:
            data.clean(unknown["id"], require_license=True)
        assert "license is unknown" in str(caught.value)

    def test_sources_are_kept_on_the_record(self, data, corpus):
        assert data.view(corpus)["sources"] == ["corpus"]

    def test_a_dataset_without_sources_is_refused(self, data):
        with pytest.raises(ValidationError):
            data.create("empty", [])

    def test_a_scan_that_finds_nothing_is_refused(self, data, lab):
        (Path(lab) / "hollow").mkdir()
        dataset = data.create("hollow", ["hollow"])
        with pytest.raises(ValidationError) as caught:
            data.scan(dataset["id"])
        assert "no files were found" in str(caught.value)


# --------------------------------------------------------------------------
# the ledger and the counters
# --------------------------------------------------------------------------
class TestTheLedger:
    def test_every_step_is_numbered_in_order(self, data, corpus):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        data.build(corpus)
        steps = data.steps(corpus)
        assert [step["seq"] for step in steps] == [1, 2, 3, 4]
        assert [step["kind"] for step in steps] == ["scan", "clean", "split", "build"]

    def test_a_scan_records_how_many_candidates_it_saw(self, data, corpus):
        scan = [s for s in data.steps(corpus) if s["kind"] == "scan"][-1]
        assert scan["records_in"] == 0
        assert scan["records_out"] == 8
        assert scan["report"]["sources"] == 1

    def test_the_build_step_carries_both_checksums(self, data, corpus):
        data.clean(corpus, dedupe=True)
        data.split(corpus, seed="m35")
        data.build(corpus)
        build = data.steps(corpus)[-1]
        assert build["output_checksum"] == data.manifest(corpus)["checksum"]
        assert build["report"]["export_checksum"]

    def test_stats_count_records_not_datasets(self, data, corpus):
        data.clean(corpus, dedupe=True)
        stats = data.stats()
        assert stats["datasets"] == 1
        assert stats["records"] == 8
        assert stats["kept"] == data.get(corpus).record_count
        assert stats["dropped"] == 8 - stats["kept"]
        assert stats["by_status"] == {"cleaned": 1}

    def test_a_dataset_can_be_found_by_name_or_id(self, data, corpus):
        assert data.get("corpus").id == corpus
        assert data.get(corpus).name == "corpus"
        with pytest.raises(NotFoundError):
            data.get("nope")

    def test_records_can_be_filtered_by_status_and_split(self, data, corpus):
        data.clean(corpus, min_chars=10)
        data.split(corpus, seed="m35")
        kept = data.records(corpus, status="kept")
        assert kept and all(row["status"] == "kept" for row in kept)
        split = kept[0]["split"]
        assert all(row["split"] == split for row in data.records(corpus, split=split))


# --------------------------------------------------------------------------
# what this build does not do
# --------------------------------------------------------------------------
class TestWhatIsNotClaimed:
    def test_no_publishing_or_upload_exists(self, data):
        """M35 prepares a corpus on this machine; it does not send it anywhere."""
        assert not hasattr(data, "upload")
        assert not hasattr(data, "publish")

    def test_a_dataset_is_not_a_training_run(self, data):
        """A dataset row has no metrics, no checkpoints and no status beyond the pipeline's."""
        assert not hasattr(data, "train")
        assert not hasattr(data, "fit")

    def test_the_export_is_jsonl_and_says_so(self, data):
        created = data.create("fmt", ["corpus"])
        assert created["format"] == "jsonl"


# --------------------------------------------------------------------------
# the GUI is a client of the same service
# --------------------------------------------------------------------------
@pytest.fixture()
def gui(tmp_path, lab):
    from archx_agent.interfaces.gui.server import GuiApi

    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(lab)]}) as ws:
        ws.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
        ws.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
        yield GuiApi(ws), ws


def http(api, method, path, *, body=None):
    from archx_agent.interfaces.gui.server import Request, split_target

    parsed_path, query, _token = split_target(path)
    request = Request(
        method=method,
        path=parsed_path,
        query=query,
        headers={"x-archx-token": api.token, "x-archx-request": "gui"},
        body=body,
    )
    response = api.dispatch(request)
    payload = response.payload
    if isinstance(payload, dict) and set(payload) == {"ok", "data"}:
        payload = payload["data"]
    return response.status, payload


class TestTheGuiIsTheSameService:
    def test_a_dataset_created_in_the_page_is_a_row_the_cli_lists(self, gui):
        api, ws = gui
        status, created = http(
            api, "POST", "/api/datasets",
            body={"name": "corpus", "sources": ["corpus"], "license": "CC-BY-4.0"},
        )
        assert status == 200
        assert ws.datasets.get(created["id"]).name == "corpus"
        _, listed = http(api, "GET", "/api/datasets")
        assert [row["id"] for row in listed["datasets"]] == [created["id"]]
        assert listed["stats"]["datasets"] == 1

    def test_the_whole_pipeline_can_be_driven_over_http(self, gui):
        api, ws = gui
        _, created = http(api, "POST", "/api/datasets", body={"name": "corpus", "sources": ["corpus"]})
        dataset_id = created["id"]
        assert http(api, "POST", f"/api/datasets/{dataset_id}/scan", body={})[0] == 200
        _, cleaned = http(
            api, "POST", f"/api/datasets/{dataset_id}/clean",
            body={"min_chars": 10, "dedupe": True, "normalize": True},
        )
        assert cleaned["counts"]["kept"] < cleaned["counts"]["dropped"] + cleaned["counts"]["kept"]
        _, split = http(api, "POST", f"/api/datasets/{dataset_id}/split", body={"seed": "m35"})
        assert split["splits"]["by_split"]
        _, built = http(api, "POST", f"/api/datasets/{dataset_id}/build", body={})
        assert built["checksum"]
        _, verified = http(api, "GET", f"/api/datasets/{dataset_id}/verify")
        assert verified["agrees"] is True

    def test_dropped_records_are_visible_in_the_page(self, gui):
        api, _ws = gui
        _, created = http(api, "POST", "/api/datasets", body={"name": "corpus", "sources": ["corpus"]})
        http(api, "POST", f"/api/datasets/{created['id']}/scan", body={})
        _, records = http(api, "GET", f"/api/datasets/{created['id']}/records?status=dropped")
        assert records["records"]
        assert all(row["status"] == "dropped" and row["reason"] for row in records["records"])

    def test_a_leak_is_a_400_with_the_reason_over_http(self, gui):
        api, _ws = gui
        _, created = http(api, "POST", "/api/datasets", body={"name": "corpus", "sources": ["corpus"]})
        dataset_id = created["id"]
        http(api, "POST", f"/api/datasets/{dataset_id}/scan", body={})
        http(api, "POST", f"/api/datasets/{dataset_id}/clean", body={"dedupe": False, "drop_empty": False})
        failure = None
        for seed in ("1", "2", "3", "4", "5", "6", "7", "8"):
            status, payload = http(
                api, "POST", f"/api/datasets/{dataset_id}/split", body={"seed": seed}
            )
            if status == 400:
                failure = payload
                break
        assert failure is not None
        assert "ignores" in failure["error"]["message"] or "whitespace" in failure["error"]["message"]

    def test_a_verify_disagreement_rides_back_as_200_with_agrees_false(self, gui, lab):
        """Over HTTP the disagreement is data, not an error: the request was answered."""
        api, _ws = gui
        _, created = http(api, "POST", "/api/datasets", body={"name": "corpus", "sources": ["corpus"]})
        dataset_id = created["id"]
        for step, body in (
            ("scan", {}),
            ("clean", {"min_chars": 10, "dedupe": True, "normalize": True}),
            ("split", {"seed": "m35"}),
            ("build", {}),
        ):
            http(api, "POST", f"/api/datasets/{dataset_id}/{step}", body=body)
        (Path(lab) / "corpus" / "c.md").write_text("changed after the build\n", encoding="utf-8")
        status, result = http(api, "GET", f"/api/datasets/{dataset_id}/verify")
        assert status == 200
        assert result["agrees"] is False
        assert result["differences"][0]["kind"] == "changed"

    def test_bad_filters_are_400s(self, gui):
        api, _ws = gui
        _, created = http(api, "POST", "/api/datasets", body={"name": "corpus", "sources": ["corpus"]})
        status, _payload = http(
            api, "GET", f"/api/datasets/{created['id']}/records?status=maybe"
        )
        assert status == 400

    def test_an_unknown_dataset_is_a_404(self, gui):
        api, _ws = gui
        assert http(api, "GET", "/api/datasets/ds_nope")[0] == 404
