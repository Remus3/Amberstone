"""RM-1090 (RM-829 sibling residual): three more stop-gate patterns were
QUADRATIC after RM-814 / RM-829.

Measured at e14071faa (seconds, 5k / 10k / 20k chars): `EV_VACUOUS.search` on
a newline run 0.10 / 0.39 / 1.53, on ` \\n` repeated 0.05 / 0.19 / 0.76;
`CLAIM_COUNT.findall` on a digit run 0.18 / 0.73 / 2.91, on a letter run
0.16 / 0.63 / 2.61; `EV_FILTERED.search` on a digit run 0.09 / 0.35 / 1.43, on
`test/` repeated 0.07 / 0.27 / 1.08. Four times the time for twice the input.
audit() runs EV_VACUOUS on every pytest output, EV_FILTERED on every pytest
command and CLAIM_COUNT on every sentence, artifact and sub-agent result, with
NO length cap.

Mechanisms. EV_VACUOUS: under re.M every line start of a blank run is a start
whose `\\s*` re-reads the rest of the run. CLAIM_COUNT: every char of a word is
a start whose `(\\w+)\\s+` re-reads the rest of the word. EV_FILTERED: every
char of a path-like run is a start whose `[\\w/\\\\.-]+` re-reads the rest of
the run, and every `test` head in a run re-reads the rest of it.

The fix: EV_VACUOUS and EV_FILTERED become _AltScan (each regex stays the
authority for the match it returns; a failed try retires the rest of its run,
proof at the class), and CLAIM_COUNT's prefix is anchored on a word boundary
(the same findall, proof at the pattern). The fourth pattern the filing named,
_REDIRECT, is NOT quadratic through its only caller (`.match` at one position
per redirection token in _ancestry_tail, behind COMMAND_PARSE_MAX): measured
0.002 s at 20k, pinned below and left as it is.
"""

import random
import re
import subprocess
import sys
from pathlib import Path

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

# The prior patterns, verbatim, used only as the oracle.
OLD_VACUOUS = re.compile(r"no tests ran|collected 0 items|^\s*INTERNALERROR>",
                         re.I | re.M)
OLD_FILTERED = re.compile(r"\s-k\s|::|\btests?[\w/\\.-]*\.py\b"
                          r"|[\w/\\.-]+\.test\.[cm]?js\b", re.I)
OLD_COUNT = re.compile(r"(?:(\w+)\s+)?\b(\d[\d,]{0,9})\s+passed\b", re.I)

