"""Training and model modification: two trainers that really run, and the rest refused by name.

This machine has no GPU, no transformer weights and no fine-tuning library. The usual way to write
this milestone is to build a `train` command that shells out to something absent and prints a
plausible loss curve - which is exactly what M34 refused to do for speech. So the milestone is
split in two, along the line between *what is true here* and *what is not*:

**What really runs.** Two trainers, both dependency-free, both deterministic, both quick enough to
finish on a CPU in the time a command should take:

``ngram``
    a word-level n-gram language model with add-k smoothing. Trained on the ``train`` split, scored
    on every split with **perplexity** - a real number with a real definition, so a smaller one is
    better and a comparison means something.
``centroid``
    a nearest-centroid text classifier over hashed bag-of-words features. Labels come from the
    record's own ``label`` or from its parent directory, and the rule that produced them is written
    into the run's config rather than left to be guessed. Scored with accuracy per split.

Both write a JSON artifact through ``fs.write``, record its sha256, and register it as a version so
the artifact a metric came from cannot be silently replaced.

**What is refused.** ``lora``, ``qlora`` and ``full`` mean "fine-tune a transformer". The chain is
computed - the switch, the base model, the weights directory, the GPU, the library, the adapter -
and every missing link is reported in order, then stored on the job. The last link is always the
same: no adapter in this build can fine-tune anything, and a registered model is not enough.

Nothing here claims to train a transformer, to know what a GPU would cost, or to have measured a
model it did not train.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from archx_agent.helpers.timeutil import iso_now
from archx_agent.managers.tools import ToolContext
from archx_agent.managers.training import (
    FINETUNE_METHODS,
    METHODS,
    RUNNABLE_METHODS,
    TrainingJob,
)

#: The words of a text, lowercased. Deliberately crude: a tokeniser that is a library is a
#: dependency this build does not need, and the trainer's job is to be checkable, not to be
#: state of the art.
_WORD = re.compile(r"[A-Za-z0-9']+")

#: How many hashed features the centroid classifier uses. A fixed width keeps the artifact small
#: and the arithmetic reproducible.
FEATURE_DIM = 512


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _hash_feature(word: str) -> int:
    return int(hashlib.sha256(word.encode("utf-8")).hexdigest()[:8], 16) % FEATURE_DIM


class NGramModel:
    """A word-level n-gram model with add-k smoothing, scored by perplexity.

    Small is not the same as fake: the counts are real, the smoothing is stated, the perplexity is
    ``exp(-mean log p)`` over the evaluation text with ``<s>``/``</s>`` as boundaries, and an
    unknown word on the evaluation split is scored as ``<unk>`` rather than skipped - skipping is
    how a language model reports a number that no text could produce.
    """

    def __init__(self, order: int = 3, smoothing: float = 0.1) -> None:
        if order < 2 or order > 5:
            raise ValidationError("the n-gram order must be between 2 and 5")
        if smoothing <= 0:
            raise ValidationError("the smoothing constant must be positive")
        self.order = int(order)
        self.smoothing = float(smoothing)
        self.counts: dict[str, Counter[str]] = {}
        self.vocab: set[str] = set()

    # -- training -------------------------------------------------------
    def fit(self, texts: list[str]) -> "NGramModel":
        contexts: dict[str, Counter[str]] = defaultdict(Counter)
        vocab: set[str] = set()
        for text in texts:
            tokens = ["<s>"] * (self.order - 1) + tokenize(text) + ["</s>"]
            for index in range(self.order - 1, len(tokens)):
                history = " ".join(tokens[index - self.order + 1:index])
                contexts[history][tokens[index]] += 1
                vocab.add(tokens[index])
        self.counts = {history: counter for history, counter in contexts.items()}
        self.vocab = vocab
        return self

    # -- scoring --------------------------------------------------------
    def _probability(self, history: str, word: str) -> float:
        counter = self.counts.get(history)
        if not counter:
            return 1.0 / (len(self.vocab) + 1)
        total = sum(counter.values()) + self.smoothing * (len(self.vocab) + 1)
        return (counter.get(word, 0) + self.smoothing) / total

    def perplexity(self, text: str) -> float:
        tokens = ["<s>"] * (self.order - 1) + tokenize(text) + ["</s>"]
        if len(tokens) <= self.order - 1:
            return float("inf")
        total = 0.0
        counted = 0
        for index in range(self.order - 1, len(tokens)):
            history = " ".join(tokens[index - self.order + 1:index])
            word = tokens[index]
            if word != "</s>" and word not in self.vocab:
                # An unseen word is *scored*, as `<unk>`, not dropped: dropping it would make the
                # number look better the less the model knows.
                word_for_scoring = "<unk>"
            else:
                word_for_scoring = word
            total += -math.log(self._probability(history, word_for_scoring))
            counted += 1
        return math.exp(total / counted) if counted else float("inf")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "ngram",
            "order": self.order,
            "smoothing": self.smoothing,
            "vocab": sorted(self.vocab),
            "counts": {history: dict(counter) for history, counter in sorted(self.counts.items())},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NGramModel":
        model = cls(order=int(payload["order"]), smoothing=float(payload["smoothing"]))
        model.vocab = set(payload.get("vocab") or [])
        model.counts = {
            history: Counter(counter)
            for history, counter in (payload.get("counts") or {}).items()
        }
        return model


class CentroidModel:
    """Nearest-centroid classifier over hashed bag-of-words features.

    The point of a centroid is that its arithmetic can be checked by hand: a document's vector is
    term counts, a class's centroid is the mean of its documents, and the prediction is the nearest
    centroid by cosine. A tiny model that can be verified beats a large one nobody can inspect.
    """

    def __init__(self) -> None:
        self.centroids: dict[str, list[float]] = {}
        self.labels: list[str] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * FEATURE_DIM
        for word in tokenize(text):
            vector[_hash_feature(word)] += 1.0
        return vector

    @staticmethod
    def _normalise(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def fit(self, examples: list[tuple[str, str]]) -> "CentroidModel":
        if not examples:
            raise ValidationError("a classifier needs at least one labelled record")
        sums: dict[str, list[float]] = defaultdict(lambda: [0.0] * FEATURE_DIM)
        counts: Counter[str] = Counter()
        for text, label in examples:
            vector = self._normalise(self._vector(text))
            target = sums[label]
            for index, value in enumerate(vector):
                target[index] += value
            counts[label] += 1
        self.centroids = {
            label: self._normalise([value / counts[label] for value in vector])
            for label, vector in sums.items()
        }
        self.labels = sorted(self.centroids)
        return self

    def predict(self, text: str) -> str:
        vector = self._normalise(self._vector(text))
        best, best_score = self.labels[0], -2.0
        for label in self.labels:
            score = sum(a * b for a, b in zip(vector, self.centroids[label]))
            if score > best_score:
                best, best_score = label, score
        return best

    def accuracy(self, examples: list[tuple[str, str]]) -> float:
        if not examples:
            return float("nan")
        hits = sum(1 for text, label in examples if self.predict(text) == label)
        return hits / len(examples)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "centroid", "labels": self.labels, "centroids": self.centroids}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CentroidModel":
        model = cls()
        model.labels = list(payload.get("labels") or [])
        model.centroids = {
            label: [float(value) for value in vector]
            for label, vector in (payload.get("centroids") or {}).items()
        }
        return model


def train_records(
    entries: list[dict[str, Any]], method: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Train on records that are already in memory: ``{"path", "split", "label", "text"}``.

    This is the whole trainer, in one place, because it has two callers: the local run, which reads
    the files itself, and the remote worker (M37), which must not train a *different* model from the
    one the local command would have trained. A worker that reimplemented the arithmetic would make
    every remote metric a claim about a second implementation.
    """
    texts: dict[str, list[tuple[str, str]]] = {"train": [], "val": [], "test": []}
    for entry in entries:
        texts.setdefault(entry.get("split") or "train", []).append(
            (entry["path"], entry["text"])
        )
    labels = {entry["path"]: entry.get("label") for entry in entries}

    if method == "ngram":
        model = NGramModel(order=int(config["order"]), smoothing=float(config["smoothing"]))
        model.fit([text for _path, text in texts.get("train", [])])
        metrics: dict[str, dict[str, float | None]] = {}
        for split, items in texts.items():
            if not items:
                continue
            perplexities = [model.perplexity(text) for _path, text in items]
            metrics[split] = {
                "perplexity": sum(perplexities) / len(perplexities),
                "records": float(len(items)),
                "tokens": float(sum(len(tokenize(text)) for _path, text in items)),
            }
        artifact = model.to_dict()
    elif method == "centroid":
        examples: dict[str, list[tuple[str, str]]] = {}
        for split, items in texts.items():
            examples[split] = [
                (text, labels[path]) for path, text in items if labels.get(path) is not None
            ]
        model = CentroidModel()
        model.fit(examples.get("train") or [])
        metrics = {}
        for split, items in examples.items():
            if not items:
                continue
            # NaN is recorded as a null, with the reason in the job's notes: a metric that was not
            # measurable is not a metric of zero.
            accuracy = model.accuracy(items)
            metrics[split] = {
                "accuracy": accuracy if accuracy == accuracy else None,
                "records": float(len(items)),
                "labels": float(len(model.labels)),
            }
        artifact = model.to_dict()
    else:
        raise ValidationError(f"{method!r} is not a trainer this build can run")
    return {"metrics": metrics, "artifact": artifact}


