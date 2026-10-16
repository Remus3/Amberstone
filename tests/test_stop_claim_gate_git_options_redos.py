"""CodeQL py/redos (alerts 54 / 55): the git-option loop backtracked exponentially.

The loop that skips git's leading options (`git -c k=v --no-pager ... push`)
had two sources of ambiguity, both measured on the prior file (2026-10-15):
`-c` matched both "-c ARG" and a bare option word, and `--?[\\w-]+` split any
`--long` word two ways. On a command that does NOT end in the subcommand the
engine tried every split: 33 x ` -c` took ~2 s through EV_COMMIT_CREATING,
40 took 56 s; 19 took ~2.7 s through _GIT_LEAD (`_EV_PUSH`), and 21 x
` --no-pager` (a realistic shape) ~1.3 s per pattern - past the 30 s Stop
timeout well under COMMAND_PARSE_MAX.

The rewrite (`_GIT_OPTIONS`) is the SAME language with the SAME first match:
every redundant path was removed and only redundant ones (a `-c` read as a bare
flag can only be followed by the loop exit, or by `-c PLAIN`; any other
continuation re-reaches a position the "-c ARG" reading already tried). The
oracle test below pins that against the prior loops over seeded inputs; the
one-off proof ran the prior file itself as the oracle (no difference).
"""

import random
import re
import subprocess
import sys
import time
from pathlib import Path

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

# The prior loops, verbatim (EV_COMMIT_CREATING required the -c argument,
# _GIT_LEAD made it optional). Kept as plain strings, used only as the oracle.
OLD_COMMIT_CREATING_LOOP = r"(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*"
OLD_LEAD_LOOP = r"(?:\s+-[Cc](?:\s+\S+)?|\s+--?[\w-]+(?:=\S+)?)*"

LEAD_PATTERNS = ["_EV_PUSH", "_EV_GIT_MERGE", "_EV_FETCH", "_EV_ANCESTRY", "_EV_REFLOG",
                 "_EV_GIT_RESET", "_EV_GIT_CHECKOUT", "_EV_GIT_STASH", "_EV_GIT_COMMIT_MAKER"]
ALL_PATTERNS = ["EV_COMMIT_CREATING"] + LEAD_PATTERNS


def _oracle(name):
    pattern = getattr(gate, name)
    old_loop = OLD_COMMIT_CREATING_LOOP if name == "EV_COMMIT_CREATING" else OLD_LEAD_LOOP
    assert pattern.pattern.count(gate._GIT_OPTIONS) == 1, name
    return re.compile(pattern.pattern.replace(gate._GIT_OPTIONS, old_loop), pattern.flags)


def _shapes():
    return [
        ("EV_COMMIT_CREATING", "git" + " -c" * 33 + " x"),
        ("EV_COMMIT_CREATING", "git" + " -c --=!" * 22),
        ("EV_COMMIT_CREATING", "git " + "-- -" * 24),
        ("EV_COMMIT_CREATING", "git" + " --no-pager" * 21 + " x"),
        ("_EV_PUSH", "git" + " -c" * 19 + " x"),
        ("_EV_PUSH", "git" + " -c --=!" * 15),
        ("_EV_PUSH", "git " + "-- -" * 24),
        ("_EV_PUSH", "git" + " --no-pager" * 21 + " x"),
        ("_EV_GIT_RESET", "git.exe" + " -C" * 19 + " x"),
    ]


def test_the_pathological_option_runs_are_fast():
    slow = []
    for name, text in _shapes():
        start = time.perf_counter()
        list(getattr(gate, name).finditer(text))
        elapsed = time.perf_counter() - start
        if elapsed > 0.25:
            slow.append((name, text[:40], round(elapsed, 2)))
    assert not slow, slow


# At COMMAND_PARSE_MAX the prior loops never finish, so this runs in a child
# with a hard timeout instead of hanging the suite.
_BIG_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
names = sys.argv[2].split(",")
limit = gate.COMMAND_PARSE_MAX
shapes = [("git", " -c"), ("git", " -c --=!"), ("git ", "-- -"), ("git", " --no-pager"),
          ("git.exe", " -C"), ("git", " -c -c x")]
worst = 0.0
for prefix, unit in shapes:
    text = prefix + unit * ((limit - len(prefix)) // len(unit))
    for name in names:
        start = time.perf_counter()
        list(getattr(gate, name).finditer(text))
        worst = max(worst, time.perf_counter() - start)
print(round(worst, 3))
"""


def test_option_runs_at_command_parse_max_finish_in_a_bounded_time():
    run = subprocess.run([sys.executable, "-c", _BIG_PROBE, str(REPO), ",".join(ALL_PATTERNS)],
                         capture_output=True, text=True, timeout=60, cwd=str(REPO))
    assert run.returncode == 0, run.stderr[-2000:]
    assert float(run.stdout.strip()) < 1.0, run.stdout


def _seeded_inputs(seed, count):
    rng = random.Random(seed)
    dash_c = ["-c", "-C"]
    options = ["-x", "--x", "--x=y", "-cx", "-c=1", "---", "--=!", "--no-pager", "--git-dir=x",
               "--no-ff", "-n", "--abort", "--is-ancestor", "-nv", "-q", "--", "-cc"]
    plain = ["merge", "revert", "cherry-pick", "push", "x", "merge-base", "-", "-=x", "pull",
             "fetch", "log", "reflog", "reset", "checkout", "stash", "commit", "remote", "update",
             "HEAD", "origin/main", "Merge", "merged", "push.default=x", '""', "|", ";", "&&",
             "git", "git.exe", "a.git", "feat", "--hard"]
    seps = [" ", " ", " ", "  ", "\t", "\n", " \\\n"]
    starts = ["git", "git.exe", "GIT", "x.git", "gitx", "env git", 'git""']
    for _ in range(count):
        words = [rng.choice(starts)]
        for _w in range(rng.randint(0, 10)):
            roll = rng.random()
            words.append(rng.choice(dash_c if roll < 0.4 else options if roll < 0.62 else plain))
        text = words[0]
        for word in words[1:]:
            text += rng.choice(seps) + word
        yield text


def test_the_rewrite_matches_the_prior_loops_exactly():
    oracles = {name: _oracle(name) for name in ALL_PATTERNS}
    diffs = []
    for seed in (117, 2026):
        for text in _seeded_inputs(seed, 1500):
            for variant in (text, gate.strip_command_noise(text)):
                for name in ALL_PATTERNS:
                    new = [(m.span(), m.groups()) for m in getattr(gate, name).finditer(variant)]
                    old = [(m.span(), m.groups()) for m in oracles[name].finditer(variant)]
                    if new != old:
                        diffs.append((name, variant, old, new))
    assert not diffs, diffs[:3]


def test_parity_of_a_dash_c_run_picks_the_same_subcommand():
    # Hand-checked first matches the rewrite must keep (prior file, measured):
    # an EVEN run of -c reads the next word as the subcommand first, an ODD
    # run reads it as the last -c's argument first.
    cases = [
        ("git -c merge revert", "revert"),
        ("git -c -c merge revert", "merge"),
        ("git -c -c -c merge revert", "revert"),
        ("git -c merge", "merge"),
        ("git -c -c revert", "revert"),
        ("git --no-pager -c x=y cherry-pick abc", "cherry-pick"),
    ]
    for text, sub in cases:
        match = gate.EV_COMMIT_CREATING.search(text)
        assert match is not None and match.group(1) == sub, (text, match)
        assert _oracle("EV_COMMIT_CREATING").search(text).group(1) == sub, text
