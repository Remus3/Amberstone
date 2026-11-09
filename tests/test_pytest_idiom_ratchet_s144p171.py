"""RM-1688 - ruff PT017, COM819 and PT013 are held at zero in the test code.

None of the three is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated --line-length 120`` (target py39) over the tracked test code: 10 findings in 8 modules.

- PT017 (7): an ``assert`` on the caught exception inside an ``except`` block, written as the
  ``try: call(); except X as e: assert ...; else: raise AssertionError`` shape (tests/test_cohort_baseline.py x2,
  tests/test_gated_g312_aram_debounce_lag.py, tests/test_gated_g506_debounce_lag.py) or the
  ``try: urlopen(); pytest.fail(); except HTTPError as e: assert`` shape (agents/agent3_testing/suite/test_file_task_api.py
  x3). Each became ``with pytest.raises(X) as excinfo:`` followed by the same assertions on ``excinfo.value``.
- COM819 (2): a trailing comma inside a one-argument call (tests/fu02_team_context/test_team_context.py,
  tests/test_panel_visibility_permode.py), removed.
- PT013 (2): ``import pytest as _pt`` inside a function (tests/test_replay_analysis.py), now a top-level
  ``import pytest``; the second, tests/test_launcher_update_hardening_pkg6b.py, is a launcher-owned test file the main
  session owns this session (lane_exclusions_s144.txt), so it is the one baseline entry.

Equivalence of the PT017 rewrite: ``pytest.raises`` fails the test when nothing is raised (replacing the ``else:
raise AssertionError`` and the ``pytest.fail`` lines), lets a different exception type propagate (as the ``except X``
did), and the assertions run against the same exception object. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("PT017", "COM819", "PT013")
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = {
    "tests/test_launcher_update_hardening_pkg6b.py",  # launcher-owned (main session); PT013 x1
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_new_pt017_com819_pt013_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_pytest_raises_and_try_except_shapes_agree(tmp_path):
    """``pytest.raises`` passes on the expected error, fails on no error and lets another error type through."""
    (tmp_path / "test_probe_raises_shapes.py").write_text(
        textwrap.dedent(
            """
            import pytest

            def boom(exc):
                raise exc("detail text")

            def test_expected():
                with pytest.raises(ValueError) as excinfo:
                    boom(ValueError)
                assert "detail" in str(excinfo.value)

            def test_nothing_raised_fails():
                with pytest.raises(ValueError):
                    pass

            def test_other_type_propagates():
                with pytest.raises(ValueError):
                    boom(KeyError)
            """
        ),
        encoding="utf-8",
        newline="\n",
    )
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
         str(tmp_path / "test_probe_raises_shapes.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False, **kwargs,
    )
    assert "2 failed, 1 passed" in proc.stdout, proc.stdout[-600:] + proc.stderr[-300:]


def test_probe_is_live():
    """Each rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = textwrap.dedent(
        """
        import pytest

        def f(g):
            try:
                g()
            except ValueError as e:
                assert 'x' in str(e)
            return foo(1, )

        def h():
            import pytest as _pt
            return _pt
        """
    )
    good = textwrap.dedent(
        """
        import pytest

        def f(g):
            with pytest.raises(ValueError) as excinfo:
                g()
            assert 'x' in str(excinfo.value)
            return foo(1)

        def h():
            return pytest
        """
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
