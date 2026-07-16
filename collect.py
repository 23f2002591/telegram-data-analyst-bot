#!/usr/bin/env python3
"""Sends eval questions (evals/questions.json) to student Telegram bots and
records each student's answer, one file per (student, question), under
data/<slug>/<question_id>.json.

Processes ONE QUESTION AT A TIME across the whole class ("question-major"),
not one student's whole question set at a time - for large classes this can
take days, and question-major means no student sees question 2's content
before every student has had their turn at question 1, bounding leakage
across the class.

Within a question, students are processed concurrently (bounded by
--concurrency, throttled by --stagger-seconds between conversation starts)
so wall-clock time isn't students x timeout - safer under Telegram's
anti-spam heuristics because new first-contacts trickle in rather than
burstinge.

Fully resumable at any scale: an already-written
data/<slug>/<question_id>.json means that (student, question) is done and
is skipped on re-run, after any crash or FloodWait.

Usage:
    python collect.py --students students.csv
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  

from telethon import TelegramClient
from telethon.errors import (FloodWaitError, PeerFloodError,
                              UsernameInvalidError, UsernameNotOccupiedError)
from telethon.sessions import StringSession

def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def render(text, vars_):
    """Substitute {{name}} placeholders with this student's vars (as JSON
    literals). A leftover {{...}} means a question/vars mismatch - fail loudly
    here, before anything is sent to a bot."""
    for name, value in vars_.items():
        text = text.replace("{{" + name + "}}", json.dumps(value))
    if "{{" in text:
        raise SystemExit(f"unrendered placeholder in message: {text!r}")
    return text


def result_path(data_dir, email, question_id):
    d = Path(data_dir) / slugify(email)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{question_id}.json"


def write_result_atomic(path, result):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.rename(path)


async def run_one(client, row, question, vars_, data_dir, sem):
    email = row["email"]
    out_path = result_path(data_dir, email, question["id"])
    if out_path.exists():
        return  # already resolved (answered/timeout/error) - skip on resume

    messages = [render(t, vars_) for t in question["messages"]]  # raises before any send if a placeholder is unfilled
    sent, replies, status = [], [], "ok"
    async with sem:
        try:
            async with client.conversation(row["telegram_bot_username"],
                                           timeout=question.get("timeout_seconds", 300)) as conv:
                for msg in messages:
                    await conv.send_message(msg)
                    sent.append(msg)
                    replies.append((await conv.get_response()).raw_text)
        except asyncio.TimeoutError:
            status = "timeout"  # keep partial transcript captured so far
        except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as e:
            write_result_atomic(out_path, {"status": "error", "vars": vars_, "error": str(e)})
            return
        except FloodWaitError as e:
            print(f"[{email}] {question['id']}: FloodWait {e.seconds}s, deferring to next run")
            await asyncio.sleep(e.seconds + 1)
            return  # leave unwritten so a re-run retries this one
        # PeerFloodError propagates to run_question_wave, which aborts the run.

    write_result_atomic(out_path, {"status": status, "vars": vars_, "sent": sent, "replies": replies})
    print(f"[{email}] {question['id']}: {status} ({len(replies)} replies)")


async def run_question_wave(client, students, question, inputs_q, data_dir, concurrency, stagger_seconds):
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    for row in students:
        tasks.append(asyncio.create_task(
            run_one(client, row, question, inputs_q[row["email"]], data_dir, sem)))
        await asyncio.sleep(stagger_seconds)  # throttles how fast new bots get first-contacted

    for coro in asyncio.as_completed(tasks):
        try:
            await coro
        except PeerFloodError:
            for t in tasks:
                t.cancel()
            print("FATAL: Telegram has flagged this account as spammy (PeerFloodError) - not a "
                  "timed wait. Verify via @SpamBot in the Telegram app, then re-run this command; "
                  "already-answered students are unaffected.")
            sys.exit(2)


async def main_async(students, questions, inputs, data_dir, concurrency, stagger_seconds):
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    client = TelegramClient(StringSession(os.environ["TELEGRAM_SESSION_STRING"]), api_id, api_hash)
    async with client:
        for question in questions:  # question-major: everyone finishes Q_n before Q_n+1 starts
            print(f"=== question '{question['id']}': {len(students)} students ===")
            await run_question_wave(client, students, question, inputs[question["id"]],
                                    data_dir, concurrency, stagger_seconds)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--students", required=True, help="roster CSV: email,github_url,telegram_bot_username")
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--inputs", default="inputs.json", help="from generate.py; run it first")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--concurrency", type=int, default=5, help="max simultaneous bot conversations")
    ap.add_argument("--stagger-seconds", type=float, default=2.0,
                     help="min delay between starting new conversations")
    args = ap.parse_args()

    students = list(csv.DictReader(open(args.students, newline="")))
    questions = json.load(open(args.questions))
    inputs = json.load(open(args.inputs))
    asyncio.run(main_async(students, questions, inputs, args.data_dir, args.concurrency, args.stagger_seconds))


if __name__ == "__main__":
    main()
