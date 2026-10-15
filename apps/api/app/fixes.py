"""Fix a problem group the way Agnost does: suggest a prompt change written from
the real failing conversations, replay those conversations with the change,
then approve it and measure the problem's rate afterwards.

Claude writes the fix from the evidence. To replay, Claude plays the agent for
the turn that failed, with the new instructions and the tool results recorded
in that turn (it can't reach the customer's systems, so tools return exactly
what they returned before). A separate call then judges whether the new turn
still shows the failure. A few healthy conversations are replayed too, so a fix
that makes good turns worse is caught before approval.

Without a model key, the fix falls back to the rule's template and replay is
unavailable.
"""
from concurrent.futures import ThreadPoolExecutor
import json

from . import improve as improve_mod
from .analysis import tool_input, utc
from .llm import LLMError

PROMPT_PATH = "prompts/system.md"
MAX_FAILING = 8
MAX_CONTROLS = 4

FIX_TOOL = {
    "name": "propose_fix",
    "description": "The smallest change to the agent's instructions that would prevent this failure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What the fix does, as an imperative, at most 80 characters."},
            "cause": {"type": "string", "description": "Why the agent fails, in one or two plain sentences, based on the conversations."},
            "instructions": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5,
                             "description": "Lines to add to the agent's system prompt. Concrete, testable, in the second person."},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "caveat": {"type": "string", "description": "What could make this fix wrong or insufficient."},
        },
        "required": ["title", "cause", "instructions", "confidence", "caveat"],
    },
}

TURN_TOOL = {
    "name": "agent_turn",
    "description": "The agent's turn: the tools it calls, then its reply to the user.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "arguments": {"type": "string"}}, "required": ["name", "arguments"]}},
            "reply": {"type": "string"},
        },
        "required": ["tool_calls", "reply"],
    },
}

JUDGE_TOOL = {
    "name": "judge_turn",
    "description": "Whether the replayed turn still shows the failure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["fixed", "still_failing", "unclear"]},
            "reason": {"type": "string", "description": "One sentence citing what the new turn does."},
        },
        "required": ["verdict", "reason"],
    },
}

CONTROL_TOOL = {
    "name": "compare_turns",
    "description": "Whether the replayed turn is worse than the original for the user.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["same_or_better", "worse"]},
            "reason": {"type": "string", "description": "One sentence comparing the two turns."},
        },
        "required": ["verdict", "reason"],
    },
}


def line(event, limit=600):
    """One event as a transcript line."""
    text = " ".join((event.content or "").split())[:limit]
    if event.role == "tool":
        status = f" [{event.status}]" if event.status and event.status != "success" else ""
        return f"Tool {event.name or 'tool'}({tool_input(event)[:300]}){status} → {text}"
    return f"{'User' if event.role == 'user' else 'Agent'}: {text}"


def transcript(events, limit=6000):
    text = "\n".join(line(event) for event in events)
    return text if len(text) <= limit else "…\n" + text[-limit:]


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


def draft(llm, cluster, examples):
    """A fix for a problem group, from Claude when it's available, else the rule's template.
    `examples` are (transcript, reason) pairs from the failing conversations."""
    if llm is not None and examples:
        prompt = (f"Problem: {cluster['title']}\nKind: {cluster['kind']}\nWhat it means: {cluster.get('description', '')}\n"
                  f"Conversations affected: {cluster.get('count', len(examples))}\n\n"
                  + "\n\n".join(f"Conversation {n}\nFlagged because: {reason}\n{text}"
                                for n, (text, reason) in enumerate(examples, 1)))
        try:
            fix = llm.tool_call(system=(
                "You review failures in a customer's AI agent, recorded by Tervik. Write the smallest change to the "
                "agent's instructions that would prevent this failure, based only on the conversations shown. "
                "Don't restate the agent's whole prompt, and don't invent tools or data it doesn't have."),
                prompt=prompt, tool=FIX_TOOL, max_tokens=2000)
            lines = [str(item).strip() for item in fix.get("instructions") or [] if str(item).strip()][:5]
            if lines:
                return {"title": str(fix.get("title") or cluster["title"])[:200], "cause": str(fix.get("cause") or ""),
                        "instructions": lines, "confidence": fix.get("confidence") if fix.get("confidence") in ("low", "medium", "high") else "medium",
                        "caveat": str(fix.get("caveat") or ""), "source": "claude", "model": getattr(llm, "model", None)}
        except LLMError:
            pass
    template = improve_mod.suggest(cluster["kind"], cluster.get("tool_name") or None)
    return {"title": template["title"], "cause": template["cause"], "instructions": template["prompt_content"].split("\n"),
            "confidence": "low", "caveat": template["uncertainty"], "source": "template", "model": None}


def diff(instructions):
    """The fix as a prompt diff the improvement lifecycle understands."""
    return f"*** path: {PROMPT_PATH}\n" + "".join(f"+ {item}\n" for item in instructions)


