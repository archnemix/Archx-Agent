# Remote compute and portability

A result computed on another machine is a **claim**. This page is about what makes one checkable,
and about the one thing this build does not do: reach a cloud.

```text
archx-agent remote export DATASET --order 3      # one JSON bundle, hashed, written through fs.write
archx-agent remote approve rj_…                 # the bundle may leave this machine
archx-agent remote dispatch rj_… --endpoint URL  # send it; record who answered
archx-agent remote collect rj_…                 # fetch the artifact and re-hash it here
archx-agent remote verify rj_…                  # re-read the file and compare it with the row
```

---

## 1. What this build is, and is not

There is no vendor SDK in this build, no credentials, and nothing that will bill anyone. A **worker**
is a second process - on this machine or another one - running:

```text
archx-agent remote worker --port 9001 --name box2                    # loopback only (default)
archx-agent remote worker --host 0.0.0.0 --port 9001 --name box2      # reachable from elsewhere
```

The worker has no database, no tools, no permissions and no workspace. Everything it needs is in the
request, which is the property that makes it a *worker* rather than a second client of the same
SQLite file. The record says `endpoint http://127.0.0.1:9001 computed this`, because that is a true
sentence; "the cloud computed this" would not be.

`archx-agent remote stats` prints the standing reason:

```text
no cloud provider is reachable from this build: a worker is a second machine (or a second
process) running `archx-agent remote worker`, and nothing here talks to a vendor's compute service
```

### 1.1 Adding a machine that is not this one

This is the case people mean by "remote": a VM, a rented box, a machine on the LAN. The recipe is
four steps, and the third is the one that decides whether it is safe.

**1. Put this build on the machine.** The worker needs Python 3.11 and this package - nothing else.
No GPU, no torch, no database, no `archx-agent init`, no home directory:

```bash
git clone <this repo> && cd Archx-Agent && ./scripts/bootstrap.sh
# or, into an existing environment:
python -m pip install -e .
```

**2. Start the worker there**, bound to the interface you want it reachable on:

```bash
archx-agent remote worker --host 0.0.0.0 --port 9001 --name render-box-1
# archx worker render-box-1 on http://0.0.0.0:9001 speaking archx-remote/1
```

**3. Make the port reachable - preferably through a tunnel, not a hole.** The worker has **no
authentication and no TLS**: anyone who can reach that port can submit a bundle and make the machine
work. So the honest options, best first:

```bash
# a. SSH tunnel from this machine; the port never opens to the world
ssh -N -L 9001:127.0.0.1:9001 user@vm.example.com     # then endpoint = http://127.0.0.1:9001

# b. a private network (WireGuard, tailscale, a VPC) and an allowlist in the cloud firewall

# c. a public port, which only makes sense behind your own reverse proxy doing TLS + auth
```

Option (a) is what this build's own acceptance run does in spirit: the client talks HTTP to a port
that only it can reach. Nothing in the protocol requires the worker to be local.

**4. Point this machine at it and run the lifecycle:**

```bash
archx-agent config set remote.enabled true
archx-agent config set remote.endpoint http://127.0.0.1:9001
archx-agent remote export DATASET --order 3
archx-agent remote approve rj_…
archx-agent remote dispatch rj_…          # --endpoint URL overrides remote.endpoint for one job
archx-agent remote collect rj_…
```

The record then says `endpoint http://… computed this`, with the machine name the worker reported
(`--name`), the protocol, and both hashes - so a result is traceable to *which* box produced it.

### 1.2 What actually executes over there

`train_records()` on the bundle: an `ngram` or `centroid` run over the records the bundle carried.
That is the whole vocabulary. There is **no way to run a shell command on the remote machine** -
`shell.run`, jobs and workflows all execute locally, in this process's sandbox, through the
permission centre. "Remote execution" here means *remote training on a bundle you hashed*, not
"send my job somewhere else and get my own code back". A bundle asking for `lora` is refused by the
worker for the same reason the local command refuses it: the trainer does not exist in this build.

What that costs you today: the corpus has to fit in `remote.max_chars` (200 000 characters), the
transfer is one JSON document with no resume, and there is no queue on the far side - a worker that
dies mid-run leaves the job `dispatched` until you dispatch again (which adds an attempt row rather
than erasing the first).

---

## 2. The bundle

`remote export` writes one document through `fs.write` and hashes it:

```json
{
  "protocol": "archx-remote/1",
  "archx_version": "0.1.0",
  "schema_version": 27,
  "created_at": "2026-10-29T08:45:31.002Z",
  "dataset": {
    "id": "ds_…", "name": "code", "license": "MIT", "seed": "m37",
    "records": 8, "by_split": {"train": 5, "val": 1, "test": 2},
    "manifest_checksum": "b7c1…",
    "manifest_lines": ["train\t1469…\t36\tcorpus/python/file1.txt", "…"],
    "text_scope": "as `fs.read` returns it - surrounding whitespace trimmed",
    "entries": [
      {"path": "corpus/python/file1.txt", "split": "train", "label": null,
       "file_sha256": "1469…", "file_bytes": 36,
       "text_sha256": "0135…", "text": "def function_1(x):\n    return x + 1"}
    ]
  },
  "run": {"method": "ngram", "order": 2, "smoothing": 0.1, "seed": 5, "label_source": "record"}
}
```

Three details are deliberate:

**Two digests per record, and they are not the same number.** `file_sha256` is measured with
`fs.probe`, which hashes bytes - the same measurement M35 recorded when the dataset was built.
`text_sha256` is the digest of the text the trainer will actually see, and `fs.read` trims
surrounding whitespace, so almost every file differs between the two. A bundle that recorded one
number for both would refuse its own records; one that hashed only the trimmed text could not be
compared with the dataset's own manifest. Neither is a nicety: the first is how a corpus edited
after the build is caught, the second is how an edit *in transit* is caught.

