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
    api_key = (api_key or "").strip()
    if api_key and not api_key.startswith("tvk_"):
        sys.exit("That isn't the project's secret key, which starts with tvk_. Copy it from the dashboard's "
                 "Connect your agent page, step 03, Prefer a secret key? Nothing was changed.")
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
    if api_key:
        print(f"Saved the secret key ({len(api_key)} characters, starts with tvk_). Endpoint: {config.get('endpoint')}")
    elif config.get("apiKey"):
        print("Kept the secret key saved earlier.")
    else:
        sys.exit("No key was given, so nothing will be sent to Tervik. Run this again and paste the key "
                 "(it starts with tvk_) at the prompt.")
    print("Restart Codex, then trust the three Tervik hooks when Codex asks (in the CLI: /hooks).")
    print("Only new turns are sent; existing chat history isn't.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    parser.add_argument("--endpoint", default=os.environ.get("TERVIK_ENDPOINT"))
    parser.add_argument("--api-key-env", default="TERVIK_API_KEY", help="Name of the environment variable holding the ingest key; never pass the key itself.")
    args = parser.parse_args()
    install(args.codex_home, args.endpoint, os.environ.get(args.api_key_env))
