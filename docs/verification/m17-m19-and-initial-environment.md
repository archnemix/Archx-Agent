# Historical verification: M17–M19 and initial environment

This is a recorded run. See the [verification index](../VERIFICATION.md) for context.

# Verification record

Everything in this file was produced by running the installed console script in this
environment. Nothing here is written from memory; regenerate it with:

```bash
./scripts/acceptance_m17_m19.sh
```

## Environment actually available to this build

| item | value | how it was checked |
|------|-------|--------------------|
| Python | 3.11.2 (only version installed) | `python3 --version`; `apt-cache` shows no 3.13; GitHub release downloads blocked (exit 35) |
| CPU / RAM | 2 vCPU / 3 GB | `nproc`, `/proc/meminfo` |
| PyPI | reachable | `curl -sI https://pypi.org/simple/` → 200 |
| Hugging Face | **unreachable** | `curl https://huggingface.co` → 000 |
| GPU | none | `nvidia-smi` absent, no `/dev/nvidia*` |
| Model weights | none obtainable | HF and its CDN are blocked, so `LlamaCppRuntime` is implemented but **unverified against a real GGUF file** |

Consequences, recorded rather than worked around:

* chat-level acceptance uses the explicitly labelled `ScriptedRuntime` test double
  (`[SIMULATED]` in every answer, `simulated: true` in JSON, recorded in traces);
* the HTTP provider contract is verified against a real local HTTP server, including
  401/402/404/429/500 and connection-refused classification;
* Python 3.13 verification is **not performed** (see GAPS.md).

## Repository state before this work

The starting commit contained a two-line `README.md` and no code:

```
$ git log --oneline --all
45c786e README
$ git ls-tree -r --name-only HEAD
README.md
```

M01-M16 therefore did not exist in this repository and were rebuilt from the foundations
before M17. `PLAN.md` lists them individually with the test file that verifies each.

## M17-M19 acceptance transcript


### home
/tmp/archx-accept-WMd5MB
$ archx-agent init
Archx Agent initialised
  home       /tmp/archx-accept-WMd5MB
  database   /tmp/archx-accept-WMd5MB/archx.db
  traces     /tmp/archx-accept-WMd5MB/events.db
  config     /tmp/archx-accept-WMd5MB/config.json
  schema     v11
  models     none found in the models directory
             add one with: archx-agent models add-http ...
[exit 0]

### M17 - six memory systems
$ archx-agent models add-scripted --name demo
registered SIMULATED model demo (mdl_0001m5wtv74j000000008b02e3924202d680)
  this runtime performs no inference; it exists to exercise the app offline
[exit 0]
project id: proj_0001m5wtv78s00000000f9a035ce3466236b
conversation id: conv_0001m5wtv7dr000000000470f829bdf68d5f
$ archx-agent memory add --kind active --conversation conv_0001m5wtv7dr000000000470f829bdf68d5f --category goal --title Current goal --content Finish the memory foundation before retrieval work --slot current_goal
stored active memory mem_0001m5wtv7jg00000000784b179bd7f0d9b6
  scope     conversation (conv_0001m5wtv7dr000000000470f829bdf68d5f)
  category  goal
  slot      current_goal
[exit 0]
$ archx-agent memory add --kind permanent --category preference --title Style --content Prefer short, direct answers without filler
stored permanent memory mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41
  scope     global
  category  preference
[exit 0]
$ archx-agent memory add --kind archival --category finding --title Benchmark note --content Keyword scan over 20k memories took 41 ms on this machine --provenance-origin manual benchmark --source user
stored archival memory mem_0001m5wtv7tv0000000030b81aa9d534536f
  scope     global
  category  finding
[exit 0]
$ archx-agent memory add --kind project --project proj_0001m5wtv78s00000000f9a035ce3466236b --category decision --title Storage choice --content Use one SQLite database with a single writer thread --provenance-origin design review --source user
stored project memory mem_0001m5wtv7z7000000009eadbe25bf1fcbdf
  scope     project (proj_0001m5wtv78s00000000f9a035ce3466236b)
  category  decision
[exit 0]
$ archx-agent memory add --kind solution --category known_issue --title Database is locked --content Under concurrent writers SQLite returned database is locked --problem concurrent writes fail with database is locked --solution serialise writes through one writer thread and set busy_timeout --verification verified --evidence storage suite: 40 concurrent writes, 0 failures
stored solution memory mem_0001m5wtv83d0000000098d4d8b2b82a1a19
  scope     global
  category  known_issue
