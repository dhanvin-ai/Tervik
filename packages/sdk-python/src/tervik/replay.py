"""Recorded-tool replay for customer CI: run a real agent function with
isolated fixtures instead of live systems.

The customer fetches cases from the dataset API, wraps their tool layer
with RecordedTools, runs their pinned agent code, and posts results back.
Unrecorded tools raise, so evaluations cannot touch production systems.
"""
import asyncio


class UnrecordedToolError(RuntimeError):
    pass


class RecordedTools:
    """Serve recorded fixture outputs keyed by tool name."""

    def __init__(self, recorded):
        self._recorded = dict(recorded or {})
        self.calls = []

    def __contains__(self, name):
        return name in self._recorded

    def call(self, name, arguments=None):
        self.calls.append({"name": name, "arguments": arguments})
        if name not in self._recorded:
            raise UnrecordedToolError(f"no recorded output for tool {name!r}")
        output = self._recorded[name]
        return output() if callable(output) else output

    async def acall(self, name, arguments=None):
        return self.call(name, arguments)


def run_case_sync(agent, case, recorded):
    """Run a sync agent function `agent(input, tools)` against a case."""
    tools = RecordedTools({t["name"]: t.get("recorded_output", "") for t in case.get("tools", [])})
    return {"response": agent(case["input"], tools), "called": [c["name"] for c in tools.calls]}


async def run_case_async(agent, case, recorded):
    tools = RecordedTools({t["name"]: t.get("recorded_output", "") for t in case.get("tools", [])})
    result = agent(case["input"], tools)
    if asyncio.iscoroutine(result):
        result = await result
    return {"response": result, "called": [c["name"] for c in tools.calls]}
