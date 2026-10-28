"""RM-258 residual: the item-263 Kai'Sa / Ashe hotfix writes through core.polled_json.

`main()` in tools/hotfix_kaisa_aram_ashe_sr_item263.py rewrote
data/champion_loadouts.json through a fixed `<name>.json.tmp` scratch file
plus a bare os.replace: no fsync before the rename, no WinError 5 retry, and
a scratch file left behind when the rename failed.

Each test points the tool's `_LOADOUTS` at a copy in tmp_path and spies on
`core.polled_json.atomic_write_bytes`, so the real data file is never read or
written.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import polled_json
from tools import hotfix_kaisa_aram_ashe_sr_item263 as tool


def _seed(tmp_path: Path, monkeypatch) -> Path:
    junk = [
        {"key": "ap-hybrid", "label": "AP Hybrid", "_is_primary": True,
         "items": ["Bloodthirster", "Lord Dominik's Regards"]},
        {"key": "bruiser-trinity", "label": "Trinity", "items": ["Axiom Arc"]},
    ]
    ench = [
        {"key": "utility-adc", "label": "Utility ADC", "_is_primary": True,
         "items": ["Blade of The Ruined King"]},
        {"key": "sr-enchanter", "label": "Enchanter",
         "items": ["Echoes of Helia", "Ardent Censer"]},
    ]
    data = {
        "champions": {
            "Kai'Sa": {"variants": {"aram-collapsed": {
                "items": [], "runes": {}, "summoners": [], "build_paths": junk}}},
            "Ashe": {"variants": {"sr-collapsed": {
                "items": [], "runes": {}, "summoners": [], "build_paths": ench}}},
            "Lux" + chr(0x2019): {"variants": {}},
        },
    }
    out = tmp_path / "champion_loadouts.json"
    out.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(tool, "_LOADOUTS", out)
    return out


def _expected(out: Path) -> bytes:
    data = json.loads(out.read_text(encoding="utf-8"))
    for (name, vk), paths in tool.PATCH.items():
        v = data["champions"][name]["variants"][vk]
        prim = next(pp for pp in paths if pp.get("_is_primary"))
        v["runes"] = dict(prim["runes"])
        v["summoners"] = list(prim["summoners"])
        v["items"] = list(prim["items"])
        v["build_paths"] = copy.deepcopy(paths)
    # The tool's historical text: ensure_ascii, indent 2, no trailing LF.
    return json.dumps(data, ensure_ascii=True, indent=2).encode("utf-8")


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

    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == out.read_bytes() == want
    assert b"\r\n" not in out.read_bytes()
    assert all(b < 0x80 for b in out.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    champs = json.loads(out.read_text(encoding="utf-8"))["champions"]
    kaisa = champs["Kai'Sa"]["variants"]["aram-collapsed"]
    assert [p["key"] for p in kaisa["build_paths"]] == [
        "on-hit", "ap-burst", "adc-crit"]
    assert kaisa["summoners"] == [4, 32]
    ashe = champs["Ashe"]["variants"]["sr-collapsed"]
    assert [p["key"] for p in ashe["build_paths"]] == [
        "utility-adc", "adc-crit", "adc-on-hit"]
    assert ashe["items"] == tool.PATCH[("Ashe", "sr-collapsed")][0]["items"]


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
