"""RM-873: the G5-01 anvil-shadow probe prints a verdict line, never a traceback.

Since RM-867 archive-split the 30 leaked fixture rows, an absent
``data/anvil_shadow.jsonl`` is the normal pre-game state (core.anvil_shadow
recreates it on the first real anvil row). The GATE 5 DRAIN CARD's one-liner
``open()``-ed the file unguarded, so the probe printed FileNotFoundError where
a verdict belongs. ``tools/anvil_shadow_probe.py`` carries the probe: one clean
FAIL line when the file is absent (or holds no readable row), and the card's
existing summary line when it is present. Every test uses a tmp_path file;
none reads or writes the live tree.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core import anvil_shadow
from tools import anvil_shadow_probe as probe

_REPO = Path(__file__).resolve().parent.parent
_TOOL = _REPO / "tools" / "anvil_shadow_probe.py"

_ROW = {
    "ts": "2026-10-25T20:01:02+00:00",
    "mode": "arena",
    "champion": "Vayne",
    "round": 4,
    "offered": ["Bloodthirster", "Mercury's Treads"],
    "owned": ["Boots"],
    "engine_version": "?",
    "native": {"take": "Bloodthirster", "why": "lifesteal"},
    "deterministic": {"take": "Bloodthirster"},
}


def _write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in rows))
    return path


def test_default_path_is_the_writers_shadow_path():
    # The probe must read the file the live writer appends to, not a copy.
    # tests/conftest.py redirects anvil_shadow.SHADOW_PATH into tmp for the
    # suite (RM-406), so pin the writer's SOURCE default, not the attribute.
    src = Path(anvil_shadow.__file__).read_text(encoding="utf-8")
    assert 'SHADOW_PATH: Path = _APP_DIR / "data" / "anvil_shadow.jsonl"' in src
    assert anvil_shadow._APP_DIR.resolve() == _REPO
    assert probe.SHADOW_PATH == _REPO / "data" / "anvil_shadow.jsonl"


def test_absent_file_prints_the_clean_fail_line(tmp_path):
    code, line = probe.probe(tmp_path / "anvil_shadow.jsonl", label="data/anvil_shadow.jsonl")
    assert code == 1
    assert line == "FAIL: data/anvil_shadow.jsonl absent (no real anvil row yet)"


def test_present_file_prints_the_cards_summary_of_the_last_row(tmp_path):
    older = dict(_ROW, ts="2026-10-25T19:00:00+00:00", champion="Lux")
    path = _write_rows(tmp_path / "anvil_shadow.jsonl", [older, _ROW])
    code, line = probe.probe(path)
    assert code == 0
    # Same fields, order and spacing as the card's former one-liner:
    # print(len(rs), r['ts'], r['champion'], r['round'], r['offered'], r['native'].get('take'))
    expected = " ".join(
        str(x)
        for x in (2, _ROW["ts"], "Vayne", 4, _ROW["offered"], "Bloodthirster")
    )
    assert line == expected


def test_blank_lines_are_not_rows(tmp_path):
    path = tmp_path / "anvil_shadow.jsonl"
    path.write_bytes(json.dumps(_ROW).encode() + b"\n\n")
    code, line = probe.probe(path)
    assert code == 0
    assert line.startswith("1 ")


def test_empty_file_is_a_fail_line_not_an_index_error(tmp_path):
    path = tmp_path / "anvil_shadow.jsonl"
    path.write_bytes(b"")
    code, line = probe.probe(path, label="data/anvil_shadow.jsonl")
    assert code == 1
    assert line == "FAIL: data/anvil_shadow.jsonl has no rows"


def test_unparseable_row_is_a_fail_line_naming_the_line(tmp_path):
    path = tmp_path / "anvil_shadow.jsonl"
    path.write_bytes(json.dumps(_ROW).encode() + b"\n{not json\n")
    code, line = probe.probe(path, label="data/anvil_shadow.jsonl")
    assert code == 1
    assert line == "FAIL: data/anvil_shadow.jsonl line 2 is not a JSON object"


def test_row_without_a_native_block_prints_none_for_the_take(tmp_path):
    row = {k: v for k, v in _ROW.items() if k != "native"}
    code, line = probe.probe(_write_rows(tmp_path / "anvil_shadow.jsonl", [row]))
    assert code == 0
    assert line.endswith(" None")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_TOOL), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO),
    )


def test_cli_absent_path_exits_1_with_one_line_and_no_traceback(tmp_path):
    res = _run_cli("--path", str(tmp_path / "missing.jsonl"))
    assert res.returncode == 1
    assert res.stderr == ""
    lines = res.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("FAIL: ")
    assert lines[0].endswith(" absent (no real anvil row yet)")


def test_cli_present_path_exits_0_with_the_summary(tmp_path):
    path = _write_rows(tmp_path / "anvil_shadow.jsonl", [_ROW])
    res = _run_cli("--path", str(path))
    assert res.returncode == 0
    assert res.stderr == ""
    assert res.stdout.splitlines() == [probe.probe(path)[1]]
