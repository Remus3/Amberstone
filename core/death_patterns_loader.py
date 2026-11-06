"""core/death_patterns_loader.py - read postmortem JSON, format coach context.

Reads `data/coaching/death_patterns.json` (written by
`scripts/postmortem_analyze.py`, ADR-007 phase 2) and renders the top-3
death patterns as a short PERSONAL CONTEXT block for the four mode coach
system prompts.

Fail-soft contract: every helper returns "" / [] / {} when the file is
missing, unreadable, oversized, not UTF-8, malformed, too deeply nested or
contains no top-3, and NEVER raises on any file content.
personal_context_block() runs at IMPORT time of coaches/aram_coach.py,
coaches/arena_coach.py, coaches/brawl_coach.py and
coach_integration/_sr_prompt.py (a module-level prompt string), so an
exception here would fail a live coach's import. An absent JSON degrades
gracefully to "no personalization", same as before ADR-007 phase 2 shipped.

Value contract (s144 true-audit cycle 133):
- No helper ever returns a non-finite float: NaN / Infinity literals and
  overflowing numbers (1e400) parse to None, so /api/personal-context's
  json.dumps never emits a bare NaN token.
- count / total_deaths / total_matches are ints in [0, MAX_COUNT]; a
  bool, negative, fractional, oversized or non-numeric value is 0.
- rate / confidence are floats in [0, 1]; anything else is 0.0.
- label / description / generated_at are single-line printable text with
  bounded length, so a file cannot splice a new line into a system prompt.
- top_patterns() returns at most three distinct keys.
"""
from __future__ import annotations

import json
import math
import pathlib

_DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "coaching" / "death_patterns.json"

# The producer writes a few KB (measured 3.9 KB, 2026-11-05); 1 MiB is far
# past any real report and keeps a runaway file out of every coach import.
MAX_FILE_BYTES = 1 << 20
# How many top3 entries are scanned for the three valid, distinct keys.
_MAX_TOP3_SCAN = 32
MAX_KEY_CHARS = 64
MAX_LABEL_CHARS = 80
MAX_DESCRIPTION_CHARS = 240
MAX_GENERATED_AT_CHARS = 40
# Far past any real death / match count; a larger number is corruption.
MAX_COUNT = 10 ** 12
_TOP_N = 3


def _finite_float_or_none(text: str) -> float | None:
    """json parse_float hook: an overflowing literal (1e400) is None, not inf."""
    value = float(text)
    return value if math.isfinite(value) else None


def _non_finite_constant(_name: str) -> None:
    """json parse_constant hook: NaN / Infinity / -Infinity parse to None."""
    return


def _safe_load(path: pathlib.Path) -> dict:
    """Read and parse the report; {} on ANY failure or a non-dict document."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_FILE_BYTES + 1)
    except (OSError, ValueError):
        return {}
    if len(raw) > MAX_FILE_BYTES:
        return {}
    try:
        data = json.loads(
            raw.decode("utf-8-sig"),
            parse_float=_finite_float_or_none,
            parse_constant=_non_finite_constant,
        )
    except (ValueError, RecursionError):
        # ValueError covers JSONDecodeError, UnicodeDecodeError and an int
        # literal past Python's digit limit; RecursionError a deep nest.
        return {}
    return data if isinstance(data, dict) else {}


def _as_count(value) -> int:
    """A non-negative integral count, else 0 (bool, negative, fractional,
    non-finite and non-numeric are all 0)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return int(value) if 0 <= value <= MAX_COUNT else 0
    if isinstance(value, float):
        if math.isfinite(value) and 0 <= value <= MAX_COUNT and value.is_integer():
            return int(value)
        return 0
    if isinstance(value, str):
        text = value.strip()
        if text.isascii() and text.isdigit() and len(text) <= 13:
            number = int(text)
            return number if number <= MAX_COUNT else 0
    return 0


