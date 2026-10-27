# Retrieval: embeddings, hybrid search and measured quality

This document covers M18 (embedding + retrieval evaluation) and the retrieval half of
M19 (how retrieved memory enters the context window). Numbers here are measured in this
repository; the command that produced them is quoted next to them.

## What is stored

`managers/schema.py` v9:

```sql
CREATE TABLE embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_type TEXT NOT NULL,      -- memory | message | artifact
  owner_id   TEXT NOT NULL,
  model_id   TEXT NOT NULL,      -- e.g. archx-hash-v1, bge-small-en-v1.5
  dim        INTEGER NOT NULL,
  vector     BLOB NOT NULL,      -- float32, little endian
  checksum   TEXT NOT NULL,      -- of the exact source text
  state      TEXT NOT NULL,      -- embedded | stale | failed
  created_at TEXT NOT NULL,
  UNIQUE(owner_type, owner_id, model_id)
);
```

Three rules follow from the schema:

1. **Identity travels with the vector.** A vector is only comparable with another vector
   from the same model *and* dimension; `helpers/vectors.top_k` raises on a mismatch and
   `EmbeddingManager.search` refuses to mix models. Silent mixing produces
   confident-looking nonsense.
2. **The checksum is the source text's.** If a memory is edited, the old vector no longer
   matches and is reported as stale rather than used.
3. **States are explicit.** `memories.embedding_state` is one of `awaiting` / `embedded` /
   `failed`. Retrieval reports how many candidates had no vector instead of pretending
   coverage is complete.

## Providers

| id | model_id | dim | local | semantic | notes |
|----|----------|-----|-------|----------|-------|
| `local-hash` | `archx-hash-v1` | 256 (32–4096) | yes | **no** | deterministic feature hashing of word unigrams/bigrams + char trigrams; dependency-free offline default; deliberately labelled non-semantic |
| `sentence-transformers` | configurable (`BAAI/bge-small-en-v1.5` recommended) | discovered | yes (after download) | yes | optional extra; raises `UnsupportedOperationError` if the package is missing |
| `http` | configurable | discovered then enforced | no | yes | any OpenAI-compatible `/v1/embeddings`; requires `memory.remote_embeddings=true`; refuses non-loopback endpoints otherwise |

`archx-agent embeddings status` prints provider id, model, dimension, and
`semantic=True/False` so the UI never overstates what it has.

## Why not the Qwen3.5 Vultron retriever

`vultr/VultronRetrieverPrime-Qwen3.5-8B` was evaluated as a candidate and **rejected**:

* it is an 8.4B **visual-document** retriever: input is page images plus a text query,
  output is 320-dim **per-token** multi-vectors scored with `score_multi_vector`
  (MaxSim late interaction), with up to 1792 visual tokens per page;
* it is not a pooled text-embedding model, so it cannot populate a
  `(owner_id, vector)` table of one vector per memory without inventing a reduction the
  model was not trained for;
* reported benchmarks (ViDoRe V1/V2/V3 = 92.08/68.18/64.26) are document-retrieval
  benchmarks over images, not memory snippets;
* 8.4B parameters cannot run in this environment (2 vCPU, 3 GB RAM, no GPU), and the
  model card's weights are not reachable here in any case.

Fallback used instead: the hash provider offline for a working, measurable pipeline;
`sentence-transformers` with `bge-small-en-v1.5` (33.4M params, 384-dim, MIT, 512-token
window, MTEB retrieval 51.68) as the recommended local semantic model when the package
and weights are available; `http` for any OpenAI-compatible embedding endpoint.

## Hybrid ranking

`MemoryManager.search` retrieves candidates with SQL token matching (`LIKE ... ESCAPE`
over up to 8 query tokens, OR'd — a full-phrase `LIKE` cannot match
`"database locked"` against `"Database is locked"`), then, when vectors exist, re-scores
the candidate set:

```
score = 3.0 * cosine(query, memory)
      + 2.0 * jaccard(query tokens, title+content tokens)
      + 1.0 * (query is a substring of the title)
      + 0.5 * pinned
```

Deliberate omissions:

* **No recency term.** It was tried: adding an age/usage bonus pushed correct answers
  below irrelevant recent ones (keyword MRR 0.708 *with* bonuses versus 0.917 for the
  hybrid without them). Freshness is not relevance; the UI shows recency separately.
* **No "access count" term.** Same reason, plus it creates a feedback loop where the item
  shown most becomes the item ranked highest.
* **Pinned content is a small prior (0.5)**, not a guarantee — pinning keeps something in
  the context window (M19) but must not monopolise search results.

Every result carries a human-readable `reason` string listing the components, so a
ranking can be explained without re-running it.

## Measured quality

Command (offline hash provider, no network):

```bash
archx-agent eval retrieval --dataset data/retrieval_set.json --k 5 --out docs/RETRIEVAL_EVAL.md
```

Dataset: `data/retrieval_set.json` — 20 labelled memories (facts, decisions, known issues,
solutions, learning notes) and 12 queries with graded relevance 1–3.

| mode | precision@5 | recall@5 | MRR | nDCG@5 |
|------|------------|----------|-----|--------|
| keyword (baseline) | 0.379 | 0.764 | 0.681 | 0.637 |
| semantic only | 0.283 | 0.847 | 0.896 | 0.839 |
| **hybrid** | **0.396** | 0.806 | **0.917** | **0.850** |

Reading these honestly:

* hybrid wins on precision, MRR and nDCG; keyword wins on recall because it returns more
  weakly-matched items and this corpus has large relevant sets per query;
* semantic-only has the *highest* recall and second MRR, but the lowest precision — the
  hash space is dense, so many neighbours score highly;
* **these numbers are an upper bound for same-vocabulary queries.** `archx-hash-v1` shares
  the query's vocabulary by construction. They prove the pipeline, the metrics and the
  hybrid blend; they do **not** prove semantic understanding. Re-run this command after
  installing a real semantic provider and the numbers will change — that is the point of
  having the harness.

## Scale limit

Comparisons are brute force over a candidate set: ~50k float dot products per second per
core at 256 dimensions (measured in this environment). Candidates are pre-filtered (scope,
kind, candidate ids from keyword matching, recency window), which keeps typical sets in
the hundreds or low thousands. **Beyond roughly 200k embedded objects**, add an ANN index
(sqlite-vec, hnswlib or a dedicated vector store) behind the same
`EmbeddingManager.search` boundary; the interface already returns `scanned` and
`degraded_reason` so a future index can be honest about what it did.

## Operations

```bash
archx-agent config set memory.embeddings_enabled true     # opt in
archx-agent embeddings status                            # provider, dim, coverage, staleness
archx-agent embeddings backfill --limit 500              # embed what is missing
archx-agent embeddings embed-conversation <conversation>
archx-agent embeddings search "which database do we use" -k 5 --threshold 0
archx-agent embeddings purge --model archx-hash-v1 --yes  # delete vectors, not memories
```

`embeddings search --threshold 0` is ranking mode (always return the top k); the default
threshold (0.62) is for "is this close enough to show as related", which is a different
question and must not be reused for ranking.
