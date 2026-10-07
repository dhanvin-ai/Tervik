"""Phase 7 alert worker: evaluate enabled rules, send due deliveries.

Ack-style safety: evaluation only queues deliveries; sending is idempotent
per dedup key and bounded per attempt. Killing this worker loses nothing.

Usage:
    python workers/alert.py [--once] [--project ID]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import select  # noqa: E402

from app.alerts import evaluate_rule, process_deliveries  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import AlertRule, make_database  # noqa: E402


def run_once(settings: Settings, project_id: str | None = None) -> dict:
    engine, sessions = make_database(settings.database_url)
    fired, evaluated = 0, 0
    with sessions.begin() as session:
        query = select(AlertRule).where(AlertRule.enabled == True)  # noqa: E712
        if project_id:
            query = query.where(AlertRule.project_id == project_id)
        for rule in session.scalars(query):
            done, _ = evaluate_rule(session, rule)
            evaluated += 1
            fired += 1 if done else 0
    with sessions.begin() as session:
        sent, failed = process_deliveries(session, settings)
    return {"evaluated": evaluated, "fired": fired, "sent": sent, "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Tervik alert worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.once:
        print(run_once(settings, args.project), flush=True)
        return 0
    while True:
        try:
            run_once(settings, args.project)
        except Exception as error:  # keep polling; rules stay enabled
            print(f"alert worker error: {type(error).__name__}", flush=True)
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