**The corpus travels.** A bundle naming only paths would be portable between two machines that
already share a filesystem, which is not portability, it is a shared disk. `remote.max_chars`
(default 200 000) refuses to ship a corpus that is larger than the user asked for.

**The run is declared, not inferred.** Method, order, smoothing, seed and the label rule are in the
bundle, so the worker trains what was asked for and the hash covers the request.

---

## 3. Nothing leaves without three answers

| Condition | Setting | Refusal says |
| --- | --- | --- |
| the switch | `remote.enabled` (off) | `remote compute is off: archx-agent config set remote.enabled true` |
| an endpoint | `remote.endpoint` (empty) | `no endpoint is configured: …` |
| an approval | `remote.require_approval` (on) | `… has not been approved: archx-agent remote approve rj_…` |

A refusal is a **row** (`status = refused`, `refusal` holds every reason), and an attempt row goes in
`remote_attempts`. The job can be dispatched later; nothing about the refusal is sticky except the
record of it.

---

## 4. What the worker checks before it computes

```text
protocol         this worker speaks archx-remote/1, the request speaks X
bundle_sha256    the body re-hashed here must equal the hash sent beside it
text_sha256      each record's text must hash to the digest in the bundle
manifest         the manifest lines rebuilt from the entries must match manifest_checksum
train split      at least one record must be in `train`
```

Each is a refusal over the wire - HTTP 422 with the reason in the body - and the requester stores it
as `refused`, with both versions named when the protocol is what disagreed. A worker answering
`archx-remote/0` is not guessed at.

Then it calls `train_records()` - **the same function the local `train run` uses**. The tests assert
that a remote run and a local run of the same config produce *equal* perplexities, not close ones.
A worker with its own implementation would make every remote metric a claim about a second program.

---

## 5. What comes back, and what it is worth

`remote collect` fetches the artifact and stores:

| Column | Meaning |
| --- | --- |
| `claimed_sha256` | what the worker said the artifact hashes to |
| `received_sha256` | what this machine measured on arrival |
| `artifact_path` | where the bytes were written (through `fs.write`) |
| `verify_note` | a sentence either agreeing or naming both hashes |
| `verified_at` | set **only** when the two agree |

A disagreement marks the job `received`, records the attempt as `mismatch`, and stops there. Calling
`remote verify` again re-reads the file, but it also re-checks the claim: a worker that misreported
its hash once cannot become verified by asking twice.

```text
$ archx-agent remote collect rj_…
received rj_…
  http://127.0.0.1:9001 returned an artifact, but its hash did not match the claim
  claimed   0000000000000000000000000000000000000000000000000000000000000000
  measured  8974207343b5330b33523079ffd245ae80842225d1413ddf623549d1cb96c65d
  - the worker claimed 0000… but the bytes hash to 8974…
```

The worker's metrics are kept on the row (`outputs.metrics`), so `remote show` prints them and a
comparison is a query rather than a screenshot:

```text
test     perplexity 4.2747, records 2, tokens 14
train    perplexity 2.8928, records 5, tokens 39
val      perplexity 4.2747, records 1, tokens 7
worker   records 8, seconds 0.001
```

---

## 6. The ledger

`remote_jobs` was **reserved in v8** (`provider`, `status`, `config`, `estimate`, `actual`,
`outputs`, `approved_by`, `task_id`). v27 adopts it with `ALTER TABLE` - a home that already had rows
keeps them - and adds what makes a result checkable: `dataset_id`, `kind`, `endpoint`, `machine`,
`protocol`, both hashes, `bundle_path`, `artifact_path`, `verified_at`, `verify_note`,
`remote_job_id`, `received_at`, `refusal`.

`remote_attempts(id, job_id, action, status, detail, endpoint, created_at, metadata)` is one row per
thing that was tried: `approve`, `dispatch`, `collect`. A dispatch that never arrived is a finding
(`failed`), and it is stored where the next reader will see it rather than printed once and lost.

Statuses: `draft → refused | dispatched → running → received → verified`, plus `failed`.

---

## 7. The page

The GUI's **Remote** tab (17th) is a client of the same service over the same socket, with the same
token requirement: `GET /api/remote/jobs`, `POST /api/remote/export`,
`POST /api/remote/jobs/{id}/{approve,dispatch,collect,verify}`, `GET /api/remote/jobs/{id}`.

It shows the two hashes as separate rows, because the interesting case is the one where they
disagree, and it offers only the actions the row allows - a job that is already approved has no
Approve button, and one that is `received` is offered `Verify again`, not `Dispatch`.

---

## 8. What this does not do

- **No cloud.** No provider SDK, no credential handling, no billing, no queue. A worker is a process
  you start and can see.
- **No bulk transfer.** The bundle carries the corpus in JSON, capped by `remote.max_chars`. There is
  no chunking, no resume, no compression.
- **No multi-machine training.** One bundle, one worker, one result. There is no sharding or
  aggregation, and nothing here claims otherwise.
- **No authentication on the worker and no TLS.** A worker on loopback is who it says; a worker
  across a network is identified by the endpoint you typed and by the hash of the bytes it returned.
  There is no signing key and no shared secret, so an open worker port is an open endpoint - use an
  SSH tunnel or a private network (§1.1 step 3) rather than a public port.
- **No retries.** A failed dispatch stays failed; the honest recovery is to dispatch again, which
  adds a second attempt row rather than erasing the first.
- **The worker runs this build's trainers only.** `ngram` and `centroid`. A bundle asking for `lora`
  is refused by the worker for the same reason the local command refuses it.
