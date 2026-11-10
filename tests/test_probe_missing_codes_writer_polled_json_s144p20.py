"""RM-1131: scripts/probe_missing_codes.py goes through core.polled_json.

The script rewrites the TRACKED planner code map
data/meta/tft_set17_champion_codes.json, the same file family
scripts/discover_champion_codes.py writes (RM-1129) and the gated TFT
drain tools read. Two defects:

  1. The whole probe ran at MODULE LEVEL: importing the file read the
     lockfile, called ``exit()`` when there was none, and otherwise issued
     LCU team-planner POST / DELETE calls against the operator's client. No
     test could import it, so its writer had no coverage at all.
  2. ``codes_file.write_bytes(...)`` rewrote the tracked file in place: no
     scratch, no fsync, no WinError 5 retry, so a reader polling the map saw
     a torn or empty file.

The probe now lives in ``main()`` behind ``if __name__ == "__main__"`` and
the save goes through ``save_codes`` -> ``core.polled_json
.atomic_write_bytes``. The bytes are unchanged (indent 2, sorted keys, LF,
no trailing newline). scripts/ sits outside the repo-wide guard
tests/test_atomic_write_guard_rm258_rm261.py (one-shot generator tree), so
this module carries its own source pin. No test touches a League client:
the import is proved call-free in a CHILD process whose
``urllib.request.urlopen`` is a recorder that raises; in this process every
test refuses and records the script's OWN ``urllib.request.urlopen``
(``bind_urlopen``, never the process-wide stdlib attribute, RM-801); and
``main()`` only runs with every lockfile path pointed at a missing file.
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

from tests._module_view import bind_urlopen

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import polled_json  # noqa: E402

_SRC = ROOT / "scripts" / "probe_missing_codes.py"
_MOD = "scripts.probe_missing_codes"
_NAME = "tft_set17_champion_codes.json"
_ORIGINAL = b'{"previous": 1}'
_CODES = {"Kobuko": 1085, "Ahri": 1001}

_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign,
                ast.AnnAssign)


def _is_docstring(node: ast.stmt) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _is_main_guard(node: ast.stmt) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__")


def _is_sys_path_insert(node: ast.stmt) -> bool:
    """`if str(PROJECT) not in sys.path: sys.path.insert(0, ...)`."""
    return (isinstance(node, ast.If) and len(node.body) == 1
            and "sys.path.insert" in ast.unparse(node.body[0])
            and not node.orelse)


def test_the_module_body_runs_no_probe():
    """Static guard, checked BEFORE anything imports the script."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    bad = [ast.unparse(n).splitlines()[0] for n in tree.body
           if not (isinstance(n, _ALLOWED_TOP) or _is_docstring(n)
                   or _is_main_guard(n) or _is_sys_path_insert(n))]
    assert bad == [], f"module-level statements run at import: {bad}"
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            calls = [ast.unparse(c.func) for c in ast.walk(node)
                     if isinstance(c, ast.Call)]
            assert not any("lcu" in c or "urlopen" in c or "read_text" in c
                           for c in calls), calls


_CHILD_IMPORT = (
    "import sys, urllib.request\n"
    "calls = []\n"
    "def refuse(*args, **kwargs):\n"
    "    calls.append(args)\n"
    "    raise RuntimeError('test refuses network access')\n"
    "urllib.request.urlopen = refuse\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import scripts.probe_missing_codes\n"
    "print('urlopen calls at import:', len(calls))\n"
)


def test_importing_the_script_makes_no_network_call():
    """Runtime twin of the static guard, in a child process so the refusing
    urlopen can never leak into another test (RM-801)."""
    test_the_module_body_runs_no_probe()
    no_window = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD_IMPORT, str(ROOT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        creationflags=no_window, check=False,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip().splitlines()[-1] == "urlopen calls at import: 0", r.stdout


@pytest.fixture
def pmc(monkeypatch):
    """Import the script, then refuse and record every network call it makes."""
    test_the_module_body_runs_no_probe()
    sys.modules.pop(_MOD, None)
    mod = importlib.import_module(_MOD)
    calls: list[object] = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("test refuses network access")

    # Scoped to the script's own urllib.request.urlopen (RM-801).
    assert bind_urlopen(monkeypatch, mod, refuse) >= 1
    yield mod
    sys.modules.pop(_MOD, None)
    assert calls == [], f"the script attempted network access: {calls}"


def test_main_without_a_lockfile_stops_before_any_lcu_call(
        pmc, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pmc, "LOCKFILES", (tmp_path / "absent" / "lockfile",))
    target = tmp_path / _NAME
    target.write_bytes(_ORIGINAL)
    monkeypatch.setattr(pmc, "CODES_FILE", target)
    assert pmc.main() == 0
    assert "NO_LOCKFILE" in capsys.readouterr().out
    assert target.read_bytes() == _ORIGINAL


def test_a_transient_permission_error_on_replace_is_retried(
        pmc, tmp_path, monkeypatch):
    target = tmp_path / _NAME
    target.write_bytes(_ORIGINAL)
    real_replace = polled_json.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    pmc.save_codes(target, _CODES)
    assert json.loads(target.read_bytes()) == _CODES
    assert calls["n"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [_NAME]


def test_an_exhausted_replace_keeps_the_target_and_no_scratch(
        pmc, tmp_path, monkeypatch):
    target = tmp_path / _NAME
    target.write_bytes(_ORIGINAL)

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        pmc.save_codes(target, _CODES)
    assert target.read_bytes() == _ORIGINAL
    assert sorted(p.name for p in tmp_path.iterdir()) == [_NAME]


def test_two_writes_of_one_file_use_distinct_per_writer_scratch_names(
        pmc, tmp_path, monkeypatch):
    target = tmp_path / _NAME
    seen: list[str] = []
    real_replace = polled_json.os.replace

    def spy(src, dst):
        seen.append(pathlib.Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", spy)
    pmc.save_codes(target, _CODES)
    pmc.save_codes(target, _CODES)
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(n.startswith(_NAME + ".") and n.endswith(".tmp")
               and n != _NAME + ".tmp" for n in seen)


def test_the_written_bytes_are_unchanged(pmc, tmp_path):
    """Same serialisation as before the move: indent 2, sorted, LF, no tail."""
    target = tmp_path / "data" / "meta" / _NAME
    pmc.save_codes(target, _CODES)
    assert target.read_bytes() == json.dumps(
        _CODES, indent=2, sort_keys=True).encode("utf-8")
    assert b"\r" not in target.read_bytes()


def test_the_default_target_is_the_tracked_set17_map(pmc):
    assert pmc.CODES_FILE == ROOT / "data" / "meta" / _NAME


def test_the_writer_does_not_write_in_place(pmc):
    """Source pin: the script delegates instead of writing the file itself."""
    src = _SRC.read_text(encoding="utf-8")
    assert ".write_bytes(" not in src
    assert ".write_text(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert pmc.atomic_write_bytes is polled_json.atomic_write_bytes
