"""Classification worker: review new and changed conversations on a schedule.

Each pass classifies up to --batch conversations per project from the last
--range. Conversations already classified with the current intents and
policies are skipped. Without ANTHROPIC_API_KEY it uses example matching for
intents only. Inside the API image, run `python -m app.jobs classify` instead.

Usage:
    python workers/classify.py [--once] [--project ID] [--range 7d] [--batch 20] [--interval 300]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from app.jobs import main, run_classification_once  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main(["classify", *sys.argv[1:]]))
