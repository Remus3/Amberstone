"""RM-1535 - ruff PGH003 (a blanket ``# type: ignore``) and PLW0108 (a lambda that only calls
another callable) are held at zero in production code.

Neither rule is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target
py39): production code carried 6 PGH003 sites (the optional-import fallbacks in
``agents/supervisor.py``, ``core/build_order.py``, ``core/build_order_precompute.py``,
``ops/audit/item_ah_drift_check.py``, ``ops/rc_state_validator.py`` and ``tools/ds_feed_index.py``)
and 5 PLW0108 sites (all in ``tools/run_phase2_perf.py``, a one-shot benchmark script).

PGH003: a bare ``# type: ignore`` silences EVERY checker error on the line, so a later real error on
the same import would be hidden. ``# type: ignore[import]`` silences only the import-resolution
family (mypy's parent code of import-not-found / import-untyped). Comment-only change.

PLW0108: ``lambda: f()`` is ``f`` when ``f`` is evaluated once and not rebound before the call.
Every site passes the callable to ``_bench`` which calls it ``reps`` times with no arguments; the
bound method or classmethod is resolved once at the call to ``_bench`` instead of once per call.
Nothing rebinds ``mc`` or the imported names in between.

No baseline: the count is zero, so ``test_no_findings`` is exact. Scope: production code.
``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the ``agents/agent3_testing/suite`` test
suite and ``tools/ds_cross_eval`` are out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("PGH003", "PLW0108")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "agents/supervisor.py",
    "core/build_order.py",
    "core/build_order_precompute.py",
    "ops/audit/item_ah_drift_check.py",
    "ops/rc_state_validator.py",
    "tools/ds_feed_index.py",
    "tools/run_phase2_perf.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_findings() -> list[tuple[str, str, int]]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            out.append((rel, d["code"], d["location"]["row"]))
    return out


def test_no_findings(tree_findings):
    assert not tree_findings, f"ruff {_RULES} findings (file, rule, line): {tree_findings}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_probe_is_live():
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    found = _ruff(
        ["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
        stdin=("import x  # type: ignore\n"
               "def f(g):\n    return [g(lambda: x.run())]\n"),
    )
    assert {d["code"] for d in found} == set(_RULES), found


def test_bare_callable_equals_lambda_wrapper():
    """The premise of the PLW0108 fix: a bound method / classmethod handed over directly behaves
    like the zero-argument lambda that wrapped it, for every repeated call."""
    class Box:
        def __init__(self):
            self.n = 0

        def bump(self):
            self.n += 1
            return self.n

        @classmethod
        def make(cls):
            return cls

    a, b = Box(), Box()
    wrapped, direct = (lambda *_: a.bump()), b.bump  # the pre-fix shape, spelled so ruff stays quiet
    assert [wrapped() for _ in range(3)] == [direct() for _ in range(3)] == [1, 2, 3]
    wrapped_cls, direct_cls = (lambda *_: Box.make()), Box.make
    assert wrapped_cls() is direct_cls() is Box
