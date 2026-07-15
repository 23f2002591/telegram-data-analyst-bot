"""Grading logic: checks against a private answer key (answers.json),
applied to already-collected data/<slug>/<question_id>.json.

Add a new question TYPE by writing one function here (signature: (parsed,
expected, tolerance_pct) -> (bool, detail_str)) and registering it in
MATCHERS. Adding a new question of an EXISTING type needs no code at all -
just a new entry in evals/questions.json and answers.json.
"""
import math
import numbers
import statistics

SAFE_GLOBALS = {"__builtins__": {}, "math": math, "statistics": statistics,
                "range": range, "round": round, "len": len, "sum": sum, "min": min, "max": max}


def _tolerance_compare(parsed, expected, tol_pct):
    if isinstance(expected, dict):
        if not isinstance(parsed, dict):
            return False, "expected object, got non-object"
        for k, v in expected.items():
            if k not in parsed:
                return False, f"missing key '{k}'"
            ok, detail = _tolerance_compare(parsed[k], v, tol_pct)
            if not ok:
                return False, f"key '{k}': {detail}"
        return True, f"within {tol_pct}% tolerance"
    if isinstance(expected, list):
        if not isinstance(parsed, list) or len(parsed) != len(expected):
            return False, "list length/shape mismatch"
        for i, (p, e) in enumerate(zip(parsed, expected)):
            ok, detail = _tolerance_compare(p, e, tol_pct)
            if not ok:
                return False, f"index {i}: {detail}"
        return True, f"within {tol_pct}% tolerance"
    if isinstance(expected, numbers.Number):
        if not isinstance(parsed, numbers.Number):
            return False, f"expected number, got {parsed!r}"
        ok = (abs(parsed - expected) <= 1e-9 if expected == 0
              else abs(parsed - expected) / abs(expected) * 100 <= tol_pct)
        detail = f"within {tol_pct}% tolerance" if ok else f"expected ~{expected}, got {parsed} (outside {tol_pct}%)"
        return ok, detail
    ok = parsed == expected
    return ok, ("exact match" if ok else f"expected {expected!r}, got {parsed!r}")


def _exact_match(parsed, expected, _tol_pct):
    ok = parsed == expected
    return ok, ("exact match" if ok else f"expected {expected!r}, got {parsed!r}")


def _tolerance_match(parsed, expected, tol_pct):
    return _tolerance_compare(parsed, expected, tol_pct)


MATCHERS = {
    "exact": _exact_match,
    "tolerance": _tolerance_match,
}


def resolve_expected(spec, vars_):
    """Static `expected`, or `expected_code` - a tiny formula evaluated
    against this student's already-collected `_vars` (their randomized
    inputs, written by collect.py) - so per-student expected values are
    never stored anywhere, just recomputed from the same values collect.py
    already recorded."""
    if "expected_code" in spec:
        scope = dict(SAFE_GLOBALS)
        scope.update(vars_)
        return eval(spec["expected_code"], scope, {})
    return spec["expected"]


def grade(collected: dict, spec: dict):
    """collected: the parsed contents of data/<slug>/<question_id>.json.
    spec: this question's entry from answers.json.
    Returns (correct: bool, detail: str)."""
    if collected.get("_status") != "answered":
        return False, collected.get("_status", "not_attempted")
    matcher = MATCHERS.get(spec.get("match", "exact"))
    if matcher is None:
        return False, f"unknown match type '{spec.get('match')}'"
    expected = resolve_expected(spec, collected.get("_vars", {}))
    checked = {k: v for k, v in collected.items() if not k.startswith("_")}
    return matcher(checked, expected, spec.get("tolerance_pct", 5))
