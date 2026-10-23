"""RM-814: EV_COMMIT, EV_CI and EV_CI_VAR stayed QUADRATIC after RM-765.

Re-measured at f349e3178 (seconds per `search`, 5k / 10k / 20k / 40k chars):
EV_COMMIT ` git` 0.06 / 0.24 / 0.93 / 3.66; EV_CI ` gh` 0.12 / 0.43 / 1.66 /
6.57; EV_CI_VAR ` a="gh"` 0.02 / 0.10 / 0.38 / 1.38 and, worse, a bound name
followed by a whitespace run (`GH="gh" $GH` + spaces + `x`) 1.32 s at 10k,
5.12 s at 20k, 20.3 s at 40k. The RM-814 sibling sweep (every module-level
pattern against repeated-token shapes) added EV_NODE_TEST (` node` 0.03 / 0.12
at 10k / 20k), the same shape as EV_COMMIT. audit() and collect_evidence() run
all four on every main-thread command with NO length cap.

Mechanisms. EV_COMMIT / EV_CI / EV_NODE_TEST: a failed try at a head word
re-reads the rest of its segment, once per head (k heads, k segment reads).
EV_CI_VAR: a failed try at a binding re-reads the WHOLE rest of the text, once
per binding; and its tail `\\s*[,\\s]\\s*` splits a whitespace run every way
(w * w / 2 tries per bound-name occurrence).

The fix keeps each regex as the authority for the match it returns and skips
only the starts a failed try (_SpanScan) or a one-pass use-site index
(_BoundNameScan) proves dead; EV_CI_VAR's tail is the same language written
without the split ambiguity. Proofs at the two classes; the differential below
pins every `search` against the PRIOR plain regexes.
"""

import functools
import itertools
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

# The prior patterns, verbatim, used only as the oracle. EV_CI_VAR's tail was
# rewritten (same language), so its old text is kept here rather than read back.
OLD = {
    "EV_COMMIT": (r"\bgit\b[^|;&]*(?<!-)\bcommit\b", re.I),
    "EV_CI": (r"\bgh(?:\.exe)?\b[^|&\n]*?\b(?:run|pr|api|workflow)\b|actions/runs", re.I),
    "EV_CI_VAR": (r"(?P<name>\b\w+)\s*=\s*r?[\"'][^\"'\n]*\bgh(?:\.exe)?[\"']"
                  r"[\s\S]*?"
                  r"[\$\{\"'\[,\s](?P=name)[\}\"']?\s*[,\s]\s*[\"']?(?:run|pr|api|workflow)\b",
                  re.I),
    "EV_NODE_TEST": (r"\bnpm\s+(?:run\s+)?test\b|\bnode\b[^|;&\n]*--test\b", re.I),
}
NAMES = sorted(OLD)

