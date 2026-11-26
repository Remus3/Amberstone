"""CodeQL py/polynomial-redos (alerts 38 / 39): agent7 input-parser rules.

`_RE_AGENT_DIRECT` and `_RE_NOTE` read `\\s*` SEP? `\\s*` `.+$`: three
quantifiers that can all take the same run of spaces, then a `$` that fails
on an interior newline. Measured on the prior patterns (2026-10-15):
"agent0" + 1600 spaces + "x\\ny" took 5.8 s and "note" + 1600 spaces + "x\\ny"
7.3 s - cubic, and POST /api/input accepts a 256 KiB body.

The rewrite keeps the SAME first match. The prior engine tried the start of
`rest` / `body` at every position from the greedy end of the separator run
DOWN to the keyword, so its answer is the largest feasible start: the greedy
end itself, or - when the separators run to the end of the text - the last
char before the end (and before a final newline). The new patterns compute
those two candidates directly (an atomic lookahead + backreference for the
greedy run), so each is tried once. The oracle test pins that against the
prior patterns over seeded and exhaustive inputs.
"""

import itertools
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from agents.agent7_context import input_parser as ip

REPO = Path(__file__).resolve().parents[1]

# The prior patterns, verbatim - the oracle.
OLD_AGENT_DIRECT = re.compile(
    r"^\s*agent\s*(?P<n>[0-7])\s*(?:,|:|-)?\s*(?P<rest>.+)$", re.IGNORECASE)
OLD_NOTE = re.compile(
    r"^\s*(?:note|remember|remind\s+me)\s*[:,]?\s*(?P<body>.+)$", re.IGNORECASE)

PAIRS = [("_RE_AGENT_DIRECT", OLD_AGENT_DIRECT), ("_RE_NOTE", OLD_NOTE)]


def _result(match):
    return None if match is None else (match.span(), match.groupdict())


def test_long_space_runs_before_an_interior_newline_are_fast():
    shapes = [
        ("_RE_AGENT_DIRECT", "agent0" + " " * 1600 + "x\ny"),
        ("_RE_AGENT_DIRECT", "agent0" + " " * 800 + "," + " " * 800 + "x\ny"),
        ("_RE_NOTE", "note" + " " * 1600 + "x\ny"),
        ("_RE_NOTE", "remind me" + " " * 800 + ":" + " " * 800 + "x\ny"),
    ]
    slow = []
    for name, text in shapes:
        start = time.perf_counter()
        getattr(ip, name).match(text)
        elapsed = time.perf_counter() - start
        if elapsed > 0.25:
            slow.append((name, text[:12], round(elapsed, 2)))
    assert not slow, slow


# 256 KiB is the /api/input body cap (agents/_supervisor_http.py _read_body).
# The prior patterns never finish at that size, so it runs in a child with a
# hard timeout instead of hanging the suite.
_BIG_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from agents.agent7_context import input_parser as ip
worst = 0.0
for name in ("_RE_AGENT_DIRECT", "_RE_NOTE"):
    for text in ("agent0" + " " * 200000 + "x\ny", "note" + " " * 200000 + "x\ny",
                 "agent0" + " " * 200000, "note:" + " \n" * 100000 + "x"):
        start = time.perf_counter()
        getattr(ip, name).match(text)
        worst = max(worst, time.perf_counter() - start)
