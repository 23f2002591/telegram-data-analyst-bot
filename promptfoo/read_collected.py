#!/usr/bin/env python3
"""promptfoo exec provider: reads an already-collected answer from
data/<slug>/<question_id>.json (written by collect.py) and prints it. No
Telegram calls here - grading can be re-run freely, any time, without
re-contacting any bot. Same script for every question, forever; adding a
new question never touches this file.

    exec: python promptfoo/read_collected.py maternal_mortality_state
promptfoo appends <prompt> <options_json> <context_json>, all ignored here -
STUDENT_EMAIL/DATA_DIR come from env vars set per-student by grade_all.py.
"""
import json
import os
import re
import sys
from pathlib import Path


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def main():
    question_id = sys.argv[1]
    email = os.environ["STUDENT_EMAIL"]
    data_dir = os.environ.get("DATA_DIR", "data")
    path = Path(data_dir) / slugify(email) / f"{question_id}.json"
    if not path.exists():
        print(json.dumps({"_status": "not_attempted"}))
        return
    print(path.read_text())


if __name__ == "__main__":
    main()
