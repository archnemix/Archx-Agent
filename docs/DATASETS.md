# Datasets

A dataset is the first thing this repository produces whose *contents* are the product rather than
a description of one, and that changes what "done" has to mean. Four claims decide whether a
prepared corpus is worth anything, and each of them can be lost in a pipeline that looks tidy:

1. **every candidate is accounted for** - a file removed by a rule keeps the rule and the reason,
   and you can ask "why is this not in my dataset" of the record rather than of a log;
2. **the split is a function of the record**, not of its position, so adding a file tomorrow does
   not move yesterday's `train` rows and a published split is reproducible;
3. **a document cannot sit in two splits** - including the copies that differ only in whitespace or
   case, which is the leak an exact hash cannot see;
4. **the manifest is a claim that can fail** - `dataset verify` re-reads the files and disagrees out
   loud, printing both hashes and naming the record that changed.

```bash
archx-agent dataset create corpus --source corpus --license CC-BY-4.0
archx-agent dataset scan   corpus           # measure every candidate (needs fs.read)
archx-agent dataset clean  corpus --min-chars 10 --normalize
archx-agent dataset split  corpus --seed m35
archx-agent dataset build  corpus           # JSONL export + manifest hash (needs fs.write)
archx-agent dataset verify corpus           # recompute from disk; exit 3 if it moved
archx-agent dataset records corpus --status dropped
archx-agent dataset explain dr_…
archx-agent dataset steps  corpus
```

The same pipeline is on the **Data** page of the GUI, which calls the same service.

## 1. Where the files come from

Sources are paths **inside the tool roots**. Walking a directory is done here one `fs.list` per
directory rather than by one recursive tool call, because each level is then a separate permission
check and an operator can see every directory that was read. There is a depth bound: a tree deeper
than four levels is refused rather than descended without a limit, and a directory listing that
comes back truncated is a refusal for the same reason - a silently truncated scan is a dataset with
holes in it.

Every file is measured with `fs.probe` (size, sha256, container head) and then read with `fs.read`
if its suffix says text. A file with a text suffix that `fs.read` refuses is **binary in fact,
whatever it is named** - the same lesson as M34's mislabelled media, applied to a corpus - and it is
recorded as a dropped candidate with the refusal in the reason. A `.png` is measured, shelved and
marked `not a text file this build can parse`: this build prepares text corpora, and saying so beats
dropping the file where nobody can see it.

## 2. Cleaning keeps its reasons

| rule | what it removes | the reason it writes |
|------|-----------------|----------------------|
| `drop_binary` | anything `fs.read` refused | `not a text file this build can parse` |
| `drop_empty` | whitespace-only or empty text | `the file is empty` |
| `min_chars` | shorter than the threshold | `fewer characters than the min_chars rule allows (5 < 10)` |
| `dedupe` | a repeated hash | `the same content is already in the dataset from an earlier path: corpus/a.txt` |
| `--normalize` | a repeated *normalised* hash | the same, naming the survivor |
| `--require-license` | nothing - it **refuses** | `the dataset's license is unknown, so nothing may be published from it` |

The first four mark records `dropped`; they are not deleted. `dataset records --status dropped`
is the audit, and `dataset explain dr_…` prints one sentence and the ledger that produced it.

Cleaning is idempotent: the same rules over the same corpus produce the same set, and the ledger
records what was asked for beside what happened (`config` and `report` on the step).

## 3. Splits that do not move

```
bucket = hash(seed + ":" + record.sha256) → a point in [0,1] → the ratio bands
```

That is the whole rule. Two consequences are worth stating because both are easy to lose:

* **byte-identical files cannot land in different splits** - the bucket is a function of the bytes,
  so the exact-duplicate leak is impossible by construction rather than by a check that could be
  forgotten;
* **adding a file does not move the existing ones**, so a model trained on yesterday's `train`
  split and evaluated on today's `test` split is still comparing the same two sets.

The seed is stored, so the assignment is reproducible from the record and the seed alone.

### The leak the hash cannot see

Two copies of one document, saved with different whitespace or case, have different bytes, different
hashes and therefore different buckets. That is a real leak, and `dataset split` refuses it:

```
error: the same text (ignoring whitespace and case) appears in two splits:
ddc27e00e31f in train and val (corpus/a.txt, corpus/resaved.txt). One document must not be in two
splits; run `dataset clean --dedupe --normalize` first, because a leak flatters every score that
comes out of this dataset
```

The normalised hash (`whitespace collapsed, case folded`) is computed at scan time and stored on the
record, so the check is a query rather than a re-read of every file.

## 4. The manifest is the dataset's claim about itself

`build` writes one JSON line per kept record through `fs.write` - the rooted file-tool checks apply to exports
like everything else - and records:

* `checksum`: sha256 over the **sorted** manifest lines `split \t sha256 \t bytes \t path`;
* the export's own sha256 and size in the row's metadata;
* a copy in `<paths.artifacts>/datasets/<id>.jsonl`.

`verify` recomputes the manifest from the files on disk and compares:

```
$ archx-agent dataset verify corpus
verify ds_…  3 records checked
  stored     72b0a2476008…
  recomputed 4d0d…            <- a file changed since the build
  the dataset no longer matches its manifest: 1 records differ
  changed   corpus/c.md
            recorded 9f21…  found 51b7…
```

The CLI exits **3** (degraded), not 1: nothing broke, the corpus moved. A missing file is a
`missing` difference, and a dataset that was never built cannot claim agreement - it says "no
manifest was recorded" rather than comparing a hash to nothing.

## 5. The rows

| table | one row per | notes |
|-------|-------------|-------|
| `datasets` | a corpus | adopts v8's reserved columns (`source`, `license`, `checksum`, `record_count`, …) and adds `status`, `seed`, `splits`, `dropped_count` |
| `dataset_records` | a **candidate**, kept or dropped | status, reason, split, chars, lines, the normalised hash in `metadata` |
| `dataset_transforms` | a step | `scan`, `clean`, `split`, `build` - records in, records out, config, report |

Schema **v25**. `datasets` and `dataset_transforms` were reserved by v8, so v25 **adopts** them with
`ALTER TABLE` rather than redefining them under any home that already has rows (D160).

Lifecycle: `draft → scanned → cleaned → split → built`. The states are a list in the code and in
`dataset stats`, so the CLI, the page and the docs cannot disagree about the order.

## 6. Tests and acceptance

* `tests/features/test_datasets_m35.py`: 60 tests. The corpus is written by the fixtures (two identical
  files, one resaved, one empty, one binary, one tiny), so the hashes are known; the leak check is
  exercised across nine seeds; `verify` is broken by editing and by deleting a file; the GUI is
  driven through `GuiApi.dispatch` over a real socket.
* `scripts/acceptance_m35.sh`: 72 checks over the CLI and a real HTTP server, including a grant
  refusal, a resaved document refused across splits, a build whose manifest is then broken twice.
* `scripts/gui_smoke.mjs`: 15 tabs; the Data panel renders a kept record and a dropped one with the
  rule that dropped it.

## 7. What this does not do

* **No training and no upload.** M35 prepares a corpus on this machine. There is no `dataset train`,
  no upload, no publishing, and the license field exists so that the person who knows can say.
* **Text only.** No tokenisation, no chat-format templating, no image or audio records beyond
  counting them as shelved candidates. A tokeniser that changes the text is a transform that would
  need its own ledger.
* **No cross-dataset dedupe.** Two datasets may share a document; there is no global corpus index.
* **No derived-file tracking.** If a transform rewrote a file, the manifest would record the source
  bytes, not the rewrite; there are no rewriting transforms in this build.
