"""Regression guard: the gate's ruff half must not die on a ruff-less interpreter.

MEASURED 2026-07-28. 8a6cdfc2 introduced a net-new ruff UP031 in the gate's OWN
source, the gate passed it, and CI went red (fixed in 11bb4dcd). Diagnosis:

  .githooks/pre-commit launches the gate through the `py` launcher, which on
  Legion resolves to a bare pythoncore build with NO ruff. The gate then shelled
  out to `sys.executable -m ruff`, i.e. that same ruff-less interpreter, got
  rc=1 with an empty stdout, parsed [] findings, and passed.

  It failed OPEN and it failed SILENTLY. 3d48e6e8 (2026-07-07) had switched the
  invocation from the `py` launcher to sys.executable to fix the OTHER channel
  (Claude PreToolUse, whose interpreter is the Python314 that owns ruff), which
  means each hardcoded choice was correct for exactly one of the two channels
  and the git-hook channel - the authoritative one - ran with a dead ruff half
  for three weeks.

The fix resolves a ruff-capable runner at call time instead of hardcoding one.
These tests pin both halves of that: a dead first candidate must be stepped
over, and a genuinely ruff-less machine must SAY SO rather than pass in silence.
"""

import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import precommit_gate as G  # noqa: E402

# A module that certainly does not exist, so `-m` exits non-zero the same way a
# ruff-less interpreter does. Spelled as a constant so the intent is readable.
_MISSING = "ruff_absent_on_this_interpreter"
_BAD = [sys.executable, "-m", _MISSING]

# Environment capability, resolved the way tests/test_skip_condition_hygiene.py
# can SEE (find_spec / shutil.which), not behind a subprocess probe it has to
# take on faith. Both forms matter: ruff can be importable by this interpreter,
# on PATH as a standalone binary, or both - and the candidate the resolution
# tests expect to win has to match whichever is actually true here.
_RUFF_IMPORTABLE = importlib.util.find_spec("ruff") is not None
_RUFF_ON_PATH = shutil.which("ruff") is not None
_GOOD = [sys.executable, "-m", "ruff"] if _RUFF_IMPORTABLE else ["ruff"]

# UP031: percent-format. The exact rule 8a6cdfc2 shipped and the gate missed.
_UP031_SOURCE = 'a = 1\nmsg = "U+%04X" % (a,)\n'

requires_ruff = pytest.mark.skipif(
    not (_RUFF_IMPORTABLE or _RUFF_ON_PATH),
    reason="ruff is installed in neither this interpreter nor PATH",
)


def _staged_repo(tmp_path: Path) -> Path:
    """A git repo with ruff.toml and one staged file carrying a net-new UP031."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Without the project ruff.toml, ruff's default select is E4/E7/E9/F and
    # UP031 is not enabled at all - the test would pass for the wrong reason.
    shutil.copy(_ROOT / "ruff.toml", repo / "ruff.toml")
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, env=env, check=True
    )
    run("init", "-q", ".")
    run("config", "user.email", "gate@test")
    run("config", "user.name", "gate")
    (repo / "victim.py").write_text("a = 1\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / "victim.py").write_text(_UP031_SOURCE, encoding="utf-8")
    run("add", "victim.py")
    return repo


def _run_gate(monkeypatch, repo: Path) -> int:
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
    return G.main()


class TestRuffResolution:
    @requires_ruff
    def test_steps_over_a_ruffless_candidate(self, monkeypatch):
        monkeypatch.setattr(G, "_ruff_candidates", lambda: [_BAD, _GOOD])
        assert G._resolve_ruff() == _GOOD

    def test_returns_none_when_no_candidate_has_ruff(self, monkeypatch):
        monkeypatch.setattr(G, "_ruff_candidates", lambda: [_BAD])
        assert G._resolve_ruff() is None

    def test_nonexistent_executable_is_survivable(self, monkeypatch):
        # OSError from a missing binary must be caught, not raised into the hook.
        monkeypatch.setattr(
            G, "_ruff_candidates", lambda: [["no_such_binary_xyz", "-m", "ruff"]]
        )
        assert G._resolve_ruff() is None

    def test_default_candidates_cover_both_hook_channels(self):
        # PreToolUse runs under Python314 pythonw (sys.executable owns ruff);
        # .githooks/pre-commit runs under the `py` launcher (may not). Both the
        # interpreter-relative and the PATH forms have to be in the list, or one
        # channel silently loses its ruff half again.
        flat = [" ".join(c) for c in G._ruff_candidates()]
        assert any(c[0] == sys.executable for c in G._ruff_candidates())
        assert any(f.startswith("ruff") for f in flat)


class TestEndToEnd:
    @requires_ruff
    def test_blocks_up031_when_first_candidate_is_ruffless(
        self, monkeypatch, tmp_path, capsys
    ):
        """THE regression. A dead first candidate must not swallow the finding."""
        repo = _staged_repo(tmp_path)
        monkeypatch.setattr(G, "_ruff_candidates", lambda: [_BAD, _GOOD])
        rc = _run_gate(monkeypatch, repo)
        err = capsys.readouterr().err
        assert rc == 2, f"gate passed a net-new UP031; stderr={err!r}"
        assert "UP031" in err

    def test_no_ruff_anywhere_warns_instead_of_passing_silently(
        self, monkeypatch, tmp_path, capsys
    ):
        """Fail-open is tolerable on a machine with no ruff; fail-SILENT is not.

        Blocking every commit on a fresh clone would wedge the headless loop, so
        the gate still exits 0 - but it has to say the ruff half did not run.
        """
        repo = _staged_repo(tmp_path)
        monkeypatch.setattr(G, "_ruff_candidates", lambda: [_BAD])
        rc = _run_gate(monkeypatch, repo)
        err = capsys.readouterr().err
        assert rc == 0
        assert "ruff" in err.lower()
        assert err.strip(), "the ruff half skipped itself without a word"
