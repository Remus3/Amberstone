"""S144-P-539 - ruff PTH204 / PTH103 / PTH115 held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): five findings in five files. Three became
pathlib: ``dashboard/routes_state.py`` ``_asset_stamp_mtime`` (``asset_fileset`` yields ``Path`` objects, so
``p.stat().st_mtime`` replaces ``os.path.getmtime(p)``), ``tests/test_asset_stamp_panels.py`` (``panel`` is a ``Path``) and
``tools/logger_leak_census.py`` (``Path(_REPORT_DIR).mkdir(parents=True, exist_ok=True)`` replaces ``os.makedirs``).

Two sites stay baselined: ``ops/migrate/e_move_helpers.py`` reads a link target off a ``scandir`` entry path and then strips
the Windows ``\\\\?\\`` verbatim prefix by hand (the one-shot migration owner's string handling, not touched blind), and
``tests/test_inbox_responder_runner.py`` ``_fd_dir_path`` reads ``/proc/self/fd/<n>``, a string path that only exists on
Linux. The baseline only shrinks: ANY new finding, or a second finding in a baselined file, fails
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

_RULES = "PTH204,PTH103,PTH115"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "ops/migrate/e_move_helpers.py": 1,  # os.readlink on a scandir path + hand-stripped verbatim prefix; one-shot migrate helper
    "tests/test_inbox_responder_runner.py": 1,  # os.readlink of the Linux-only /proc/self/fd/<n> string
}
_FIXED = (
    "dashboard/routes_state.py",
    "tests/test_asset_stamp_panels.py",
    "tools/logger_leak_census.py",
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
    """A positive control: all three rules fire on the pattern each exists for."""
    probe = (
        "import os\n"
        'os.path.getmtime("a")\n'
        'os.makedirs("d")\n'
        'os.readlink("l")\n'
    )
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH103", "PTH115", "PTH204"]


def _load_by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def test_the_census_creates_a_missing_nested_report_directory(tmp_path, monkeypatch, capsys):
    """Behaviour pin: the report dir (and its parents) is created, and both files land LF-terminated."""
    nested = tmp_path / "a" / "b"
    monkeypatch.setenv("RC_LOGGER_CENSUS_REPORT_DIR", str(nested))
    census_mod = _load_by_path("_s144p539_census", "tools/logger_leak_census.py")
    assert not nested.exists()
    census_mod._Census().pytest_sessionfinish(None, 0)
    capsys.readouterr()
    report = json.loads((nested / "logger_leak_census.json").read_text(encoding="utf-8"))
    assert report["tests_observed"] == 0
    assert b"\r" not in (nested / "logger_leak_census.txt").read_bytes()


def test_the_asset_stamp_is_the_newest_mtime_of_the_fileset(tmp_path, monkeypatch):
    """Behaviour pin: max over the Path fileset's st_mtime; an unreadable entry is skipped; empty is 0.0."""
    from dashboard import _static, routes_state

    old = tmp_path / "old.js"
    new = tmp_path / "new.js"
    gone = tmp_path / "gone.js"
    for p, t in ((old, 1_000_000.0), (new, 2_000_000.0)):
        p.write_text("x", encoding="utf-8")
        os.utime(p, (t, t))
    monkeypatch.setattr(_static, "asset_fileset",
                        lambda web_root=None: [("old.js", old), ("gone.js", gone), ("new.js", new)])
    assert routes_state._asset_stamp_mtime() == 2_000_000.0
    monkeypatch.setattr(_static, "asset_fileset", lambda web_root=None: [("gone.js", gone)])
    assert routes_state._asset_stamp_mtime() == 0.0
