# Phase 1: working foundation

This phase establishes an installable integration and a locally runnable product. Completion means these acceptance gates have been demonstrated; it does not mean full Agnost parity or public SaaS readiness.

| Gate | Verification | Status |
|---|---|---|
| Repository and repeatable setup | Dependency installation and documented commands; ignored credentials/data | Complete |
| Project creation and credentials | Create project; ingest key cannot authorize administration | Complete |
| Durable ingestion | Valid batch commits; invalid batch commits nothing; duplicate retry adds no records | Complete |
| Project boundaries | Identical source IDs in different projects remain distinct | Complete |
| Dashboard backed by persisted data | Overview, filters, evidence, conversation and nested spans | Complete |
| Reviewable triage | Evidenced deterministic signals; resolution persists and changes only review status | Complete |
| Downloadable skill and SDK | Valid skill, downloaded ZIP, portable clients, successful SDK/API request | Complete |
| Container adapters | PostgreSQL ingestion/query round trip and ClickHouse mirror verified | Complete |
| Regression checks and CI | Builds, TypeScript, SDK/API tests, restart smoke, Actions workflow | Complete |

## Included

React dashboard, FastAPI service, SQLAlchemy storage adapters, project keys, event schema, conversations and spans, deterministic signal groups, review status, setup screen, a packaged integration skill, portable Node/Python clients, sample workspace, container configuration, and automated checks.

Sample conversations must be loaded explicitly and labeled as demo data. Runtime counts, rates, costs, and trends must come from stored events. Evidence requires a matching recorded message or tool outcome.

## Deferred

Account login and organization permissions; semantic classification/clustering; distributed analysis; durable ClickHouse retry; retention and deletion lifecycle; hosted deployment; alert delivery; MCP service; replay/evaluations; automated prompt or code changes; billing. No later phase starts automatically when this phase is handed over.

## Test record

Validated on 6 October 2026:

- `npm run check`: passed TypeScript checks, SDK/web production builds, 9 Node SDK tests, 6 Python client tests, 30 API tests, and the end-to-end restart smoke test. The API test runner reports one upstream Starlette/httpx deprecation warning; no test fails.
- `npm run test:containers`: passed against running PostgreSQL 17 and ClickHouse 25.8 containers. Verified committed events, validation atomicity, administrator/ingest-key separation, duplicate acknowledgements, persisted dashboard counts, and exact ClickHouse mirror count. Test-owned records were removed afterward.
- PostgreSQL verification exposed a driver-specific `rowcount` ambiguity. Ingestion now uses `INSERT … RETURNING` to count accepted records, so duplicate delivery is acknowledged correctly and is not mirrored twice.
- Skill validator: passed. ZIP integrity and required clients verified. The browser's download produced the actual generated skill archive.
- Independent coding-agent fixture: installed the portable Node client into an existing HTTP handler, exercised real local tool operations, and verified 12 events per pass. Repeating integration produced 12 again rather than double capture. Responses, original exceptions, parent spans, and application-specific redaction were preserved.
- Browser checks: explicit sample loading, stored metrics/trend, failure search/evidence, review action, conversation messages, trace selection and recorded inputs/outputs, skill download, and mobile navigation. At a 390px viewport the document width was 390px with no horizontal overflow; the temporary viewport override was reset.
- GitHub Actions workflow runs the same `npm run check` suite on pushes and pull requests. Current remote runs are visible in the repository's Actions tab.
