"""Phase 2 normalization worker.

Polls the durable ingestion outbox and materializes events, usage, and
the ClickHouse mirror. Ack already happened at enqueue time, so killing
this worker never loses acknowledged events -- they stay pending and are
picked up on restart.

Usage:
    python workers/normalize.py [--once] [--project ID]

Set DATABASE_URL, CLICKHOUSE_URL, NATS_URL like the API. NATS is an
optional wake-up transport; the database outbox is the durable core.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from app.config import Settings  # noqa: E402
from app.db import make_database  # noqa: E402
from app import queue as queue_mod  # noqa: E402


def run_once(settings: Settings, project_id: str | None = None) -> int:
    engine, sessions = make_database(settings.database_url)
    with sessions.begin() as session:
        processed = queue_mod.process_pending(session, engine, settings, project_id=project_id)
    with sessions.begin() as session:
        queue_mod.retry_mirrors(session, settings)
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Tervik normalization worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.once:
        return run_once(settings, args.project)
    while True:
        try:
            run_once(settings, args.project)
        except Exception as error:  # keep polling; jobs stay pending
            print(f"worker error: {type(error).__name__}", flush=True)
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
