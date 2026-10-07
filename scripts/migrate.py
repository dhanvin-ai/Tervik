"""Migration check: verify all expected tables exist (additive migrations).

Usage: apps/api/.venv/bin/python scripts/migrate.py --check [--database URL]
Exits nonzero with the missing list. Safe to run any time.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import inspect  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import Base, make_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Tervik migration check")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    settings = Settings.from_env()
    url = args.database or settings.database_url
    engine, _ = make_database(url)
    expected = set(Base.metadata.tables)
    existing = set(inspect(engine).get_table_names())
    missing = sorted(expected - existing)
    if missing:
        print(f"missing tables: {missing}")
        return 1
    print(f"OK: {len(expected)} tables present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