def simulate(llm, fix, case):
    """Claude plays the agent for the turn, with the fix added and only the recorded tool results."""
    recorded = [event for event in case["turn"] if event.role == "tool"]
    tools = "\n".join(f"- {event.name or 'tool'}({tool_input(event)[:300]}) returned [{event.status or 'success'}]: "
                      f"{' '.join((event.content or '').split())[:500]}" for event in recorded) or "(no tools were called in this turn)"
    return llm.tool_call(system=(
        "You are the AI agent in the conversation below, replaying one turn. You don't have the agent's full "
        "instructions: infer its role from the conversation, and follow these new instructions as well:\n"
        + "\n".join(f"- {item}" for item in fix["instructions"]) +
        "\nTools return exactly the recorded results listed; you can't call any other tool or invent results."),
        prompt=(f"Conversation so far:\n{transcript(case['history']) or '(this is the first message)'}\n\n"
                f"New user message:\nUser: {case['user'].content}\n\nRecorded tool results available in this turn:\n{tools}\n\n"
                "Write the agent's turn."), tool=TURN_TOOL, max_tokens=1500)


def render(turn):
    calls = "\n".join(f"Tool {call.get('name')}({call.get('arguments', '')})" for call in turn.get("tool_calls") or [])
    return (calls + "\n" if calls else "") + f"Agent: {turn.get('reply', '')}"


def replay_failing(llm, fix, case, kind, reason):
    turn = simulate(llm, fix, case)
    after = f"\nWhat the user said next, originally:\nUser: {case['next'].content}" if case["next"] is not None else ""
    judged = llm.tool_call(system=(
        "You judge whether a replayed AI agent turn still shows a failure that Tervik flagged in the original. "
        "Judge only the new turn against the failure described; don't reward style."),
        prompt=(f"Failure: {kind}. Flagged because: {reason}\n\nUser message:\nUser: {case['user'].content}\n\n"
                f"Original turn:\n{transcript(case['turn'], 3000) or '(no reply)'}{after}\n\nReplayed turn with the fix:\n{render(turn)}"),
        tool=JUDGE_TOOL, max_tokens=800)
    verdict = judged.get("verdict") if judged.get("verdict") in ("fixed", "still_failing", "unclear") else "unclear"
    return verdict, str(judged.get("reason") or ""), turn


def replay_control(llm, fix, case):
    turn = simulate(llm, fix, case)
    judged = llm.tool_call(system=(
        "You compare an AI agent's original turn with the same turn replayed under new instructions. Say whether "
        "the replayed turn is worse for the user: less accurate, less helpful, or taking an action they didn't ask for."),
        prompt=(f"User message:\nUser: {case['user'].content}\n\nOriginal turn:\n{transcript(case['turn'], 3000) or '(no reply)'}"
                f"\n\nReplayed turn:\n{render(turn)}"), tool=CONTROL_TOOL, max_tokens=800)
    verdict = "worse" if judged.get("verdict") == "worse" else "same_or_better"
    return verdict, str(judged.get("reason") or ""), turn


def replay(llm, fix, failing, controls):
    """Replay the failing cases and the healthy controls, in parallel.
    `failing` items are (case, kind, reason); `controls` items are cases."""
    def run_failing(item):
        case, kind, reason = item
        try:
            verdict, why, turn = replay_failing(llm, fix, case, kind, reason)
        except LLMError as error:
            verdict, why, turn = "unclear", f"The replay didn't finish ({error.code}).", {}
        return {"conversation_id": case["user"].conversation_id, "group": "failing", "verdict": verdict, "reason": why,
                "user": case["user"].content[:400], "original": transcript(case["turn"], 1200), "replayed": render(turn) if turn else ""}

    def run_control(case):
        try:
            verdict, why, turn = replay_control(llm, fix, case)
        except LLMError as error:
            verdict, why, turn = "unclear", f"The replay didn't finish ({error.code}).", {}
        return {"conversation_id": case["user"].conversation_id, "group": "control", "verdict": verdict, "reason": why,
                "user": case["user"].content[:400], "original": transcript(case["turn"], 1200), "replayed": render(turn) if turn else ""}

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run_failing, failing)) + list(pool.map(run_control, controls))
    failing_rows = [row for row in results if row["group"] == "failing"]
    control_rows = [row for row in results if row["group"] == "control"]
    return {
        "results": results,
        "summary": {
            "failing": len(failing_rows),
            "fixed": sum(row["verdict"] == "fixed" for row in failing_rows),
            "still_failing": sum(row["verdict"] == "still_failing" for row in failing_rows),
            "unclear": sum(row["verdict"] == "unclear" for row in results),
            "controls": len(control_rows),
            "worse": sum(row["verdict"] == "worse" for row in control_rows),
            "model": getattr(llm, "model", None),
        },
    }


def coding_agent_prompt(fix, title):
    """What to paste into Claude Code, Codex, or Cursor to apply an approved fix."""
    return ("Use the tervik skill to apply a fix to the agent in this workspace. Tervik found this problem: "
            f"{title}. Why it happens: {fix.get('cause', '')} Add these instructions to the agent's system prompt, "
            "keeping its existing instructions:\n" + "\n".join(f"- {item}" for item in fix.get("instructions", [])) +
            "\nDon't change the Tervik instrumentation. Then run the agent and send a message like one that used to "
            "trigger the problem, to check the fix.")


def dumps(value):
    return json.loads(json.dumps(value, default=str))
