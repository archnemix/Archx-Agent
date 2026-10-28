# Experimental Mode

An experiment here is a **declaration**: a command, the parameters it takes, and where the numbers
come from. Running it produces a **run**: the parameters it actually used, the command that
resolved, the exit code, the duration, and the numbers — or a sentence explaining why there are no
numbers. Comparing runs ranks what it can and names what it cannot.

That is a small surface with one big decision in it: *the tool never invents a metric*. Everything
below is a consequence of that.

---

## 1. The rule, and why it is the whole design

The most common way a results table lies is by treating "no answer" as "0.0". A run crashes, the
JSON never appears, and the average quietly improves. So:

* an experiment declares a metrics source of `none`, `stdout-json` (the last non-empty line of
  stdout) or `file` (a JSON file the run writes, inside the experiment's directory);
* the runner reads **only** that source, through `fs.read` for a file — the same capability as
  everything else;
* if the source is missing, malformed, or not numeric, the run is stored with `metrics_error`
  and **no** metric rows;
* `compare` lists those runs by id with the reason, instead of dropping them silently.

The same care shows up in the parameter handling. A substituted value must be **one shell-safe
token** (`A-Za-z0-9_.:/=+@-`, up to 200 characters). A value that is not is refused *before*
anything runs, rather than quoted: quoting something the user did not quote changes the command
they meant.

```bash
archx-agent experiment run ex_… --set 'n=5; rm -rf /'
# error: parameter 'n' is '5; rm -rf /'; a substituted value has to be a single shell-safe token
#        (letters, digits and _ . : / = + @ -)                        [exit 2, nothing started]
```

---

## 2. Declaring

```bash
archx-agent experiment create sizes \
  --command 'python bench.py {n} seed={seed}' \
  --param n=100 --param seed=0 \
  --metric-source stdout-json \
  --hypothesis "sorting time grows with n"
```

* Every `{placeholder}` in the command must have a declared parameter, and every declared
  parameter must appear in the command. Both directions are checked, by name, because a typo in
  either one is otherwise a silent no-op.
* `--param NAME=DEFAULT` declares a parameter; without `=DEFAULT` it must be passed at run time.
* `--metric-source file --metric-file metrics.json` reads that file from the experiment's
  directory. A path that escapes the directory is refused as a declaration error.
* `--root` must be inside the tool roots. That is the same boundary `shell.run` enforces, not a
  second implementation of it.
* `--hypothesis` is stored with the experiment, so a later reader knows what was being asked.

The declarations live in `experiment_specs`. (The v13 schema already had an `experiments` table —
a manual log with `baseline`/`target`/`criteria` that nothing reads. This mode does not redefine
it: a table someone might have rows in is not a table to repurpose in a migration.)

---

## 3. Running

```bash
archx-agent experiment run ex_… --set n=1000 --timeout 120 --seed "warm cache"
```

Each run:

* resolves the parameters (declared defaults, then overrides), substitutes them into the command,
  and prints the command it is about to run;
* runs it through `shell.run` under the permission centre — no grant means **exit 4** with the
  approval id, and the refusal is still recorded as a run with `status: refused`;
* creates a **task** of type `experiment` (`manual=True`, so it is not swept away when the CLI
  process exits), logs the command, each metric and any `metrics_error` on its timeline, and
  completes or fails that task;
* keeps stdout/stderr as an artifact (`experiment-log`) attached to the task.

Statuses are `passed`, `failed`, `timeout`, `refused`, `error`. A failing command is a *run*, not
an absence: `failed` with its exit code, and the task fails with an `unresolved` item naming it.

Exit codes follow the run: `0` passed, `1` failed, `3` timeout, `4` refused, `2` for a usage or
validation error (bad parameter, unsafe value, unknown metric), `5` if the tool layer is
unavailable.

---

## 4. Comparing

```bash
archx-agent experiment compare ex_… --metric quality
archx-agent experiment compare ex_… --metric loss --minimise
```

```
sizes: quality (highest wins, 4 run(s))
  best  xr_…  quality=4  n=40
  xr_…  failed  exit 3
  note: xr_… is not ranked: the last line of stdout is not valid JSON: Expecting value: line 1 …
  note: 1 of 4 run(s) have a value for quality
  note: 1 run(s) did not pass; their metrics are shown but a failed run is not a result
```

`compare` also warns when the runs do not all carry the same parameter names, because that is the
case where a table looks comparable and is not.

Metrics are stored as **rows** (`experiment_metrics`), so the ranking is a query:

```sql
SELECT r.params, m.value
FROM experiment_metrics m JOIN experiment_runs r ON r.id = m.run_id
WHERE m.name = 'accuracy' ORDER BY m.value DESC LIMIT 5;
```

A metric that only some runs have is visible as a gap in that table rather than as a zero.

---

## 5. The record

| table | holds |
|-------|-------|
| `experiment_specs` | id `ex_…`, name, hypothesis, command, root, declared params, metrics source, `open`/`closed` |
| `experiment_runs` | id `xr_…`, the params used, the resolved command, status, exit code, duration, metrics JSON, `metrics_error`, task/tool-run/artifact ids, seed, note |
| `experiment_metrics` | `(run_id, name)` → `value`, plus the raw text when it was not numeric |

```bash
archx-agent experiment show ex_…      # runs, metrics, counts, the failing runs
archx-agent experiment runs ex_…      # the ledger
archx-agent experiment stats          # how many experiments, runs, metrics
archx-agent experiment close ex_…     # the runs stay readable
archx-agent experiment reopen ex_…
archx-agent experiment delete ex_… --yes   # takes the runs and metrics with it
```

`close` is not `delete`: a closed experiment cannot be run again until it is reopened, and
`delete` requires `--yes` because it removes the history too.

---

## 6. Where it is exercised

| what | where |
|------|-------|
| unit and route tests | `tests/test_experiments_m32.py` (65) |
| acceptance, driven like a person | `scripts/acceptance_m32.sh` (53 checks) |
| CI step | `experimental mode acceptance` in `.github/workflows/model-matrix.yml` |
| GUI | the **Experiments** tab, `docs/GUI.md` § the Experiments panel |

The acceptance script is the honest one: it grants `shell.run` halfway through to prove the
refusal came first, composes a metrics file inside the experiment directory, breaks the JSON on
purpose, and asks the GUI the same questions the CLI answered.

---

## 7. What this is not

* **Not a sweep runner.** There is no grid expansion in the runner; `--set` is one run. A sweep is
  a loop over `experiment run`, which keeps every run a row and every failure visible — and it is
  what a workflow step is for.
* **Not a plot.** Numbers are queryable rows; drawing them is M41's job, and a chart built from
  these rows cannot disagree with the table.
* **Not a model judge.** No model is asked what a run means. If a metric is not declared, there is
  no metric.
