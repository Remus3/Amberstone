"""RM-1172: scripts/team_planner_sync.py runs nothing at import.

The script pushes the tracked TFT meta's S/A comps into the operator's
client Team Planner over LCU (POST create, DELETE clear, POST import, PATCH
name, DELETE oldest at capacity). Before this fix the WHOLE sync ran at
MODULE LEVEL: importing the file read the lockfile and called
``sys.exit(1)`` when there was none, and with a client up it issued the
team-planner writes. No test could import it, so none of its logic had any
coverage. Same class as scripts/probe_missing_codes.py (RM-1131).

The sync now lives in ``main()`` behind ``if __name__ == "__main__"``; the
pure parts (``champ_to_lcu_id``, ``collect_target_comps``,
``read_lockfile``) are importable functions and the request builder is
``make_lcu``. Exit codes, prints, the check order (lockfile, then meta, then
comps) and the request sequence are unchanged. No test touches a League
client: the import is proved call-free in a CHILD process whose
``urllib.request.urlopen`` is a recorder that raises; in this process every
test refuses and records the script's OWN ``urllib.request.urlopen``
(``bind_urlopen``, never the process-wide stdlib attribute, RM-801); and the
sync-loop test swaps ``make_lcu`` for an in-memory recorder.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import pathlib
import subprocess
import sys
import uuid

import pytest

from tests._module_view import bind_urlopen

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SRC = ROOT / "scripts" / "team_planner_sync.py"
_MOD = "scripts.team_planner_sync"
_LOCKFILE_TEXT = "LeagueClient:4242:50123:synthetic-pw:https\n"
_PLANNER = "/lol-tft-team-planner/v1/sets/TFTSet17/teams/"

_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign,
                ast.AnnAssign)


def _is_docstring(node: ast.stmt) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _is_main_guard(node: ast.stmt) -> bool:
    """Exactly `if __name__ == "__main__":`."""
    return (isinstance(node, ast.If) and not node.orelse
            and ast.unparse(node.test) == "__name__ == '__main__'")


def test_the_module_body_runs_no_sync():
    """Static guard, checked BEFORE anything imports the script."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    bad = [ast.unparse(n).splitlines()[0] for n in tree.body
           if not (isinstance(n, _ALLOWED_TOP) or _is_docstring(n)
                   or _is_main_guard(n))]
    assert bad == [], f"module-level statements run at import: {bad}"
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            calls = [ast.unparse(c.func) for c in ast.walk(node)
                     if isinstance(c, ast.Call)]
            assert not any(k in c for c in calls
                           for k in ("lcu", "urlopen", "read_text", "exists",
                                     "loads", "next", "exit")), calls


_CHILD_IMPORT = (
    "import sys, urllib.request\n"
    "calls = []\n"
    "def refuse(*args, **kwargs):\n"
    "    calls.append(args)\n"
    "    raise RuntimeError('test refuses network access')\n"
    "urllib.request.urlopen = refuse\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import scripts.team_planner_sync\n"
    "print('urlopen calls at import:', len(calls))\n"
)


def test_importing_the_script_makes_no_network_call_and_does_not_exit():
    """Runtime twin of the static guard, in a child process so the refusing
    urlopen can never leak into another test (RM-801)."""
    no_window = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD_IMPORT, str(ROOT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        creationflags=no_window,
    )
    assert r.returncode == 0, (r.stdout[-1000:], r.stderr[-2000:])
    assert r.stdout.strip().splitlines()[-1] == "urlopen calls at import: 0", r.stdout


@pytest.fixture
def tps(monkeypatch):
    """Import the script, then refuse and record every network call it makes."""
    test_the_module_body_runs_no_sync()
    sys.modules.pop(_MOD, None)
    mod = importlib.import_module(_MOD)
    calls: list[object] = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("test refuses network access")

    # Scoped to the script's own urllib.request.urlopen (RM-801).
    assert bind_urlopen(monkeypatch, mod, refuse) >= 1
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    yield mod
    sys.modules.pop(_MOD, None)
    assert calls == [], f"the script attempted network access: {calls}"


def _lockfile(tmp_path: pathlib.Path) -> pathlib.Path:
    lf = tmp_path / "client" / "lockfile"
    lf.parent.mkdir(parents=True)
    lf.write_bytes(_LOCKFILE_TEXT.encode("ascii"))
    return lf