def _as_unit(value) -> float:
    """A finite float in [0, 1], else 0.0 (bool and non-real are 0.0)."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return 0.0
    elif isinstance(value, int):
        # Compare as int first: float() of a 400-digit int overflows.
        return float(value) if 0 <= value <= 1 else 0.0
    if not isinstance(value, float) or not math.isfinite(value):
        return 0.0
    if 0.0 <= value <= 1.0:
        return float(value)
    return 0.0


def _clean_text(value, limit: int) -> str:
    """Single-line printable text, whitespace collapsed, at most `limit`
    characters ("..." marks a cut); "" for a non-str or blank value."""
    if not isinstance(value, str):
        return ""
    # Read a bounded prefix: enough for `limit` visible characters after
    # collapsing, without walking a multi-megabyte string.
    chunk = value[: limit * 4 + 16]
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in chunk).split())
    if text and (len(text) > limit or len(chunk) < len(value)):
        text = text[: limit - 3].rstrip() + "..."
    return text


def _valid_key(key) -> bool:
    return (
        isinstance(key, str)
        and 0 < len(key) <= MAX_KEY_CHARS
        and key.isprintable()
        and key.strip() == key
    )


def top_patterns(path: pathlib.Path | None = None) -> list[dict]:
    """Return the top-3 patterns as a list of dicts.

    Each entry carries {key, label, description, count, rate, confidence}.
    The rate/confidence keys are present in the source JSON (written by
    scripts/postmortem_analyze.build_report); when absent, non-finite,
    outside [0, 1] or not a number (older schema or malformed entry) they
    default to 0.0 so consumers can render without None-guards. A missing
    or malformed count is 0; a missing or non-text label falls back to the
    key. At most three distinct keys; an invalid key is skipped.

    Empty list when the JSON is missing/malformed or no patterns fired.
    """
    data = _safe_load(path or _DEFAULT_PATH)
    top3 = data.get("top3")
    patterns = data.get("patterns")
    if not isinstance(top3, list) or not isinstance(patterns, dict):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for key in top3[:_MAX_TOP3_SCAN]:
        if not _valid_key(key) or key in seen:
            continue
        meta = patterns.get(key)
        if not isinstance(meta, dict):
            continue
        seen.add(key)
        out.append({
            "key": key,
            "label": _clean_text(meta.get("label"), MAX_LABEL_CHARS) or key,
            "description": _clean_text(meta.get("description"), MAX_DESCRIPTION_CHARS),
            "count": _as_count(meta.get("count", 0)),
            "rate": _as_unit(meta.get("rate", 0.0)),
            "confidence": _as_unit(meta.get("confidence", 0.0)),
        })
        if len(out) >= _TOP_N:
            break
    return out


def report_summary(path: pathlib.Path | None = None) -> dict:
    """Return the report envelope fields {generated_at, total_deaths, total_matches}.

    Empty dict when the JSON is missing/malformed. Companion to
    top_patterns() so route consumers can present the top-3 alongside the
    raw cohort totals without re-reading the file or duplicating fail-soft
    logic. A malformed total is 0; a blank or non-text generated_at is
    omitted.
    """
    data = _safe_load(path or _DEFAULT_PATH)
    if not data:
        return {}
    out: dict = {}
    gen = _clean_text(data.get("generated_at"), MAX_GENERATED_AT_CHARS)
    if gen:
        out["generated_at"] = gen
    out["total_deaths"] = _as_count(data.get("total_deaths", 0))
    out["total_matches"] = _as_count(data.get("total_matches", 0))
    return out


def role_grades_summary(path: pathlib.Path | None = None) -> dict:
    """Return the role_grades envelope from the postmortem JSON.

    Shape mirrors scripts/postmortem_analyze.aggregate_role_grades output:

        {total_matches_scored, overall, by_role}

    Empty dict when the JSON is missing/malformed or the section is absent
    (older schema_version=1 files). Same fail-soft contract as
    top_patterns / report_summary; non-finite numbers anywhere inside it
    are already None (see _safe_load).

    Companion to top_patterns + report_summary so the route consumer can
    surface the role-grade distribution alongside the death-pattern top-3
    without re-reading the file.
    """
    data = _safe_load(path or _DEFAULT_PATH)
    rg = data.get("role_grades")
    if not isinstance(rg, dict):
        return {}
    return rg


def damage_recap_summary(path: pathlib.Path | None = None) -> dict:
    """Return the RM-608 ``damage_recap`` section (ESTIMATED damage-type split).

    Additive companion to role_grades_summary. Empty dict when the JSON is
    missing/malformed, the section is absent, or it is not tagged
    provenance=estimated (the split is a model and must never surface
    unlabelled). Same fail-soft contract as the other helpers.
    """
    data = _safe_load(path or _DEFAULT_PATH)
    dr = data.get("damage_recap")
    if not isinstance(dr, dict) or dr.get("provenance") != "estimated":
        return {}
    return dr


def personal_context_block(path: pathlib.Path | None = None) -> str:
    """Format the top-3 patterns as a system-prompt-ready string block.

    Returns "" when no top-3 - safe to f-string into any prompt without
    a None / empty-block guard at the call site. The block is APPENDED
    to existing prompts so the cached prefix above stays byte-identical.
    Every row is one line: labels and descriptions are single-line text
    (top_patterns), so a file cannot add a line to the prompt.
    """
    patterns = top_patterns(path)
    if not patterns:
        return ""
    lines = [
        "",
        "PERSONAL CONTEXT (operator's recurring death patterns from rewind_history.db):",
    ]
    for i, p in enumerate(patterns, start=1):
        lines.append(f"  {i}. {p['label']} ({p['count']}x): {p['description']}")
    lines.append("Calibrate advice to these recurring mistakes when applicable.")
    return "\n".join(lines)
