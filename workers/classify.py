"""Classification worker: review new and changed conversations on a schedule.

Each pass classifies up to --batch conversations per project from the last
--range. Conversations already classified with the current intents and
policies are skipped, so repeated passes only pay for what changed. Without
ANTHROPIC_API_KEY it uses example matching for intents only.

Usage:
    python workers/classify.py [--once] [--project ID] [--range 7d] [--batch 20]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import select  # noqa: E402

from app.classify import run_classification  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Project, make_database  # noqa: E402
from app.llm import from_settings  # noqa: E402


def run_once(settings: Settings, project_id: str | None = None, range: str = "7d", batch: int = 20) -> dict:
    _, sessions = make_database(settings.database_url)
    llm = from_settings(settings)
    with sessions() as session:
        query = select(Project.id)
        if project_id:
            query = query.where(Project.id == project_id)
        project_ids = list(session.scalars(query))
    totals = {"projects": len(project_ids), "analyzed": 0, "errors": 0, "pending": 0}
    for id in project_ids:
        result = run_classification(sessions, id, llm, range=range, limit=batch)
        for key in ("analyzed", "errors", "pending"):
            totals[key] += result[key]
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description="Tervik classification worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--range", default="7d", choices=["1h", "24h", "7d", "30d", "90d", "all"])
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--interval", type=float, default=300.0)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.once:
        print(run_once(settings, args.project, args.range, args.batch), flush=True)
        return 0
    while True:
        try:
            run_once(settings, args.project, args.range, args.batch)
        except Exception as error:  # keep polling; a later pass retries
            print(f"classify worker error: {type(error).__name__}", flush=True)
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
