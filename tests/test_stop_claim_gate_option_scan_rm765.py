"""RM-765: the git-option patterns kept a QUADRATIC residue after the s118
exponential fix (LEDGER 1728). RM-814 follow-up: the decision is a
deterministic work count; wall-clock is a min-of-N backstop only.

Re-measured at adbd2c93f (seconds per pattern, worst of the ten _GIT_OPTIONS
patterns): `git -c git -c git ...` 0.08 / 0.31 / 1.31 at 5k / 10k / 20k
characters, ` --git` 0.16 / 0.55 / 2.13, ` -c x.git` 0.07 / 0.32 / 1.06,
` --x=git` 0.09 / 0.36 / 1.40 - four times the time for twice the input.
Mechanism: finditer re-tries the pattern at EVERY `git` word, and each failed
try re-reads the whole option run that follows it, so a run holding k `git`
words costs k runs. COMMAND_PARSE_MAX caps only the sub-agent parsers; the
main-thread audit runs EV_COMMIT_CREATING / _EV_PUSH / _EV_GIT_MERGE on every
main command uncapped, so the cap did not bound the residue there.

The fix (`_OptionScan`) keeps every regex as the ONLY authority for a match
and skips only the starts a failed try PROVES dead (proof at _OptionScan).
The differential test below pins finditer / search against the plain regex.
"""

import random
import re
import subprocess
import sys
from pathlib import Path

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

NAMES = ["EV_COMMIT_CREATING", "_EV_PUSH", "_EV_GIT_MERGE", "_EV_FETCH", "_EV_ANCESTRY",
         "_EV_REFLOG", "_EV_GIT_RESET", "_EV_GIT_CHECKOUT", "_EV_GIT_STASH",
         "_EV_GIT_COMMIT_MAKER"]
MAIN_THREAD = ["EV_COMMIT_CREATING", "_EV_PUSH", "_EV_GIT_MERGE"]

SHAPES = [("git", " -c git"), ("git", " --git"), ("git", " -c x.git"), ("git", " --x=git"),
          ("git.exe", " -C git.exe"), ("GIT", " -c GIT"), ("git", " -c -c git")]

# Timing is a BACKSTOP only (RM-814 follow-up); the bound that decides is the
# deterministic work count below. Run in a child with a hard timeout; each
# case keeps the MIN of REPEATS samples so a descheduled sample on a loaded box
# cannot fail it. Before the fix the worst case took 1.3-2.1 s at the cap, so
# the generous bounds still catch the residue at twice the cap.
REPEATS = 5
_PROBE = r"""
import ast, sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
names = sys.argv[2].split(",")
size = int(float(sys.argv[3]) * gate.COMMAND_PARSE_MAX)
repeats = int(sys.argv[4])
shapes = ast.literal_eval(sys.argv[5])
worst, where = 0.0, ""
for prefix, unit in shapes:
    text = prefix + unit * ((size - len(prefix)) // len(unit))
    for name in names:
        for call in ("finditer", "search"):
            best = None
            for _ in range(repeats):
                start = time.perf_counter()
                if call == "finditer":
                    list(getattr(gate, name).finditer(text))
                else:
                    getattr(gate, name).search(text)
                elapsed = time.perf_counter() - start
                best = elapsed if best is None else min(best, elapsed)
            if best > worst:
                worst, where = best, f"{name}.{call} {prefix + unit!r}"
print(round(worst, 3), where)
"""


def _probe(names, scale):
    run = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), ",".join(names), str(scale),
                          str(REPEATS), repr(SHAPES)],
                         capture_output=True, text=True, timeout=300, cwd=str(REPO))
    assert run.returncode == 0, run.stderr[-2000:]
    worst, _, where = run.stdout.strip().partition(" ")
    return float(worst), where


def test_dead_option_runs_at_command_parse_max_are_fast():
    worst, where = _probe(NAMES, 1)
    assert worst < 1.0, (worst, where)


def test_the_uncapped_main_thread_patterns_stay_fast_past_the_cap():
    # audit() runs these three on every main-thread command with no length cap.
    worst, where = _probe(MAIN_THREAD, 2)
    assert worst < 2.0, (worst, where)


def _try_cost(scan, text, start):
    """Upper bound on what one failed try at START reads: its head, then the
    readable option run after it (the loop cannot advance past that run, and
    the s118 rewrite made each step unambiguous). A head ending inside a word
    costs just the head (the loop needs whitespace first)."""
    head_end = scan._head.match(text, start).end()
    return max(gate._option_run_end(text, head_end), head_end) - start


