"""Create an isolated Python environment for the API and install development dependencies."""

from pathlib import Path
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / "apps" / "api" / ".venv"

if sys.version_info < (3, 11):
    raise SystemExit("Tervik needs Python 3.11 or newer.")

venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)
python = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
subprocess.run([str(python), "-m", "pip", "install", "-e", str(ROOT / "apps" / "api") + "[dev]"], check=True)
print("Tervik API environment is ready. Start the product with npm run dev.")
