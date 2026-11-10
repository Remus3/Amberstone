"""RM-1687 - ruff PT022 (a fixture that ``yield``s with no teardown after it) is held at zero in the test code.

PT022 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39): 6 findings in 6 modules - ``tests/conftest.py`` (the session-scoped
``redirect_spec_loaded_tool_logs_to_tmp``), four ``tests/test_*.py`` autouse fixtures
(``fresh_caches`` x2, ``_reset_fake``, ``_reset``) and ``agents/agent3_testing/suite/conftest.py``
(``_fake_headless_route``). Each ended in a bare trailing ``yield`` with no statement after it, so the
generator never had a teardown half. None sits in a main-session-owned module or in a file another lane
branch changed, so the baseline is empty. The rule has no safe fix; each trailing ``yield`` was deleted by
hand, turning the generator fixture into a plain function fixture.

Equivalence: pytest runs a plain fixture's body at setup exactly as it runs the code before the ``yield``
of a generator fixture, and a generator whose ``yield`` is its last statement resumes into nothing at
teardown. Monkeypatch undo is owned by the ``monkeypatch`` fixture, not by these bodies. The run uses NO
config (``--isolated``) so a per-file-ignore cannot hide a finding. A fixture that ``yield``s INSIDE a
``with`` block, or has code after the ``yield``, is not flagged and is not touched.
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

_RULES = ("PT022",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = set()


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


def test_no_new_pt022_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_trailing_yield_and_plain_return_fixtures_set_up_the_same_state(tmp_path):
    """A fixture that only sets state before a trailing ``yield`` behaves like the plain function it becomes."""
    (tmp_path / "test_probe_fixture_shapes.py").write_text(
        textwrap.dedent(
            """
            import pytest

            SEEN = []

            @pytest.fixture
            def with_yield():
                SEEN.append("yield")
                yield

            @pytest.fixture
            def plain():
                SEEN.append("plain")

            def test_both(with_yield, plain):
                assert SEEN == ["yield", "plain"]
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
         str(tmp_path / "test_probe_fixture_shapes.py")],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False, **kwargs,
    )
    assert proc.returncode == 0, proc.stdout[-600:] + proc.stderr[-300:]
    assert "1 passed" in proc.stdout, proc.stdout[-300:]


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "import pytest\n\n@pytest.fixture\ndef f():\n    x = 1\n    yield\n"
    good = "import pytest\n\n@pytest.fixture\ndef f():\n    x = 1\n"
    teardown = "import pytest\n\n@pytest.fixture\ndef f():\n    x = 1\n    yield\n    x = 2\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=teardown) == []
