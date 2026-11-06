"""RM-258 residual: tools/gen_archmap.py rewrites ARCHITECTURE.md through core.polled_json.

`_update_file()` rewrote docs/ARCHITECTURE.md through a fixed
`ARCHITECTURE.md.tmp` scratch (with_suffix + write_bytes) and a bare
Path.replace: no fsync before the rename, no WinError 5 retry, and the scratch
left behind when the rename failed. It now hands the same UTF-8 bytes (LF kept,
RM-441) to `core.polled_json.atomic_write_bytes`.

The pre-commit hook runs `gen_archmap.py --check` on every commit, so the
import stays inside the write branch: a broken core/ package must never block
the commit that fixes it. One test pins that the check path imports nothing
from core/.

Every test writes only under tmp_path; no tracked file is read or written.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
import tools.gen_archmap as gam

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
_START, _END = "<!-- archmap:start", "<!-- archmap:end -->"
_ORIGINAL = b"# Title\n\n<!-- archmap:start -->\nold\n<!-- archmap:end -->\ntail\n"
_BLOCK = "<!-- archmap:start -->\nrow one\nrow two\n<!-- archmap:end -->"


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "ARCHITECTURE.md"
    p.write_bytes(_ORIGINAL)
    return p


def test_update_file_writes_through_polled_json(doc, monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", spy)
    assert gam._update_file(doc, _START, _END, _BLOCK, check=False) is True
    assert calls == [(doc, doc.read_bytes())]
    assert b"row one\nrow two\n" in doc.read_bytes()
    assert b"\r" not in doc.read_bytes()
    assert list(doc.parent.glob("*.tmp")) == []


def test_check_mode_writes_nothing(doc, monkeypatch):
    def boom(path, data):
        raise AssertionError("--check must not write")

    monkeypatch.setattr(polled_json, "atomic_write_bytes", boom)
    assert gam._update_file(doc, _START, _END, _BLOCK, check=True) is True
    assert doc.read_bytes() == _ORIGINAL


def test_unchanged_block_writes_nothing(doc, monkeypatch):
    def boom(path, data):
        raise AssertionError("an unchanged doc must not be rewritten")

    monkeypatch.setattr(polled_json, "atomic_write_bytes", boom)
    same = "<!-- archmap:start -->\nold\n<!-- archmap:end -->"
    assert gam._update_file(doc, _START, _END, same, check=False) is False


def test_refused_rename_keeps_doc_and_leaves_no_scratch(doc, monkeypatch):
    def refuse(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", refuse)
    with pytest.raises(PermissionError):
        gam._update_file(doc, _START, _END, _BLOCK, check=False)
    assert doc.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in doc.parent.iterdir()) == ["ARCHITECTURE.md"]


def test_no_hand_rolled_swap_left():
    src = (_TOOLS / "gen_archmap.py").read_text(encoding="utf-8")
    assert '.tmp")' not in src
    assert "tmp.replace(" not in src


def _run_script_mode(code: str, cwd: Path) -> subprocess.CompletedProcess:
    # -I: no PYTHONPATH, no user site; sys.path[0] = tools/ as in
    # `python tools/gen_archmap.py`, the shape the pre-commit hook runs.
    prelude = f"import sys; sys.path.insert(0, {str(_TOOLS)!r}); import gen_archmap as g\n"
    return subprocess.run(
        [sys.executable, "-I", "-c", prelude + code],
        cwd=cwd, capture_output=True, text=True, timeout=120,
    )


def test_check_path_imports_nothing_from_core(doc, tmp_path):
    code = (
        f"g._update_file(__import__('pathlib').Path({str(doc)!r}), "
        f"{_START!r}, {_END!r}, {_BLOCK!r}, check=True)\n"
        "bad = sorted(m for m in sys.modules if m == 'core' or m.startswith('core.'))\n"
        "assert not bad, bad\n"
    )
    proc = _run_script_mode(code, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert doc.read_bytes() == _ORIGINAL


def test_script_mode_write_imports_core_from_a_foreign_cwd(doc, tmp_path):
    code = (
        f"assert g._update_file(__import__('pathlib').Path({str(doc)!r}), "
        f"{_START!r}, {_END!r}, {_BLOCK!r}, check=False)\n"
        "assert 'core.polled_json' in sys.modules\n"
    )
    proc = _run_script_mode(code, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert b"row one\nrow two\n" in doc.read_bytes()
    assert list(tmp_path.glob("*.tmp")) == []
