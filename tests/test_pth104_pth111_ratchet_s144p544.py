"""S144-P-544 - ruff PTH104 / PTH111 (os.rename / os.path.expanduser) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): sixteen findings in eleven files, four of
them in the vendored kit (``ops/fleet_kit/``, fenced). Four sites became pathlib: ``tools/inbox_responder_export.py``
renames a ``Path`` directory with ``Path.rename`` (both spellings call ``os.rename``, so the RM-411 scoped fault in
``tests/test_inbox_responder_export.py`` still bites), and ``tools/perseus_recall.py``, ``tools/perseus_sync.py`` and
``tools/scheduled_boot_verify.py`` take ``Path.home()`` for ``os.path.expanduser("~")`` (the boot-verify default stays lazy). Eight findings in five files stay
baselined, for a stated reason each:

- ``core/log_rotation.py`` and ``tools/progress_watch.py`` (three sites): the rename IS the seam the race tests patch
  (``log_rotation.os.rename``; ``progress_watch._move`` / ``_capture``, the S144-P-528 baseline carries progress_watch), so the call stays
  a bare ``os.rename`` on the plain os layer.
- ``tests/_basetemp_guard.py`` and ``tools/stop_claim_gate.py``: the argument is ARBITRARY text (a pytest ``--basetemp``
  value, a command word). ``Path.expanduser`` raises RuntimeError where ``os.path.expanduser`` returns the text unchanged
  (a home that cannot be resolved), and both are gates that must never raise on odd input.
- ``tests/test_launcher_first_run.py`` (three sites) is the packaging owner's.

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

_RULES = "PTH104,PTH111"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "core/log_rotation.py": 1,  # os.rename is the no-clobber link seam the race tests patch
    "tests/_basetemp_guard.py": 1,  # expanduser on an arbitrary --basetemp value; a gate must not raise
    "tests/test_launcher_first_run.py": 3,  # packaging owner's test
    "tools/progress_watch.py": 2,  # os.rename inside the _move and _capture seams of the race tests
    "tools/stop_claim_gate.py": 1,  # expanduser on arbitrary command text; a gate must not raise
}
_FIXED = (
    "tools/inbox_responder_export.py",
    "tools/perseus_recall.py",
    "tools/perseus_sync.py",
    "tools/scheduled_boot_verify.py",
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
    probe = "import os\nos.rename('a', 'b')\nos.path.expanduser('~')\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PTH104", "PTH111"]


def test_path_rename_moves_a_directory_and_refuses_a_non_empty_target_like_os_rename(tmp_path):
    """The converted export site: same move, and the same OSError the caller's branch decides on."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    src.rename(dst)
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"
    assert not src.exists()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(OSError):  # FileExistsError on Windows, ENOTEMPTY / EEXIST on POSIX
        other.rename(dst)


def test_path_rename_goes_through_os_rename(tmp_path, monkeypatch):
    """Why the RM-411 scoped fault in the export tests still bites the converted call."""
    seen = []
    real = os.rename

    def spy(src, dst, *a, **kw):
        seen.append((Path(src), Path(dst)))
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(os, "rename", spy)
    (tmp_path / "a").mkdir()
    (tmp_path / "a").rename(tmp_path / "b")
    assert seen == [(tmp_path / "a", tmp_path / "b")]


def test_home_spellings_agree_when_a_home_resolves():
    """The converted perseus / boot-verify sites read the same home the old spelling did."""
    old = os.path.join(os.path.expanduser("~"), ".perseus-vault")  # noqa: PTH111, PTH118 - the old spelling is the control
    assert str(Path.home() / ".perseus-vault") == old
    from tools import perseus_recall, perseus_sync

    assert perseus_recall.PERSEUS_HOME == old
    assert perseus_sync.PERSEUS_HOME == old


@pytest.mark.skipif(sys.platform != "win32", reason="a POSIX home falls back to the passwd entry")
def test_an_unresolvable_home_returns_tilde_from_os_but_raises_from_pathlib(monkeypatch):
    """Why the two gate sites on arbitrary text stay baselined."""
    for name in ("HOME", "USERPROFILE", "HOMEPATH", "HOMEDRIVE"):
        monkeypatch.delenv(name, raising=False)
    assert os.path.expanduser("~") == "~"  # noqa: PTH111 - the old spelling is the control
    with pytest.raises(RuntimeError):
        Path("~").expanduser()
