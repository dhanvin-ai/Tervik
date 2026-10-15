"""Fix a problem group with the coding agent in the customer's own project.

Tervik doesn't write fixes. The fix agent that ships in the Tervik skill
(skills/tervik/agents/tervik-fixer.md) runs inside the customer's project, where
the agent's real code, prompts, and tools are:

1. It downloads the problem's failing turns, and a few healthy ones, from
   GET /api/clusters/{id}/cases.
2. It changes the agent's code or prompt, then replays each of those turns
   through the real agent and judges whether the failure is gone and whether a
   healthy turn got worse.
3. It reports the change and every replay result to POST /api/clusters/{id}/fix.

A person then approves the fix in the dashboard, once it fixes at least one
failing turn and makes no healthy turn worse.
"""
from .analysis import tool_input, utc

MAX_FAILING = 8
MAX_CONTROLS = 4
MAX_HISTORY = 12


def failing_turn(events, flagged):
    """The turn to replay for a flagged event: its history, the user message
    that started it, the agent's events in it, and what the user said next.
    A user-side signal (a correction, frustration) points at the agent turn
    before it. None when the conversation has no user message to replay from."""
    ordered = sorted(events, key=lambda e: (utc(e.timestamp), e.id))
    index = next((i for i, event in enumerate(ordered) if event.id == flagged.id), None)
    if index is None:
        return None
    if flagged.role == "user":
        index = next((i for i in range(index - 1, -1, -1) if ordered[i].role != "user"), None)
        if index is None:
            return None
    start = next((i for i in range(index, -1, -1) if ordered[i].role == "user"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(ordered)) if ordered[i].role == "user"), len(ordered))
    return {"history": ordered[:start], "user": ordered[start], "turn": ordered[start + 1:end],
            "next": ordered[end] if end < len(ordered) else None}


def event_view(event):
    view = {"role": event.role, "content": (event.content or "")[:4000]}
    if event.role == "tool":
        view.update(name=event.name or "tool", input=tool_input(event)[:2000], status=event.status or "success")
    return view


def case_view(case, kind=None, reason=None):
    """One turn as the coding agent replays it: the conversation before it, the
    user's message, what the agent did (its tool calls with their recorded
    results, then its reply), and what the user said next."""
    view = {"conversation_id": case["user"].conversation_id,
            "history": [event_view(event) for event in case["history"][-MAX_HISTORY:]],
            "user": (case["user"].content or "")[:4000],
            "turn": [event_view(event) for event in case["turn"]],
            "next": (case["next"].content or "")[:2000] if case["next"] is not None else None}
    if kind:
        view.update(kind=kind, reason=reason)
    return view


def summarize(results):
    """The replay's counts, from the reported rows rather than the agent's own tally."""
    failing = [row for row in results if row["group"] == "failing"]
    controls = [row for row in results if row["group"] == "control"]
    return {"failing": len(failing),
            "fixed": sum(row["verdict"] == "fixed" for row in failing),
            "still_failing": sum(row["verdict"] == "still_failing" for row in failing),
            "unclear": sum(row["verdict"] == "unclear" for row in results),
            "controls": len(controls),
            "worse": sum(row["verdict"] == "worse" for row in controls)}


def agent_prompt(problem_id, title):
    """What to paste into the coding agent, in the agent's project, to fix a problem."""
    return (f"Use the tervik skill to fix the problem \"{title}\" (problem {problem_id}). Follow the skill's "
            "tervik-fixer agent: download the failing conversations, change my agent's code, replay them through "
            "my agent, and report the fix and the results to Tervik.")
