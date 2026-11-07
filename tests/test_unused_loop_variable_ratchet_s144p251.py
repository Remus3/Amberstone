"""RM-1750 - ruff B007 (unused loop control variable) held at zero outside two named fences.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 15 findings outside the fences, 14 in test
code (the test modules and ``agents/agent3_testing/suite``) and 1 in ``tools/stop_claim_gate.py``. Each unused
name now carries the dummy prefix (``_i``, ``_mode``, ``_code``, ``_turn``, ``_pos``, ``_pair``) or is dropped
(``.values()`` for a dict key that was never read). The one exception is the ``for last in ...: pass`` idiom in
``tests/test_xdist_suite_fragments_s144q33.py``, which read the loop variable only AFTER the loop; it is now a
list and a ``[-1]`` index. No other behaviour changes: a loop variable that nothing reads cannot be observed.

CORRECTED s152 (F4): the ``_turn`` rename in ``tools/stop_claim_gate.py`` DID change behaviour. B007 cannot see a
read from a nested function, and ``audit()``'s ``flag()`` read ``turn`` that way, so every finding was keyed on
``""`` and a claim restated in a later turn read as already surfaced. ``flag()`` now takes ``turn`` as a parameter.
Before renaming a B007 hit, grep the enclosing function for a nested ``def`` / ``lambda`` that reads the name.

The held scope is every tracked ``.py`` file NOT under the two fences:

- ``agents/daemon_slayer/``: the DS lane's tree (30 findings), untouched by the repo lane.
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

_RULE = "B007"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
_FIXED = (
    "agents/agent3_testing/suite/test_round12.py",
    "agents/agent3_testing/suite/test_round14.py",
    "agents/agent3_testing/suite/test_round18.py",
    "tests/test_arm_confirm_server_gate.py",
    "tests/test_cost_health_watchdog.py",
    "tests/test_ds_feed_index.py",
    "tests/test_loadout_pollution_cleanup_item213.py",
    "tests/test_moon_sync_poller.py",
    "tests/test_obs_recorder.py",
    "tests/test_session_hygiene.py",
    "tests/test_xdist_suite_fragments_s144q33.py",
    "tools/stop_claim_gate.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
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


def test_nothing_outside_the_fenced_scopes_has_an_unused_loop_variable(held_counts):
    assert not held_counts, f"ruff {_RULE} findings outside the fenced scopes, file: count: {held_counts}"


def test_the_fixed_modules_are_tracked_and_in_the_held_scope():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel


def test_the_fences_name_real_directories():
    for prefix in _NOT_THIS_SCOPE:
        assert (REPO_ROOT / prefix).is_dir(), prefix


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin="for i in range(3):\n    pass\n")
    assert any(d["code"] == _RULE for d in found), [d["code"] for d in found]


def test_a_dummy_prefixed_variable_is_not_reported():
    """The fix the sweep applied is the one B007 accepts, so the held scope cannot be satisfied vacuously."""
    assert not _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin="for _i in range(3):\n    pass\n")
