# TDS P1 — Telegram bot grading pipeline

Collection (talking to Telegram) and grading (checking answers) are fully
decoupled: `collect.py` is the only thing that ever contacts Telegram;
`promptfoo` only ever reads what it already collected, so grading can be
re-run any number of times without waiting on a bot again.

## What's public vs private

- `evals/questions.json` — **public**. What gets sent: message text,
  per-question timeout, and the (side-effect-free) `randomize` recipe used
  to generate per-student inputs. Safe to publish — it never reveals a
  correct answer, only how inputs are drawn.
- `promptfoo/promptfoo.yaml` — **private, never publish**. What's correct:
  exact/tolerance checks, or `llm-rubric` for anything needing an LLM judge.
  Same convention as our other `promptfoo`-based assignments — expected
  values/formulas live directly in the YAML's assertions.
- `data/` — **private, git-ignored**. One directory per student
  (`data/<slug>/`), one file per question (`<question_id>.json`), plus
  `grade.json` once graded. Self-contained per student — easy to hand a
  student their own record later.

## One-time setup

```
uv sync   # or: pip install -r requirements.txt
npm install -g promptfoo   # or use npx promptfoo everywhere below
```

You need a Telegram **user account** (not a bot) to act as the grader,
because bots cannot message other bots. Run `python login.py` yourself in a
real terminal (it asks for your phone number + the login code Telegram
texts you, once); it prints a session string:

```
export TELEGRAM_API_ID=...
export TELEGRAM_API_HASH=...
export TELEGRAM_SESSION_STRING=...
```

Consider a Telegram number dedicated to grading rather than your personal
account (see rate-limit notes below).

## Running it

```
python collect.py --csv students.csv
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
python grade_all.py --csv students.csv
```

Writes `data/<slug>/grade.json` per student.

**Gotcha verified while testing this config:** promptfoo runs `exec:`
providers with their cwd set to the config file's own directory
(`promptfoo/`), not wherever you invoke `promptfoo`/`grade_all.py` from. So
`read_collected.py`'s `DATA_DIR` must be an absolute path — `grade_all.py`
already resolves it for you (`Path(args.data_dir).resolve()`); if you ever
invoke `promptfoo eval` by hand instead, pass an absolute `DATA_DIR`, not a
relative one, or it'll silently look in `promptfoo/data` and everything will
report `not_attempted`. Also needs `python3` on `PATH` (not `python`) —
that's what `promptfoo.yaml`'s provider commands call; adjust if your
environment only has one or the other.

## Answer format contract (what students are told)

Every reply that should be graded must end with a single line:

```
FINAL_ANSWER: {"state": "..."}   (or whatever fields that question needs)
```

- Exactly one `FINAL_ANSWER:` block per reply — more than one, or invalid
  JSON in it, is a `format_error`, not "first/last one wins."
- The block must fit in a single Telegram message.

## Adding a new question

1. Add an entry to `evals/questions.json` — id, timeout, one or more
   `messages` (a list = a multi-turn exchange with that one bot), and an
   optional `randomize` recipe (tiny per-var code snippets, seeded by the
   student's email, evaluated with a small safe set of builtins: `math`,
   `statistics`, `rng`).
2. Add a `providers:` entry and a `tests:` entry to `promptfoo/promptfoo.yaml`
   — `is-json` for schema, `type: python` for exact/tolerance checks
   (formula written directly in the YAML), or `type: llm-rubric` for
   anything needing an LLM judge (see promptfoo docs for `llm-rubric` -
   useful for open-ended or visual grading, e.g. chart correctness).

No Python changes needed for either step — `collect.py` and
`read_collected.py` are both fully generic over whatever's in these two
files.

## Rate limits / account safety

- `FloodWaitError`: Telegram says "wait N seconds" for one specific call —
  handled automatically, retried for just that bot.
- `PeerFloodError`: the account itself is flagged as spammy — not a timed
  wait. Verify via `@SpamBot` in the Telegram app, then re-run; already
  collected work is untouched.
- Pilot with a handful of students (small CSV) before running a whole class.
