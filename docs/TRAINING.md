# Training and model modification

This machine has no GPU, no transformer weights and no fine-tuning library. The usual way to write
this milestone is a `train` command that shells out to something absent and prints a plausible loss
curve; that would pass a demo and be a lie, which is the one thing the last twelve milestones have
refused to do. So the milestone is split along the line between what is true here and what is not.

**Two trainers really run**, on a CPU, in the time a command should take, with numbers that can be
checked by hand:

| method | what it is | metric |
|--------|------------|--------|
| `ngram` | a word-level n-gram language model with add-k smoothing | perplexity per split |
| `centroid` | a nearest-centroid text classifier over hashed bag-of-words | accuracy per split |

**Fine-tuning is refused by name.** `lora`, `qlora` and `full` walk a chain - the switch, the base
model, the weights directory, the library, the GPU, the adapter - and every missing link is reported
in order and stored on the job.

```bash
archx-agent train preflight --dataset corpus          # what would have to be true
archx-agent train run --method ngram --dataset corpus --order 2 --seed 7
archx-agent train run --method centroid --dataset corpus
archx-agent train show tj_…
archx-agent train metrics tj_…
archx-agent train compare tj_a tj_b
archx-agent train predict tj_… "def f(x): return x + 1"
archx-agent train run --method lora --dataset corpus  # refused, with six reasons
archx-agent train stats
```

The same operations are on the **Train** page of the GUI, which calls the same service.

## 1. Nothing runs until the dataset can support it

`train preflight` is a list of checks, each a row with `ok` and a sentence:

| check | asks |
|-------|------|
| `method` | is this a method the build knows? |
| `dataset` | does that dataset exist? |
| `records` | did anything survive cleaning? |
| `split` | has the dataset been split? |
| `validation` | is there at least one val or test record? |
| `built` | was the manifest written? |
| `manifest` | does it still agree with the files on disk? |

A run with a failed check is **refused**, not attempted, and the refusal says which check failed.
The last row is the interesting one: a dataset whose files drifted after the build is not a dataset
you can train on and report a number for, and M35's `verify` already knows how to say so.

## 2. The n-gram model, and why its perplexity is checkable

The model counts transitions, smooths with add-k, and scores text as
`exp(-mean log p)` with `<s>`/`</s>` boundaries. Two decisions make the number meaningful:

* **an unseen word is scored, as `<unk>`, not skipped.** Skipping is how a language model reports a
  number no text could produce - better-looking the less it knows.
* **the counts and smoothing are in the artifact**, so anyone can recompute the perplexity from the
  file the run wrote. `scripts/acceptance_m36.sh` does exactly that with an independent
  implementation and fails if the two disagree by more than 1e-9.

On a three-file training split the model reports `2.58` on train and `6.59` on validation, which is
the shape a small model should have: memorised transitions are cheap, unseen ones are not.

## 3. The centroid classifier, and where its labels come from

A document becomes term counts over 512 hashed features, a class becomes the mean of its documents,
and a prediction is the nearest centroid by cosine. The arithmetic fits on a page, which is the
point: a model whose behaviour can be checked beats one nobody can inspect.

Labels come from the record's own `label` if it has one, otherwise from **its parent directory** -
and the rule is written into the run's `config.label_source` rather than left to be guessed. A
corpus of `python/` and `rust/` files therefore classifies as those two, and the acceptance script
checks a rust-shaped document comes back `rust`.

Accuracy is a fraction, and a set with nothing in it is **NaN** - recorded as null, because a metric
that could not be measured is not a metric of zero. Splits with no records are absent from the
metrics rather than present as `0`.

## 4. Fine-tuning: the chain

```
$ archx-agent train run --method lora --dataset corpus; echo "exit $?"
refused tj_…  lora on ds_…
  - training is off: `archx-agent config set training.enabled true`
  - no base model is named (training.base_model is empty), and this build ships no transformer weights
  - no training.weights_dir is configured, so no local checkpoint could be loaded
  - no fine-tuning library is installed here (torch is not importable)
  - no CUDA device is visible: a step of LoRA on a real checkpoint needs one
  - no adapter in this build can fine-tune anything: `lora` is not implemented, and a registered
    model is not enough
exit 3
```

The chain is computed from the machine, not printed from a constant: `train stats` shows the same
list, turning `training.enabled` on removes exactly that reason, naming a `base_model` that is not
registered says so, and a `weights_dir` that does not exist is named as such. The last line never
goes away, and that is the honest part - a chat runtime is not a trainer.

Exit **3** (degraded): nothing broke and nothing was trained.

## 5. What a run leaves behind

| table | one row per | notes |
|-------|-------------|-------|
| `training_jobs` | a run | adopts v8's reserved columns and adds `kind`, `seed`, `artifact_path`, `artifact_sha256`, `refusal`, `version_id` |
| `training_metrics` | a measured number | `(job_id, split, name, value)`, so a comparison is a query and a missing number is a missing row |

The artifact is a JSON file written through `fs.write` (so rooted file-tool checks apply; this is not OS process isolation), copied into
`<paths.artifacts>/training/`, hashed into the row, and **registered as a version** - the model a
metric came from cannot be silently replaced by a later one with the same name.

`train predict` re-reads the artifact from disk before using it: a prediction is made by the file
the run recorded, not by an object left in memory.

## 6. Comparing runs

```
$ archx-agent train compare tj_a tj_b
metric perplexity (lower is better)
run                     method    status     perplexity
----------------------  --------  ---------  ------------
tj_a                    ngram     completed  6.5897      best
tj_b                    ngram     completed  6.9001
```

`best` is named only when **every** run in the comparison used the same method and **all** of them
produced the metric. Mixed methods get `no winner is named`, a refused run gets `did not run`, and
one method with a missing number gets neither a winner nor a silent gap.

## 7. Tests and acceptance

* `tests/features/test_training_m36.py`: 54 tests. The n-gram distribution is checked against arithmetic by
  hand (four outcomes summing to 1), the unknown-word rule is checked by comparing two perplexities,
  the centroid is checked on a distribution the test constructs, the fine-tune chain is shortened
  one link at a time, and the GUI is driven through `GuiApi.dispatch` over a real socket.
* `scripts/acceptance_m36.sh`: 57 checks, including an **independent** perplexity implementation
  that must agree with the run's number to 1e-9.
* `scripts/gui_smoke.mjs`: 18 tabs; the Train panel shows the metrics and the refusal card.

## 8. What this does not do

* **No transformer training, no LoRA, no adapters, no checkpoints from a hub.** Nothing is
  downloaded, and no claim is made about what such a run would cost or produce.
* **No evaluation harness beyond the two trainers' own metrics.** Perplexity and accuracy are
  defined by the code above and nothing else; there is no benchmark suite.
* **No GPU arithmetic.** No memory estimate, no throughput figure, no `torch` path - because none
  of it could be measured here.
* **No serving.** An artifact can be scored with `train predict`; there is no server, no chat model
  swap, no deployment.
