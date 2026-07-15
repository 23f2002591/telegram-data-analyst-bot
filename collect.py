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
bursting.

Fully resumable at any scale: an already-written
data/<slug>/<question_id>.json means that (student, question) is done and
is skipped on re-run, after any crash or FloodWait.

Usage:
    python collect.py --csv students.csv
"""
import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # load TELEGRAM_API_ID/TELEGRAM_API_HASH/TELEGRAM_SESSION_STRING from .env if present

from telethon import TelegramClient
from telethon.errors import (FloodWaitError, PeerFloodError,
                              UsernameInvalidError, UsernameNotOccupiedError)
from telethon.sessions import StringSession

MARKER = "FINAL_ANSWER:"
SAFE_GLOBALS = {"__builtins__": {}, "math": math, "statistics": statistics,
                "range": range, "round": round, "len": len, "sum": sum, "min": min, "max": max}


def slugify(email):
    return re.sub(r"[^a-zA-Z0-9]+", "_", email.strip().lower()).strip("_")


def extract_json_block(text):
    """Pulls the {...} object following a FINAL_ANSWER: marker out of a
    chatty reply. Brace-counted rather than regex, so it's not confused by
    nested objects or trailing prose."""
    if not text or MARKER not in text:
        return None
    start = text.find("{", text.find(MARKER))
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def generate_vars(question, email):
    """Deterministic per-student values from the tiny code snippets in
    `randomize`, seeded from the student's email - reproducible later
    (e.g. by promptfoo's assertions) without ever being stored separately."""
    recipe = question.get("randomize", {})
    if not recipe:
        return {}
    seed = int(hashlib.sha256(f"{email}:{question['id']}".encode()).hexdigest(), 16) % (2**32)
    scope = dict(SAFE_GLOBALS)
    scope["rng"] = random.Random(seed)
    values = {}
    for name, code in recipe.items():
        values[name] = eval(code, scope, {**scope, **values})
    return values


def render(text, vars_):
    for name, value in vars_.items():
        text = text.replace("{{" + name + "}}", json.dumps(value))
    return text


def result_path(data_dir, email, question_id):
    d = Path(data_dir) / slugify(email)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{question_id}.json"


def write_result_atomic(path, result):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.rename(path)


async def run_one(client, row, question, data_dir, sem):
    email, bot_username = row["email"], row["telegram_bot_username"]
    out_path = result_path(data_dir, email, question["id"])
    if out_path.exists():
        return  # already answered/timed out/permanently failed - skip

    async with sem:
        try:
            entity = await client.get_entity(bot_username)
        except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as e:
            write_result_atomic(out_path, {"_status": "error", "_error": f"cannot resolve bot: {e}"})
            print(f"[{email}] {question['id']}: cannot resolve bot - {e}")
            return
        if not getattr(entity, "bot", False):
            write_result_atomic(out_path, {"_status": "error", "_error": "not a bot account"})
            print(f"[{email}] {question['id']}: '{bot_username}' is not a bot account")
            return

        vars_ = generate_vars(question, email)
        timeout_seconds = question.get("timeout_seconds", 300)
        reply = None
        while True:
            try:
                async with client.conversation(bot_username, timeout=timeout_seconds) as conv:
                    for text in question["messages"]:
                        await conv.send_message(render(text, vars_))
                        try:
                            reply_msg = await conv.get_response(timeout=timeout_seconds)
                            reply = reply_msg.raw_text
                        except asyncio.TimeoutError:
                            reply = None
                            break
                break
            except FloodWaitError as e:
                # Localized, timed wait - safe to sleep and retry this one
                # bot's conversation without affecting anyone else.
                print(f"[{email}] {question['id']}: FloodWait {e.seconds}s, retrying after wait")
                await asyncio.sleep(e.seconds + 1)
            # PeerFloodError propagates up uncaught: it's account-level, not
            # specific to this bot, and is handled by the wave runner (stop
            # everything). Any other unexpected exception also propagates -
            # no file gets written, so this (student, question) is retried
            # on the next run rather than being wrongly marked done.

        if reply is None:
            result = {"_status": "timeout", "_vars": vars_}
        else:
            parsed = extract_json_block(reply)
            result = ({"_status": "format_error", "_raw_reply": reply, "_vars": vars_} if parsed is None
                      else {**parsed, "_status": "answered", "_vars": vars_})

        write_result_atomic(out_path, result)
        print(f"[{email}] {question['id']}: {result['_status']}")


async def run_question_wave(client, students, question, data_dir, concurrency, stagger_seconds):
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    for row in students:
        tasks.append(asyncio.create_task(run_one(client, row, question, data_dir, sem)))
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


async def main_async(students, questions, data_dir, concurrency, stagger_seconds):
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    client = TelegramClient(StringSession(os.environ["TELEGRAM_SESSION_STRING"]), api_id, api_hash)
    async with client:
        for question in questions:  # question-major: everyone finishes Q_n before Q_n+1 starts
            print(f"=== question '{question['id']}': {len(students)} students ===")
            await run_question_wave(client, students, question, data_dir, concurrency, stagger_seconds)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="students CSV: email,github_url,telegram_bot_username")
    ap.add_argument("--questions", default="evals/questions.json")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--concurrency", type=int, default=5, help="max simultaneous bot conversations")
    ap.add_argument("--stagger-seconds", type=float, default=2.0,
                     help="min delay between starting new conversations")
    args = ap.parse_args()

    students = list(csv.DictReader(open(args.csv, newline="")))
    questions = json.load(open(args.questions))
    asyncio.run(main_async(students, questions, args.data_dir, args.concurrency, args.stagger_seconds))


if __name__ == "__main__":
    main()
