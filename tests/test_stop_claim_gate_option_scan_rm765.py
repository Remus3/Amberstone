"""RM-765: the git-option patterns kept a QUADRATIC residue after the s118
exponential fix (LEDGER 1728).

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

# Run in a child with a hard timeout: before the fix these take seconds each.
_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
names = sys.argv[2].split(",")
size = int(float(sys.argv[3]) * gate.COMMAND_PARSE_MAX)
shapes = [("git", " -c git"), ("git", " --git"), ("git", " -c x.git"), ("git", " --x=git"),
          ("git.exe", " -C git.exe"), ("GIT", " -c GIT"), ("git", " -c -c git")]
worst, where = 0.0, ""
for prefix, unit in shapes:
    text = prefix + unit * ((size - len(prefix)) // len(unit))
    for name in names:
        for call in ("finditer", "search"):
            start = time.perf_counter()
            result = getattr(gate, name).finditer(text) if call == "finditer" else None
            if result is not None:
                list(result)
            else:
                getattr(gate, name).search(text)
            elapsed = time.perf_counter() - start
            if elapsed > worst:
                worst, where = elapsed, f"{name}.{call} {prefix + unit!r}"
print(round(worst, 3), where)
"""


def _probe(names, scale):
    run = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), ",".join(names), str(scale)],
                         capture_output=True, text=True, timeout=300, cwd=str(REPO))
    assert run.returncode == 0, run.stderr[-2000:]
    worst, _, where = run.stdout.strip().partition(" ")
    return float(worst), where


def test_dead_option_runs_at_command_parse_max_are_fast():
    worst, where = _probe(NAMES, 1)
    assert worst < 0.25, (worst, where)


def test_the_uncapped_main_thread_patterns_stay_fast_past_the_cap():
    # audit() runs these three on every main-thread command with no length cap.
    worst, where = _probe(MAIN_THREAD, 2)
    assert worst < 0.5, (worst, where)


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
