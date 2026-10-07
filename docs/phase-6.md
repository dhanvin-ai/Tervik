# Phase 6: intents and recurring-problem discovery

Implements section 9 of the saved roadmap: configured intents first, then
the founder-described discovery pipeline (embed → cosine-drift
segmentation → BIRCH compression → density grouping → matching), evaluated
rather than assumed.

## Pipeline

- Embeddings: deterministic TF-IDF + L2 normalization (`app/clustering.py`).
  An SVD variant was evaluated and rejected: dense projections smeared
  unrelated short texts together and collapsed precision. The embedding
  step is a seam: a model-based provider plugs in without changing
  segmentation, grouping, matching, or storage.
- Segmentation: conversations with 6+ messages split where consecutive
  message cosine similarity drops below 0.25.
- Compression: BIRCH CF-tree (`threshold=0.3`, no forced partitioning).
  Radius-bounded multi-member centers are emitted as cores directly.
- Grouping: singleton centers merge only on mutual-best centroid matches
  (mutual reachability without hub chaining), leftovers join above 0.30
  mean similarity, members below 0.30 peak similarity are ejected.
- Matching: new traffic assigns to the nearest group centroid above 0.35.
- Intents: customer examples matched by centroid cosine above 0.30, so the
  product works before substantial traffic exists.

## Measured quality

`tests/fixtures/clustering-eval.json` is tiered: `repeated`
(near-verbatim recurring phrasings, the production shape) and
`paraphrase` (uniquely-worded same-topic texts, needs model embeddings).
`apps/api/.venv/bin/python scripts/evaluate_discovery.py` reports pairwise
precision/recall plus repeated-tier recall; the pytest gate
(`test_discovery_eval.py`) requires precision >= 0.85 and repeated-tier
recall >= 0.70. Current: precision 1.0, repeated recall 0.73, zero
mistaken merges. The paraphrase tier is reported, not gated, and tracks
the embedding-adapter gap.

## Product surface

- Discovery page: recurring topics with evidence, member conversations,
  coverage denominators (conversations/messages/users kept distinct),
  configured intents with match counts.
- Lifecycle: rename (label override, evidence untouched), dismiss, merge,
  split, manual creation. Taxonomies are per-project; customer edits
  preserve evidence because edits touch labels/status, never telemetry.
- `docs/compatibility.md` keeps the integration matrix; model-based
  discovery stays future work alongside alerts (Phase 7).
