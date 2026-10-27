"""RM-829: _HEREDOC and EV_SUMMARY_LINE stayed QUADRATIC after RM-814.

Measured at f073b1ca1 (seconds, 5k / 10k / 20k chars):
`_HEREDOC.sub` on ` <<A<i>` 0.04 / 0.17 / 0.75, on ` <<A` 0.02 / 0.07 / 0.31,
on `<<AAAA...` (one long word, a one-letter terminator line) 0.07 / 0.27 / 1.19;
`EV_SUMMARY_LINE.search` on a digit run 0.10 / 0.41 / 1.79, on `1,` repeated
0.06 / 0.22 / 0.89, on `1 passed ` repeated 0.02 / 0.09 / 0.34. Four times the
time for twice the input. audit() runs _HEREDOC on every main bash command
through strip_command_noise and the raw-bash pass, and EV_SUMMARY_LINE on every
tool result, with NO length cap.

Mechanisms. _HEREDOC: a start with no terminator line reads the WHOLE rest of
the text (`.*?` is re.S), once per start and once more per shorter backtracked
word. EV_SUMMARY_LINE: every digit of a run is a start whose `[\\d,]*` re-reads
the run, and every count on a line re-reads the rest of the line for `in Ns`.

The fix keeps each regex as the authority for the match it returns and skips
only the starts a one-pass terminator-line index (_HeredocScan) or a failed
try (_SummaryLineScan) proves dead. Proofs at the two classes; the
differential below pins every result against the PRIOR plain regexes.
"""

import random
import re
import subprocess
import sys
from pathlib import Path

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

