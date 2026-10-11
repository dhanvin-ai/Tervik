"""Build a reproducible, self-contained download from the actual integration skill."""

from hashlib import sha256
from pathlib import Path
import re
import zipfile

root = Path(__file__).resolve().parents[1]
source = root / "skills" / "tervik"
target = root / "apps" / "web" / "public" / "tervik-skill.zip"
if not (source / "SKILL.md").exists():
    raise SystemExit("The Tervik skill must exist before building its download.")


def portable_python_client():
    """One standard-library file with the Python SDK's exporter and its
    interaction API, so a customer project can copy it without installing."""
    sdk = root / "packages" / "sdk-python" / "src" / "tervik"
    client = (sdk / "client.py").read_text().replace('CLIENT_NAME = "tervik"', 'CLIENT_NAME = "tervik-python"', 1)
    interactions = (sdk / "interactions.py").read_text()
    body = interactions.split('"""', 2)[2]  # drop the module docstring
    body = re.sub(r"^from \.client import [^\n]+\n", "", body, count=1, flags=re.M)
    header = ("# Generated from packages/sdk-python by scripts/bundle_skill.py. Edit those files instead.\n")
    return header + client.rstrip() + "\n\n\n# ---- Interaction tracking ----\n" + body.lstrip("\n")


(source / "scripts" / "tervik_client.py").write_text(portable_python_client())
target.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        member = zipfile.ZipInfo("tervik/" + path.relative_to(source).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        member.external_attr = 0o100644 << 16
        archive.writestr(member, path.read_bytes())
digest = sha256(target.read_bytes()).hexdigest()
target.with_suffix(".zip.sha256").write_text(digest + "  tervik-skill.zip\n")
print(f"Bundled Tervik skill ({target.stat().st_size:,} bytes).")
