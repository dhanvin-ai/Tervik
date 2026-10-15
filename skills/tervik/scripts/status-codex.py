"""Report whether Tervik's Codex hooks are installed and can reach Tervik, without showing the key."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def status(codex_home):
    try:
        config = json.loads((codex_home / "tervik.json").read_text())
    except (OSError, ValueError):
        config = {}
    try:
        hooks = json.loads((codex_home / "hooks.json").read_text()).get("hooks", {})
    except (OSError, ValueError, AttributeError):
        hooks = {}
    installed = [event for event, groups in hooks.items()
                 if any("tervik/codex-hook.py" in hook.get("command", "") for group in groups for hook in group.get("hooks", []))]
    endpoint = os.environ.get("TERVIK_ENDPOINT") or config.get("endpoint") or "http://127.0.0.1:8000"
    report = {"hooks_installed": sorted(installed), "hook_script": (codex_home / "tervik" / "codex-hook.py").is_file(),
              "key_configured": bool(os.environ.get("TERVIK_API_KEY") or config.get("apiKey")), "endpoint": endpoint}
    try:
        with urlopen(endpoint.rstrip("/") + "/api/health", timeout=60) as response:
            report["health"] = json.load(response).get("status")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        report["health"] = f"unreachable ({getattr(error, 'reason', error)})"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    print(json.dumps(status(parser.parse_args().codex_home), indent=2))
