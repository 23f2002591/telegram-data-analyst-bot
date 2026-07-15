#!/usr/bin/env python3
"""Runs promptfoo once per student against already-collected data
(data/<slug>/*.json from collect.py) - no Telegram calls, so this can be
re-run freely any time (e.g. after tweaking a tolerance in promptfoo.yaml)
without waiting on any bot again. Writes each student's graded result to
data/<slug>/grade.json.

Usage: python grade_all.py --csv students.csv
"""
import argparse
import csv
import os
import re
import subprocess
from pathlib import Path


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--config", default="promptfoo/promptfoo.yaml")
    args = ap.parse_args()

    # read_collected.py runs with its cwd set to the config file's own
    # directory (promptfoo/), not wherever this script is invoked from - so
    # DATA_DIR must be absolute, or it'd resolve relative to the wrong place.
    data_dir = Path(args.data_dir).resolve()

    for row in csv.DictReader(open(args.csv, newline="")):
        email = row["email"]
        out_path = data_dir / slugify(email) / "grade.json"
        env = {**os.environ, "STUDENT_EMAIL": email, "DATA_DIR": str(data_dir)}
        subprocess.run(["npx", "promptfoo", "eval", "-c", args.config, "-o", str(out_path)], env=env, check=False)
        print(f"[{email}] graded -> {out_path}")


if __name__ == "__main__":
    main()