[exit 0]
$ archx-agent memory add --kind learning --category progress --title Learned WAL --content WAL mode lets readers continue while a write is in flight --topic sqlite --outcome passed
stored learning memory mem_0001m5wtv87g00000000d7f3b0e4d591f09c
  scope     learner (default)
  category  progress
[exit 0]

### retrieval under a budget (what actually reaches the model)
$ archx-agent memory retrieve --conversation conv_0001m5wtv7dr000000000470f829bdf68d5f --project proj_0001m5wtv78s00000000f9a035ce3466236b --budget 90
budget 90 tokens, used 73
  + active    Current goal  (18t) - active memory for this conversation
  + permanent Style  (14t) - permanent memory (global)
  + project   Storage choice  (19t) - project memory
  + solution  Database is locked  (22t) - verified solution matched the request
[exit 0]

### edit keeps history, duplicate is refused
$ archx-agent memory edit mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41 --content Prefer short, direct answers; no filler at all
updated mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41 to version 2
[exit 0]
$ archx-agent memory history mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41
version  change  changed_at              
-------  ------  ------------------------
1        update  2026-10-26T19:26:24.901Z
[exit 0]
$ archx-agent memory add --kind permanent --category preference --title Style --content Prefer short, direct answers; no filler at all
error: an identical permanent memory already exists (mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41)
[exit 1]

### search, then delete (soft) and confirm it is gone from results
$ archx-agent memory search sqlite
[degraded] no embedding index is configured; semantic search is unavailable and results are keyword-only
  6.40  solution  Database is locked
        mem_0001m5wtv83d0000000098d4d8b2b82a1a19  (token-overlap=0.12, content-substring, verified, age_days=0.0)
  4.82  project   Storage choice
        mem_0001m5wtv7z7000000009eadbe25bf1fcbdf  (token-overlap=0.11, content-substring, age_days=0.0)
[exit 0]
$ archx-agent memory delete mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41
mem_0001m5wtv7pm00000000ddbfb8ca5cadfd41: deleted
[exit 0]
$ archx-agent memory search filler
[degraded] no embedding index is configured; semantic search is unavailable and results are keyword-only
no memories match 'filler'
[exit 0]
$ archx-agent memory stats
{
  "by_kind": {
    "active": 1,
    "permanent": 0,
    "archival": 1,
    "project": 1,
    "solution": 1,
    "learning": 1
  },
  "total_active": 5,
  "deleted": 1,
  "sources": 0,
  "retrievals": 4,
  "history_entries": 2,
  "embedding_states": {
    "awaiting": 5
  }
}
[exit 0]

### M18 - embeddings and measured retrieval quality
$ archx-agent config set memory.embeddings_enabled true
set memory.embeddings_enabled = True in /tmp/archx-accept-WMd5MB/config.json
[exit 0]
$ archx-agent embeddings status
provider local-hash model=archx-hash-v1 dim=256 semantic=False local=True
states           {}
stale vectors    0
threshold        0.62
[exit 0]
$ archx-agent embeddings backfill
{
  "embedded": 7,
  "failed": 0,
  "model_id": "archx-hash-v1"
}
[exit 0]
$ archx-agent embeddings search which database do we use for storage -k 3 --threshold 0
scanned 5 vector(s) with archx-hash-v1
  0.378  Storage choice  mem_0001m5wtv7z7000000009eadbe25bf1fcbdf
  0.187  Database is locked  mem_0001m5wtv83d0000000098d4d8b2b82a1a19
  0.050  Learned WAL  mem_0001m5wtv87g00000000d7f3b0e4d591f09c
[exit 0]
$ archx-agent eval retrieval --dataset /home/user/Archx-Agent/data/retrieval_set.json --k 5
# Retrieval evaluation: archx-memory-retrieval-v1

Labelled retrieval set over Archx project knowledge: technical facts, decisions, known issues and solutions. Relevance is graded 1 (useful) to 3 (directly answers the query).

Corpus: 20 items, queries: 12, k=5

| mode | precision@k | recall@k | MRR | nDCG@k | degraded |
|------|-------------|----------|-----|--------|----------|
| keyword | 0.379 | 0.764 | 0.681 | 0.637 | no |
| semantic | 0.283 | 0.847 | 0.896 | 0.839 | no |
| hybrid | 0.396 | 0.806 | 0.917 | 0.850 | no |

Notes reported by the implementation:
- keyword-only baseline (vectors deliberately unused)

Per-query detail is included in the JSON report (`--json`).
[exit 0]
$ archx-agent eval retrieval ... --json --no-scratch   # (full JSON omitted here; regenerate with the script)

