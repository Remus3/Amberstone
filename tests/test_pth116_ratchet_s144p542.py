"""S144-P-542 - ruff PTH116 (os.stat) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): eighteen findings in thirteen files. Nine
sites in six files became ``Path.stat``: ``tools/inbox_responder_runner.py`` (``note_path`` is ``inbox / name``) and eight
test sites whose argument is already a ``Path`` (``tmp_path`` children, ``ensure_export``'s returned ``Path``) or a string
a ``Path(...)`` wraps one step earlier (``test_highlight_reel_rm639.py``, ``test_league_settings_mtime_cache.py``).

Nine findings in seven files stay baselined. Five production modules call ``os.stat`` on a caller-supplied STRING that can
be empty, hold an embedded NUL or name a device: ``Path("").stat()`` stats ``.`` and succeeds where ``os.stat("")`` raises, so
a blind swap would change behaviour (``core/hud_settings.py`` and ``core/league_settings.py`` document the device / NUL
refusal; ``core/vod_retention.py`` ``_stat_size`` and ``tft/tft_prompt.py`` ``_stamp`` return None on OSError;
``dashboard/routes_recordings.py`` passes ``follow_symlinks=False`` on a realpath). ``ops/launcher/first_run.py`` is the
packaging owner's and ``ops/rc_supervisor.py`` is a frozen file. The baseline only shrinks: ANY new finding, or a second
finding in a baselined file, fails ``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding, and ``--preview`` because the PTH family differs under it.
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

_RULES = "PTH116"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "core/hud_settings.py": 1,  # str path; NUL / device-name refusal before open
    "core/league_settings.py": 1,  # str path; NUL / device-name refusal before open
    "core/vod_retention.py": 1,  # str path; empty string must stay None, not "."
    "dashboard/routes_recordings.py": 1,  # follow_symlinks=False on a realpath string
    "tft/tft_prompt.py": 1,  # str path; None when absent
    "ops/launcher/first_run.py": 3,  # packaging owner's module, not touched from the repo lane
    "ops/rc_supervisor.py": 1,  # FROZEN file
}
_FIXED = (
    "tools/inbox_responder_runner.py",
    "tests/test_file_ingest_true_audit_s144t584.py",
    "tests/test_highlight_reel_rm639.py",
    "tests/test_inbox_responder_export.py",
    "tests/test_install_bat_key_stage_rm779.py",
    "tests/test_league_settings_mtime_cache.py",
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
    """A positive control: PTH116 fires on os.stat, the pattern the baseline exists for."""
    probe = 'import os\nos.stat("a")\n'
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["PTH116"]


def test_an_empty_string_stats_differently_so_the_string_sites_stay_baselined():
    """Why the five string-path production sites are not swapped blind."""
    with pytest.raises(OSError):
        os.stat("")  # noqa: PTH116 - the point of the test
    assert Path("").stat().st_mode  # Path("") is "." and succeeds


def test_a_path_stat_matches_os_stat_for_a_path_argument(tmp_path):
    """Behaviour pin for the converted sites: same stat_result fields from either spelling."""
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    a, b = os.stat(p), p.stat()  # noqa: PTH116 - the old spelling is the control
    assert (a.st_size, a.st_mtime_ns, a.st_ino) == (b.st_size, b.st_mtime_ns, b.st_ino)
