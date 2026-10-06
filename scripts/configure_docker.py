"""Create local container credentials without committing or printing them."""

from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env.docker"
if target.exists():
    raise SystemExit(".env.docker already exists; existing credentials were preserved.")
payload = "\n".join([
    "# Local container environment. This file is ignored by Git.",
    "POSTGRES_PASSWORD=" + secrets.token_hex(24),
    "CLICKHOUSE_PASSWORD=" + secrets.token_hex(24),
    "TERVIK_ADMIN_TOKEN=" + secrets.token_hex(32),
    "TERVIK_API_PORT=8001",
    "TERVIK_WEB_PORT=4173",
    "TERVIK_DEMO_ENABLED=false",
    "",
])
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w") as handle:
    handle.write(payload)
print("Created .env.docker. Enter its TERVIK_ADMIN_TOKEN in the dashboard's access settings.")
print("Start containers: docker compose --env-file .env.docker up --build -d")
