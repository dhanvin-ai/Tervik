# Phase 10: hosted MCP and broader parity

Implements section 13 of the saved roadmap: the authenticated hosted MCP
interface plus the parity close-out across all ten phases.

## Hosted MCP

`POST /mcp` speaks JSON-RPC 2.0 (`initialize`, `tools/list`,
`tools/call`). Authorization is a dashboard session token today; an OAuth
provider plugs into the same seam later. Every project-scoped tool checks
organization membership (unknown ids return not-found across orgs) and
audits the call. Tools are bounded (50 rows, truncated text) and expose
conversations, clusters with evidence, intents, improvements, and an ops
summary — everything a coding agent needs to investigate without
dashboard access. The two capabilities stay distinct: this server exposes
the platform; instrumenting a customer's own MCP server is a skill recipe
(`docs/compatibility.md`) that wraps its tool handlers.

## Broader parity

- Third framework: Anthropic messages (incl. streaming) with fixture
  tests; matrix updated.
- Client versions: every SDK sends `X-Tervik-Client`; `GET /api/compat`
  advertises minimums over the stable events-v2 contract.
- Operations: `docs/runbooks.md` (symptoms, rotation, restore, upgrades),
  `scripts/migrate.py --check` for additive schema verification,
  `docs/parity.md` reviewing every feature-matrix row.
- Deferred with owners: pilot teams (Phase 7 gate), payment provider,
  OAuth, model-embedding recall, voice/Go, public site, repo-PR
  connector, skill-install UX polish.

## Gate

The feature matrix meets the agreed parity target (`docs/parity.md`);
installation, permissions, data lifecycle, and failure recovery are
implemented and tested end to end.
