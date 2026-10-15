"""Install Tervik's Codex hooks without placing the ingest key in command arguments."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import uuid

EVENTS = ("UserPromptSubmit", "PostToolUse", "Stop")


def install(codex_home, endpoint=None, api_key=None):
    source = Path(__file__).resolve().parent
    adapter = codex_home / "tervik"
    adapter.mkdir(parents=True, exist_ok=True)
    for name in ("codex-hook.py", "tervik_client.py"):
        shutil.copy2(source / name, adapter / name)

    config_path = codex_home / "tervik.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if endpoint:
        config["endpoint"] = endpoint
    if api_key:
        config["apiKey"] = api_key
    config.setdefault("userId", str(uuid.uuid4()))
    # Restrict permissions before writing, including when updating an existing file.
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        os.fchmod(fd, 0o600)
        output.write(json.dumps(config, indent=2) + "\n")

    # Add the hooks beside any the user already has, once each.
    hooks_path = codex_home / "hooks.json"
    hooks = json.loads(hooks_path.read_text()) if hooks_path.exists() else {}
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(adapter / 'codex-hook.py'))}"
    for event in EVENTS:
        groups = hooks.setdefault("hooks", {}).setdefault(event, [])
        groups[:] = [group for group in groups
                     if not any("tervik/codex-hook.py" in hook.get("command", "") for hook in group.get("hooks", []))]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
    hooks_path.write_text(json.dumps(hooks, indent=2) + "\n")

    print(f"Installed Tervik's Codex hooks in {hooks_path}")
    print(f"Private configuration: {config_path}")
    if not (config.get("apiKey") or os.environ.get("TERVIK_API_KEY")):
        print("Configure the Tervik project key, then run this again. No events are sent without it.")
    print("Restart Codex, then trust the three Tervik hooks when Codex asks (in the CLI: /hooks).")
    print("Only new turns are sent; existing chat history isn't.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    parser.add_argument("--endpoint", default=os.environ.get("TERVIK_ENDPOINT"))
    parser.add_argument("--api-key-env", default="TERVIK_API_KEY", help="Name of the environment variable holding the ingest key; never pass the key itself.")
    args = parser.parse_args()
    install(args.codex_home, args.endpoint, os.environ.get(args.api_key_env))