# Timing is a BACKSTOP only; the bounds that decide are the deterministic
# counts below (authority tries, separator parses). Run in a child with a hard
# timeout; each shape keeps the MIN of REPEATS samples, so a descheduled sample
# on a loaded box (one read 0.326 s under 48 burners on 16 CPUs, idle 2-3 ms)
# cannot fail it. Before the fix the worst shape took 5 s at the cap and 20 s
# at twice the cap, so the generous bounds still catch the residue.
REPEATS = 5
_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
size = int(float(sys.argv[2]) * gate.COMMAND_PARSE_MAX)
def fill(unit, lead=""):
    return lead + unit * ((size - len(lead)) // len(unit))
shapes = [
    ("EV_COMMIT", fill(" git")), ("EV_COMMIT", fill(" git.exe")), ("EV_COMMIT", fill("\nGIT x")),
    ("EV_COMMIT", fill(" -git")),
    ("EV_CI", fill(" gh")), ("EV_CI", fill(" gh.exe")), ("EV_CI", fill("\tgh x")),
    ("EV_CI", fill(' a="gh"')), ("EV_CI", fill(" $GH")),
    ("EV_CI_VAR", fill(' a="gh"')), ("EV_CI_VAR", fill(" ab = r'gh'")),
    ("EV_CI_VAR", fill(' a="gh" $b')), ("EV_CI_VAR", fill(" ", 'GH="gh" $GH') + "x"),
    ("EV_CI_VAR", fill(" ", 'GH="gh" $GH,') + "x"),
    ("EV_CI_VAR", "".join(' a%d="gh"' % i for i in range(size // 9))),
    ("EV_CI_VAR", fill(" $GH x", 'GH="gh"')),
    ("EV_NODE_TEST", fill(" node")), ("EV_NODE_TEST", fill(" npm node")),
]
worst, where = 0.0, ""
for name, text in shapes:
    best = None
    for _ in range(int(sys.argv[3])):
        start = time.perf_counter()
        getattr(gate, name).search(text)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    if best > worst:
        worst, where = best, "%s %r" % (name, text[:16])
print(round(worst, 3), where)
"""


def _probe(scale):
    run = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), str(scale), str(REPEATS)],
                         capture_output=True, text=True, timeout=600, cwd=str(REPO))
    assert run.returncode == 0, run.stderr[-2000:]
    worst, _, where = run.stdout.strip().partition(" ")
    return float(worst), where


def test_the_main_thread_patterns_are_fast_at_command_parse_max():
    worst, where = _probe(1)
    assert worst < 1.0, (worst, where)


def test_the_main_thread_patterns_stay_fast_at_twice_the_cap():
    # audit() / collect_evidence() run these on every main command, uncapped.
    worst, where = _probe(2)
    assert worst < 2.0, (worst, where)


def test_each_pattern_is_a_scan():
    assert isinstance(gate.EV_COMMIT, gate._SpanScan)
    assert isinstance(gate.EV_CI, gate._SpanScan)
    assert isinstance(gate.EV_NODE_TEST, gate._SpanScan)
    assert isinstance(gate.EV_CI_VAR, gate._BoundNameScan)


class _Counting:
    """Wraps a scan's authority regex and counts the tries made through it."""

    def __init__(self, regex):
        self.regex, self.tries = regex, 0

    def match(self, text, pos=0):
        self.tries += 1
        return self.regex.match(text, pos)

    def __getattr__(self, name):
        return getattr(self.regex, name)


def _tries(monkeypatch, name, text):
    scan = getattr(gate, name)
    counting = _Counting(scan.regex)
    monkeypatch.setattr(scan, "regex", counting)
    result = scan.search(text)
    return counting.tries, result


def test_a_failed_try_retires_its_whole_segment(monkeypatch):
    """Deterministic work bound: one authority try per segment, never per head."""
    assert _tries(monkeypatch, "EV_COMMIT", "git " * 5000) == (1, None)
    assert _tries(monkeypatch, "EV_COMMIT", "git x;" * 1000) == (1000, None)
    assert _tries(monkeypatch, "EV_CI", "gh " * 5000) == (1, None)
    assert _tries(monkeypatch, "EV_CI", "gh x\n" * 1000) == (1000, None)
    assert _tries(monkeypatch, "EV_NODE_TEST", "node " * 5000) == (1, None)
    tries, match = _tries(monkeypatch, "EV_COMMIT", "git x " * 3000 + "commit")
    assert tries == 1 and match.span() == (0, 6 * 3000 + 6)


def test_unused_bindings_cost_no_authority_try(monkeypatch):
    binds = "".join(f' a{i}="gh"' for i in range(2000))
    assert _tries(monkeypatch, "EV_CI_VAR", binds) == (0, None)
    tries, match = _tries(monkeypatch, "EV_CI_VAR", binds + " $a1999 run")
    assert tries == 1 and match.group("name") == "a1999"


def test_a_whitespace_run_after_a_bound_name_costs_at_most_one_try(monkeypatch):
    """The shape that took 5 s at the cap. With no real use the run never
    reaches the regex; with a later use it is read by ONE try, whose
    separator then has one parse per prefix (next test), so the try is linear."""
    run = " " * 20000
    for sep in ("", ","):
        lead = 'GH="gh" $GH' + sep + run + "x"
        assert _tries(monkeypatch, "EV_CI_VAR", lead) == (0, None), repr(sep)
        tries, match = _tries(monkeypatch, "EV_CI_VAR", lead + " $GH run")
        assert tries == 1 and match.span() == (0, len(lead) + 8), repr(sep)


# The separator as alternatives of atoms (the old one for contrast). Each
# parse is a split of the word into slices that fullmatch their atoms, checked
# by the engine; a failing tail attempt explores every parse of every prefix.
_NEW_SEP = [[r"\s*", ",", r"\s*"], [r"\s", r"\s*"]]  # (?:\s*,|\s)\s*
_OLD_SEP = [[r"\s*", r"[,\s]", r"\s*"]]  # \s*[,\s]\s*


def _parses(alternatives, word):
    total = 0
    for atoms in alternatives:
        compiled = [re.compile(atom) for atom in atoms]

        @functools.cache
        def ways(i, k, compiled=compiled):
            if k == len(compiled):
                return int(i == len(word))
            return sum(ways(j, k + 1) for j in range(i, len(word) + 1)
                       if compiled[k].fullmatch(word, i, j))
        total += ways(0, 0)
    return total


def test_the_ci_var_separator_has_one_parse():
    """Deterministic operation bound for the whitespace tail: at most ONE parse
    of any whitespace / comma word (the old separator had one per whitespace
    char, so a failing attempt on a run of w explored about w * w / 2)."""
    assert gate._CI_VAR_SEP == r"(?:\s*,|\s)\s*"
    assert gate._CI_VAR_SEP in gate.EV_CI_VAR.pattern
    sep, old = re.compile(gate._CI_VAR_SEP), re.compile(r"\s*[,\s]\s*")
    checked = 0
    for length in range(7):
        for chars in itertools.product(" \t,x", repeat=length):
            word = "".join(chars)
            new_parses, old_parses = _parses(_NEW_SEP, word), _parses(_OLD_SEP, word)
            assert (new_parses > 0) == bool(sep.fullmatch(word)), repr(word)
            assert (old_parses > 0) == bool(old.fullmatch(word)), repr(word)
            assert new_parses <= 1, (repr(word), new_parses)
            checked += 1
    assert checked == sum(4 ** n for n in range(7))
    assert _parses(_OLD_SEP, " " * 12) == 12, "the counter does see the old split"
    assert _parses(_NEW_SEP, " " * 12) == 1


def test_hand_checked_cases_match_the_prior_regexes():
    cases = [
        ("EV_COMMIT", "git -C x commit -m y"), ("EV_COMMIT", "git cherry-pick --no-commit x"),
        ("EV_COMMIT", "git x | commit"), ("EV_COMMIT", "git x; git commit"),
        ("EV_COMMIT", "echo git\ncommit"), ("EV_COMMIT", "git x -commit"),
        ("EV_CI", "gh x | gh run list"), ("EV_CI", "gh.exe api repos"),
        ("EV_CI", "gh x\nrun"), ("EV_CI", "gh x actions/runs"), ("EV_CI", "x actions/runs gh run"),
        ("EV_CI", "ghrun"), ("EV_CI", "gh.exerun"),
        ("EV_CI_VAR", 'GH="C:/x/gh.exe" && "$GH" run list'),
        ("EV_CI_VAR", "A='gh'\nB='gh'\nsubprocess.run([B, 'run'])"),
        ("EV_CI_VAR", "gh = 'gh'\n[GH, 'pr', 'list']"),
        ("EV_CI_VAR", 'GH="gh" ${GH} api x'), ("EV_CI_VAR", 'GH="gh" $GHX run'),
        ("EV_CI_VAR", 'k="gh" $\u212a run'), ("EV_CI_VAR", 's="gh" $\u017f run'),
        ("EV_CI_VAR", '\u03c3="gh" $\u03c2 run'), ("EV_CI_VAR", 'i="gh" $\u0130 run'),
        ("EV_CI_VAR", 'run="gh" $GH run run'),
        ("EV_NODE_TEST", "node x --test y"), ("EV_NODE_TEST", "node x | y --test"),
        ("EV_NODE_TEST", "npm run test"), ("EV_NODE_TEST", "node a; npm test"),
    ]
    for name, text in cases:
        old = re.compile(*OLD[name]).search(text)
        new = getattr(gate, name).search(text)
        assert _shape(old) == _shape(new), (name, text, _shape(old), _shape(new))
    assert gate.EV_CI_VAR.search('k="gh" $\u212a run') is not None, "Kelvin sign folds to k"
    assert gate.EV_CI_VAR.search('\u03c3="gh" $\u03c2 run') is None, "final sigma does not"


def _shape(match):
    if match is None:
        return None
    return match.span(), match.groups(), match.groupdict()


def _fuzz_inputs(seed, count):
    rng = random.Random(seed)
    heads = ["git", "git.exe", "GIT", "-git", "gitx", "gh", "gh.exe", "GH", "Gh.EXE", "ghx",
             "node", "npm", "NODE", "x.gh", "a/gh"]
    tails = ["commit", "-commit", "--no-commit", "Commit", "commitx", "run", "pr", "api",
             "workflow", "runs", "prx", "actions/runs", "ACTIONS/RUNS", "--test", "test",
             "--testx", "list", "view"]
    names = ["GH", "gh", "Gh", "a", "A", "k", "\u212a", "s", "\u017f", "\u03c3", "\u03c2",
             "i", "\u0130", "run", "x1", "_"]
    glue = ["=", " = ", "='gh'", '="gh"', "=r'x/gh.exe'", '="gh.exe"', "='x gh'", "=\"ghx\"",
            "$", "${", "}", '"', "'", "[", ",", ", ", "(", ")", "&&", "&", "|", ";", "\n",
            "x", "-c", "--", ">", "<<EOF", "EOF"]
    seps = [" ", " ", " ", "  ", "\t", "\n", "", "", ";", "|", "&&", ",", "   \n  "]
    for _ in range(count):
        words = []
        for _w in range(rng.randint(1, 16)):
            roll = rng.random()
            pool = heads if roll < 0.3 else tails if roll < 0.55 else names if roll < 0.75 else glue
            words.append(rng.choice(pool))
        text = words[0]
        for word in words[1:]:
            text += rng.choice(seps) + word
        if rng.random() < 0.05:
            text = text * rng.randint(5, 30)
        yield text


def test_the_scans_match_the_prior_regexes_exactly():
    plains = {name: re.compile(*OLD[name]) for name in NAMES}
    diffs, compared = [], 0
    for seed in (814, 2026):
        for text in _fuzz_inputs(seed, 1500):
            for variant in (text, gate.strip_command_noise(text), gate._HEREDOC.sub(" ", text)):
                for name in NAMES:
                    old = _shape(plains[name].search(variant))
                    new = _shape(getattr(gate, name).search(variant))
                    compared += 1
                    if old != new:
                        diffs.append((name, variant, old, new))
    assert compared == 2 * 1500 * 3 * len(NAMES)
    assert not diffs, diffs[:3]


def test_the_rewritten_ci_var_regex_is_the_prior_one():
    """Language check on the one rewritten piece, over every short ws/comma word."""
    old, new = re.compile(r"\s*[,\s]\s*\Z"), re.compile(r"(?:\s*,|\s)\s*\Z")
    checked = 0
    for length in range(7):
        for chars in itertools.product(" \t\n,x", repeat=length):
            word = "".join(chars)
            assert bool(old.match(word)) == bool(new.match(word)), repr(word)
            checked += 1
    assert checked == sum(5 ** n for n in range(7))


def _cased():
    for code in range(0x110000):
        if 0xD800 <= code <= 0xDFFF:
            continue
        char = chr(code)
        if char.lower() != char or char.upper() != char or char.casefold() != char:
            yield char


def test_the_fold_is_the_engine_backreference_rule():
    """_BoundNameScan keys names by _fold; the engine compares a re.I
    backreference char by char. They must agree on every case-related pair,
    and folding must never move a char into or out of \\w."""
    same = re.compile(r"(.)\1", re.I | re.S)
    word = re.compile(r"\w")
    bad = []
    for char in _cased():
        partners = {char.lower()[0], char.upper()[0], char.casefold()[0], char.title()[0],
                    char.swapcase()[0], char.lower()[-1]}
        for other in partners:
            engine = same.fullmatch(char + other) is not None
            if engine != (gate._fold(char) == gate._fold(other)):
                bad.append((hex(ord(char)), hex(ord(other)), engine))
        if (word.match(char) is None) != (word.match(gate._fold(char)) is None):
            bad.append((hex(ord(char)), "word class", unicodedata.category(char)))
    assert not bad, bad[:10]
