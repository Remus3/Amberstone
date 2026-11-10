"""S144-Q-163: the S144-Q-158 brace readings multiplied the stop gate's work.

S144-Q-158 walks `_launcher_scripts` behind PowerShell brace heads BESIDE the
plain reading. Each reading tried every (ESCAPES, FULL) option pair, so a
brace-headed statement cost 1 + 2 x 6 `_launcher_script` reads where it had
cost 1 + 6; with `_readings(extra=True)` also adding a brace-broken text, a
long run of `if ($y) { ... } else { ... }` statements cost about four times
what it did. And a launcher's script is walked once per caller that names it
(the raw walk, the held walk of S144-Q-157, each reading), so a nested
launcher's script was walked again at every level: three walks of the same
19,620-char innermost script for one `_has_bypass` call (measured on
6e7a1fb78 with `if ($x) { bash -c "..." }` twice nested).

Measured on 6e7a1fb78 against 24fbe16a0 (before S144-Q-158), seconds at
just under COMMAND_PARSE_MAX: `; if ($y) { bash -c x } else { git log -n 1 }`
repeated 0.124 vs 0.030; the same twice nested 0.379; verifier round 3 of
S144-Q-158 timed pathological commands at up to 0.94 s on a loaded box.

Fix, exact by construction (no count change):
- ESCAPES is read only by `env` and FULL only by a prefix command, both at
  the head `_unwrapped` reaches after keyword heads and `NAME=VALUE`
  prefixes. With neither there, every option pair gives the plain reading,
  so `_launcher_scripts` reads it once (`_wrapped_head`).
- `_has_bypass` answers each (command, depth, extra, expand) once per
  top-level call (`_BYPASS_MEMO`, a scope opened by the outermost
  `_has_bypass` or `_bypass_targets` call and closed when it returns). The
  walk is a pure function of those four, so a repeat returns the answer the
  walk would give. Nothing is kept between top-level calls.

Timing is a BACKSTOP only (child process, MIN of repeats); the deterministic
counts below decide.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import stop_claim_gate as gate

REPO = Path(__file__).resolve().parents[1]

FLAT_UNIT = "; if ($y) { bash -c x } else { git log -n 1 }"


def _nest(depth, core):
    text = core
    for level in range(depth):
        quote = "'" if level % 2 == 0 else '"'
        text = f"if ($x) {{ bash -c {quote}{text}{quote} }}"
    return text


def _count_calls(monkeypatch, name, run, keep=lambda *a: True):
    real = getattr(gate, name)
    seen = []

    def spy(*args, **kwargs):
        if keep(*args):
            seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(gate, name, spy)
    run()
    return seen


def test_flat_brace_statements_read_each_launcher_a_bounded_number_of_times(monkeypatch):
    units = 60
    command = FLAT_UNIT * units
    calls = _count_calls(monkeypatch, "_launcher_script",
                         lambda: gate._bypass_targets(command, None))
    # 6e7a1fb78: 3,900 reads (65 a unit); after the fix 900 (15). Each
    # unit is two statements read in two texts, each by the raw and the
    # held walk; with no wrapper at the head, a statement needs at most its
    # plain and its brace reading.
    assert len(calls) <= 20 * units, len(calls)


def test_a_wrapper_head_still_gets_every_option_reading(monkeypatch):
    words = gate._tokens("if ($x) { nice --adjustment 5 bash -c 'git commit -n' }"
                         .lstrip("({").rstrip(")}").strip())
    calls = _count_calls(monkeypatch, "_launcher_script",
                         lambda: gate._launcher_scripts(words, True))
    # the first read, the plain keyword reading once (its head is `($x)`,
    # no wrapper), and all 6 option pairs for the brace reading (`nice`)
    assert len(calls) == 8, len(calls)
    braced = [call for call in calls if call[1].get("braces")]
    assert len(braced) == 6, calls


def test_a_nested_launcher_script_is_walked_once_per_call(monkeypatch):
    inner = FLAT_UNIT * 40
    command = _nest(2, inner)
    calls = _count_calls(monkeypatch, "_readings",
                         lambda: gate._has_bypass(command),
                         keep=lambda text, *rest: text == inner)
    # 6e7a1fb78: 3 walks (the raw script, and again under the held walk)
    assert len(calls) == 1, len(calls)


def test_the_memo_lives_for_one_top_level_call_only():
    command = "if ($x) { bash -c 'git commit -n' }; git log -n 1"
    assert gate._BYPASS_MEMO.get() is None
    assert gate._has_bypass(command) is True
    assert gate._BYPASS_MEMO.get() is None
    assert gate._bypass_targets(command, None) == [None]
    assert gate._BYPASS_MEMO.get() is None


def test_the_memo_scope_closes_when_the_walk_raises(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("walk failed")

    monkeypatch.setattr(gate, "_readings", boom)
    with pytest.raises(RuntimeError):
        gate._has_bypass("bash -c 'git commit -n'; echo $x")
    assert gate._BYPASS_MEMO.get() is None


def test_no_answer_is_carried_into_the_next_call(monkeypatch):
    command = "if ($x) { bash -c 'git status -n' }"
    first = gate._has_bypass(command)
    monkeypatch.setattr(gate, "_git_words_bypass", lambda words: True)
    assert first is False
    assert gate._has_bypass(command) is True


# Behind a brace or keyword head, a launcher that only an option reading
# finds (env's -S escapes, a prefix option read in full) is still read.
VARIANT_ONLY = [
    r"""if ($x) { env -S 'bash\_-c\_"git commit -n"' }""",
    r"""} else { env -S 'bash -c\_"git commit -n"' }""",
    r"""then env -S 'bash\_-c\_"git commit -n"'""",
    r"""if ($x) { nohup env -S 'bash\_-c\_"git commit -n"' }""",
    "if ($x) { nice --adjustment 5 bash -c 'git commit -n' }",
    "} else { nice --adj 5 bash -c 'git commit -n' }",
    "if ($x) { sudo -h host bash -c 'git commit -n' }",
    "then timeout --sig KILL 5 bash -c 'git commit -n'",
]


@pytest.mark.parametrize("command", VARIANT_ONLY)
def test_an_option_reading_behind_a_head_still_names_the_launcher(command):
    words = gate._tokens(command.strip().lstrip("({").rstrip(")}").strip())
    scripts = gate._launcher_scripts(words, True)
    assert any("git commit -n" in script for script in scripts), scripts
    assert gate._has_bypass(command) is True


_PROBE = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from tools import stop_claim_gate as gate
size = gate.COMMAND_PARSE_MAX - 300
unit = "; if ($y) { bash -c x } else { git log -n 1 }"
def nest(depth, core):
    for level in range(depth):
        q = "'" if level % 2 == 0 else '"'
        core = "if ($x) { bash -c %s%s%s }" % (q, core, q)
    return core
def sized(depth, unit, lead=""):
    over = len(nest(depth, lead))
    return nest(depth, lead + unit * ((size - over) // len(unit)))
shapes = [sized(0, unit), sized(1, unit), sized(2, unit),
          sized(2, " } else { git log -n 1", "if ($y) { x"),
          sized(0, " } else { echo git commit -n", "if ($x) { bash -c 'git status'"),
          sized(2, "; git log -n 1; bash -c 'git log -n 1'")]
worst = 0.0
for text in shapes:
    best = None
    for _ in range(int(sys.argv[2])):
        start = time.perf_counter()
        gate._bypass_targets(text, None)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    worst = max(worst, best)
print(round(worst, 3))
"""


def test_pathological_brace_commands_stay_under_the_rm829_budget():
    run = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), "3"],
                         capture_output=True, text=True, timeout=600, cwd=str(REPO), check=False)
    assert run.returncode == 0, run.stderr[-2000:]
    assert float(run.stdout.strip()) < 1.0, run.stdout
