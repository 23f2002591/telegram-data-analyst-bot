# TDS P1 — Telegram bot grading pipeline

Collection (talking to Telegram) and grading (checking answers) are fully
decoupled: `collect.py` is the only thing that ever contacts Telegram;
`grade_all.py` only ever reads what it already collected, so grading can be
re-run any number of times without waiting on a bot again. Pure Python
throughout — no other runtime required.

## What's public vs private

- `evals/questions.json` — **public**. What gets sent: message text,
  per-question timeout, and the (side-effect-free) `randomize` recipe used
  to generate per-student inputs. Safe to publish — it never reveals a
  correct answer, only how inputs are drawn.
- `answers.json` — **private, git-ignored, never publish**. What's correct:
  a static `expected` value, or `expected_code` — a tiny formula evaluated
  against that student's already-collected `_vars` (see `grading.py`).
- `data/` — **private, git-ignored**. One directory per student
  (`data/<slug>/`), one file per question (`<question_id>.json`), plus
  `grade.json` once graded. Self-contained per student — easy to hand a
  student their own record later.

## One-time setup

```
uv sync   # or: pip install -r requirements.txt
```

You need a Telegram **user account** (not a bot) to act as the grader,
because bots cannot message other bots. Run `python3 login.py` yourself in a
real terminal (it asks for your phone number + the login code Telegram
texts you, once); it prints a session string. Copy `.env.example` to `.env`
and fill in `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` (from
https://my.telegram.org → API development tools) and
`TELEGRAM_SESSION_STRING` (from `login.py`'s output).

Consider a Telegram number dedicated to grading rather than your personal
account (see rate-limit notes below).

## Running it

```
python3 collect.py --csv students.csv
```

This is the only step that talks to Telegram. It's **question-major**: it
finishes question 1 for the entire class before starting question 2 — so no
student ever sees a later question's content before everyone has had their
turn at the earlier ones, which matters once a class is large enough that
grading takes hours or days. Within one question, students are processed
concurrently (`--concurrency`, default 5 simultaneous conversations),
throttled by `--stagger-seconds` (default 2s between starting new ones) so
new first-contacts trickle in rather than bursting — bounded parallelism
that stays under Telegram's anti-spam heuristics instead of fighting them.

It's safe to re-run at any point, at any scale: `data/<slug>/<question_id>.json`
existing means that (student, question) pair is done and gets skipped.
`FloodWaitError` (a timed wait Telegram itself asked for) is retried
automatically for just that one bot. `PeerFloodError` (the account got
flagged as spammy — not a timed wait) stops the whole run with instructions
to verify via @SpamBot before re-running; nothing already collected is lost.

Then grade everyone (no Telegram calls, freely re-runnable):

```
python3 grade_all.py --csv students.csv
```

Writes `data/<slug>/grade.json` per student — a list of
`{question_id, status, correct, detail}` rows.

## Answer format contract (what students are told)

Every reply that should be graded must end with a single line:

```
FINAL_ANSWER: {"state": "..."}   (or whatever fields that question needs)
```

- Exactly one `FINAL_ANSWER:` block per reply — more than one, or invalid
  JSON in it, is a `format_error`, not "first/last one wins."
- The block must fit in a single Telegram message.

## Adding a new question

Exactly two files, always:

1. **`evals/questions.json`** — add one entry: `id`, `timeout_seconds`, one
   or more `messages` (a list = a multi-turn exchange with that one bot),
   and an optional `randomize` recipe (tiny per-var code snippets, seeded by
   the student's email, evaluated with a small safe set of builtins:
   `math`, `statistics`, `rng`).
2. **`answers.json`** — add one entry: `id`, `match` (`"exact"` or
   `"tolerance"`, plus `tolerance_pct` if so), and either a static
   `expected` or a private `expected_code` formula (evaluated against that
   student's collected `_vars`).

No Python changes needed for either step — `collect.py`, `grade_all.py`, and
`grading.py` are all fully generic over whatever's in these two files.

Adding a genuinely new *type* of check (not just a new question) is the one
place that needs code: write one function in `grading.py`
(`(parsed, expected, tolerance_pct) -> (bool, detail_str)`) and register it
in `MATCHERS` — then any question can use it via `"match"` in `answers.json`.

## Rate limits / account safety

- `FloodWaitError`: Telegram says "wait N seconds" for one specific call —
  handled automatically, retried for just that bot.
- `PeerFloodError`: the account itself is flagged as spammy — not a timed
  wait. Verify via `@SpamBot` in the Telegram app, then re-run; already
  collected work is untouched.
- Pilot with a handful of students (small CSV) before running a whole class.
