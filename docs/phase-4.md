# Phase 4: integration coverage

Implements section 7 of the saved roadmap. Python is the second SDK,
shipped as the `tervik` pip package (standard library only).

## What was built

- `packages/sdk-python`: `tervik.Tervik` client (buffered HTTP, flush,
  shutdown, redaction, drop counters) plus `tervik.integrations` with
  `instrument_openai` and `TervikCallbackHandler`. Frameworks are
  duck-typed and never imported.
- OpenAI: wraps `chat.completions.create` (including `stream=True`) and
  `responses.create`. Records user/assistant turns, token usage, model,
  and requested tool calls as tool spans. Re-instrumenting is a no-op;
  `unpatch()` restores the originals.
- LangChain/LangGraph: callback handler for chain/LLM/tool events with
  shared trace ids and tool-parent linkage. Duplicate run delivery is
  recorded once.
- Fixture tests per integration: normal calls, streaming, tool failures,
  parallel operations, retries, shutdown (`packages/sdk-python/tests`,
  8 tests). Client parity suite (`test_sdk_python.py`) covers the same
  matrix for the raw client.
- Historical import: original timestamps and stable span relationships
  round-trip through `POST /v1/events`; re-import is a no-op
  (`apps/api/tests/test_phase4.py`).
- `docs/compatibility.md`: versioned support matrix and the
  no-duplicate-telemetry rule.

## Completion gate

Every advertised integration passes its fixture tests. The remaining
gate item is one real customer application test per integration, which
requires a pilot application and is tracked as the Phase 4 exit criterion
alongside the matrix above.
