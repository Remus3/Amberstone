"""RM-258 residual: the SHA-citation remapper writes through core.polled_json.

`main([... "--apply"])` in tools/rewrite_sha_citations.py rewrote each changed
doc through a fixed `<name>.<suffix>.tmp` scratch file plus a bare
Path.replace: no fsync before the rename, no WinError 5 retry, and the scratch
left behind when the rename failed.

Every test builds its own commit map and doc under tmp_path and spies on
`core.polled_json.atomic_write_text`, so no tracked doc is read or written.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import rewrite_sha_citations as tool

OLD_A = "aaaaaaaa" + "1" * 32
NEW_A = "bbbbbbbb" + "2" * 32
_DOC = f"# ledger\n\n- shipped `{OLD_A[:8]}` today\n"
_REMAPPED = f"# ledger\n\n- shipped `{NEW_A[:8]}` today\n"


@pytest.fixture
def tree(tmp_path) -> tuple[Path, Path]:
    cmap = tmp_path / "commit-map"
    cmap.write_bytes(f"old new\n{OLD_A} {NEW_A}\n".encode("ascii"))
    doc = tmp_path / "docs" / "LEDGER.md"
    doc.parent.mkdir()
    doc.write_bytes(_DOC.encode("ascii"))
    return cmap, doc


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, str]] = []
    real = polled_json.atomic_write_text

    def _spy(path, content):
        calls.append((Path(path), content))
        real(path, content)

    monkeypatch.setattr(polled_json, "atomic_write_text", _spy)
    return calls


def test_apply_writes_through_polled_json(tree, spy):
    cmap, doc = tree
    assert tool.main(["--map", str(cmap), "--apply", str(doc)]) == 0
    assert spy == [(doc, _REMAPPED)]
    # Same bytes the old write_text(newline="") produced: UTF-8, LF kept.
    assert doc.read_bytes() == _REMAPPED.encode("ascii")
    assert sorted(p.name for p in doc.parent.iterdir()) == ["LEDGER.md"]


def test_dry_run_writes_nothing(tree, spy):
    cmap, doc = tree
    assert tool.main(["--map", str(cmap), str(doc)]) == 0
    assert spy == []
    assert doc.read_bytes() == _DOC.encode("ascii")


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tree, monkeypatch):
    cmap, doc = tree
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main(["--map", str(cmap), "--apply", str(doc)])
    assert len(fired) == 1
    assert doc.read_bytes() == _DOC.encode("ascii")
    assert sorted(p.name for p in doc.parent.iterdir()) == ["LEDGER.md"]


def test_rerun_is_a_no_op(tree, spy):
    cmap, doc = tree
    tool.main(["--map", str(cmap), "--apply", str(doc)])
    assert tool.main(["--map", str(cmap), "--apply", str(doc)]) == 0
    assert len(spy) == 1


def test_script_mode_resolves_core_from_any_cwd(tree, tmp_path):
    # The documented invocation is `python tools/rewrite_sha_citations.py`;
    # in script mode sys.path[0] is tools/, so the core import must not
    # depend on the cwd or PYTHONPATH.
    cmap, doc = tree
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, tool.__file__, "--map", str(cmap), str(doc)],
        capture_output=True, text=True, cwd=str(tmp_path), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc.read_bytes() == _DOC.encode("ascii")


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".tmp" not in text
    assert "tmp.replace(" not in text
    assert "polled_json.atomic_write_text(" in text
