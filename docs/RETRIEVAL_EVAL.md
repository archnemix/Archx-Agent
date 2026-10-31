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
