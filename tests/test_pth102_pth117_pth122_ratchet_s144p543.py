"""S144-P-543 - ruff PTH102 / PTH117 / PTH122 (os.mkdir / os.path.isabs / os.path.splitext) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): eleven findings in eight files outside the
vendored kit (PTH201, PTH207, PTH208, PTH108 and PTH202 already have their own ratchets). One site became pathlib:
``tools/p3_ascii_census.py`` takes ``Path(rel).suffix.lower()`` of a tracked relative name and compares it to a fixed
extension set. Ten findings in seven files stay baselined, for a stated reason each:

- ``os.path.isabs`` (``core/disk_guard.py``, ``dashboard/routes_recordings.py``, ``ops/migrate/e_move_helpers.py``,
  ``tests/test_inbox_responder_runner.py``): ``Path.is_absolute`` is not the same predicate. A rooted path with no drive
  (``/x``) is absolute to ``os.path.isabs`` on Windows up to Python 3.12 and is not to ``Path.is_absolute``, and this tree
  runs on 3.12 (CI) and 3.14 (Legion), so a swap changes behaviour on one of them.
- ``os.path.splitext`` (``dashboard/routes_recordings.py``, ``ops/migrate/e_move_helpers.py``,
  ``tools/live_write_tracer.py``): ``Path.suffix`` of a trailing-dot name differs by version (3.14 reads ``.``, earlier
  reads nothing) where ``splitext`` always reads ``.``.
- ``os.mkdir`` in ``ops/launcher/first_run.py`` and ``tests/test_launcher_first_run.py`` is the
  packaging owner's.

The baseline only shrinks: ANY new finding, or a second finding in a baselined file, fails
``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding,
and ``--preview`` because the PTH family differs under it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import ntpath
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PTH102,PTH117,PTH122"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "core/disk_guard.py": 1,  # isabs on an OBS-written string
    "dashboard/routes_recordings.py": 3,  # isabs + two splitext on request / config strings
    "ops/launcher/first_run.py": 1,  # packaging owner's module
    "ops/migrate/e_move_helpers.py": 2,  # isabs + splitext on walked names
    "tests/test_inbox_responder_runner.py": 1,  # isabs on a decoded fd path inside a patched-open fake
    "tests/test_launcher_first_run.py": 1,  # packaging owner's test
    "tools/live_write_tracer.py": 1,  # splitext inside the tracer's own hook, on the plain os layer
}
_FIXED = (
    "tools/p3_ascii_census.py",
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
    """A positive control: each rule fires on the pattern the baseline exists for."""
    probe = "import os\nos.mkdir('a')\nos.path.isabs('a')\nos.path.splitext('a')\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH102", "PTH117", "PTH122"]


def test_isabs_and_is_absolute_agree_on_a_drive_rooted_path_but_not_a_rooted_one():
    """Why the isabs sites stay baselined: only the drive-and-root form is shared by both spellings."""
    assert ntpath.isabs("C:\\x") and PureWindowsPath("C:\\x").is_absolute()
    assert not ntpath.isabs("C:x") and not PureWindowsPath("C:x").is_absolute()
    assert not PureWindowsPath("/x").is_absolute()
    if sys.version_info < (3, 13):
        assert ntpath.isabs("/x")  # the version-dependent half: a swap would flip this answer


def test_a_trailing_dot_name_reads_a_different_extension_by_version():
    """Why the splitext sites on strings stay baselined."""
    assert os.path.splitext("x.")[1] == "."  # noqa: PTH122 - the old spelling is the control
    assert Path("x.").suffix == ("." if sys.version_info >= (3, 14) else "")


@pytest.mark.parametrize("rel", ["a.PY", "dir/b.ps1", "c.tar.gz", ".hidden", "noext", "d.", "e/f.g/h"])
def test_the_census_extension_matches_splitext_for_every_name_it_can_meet(rel):
    """tools/p3_ascii_census.py compares the lower-cased extension to a fixed set of dotted names (never "." or "")."""
    old = os.path.splitext(rel)[1].lower()  # noqa: PTH122 - the old spelling is the control
    new = Path(rel).suffix.lower()
    census = {".py", ".ps1", ".gz"}
    assert (old in census) == (new in census)
