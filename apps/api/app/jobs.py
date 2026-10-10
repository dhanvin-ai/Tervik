"""Background jobs, runnable inside the API image:

    python -m app.jobs alerts [--once] [--project ID] [--interval 60]
    python -m app.jobs classify [--once] [--project ID] [--range 7d] [--batch 20] [--interval 300]

Alerts evaluate enabled rules and send due deliveries. Classification reviews
new and changed conversations; already-reviewed ones are skipped, so repeated
passes only pay for what changed. Killing either job loses nothing.
"""
import argparse
import time

from sqlalchemy import select

from .alerts import evaluate_rule, process_deliveries
from .classify import run_classification
from .config import Settings
from .db import AlertRule, Project, make_database
from .llm import from_settings

RANGES = ["1h", "24h", "7d", "30d", "90d", "all"]


def run_alerts_once(settings: Settings, project_id: str | None = None) -> dict:
    _, sessions = make_database(settings.database_url)
    fired, evaluated = 0, 0
    with sessions.begin() as session:
        query = select(AlertRule).where(AlertRule.enabled == True)  # noqa: E712
        if project_id:
            query = query.where(AlertRule.project_id == project_id)
        for rule in session.scalars(query):
            done, _ = evaluate_rule(session, rule, settings=settings)
            evaluated += 1
            fired += 1 if done else 0
    with sessions.begin() as session:
        sent, failed = process_deliveries(session, settings)
    return {"evaluated": evaluated, "fired": fired, "sent": sent, "failed": failed}


def run_classification_once(settings: Settings, project_id: str | None = None, range: str = "7d",
                            batch: int = 20) -> dict:
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tervik background jobs")
    parser.add_argument("job", choices=["alerts", "classify"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--range", default="7d", choices=RANGES)
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--interval", type=float, default=None)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.job == "alerts":
        task, interval = (lambda: run_alerts_once(settings, args.project)), args.interval or 60.0
    else:
        task, interval = (lambda: run_classification_once(settings, args.project, args.range, args.batch)), args.interval or 300.0
    if args.once:
        print(task(), flush=True)
        return 0
    while True:
        try:
            task()
        except Exception as error:  # keep polling; the next pass retries
            print(f"{args.job} job error: {type(error).__name__}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
