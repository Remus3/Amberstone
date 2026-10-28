"""RM-258 residual: the ranged-only melee backfill writes through core.polled_json.

`main()` in tools/hotfix_ranged_only_melee_loadouts.py rewrote
data/champion_loadouts.json through a fixed `<name>.json.tmp` scratch file
plus a bare os.replace: no fsync before the rename, no WinError 5 retry, and
a scratch file left behind when the rename failed.

Each test points the tool's `_LOADOUTS` at a copy in tmp_path, pins
`_is_melee` (so no DS champion snapshot is read) and spies on
`core.polled_json.atomic_write_bytes`, so the real data file is never read or
written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import hotfix_ranged_only_melee_loadouts as tool

_RUNAAN = "Runaan's Hurricane"
_LUX = "Lux" + chr(0x2019)


def _seed(tmp_path: Path, monkeypatch) -> Path:
    garen_path = {"key": "bruiser-on-hit", "label": "On-hit", "_is_primary": True,
                  "items": ["Stridebreaker", _RUNAAN, "Sterak's Gage"]}
    data = {
        "champions": {
            "Garen": {"variants": {"sr-collapsed": {
                "items": ["Stridebreaker", _RUNAAN, "Sterak's Gage"],
                "build_paths": [garen_path]}}},
            "Ashe": {"variants": {"sr-collapsed": {
                "items": [_RUNAAN], "build_paths": [
                    {"key": "adc-crit", "_is_primary": True,
                     "items": [_RUNAAN]}]}}},
            _LUX: {"variants": {}},
        },
    }
    out = tmp_path / "champion_loadouts.json"
    out.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(tool, "_LOADOUTS", out)
    monkeypatch.setattr(tool, "_is_melee", lambda champ: champ == "Garen")
    return out


def _expected(out: Path) -> bytes:
    data = json.loads(out.read_text(encoding="utf-8"))
    tool.apply(data)
    # The tool's historical text: ensure_ascii, indent 2, one trailing LF.
    return (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_main_writes_through_polled_json(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    want = _expected(out)

    tool.main()

    raw = out.read_bytes()
    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == raw == want
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert all(b < 0x80 for b in raw)
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    champs = json.loads(raw.decode("utf-8"))["champions"]
    garen = champs["Garen"]["variants"]["sr-collapsed"]
    assert _RUNAAN not in garen["build_paths"][0]["items"]
    assert len(garen["build_paths"][0]["items"]) == 3
    assert garen["items"] == garen["build_paths"][0]["items"]
    # A ranged champion keeps its Runaan's.
    assert champs["Ashe"]["variants"]["sr-collapsed"]["items"] == [_RUNAAN]
    assert _LUX in champs


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = _seed(tmp_path, monkeypatch)
    prior = out.read_bytes()
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main()
    assert len(fired) == 1
    assert out.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_rerun_rewrites_the_same_bytes(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    tool.main()
    written = out.read_bytes()
    tool.main()
    assert len(spy) == 2
    assert spy[1][1] == written == out.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".json.tmp" not in text
    assert "polled_json.atomic_write_bytes(" in text
