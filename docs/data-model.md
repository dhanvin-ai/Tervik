# Canonical data model

The [Phase 1 gate](../plan.md) requires multi-turn conversations, nested tools, late arrivals, and evidence-backed findings. The event schema in `schemas/events-v2.schema.json` and fixture in `tests/fixtures/phase-1-gate.json` make this requirement executable. These are the canonical design contract; transport adapters may accept a smaller SDK shape and add server-owned fields during normalization.

## Ownership and identity

An organization owns projects. Each project owns environments, telemetry, analysis definitions, and workflow records. Authenticated membership determines read/write permissions. An ingest credential selects its organization, project, and environment on the server; untrusted client attributes never override ownership.

Event identity is `(organization_id, project_id, event_id)`. Message, trace, span, finding, and conversation IDs are additionally scoped to their project. Customer source identifiers are retained; internal identifiers can be derived deterministically to avoid collisions across projects. The same event ID with the same payload is a retry. Reusing an ID for a different event is an application error, not a second event.

Every canonical event carries `schema_version`, `event_id`, organization/project/environment scope, `source_timestamp`, and `ingested_at`. Source time places an interaction in its timeline. Ingestion time records arrival and drives queue delay diagnostics. Never replace source time with arrival time when a delayed event appears.

## Entities and relationships

| Entity | Key and relationships | Important fields and rules |
|---|---|---|
| Organization | `id`; owns projects and memberships | Name, creation time; tenant root |
| Account | `id`; memberships and sessions | Normalized email, salted password hash; no plaintext password |
| Membership | `(organization_id, account_id)` | Owner/admin/member/viewer role; mutations require the appropriate role |
| Project | `id`, `organization_id` | Name, settings, capture policy, retention days; no globally visible project list |
| Environment | `id`, `project_id` | Name and creation time; project-local unique name |
| Ingest credential | `id`, project/environment scope | Secret hash, display prefix, created/revoked times; returned once |
| End user | Project-scoped customer user ID | Optional redacted attributes; distinct from dashboard account |
| Agent version | `id`, `project_id` | Version label, deployment/build identity, configuration digest |
| Conversation | Project-scoped source ID | End user, environment, first/last source times; grows with late arrivals |
| Message | `id`, `conversation_id` | Role, content/content reference, source time, agent version; represents communication |
| Trace | Project-scoped `trace_id` | Conversation, environment, source start/end; technical execution |
| Span | `(project_id, trace_id, span_id)` | Parent span ID, optional message ID, operation kind/name, timing, status, attributes |
| Tool execution | Span reference | Tool name, redacted input/output or payload references, error/status |
| Outcome signal | `id`, conversation/message/span references | Explicit rating/result, source type, source time; inferred abandonment is not an observed outcome |
| Intent definition | `id`, `project_id` | Name, examples, version, enabled flag |
| Behavior rule | `id`, `project_id` | Versioned definition, scope, thresholds; customer-owned configuration |
| Finding | `id`, `project_id` | Category, confidence, detector version, status, source window; requires evidence |
| Evidence reference | `(finding_id, record_kind, record_id)` | References a retained message, span, or outcome; includes reason and scope |
| Cluster | `id`, `project_id` | Label, algorithm/version, lifecycle/status, source window |
| Cluster membership | `(cluster_id, finding_id)` | Score, assigned time; retain revisions for comparisons |
| Alert | `id`, `project_id` | Rule/cluster condition, channel, cadence, enabled flag |
| Delivery | `id`, `alert_id` | Deduplication key, attempts, state, safe error code, sent time |
| Evaluation dataset | `id`, `project_id` | Version, source references, expected outcomes, capture/redaction policy |
| Evaluation run | `id`, dataset/version references | Baseline/candidate versions, scores, state, artifact references |
| Improvement | `id`, `project_id` | Evidence/evaluation references, proposed patch, approval, state |
| Deployment | `id`, improvement/version references | Approved actor, target, rollout/rollback state, source time |
| Usage record | Unique project/event identity | Accepted bytes/events, processed time; retries cannot increase usage |
| Audit record | `id`, organization/account references | Action, resource identity, safe metadata, timestamp; secrets excluded |
| Ingestion job | Unique project/event identity | Versioned normalized payload, state, retry count/time, lease, safe error code |
| Payload object | Deterministic scoped key | Content digest, size, content type, retention deadline; no public URL |

## Messages and spans stay separate

A user message can trigger one agent turn, several model calls, and several nested tools. Messages therefore have a one-to-many relationship with spans. A tool span can also exist without a captured message when content capture is disabled. Recording a technical operation does not fabricate another user or assistant message.

Span parentage uses `(project_id, trace_id, parent_span_id)`. Parent references are allowed to be unresolved temporarily: child spans commonly arrive first. Read queries reconstruct the tree without rejecting or discarding those children. Cycles, inconsistent trace scope, and duplicate operation IDs are diagnosable errors.

## Storage and lifecycle

PostgreSQL holds account/configuration records, queue acceptance, operational state, and idempotency/usage records. ClickHouse stores analytics telemetry. S3-compatible storage holds large redacted payloads and later evaluation artifacts. A development SQL projection supports the initial investigation UI; the architecture document identifies any remaining production-scale query work explicitly.

Acknowledgement follows a durable acceptance commit. Normalization writes each logical record idempotently. Retried external writes must use a stable record/object key, and analytics queries must count logical event IDs rather than physical duplicate rows. Workers acknowledge transport delivery only after required sinks commit. A bounded failure becomes replayable work, not a lost event.

Capture/redaction is applied before persisted queue or sink writes. Retention uses source timestamps and deletes SQL projections, ClickHouse logical records, and associated payload objects; operational/audit metadata follows its own policy. A late event already outside retention is counted as expired rather than resurrecting deleted content.

## Evolution

Schema version `2` is immutable once published. Additive optional attributes can remain in `2`; a changed meaning or required field requires a new version and explicit adapter. Database changes use additive migrations and preserve existing records. Phase 1 legacy projects are isolated from newly created customer organizations. Future entities in the table above are specified now and implemented only in their assigned phase.
