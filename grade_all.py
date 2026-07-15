#!/usr/bin/env python3
"""Grades every student from already-collected data (data/<slug>/*.json,
written by collect.py) against the private answer key (answers.json). Pure
Python, no Telegram calls - freely re-runnable any time (e.g. after
tweaking a tolerance) without waiting on any bot again.

Usage: python3 grade_all.py --csv students.csv
"""
import argparse
import csv
import json
import re
from pathlib import Path

from grading import grade


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def grade_student(email, questions, answer_specs, data_dir):
    rows = []
    for q in questions:
        path = Path(data_dir) / slugify(email) / f"{q['id']}.json"
        if not path.exists():
            rows.append({"question_id": q["id"], "status": "not_attempted", "correct": False})
            continue

        collected = json.loads(path.read_text())
        spec = answer_specs.get(q["id"])
        if spec is None:
            rows.append({"question_id": q["id"], "status": collected.get("_status"),
                         "correct": None, "detail": "no answer key for this question"})
            continue

        correct, detail = grade(collected, spec)
        rows.append({"question_id": q["id"], "status": collected.get("_status"),
                     "correct": correct, "detail": detail})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--answers", default="answers.json")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    questions = json.load(open(args.questions))
    answer_specs = {a["id"]: a for a in json.load(open(args.answers))}

    for row in csv.DictReader(open(args.csv, newline="")):
        email = row["email"]
        rows = grade_student(email, questions, answer_specs, args.data_dir)
        out_path = Path(args.data_dir) / slugify(email) / "grade.json"
        out_path.write_text(json.dumps(rows, indent=2))
        n_correct = sum(1 for r in rows if r["correct"] is True)
        print(f"[{email}] {n_correct}/{len(rows)} correct -> {out_path}")


if __name__ == "__main__":
    main()
