"""S144-P-541 - ruff PTH106 / PTH107 (``os.rmdir`` / ``os.remove``) held at zero.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 36 findings in five files. All became pathlib:
``tests/test_obj_participation.py`` (seven ``tearDown`` pairs plus one mid-test delete) and
``tests/test_postmortem_analyze.py`` (seven pairs) delete a ``pathlib.Path`` database and its ``mkdtemp`` directory,
``tests/test_match_metrics_true_audit_s144.py`` and ``tests/test_db_schema_true_audit_s144t172.py`` delete a ``Path``
fixture file, and ``tools/ddragon_mirror_refresh.py`` unlinks a symlink / junction alias of a version directory (``d`` is a
``Path`` from the version listing, so ``d.rmdir()`` is the same ``os.rmdir`` call). ``Path.unlink`` and ``Path.rmdir``
call ``os.unlink`` / ``os.rmdir`` on the same path, so nothing behavioural moves; the three test files whose only ``os``
use was these calls drop the import.

The ratchet is ZERO, with no baseline: nothing is left to hold. ``ops/fleet_kit/`` is vendored byte-for-byte and fenced
(it holds no finding today either). The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding,
and ``--preview`` because the PTH family differs under it.
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

_RULES = "PTH106,PTH107"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
_FIXED = (
    "tests/test_obj_participation.py",
    "tests/test_postmortem_analyze.py",
    "tests/test_match_metrics_true_audit_s144.py",
    "tests/test_db_schema_true_audit_s144t172.py",
    "tools/ddragon_mirror_refresh.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_the_tree_holds_zero_findings(held_counts):
    assert not held_counts, f"ruff {_RULES} findings, file: count: {held_counts}"


def test_the_fixed_modules_are_tracked_and_in_scope():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: both rules fire on the pattern each exists for."""
    probe = (
        "import os\n"
        'os.rmdir("a")\n'
        'os.remove("a")\n'
    )
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH106", "PTH107"]


def test_the_fence_names_only_a_vendored_tree():
    assert set(_NOT_THIS_SCOPE) == {"ops/fleet_kit/"}
    assert (REPO_ROOT / "ops" / "fleet_kit").is_dir()
