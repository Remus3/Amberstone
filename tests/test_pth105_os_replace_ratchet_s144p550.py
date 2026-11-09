"""S144-P-550 - ruff PTH105 (os.replace) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 42 findings in 32 files, six of them (four
files) in the vendored kit (``ops/fleet_kit/``, fenced). Four sites became pathlib: the lock-file helpers of
``tests/test_lane_lock.py`` (two), ``tests/test_lane_pid_reuse.py`` and ``tests/test_lanes_fleet_v6.py`` write a tmp
file and land it with ``tmp.replace(lock)``. ``Path.replace`` calls ``os.replace`` (pinned below), so the result is the
same atomic swap. The other 32 findings in 25 files stay baselined, for a stated reason each:

- ``core/polled_json.py``, ``tools/phase_watcher.py``, ``tools/moon_sync_poller.py``, ``tools/stop_claim_gate.py`` and
  ``tools/shadow_archive_split.py``: the atomic-write guard (``tests/test_atomic_write_guard_rm258_rm261.py``) recognises
  a hand-rolled swap by its ``os.replace`` call and sanctions each one by name, so respelling one would only make the
  guard blind to it.
- ``core/log_rotation.py``: the rename is the no-clobber seam the race tests patch.
- ``ops/rc_dev_runtime.py`` and ``ops/rc_supervisor.py`` are FROZEN files (CLAUDE.md); ``ops/launcher/*`` is the packaging
  owner's; ``ops/rc_transactional_deploy.py`` and ``oss/win32_atomic_io`` are atomic-IO implementations pinned the same way
  as the guard rows above.
- ``tools/daemon_slayer_cdragon_*_extract.py``: dropping the then-unused ``import os`` shifts the line numbers that
  ``docs/specs`` and the DS changelog cite, so the two stay until a doc-cite pass.
- Eleven test files use ``os.replace`` BY NAME: they inject a fault at it (``replace_fails``, ``scoped_fs_fault``,
  ``monkeypatch.setattr(polled_json.os, "replace", ...)``), they are the positive control that a rename onto an open file
  raises PermissionError, or they model a writer whose shape the test is about (a kit writer, a tracer self-test).

The baseline only shrinks: ANY new finding, or a second finding in a baselined file, fails
``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding,
and ``--preview`` because the PTH family differs under it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PTH105"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "core/log_rotation.py": 4,  # the no-clobber rename seam the race tests patch
    "core/polled_json.py": 1,  # the atomic-write primitive; the guard keys on os.replace
    "ops/launcher/service_host.py": 2,  # packaging owner's
    "ops/launcher/updater.py": 1,  # packaging owner's
    "ops/rc_dev_runtime.py": 1,  # FROZEN
    "ops/rc_supervisor.py": 1,  # FROZEN
    "ops/rc_transactional_deploy.py": 1,  # atomic-IO implementation, sanctioned by name
    "oss/win32_atomic_io/src/win32_atomic_io/_atomic.py": 1,  # extracted package, drift-pinned to polled_json
    "tests/test_ddragon_fetch_writer_emits_lf.py": 1,  # control inside a patched polled_json.os.replace window
    "tests/test_decision_detector_lane8_cycle12.py": 1,  # rename onto an open file raises PermissionError
    "tests/test_lcu_push_watcher.py": 1,  # the log rotation rename under test
    "tests/test_live_write_tracer_selftest.py": 1,  # the tracer watches os.replace by name
    "tests/test_log_rotation_no_clobber_rm864.py": 1,  # models the POSIX replacing rename
    "tests/test_loop_control_contention.py": 1,  # rename onto an open file raises PermissionError
    "tests/test_performance_tracker_lane8_cycle23.py": 1,  # rename onto an open file raises PermissionError
    "tests/test_prod_artifact_guard_writer_rm148.py": 1,  # asserts the os.replace attribution
    "tests/test_progress_reaper_rm816.py": 1,  # models the kit writer's os.replace shape
    "tests/test_rofl_archive_lane8_download_bounds.py": 1,  # control inside a scoped replace fault
    "tests/test_tft_sources_tft_log.py": 2,  # positive control: plain open blocks the rename, shared open does not
    "tools/daemon_slayer_cdragon_ratio_extract.py": 1,  # docs cite this file's line numbers
    "tools/daemon_slayer_cdragon_spell_extract.py": 1,  # docs cite this file's line numbers
    "tools/moon_sync_poller.py": 1,  # sanctioned by name in the atomic-write guard
    "tools/phase_watcher.py": 1,  # sanctioned by name in the atomic-write guard
    "tools/shadow_archive_split.py": 3,  # the two-file swap the guard pins
    "tools/stop_claim_gate.py": 1,  # sanctioned by name in the atomic-write guard
}
_FIXED = (
    "tests/test_lane_lock.py",
    "tests/test_lane_pid_reuse.py",
    "tests/test_lanes_fleet_v6.py",
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


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: the rule fires on the pattern the baseline exists for."""
    probe = "import os\nos.replace('a', 'b')\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["PTH105"]


def test_path_replace_overwrites_an_existing_file_like_os_replace(tmp_path):
    """The converted lock helpers: the tmp file lands over an existing lock."""
    lock = tmp_path / "lane.lock"
    lock.write_text("old", encoding="utf-8")
    tmp = lock.with_name(lock.name + ".tmp")
    tmp.write_text("new", encoding="utf-8")
    tmp.replace(lock)
    assert lock.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()


def test_path_replace_goes_through_os_replace(tmp_path, monkeypatch):
    """Why a fault injected at os.replace still bites a converted call."""
    seen = []
    real = os.replace

    def spy(src, dst, *a, **kw):
        seen.append((Path(src), Path(dst)))
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", spy)
    (tmp_path / "a").write_text("x", encoding="utf-8")
    (tmp_path / "a").replace(tmp_path / "b")
    assert seen == [(tmp_path / "a", tmp_path / "b")]
