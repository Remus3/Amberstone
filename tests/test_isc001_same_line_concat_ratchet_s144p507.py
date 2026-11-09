"""ISC001 - two string literals on ONE line with no operator or comma between them (S144-P-507).

``["a" "b", "c"]`` is the classic missing-comma bug: the two literals fuse into ``"ab"`` and the list is
one item short, with no error anywhere. ruff.toml does not select ISC001, and the neighbouring ratchets
only mention it in passing (test_isc002_backslash_concat_ratchet_s144p237 and
test_precedence_and_dead_branch_ratchet_s144p112 each say its only hits are in ``ops/rc_supervisor.py``),
so nothing held that count.

Measured 2026-11-09 with ``ruff check --isolated`` (target py39) over every tracked ``.py`` file
(production, ``tests/``, ``agents/daemon_slayer`` and ``agents/agent3_testing`` included): 2 findings, both in
the frozen ``ops/rc_supervisor.py`` (lines of the ``resolved_decisions.json`` startup errors, where two
f-strings sit on one line with a run of spaces between them). A frozen file takes no edit from a lane, so
those two stay as the baseline, which only shrinks. A tokenizer probe over the production files found the
same two and no others (``ISC004``, the multi-line wrapped-string shape, has about 150 deliberate hits and is a
style rule, not this bug class: each one was read as an intended wrap).

A baseline row that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere else fails ``test_no_new_findings``. ``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The
run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
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

_RULE = "ISC001"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)
# file -> finding count that stays (frozen file; module docstring). Only shrinks.
_BASELINE = {
    "ops/rc_supervisor.py": 2,
}


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
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_baseline_names_only_a_frozen_file():
    """The only reason a row may stay is a frozen file (CLAUDE.md); anything else is fixed, not baselined."""
    frozen_text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for rel in _BASELINE:
        assert f"`{rel}`" in frozen_text, rel


def test_probe_is_live():
    """The isolated run reports a minimal missing-comma offender, so an empty tree result is a real scan."""
    probe = 'ITEMS = ["alpha" "beta", "gamma"]\n'
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {_RULE}


def test_a_comma_separated_list_is_quiet():
    probe = 'ITEMS = ["alpha", "beta", "gamma"]\n'
    assert _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe) == []
