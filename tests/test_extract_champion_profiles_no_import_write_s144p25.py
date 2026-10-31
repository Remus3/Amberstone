"""RM-1176: scripts/extract_champion_profiles.py writes nothing at import.

The one-shot migration helper (kept in tree as a migration doc by the
2026-10-09 repo review, B27-02) did all its work at MODULE LEVEL: importing
it read every profile through champion_profiles.py, created
data/champion_profiles/ and rewrote all of its TRACKED files with in-place
``write_bytes`` calls (no scratch, no fsync, no WinError 5 retry), while
champion_profiles.py reads those same files at import. Same class as
scripts/team_planner_sync.py (RM-1172) and scripts/fetch_cdragon_pbe.py
(RM-1174).

The work now lives in ``main()`` behind ``if __name__ == "__main__"``; the
byte shape is the importable ``render()`` (indent 2, raw UTF-8, LF, no
trailing newline) and every write goes through
``core.polled_json.atomic_write_bytes``. No test writes under the repo: the
import is proved write-free in a CHILD process whose writers refuse, and
``main()`` is driven against tmp_path with synthetic profiles.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402

_SRC = ROOT / "scripts" / "extract_champion_profiles.py"
_MOD = "scripts.extract_champion_profiles"
_DATA = ROOT / "data" / "champion_profiles"

_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign,
                ast.AnnAssign)

# Synthetic profiles (hand-written, not a copy of a tracked file); the
# second carries a non-ASCII name so ensure_ascii=False stays pinned.
_PROFILES = {
    "Alpha": {"dmg": "ad", "role": "fighter", "mana": True, "sustain": False,
              "mechanic": "dash", "aram": {"dmg_dealt": 1.05}},
    "Beta": {"dmg": "ap", "role": "mage", "mana": True, "sustain": True,
             "mechanic": "Caf\u00e9 \u00e9t\u00e9", "aram": {}},
}


def _is_docstring(node: ast.stmt) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _is_main_guard(node: ast.stmt) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__")


def _is_sys_path_insert(node: ast.stmt) -> bool:
    """`if str(ROOT) not in sys.path: sys.path.insert(0, ...)`."""
    return (isinstance(node, ast.If) and len(node.body) == 1
            and "sys.path.insert" in ast.unparse(node.body[0])
            and not node.orelse)


def test_the_module_body_writes_nothing():
    """Static guard, checked BEFORE anything imports the script."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    bad = [ast.unparse(n).splitlines()[0] for n in tree.body
           if not (isinstance(n, _ALLOWED_TOP) or _is_docstring(n)
                   or _is_main_guard(n) or _is_sys_path_insert(n))]
    assert bad == [], f"module-level statements run at import: {bad}"
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, "module", None) or ""] + [
                a.name for a in node.names]
            # The loader reads all 168 tracked profiles at import.
            assert "champion_profiles" not in names, ast.unparse(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            calls = [ast.unparse(c.func) for c in ast.walk(node)
                     if isinstance(c, ast.Call)]
            assert not any(k in c for c in calls
                           for k in ("write", "mkdir", "print", "dumps")), calls


_CHILD_IMPORT = (
    "import pathlib, sys\n"
    "calls = []\n"
    "def refuse(name):\n"
    "    def _refuse(self, *args, **kwargs):\n"
    "        calls.append((name, str(self)))\n"
    "        raise RuntimeError('test refuses writes')\n"
    "    return _refuse\n"
    "for attr in ('write_bytes', 'write_text', 'mkdir'):\n"
    "    setattr(pathlib.Path, attr, refuse(attr))\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import scripts.extract_champion_profiles\n"
    "print('writes at import:', len(calls))\n"
    "print('loader imported:', 'champion_profiles' in sys.modules)\n"
)


def test_importing_the_script_writes_nothing_and_prints_nothing_else():
    """Runtime twin of the static guard, in a child process so the refusing
    writers can never leak into another test."""
    test_the_module_body_writes_nothing()
    no_window = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD_IMPORT, str(ROOT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        creationflags=no_window,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip().splitlines() == [
        "writes at import: 0", "loader imported: False"], r.stdout


@pytest.fixture
def ecp():
    test_the_module_body_writes_nothing()
    sys.modules.pop(_MOD, None)
    mod = importlib.import_module(_MOD)
    yield mod
    sys.modules.pop(_MOD, None)


def test_the_default_target_is_the_tracked_profile_dir(ecp):
    assert ecp.OUT_DIR == _DATA


def test_render_is_indent_two_raw_utf8_lf_no_trailing_newline(ecp):
    data = _PROFILES["Beta"]
    out = ecp.render(data)
    assert out == json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    assert "Caf\u00e9".encode() in out
    assert b"\\u00e9" not in out
    assert b"\r" not in out
    assert not out.endswith(b"\n")


def test_main_writes_one_file_per_profile_and_no_scratch(ecp, tmp_path, capsys):
    out_dir = tmp_path / "profiles"
    assert ecp.main(out_dir=out_dir, champions=_PROFILES) == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ["Alpha.json",
                                                         "Beta.json"]
    for name, data in _PROFILES.items():
        assert (out_dir / f"{name}.json").read_bytes() == ecp.render(data)
    assert capsys.readouterr().out.startswith("Wrote 2 champion files to ")


def test_an_exhausted_replace_keeps_the_profile_and_no_scratch(
        ecp, tmp_path, monkeypatch):
    target = tmp_path / "Alpha.json"
    original = b'{"dmg": "ap"}'
    target.write_bytes(original)

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        ecp.main(out_dir=tmp_path, champions={"Alpha": _PROFILES["Alpha"]})
    assert target.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Alpha.json"]


def test_a_rerun_over_the_tracked_profiles_is_a_byte_no_op(ecp):
    """The migration is done: champion_profiles.py LOADS these files, so a
    re-run must write back exactly the bytes already tracked. Read-only."""
    files = sorted(_DATA.glob("*.json"))
    assert files, "data/champion_profiles/ holds no profiles"
    drift = [p.name for p in files
             if ecp.render(json.loads(p.read_bytes())) != p.read_bytes()]
    assert drift == [], f"a re-run would rewrite: {drift[:10]}"
