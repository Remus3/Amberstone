"""RM-451: nothing but a real hook fire may append to the LIVE hook log.

WHY THIS EXISTS. `ops/runtime/hook_invocations.jsonl` is read by the responder
dry cycle, which since RM-434 treats a null-session row during a known-child
cycle as a VIOLATION. Measured 2026-09-16: 9 of 762 live rows carried a null
session. 7 of them record `stdin: tty` and 2 predate that field. All 5 of the
2026-09-16 rows were attributed by timestamp to AGENT BASH CALLS running the
file by hand, not to a test: a probe script that `runpy`-executed the live
`tools/rc_facts.py` as `__main__` three times (3 rows inside 3 seconds), and a
subagent running `python tools/rc_facts.py` twice (2 rows, 3 seconds apart).
Every real fire in the log (753 rows) carries a JSON payload.

On Windows the NUL device reports `isatty() == True`, so a child started with
`stdin=DEVNULL` - or from a harness whose own stdin is NUL - lands in the `tty`
branch. That is why a hand run records `stdin: tty` without any terminal.

Two defences, each asserted here:

1. `record_invocation` refuses a payload-less row whose stdin was a tty. A
   Claude Code hook fire always pipes a JSON payload, so this refuses only the
   hand run. Every other payload-less state (none / empty / notdict / error)
   still records, because those diagnose a REAL misfire.
2. Under pytest `RC_HOOK_LOG` points at a tmp file (tests/conftest.py), so any
   test - in-process or a child inheriting the environment - resolves away
   from the repo's live log.

Assertions are on the RESOLVED PATH and on rows attributed to the child's pid,
never on a whole-file digest of the live log: other live sessions append to it
continuously (the RM-434 flake class), and in a worktree it does not exist, so
a hash comparison there would pass vacuously.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tools import rc_facts  # noqa: E402

_PY = sys.executable
_LIVE = (_ROOT / "ops" / "runtime" / "hook_invocations.jsonl").resolve()
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


# ------------------------------------------------ defence 2: path under pytest


def test_live_log_anchor_is_the_repo_runtime_path():
    """Anchor: the path the other arms compare against is really the default.

    Without this, a typo in `_LIVE` would make every `!=` below pass forever.
    """
    saved = os.environ.pop("RC_HOOK_LOG", None)
    try:
        assert rc_facts.invocation_log_path().resolve() == _LIVE
    finally:
        if saved is not None:
            os.environ["RC_HOOK_LOG"] = saved


def test_pytest_resolves_the_hook_log_away_from_the_live_log():
    assert os.environ.get("RC_HOOK_LOG"), "RC_HOOK_LOG is not set under pytest"
    assert rc_facts.invocation_log_path().resolve() != _LIVE


def test_a_child_process_inherits_the_redirect():
    """A subprocess cannot be handed `path=`; it must inherit the redirect."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from tools.rc_facts import invocation_log_path; "
            "print(invocation_log_path().resolve())")
    r = subprocess.run([_PY, "-c", code, str(_ROOT)], capture_output=True, text=True,
                       timeout=60, creationflags=_NO_WINDOW)
    assert r.returncode == 0, r.stderr
    resolved = Path(r.stdout.strip())
    assert str(resolved), "child printed no path"
    assert resolved != _LIVE


