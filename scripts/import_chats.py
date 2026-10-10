"""Import your OpenAI Codex sessions or ChatGPT history into a running Tervik.

    python3 scripts/import_chats.py codex [--watch] [--classify]
    python3 scripts/import_chats.py chatgpt ~/Downloads/chatgpt-export.zip [--classify]

Codex: reads the session files Codex keeps in ~/.codex/sessions. With
--watch it keeps running and sends each Codex turn as soon as it finishes.

ChatGPT: in ChatGPT open Settings > Data controls > Export data, download the
zip from the email, and pass its path (or the unzipped folder).

Conversations go to a project named "Codex" or "ChatGPT", created on first
use with starter intents and policies. Everything stays in your local Tervik
unless ANTHROPIC_API_KEY is set, in which case classification sends
conversation text to Anthropic.
"""
import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sdk-python" / "src"))

from tervik.importers import Uploader, codex_files, load_chatgpt, parse_chatgpt, parse_codex  # noqa: E402

SEEDS = {
    "codex": {
        "intents": [
            ("Fix a bug", "The user wants something broken to work again.",
             ["fix this error", "the build is failing", "this test fails, fix it", "why is this crashing"]),
            ("Build a feature", "The user wants new functionality added.",
             ["add a page for", "implement this feature", "create a new component", "build the backend for"]),
            ("Change the design", "The user wants the look or layout of an interface changed.",
             ["make the UI look like this", "change the colors", "redesign the landing page", "make it look like the image"]),
            ("Explain or review code", "The user wants to understand or assess existing code.",
             ["go through all the files and tell me", "explain how this works", "review this code"]),
            ("Run, test, or ship", "The user wants the project run, tested, previewed, committed, or deployed.",
             ["give me localhost preview", "how do I test this", "run the tests", "commit and push it"]),
        ],
        "policies": [
            ("Check the work before calling it done", "Before saying a change is finished, the agent runs the relevant "
             "tests, build, or app, or says clearly that it could not."),
            ("Ask before destructive actions", "The agent does not delete files, force-push, or rewrite git history "
             "without the user's explicit approval."),
        ],
    },
    "chatgpt": {
        "intents": [
            ("Write or edit text", "The user wants text drafted, rewritten, or polished.",
             ["write an email", "rewrite this paragraph", "make this sound more professional"]),
            ("Learn about a topic", "The user wants something explained.",
             ["explain this to me", "what is the difference between", "how does this work"]),
            ("Write or debug code", "The user wants code written, fixed, or explained.",
             ["write a python function", "fix this code", "why does this error happen"]),
            ("Plan or brainstorm", "The user wants ideas, options, or a plan.",
             ["give me ideas for", "make a plan for", "help me decide between"]),
            ("Study help", "The user wants help preparing for a test or understanding course material.",
             ["solve this question", "summarize this chapter", "make notes for my exam"]),
        ],
        "policies": [
            ("Admit uncertainty", "When the assistant is not sure, it says so instead of presenting a guess as fact."),
            ("Follow formatting instructions", "The assistant follows the format, length, and style the user asked for."),
        ],
    },
}


