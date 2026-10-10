"""Phase 7 alert worker: evaluate enabled rules, send due deliveries.

Ack-style safety: evaluation only queues deliveries; sending is idempotent
per dedup key and bounded per attempt. Killing this worker loses nothing.
Inside the API image, run `python -m app.jobs alerts` instead.

Usage:
    python workers/alert.py [--once] [--project ID] [--interval 60]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from app.jobs import main, run_alerts_once  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main(["alerts", *sys.argv[1:]]))
