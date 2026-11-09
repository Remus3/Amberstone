"""SIM115 in test code - open() without a context manager (S144-P-488).

The production ratchet (tests/test_sim115_open_context_prod_ratchet_s144p210.py) leaves tests/ and
tools/tests/ out of scope. Measured 2026-11-09 with ``ruff check --isolated`` (target py39): the two
trees carried 35 findings in 15 files. Eighteen in eleven files are one-shot ``open(p).read()`` reads
(a module's own source read to assert it is ASCII, holds no ``.tmp`` name, or imports no heavy
dependency). Each leaked its handle until the interpreter collected it, which on Windows can pin the
file and fires a ResourceWarning under ``-W error``. They now read inside
``with open(...) as fh:`` (same file, mode and encoding, so the same decoded value).

The 15 that stay are deliberate and are the baseline below, which only shrinks:
- ``tests/test_routes_pickban.py`` (14) and ``tests/test_pickban_systems_p1l2.py`` (1) create a scratch
  db path with ``tempfile.NamedTemporaryFile(delete=False)`` and close it on the next line; only the name
  is wanted and ``tearDown`` unlinks it.
- ``tests/test_log_rotation_rm718a.py`` and ``tests/test_moon_sync_poller.py`` held a handle open ON
  PURPOSE so the code under test meets a locked file (each closed it in a ``finally``). S144-P-561 / -562
  respelled both as ``Path.open``, which SIM115 does not flag, so their rows left the baseline (S144-P-566).

Scope: tracked ``.py`` files under ``tests/`` and ``tools/tests/``. ``agents/daemon_slayer/tests`` is the
DS lane's, ``oss/`` and the agent3 suite have their own trees. The run uses NO config (``--isolated``) so
a per-file-ignore cannot hide a finding. A baseline row that stops offending fails
``test_baseline_is_exact`` until it is dropped; a new finding anywhere else fails ``test_no_new_findings``.
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

_RULE = "SIM115"
_IN_SCOPE = ("tests/", "tools/tests/")
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "tests/test_pickban_systems_p1l2.py": 1,
    "tests/test_routes_pickban.py": 14,
}
_FIXED = (
    "tests/test_coach_parse_json_fence.py",
    "tests/test_log_rotation_rm718a.py",
    "tests/test_moon_sync_poller.py",
    "tests/test_lane_launcher.py",
    "tests/test_ops_audit_perm_swarm_runners_atomic_s144p208.py",
    "tests/test_queue_loop.py",
    "tests/test_spell_prefs_atomic_rm297d.py",
    "tests/test_steer_channel.py",
    "tests/test_vision_profile_2560_ocr_boxes.py",
    "tools/tests/test_cdragon_ratio_extract.py",
    "tools/tests/test_cdragon_spell_extract.py",
    "tools/tests/test_wiki_ability_extract.py",
    "tools/tests/test_wiki_stats_extract.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin,
        check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULE, "tests", "tools/tests"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_IN_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


@pytest.mark.parametrize(
    "probe",
    [
        'src = open(__file__, encoding="utf-8").read()\n',
        'import ast\ntree = ast.parse(open("x.py", encoding="utf-8").read())\n',
    ],
)
def test_probe_is_live(probe):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