def api_call(api, method, path, body=None):
    headers = {"Content-Type": "application/json"}
    if os.getenv("TERVIK_ADMIN_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["TERVIK_ADMIN_TOKEN"]
    request = urllib.request.Request(api + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path} failed with HTTP {error.code}: {error.read().decode()[:300]}")
    except urllib.error.URLError:
        raise SystemExit(f"Cannot reach Tervik at {api}. Start it first with: npm run dev")


def resolve_project(api, source, project_id=None):
    if project_id:
        return project_id, None
    name = {"codex": "Codex", "chatgpt": "ChatGPT"}[source]
    existing = next((p for p in api_call(api, "GET", "/api/projects") if p["name"] == name), None)
    if existing:
        return existing["id"], name
    created = api_call(api, "POST", "/api/projects", {"name": name})
    base = f'/api/projects/{created["id"]}'
    for intent, description, examples in SEEDS[source]["intents"]:
        api_call(api, "POST", f"{base}/intents", {"name": intent, "description": description, "examples": examples})
    for title, description in SEEDS[source]["policies"]:
        api_call(api, "POST", f"{base}/policies", {"title": title, "description": description})
    print(f'Created project "{name}" with {len(SEEDS[source]["intents"])} intents and '
          f'{len(SEEDS[source]["policies"])} policies.')
    return created["id"], name


def classify(api, project_id):
    total, first = 0, True
    while True:
        result = api_call(api, "POST", f"/api/projects/{project_id}/classify", {"range": "90d", "limit": 25})
        if first:
            how = f'an LLM ({result["model"]})' if result["classifier"] == "llm" else \
                "example matching (set ANTHROPIC_API_KEY for an LLM that also checks policies)"
            print(f"Classifying conversations with {how}...")
            first = False
        total += result["analyzed"]
        if result.get("error_code"):
            print(f'  Classification stopped: {result["error_code"]}')
            break
        if not result["pending"] or not result["analyzed"]:
            break
        print(f'  {total} done, {result["pending"]} to go')
    print(f"Classified {total} conversations.")


def report(api, project_id, name):
    summary = api_call(api, "GET", f"/api/projects/{project_id}/summary?range=90d")
    problems = api_call(api, "GET", f"/api/clusters?project_id={project_id}&range=30d")
    rate = f'{summary["success_rate"]}%' if summary["success_rate"] is not None else "n/a"
    print(f'\n{name or project_id}: {summary["total_conversations"]} conversations, {summary["turns"]} turns, '
          f'{summary["tool_calls"]} tool calls, {rate} succeeded (last 90 days).')
    if problems:
        print("Top problems (last 30 days):")
        for row in problems[:6]:
            print(f'  - {row["title"]}: {row["count"]} conversations')
    print(f"\nDashboard: http://127.0.0.1:5173/#overview  (pick \"{name or project_id}\" in the sidebar)")
    print(f"API:       {api}/api/projects/{project_id}/summary?range=30d  (more at {api}/docs)")


def run_codex(args, since_ms):
    files = codex_files(args.codex_home)
    if not files:
        raise SystemExit("No Codex sessions found in ~/.codex/sessions. Use Codex once, or pass --codex-home.")
    if args.dry_run:
        conversations = [c for c in (parse_codex(f, args.user, since_ms) for f in files) if c]
        kinds = Counter("turn" if "parent_id" not in e or not e.get("parent_id") else e["primitive_name"]
                        for c in conversations for e in c.events)
        print(f"{len(files)} files, {len(conversations)} sessions, {kinds.pop('turn', 0)} finished turns, "
              f"{sum(kinds.values())} tool calls: {dict(kinds.most_common(8))}")
        return
    project_id, name = resolve_project(args.api, "codex", args.project)
    uploader, sent, seen = Uploader(args.api, project_id), set(), {}

    def scan():
        new_turns = Counter()
        for path in codex_files(args.codex_home):
            stamp = os.path.getmtime(path)
            if seen.get(path) == stamp:
                continue
            conversation = parse_codex(path, args.user, since_ms)
            seen[path] = stamp
            if conversation is None:
                continue
            done = uploader.send(conversation, skip=sent)
            sent.update(done)
            turns = sum(1 for e in conversation.events if not e.get("parent_id") and e["event_id"] in done)
            if turns:
                new_turns[conversation.session["metadata"]["project"]] += turns
        return new_turns

    print(f"Importing {len(files)} Codex session files...")
    first = scan()
    tools = len(sent) - sum(first.values())
    print(f"Sent {sum(first.values())} turns and {tools} tool calls"
          + (f" ({uploader.rejected} rejected)" if uploader.rejected else "")
          + ". Tervik ignores anything it already has, so re-running is safe.")
    if args.classify:
        classify(args.api, project_id)
    report(args.api, project_id, name)
    if not args.watch:
        return
    print(f"\nWatching for new Codex turns every {args.interval:g}s. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.interval)
            fresh = scan()
            for folder, count in fresh.items():
                print(f"{time.strftime('%H:%M:%S')}  +{count} turn(s) from {folder}")
            if fresh and args.classify:
                classify(args.api, project_id)
    except KeyboardInterrupt:
        print("\nStopped watching.")


def run_chatgpt(args, since_ms):
    try:
        raw = load_chatgpt(args.path)
    except (OSError, ValueError) as error:
        raise SystemExit(f"Could not read the ChatGPT export: {error}")
    conversations = [c for c in (parse_chatgpt(item, args.user, since_ms) for item in raw) if c and c.events]
    turns = sum(1 for c in conversations for e in c.events if not e.get("parent_id"))
    print(f"{len(raw)} conversations in the export; {len(conversations)} updated in the last {args.days} days "
          f"with {turns} turns.")
    if args.dry_run or not conversations:
        return
    project_id, name = resolve_project(args.api, "chatgpt", args.project)
    uploader = Uploader(args.api, project_id)
    for index, conversation in enumerate(conversations, 1):
        uploader.send(conversation)
        if index % 25 == 0:
            print(f"  {index}/{len(conversations)} conversations sent")
    print(f"Sent {turns} turns" + (f" ({uploader.rejected} requests rejected)" if uploader.rejected else "")
          + ". Tervik ignores anything it already has, so re-running is safe.")
    if args.classify:
        classify(args.api, project_id)
    report(args.api, project_id, name)


def main():
    sys.stdout.reconfigure(line_buffering=True)  # show progress promptly, even when piped to a file
    parser = argparse.ArgumentParser(description="Import Codex sessions or ChatGPT history into Tervik")
    sub = parser.add_subparsers(dest="source", required=True)
    for source in ("codex", "chatgpt"):
        command = sub.add_parser(source)
        if source == "chatgpt":
            command.add_argument("path", help="The export .zip, its conversations.json, or the unzipped folder")
        else:
            command.add_argument("--watch", action="store_true", help="Keep sending new turns as they finish")
            command.add_argument("--interval", type=float, default=15.0, help="Seconds between scans with --watch")
            command.add_argument("--codex-home", default=None, help="Codex data folder (default ~/.codex)")
        command.add_argument("--api", default=os.getenv("TERVIK_ENDPOINT", "http://127.0.0.1:8000"))
        command.add_argument("--project", default=None, help="Send to this project ID instead")
        command.add_argument("--user", default=getpass.getuser(), help="The user ID to record (default: your login)")
        command.add_argument("--days", type=int, default=90, help="Only import the last N days (default 90)")
        command.add_argument("--classify", action="store_true", help="Classify intents and policies afterwards")
        command.add_argument("--dry-run", action="store_true", help="Parse and count without sending anything")
    args = parser.parse_args()
    args.api = args.api.rstrip("/")
    since_ms = int((time.time() - args.days * 86400) * 1000)
    (run_codex if args.source == "codex" else run_chatgpt)(args, since_ms)


if __name__ == "__main__":
    main()
