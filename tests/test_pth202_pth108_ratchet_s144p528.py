"""S144-P-528 - ruff PTH202 (os.path.getsize) and PTH108 (os.unlink) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 14 findings in 9 files once the
math-constant sample data is set aside. Eight became pathlib: the six ``os.path.getsize(<Path>)`` evidence reads of
``tests/test_live_write_tracer_selftest.py`` (every operand is already a ``Path``, so ``.stat().st_size``),
``tests/test_atlas_dust.py`` (the ``mkstemp`` script cleanup, ``Path(path).unlink()``) and
``tests/_basetemp_guard.py`` (the Windows marker probe, ``marker.unlink()`` on an existing ``Path``; the raised
``FileNotFoundError`` / ``OSError`` are the same).

The rest stay, each for a stated reason, and the baseline only shrinks. ANY new finding, or one more than a file's
baseline, fails ``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore
cannot hide a finding, and ``--preview`` because both rules are preview-only in this ruff.
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

_RULES = "PTH202,PTH108"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    # tests/test_log_rotation_no_clobber_rm864.py patches `log_rotation.os.unlink`: the module-level os call IS the seam.
    "core/log_rotation.py": 2,
    "ops/launcher/first_run.py": 2,  # PKG-owned file (main session)
    # os.link-then-unlink move for POSIX: the unlink is the second half of the os.link above it, kept on the same os layer.
    "tools/progress_watch.py": 1,
    # inside the patched os.rename wrapper: the tracer keeps every call in its own hook on the plain os layer.
    "tools/live_write_tracer.py": 1,
}
_FIXED = (
    "tests/test_live_write_tracer_selftest.py",
    "tests/test_atlas_dust.py",
    "tests/_basetemp_guard.py",
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


@pytest.mark.parametrize(
    ("probe", "code"),
    [
        ('import os\nn = os.path.getsize("f")\n', "PTH202"),
        ('import os\nos.unlink("f")\n', "PTH108"),
    ],
)
def test_the_fence_is_not_empty_of_findings_by_accident(probe, code):
    """A positive control: each rule does fire on the pattern it exists for."""
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == [code]


def test_the_fixed_spellings_are_quiet():
    probe = 'from pathlib import Path\np = Path("f")\nn = p.stat().st_size\np.unlink()\n'
    assert _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe) == []