def _meta(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    mf = tmp_path / "meta" / "tft_set17_meta.json"
    mf.parent.mkdir(parents=True)
    mf.write_bytes(json.dumps(payload).encode("utf-8"))
    return mf


def test_main_without_a_lockfile_returns_1_before_any_call(
        tps, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tps, "LOCKFILES", (tmp_path / "absent" / "lockfile",))
    monkeypatch.setattr(tps, "META_FILE", tmp_path / "absent" / "meta.json")
    assert tps.main() == 1
    assert "NO_LOCKFILE - launch League client first" in capsys.readouterr().out


def test_main_checks_the_lockfile_before_the_meta(
        tps, tmp_path, monkeypatch, capsys):
    """Order unchanged: no lockfile wins even when the meta is missing too."""
    monkeypatch.setattr(tps, "LOCKFILES", (tmp_path / "absent" / "lockfile",))
    monkeypatch.setattr(tps, "META_FILE", tmp_path / "absent" / "meta.json")
    tps.main()
    out = capsys.readouterr().out
    assert "NO_LOCKFILE" in out and "Meta file not found" not in out


def test_main_without_the_meta_file_returns_1(tps, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tps, "LOCKFILES", (_lockfile(tmp_path),))
    monkeypatch.setattr(tps, "META_FILE", tmp_path / "absent" / "meta.json")
    assert tps.main() == 1
    assert "Meta file not found" in capsys.readouterr().out


def test_main_with_no_s_or_a_comps_returns_1(tps, tmp_path, monkeypatch, capsys):
    """The tracked Set 17 skeleton (RM-846) has empty comps: the sync stops."""
    monkeypatch.setattr(tps, "LOCKFILES", (_lockfile(tmp_path),))
    monkeypatch.setattr(tps, "META_FILE",
                        _meta(tmp_path, {"tier_list": {}, "comps": {}}))
    assert tps.main() == 1
    assert "No S/A tier comps found in meta" in capsys.readouterr().out


def test_read_lockfile_takes_the_first_existing_path_and_parses_it(
        tps, tmp_path):
    lf = _lockfile(tmp_path)
    assert tps.read_lockfile((tmp_path / "nope", lf)) == ("50123", "synthetic-pw")
    assert tps.read_lockfile((tmp_path / "nope",)) is None


def test_the_default_paths_are_unchanged(tps):
    assert tps.META_FILE == ROOT / "data" / "meta" / "tft_set17_meta.json"
    # The defaults are Windows install paths. On Linux `Path` is a PosixPath
    # that keeps the whole backslash string as one name (CI run 41231114850),
    # so read them with Windows semantics on every OS.
    names = [pathlib.PureWindowsPath(p).name for p in tps.LOCKFILES]
    assert names == ["lockfile", "lockfile"]
    assert "(PBE)" in str(tps.LOCKFILES[0])
    assert tps.SET_ID == "TFTSet17"


def test_champ_to_lcu_id_strips_apostrophes_spaces_and_dots(tps):
    assert tps.champ_to_lcu_id("Kai'Sa") == "TFT17_KaiSa"
    assert tps.champ_to_lcu_id("Dr. Mundo") == "TFT17_DrMundo"
    assert tps.champ_to_lcu_id("Jhin") == "TFT17_Jhin"


def test_collect_target_comps_keeps_s_then_a_and_known_names_only(tps):
    meta = {
        "tier_list": {
            "A": [{"name": "Alpha"}, "Bravo"],
            "S": ["Charlie", {"name": "Unknown"}],
            "B": ["Delta"],
        },
        "comps": {"Alpha": {}, "Bravo": {}, "Charlie": {}, "Delta": {}},
    }
    assert tps.collect_target_comps(meta) == [
        ("Charlie", "S"), ("Alpha", "A"), ("Bravo", "A")]
    assert tps.collect_target_comps({}) == []


def test_main_syncs_one_comp_with_the_unchanged_request_sequence(
        tps, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tps, "LOCKFILES", (_lockfile(tmp_path),))
    monkeypatch.setattr(tps, "META_FILE", _meta(tmp_path, {
        "tier_list": {"S": ["Sniper Squad"]},
        "comps": {"Sniper Squad": {"core_units": ["Jhin"],
                                   "flex_units": ["Kai'Sa"]}},
    }))
    seen: list[tuple] = []
    built: list[tuple] = []

    def make_lcu(port, pw):
        built.append((port, pw))

        def lcu(method, ep, body=None, silent=False):
            seen.append((method, ep, body))
            return 204, ""
        return lcu

    monkeypatch.setattr(tps, "make_lcu", make_lcu)
    assert tps.main() == 0
    assert built == [("50123", "synthetic-pw")]
    team = tps.team_uuid_for("Sniper Squad")
    assert seen == [
        ("POST", _PLANNER + team, None),
        ("DELETE", _PLANNER + team + "/champions", None),
        ("POST", _PLANNER + team + "/import", ["TFT17_Jhin", "TFT17_KaiSa"]),
        ("PATCH", _PLANNER + team + "/name", {"name": "Sniper Squad"}),
    ]
    out = capsys.readouterr().out
    assert "[S] Sniper Squad: * import OK (2 units)" in out
    assert "Done: 1 synced, 0 failed" in out


def test_team_uuid_is_the_stable_uuid5_of_the_comp_name(tps):
    assert tps.team_uuid_for("X") == str(
        uuid.uuid5(uuid.NAMESPACE_DNS, "amberstone.X"))
