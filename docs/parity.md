# Feature-matrix parity review (Phase 10 gate)

Each row of `docs/feature-matrix.md` against this build. Status is
implemented and tested unless noted.

| Feature | Status |
|---|---|
| Website | Deferred: dashboard welcome + integration pages serve onboarding; public site pending |
| Accounts | Done: signup/login/logout, expiring sessions, revocation |
| Organizations and roles | Done: owner/admin/member/viewer, cross-org isolation enforced |
| Projects and environments | Done: org-owned, environment-scoped credentials |
| Credential lifecycle | Done: hashed, once-only, revocable, audited; ingest cannot read |
| HTTP ingestion | Done: durable outbox, idempotent, usage-once, quotas |
| OTLP ingestion | Done: TracesData JSON, identity-preserving normalization |
| Recovery and diagnostics | Done: jobs view, replay, bounded retries, dead-letter, ops summary |
| Capture and retention | Done: per-project settings, pre-queue redaction, retention runner, export, deletion |
| TypeScript SDK | Done: buffering, streaming, tools, never-throw, version header |
| Python SDK | Done: client, streaming, OpenAI/LangChain/Anthropic, replay helper |
| Downloadable skill | Done: 9-step procedure, idempotence marker, ZIP bundle (skill-install UX polish deferred to last-mile list) |
| Conversation investigation | Done: search, timeline, messages/trace tabs, evidence |
| Trace investigation | Done: nested spans, out-of-order, tool I/O |
| Framework integrations | Partial: OpenAI, LangChain, Anthropic via fixtures; more frameworks per demand |
| Failure classification | Done: 8 evidenced categories, versions, 1.0/1.0 eval, abstention |
| Intent discovery | Done: configured intents + matching |
| Semantic clustering | Done: P=1.0/repeated-R=0.73 tiered gate; model-embedding recall tracked |
| Dashboard analytics | Done: trends, filters, coverage denominators |
| Alerts and summaries | Done: threshold/trend/summary, webhook/email, dedup, retries, replay |
| Hosted MCP | Done: session-auth JSON-RPC tools, scoped, audited (OAuth provider future) |
| Evaluations | Done: findings datasets, review gate, replay comparison, verdicts |
| Improvements | Done: lifecycle with guards, registry, rollback, measurements (repo-PR delivery via exported diff) |
| Outcome measurement | Done: before/after flagged rates on resolve |
| Billing and usage | Partial: metering, plans, enforcement; payment provider pending |
| Administration | Done: roles, audit, retention, ops, backup check, runbooks |

Parity target met for the agreed Phase 1–10 scope. Open items (pilot
teams, payment provider, OAuth, model embeddings, voice/Go, public site,
repo-PR connector, skill-install UX) are tracked per-phase, not blockers.
