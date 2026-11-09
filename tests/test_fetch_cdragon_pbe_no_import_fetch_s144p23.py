"""RM-1174: scripts/fetch_cdragon_pbe.py runs nothing at import.

The script fetched two CommunityDragon PBE files at MODULE LEVEL: importing
it opened two network requests and rewrote three files under data/meta/,
one of them the TRACKED planner code map
data/meta/tft_set17_champion_codes.json that tft/tft_live_analysis.py reads.
Nothing could import it, so none of its logic had a test, and every write
was an in-place ``write_bytes`` (no scratch, no fsync, no WinError 5 retry),
so a reader polling the map could see a torn or empty file. Same class as
scripts/probe_missing_codes.py (RM-1131) and scripts/team_planner_sync.py
(RM-1172).

The work now lives in ``main()`` behind ``if __name__ == "__main__"``; the
Set 17 extraction and the merge are importable helpers, and every write goes
through ``core.polled_json.atomic_write_bytes``. The merged map keeps its
bytes (indent 2, sorted keys, LF, no trailing newline). No test touches the
network: the import is proved call-free in a CHILD process whose
``urllib.request.urlopen`` and ``OpenerDirector.open`` are recorders that
raise, and in this process every test refuses and records the script's OWN
``open_consented`` (the consent opener every fetch goes through since
RM-1441; a module attribute, never the process-wide stdlib one, RM-801).
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

_SRC = ROOT / "scripts" / "fetch_cdragon_pbe.py"
_MOD = "scripts.fetch_cdragon_pbe"
_CODES_NAME = "tft_set17_champion_codes.json"

_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign,
                ast.AnnAssign)

# Synthetic team-planner rows (hand-written, not a CommunityDragon capture).
_PLANNER_ROWS = [
    {"character_id": "TFT17_Alpha", "display_name": "Alpha",
     "team_planner_code": 11},
    {"character_id": "TFT_Set17_Beta", "display_name": "Beta",
     "team_planner_code": 0},
    {"character_id": "TFT16_Gamma", "display_name": "Gamma",
     "team_planner_code": 33},
    {"character_id": "TFT17_NoCode", "display_name": "NoCode"},
    {"character_id": "TFT17_NoName", "display_name": "",
     "team_planner_code": 44},
    "not-a-dict",
]


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


def test_the_module_body_runs_no_fetch():
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
            assert not any(k in c for c in calls
                           for k in ("fetch", "urlopen", "read_text",
                                     "write", "print")), calls


_CHILD_IMPORT = (
    "import sys, urllib.request\n"
    "calls = []\n"
    "def refuse(*args, **kwargs):\n"
    "    calls.append(args)\n"
    "    raise RuntimeError('test refuses network access')\n"
    "urllib.request.urlopen = refuse\n"
    "urllib.request.OpenerDirector.open = refuse\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import scripts.fetch_cdragon_pbe\n"
    "print('urlopen calls at import:', len(calls))\n"
)


def test_importing_the_script_makes_no_network_call_and_prints_nothing():
    """Runtime twin of the static guard, in a child process so the refusing
    urlopen can never leak into another test (RM-801)."""
    test_the_module_body_runs_no_fetch()
    no_window = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD_IMPORT, str(ROOT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        check=False, creationflags=no_window,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip().splitlines() == ["urlopen calls at import: 0"], r.stdout


@pytest.fixture
def pbe(monkeypatch):
    """Import the script, then refuse and record every network call it makes."""
    test_the_module_body_runs_no_fetch()
    sys.modules.pop(_MOD, None)
    mod = importlib.import_module(_MOD)
    calls: list[object] = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("test refuses network access")

    # Scoped to the script's own consent opener (RM-801, RM-1441).
    monkeypatch.setattr(mod, "open_consented", refuse)
    yield mod
    sys.modules.pop(_MOD, None)
    assert calls == [], f"the script attempted network access: {calls}"


def test_the_default_targets_are_the_data_meta_files(pbe):
    meta = ROOT / "data" / "meta"
    assert meta / _CODES_NAME == pbe.CODES_FILE
    assert meta / "cdragon_teamplanner_pbe.json" == pbe.TEAMPLANNER_RAW
    assert meta / "cdragon_tft_pbe.json" == pbe.TFT_RAW


def test_set17_codes_keeps_only_named_set17_rows_with_a_code(pbe):
    assert pbe.set17_codes(_PLANNER_ROWS) == {"Alpha": 11, "Beta": 0}
    assert pbe.set17_codes({"not": "a list"}) == {}


def test_merge_codes_overlays_new_codes_and_keeps_the_byte_shape(pbe, tmp_path):
    target = tmp_path / _CODES_NAME
    target.write_bytes(b'{"Alpha": 1, "Zeta": 9}')
    merged = pbe.merge_codes(target, {"Alpha": 11, "Beta": 0})
    expected = {"Alpha": 11, "Beta": 0, "Zeta": 9}
    assert merged == expected
    assert target.read_bytes() == json.dumps(
        expected, indent=2, sort_keys=True).encode("utf-8")
    assert b"\r" not in target.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [_CODES_NAME]


def test_merge_codes_creates_a_missing_map(pbe, tmp_path):
    target = tmp_path / _CODES_NAME
    assert pbe.merge_codes(target, {"Alpha": 11}) == {"Alpha": 11}
    assert json.loads(target.read_bytes()) == {"Alpha": 11}


def test_an_exhausted_replace_keeps_the_map_and_no_scratch(
        pbe, tmp_path, monkeypatch):
    target = tmp_path / _CODES_NAME
    original = b'{"Alpha": 1}'
    target.write_bytes(original)

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        pbe.merge_codes(target, {"Alpha": 11})
    assert target.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == [_CODES_NAME]


def test_main_with_the_network_refused_writes_nothing_and_exits_zero(
        pbe, tmp_path, monkeypatch, capsys):
    """Both fetches fail closed (the old per-section try/except), so main()
    reports each failure, leaves every target untouched and exits 0."""
    codes = tmp_path / _CODES_NAME
    codes.write_bytes(b'{"Alpha": 1}')
    monkeypatch.setattr(pbe, "CODES_FILE", codes)
    monkeypatch.setattr(pbe, "TEAMPLANNER_RAW", tmp_path / "planner.json")
    monkeypatch.setattr(pbe, "TFT_RAW", tmp_path / "tft.json")
    real_fetch = pbe.fetch
    seen: list[str] = []

    def recording_fetch(url):
        seen.append(url)
        return real_fetch(url)  # reaches the refusing open_consented

    monkeypatch.setattr(pbe, "fetch", recording_fetch)
    # These two refusals are expected: route them past the fixture recorder.
    with pytest.MonkeyPatch.context() as mp:
        def refuse(*args, **kwargs):
            raise RuntimeError("test refuses network access")
        mp.setattr(pbe, "open_consented", refuse)
        assert pbe.main() == 0
    out = capsys.readouterr().out
    assert "team planner FAILED" in out
    assert "TFT en_us FAILED" in out
    assert seen == [pbe.TEAMPLANNER_URL, pbe.TFT_EN_US_URL]
    assert codes.read_bytes() == b'{"Alpha": 1}'
    assert sorted(p.name for p in tmp_path.iterdir()) == [_CODES_NAME]


def test_main_with_served_payloads_writes_all_three_files(
        pbe, tmp_path, monkeypatch, capsys):
    codes = tmp_path / _CODES_NAME
    planner = tmp_path / "planner.json"
    tft = tmp_path / "tft.json"
    monkeypatch.setattr(pbe, "CODES_FILE", codes)
    monkeypatch.setattr(pbe, "TEAMPLANNER_RAW", planner)
    monkeypatch.setattr(pbe, "TFT_RAW", tft)
    planner_raw = json.dumps(_PLANNER_ROWS)
    tft_raw = json.dumps({"champions": [], "traits": [], "items": []})
    served = {pbe.TEAMPLANNER_URL: planner_raw, pbe.TFT_EN_US_URL: tft_raw}
    monkeypatch.setattr(pbe, "fetch", lambda url: served[url])
    assert pbe.main() == 0
    assert planner.read_bytes() == planner_raw.encode("utf-8")
    assert tft.read_bytes() == tft_raw.encode("utf-8")
    assert json.loads(codes.read_bytes()) == {"Alpha": 11, "Beta": 0}
    out = capsys.readouterr().out
    assert "Merged 2 CDragon codes into 2 total" in out


def test_the_writer_does_not_write_in_place(pbe):
    """Source pin: the script delegates every write instead of doing it."""
    src = _SRC.read_text(encoding="utf-8")
    assert ".write_bytes(" not in src
    assert ".write_text(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src
    assert pbe.atomic_write_bytes is polled_json.atomic_write_bytes
