from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
python = root / "apps" / "api" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    raise SystemExit("Run npm run setup:api first.")
code = 0
for suite in ("packages/sdk/test", "packages/sdk-python/tests"):
    code = subprocess.call([str(python), "-m", "unittest", "discover", "-s", suite, "-p", "test_*.py"], cwd=root) or code
sys.exit(code)
