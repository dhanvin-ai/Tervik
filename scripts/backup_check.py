"""Backup restoration check: snapshot the SQLite database and verify the
restored copy serves identical project/event counts.

Usage: apps/api/.venv/bin/python scripts/backup_check.py [--database PATH]

PostgreSQL deploys: use pg_dump/pg_restore on the same schedule and compare
`SELECT count(*)` per table; the procedure is documented in docs/phase-7.md.
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

TABLES = ["projects", "events", "ingestion_jobs", "usage_records", "alert_rules",
          "alert_deliveries", "behavior_rules", "intents", "semantic_clusters"]


def counts(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = {}
        existing = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TABLES:
            result[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] \
                if table in existing else None
        return result
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Tervik backup restoration check")
    parser.add_argument("--database", default="./.data/tervik.db")
    args = parser.parse_args()
    source = Path(args.database)
    if not source.exists():
        print(f"no database at {source}; nothing to verify")
        return 0
    backup = source.with_suffix(".backup-check.db")
    shutil.copyfile(source, backup)
    try:
        before, after = counts(source), counts(backup)
        assert before == after, (before, after)
        print(f"OK: restored {backup.name} matches ({sum(v or 0 for v in before.values())} rows)")
        return 0
    finally:
        backup.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
