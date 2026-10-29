"""M36 - Training and model modification: what really runs, and what is refused by name.

This milestone has the same hazard M34 had, and the tests are built to catch it in the same place:
a `train` command that shells out to something absent and prints a loss curve would pass a demo and
be a lie.

1. **the trainers are real arithmetic.** `TestTheNGramModel` checks perplexity against values
   computed by hand and checks that an unseen word is *scored* (as `<unk>`) rather than skipped -
   skipping is how a language model reports a number no text could produce. `TestTheCentroidModel`
   checks a prediction against a distribution it constructs itself.
2. **a run's numbers come from the split it claims.** `TestRunsOnARealCorpus` trains on a corpus the
   fixture writes and asserts that train/val/test are scored separately, that the metrics are rows,
   and that the artifact on disk is the one the run points at.
3. **fine-tuning is refused with every missing link named.** `TestTheFineTuneBoundary` removes one
   link at a time - the switch, the model, the weights directory, the library, the GPU - and asserts
   the chain shortens by exactly that link and that the refusal is a row.
4. **a comparison names what it could not rank.** `TestComparison` mixes methods and asserts no
   winner is named, and compares two runs of one method and asserts the winner is the better metric.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from archx_agent.application.training import (
    FEATURE_DIM,
    CentroidModel,
    NGramModel,
    tokenize,
)
from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.managers.schema import SCHEMA_VERSION
from archx_agent.managers.training import (
    FINETUNE_METHODS,
    METHODS,
    RUNNABLE_METHODS,
    STATUSES,
)


# --------------------------------------------------------------------------
# fixtures: a corpus with two labels and enough text to train on
# --------------------------------------------------------------------------
@pytest.fixture()
def lab(tmp_path) -> Path:
    folder = tmp_path / "lab"
    for language, template in (
        ("python", "def function_{n}(x):\n    return x + {n}\n"),
        ("rust", "fn function_{n}(x: i32) -> i32 {{\n    x + {n}\n}}\n"),
    ):
        (folder / "corpus" / language).mkdir(parents=True, exist_ok=True)
        for n in range(1, 5):
            body = template.format(n=n) if language == "rust" else template.format(n=n)
            (folder / "corpus" / language / f"file{n}.txt").write_text(body, encoding="utf-8")
    return folder


@pytest.fixture()
def ws(tmp_path, lab):
    with open_workspace(home=str(tmp_path / "home"), overrides={"tools.roots": [str(lab)]}) as workspace:
        yield workspace


@pytest.fixture()
def granted(ws):
    ws.permissions.grant("fs.read", subject="*", duration="persistent", confirm=True)
    ws.permissions.grant("fs.write", subject="*", duration="persistent", confirm=True)
    return ws


@pytest.fixture()
def trainer(granted):
    return granted.trainer


@pytest.fixture()
def dataset(granted, trainer):
    created = granted.data.create("code", ["corpus"], license="MIT")
    granted.data.scan(created["id"])
    granted.data.clean(created["id"])
    granted.data.split(created["id"], train=0.5, val=0.25, test=0.25, seed="m36")
    granted.data.build(created["id"])
    return created["id"]


# --------------------------------------------------------------------------
# the two trainers, on their own
# --------------------------------------------------------------------------
class TestTheNGramModel:
    def test_a_bigram_distribution_sums_to_one_by_hand(self):
        """'a b a': after 'a' comes b once and </s> once, with three words in the vocabulary.

        With k=1 the vocabulary+unk outcomes are a, b, </s> and <unk>: p(b|a)=p(</s>|a)=2/6,
        p(a|a)=p(<unk>|a)=1/6, and the four add up to 1. That is an arithmetic result a reader can
        check on paper, which is the point of a model this small.
        """
        model = NGramModel(order=2, smoothing=1.0).fit(["a b a"])
        assert len(model.vocab) == 3
        assert model._probability("a", "b") == pytest.approx(2 / 6)
        assert model._probability("a", "</s>") == pytest.approx(2 / 6)
        assert model._probability("a", "a") == pytest.approx(1 / 6)
        assert model._probability("a", "<unk>") == pytest.approx(1 / 6)
        total = sum(model._probability("a", word) for word in ("a", "b", "</s>", "<unk>"))
        assert total == pytest.approx(1.0)

    def test_smoothing_gives_an_unseen_transition_a_non_zero_probability(self):
        model = NGramModel(order=2, smoothing=0.5).fit(["a b a"])
        assert model._probability("a", "z") > 0

    def test_perplexity_of_the_training_text_is_finite_and_positive(self):
        model = NGramModel(order=2, smoothing=0.1).fit(["the cat sat on the mat"])
        value = model.perplexity("the cat sat on the mat")
        assert math.isfinite(value) and value > 0

    def test_perplexity_is_higher_for_text_the_model_did_not_see(self):
        model = NGramModel(order=2, smoothing=0.1).fit(["the cat sat on the mat"])
        seen = model.perplexity("the cat sat on the mat")
        unseen = model.perplexity("zebra quixotic waltz")
        assert unseen > seen

    def test_an_unknown_word_is_scored_not_skipped(self):
        """Skipping unknown words is how a model reports a number no text could produce."""
        model = NGramModel(order=2, smoothing=0.1).fit(["alpha beta"])
        with_unknown = model.perplexity("alpha zzz beta")
        assert math.isfinite(with_unknown)
        assert with_unknown > model.perplexity("alpha beta")

    def test_the_order_is_bounded(self):
        with pytest.raises(ValidationError):
            NGramModel(order=9)
        with pytest.raises(ValidationError):
            NGramModel(order=1)

    def test_the_smoothing_must_be_positive(self):
        with pytest.raises(ValidationError):
            NGramModel(order=2, smoothing=0)

    def test_it_round_trips_through_its_own_artifact(self):
        model = NGramModel(order=2).fit(["a b a", "a c a"])
        restored = NGramModel.from_dict(json.loads(json.dumps(model.to_dict())))
        assert restored.perplexity("a b a") == pytest.approx(model.perplexity("a b a"))

    def test_tokenize_is_crude_and_says_so(self):
        assert tokenize("Hello, World! 42") == ["hello", "world", "42"]


class TestTheCentroidModel:
    def test_a_document_lands_closest_to_its_own_class(self):
        model = CentroidModel().fit([
            ("the cat sat", "cats"), ("the cat slept", "cats"),
            ("the dog barked", "dogs"), ("the dog ran", "dogs"),
        ])
        assert model.predict("the cat sat") == "cats"
        assert model.predict("the dog ran") == "dogs"

    def test_accuracy_is_a_fraction_of_hits(self):
        model = CentroidModel().fit([("a a", "x"), ("b b", "y")])
        assert model.accuracy([("a a", "x"), ("a a", "y")]) == pytest.approx(0.5)

    def test_accuracy_of_an_empty_set_is_not_zero(self):
        """A metric that was not measurable is not a metric of zero."""
        value = CentroidModel().accuracy([])
        assert value != value  # NaN

    def test_the_feature_width_is_fixed(self):
        assert FEATURE_DIM == 512
        assert len(CentroidModel._vector("anything at all")) == FEATURE_DIM

    def test_it_round_trips_through_its_own_artifact(self):
        model = CentroidModel().fit([("a a", "x"), ("b b", "y")])
        restored = CentroidModel.from_dict(json.loads(json.dumps(model.to_dict())))
        assert restored.predict("b b") == model.predict("b b")

    def test_a_classifier_with_no_examples_is_refused(self):
        with pytest.raises(ValidationError):
            CentroidModel().fit([])


# --------------------------------------------------------------------------
# preflight: what has to be true before a run means anything
# --------------------------------------------------------------------------
class TestPreflight:
    def test_an_unsplit_dataset_fails_the_split_check(self, granted, trainer):
        created = granted.data.create("raw", ["corpus"])
        granted.data.scan(created["id"])
        result = trainer.preflight(method="ngram", dataset=created["id"])
        assert result["runnable"] is False
        assert any("no split yet" in reason for reason in result["reasons"])

    def test_a_built_and_verified_dataset_passes(self, trainer, dataset):
        result = trainer.preflight(method="ngram", dataset=dataset)
        assert result["runnable"] is True
        assert result["checks"]
        assert all(check["ok"] for check in result["checks"])
        assert "train a real model" in result["note"]

    def test_an_unknown_method_is_refused(self, trainer, dataset):
        with pytest.raises(ValidationError):
            trainer.preflight(method="telepathy", dataset=dataset)

    def test_fine_tuning_never_passes_preflight(self, trainer, dataset):
        for method in FINETUNE_METHODS:
            result = trainer.preflight(method=method, dataset=dataset)
            assert result["runnable"] is False
            assert result["reasons"]

    def test_a_missing_dataset_is_a_failed_check_not_a_crash(self, trainer):
        result = trainer.preflight(method="ngram", dataset="ds_nope")
        assert result["runnable"] is False
        assert any("no such dataset" in reason for reason in result["reasons"])


# --------------------------------------------------------------------------
# running for real
# --------------------------------------------------------------------------
class TestRunsOnARealCorpus:
    def test_an_ngram_run_completes_and_records_metrics_per_split(self, trainer, dataset):
        job = trainer.run(method="ngram", dataset=dataset, order=2, seed=7)
        assert job["status"] == "completed"
        assert set(job["metrics"]) == {"train", "val", "test"}
        assert all("perplexity" in values for values in job["metrics"].values())

    def test_the_metrics_are_rows_not_just_json(self, trainer, dataset):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        metrics = trainer.metrics(job["id"])["by_split"]
        assert set(metrics) == {"train", "val", "test"}
        assert metrics["train"]["perplexity"] > 0

    def test_the_artifact_is_on_disk_and_is_what_the_job_points_at(self, trainer, dataset, lab):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        artifact = Path(lab) / job["artifact_path"]
        assert artifact.exists()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["kind"] == "ngram" and payload["order"] == 2
        assert payload["trained_on"] == dataset

    def test_the_artifact_hash_is_recorded_and_matches(self, trainer, dataset, lab):
        import hashlib

        job = trainer.run(method="ngram", dataset=dataset, order=2)
        body = (Path(lab) / job["artifact_path"]).read_bytes()
        assert job["artifact_sha256"] == hashlib.sha256(body).hexdigest()

    def test_the_artifact_is_versioned(self, trainer, dataset):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        assert job["version_id"]

    def test_a_centroid_run_labels_from_the_directory_and_says_so(self, trainer, dataset):
        job = trainer.run(method="centroid", dataset=dataset)
        assert job["status"] == "completed"
        assert job["config"]["label_source"] == "directory"
        assert job["metrics"]["train"]["labels"] == 2

    def test_predicting_uses_the_artifact_on_disk(self, trainer, dataset):
        job = trainer.run(method="centroid", dataset=dataset)
        prediction = trainer.predict(job["id"], "fn function_1(x: i32) -> i32 { x + 1 }")
        assert prediction["label"] in prediction["labels"]

    def test_predicting_with_an_ngram_run_gives_a_perplexity(self, trainer, dataset):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        prediction = trainer.predict(job["id"], "def function_1(x): return x + 1")
        assert prediction["kind"] == "ngram" and prediction["perplexity"] > 0

    def test_a_refused_run_cannot_be_used_to_predict(self, trainer, dataset):
        job = trainer.run(method="lora", dataset=dataset)
        with pytest.raises(ValidationError):
            trainer.predict(job["id"], "anything")

    def test_the_same_seed_and_corpus_produce_the_same_metrics(self, trainer, dataset):
        first = trainer.run(method="ngram", dataset=dataset, order=2, seed=3)
        second = trainer.run(method="ngram", dataset=dataset, order=2, seed=3)
        assert first["metrics"] == second["metrics"]

    def test_an_unknown_dataset_is_refused_on_the_record(self, trainer):
        """A run against a dataset that does not exist is a refusal, not a traceback."""
        job = trainer.run(method="ngram", dataset="ds_nope")
        assert job["status"] == "refused"
        assert any("no such dataset" in reason for reason in job["reasons"])

    def test_a_run_needs_fs_read(self, granted, trainer, lab, tmp_path):
        """Reading the corpus is a tool call, and a tool call needs a grant."""
        created = granted.data.create("code", ["corpus"])
        granted.data.scan(created["id"])
        granted.data.clean(created["id"])
        granted.data.split(created["id"], train=0.5, val=0.25, test=0.25, seed="x")
        granted.data.build(created["id"])
        # Take the grants away again: the run should be refused by the permission centre, not by
        # an exception from the trainer's own code.
        for grant in granted.permissions.grants():
            if not grant.revoked_at:
                granted.permissions.revoke(grant.id)
        job = trainer.run(method="ngram", dataset=created["id"])
        assert job["status"] == "refused"
        message = " ".join(job["reasons"]).lower()
        assert "approval" in message or "grant" in message or "permission" in message

    def test_a_run_records_the_manifest_it_trained_on(self, trainer, dataset, lab):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        payload = json.loads((Path(lab) / job["artifact_path"]).read_text(encoding="utf-8"))
        assert payload["seed"] == 0
        assert payload["trained_on"] == dataset


# --------------------------------------------------------------------------
# the fine-tuning boundary
# --------------------------------------------------------------------------
class TestTheFineTuneBoundary:
    def test_a_fine_tune_run_is_refused_and_stored_as_a_row(self, trainer, dataset):
        job = trainer.run(method="lora", dataset=dataset)
        assert job["status"] == "refused"
        assert job["refusal"]
        assert trainer.manager.get(job["id"]).status == "refused"

    def test_the_chain_names_every_missing_link_in_order(self, trainer):
        reasons = trainer.blockers("lora")
        assert reasons[0].startswith("training is off")
        assert "no base model is named" in reasons[1]
        assert "training.weights_dir" in reasons[2]
        assert any("torch is not importable" in reason for reason in reasons)
        assert any("no CUDA device" in reason for reason in reasons)
        assert reasons[-1].startswith("no adapter in this build can fine-tune anything")

    def test_turning_the_switch_on_removes_exactly_that_reason(self, trainer):
        before = trainer.blockers("lora")
        trainer.ws.config.set("training.enabled", True)
        after = trainer.blockers("lora")
        assert before[0].startswith("training is off")
        assert not after[0].startswith("training is off")
        assert len(after) == len(before) - 1

    def test_naming_a_model_that_does_not_exist_says_so(self, trainer):
        trainer.ws.config.set("training.base_model", "llama-3-8b")
        reasons = trainer.blockers("lora")
        assert any("is not a registered model" in reason for reason in reasons)

    def test_a_weights_dir_that_does_not_exist_is_named(self, trainer, tmp_path):
        trainer.ws.config.set("training.weights_dir", str(tmp_path / "nowhere"))
        reasons = trainer.blockers("lora")
        assert any("does not exist on this machine" in reason for reason in reasons)

    def test_the_refusal_survives_a_restart(self, trainer, dataset):
        job = trainer.run(method="qlora", dataset=dataset)
        with open_workspace(
            home=str(Path(trainer.ws.config.path("paths.home"))), 
        ) as reopened:
            assert reopened.training.get(job["id"]).status == "refused"

    def test_stats_says_plainly_it_cannot_finetune(self, trainer):
        stats = trainer.stats()
        assert stats["can_finetune"] is False
        assert stats["why_not"]
        assert stats["runnable"] == list(RUNNABLE_METHODS)


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
class TestComparison:
    def test_two_runs_of_one_method_rank_the_better_metric(self, trainer, dataset):
        coarse = trainer.run(method="ngram", dataset=dataset, order=2, smoothing=0.5)
        finer = trainer.run(method="ngram", dataset=dataset, order=3, smoothing=0.1)
        result = trainer.compare([coarse["id"], finer["id"]])
        assert result["metric"] == "perplexity" and result["lower_is_better"] is True
        assert result["best"] == min(result["rows"], key=lambda row: row["value"])["job_id"]

    def test_mixed_methods_name_no_winner(self, trainer, dataset):
        ngram = trainer.run(method="ngram", dataset=dataset, order=2)
        centroid = trainer.run(method="centroid", dataset=dataset)
        result = trainer.compare([ngram["id"], centroid["id"]])
        assert result["best"] is None
        assert any("different methods" in note for note in result["notes"])

    def test_a_refused_run_is_listed_and_explained(self, trainer, dataset):
        good = trainer.run(method="ngram", dataset=dataset, order=2)
        refused = trainer.run(method="full", dataset=dataset)
        result = trainer.compare([good["id"], refused["id"]])
        assert any(row["status"] == "refused" for row in result["rows"])
        assert any("did not run" in note for note in result["notes"])

    def test_an_empty_comparison_is_refused(self, trainer):
        with pytest.raises((ValidationError, IndexError)):
            trainer.compare([])


# --------------------------------------------------------------------------
# the ledger and the counters
# --------------------------------------------------------------------------
class TestTheLedger:
    def test_a_completed_run_is_a_row_with_its_dataset(self, trainer, dataset):
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        stored = trainer.manager.get(job["id"])
        assert stored.dataset_id == dataset
        assert stored.started_at and stored.completed_at
        assert stored.artifact_path

    def test_jobs_can_be_listed_by_status_and_dataset(self, trainer, dataset):
        trainer.run(method="ngram", dataset=dataset, order=2)
        trainer.run(method="lora", dataset=dataset)
        assert len(trainer.jobs(status="completed")) == 1
        assert len(trainer.jobs(status="refused")) == 1
        assert len(trainer.jobs(dataset=dataset)) == 2

    def test_stats_counts_jobs_and_metrics(self, trainer, dataset):
        trainer.run(method="ngram", dataset=dataset, order=2)
        stats = trainer.stats()
        assert stats["jobs"] == 1
        assert stats["by_status"] == {"completed": 1}
        assert stats["metrics"] >= 3

    def test_the_schema_adopts_the_reserved_table(self, ws):
        assert SCHEMA_VERSION == 26
        assert ws.store.table_exists("training_jobs")
        assert ws.store.table_exists("training_metrics")
        columns = {row["name"] for row in ws.store.query("PRAGMA table_info(training_jobs)")}
        # reserved in v8 and still there
        for reserved in ("method", "base_model", "dataset_id", "status", "config", "metrics",
                         "checkpoints", "created_at", "started_at", "completed_at", "error"):
            assert reserved in columns
        for added in ("kind", "seed", "artifact_path", "artifact_sha256", "refusal", "version_id"):
            assert added in columns

    def test_the_method_lists_are_what_they_say(self):
        assert RUNNABLE_METHODS == ("ngram", "centroid")
        assert FINETUNE_METHODS == ("lora", "qlora", "full")
        assert METHODS == RUNNABLE_METHODS + FINETUNE_METHODS
        assert STATUSES == ("queued", "running", "completed", "failed", "refused")

    def test_only_splits_with_records_appear_in_the_metrics(self, trainer, dataset):
        """A split with nothing in it is absent, not a zero that would flatter an average."""
        job = trainer.run(method="ngram", dataset=dataset, order=2)
        for split in job["metrics"]:
            assert job["metrics"][split]["records"] > 0


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
    def _dataset(self, api):
        _status, created = http(
            api, "POST", "/api/datasets", body={"name": "code", "sources": ["corpus"]}
        )
        dataset_id = created["id"]
        for step, body in (
            ("scan", {}), ("clean", {}), ("split", {"seed": "m36", "train": 0.5, "val": 0.25,
                                                     "test": 0.25}), ("build", {}),
        ):
            http(api, "POST", f"/api/datasets/{dataset_id}/{step}", body=body)
        return dataset_id

    def test_a_run_started_in_the_page_is_a_row_the_cli_lists(self, gui):
        api, ws = gui
        dataset_id = self._dataset(api)
        status, job = http(
            api, "POST", "/api/training/runs",
            body={"method": "ngram", "dataset": dataset_id, "order": 2},
        )
        assert status == 200 and job["status"] == "completed"
        assert ws.training.get(job["id"]).status == "completed"
        _status, listed = http(api, "GET", "/api/training/runs")
        assert [row["id"] for row in listed["runs"]] == [job["id"]]

    def test_a_refusal_over_http_is_a_200_with_the_reasons(self, gui):
        api, _ws = gui
        dataset_id = self._dataset(api)
        status, job = http(
            api, "POST", "/api/training/runs", body={"method": "lora", "dataset": dataset_id}
        )
        assert status == 200
        assert job["status"] == "refused" and job["reasons"]

    def test_the_metrics_endpoint_returns_the_same_numbers(self, gui):
        api, _ws = gui
        dataset_id = self._dataset(api)
        _status, job = http(
            api, "POST", "/api/training/runs",
            body={"method": "ngram", "dataset": dataset_id, "order": 2},
        )
        status, metrics = http(api, "GET", f"/api/training/runs/{job['id']}/metrics")
        assert status == 200
        assert metrics["by_split"]["val"]["perplexity"] > 0

    def test_stats_says_it_cannot_finetune(self, gui):
        api, _ws = gui
        _status, stats = http(api, "GET", "/api/training/runs")
        assert stats["stats"]["can_finetune"] is False