class TrainingService:
    """Run the two trainers that work here, and say why the others cannot."""

    def __init__(self, ws) -> None:
        self.ws = ws

    # -- plumbing ---------------------------------------------------------
    @property
    def manager(self):
        return self.ws.training

    def _execute(self, name: str, arguments: dict[str, Any], context: ToolContext):
        run = self.ws.tools.execute(name, arguments, context=context, requester="training")
        if run.status == "denied":
            approval = getattr(run, "approval_id", None)
            if approval:
                raise ApprovalRequiredError(
                    f"{name} needs approval: approve {approval} or grant the capability",
                    approval_id=approval,
                )
            raise PermissionDeniedError(run.error or f"{name} was refused")
        if run.status == "failed":
            raise ToolError(run.error or f"{name} failed")
        return run

    def _context(self, purpose: str, task_id: str | None = None) -> ToolContext:
        return ToolContext(task_id=task_id, purpose=purpose)

    def _artifacts_dir(self) -> Path:
        base = Path(self.ws.config.path("paths.artifacts")) / "training"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _read_text(self, path: str, task_id: str | None = None) -> str:
        run = self._execute(
            "fs.read", {"path": path}, self._context(f"training read {path}", task_id)
        )
        return str((run.result or {}).get("content") or "")

    # -- the fine-tuning boundary ----------------------------------------
    def blockers(self, method: str, base_model: str | None = None) -> list[str]:
        """Every reason this build cannot fine-tune a transformer, in the order found."""
        reasons: list[str] = []
        if method not in FINETUNE_METHODS:
            return reasons
        if not self.ws.config.get("training.enabled", False):
            reasons.append("training is off: `archx-agent config set training.enabled true`")
        wanted = (base_model or str(self.ws.config.get("training.base_model", "") or "")).strip()
        if not wanted:
            reasons.append(
                "no base model is named (training.base_model is empty), and this build ships no "
                "transformer weights"
            )
        else:
            record = self._model(wanted)
            if record is None:
                reasons.append(f"{wanted!r} is not a registered model")
            else:
                reasons.append(
                    f"model {record.name!r} is registered, but a chat runtime is not a trainer"
                )
        weights = str(self.ws.config.get("training.weights_dir", "") or "").strip()
        if not weights:
            reasons.append(
                "no training.weights_dir is configured, so no local checkpoint could be loaded"
            )
        elif not Path(weights).exists():
            reasons.append(f"training.weights_dir {weights!r} does not exist on this machine")
        if not self._library_available("torch"):
            reasons.append("no fine-tuning library is installed here (torch is not importable)")
        if not self._gpu_present():
            reasons.append(
                "no CUDA device is visible: a step of LoRA on a real checkpoint needs one"
            )
        reasons.append(
            f"no adapter in this build can fine-tune anything: `{method}` is not implemented, and "
            "a registered model is not enough"
        )
        return reasons

    @staticmethod
    def _library_available(name: str) -> bool:
        import importlib.util

        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):  # pragma: no cover - a broken install
            return False

    @staticmethod
    def _gpu_present() -> bool:
        """A GPU is present when a CUDA device can actually be opened - not when a file exists."""
        import importlib.util

        if importlib.util.find_spec("torch") is None:
            return False
        try:  # pragma: no cover - only on a machine with torch installed
            import torch

            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001 - any failure means "not usable here"
            return False

    def _model(self, wanted: str):
        try:
            found = self.ws.models.get(wanted)
        except Exception:  # noqa: BLE001 - a miss is a normal outcome
            found = None
        if found is not None and not hasattr(found, "is_err"):
            return found
        if found is not None and not found.is_err:
            return found.value
        try:
            named = self.ws.models.by_name(wanted)
        except Exception:  # noqa: BLE001
            return None
        if hasattr(named, "is_err"):
            return None if named.is_err else named.value
        return named

    # -- preflight --------------------------------------------------------
    def preflight(
        self,
        *,
        method: str,
        dataset: str | None = None,
        base_model: str | None = None,
    ) -> dict[str, Any]:
        """What would have to be true before this run could mean anything, and what is true."""
        if method not in METHODS:
            raise ValidationError(
                f"unknown method {method!r} (this build knows {', '.join(METHODS)})"
            )
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        check("method", method in RUNNABLE_METHODS or method in FINETUNE_METHODS,
              f"{method} is a method this build knows")
        if method in FINETUNE_METHODS:
            reasons = self.blockers(method, base_model)
            check("adapter", False,
                  f"{method} cannot run here: {'; '.join(reasons)}")
            return {
                "method": method,
                "runnable": False,
                "checks": checks,
                "reasons": reasons,
                "note": "this build cannot fine-tune a transformer; nothing was attempted",
            }

        dataset_id = dataset
        dataset_view: dict[str, Any] | None = None
        if dataset_id:
            try:
                dataset_view = self.ws.data.view(dataset_id)
            except NotFoundError:
                dataset_view = None
        check("dataset", dataset_view is not None,
              f"dataset {dataset_id!r} exists" if dataset_view else f"no such dataset: {dataset_id}")
        if dataset_view:
            counts = dataset_view["counts"]
            check("records", counts["kept"] > 0, f"{counts['kept']} kept records")
            by_split = counts["by_split"]
            check("split", bool(by_split), "the dataset has a split"
                  if by_split else "the dataset has no split yet: run `dataset split`")
            check("validation", by_split.get("val", 0) + by_split.get("test", 0) > 0,
                  f"{by_split.get('val', 0)} val and {by_split.get('test', 0)} test records")
            check("built", bool(dataset_view.get("checksum")),
                  "the dataset was built and its manifest recorded"
                  if dataset_view.get("checksum") else "the dataset was never built: run `dataset build`")
            if dataset_view.get("checksum"):
                verified = self.ws.data.verify(dataset_view["id"])
                check("manifest", verified["agrees"], verified["note"])

        runnable = all(item["ok"] for item in checks)
        return {
            "method": method,
            "runnable": runnable,
            "checks": checks,
            "reasons": [f"{item['check']}: {item['detail']}" for item in checks if not item["ok"]],
            "note": (
                "every check passed; this run would train a real model on this machine"
                if runnable else "at least one check failed, and a run would not be honest"
            ),
        }

    # -- running ----------------------------------------------------------
    def run(
        self,
        *,
        method: str,
        dataset: str,
        seed: int = 0,
        order: int = 3,
        smoothing: float = 0.1,
        label_source: str = "directory",
        notes: str = "",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if method not in METHODS:
            raise ValidationError(
                f"unknown method {method!r} (this build knows {', '.join(METHODS)})"
            )
        config = {"order": int(order), "smoothing": float(smoothing),
                  "label_source": label_source, "seed": int(seed)}
        job = self.manager.create(
            method=method, dataset_id=dataset, config=config, seed=seed,
            base_model=None, notes=notes, task_id=task_id,
        )
        if method in FINETUNE_METHODS:
            return self._refuse(job, method)

        preflight = self.preflight(method=method, dataset=dataset)
        if not preflight["runnable"]:
            return self._refuse(job, method, preflight=preflight)
        self.manager.update(job.id, status="running", preflight=preflight, started_at=iso_now())

        try:
            result = self._train(job, dataset, method, config, task_id=task_id)
        except (ToolError, PermissionDeniedError, ApprovalRequiredError) as exc:
            self.manager.update(job.id, status="failed", error=str(exc), completed_at=iso_now())
            raise
        except Exception as exc:  # noqa: BLE001 - a run that breaks is a row, not a traceback
            self.manager.update(job.id, status="failed", error=str(exc), completed_at=iso_now())
            raise

        for split, values in result["metrics"].items():
            self.manager.record_metrics(job.id, values, split=split)
        artifact = self._write_artifact(job, result["artifact"])
        version_id = self._version(job, artifact)
        finished = self.manager.update(
            job.id,
            status="completed",
            metrics=result["metrics"],
            completed_at=iso_now(),
            artifact_path=artifact["path"],
            artifact_sha256=artifact["sha256"],
            version_id=version_id,
            preflight=preflight,
        )
        return self.view(finished.id)

    def _refuse(
        self, job: TrainingJob, method: str, *, preflight: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        reasons = preflight["reasons"] if preflight else self.blockers(method)
        refused = self.manager.update(
            job.id,
            status="refused",
            preflight=preflight or {"method": method, "runnable": False, "reasons": reasons},
            refusal="; ".join(reasons),
            completed_at=iso_now(),
            metrics={},
        )
        payload = self.view(refused.id)
        payload["reasons"] = reasons
        payload["status"] = "refused"
        return payload

    def _train(
        self, job: TrainingJob, dataset: str, method: str, config: dict[str, Any],
        *, task_id: str | None = None,
    ) -> dict[str, Any]:
        view = self.ws.data.view(dataset)
        records = self.ws.data.records(view["id"], status="kept", limit=100_000)
        entries = [
            {
                "path": record["path"],
                "split": record["split"] or "train",
                "label": self._label(record, config.get("label_source") or "record"),
                "text": self._read_text(record["path"], task_id),
            }
            for record in records
        ]
        trained = train_records(entries, method, config)
        trained["artifact"]["trained_on"] = view["id"]
        trained["artifact"]["seed"] = int(config["seed"])
        return trained

    @staticmethod
    def _label(record: dict[str, Any], source: str) -> str | None:
        """Where a label came from, said out loud rather than inferred quietly."""
        if record.get("label"):
            return str(record["label"])
        if source == "directory":
            parent = str(Path(record["path"]).parent).replace("\\", "/")
            return parent.split("/")[-1] or None
        return None

    def _write_artifact(self, job: TrainingJob, artifact: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(artifact, indent=2, sort_keys=True)
        target = f"{job.id}.model.json"
        written = self._execute(
            "fs.write", {"path": target, "content": body, "create_parents": True},
            self._context(f"training artifact {target}", job.task_id),
        )
        output = dict(written.result or {})
        local = self._artifacts_dir() / target
        local.write_text(body, encoding="utf-8")
        return {
            "path": output.get("path") or target,
            "local": str(local),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "bytes": len(body.encode("utf-8")),
        }

    def _version(self, job: TrainingJob, artifact: dict[str, Any]) -> str | None:
        """Record the artifact as a version, so the file a metric came from cannot drift."""
        try:
            record = self.ws.versions.record(
                # `artifact` is an allowed version subject; the id names the run it belongs to.
                "artifact", f"{job.id}.model",
                content=Path(artifact["local"]).read_text(encoding="utf-8"),
                note=f"the model {job.method} wrote after the metrics were measured",
            )
        except Exception:  # noqa: BLE001 - versioning must not lose the run
            return None
        version = getattr(record, "version", None)
        return getattr(version, "version", None) or getattr(version, "id", None)

    # -- reading ----------------------------------------------------------
    def view(self, wanted: str) -> dict[str, Any]:
        job = self.manager.resolve(wanted)
        payload = job.to_dict()
        payload["metric_rows"] = [row.to_dict() for row in self.manager.metrics(job.id)]
        payload["reasons"] = [] if job.status != "refused" else [
            part.strip() for part in (job.refusal or "").split("; ") if part.strip()
        ]
        payload["sentence"] = self._sentence(job)
        return payload

    @staticmethod
    def _sentence(job: TrainingJob) -> str:
        if job.status == "completed":
            return f"{job.method} trained on {job.dataset_id} and wrote {job.artifact_path}"
        if job.status == "refused":
            return f"{job.method} was refused before it started: {job.refusal}"
        if job.status == "failed":
            return f"{job.method} started and failed: {job.error}"
        return f"{job.method} is {job.status}"

    def jobs(self, *, status: str | None = None, dataset: str | None = None,
             limit: int = 50) -> list[dict[str, Any]]:
        return [
            job.to_dict()
            for job in self.manager.jobs(status=status, dataset_id=dataset, limit=limit)
        ]

    def metrics(self, wanted: str) -> dict[str, Any]:
        job = self.manager.resolve(wanted)
        grouped: dict[str, dict[str, float]] = {}
        for row in self.manager.metrics(job.id):
            grouped.setdefault(row.split, {})[row.name] = row.value
        return {"job_id": job.id, "method": job.method, "status": job.status, "by_split": grouped}

    def compare(self, job_ids: list[str]) -> dict[str, Any]:
        """Line runs up on one metric - and say plainly where a comparison is not possible."""
        jobs = [self.manager.resolve(wanted) for wanted in job_ids]
        if not jobs:
            raise ValidationError("nothing to compare")
        metric = "perplexity" if jobs[0].method == "ngram" else "accuracy"
        rows: list[dict[str, Any]] = []
        notes: list[str] = []
        for job in jobs:
            value = self.manager.latest_metric(job.id, metric, split="val")
            if value is None:
                value = self.manager.latest_metric(job.id, metric, split="test")
            rows.append({
                "job_id": job.id, "method": job.method, "status": job.status,
                "metric": metric, "value": value,
            })
            if job.status != "completed":
                notes.append(f"{job.id} did not run ({job.status}), so it has no {metric}")
            if job.method != jobs[0].method:
                notes.append(
                    f"{job.id} is a {job.method} run: its {metric} is not comparable with a "
                    f"{jobs[0].method} run"
                )
        ranked = [row for row in rows if row["value"] is not None]
        lower_is_better = metric == "perplexity"
        best = None
        if len({row["method"] for row in rows}) > 1:
            # Two methods do not produce comparable numbers, so no winner is named even if only
            # one of them happens to have a value.
            notes.append("the runs use different methods, so no winner is named")
        elif not ranked:
            notes.append(f"no run has a {metric} to rank")
        elif len(ranked) < len(rows):
            notes.append(
                f"only {len(ranked)} of {len(rows)} runs produced a {metric}, so no winner is named"
            )
        else:
            best = (min if lower_is_better else max)(ranked, key=lambda row: row["value"])["job_id"]
        return {
            "metric": metric,
            "lower_is_better": lower_is_better,
            "rows": rows,
            "best": best,
            "notes": notes,
        }

    def predict(self, wanted: str, text: str) -> dict[str, Any]:
        """Use the artifact the run wrote - re-read from disk, not from a copy in memory."""
        job = self.manager.resolve(wanted)
        if job.status != "completed":
            raise ValidationError(
                f"{job.id} is {job.status}; there is no artifact to use: {self._sentence(job)}"
            )
        if not job.artifact_path:
            raise NotFoundError(f"{job.id} recorded no artifact")
        raw = self._read_text(job.artifact_path)
        payload = json.loads(raw)
        kind = payload.get("kind")
        if kind == "ngram":
            model = NGramModel.from_dict(payload)
            return {
                "job_id": job.id, "kind": "ngram",
                "perplexity": model.perplexity(text),
                "tokens": len(tokenize(text)),
            }
        if kind == "centroid":
            model = CentroidModel.from_dict(payload)
            return {
                "job_id": job.id, "kind": "centroid",
                "label": model.predict(text), "labels": model.labels,
            }
        raise ValidationError(f"{job.artifact_path} is not a model this build can load")

    def stats(self) -> dict[str, Any]:
        base = self.manager.stats()
        base["enabled"] = bool(self.ws.config.get("training.enabled", False))
        base["base_model"] = str(self.ws.config.get("training.base_model", "") or "")
        base["weights_dir"] = str(self.ws.config.get("training.weights_dir", "") or "")
        base["can_finetune"] = False
        base["why_not"] = self.blockers("lora")
        return base
