"""Phase 10 hosted MCP server: JSON-RPC interface for authorized coding agents.

Transport: Streamable-HTTP-style JSON-RPC 2.0 on POST /mcp. Auth is a
dashboard session token (OAuth provider plugs in later); every tool call
is organization-scoped and audited. This is capability (b): exposing the
platform. Instrumenting a customer's own MCP server (capability a) is a
skill recipe that wraps its tool handlers with the SDK.
"""
import json

MCP_VERSION = "10.0.0"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "tervik", "version": MCP_VERSION}

ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_UNAUTHORIZED = -32001
ERROR_FORBIDDEN = -32003
ERROR_NOT_FOUND = -32004


def envelope(request_id):
    return {"jsonrpc": "2.0", "id": request_id}


def result(request_id, data):
    return {**envelope(request_id), "result": data}


def error(request_id, code, message):
    return {**envelope(request_id), "error": {"code": code, "message": message}}


def text_result(request_id, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)[:20000]
    return result(request_id, {"content": [{"type": "text", "text": text}]})


TOOLS = [
    {"name": "tervik_list_conversations",
     "description": "List conversation summaries for a project. Scoped to the caller's organizations.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"},
                                    "range": {"type": "string", "enum": ["24h", "7d", "30d"]},
                                    "search": {"type": "string"}, "flagged_only": {"type": "boolean"}},
                     "required": ["project_id"]}},
    {"name": "tervik_get_conversation",
     "description": "Read one conversation with messages, signals, and spans.",
     "inputSchema": {"type": "object",
                     "properties": {"conversation_id": {"type": "string"}},
                     "required": ["conversation_id"]}},
    {"name": "tervik_list_clusters",
     "description": "List failure clusters with evidence counts for a project.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"},
                                    "range": {"type": "string", "enum": ["24h", "7d", "30d"]},
                                    "status": {"type": "string", "enum": ["open", "resolved"]}},
                     "required": ["project_id"]}},
    {"name": "tervik_get_cluster",
     "description": "Read one cluster with its evidence and suggested next step.",
     "inputSchema": {"type": "object",
                     "properties": {"cluster_id": {"type": "string"},
                                    "range": {"type": "string", "enum": ["24h", "7d", "30d"]}},
                     "required": ["cluster_id"]}},
    {"name": "tervik_list_intents",
     "description": "List configured intents for a project.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}},
                     "required": ["project_id"]}},
    {"name": "tervik_get_improvement",
     "description": "Read an improvement with lifecycle state, diff, and measurements.",
     "inputSchema": {"type": "object",
                     "properties": {"improvement_id": {"type": "string"}},
                     "required": ["improvement_id"]}},
    {"name": "tervik_summary",
     "description": "Calls, conversations, active users, success rate, latency, and the timeline for a project.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]}},
                     "required": ["project_id"]}},
    {"name": "tervik_tool_stats",
     "description": "Per-tool call volume, success rate, latency percentiles, and the most common errors.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]}},
                     "required": ["project_id"]}},
    {"name": "tervik_list_errors",
     "description": "Recent failed operations (agent turns and tool calls) with grouped error messages.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]},
                                    "name": {"type": "string", "description": "Only this tool or agent."}},
                     "required": ["project_id"]}},
    {"name": "tervik_intent_stats",
     "description": "How often each intent appears, plus suggested intents that nothing configured covers.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]}},
                     "required": ["project_id"]}},
    {"name": "tervik_list_violations",
     "description": "Policy violations per policy, with rates over analyzed conversations.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]}},
                     "required": ["project_id"]}},
    {"name": "tervik_search",
     "description": "Find messages containing text across a project's conversations.",
     "inputSchema": {"type": "object",
                     "properties": {"project_id": {"type": "string"}, "query": {"type": "string"},
                                    "range": {"type": "string", "enum": ["1h", "24h", "7d", "30d", "90d", "all"]}},
                     "required": ["project_id", "query"]}},
    {"name": "tervik_ops_summary",
     "description": "Queue backlog, delivery rates, and analysis coverage for the caller's scope.",
     "inputSchema": {"type": "object", "properties": {}}},
]
