"""RM-258 residual: the item-275 thin-ARAM-ADC hotfix writes through core.polled_json.

`run()` in tools/hotfix_thin_aram_adc_item275.py rewrote
data/champion_loadouts.json through a fixed `<name>.json.tmp` scratch file
plus a bare os.replace: no fsync before the rename, no WinError 5 retry, and
a scratch file left behind when the rename failed.

Each test points the tool's `_LOADOUTS` at a copy in tmp_path and spies on
`core.polled_json.atomic_write_bytes`, so the real data file is never read or
written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import hotfix_thin_aram_adc_item275 as tool

_THIN = ["Blade of The Ruined King", "Berserker's Greaves",
         "Lord Dominik's Regards", "Runaan's Hurricane"]


def _seed(tmp_path: Path, monkeypatch) -> Path:
    jinx = [
        {"key": "adc-crit", "label": "Crit", "_is_primary": True,
         "items": list(_THIN)},
        {"key": "on-hit", "label": "On-Hit", "items": ["Wit's End"] * 6},
    ]
    lulu = [
        {"key": "on-hit", "label": "On-Hit", "_is_primary": True,
         "items": ["Nashor's Tooth"] * 6},
    ]
    data = {
        "champions": {
            "Kai" + chr(0x2019) + "Sa": {"variants": {}},
            "Jinx": {"variants": {"aram-collapsed": {"build_paths": jinx}}},
            "Lulu": {"variants": {"aram-collapsed": {"build_paths": lulu}}},
        },
    }
    out = tmp_path / "champion_loadouts.json"
    out.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(tool, "_LOADOUTS", out)
    return out


def _expected(out: Path) -> bytes:
    data = json.loads(out.read_text(encoding="utf-8"))
    assert tool.apply(data) == 2
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


def test_run_writes_through_polled_json(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    want = _expected(out)

    assert tool.run() == 0

    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == out.read_bytes() == want
    assert b"\r\n" not in out.read_bytes()
    assert all(b < 0x80 for b in out.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    champs = json.loads(out.read_text(encoding="utf-8"))["champions"]
    jinx = champs["Jinx"]["variants"]["aram-collapsed"]
    label, items = tool._EXTEND[("Jinx", "adc-crit")]
    assert jinx["build_paths"][0]["items"] == items
    assert jinx["build_paths"][0]["label"] == label
    assert jinx["items"] == items
    lulu = champs["Lulu"]["variants"]["aram-collapsed"]
    assert lulu["build_paths"][0]["label"] == tool._AP_ONHIT_LABEL


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
        tool.run()
    assert len(fired) == 1
    assert out.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_dry_run_and_idempotent_rerun_write_nothing(tmp_path, monkeypatch, spy):
    out = _seed(tmp_path, monkeypatch)
    prior = out.read_bytes()
    assert tool.run(dry_run=True) == 0
    assert spy == []
    assert out.read_bytes() == prior

    assert tool.run() == 0
    written = out.read_bytes()
    assert tool.run() == 0
    assert len(spy) == 1
    assert out.read_bytes() == written


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".json.tmp" not in text
    assert "polled_json.atomic_write_bytes(" in text
