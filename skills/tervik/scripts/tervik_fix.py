#!/usr/bin/env python3
"""Talk to Tervik while fixing a problem it found (see agents/tervik-fixer.md).

  python tervik_fix.py cases  <problem-id>                 # download the turns to replay
  python tervik_fix.py report <problem-id> <report.json>   # send the fix and replay results
  python tervik_fix.py status <problem-id>                 # the latest fix reported

Reads TERVIK_ENDPOINT (default http://127.0.0.1:8000) and TERVIK_FIX_KEY, a
project API key (it starts with tervik_) from the problem's Fix panel in the
Tervik dashboard. The key reads that project's problems and reports fixes; it
can't approve one. Standard library only.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def call(method, path, body=None):
    key = os.getenv("TERVIK_FIX_KEY", "").strip()
    if not key.startswith("tervik_"):
        sys.exit("Set TERVIK_FIX_KEY to the project API key from the problem's Fix panel in the Tervik dashboard "
                 "(it starts with tervik_). Keep it out of source control.")
    endpoint = os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000").rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(endpoint + path, data=data, method=method, headers={
        "X-API-Key": key, "Accept": "application/json", "User-Agent": "tervik-fixer",
        **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("detail")
        except ValueError:
            detail = None
        hints = {401: "The key was rejected: create a new one in the problem's Fix panel.",
                 403: "This key can't do that.", 404: "No such problem in the key's project. Check the problem ID."}
        sys.exit(f"Tervik answered {error.code}: {detail or hints.get(error.code, 'request failed')}")
    except urllib.error.URLError as error:
        sys.exit(f"Can't reach Tervik at {endpoint} ({error.reason}). Check TERVIK_ENDPOINT.")


def problem_path(problem_id, suffix):
    return f"/api/clusters/{urllib.parse.quote(problem_id, safe='')}/{suffix}"


def cases(problem_id):
    data = call("GET", problem_path(problem_id, "cases"))
    folder = Path(".tervik") / "fix" / problem_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "cases.json"
    target.write_text(json.dumps(data, indent=2))
    problem = data["problem"]
    print(f"Problem: {problem['title']} ({problem['kind']}, {problem.get('count', '?')} conversations)")
    print(f"Saved {len(data['failing'])} failing and {len(data['controls'])} healthy turns to {target}")
    print("These hold real conversations: keep .tervik/ out of version control, and delete it when you're done.")


def report(problem_id, path):
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        sys.exit(f"Can't read the report at {path}: {error}. Write it as agents/tervik-fixer.md step 6 shows.")
    fix = call("POST", problem_path(problem_id, "fix"), body)
    summary = fix["replay"]["summary"]
    print(f"Reported: {fix['title']}")
    print(f"Replay: {summary['fixed']} of {summary['failing']} failing turns fixed, "
          f"{summary['worse']} of {summary['controls']} healthy turns worse, {summary['unclear']} unclear.")
    if fix["state"] == "awaiting_approval":
        print("Ready to approve in the Tervik dashboard: Problems, then this problem's Fix panel.")
    else:
        print("Not ready to approve: it needs at least one failing turn fixed and no healthy turn worse.")


def status(problem_id):
    fix = call("GET", problem_path(problem_id, "fix"))["fix"]
    if fix is None:
        print("No fix reported for this problem yet.")
        return
    summary = (fix.get("replay") or {}).get("summary") or {}
    print(f"{fix['title']}: {fix['state']}. Fixed {summary.get('fixed', 0)} of {summary.get('failing', 0)} "
          f"failing turns; {summary.get('worse', 0)} healthy turns worse.")


if __name__ == "__main__":
    commands = {"cases": (cases, 1), "report": (report, 2), "status": (status, 1)}
    if len(sys.argv) < 2 or sys.argv[1] not in commands or len(sys.argv) != 2 + commands[sys.argv[1]][1]:
        sys.exit(__doc__)
    command, _ = commands[sys.argv[1]]
    command(*sys.argv[2:])