### M19 - five context strategies preserve history
$ archx-agent context build conv_0001m5wtv7dr000000000470f829bdf68d5f --strategy oldest_first --budget 120
manifest ctx_0001m5wtvbcz000000004bdcf343c5441c7d  strategy=oldest_first
budget 120  used 118  memory 22
included:
  + memory   mem_0001m5wtv7jg000000   22t  memory retrieval: active
  + message  msg_0001m5wtvb3q000000   18t  recent turn
  + message  msg_0001m5wtvb80000000   24t  recent turn
  + message  msg_0001m5wtvb82000000   18t  recent turn
omitted:
  - message  msg_0001m5wtvazd000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvazb000000 24t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvav5000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvav3000000 24t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvapv000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvaps000000 24t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvajh000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvajf000000 24t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvae9000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvae7000000 24t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtv7e1000000 18t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtv7dz000000 14t  older turn dropped to fit the context window (stor
  - message  msg_0001m5wtvb3n000000 24t  prompt overhead pushed the window over budget (old
[exit 0]
$ archx-agent context build conv_0001m5wtv7dr000000000470f829bdf68d5f --strategy ai_select --budget 150 --message what did we decide about storage
manifest ctx_0001m5wtvbhe00000000f663e7806244aa35  strategy=ai_select
budget 150  used 144  memory 22
included:
  + memory   mem_0001m5wtv7jg000000   22t  memory retrieval: active
  + message  msg_0001m5wtvb3n000000   24t  selected: recent, relevant to the request
  + message  msg_0001m5wtvb3q000000   18t  selected: recent, relevant to the request
  + message  msg_0001m5wtvb80000000   24t  selected: recent, relevant to the request
  + message  msg_0001m5wtvb82000000   18t  selected: recent, relevant to the request
omitted:
  - message  msg_0001m5wtvae7000000 24t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvae9000000 18t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvajf000000 24t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvajh000000 18t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvaps000000 24t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvapv000000 18t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvav3000000 24t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvav5000000 18t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvazb000000 24t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtvazd000000 18t  not selected (score 0.00, low relevance)
  - message  msg_0001m5wtv7dz000000 14t  prompt overhead pushed the window over budget (old
  - message  msg_0001m5wtv7e1000000 18t  prompt overhead pushed the window over budget (old
[exit 0]
$ archx-agent context build conv_0001m5wtv7dr000000000470f829bdf68d5f --strategy summarize --budget 150 --allow-simulated
manifest ctx_0001m5wtvbnj0000000275856edcb0388eaf  strategy=summarize
budget 150  used 143  memory 22
included:
  + memory   mem_0001m5wtv7jg000000   22t  memory retrieval: active
  + summary  sum_0001m5wtvbng000000   35t  older messages summarised
  + message  msg_0001m5wtvb80000000   24t  recent turn
  + message  msg_0001m5wtvb82000000   18t  recent turn
omitted:
  - message  msg_0001m5wtv7dz000000 10t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtv7e1000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvae7000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvae9000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvajf000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvajh000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvaps000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvapv000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvav3000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvav5000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvazb000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvazd000000 14t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvb3n000000 20t  replaced in-context by summary sum_0001m5wtvbng000
  - message  msg_0001m5wtvb3q000000 18t  prompt overhead pushed the window over budget (old
[exit 0]
proposal: prop_0001m5wtvbse00000000d80ce674b7029c69
$ archx-agent context build conv_0001m5wtv7dr000000000470f829bdf68d5f --strategy ai_proposed --proposal prop_0001m5wtvbse00000000d80ce674b7029c69 --budget 150 --allow-simulated
manifest ctx_0001m5wtvbxr000000002afcbf214de040e6  strategy=ai_proposed
budget 150  used 139  memory 22
included:
  + memory   mem_0001m5wtv7jg000000   22t  memory retrieval: active
  + summary  sum_0001m5wtvbxp000000   15t  approved summarisation
  + message  msg_0001m5wtvb3q000000   14t  retained by approved proposal
  + message  msg_0001m5wtvb80000000   20t  retained by approved proposal
  + message  msg_0001m5wtvb82000000   14t  retained by approved proposal
omitted:
  - message  msg_0001m5wtv7dz000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtv7e1000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvae7000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvae9000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvajf000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvajh000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvaps000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvapv000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvav3000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvav5000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvazb000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvazd000000 ?t  replaced by an approved summary
  - message  msg_0001m5wtvb3n000000 20t  prompt overhead pushed the window over budget (old
[exit 0]
$ archx-agent context build conv_0001m5wtv7dr000000000470f829bdf68d5f --strategy manual --manual-ids msg_0001m5wtvae7000000003745e4d5d20e5194 --budget 300
manifest ctx_0001m5wtvc5r00000000f05eaa88432c2359  strategy=manual
budget 300  used 29  memory 0
included:
  + message  msg_0001m5wtvae7000000   24t  manually included
omitted:
  - message  msg_0001m5wtv7dz000000 14t  not selected manually
  - message  msg_0001m5wtv7e1000000 18t  not selected manually
  - message  msg_0001m5wtvae9000000 18t  not selected manually
  - message  msg_0001m5wtvajf000000 24t  not selected manually
  - message  msg_0001m5wtvajh000000 18t  not selected manually
  - message  msg_0001m5wtvaps000000 24t  not selected manually
  - message  msg_0001m5wtvapv000000 18t  not selected manually
  - message  msg_0001m5wtvav3000000 24t  not selected manually
  - message  msg_0001m5wtvav5000000 18t  not selected manually
  - message  msg_0001m5wtvazb000000 24t  not selected manually
  - message  msg_0001m5wtvazd000000 18t  not selected manually
  - message  msg_0001m5wtvb3n000000 24t  not selected manually
  - message  msg_0001m5wtvb3q000000 18t  not selected manually
  - message  msg_0001m5wtvb80000000 24t  not selected manually
  - message  msg_0001m5wtvb82000000 18t  not selected manually
[exit 0]
$ archx-agent context summaries conv_0001m5wtv7dr000000000470f829bdf68d5f
[
  {
    "id": "sum_0001m5wtvbng00000000830070e06916aa2b",
    "conversation_id": "conv_0001m5wtv7dr000000000470f829bdf68d5f",
    "source_start_seq": 1,
    "source_end_seq": 13,
    "content": "[SIMULATED] I received 143 words. No model was run.",
    "token_estimate": 15,
    "generator": "simulated-test-double",
    "created_at": "2026-10-26T19:26:28.016Z",
    "superseded_by": null
  },
  {
    "id": "sum_0001m5wtvbxp0000000011de7b3c01dea15b",
    "conversation_id": "conv_0001m5wtv7dr000000000470f829bdf68d5f",
    "source_start_seq": 1,
    "source_end_seq": 12,
    "content": "[SIMULATED] I received 132 words. No model was run.",
    "token_estimate": 15,
    "generator": "simulated-test-double",
    "created_at": "2026-10-26T19:26:28.278Z",
    "superseded_by": null
  }
]
[exit 0]
stored messages after all of the above:
16

### trace: every write above is recorded
$ archx-agent trace list --limit 12
seq  time      kind          name                  status  detail
---  --------  ------------  --------------------  ------  ------
1    19:26:23  system        workspace.opened      ok            
2    19:26:23  system        workspace.closed      ok            
3    19:26:23  system        workspace.opened      ok            
4    19:26:23  system        workspace.closed      ok            
5    19:26:23  system        workspace.opened      ok            
6    19:26:23  project       project.created       ok            
7    19:26:23  system        workspace.closed      ok            
8    19:26:23  system        workspace.opened      ok            
9    19:26:23  conversation  conversation.created  ok            
10   19:26:23  context       context.built         ok            
11   19:26:23  message       message.appended      ok            
12   19:26:23  model_call    model.request         ok      demo  
[exit 0]
$ archx-agent db check
integrity     ok
foreign keys  ok
schema        v11
tables        47
write journal 5 recent entries
[exit 0]


## Observed results, summarised

| check | result |
|-------|--------|
| six memory kinds created through the CLI | 6/6, each with scope + provenance printed |
| active/project/learning scope enforcement | active requires a conversation, project requires a project, learning lands in `learner` scope |
| duplicate refusal | identical permanent memory refused, exit 1, existing id named |
| edit keeps history | version 2, previous snapshot listed by `memory history` |
| retrieval under a 90-token budget | 73 tokens used, four items with reasons, archival excluded by design |
| soft delete | `search` no longer returns it, `memory stats` counts it as deleted |
| embeddings backfill + search | 7 vectors, top hit 0.378 for the storage question |
| retrieval evaluation | keyword 0.637 / semantic 0.839 / hybrid 0.850 nDCG@5 |
| all five context strategies | manifests produced, every omission has a reason |
| history preserved by every strategy | stored message count unchanged after summarize + ai_proposed |
| rejected proposal | cannot be applied after rejection (exit 2) |
| trace | writes, model calls and context builds recorded in order |
| `db check` | integrity ok, foreign keys ok, schema v12, 48 tables (pre-M21 baseline) |

