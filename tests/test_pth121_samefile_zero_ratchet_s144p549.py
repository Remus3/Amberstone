"""S144-P-549 - ruff PTH121 (``os.path.samefile``) held at ZERO over the tracked tree outside the vendored kit.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): four findings in two test files, none in
production code. ``tests/test_rofl_dedupe_atomic_swap_rm258.py`` (three) and ``tests/test_inbox_responder_runner.py`` (one)
asked whether two hard-linked replay files, or a ``/proc`` fd link and a temp directory, name the same inode. They now
spell ``Path.samefile``, which is the same ``os.stat`` pair comparison (``os.path.samefile`` is what ``Path.samefile``
calls on 3.12), so no behaviour moves. A fresh zero ratchet holds the rule: ANY new finding fails
``test_no_pth121_finding_outside_the_fence``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a
finding, and ``--preview`` because the PTH family differs under it. ``ops/fleet_kit/`` is vendored byte-for-byte and
fenced.
"""
from __future__ import annotations

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

_RULES = "PTH121"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
_FIXED = (
    "tests/test_rofl_dedupe_atomic_swap_rm258.py",
    "tests/test_inbox_responder_runner.py",
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


def test_no_pth121_finding_outside_the_fence():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    found = sorted(
        {rel for d in _ruff(["."]) if (rel := relative_posix(Path(d["filename"]).resolve())) in held}
    )
    assert not found, f"ruff {_RULES} findings (use Path.samefile): {found}"


def test_the_fixed_modules_are_tracked_and_in_scope():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: the rule fires on the pattern it exists for, and not on the pathlib spelling."""
    bad = "import os\nos.path.samefile('a', 'b')\n"
    good = "from pathlib import Path\nPath('a').samefile('b')\n"
    assert [d["code"] for d in _ruff(["--stdin-filename", "probe.py", "-"], stdin=bad)] == ["PTH121"]
    assert _ruff(["--stdin-filename", "probe.py", "-"], stdin=good) == []


def test_path_samefile_agrees_with_os_path_samefile_on_a_link_and_a_distinct_file(tmp_path):
    """Behaviour pin: Path.samefile gives the os.path.samestat answer (the stat-pair test samefile is built on) for a hard link, a distinct copy and a directory."""
    a = tmp_path / "a.bin"
    a.write_bytes(b"x")
    link = tmp_path / "link.bin"
    try:
        os.link(a, link)
    except (OSError, NotImplementedError):
        link = None  # no hard-link support on this filesystem: the distinct-file half still holds
    other = tmp_path / "other.bin"
    other.write_bytes(b"x")
    pairs = [(a, other), (tmp_path, tmp_path), (a, a)]
    if link is not None:
        pairs.append((a, link))
    for left, right in pairs:
        assert left.samefile(right) is os.path.samestat(left.stat(), right.stat()), (left, right)
    assert a.samefile(a) is True
    assert a.samefile(other) is False
    if link is not None:
        assert a.samefile(link) is True