def test_a_dead_option_run_is_read_once(monkeypatch):
    """Deterministic work bound: summed over the tries the scan makes, the
    reading cost stays within twice the text, where trying every head (the
    plain regex) costs about n * n / (2 * unit)."""
    text_size = gate.COMMAND_PARSE_MAX
    for prefix, unit in SHAPES:
        text = prefix + unit * ((text_size - len(prefix)) // len(unit))
        for name in NAMES:
            scan = getattr(gate, name)
            starts = []
            real = scan.regex

            class _Counting:
                def match(self, s, pos=0, _real=real, _starts=starts):
                    _starts.append(pos)
                    return _real.match(s, pos)

                def __getattr__(self, attr, _real=real):
                    return getattr(_real, attr)

            monkeypatch.setattr(scan, "regex", _Counting())
            for call in ("finditer", "search"):
                starts.clear()
                if call == "finditer":
                    list(scan.finditer(text))
                else:
                    scan.search(text)
                work = sum(_try_cost(scan, text, s) for s in starts)
                assert work <= 2 * len(text), (name, call, prefix + unit, len(starts), work)
            monkeypatch.setattr(scan, "regex", real)
    scan = gate._EV_PUSH
    text = "git" + " -c git" * ((text_size - 3) // 7)
    every_head = sum(_try_cost(scan, text, m.start()) for m in scan._head.finditer(text))
    assert every_head > 100 * len(text), "the cost model does see the plain regex's residue"


def test_every_option_pattern_uses_the_scan():
    """By construction, so a new _GIT_OPTIONS pattern cannot reopen the residue."""
    found = sorted(name for name, value in vars(gate).items()
                   if hasattr(value, "pattern") and isinstance(value.pattern, str)
                   and gate._GIT_OPTIONS in value.pattern)
    assert found == sorted(NAMES), found
    unwrapped = [name for name in found if not isinstance(getattr(gate, name), gate._OptionScan)]
    assert not unwrapped, unwrapped


def _plain(name):
    scan = getattr(gate, name)
    return re.compile(scan.pattern, scan.flags)


def _fuzz_inputs(seed, count):
    rng = random.Random(seed)
    dash_c = ["-c", "-C"]
    gitty = ["git", "git.exe", "GIT", "Git.EXE", "x.git", "a/git", "--git", "--x=git",
             "--x-git", "-cgit", "git.exex", "--x-git.exe", "x.git.exe", "-c=git", "git;",
             "git|x", "gitx", "git.ex", "-C=git.exe"]
    options = ["-x", "--x", "--x=y", "-cx", "-c=1", "---", "--=!", "--no-pager", "--git-dir=x",
               "--no-ff", "-n", "--abort", "--is-ancestor", "-nv", "-q", "--", "-cc", "-",
               "-=x", "--hard", "-g", "--walk-reflogs"]
    subs = ["merge", "revert", "cherry-pick", "push", "merge-base", "pull", "fetch", "log",
            "reflog", "reset", "checkout", "stash", "commit", "remote", "update", "Merge",
            "PUSH", "remote\tupdate"]
    plain = ["x", "HEAD", "origin/main", "abc1234", "push.default=x", '""', "|", ";", "&&",
             "&", ">", "2>&1", "feat", "a.git", "(", "<x"]
    seps = [" ", " ", " ", " ", "  ", "\t", "\n", " \\\n", "", ";", "|", "&&"]
    for _ in range(count):
        words = [rng.choice(["git", "git.exe", "GIT", "x.git", "env git", "--git"])]
        for _w in range(rng.randint(0, 14)):
            roll = rng.random()
            pool = (dash_c if roll < 0.3 else gitty if roll < 0.55 else options if roll < 0.7
                    else subs if roll < 0.88 else plain)
            words.append(rng.choice(pool))
        text = words[0]
        for word in words[1:]:
            text += rng.choice(seps) + word
        if rng.random() < 0.05:
            text = text * rng.randint(5, 40)
        yield text


def test_the_scan_matches_the_plain_regex_exactly():
    plains = {name: _plain(name) for name in NAMES}
    diffs, compared = [], 0
    for seed in (765, 2026):
        for text in _fuzz_inputs(seed, 1500):
            for variant in (text, gate.strip_command_noise(text)):
                for name in NAMES:
                    scan, plain = getattr(gate, name), plains[name]
                    new = [(m.span(), m.groups()) for m in scan.finditer(variant)]
                    old = [(m.span(), m.groups()) for m in plain.finditer(variant)]
                    first_new, first_old = scan.search(variant), plain.search(variant)
                    same_first = (first_new is None) == (first_old is None) and (
                        first_new is None or (first_new.span(), first_new.groups())
                        == (first_old.span(), first_old.groups()))
                    compared += 1
                    if new != old or not same_first:
                        diffs.append((name, variant, old, new))
    assert compared == 2 * 1500 * 2 * len(NAMES)
    assert not diffs, diffs[:3]


def test_a_later_start_can_match_where_an_earlier_one_failed():
    """The skip is NOT "everything after a failed git": here the first try
    fails (`--x-git.exe` is no option word, so the run dies on it) and the
    `git.exe` inside that word is a real start. Hand-checked on the plain regex."""
    text = "git --x-git.exe push origin"
    assert _plain("_EV_PUSH").search(text).span() == (8, len(text))
    assert gate._EV_PUSH.search(text).span() == (8, len(text))
    # Every start fails: each run dies on `x`, which no `-c` precedes.
    text = "git -c git -c git x push"
    assert _plain("_EV_PUSH").search(text) is None
    assert gate._EV_PUSH.search(text) is None


def test_the_scan_still_reads_like_a_pattern():
    scan = gate._EV_PUSH
    assert scan.pattern.count(gate._GIT_OPTIONS) == 1
    assert scan.flags & re.I
    assert scan.match("git push x").group(1) == " x", "other methods delegate"
