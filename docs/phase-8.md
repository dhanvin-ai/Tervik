# Phase 8: evaluations and replay

Implements section 11 of the saved roadmap: a customer-controlled
evaluation runner that compares a candidate agent against a baseline
without touching live systems.

## How it works

- Datasets are built from production findings plus healthy controls
  (`POST /api/projects/{id}/datasets/from-findings`) or authored
  directly. Cases pin the input, recorded tool fixtures, and expectations
  (response content, required tool calls, banned violation kinds).
- Datasets stay `draft` until customer review (`reviewed`, `approved`);
  drafts cannot run. Deleting a dataset removes its runs.
- Runs execute the deterministic replay runner (`app/evaluate.py`):
  recorded tool outputs are served, unrecorded tools fail closed (sandbox
  isolation; `optional` calls skip instead), transcripts are rebuilt, and
  the Phase 5 detectors score rule compliance. Repeats (up to 5) verify
  stability; identical descriptors reproduce exactly (stable ids plus
  causal microsecond offsets, so analysis ordering cannot flake).
- Comparison reports per-case passes, fixed vs regressed sets, violation
  deltas, and a verdict (`improved`, `regressed`, `mixed`, `no_change`)
  with reproducible artifacts per run.
- Customer CI uses `tervik.replay.RecordedTools` to run pinned agent code
  against the same fixtures and post results back; unrecorded tools raise
  instead of reaching production.

## Gate

A candidate that wires the recorded tool fixes the target failure cases
without regressing controls, reproducibly (`test_phase8.py`). Latency and
cost are reported per case; model-variation repeats are supported via the
repeats parameter. Sandbox execution against isolated test tools is the
`RecordedTools` path; full customer-sandbox hosting stays future work
alongside automatic prompt application (Phase 9).