def test_real_cli_under_pytest_writes_its_row_to_the_redirect_not_the_live_log():
    """End to end through the real `__main__` block, attributed by child pid.

    `--inbox-only` performs no port / HTTP / LCU probe. An EMPTY PIPE is used
    rather than DEVNULL because it is a non-tty on every OS, so the row is NOT
    refused by defence 1 and this arm isolates defence 2.
    """
    redirect = Path(os.environ["RC_HOOK_LOG"])
    proc = subprocess.Popen([_PY, str(_ROOT / "tools" / "rc_facts.py"), "--inbox-only"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    proc.communicate(input=b"", timeout=60)
    assert proc.returncode == 0
    mine = [r for r in _rows(redirect) if r.get("pid") == proc.pid]
    assert len(mine) == 1, f"expected one row for pid {proc.pid} in {redirect}"
    assert mine[0]["stdin"] == "empty"
    assert not [r for r in _rows(_LIVE) if r.get("pid") == proc.pid]


# ------------------------------------------------ defence 1: refuse a hand run


def test_a_payloadless_tty_run_writes_no_hook_row(tmp_path):
    log = tmp_path / "hooks.jsonl"
    rc_facts.record_invocation("SessionStart", {}, path=log, stdin_state="tty")
    rc_facts.record_invocation("UserPromptSubmit", None, path=log, stdin_state="tty")
    assert not log.exists(), "a hand run on a tty wrote a null-session row"


# RM-459 (1). DECISION: the refused tty run leaves a MARKER ROW in a SIDECAR
# (`<log stem>.skipped.jsonl`, beside the resolved hook log), never a row in the
# hook log itself and never nothing. Why each alternative loses:
#   - nothing (RM-451 as shipped): a real fire that ever arrived this way would
#     vanish without trace, and after-the-fact auditability is this log's only
#     purpose.
#   - a marker row IN the hook log: `runner.hook_log_violations` flags any
#     null-session row appended during a known-child cycle, so it reinstates
#     exactly the dry-cycle red RM-451 removed, and changing that rule is
#     responder grammar this row may not touch.
#   - a stderr line only: gone when the process exits, so it answers nothing
#     after the fact.
# The sidecar path derives from the resolved log path, so `RC_HOOK_LOG` (and the
# per-worker redirect in tests/conftest.py) moves it too.


def test_skip_marker_path_sits_beside_the_log_and_is_not_the_log(tmp_path):
    log = tmp_path / "hooks.jsonl"
    marker = rc_facts.skipped_invocation_log_path(log)
    assert marker == tmp_path / "hooks.skipped.jsonl"
    assert marker != log
    live = rc_facts.skipped_invocation_log_path(_LIVE)
    assert live.name == "hook_invocations.skipped.jsonl"
    assert live.parent == _LIVE.parent


def test_a_payloadless_tty_run_leaves_one_skip_marker_per_refusal(tmp_path):
    log = tmp_path / "hooks.jsonl"
    rc_facts.record_invocation("SessionStart", {}, path=log, stdin_state="tty")
    rc_facts.record_invocation("UserPromptSubmit", None, path=log, stdin_state="tty")
    rows = _rows(rc_facts.skipped_invocation_log_path(log))
    assert [r["event"] for r in rows] == ["SessionStart", "UserPromptSubmit"]
    for r in rows:
        assert r["reason"] == "tty-no-payload"
        assert r["stdin"] == "tty"
        assert r["pid"] == os.getpid()
        assert "session" not in r, "a marker must not look like a hook row"
    assert not log.exists()


@pytest.mark.parametrize("state", ["none", "empty", "notdict", "error", "n/a", "json"])
def test_no_skip_marker_unless_the_row_was_refused(tmp_path, state):
    log = tmp_path / "hooks.jsonl"
    rc_facts.record_invocation("SessionStart", {}, path=log, stdin_state=state)
    rc_facts.record_invocation("SessionStart", {"session_id": "s-2"}, path=log, stdin_state="tty")
    assert not rc_facts.skipped_invocation_log_path(log).exists()


def test_skip_marker_follows_the_pytest_redirect_not_the_live_tree():
    redirect = rc_facts.invocation_log_path()
    marker = rc_facts.skipped_invocation_log_path(redirect)
    assert marker.resolve().parent == Path(os.environ["RC_HOOK_LOG"]).resolve().parent
    assert marker.resolve() != rc_facts.skipped_invocation_log_path(_LIVE).resolve()


def test_skip_marker_write_failure_never_raises(tmp_path):
    """A logger that failed would convert a working hook into a broken one."""
    log = tmp_path / "hooks.jsonl"
    rc_facts.skipped_invocation_log_path(log).mkdir()  # occupy the marker path
    rc_facts.record_invocation("SessionStart", {}, path=log, stdin_state="tty")
    assert not log.exists()


def test_a_tty_run_that_carries_a_payload_still_records(tmp_path):
    """The refusal is keyed on the ABSENT payload, never on the tty alone."""
    log = tmp_path / "hooks.jsonl"
    rc_facts.record_invocation("SessionStart", {"session_id": "s-1", "source": "startup"},
                               path=log, stdin_state="tty")
    rows = _rows(log)
    assert len(rows) == 1 and rows[0]["session"] == "s-1"


@pytest.mark.parametrize("state", ["none", "empty", "notdict", "error", "n/a"])
def test_other_payloadless_states_still_record(tmp_path, state):
    """These diagnose a REAL misfire (pythonw with no stdin, an empty pipe)."""
    log = tmp_path / "hooks.jsonl"
    rc_facts.record_invocation("SessionStart", {}, path=log, stdin_state=state)
    rows = _rows(log)
    assert len(rows) == 1
    assert rows[0]["payload"] is False and rows[0]["stdin"] == state