print(round(worst, 3))
"""


def test_the_body_cap_size_stays_linear():
    run = subprocess.run([sys.executable, "-c", _BIG_PROBE, str(REPO)],
                         capture_output=True, text=True, timeout=60, cwd=str(REPO),
                         check=False)
    assert run.returncode == 0, run.stderr[-2000:]
    assert float(run.stdout.strip()) < 1.0, run.stdout


def _seeded(seed, count):
    rng = random.Random(seed)
    heads = ["agent0", "agent 7", "AGENT3", " agent\t5", "agent8", "agent", "note", "NOTE",
             " remember", "remind me", "remind\n me", "remindme", "notes", "x note", ""]
    # chr(): NBSP and LINE SEPARATOR are \s too, and the source stays ASCII.
    pieces = [" ", "  ", "\t", "\n", ",", ":", "-", ";", "x", "do it", "a b", "\r", chr(0xA0),
              chr(0x2028), ",,", "::", "-x", "\n\n"]
    for _ in range(count):
        text = rng.choice(heads)
        for _p in range(rng.randint(0, 7)):
            text += rng.choice(pieces)
        yield text


def test_the_rewrite_matches_the_prior_patterns_exactly():
    diffs = []
    for seed in (117, 2026):
        for text in _seeded(seed, 6000):
            for name, old in PAIRS:
                if _result(getattr(ip, name).match(text)) != _result(old.match(text)):
                    diffs.append((name, text))
    alphabet = [" ", "\n", ",", ":", "-", "x"]
    for head in ("agent0", "note"):
        for size in range(7):
            for tail in itertools.product(alphabet, repeat=size):
                text = head + "".join(tail)
                for name, old in PAIRS:
                    if _result(getattr(ip, name).match(text)) != _result(old.match(text)):
                        diffs.append((name, text))
    assert not diffs, diffs[:5]


# ---- CodeQL py/polynomial-redos alerts 106 / 107 (s169) ---------------------
# The s118 rewrite is linear at runtime, but its fallback arm is still
# `[\s\S]*` + a `\Z` lookahead pin ahead of `.+$`, and CodeQL's static model
# does not see the pin: it reads two adjacent unbounded quantifiers over the
# same chars (alerts 107 / 106 at the `.match(text)` calls in
# InputParser.parse). The robust fix is a rule with no such shape: an anchored
# head regex, a separator regex and a single-quantifier line regex, joined in
# code. These tests pin that shape and the exact matches.

def _pattern_sources(rule):
    """Every regex source a rule object runs (a Pattern, or an object holding some)."""
    if isinstance(rule, re.Pattern):
        return [rule.pattern]
    return [v.pattern for v in vars(rule).values() if isinstance(v, re.Pattern)]


def test_rules_carry_no_adjacent_overlapping_unbounded_quantifiers():
    bad = []
    for name in ("_RE_AGENT_DIRECT", "_RE_NOTE"):
        sources = _pattern_sources(getattr(ip, name))
        assert sources, name          # an empty enumeration must not pass
        for src in sources:
            if "[\\s\\S]*" in src or "(?<!" in src or ".+$" in src:
                bad.append((name, src))
    assert not bad, bad


def test_real_inputs_parse_as_before():
    cases = [
        ("_RE_AGENT_DIRECT", "Agent 6, audit this file", {"n": "6", "rest": "audit this file"}),
        ("_RE_AGENT_DIRECT", "agent3: do x", {"n": "3", "rest": "do x"}),
        ("_RE_AGENT_DIRECT", "  agent0 - status please\n", {"n": "0", "rest": "status please"}),
        ("_RE_AGENT_DIRECT", "agent7 go", {"n": "7", "rest": "go"}),
        ("_RE_NOTE", "note: buy more wards", {"body": "buy more wards"}),
        ("_RE_NOTE", "Remember, the dragon timer", {"body": "the dragon timer"}),
        ("_RE_NOTE", "remind me to ping Agent 4", {"body": "to ping Agent 4"}),
    ]
    for name, text, groups in cases:
        m = getattr(ip, name).match(text)
        assert m is not None, (name, text)
        assert m.groupdict() == groups, (name, text, m.groupdict())
    for name, text in (("_RE_AGENT_DIRECT", "agent8 x"), ("_RE_AGENT_DIRECT", "agent3"),
                       ("_RE_NOTE", "note"), ("_RE_NOTE", "hello note: x")):
        assert getattr(ip, name).match(text) is None, (name, text)


def test_pathological_runs_of_each_separator_class_stay_fast():
    n = 50_000
    shapes = [
        ("_RE_AGENT_DIRECT", "agent0" + "0" * n + "\ny"),
        ("_RE_AGENT_DIRECT", "agent0" + "\t" * n + "x\ny"),
        ("_RE_AGENT_DIRECT", "agent0," + " " * n),
        ("_RE_NOTE", "note" + "0" * n + "\ny"),
        ("_RE_NOTE", "note:" + " \n" * (n // 2) + "x"),
        ("_RE_NOTE", "remind  me" + " " * n),
    ]
    slow = []
    for name, text in shapes:
        start = time.perf_counter()
        getattr(ip, name).match(text)
        elapsed = time.perf_counter() - start
        if elapsed > 0.5:
            slow.append((name, text[:12], round(elapsed, 2)))
    assert not slow, slow


# ---- CodeQL py/polynomial-redos alert 110 (s170) -----------------------------
# Alert 110 sits on `self.head.match(text)` in _HeadSepLine.match: the head
# regex reached through an attribute is modelled as a SEARCH, so its leading
# `\s*` reads as retried from every space of a long run before a missing
# keyword (quadratic). An explicit `^` pins the head to offset 0 in any model.
# The `.+$` line regex had the same retried shape (`[^\n]+` then a lookahead
# that fails on an interior newline); it is now a newline lookup in code.

def test_rule_heads_are_explicitly_anchored():
    unanchored = [(name, getattr(ip, name).head.pattern)
                  for name in ("_RE_AGENT_DIRECT", "_RE_NOTE")
                  if not getattr(ip, name).head.pattern.startswith(("^", "\\A"))]
    assert not unanchored, unanchored


def test_rest_line_is_not_a_retried_regex():
    assert not hasattr(ip, "_LINE")
    for name in ("_RE_AGENT_DIRECT", "_RE_NOTE"):
        sources = _pattern_sources(getattr(ip, name))
        assert len(sources) == 2, (name, sources)     # head + separator only


def test_search_shaped_pathological_inputs_stay_fast():
    n = 100_000
    shapes = [
        ("_RE_AGENT_DIRECT", " " * n + "x"),
        ("_RE_AGENT_DIRECT", " " * n + "agent"),
        ("_RE_AGENT_DIRECT", "agent0 " + "x" * n + "\n\ny"),
        ("_RE_NOTE", " " * n + "x"),
        ("_RE_NOTE", "note " + "x" * n + "\ny\n"),
    ]
    slow = []
    for name, text in shapes:
        start = time.perf_counter()
        getattr(ip, name).match(text)
        elapsed = time.perf_counter() - start
        if elapsed > 0.5:
            slow.append((name, text[:12], round(elapsed, 2)))
    assert not slow, slow