# Timing is a BACKSTOP only; the bounds that decide are the deterministic
# counts below. Run in a child with a hard timeout; each shape keeps the MIN of
# REPEATS samples, so one descheduled sample on a loaded box cannot fail it.
REPEATS = 5
_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
size = int(float(sys.argv[2]) * gate.COMMAND_PARSE_MAX)
def fill(unit, lead="", tail=""):
    return lead + unit * ((size - len(lead) - len(tail)) // len(unit)) + tail
vacuous = gate.EV_VACUOUS.search
filtered = gate.EV_FILTERED.search
count = gate.CLAIM_COUNT.findall
ancestry = lambda text: gate._ancestry_ok(text, "", False)
probe = "git merge-base --is-ancestor HEAD origin/main "
shapes = [
    ("vacuous", vacuous, fill("\n")),
    ("vacuous", vacuous, fill(" \n")),
    ("vacuous", vacuous, fill("\n\t ")),
    ("vacuous", vacuous, fill("\n", "", "INTERNALERROx")),
    ("vacuous", vacuous, fill("\n INTERNALERROR")),
    ("filtered", filtered, fill("1")),
    ("filtered", filtered, fill("test/")),
    ("filtered", filtered, fill("tests.")),
    ("filtered", filtered, fill("a.test.")),
    ("filtered", filtered, fill("x", "", ".py1")),
    ("filtered", filtered, fill(" -k")),
    ("filtered", filtered, fill(":")),
    ("count", count, fill("1")),
    ("count", count, fill("a")),
    ("count", count, fill(" ", "a", "1")),
    ("count", count, fill(" ", "1", "x")),
    ("count", count, fill("1,")),
    ("count", count, fill("1 ")),
    ("count", count, fill("1 passe")),
    ("ancestry", ancestry, fill("1", probe)),
    ("ancestry", ancestry, fill(">1", probe)),
    ("ancestry", ancestry, fill("1>", probe)),
]
worst, where = 0.0, ""
for kind, call, text in shapes:
    best = None
    for _ in range(int(sys.argv[3])):
        start = time.perf_counter()
        call(text)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    if best > worst:
        worst, where = best, "%s %r" % (kind, text[:16])
print(round(worst, 3), where)
"""


def _probe(scale):
    run = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), str(scale), str(REPEATS)],
                         capture_output=True, text=True, timeout=600, cwd=str(REPO))
    assert run.returncode == 0, run.stderr[-2000:]
    worst, _, where = run.stdout.strip().partition(" ")
    return float(worst), where


def test_the_patterns_are_fast_at_command_parse_max():
    worst, where = _probe(1)
    assert worst < 1.0, (worst, where)


def test_the_patterns_stay_fast_at_twice_the_cap():
    # None of the three is capped: audit() runs them on every output / sentence.
    worst, where = _probe(2)
    assert worst < 2.0, (worst, where)


def test_each_pattern_keeps_its_authority():
    for scan, old in ((gate.EV_VACUOUS, OLD_VACUOUS), (gate.EV_FILTERED, OLD_FILTERED)):
        assert isinstance(scan, gate._AltScan)
        assert scan.regex.pattern == old.pattern
        assert scan.regex.flags == old.flags
    # CLAIM_COUNT is the one rewritten pattern: the same text plus one `\b`.
    assert gate.CLAIM_COUNT.pattern == OLD_COUNT.pattern.replace("(?:(", r"(?:\b(", 1)
    assert gate.CLAIM_COUNT.flags == OLD_COUNT.flags


def test_redirect_is_only_ever_matched_at_one_position():
    """_REDIRECT's cost is per call, never per start: its only use is `.match`
    (one start per redirection token). A `search` / `finditer` caller would be
    the quadratic the filing measured (1.65 s at 20k) and must re-open this."""
    source = (REPO / "tools" / "stop_claim_gate.py").read_text(encoding="utf-8")
    uses = re.findall(r"\b_REDIRECT\.(\w+)\(", source)
    assert uses == ["match"], uses


class _Counting:
    """Wraps a compiled alternative and counts the tries made through it."""

    def __init__(self, regex):
        self.regex, self.tries = regex, 0

    def match(self, text, pos=0):
        self.tries += 1
        return self.regex.match(text, pos)

    def search(self, text, pos=0):
        self.tries += 1
        return self.regex.search(text, pos)


def _tries(monkeypatch, scan, text):
    counted = [(_Counting(alt), head, stop) for alt, head, stop in scan._parts]
    monkeypatch.setattr(scan, "_parts", counted)
    match = scan.search(text)
    return [alt.tries for alt, _head, _stop in counted], match


def test_a_failed_try_retires_the_rest_of_its_run(monkeypatch):
    """Deterministic work bound: one try per run, never one per start. The
    FREE alternatives are searched once each."""
    vacuous = gate.EV_VACUOUS
    assert _tries(monkeypatch, vacuous, "\n" * 20000) == ([1, 1, 1], None)
    assert _tries(monkeypatch, vacuous, " \n" * 10000) == ([1, 1, 1], None)
    tries, match = _tries(monkeypatch, vacuous, "x\n" * 1000)
    assert tries == [1, 1, 1001] and match is None
    tries, match = _tries(monkeypatch, vacuous, "\n" * 5000 + "  internalerror> x")
    assert tries == [1, 1, 1] and match.span() == (0, 5000 + 16)
    filtered = gate.EV_FILTERED
    assert _tries(monkeypatch, filtered, "1" * 20000) == ([1, 1, 0, 1], None)
    assert _tries(monkeypatch, filtered, "test/" * 4000) == ([1, 1, 1, 1], None)
    assert _tries(monkeypatch, filtered, "test/ " * 3000) == ([1, 1, 3000, 3000], None)
    tries, match = _tries(monkeypatch, filtered, "a/" * 5000 + "tests/x.py run")
    assert tries == [1, 1, 1, 1] and match.span() == (10000, 10010)


def test_claim_count_tries_a_word_once():
    """The `\\b` the rewrite adds is the whole bound: a prefix try starts only
    at a word's first char, so a word costs one greedy read, not one per char."""
    assert gate.CLAIM_COUNT.match("a" * 20000, 1) is None
    assert gate.CLAIM_COUNT.match("ab 12 passed", 1) is None
    assert gate.CLAIM_COUNT.match("ab 12 passed", 0).groups() == ("ab", "12")


VACUOUS_CASES = [
    "no tests ran", "NO TESTS RAN in 0.1s", "collected 0 items", "INTERNALERROR> x",
    "  INTERNALERROR> x", "\n\n \t INTERNALERROR> x", "x INTERNALERROR> y",
    "x\n INTERNALERROR>", "\r\nINTERNALERROR>", "\u2028INTERNALERROR>", "a\u2028 INTERNALERROR>",
    " \n x\n  internalerror>", "INTERNALERROR", "\n\n\n", "", "x\n\nno tests ran",
    "  \n  collected 0 items\nINTERNALERROR>", "\x1c\nINTERNALERROR>", "\n\x85INTERNALERROR>",
]
FILTERED_CASES = [
    "pytest tests/test_x.py", "pytest -k foo", "pytest a::b", "python -m pytest tests",
    "pytest tests", "node --test web/js/a.test.mjs", "node --test a.test.cjs", "x.test.js",
    "x.test.jsx", "pkg/tests/test_a.py", "a/b/test.py", "TESTS/X.PY", "test.pyc",
    "test_x.py.bak", "tests\\x.py", "-k\tx ", " -k ", "1test.py", "test/a.test.js x.py",
    "a.b-c/test_.py", "_test.py", "test-1.py", "tests::x", "a.test.mjs.test.js",
    "x/test/y/test/z.py", "test", "\u00e9test.py", "test\u00e9.py", "pytest  -k  x",
]
COUNT_CASES = [
    "12 passed", "Test 1 passed", "suite 1,234 passed", "10 856 passed", "x12 passed",
    "12passed", "12 passedx", "a  b 12 passed", "1 2 3 passed", "ab12 3 passed",
    "\u0661\u0662 passed", "lane 8 328 passed, 2 failed", "1,2,3,4,5,6,7,8,9,0,1 passed",
    "x_y 5 PASSED", "x-y 5 passed", "a\n5 passed", "a\t\t5\npassed", "5 passed 6 passed",
    "the 5 passed and 7 passed", "1234567890123 passed", "\u00e9t\u00e9 4 passed",
    ",5 passed", "a,5 passed", "a 5,6 passed",
]


def _shape(match):
    if match is None:
        return None
    return match.span(), match.groups()


def test_hand_checked_cases_match_the_prior_regexes():
    for text in VACUOUS_CASES:
        assert _shape(OLD_VACUOUS.search(text)) == _shape(gate.EV_VACUOUS.search(text)), text
    for text in FILTERED_CASES:
        assert _shape(OLD_FILTERED.search(text)) == _shape(gate.EV_FILTERED.search(text)), text
    for text in COUNT_CASES:
        assert OLD_COUNT.findall(text) == gate.CLAIM_COUNT.findall(text), text
    assert gate.EV_VACUOUS.search("x\n  INTERNALERROR> y").span() == (2, 18)
    assert gate.EV_FILTERED.search("run pkg/tests/test_a.py ok").group() == "tests/test_a.py"


def _texts(rng, pool, seps, count):
    for _ in range(count):
        words = [rng.choice(pool) for _w in range(rng.randint(1, 18))]
        text = words[0]
        for word in words[1:]:
            text += rng.choice(seps) + word
        if rng.random() < 0.05:
            text = text * rng.randint(3, 20)
        yield text


_VACUOUS_POOL = ["INTERNALERROR>", "internalerror>", "INTERNALERROR", "no tests ran",
                 "collected 0 items", "collected", "x", "\u2028", "\x1c", "\x85", ">", ""]
_VACUOUS_SEPS = ["\n", "\n", " ", "\t", "", "\r\n", " \n ", "\n\n", "  "]
_FILTERED_POOL = ["test", "tests", "TEST", "test_a", ".py", "py", ".test.", "test.js",
                  ".test.mjs", "js", "cjs", "-k", "::", ":", "/", "\\", ".", "-", "_", "1",
                  "a", "pkg", "\u00e9", "x.py", "a.test.js", "tests/"]
_FILTERED_SEPS = [" ", " ", "", "", "/", ".", "\t", "\n", "-", ":"]
_COUNT_POOL = ["1", "12", "1,234", ",", "0", "\u0661", "passed", "PASSED", "passedx", "a",
               "ab", "test", "lane", "_", "x1", "1x", "\u00e9", "-", "856", "10"]
_COUNT_SEPS = [" ", " ", " ", "", "\n", "\t", ", ", "  ", ","]


def test_the_scans_match_the_prior_regexes_exactly():
    diffs, compared, found = [], 0, 0
    for seed in (144, 2026):
        rng = random.Random(seed)
        for old, scan, pool, seps in ((OLD_VACUOUS, gate.EV_VACUOUS, _VACUOUS_POOL, _VACUOUS_SEPS),
                                      (OLD_FILTERED, gate.EV_FILTERED, _FILTERED_POOL,
                                       _FILTERED_SEPS)):
            for text in _texts(rng, pool, seps, 1500):
                want, got = _shape(old.search(text)), _shape(scan.search(text))
                compared += 1
                found += want is not None
                if want != got:
                    diffs.append((old.pattern[:12], text, want, got))
        for text in _texts(rng, _COUNT_POOL, _COUNT_SEPS, 1500):
            want, got = OLD_COUNT.findall(text), gate.CLAIM_COUNT.findall(text)
            compared += 1
            found += bool(want)
            if want != got:
                diffs.append(("count", text, want, got))
    assert compared == 2 * 3 * 1500, compared
    # The oracle must actually match something, or equality proves nothing.
    assert found > 2000, found
    assert not diffs, diffs[:3]
