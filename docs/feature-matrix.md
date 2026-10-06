# Tervik feature matrix

This is the implementation checklist for [the saved roadmap](../plan.md). Phase numbers follow that roadmap. A working prototype is not a completed later-phase gate.

| Feature | Customer behavior | Dependencies | Completion test | Phase |
|---|---|---|---|---|
| Website | Explain the product and offer the two-step skill setup | Skill release, onboarding | Installation command and prompt lead to a recorded customer conversation | 1 specification; 3 release |
| Accounts | Sign up, log in, log out, select an organization | Password hashing, expiring sessions, membership | Logged-out access fails; session revocation takes effect | 2 |
| Organizations and roles | Owners manage access; viewers investigate without changing settings | Tenant-scoped queries, role checks | Cross-organization identifiers return no data; viewer mutations fail | 2 |
| Projects and environments | Separate applications and development/production telemetry | Organization ownership, scoped credentials | A key cannot inject into another project or environment | 2 |
| Credential lifecycle | Create an ingest-only key, copy once, revoke it | Hashed keys, role checks, audit records | Revoked key fails; ingest key cannot read conversations | 2 |
| HTTP ingestion | Send bounded validated batches and retry safely | Stable IDs, durable acceptance, normalization | Acknowledged events survive worker termination; retries do not increase counts | 2 |
| OTLP ingestion | Export technical operations and GenAI attributes | OTLP HTTP decoding, normalization | Nested and out-of-order spans preserve their identifiers and parents | 2 |
| Recovery and diagnostics | Inspect pending/failed work and replay failures | Retry budget, dead-letter records, permissions | Failed job is visible without leaking contents; replay succeeds once | 2 |
| Capture and retention | Choose content capture, redact sensitive fields, expire stored telemetry | Ingestion settings, deletion worker, object-store lifecycle | Redacted content never reaches a sink; expired data leaves every configured sink | 2 |
| TypeScript SDK | Capture interactions without interrupting the agent | HTTP contract, buffering, stable IDs | Flush, retries, tool exceptions, and shutdown preserve application behavior | 3 |
| Python SDK | Same workflow for Python applications | Second client, compatibility fixtures | Streaming/async/tool fixture reaches the same canonical records | 4 |
| Downloadable skill | Inspect a repo, instrument the real entrypoint, verify traffic | SDK, authenticated project setup, integration recipes | Re-running the skill adds no duplicate wrappers; a real interaction is visible | 3 |
| Conversation investigation | Search and inspect ordered messages | Canonical messages, timestamps, tenant queries | Late messages sort by source time and remain linked to their conversation | 3 |
| Trace investigation | Inspect model calls and nested tools separately from messages | Traces, spans, tools, normalized attributes | Several operations can belong to one message; a child can arrive before its parent | 3 |
| Framework integrations | Support the frameworks pilot customers actually use | SDKs, versioned recipes, test applications | Supported versions pass normal, streaming, parallel, retry, and error fixtures | 4 |
| Failure classification | Detect frustration, corrections, repetition, and observed errors | Evidence references, versioned rules/classifiers | Every displayed finding links to recorded evidence; precision is measured | 5 |
| Intent discovery | Find what customers are trying to accomplish | Embeddings, segmentation, customer definitions | Human-reviewed labeled examples meet the agreed quality benchmark | 6 |
| Semantic clustering | Group recurring issues and track changes | Discovery output, clustering workers, memberships | Cluster quality, stability, and affected-user counts pass a reviewed dataset | 6 |
| Dashboard analytics | Compare trends, segments, versions, and affected users | Analytics query store, rules, filters | Filters reconcile to underlying records and do not mix organizations | 7 |
| Alerts and summaries | Receive actionable findings in selected channels | Delivery records, integrations, deduplication | A qualifying finding sends once; a failed delivery can retry safely | 8 |
| Hosted MCP | Let an authorized coding agent investigate evidence | Scoped authentication, query tools, audit | Tools obey project permissions and return bounded evidence | 9 |
| Evaluations | Compare a candidate agent to a baseline | Versioned datasets, isolated runner, scoring | Same dataset produces a reviewable comparison with reproducible artifacts | 10 |
| Improvements | Propose and approve a prompt/code change | Evidence, evaluation results, repository connectors | No deployment occurs before approval; rollback restores the prior version | 11 |
| Outcome measurement | Link an approved change to real follow-up results | Deployments, agent versions, attribution | Before/after reports use comparable populations and recorded versions | 11 |
| Billing and usage | Explain consumption, limits, and invoices | Idempotent usage records, payment integration | Retried telemetry is charged once; limits and invoices reconcile | 12 |
| Administration | Manage retention, access, operational health, and audit | Tenant roles, audit records, recovery procedures | Privileged changes are attributable; backup/restore and incident drills pass | 12 |

## Phase boundaries

Phase 1 defines the contracts, relationships, and acceptance fixtures. The repository also contains a dashboard/SDK prototype to make the foundation reviewable. Phase 2 turns ownership, credential management, and ingestion into durable services. The existing deterministic signal groups are a preview, not completion of semantic analysis, evaluations, alerts, or improvement workflows.
