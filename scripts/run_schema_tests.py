from pathlib import Path
import os
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
python = root / 'apps/api/.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if not python.exists():
    raise SystemExit('Run npm run setup:api first.')
raise SystemExit(subprocess.call([str(python), '-m', 'pytest', str(root / 'tests/specification'), '-q'], cwd=root))
