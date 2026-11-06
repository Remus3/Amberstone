"""RM-1749 - ruff RUF022 (unsorted ``__all__``) and RUF023 (unsorted ``__slots__``) held at zero everywhere else.

Closes the series RM-1747 (``tools/``, ``lib/``, ``tft/``, ``game_reader/``, ``vision_server/``, ``agents/`` outside
DS) and RM-1748 (``core/``). Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 3 findings outside
those scopes, in ``ops/audit/ds_perm_swarm/__init__.py``, ``oss/win32_atomic_io/src/win32_atomic_io/__init__.py`` and
``tests/test_no_process_wide_stdlib_fakes_rm801.py``. The order of an ``__all__`` or ``__slots__`` carries no meaning
for an import or an attribute lookup, and none of the three modules iterates its own tuple (checked by grep).

The held scope here is every tracked ``.py`` file NOT under ``core/`` (P-249's) and NOT under the two named fences:

- ``agents/daemon_slayer/``: the DS lane's tree (about 50 findings), untouched by the repo lane.
- ``ops/fleet_kit/``: vendored byte-for-byte and pinned by its MANIFEST, so a local edit fails.

The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. The held scope has no baseline.
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

_RULES = ("RUF022", "RUF023")
# Scopes held by a sibling ratchet or fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "core/": "held by test_sorted_all_and_slots_core_ratchet_s144p249",
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
_FIXED = (
    "ops/audit/ds_perm_swarm/__init__.py",
    "oss/win32_atomic_io/src/win32_atomic_io/__init__.py",
    "tests/test_no_process_wide_stdlib_fakes_rm801.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def rest_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_nothing_outside_the_fenced_scopes_has_unsorted_all_or_slots(rest_counts):
    assert not rest_counts, f"ruff {_RULES} findings outside the fenced scopes, file: count: {rest_counts}"


def test_the_fixed_modules_are_tracked_and_in_the_held_scope():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel


def test_the_fences_name_real_directories():
    for prefix in _NOT_THIS_SCOPE:
        assert (REPO_ROOT / prefix).is_dir(), prefix


@pytest.mark.parametrize(
    ("rule", "probe"),
    [
        ("RUF022", "__all__ = ['b', 'a']\n"),
        ("RUF023", "class C:\n    __slots__ = ('b', 'a')\n"),
    ],
)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"] == rule for d in found), (rule, [d["code"] for d in found])