# The prior patterns, verbatim, used only as the oracle.
OLD_HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?.*?^\1\s*$", re.S | re.M)
OLD_SUMMARY = re.compile(
    r"\d[\d,]*\s+(?:passed|failed|error)\b[^\n]*?\bin\s+[\d.]+\s*s"
    r"|^[^a-zA-Z\n]{0,4}duration_ms\s+[\d.]+\s*$", re.I | re.M)

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
heredoc = lambda text: gate._HEREDOC.sub(" ", text)
summary = lambda text: gate.EV_SUMMARY_LINE.search(text)
lines = lambda text: [gate.EV_SUMMARY_LINE.search(line) for line in text.splitlines()]
shapes = [
    ("heredoc", heredoc, fill(" <<A")),
    ("heredoc", heredoc, "".join(" <<A%d" % i for i in range(size // 6))),
    ("heredoc", heredoc, fill("A", "<<", "\nA")),
    ("heredoc", heredoc, fill("\nEOFX", "<<EOF")),
    ("heredoc", heredoc, fill(" <<'A'")),
    ("heredoc", heredoc, fill(" <<AB", "", "\nA")),
    ("heredoc", heredoc, fill("A\n<<A ")),
    ("summary", summary, fill("1")),
    ("summary", summary, fill("1,")),
    ("summary", summary, fill("1 passed ")),
    ("summary", summary, fill("1 passed in x ")),
    ("summary", summary, fill(" ", "1 passed", "x")),
    ("summary", summary, fill(" ", "1", "x")),
    ("summary", summary, fill("1.", "1 passed in ", "x")),
    ("summary", summary, fill("\n1 passed x")),
    ("summary", summary, fill("1.", "duration_ms ", "x")),
    ("summary", lines, fill("1 passed ")),
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


def test_the_two_patterns_are_fast_at_command_parse_max():
    worst, where = _probe(1)
    assert worst < 1.0, (worst, where)


def test_the_two_patterns_stay_fast_at_twice_the_cap():
    # Neither path is capped: audit() runs both on every main command / result.
    worst, where = _probe(2)
    assert worst < 2.0, (worst, where)


def test_each_pattern_is_a_scan():
    assert isinstance(gate._HEREDOC, gate._HeredocScan)
    assert isinstance(gate.EV_SUMMARY_LINE, gate._SummaryLineScan)
    assert gate._HEREDOC.regex.pattern == OLD_HEREDOC.pattern
    assert gate._HEREDOC.regex.flags == OLD_HEREDOC.flags
    assert gate.EV_SUMMARY_LINE.regex.pattern == OLD_SUMMARY.pattern
    assert gate.EV_SUMMARY_LINE.regex.flags == OLD_SUMMARY.flags


class _Counting:
    """Wraps a regex and counts the tries made through it."""

    def __init__(self, regex):
        self.regex, self.tries = regex, 0

    def match(self, text, pos=0):
        self.tries += 1
        return self.regex.match(text, pos)

    def __getattr__(self, name):
        return getattr(self.regex, name)


def _summary_tries(monkeypatch, text):
    counting = _Counting(gate.EV_SUMMARY_LINE.regex)
    monkeypatch.setattr(gate.EV_SUMMARY_LINE, "regex", counting)
    result = gate.EV_SUMMARY_LINE.search(text)
    return counting.tries, result


def test_a_failed_summary_try_retires_the_rest_of_its_line(monkeypatch):
    """Deterministic work bound: one authority try per line, never per count,
    and no try at all for a count with no status word after it."""
    assert _summary_tries(monkeypatch, "1" * 20000) == (0, None)
    assert _summary_tries(monkeypatch, "1," * 10000) == (0, None)
    assert _summary_tries(monkeypatch, "1 passed " * 2000) == (1, None)
    assert _summary_tries(monkeypatch, "1 passed x\n" * 1000) == (1000, None)
    tries, match = _summary_tries(monkeypatch, "1 passed x " * 1000 + "in 2s")
    assert tries == 1 and match.span() == (0, 11 * 1000 + 5)
    # A count whose whitespace crosses the line still gets its own try.
    tries, match = _summary_tries(monkeypatch, "1 passed x 2\npassed in 3s")
    assert tries == 2 and match.span() == (11, 25)


class _CountingFixed:
    def __init__(self, fixed):
        self.fixed, self.tries = fixed, 0

    def __call__(self, depth):
        self.tries += 1
        return self.fixed(depth)


def _heredoc_tries(monkeypatch, text):
    scan = gate._HEREDOC
    authority = _Counting(scan.regex)
    fixed = _CountingFixed(scan._fixed)
    monkeypatch.setattr(scan, "regex", authority)
    monkeypatch.setattr(scan, "_fixed", fixed)
    spans = [m.span() for m in scan.finditer(text)]
    return fixed.tries, authority.tries, spans


def test_a_heredoc_start_with_no_terminator_costs_no_try(monkeypatch):
    """Deterministic work bound: a start reaches the regex only when the index
    holds a terminator line after it, and then that try is the match."""
    assert _heredoc_tries(monkeypatch, " <<A" * 5000) == (0, 0, [])
    assert _heredoc_tries(monkeypatch, "A\n" + "<<A " * 5000) == (0, 0, [])
    # The word's own line is not a terminator, even when `\s*` put the word
    # at a line start.
    assert _heredoc_tries(monkeypatch, "<<\nA") == (0, 0, [])
    text = "<<" + "A" * 20000 + "\nA"
    assert _heredoc_tries(monkeypatch, text) == (1, 0, [(0, len(text))])
    text = "<<A\n" * 1000 + "A"
    assert _heredoc_tries(monkeypatch, text) == (1, 0, [(0, len(text))])
    # `\s*$` reaches the end of the text after the last terminator, so the
    # last match also takes the final newline.
    text = "<<A x\nA\n" * 1000
    spans = [(8 * i, 8 * i + 7) for i in range(999)] + [(7992, 8000)]
    assert _heredoc_tries(monkeypatch, text) == (1000, 0, spans)


HEREDOC_CASES = [
    "cat <<EOF\nx\nEOF\n", "cat <<'EOF'\nx\nEOF", "<<-EOF\n\tx\nEOF", "<<EOF\nEO\n",
    "<<EOF x\nEOF  \n\n  \ny", "<<\nEOF\nEOF", "<<EOF", "EOF\n<<EOF", "<<EOF\nEOFX\nEOF",
    "<<<EOF\nEOF", "<<A <<B\nB\nA", "<<\u00e9t\u00e9\n\u00e9\n", "<<EOF\r\nx\r\nEOF\r\n",
    "<<EOF\nEOF \x1c\nz", "<<EOF\n EOF\nEOF", "<< 'EOF' x\nEOF", "<<-'A'\nA", "<<- A\nA",
    "<<'A\nA", "<<A'\nA", "<<A\n\nA\n\n\n", "<<A\nA\nA", "x<<A<<B\nB\nA\n<<C\nC",
    "<<A_1\nA_\n", "<<EOF\nEOF\u2028\nq", "<<EOF\nEOF\n   ", "<<EOF\nEOF   \n   x",
]


def test_hand_checked_heredocs_match_the_prior_regex():
    for text in HEREDOC_CASES:
        old = [_shape(m) for m in OLD_HEREDOC.finditer(text)]
        new = [_shape(m) for m in gate._HEREDOC.finditer(text)]
        assert old == new, (text, old, new)
        assert OLD_HEREDOC.sub(" ", text) == gate._HEREDOC.sub(" ", text), text
        assert _shape(OLD_HEREDOC.search(text)) == _shape(gate._HEREDOC.search(text)), text
    assert gate._HEREDOC.sub(" ", "cat <<EOF\nx\nEOF\ny") == "cat  \ny"
    assert gate._HEREDOC.sub(lambda m: "[" + m.group(1) + "]", "<<A\nA") == "[A]"
    assert gate._HEREDOC.sub(r"<\1>", "<<A\nA") == "<A>"


SUMMARY_CASES = [
    "12 passed in 3.4s", "1,234 passed, 5 skipped in 60.01s (0:01:00)", "3 failed in 2 s",
    "1 error in 0.5s", "1 PASSED IN 2S", "2 passed\nin 3s", "2\npassed in 3s",
    ",5 passed in 1s", "a,1 passed in 1s", "x1 passed in 1s", "1 passedx in 1s",
    "1 passed pin 2s", "1 passed in\n\n2.0\ns", "\u2139 duration_ms 123.4",
    "12 duration_ms 5", "abc duration_ms 5", "duration_ms\n5", "1 passed x 2\npassed in 3s",
    "1 passed in x 2 failed in 3s", "1 passed\n2 passed in 4s", "\u0661 passed in 2s",
    "1 passed in 1.2.3 s", "duration_ms 1\n1 passed in 2s", "1 passed in 2s duration_ms 3",
]


def test_hand_checked_summaries_match_the_prior_regex():
    for text in SUMMARY_CASES:
        for variant in [text, *text.splitlines()]:
            old, new = OLD_SUMMARY.search(variant), gate.EV_SUMMARY_LINE.search(variant)
            assert _shape(old) == _shape(new), (variant, _shape(old), _shape(new))


def _shape(match):
    if match is None:
        return None
    return match.span(), match.groups()


def _texts(rng, pool, seps, count):
    for _ in range(count):
        words = [rng.choice(pool) for _w in range(rng.randint(1, 18))]
        text = words[0]
        for word in words[1:]:
            text += rng.choice(seps) + word
        if rng.random() < 0.05:
            text = text * rng.randint(3, 20)
        yield text


_HEREDOC_POOL = ["<<", "<<-", "<< ", "<<'", "<<-'", "<<<", "'", "EOF", "EO", "E", "EOFX",
                 "A", "AB", "B", "_", "1", "\u00e9", "x", "cat", "-", "EOF'", "<<EOF", "<<A",
                 "<<'EOF'", "\r", "\t", "\x1c", "\u2028"]
_HEREDOC_SEPS = ["\n", "\n", "\n", " ", "", "", "\t", "\r\n", "  \n", "\n\n", " \n "]
_SUMMARY_POOL = ["1", "12", "1,234", ",", ",5", "0", "\u0661", "passed", "PASSED", "failed",
                 "error", "errors", "passedx", "in", "IN", "pin", "1.5", "0.2s", "s", "S",
                 "x", "duration_ms", "\u2139", "2.0s", "in 3s", "1 passed", "(0:01:00)", "."]
_SUMMARY_SEPS = [" ", " ", " ", "", "\n", "\t", ", ", "  ", " \n", ","]


def test_the_scans_match_the_prior_regexes_exactly():
    diffs, compared, found = [], 0, 0
    for seed in (829, 2026):
        rng = random.Random(seed)
        for text in _texts(rng, _HEREDOC_POOL, _HEREDOC_SEPS, 1500):
            old = [_shape(m) for m in OLD_HEREDOC.finditer(text)]
            new = [_shape(m) for m in gate._HEREDOC.finditer(text)]
            compared += 1
            found += len(old)
            if old != new or OLD_HEREDOC.sub(" ", text) != gate._HEREDOC.sub(" ", text):
                diffs.append(("heredoc", text, old, new))
        for text in _texts(rng, _SUMMARY_POOL, _SUMMARY_SEPS, 1500):
            for variant in [text, *text.splitlines()]:
                old = _shape(OLD_SUMMARY.search(variant))
                new = _shape(gate.EV_SUMMARY_LINE.search(variant))
                compared += 1
                found += old is not None
                if old != new:
                    diffs.append(("summary", variant, old, new))
    assert compared > 2 * 1500 * 2, compared
    # The oracle must actually match something, or equality proves nothing.
    assert found > 1000, found
    assert not diffs, diffs[:3]
