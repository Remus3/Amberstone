"""RM-910: the extractor must fail loudly when the DDragon champion or item
map comes back empty or short.

``fetch_ddragon`` read both maps with ``.get("data", {})``, so an empty or
reshaped DDragon payload flowed straight into champions.json / items.json and
the manifest counts, and it also made the RM-914 roster gate vacuous (an
empty DDragon map skips it by design). Every committed snapshot 16.10.1 ..
16.21.1 records 172-173 champions and 699-706 items (the throwback partition
applied, as the manifest counts it), so the floors sit at half the measured
minimum, the RM-807 (d) convention: 86 champions, 349 items.

``main()`` now exits ``EXIT_UPSTREAM_SHORT`` with a named reason right after
the DDragon fetch, before any lolmath, Meraki or CDragon fetch and any write.
The one way past it is ``--allow-short-upstream REASON`` (the same flag as the
Meraki / Arena gate), logged and recorded in the manifest
``upstream_short_override``.

Every test is synthetic (no network, no live-tree write).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import daemon_slayer_extract as dse  # noqa: E402

from agents.daemon_slayer.mode_variants import (  # noqa: E402
    VARIANT_CHAMPION_KEY_FLOOR,
    VARIANT_ITEM_ID_RANGE,
)


def _champs(n: int, key_base: int = 1) -> dict:
    return {f"Champ{i:03d}": {"key": str(key_base + i), "name": f"Champ{i:03d}", "stats": {}}
            for i in range(n)}


def _items(n: int, id_base: int = 1000) -> dict:
    return {str(id_base + i): {"name": f"Item{i}"} for i in range(n)}


def _dd(champions: dict, items: dict) -> dse.DDragonSnapshot:
    return dse.DDragonSnapshot(version="99.1.1", champions=champions, items=items)


# --- the floors ----------------------------------------------------------------

def test_floors_and_exit_code():
    assert dse.DDRAGON_CHAMPIONS_MIN == 86
    assert dse.DDRAGON_ITEMS_MIN == 349
    assert dse.EXIT_UPSTREAM_SHORT == 6


@pytest.mark.parametrize("champions", [{}, None, []])
def test_an_empty_champion_map_raises_naming_it(champions):
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_ddragon_counts(_dd(champions, _items(706)))
    msg = str(exc.value)
    assert "RM-910" in msg
    assert "ddragon_champions 0" in msg
    assert "--allow-short-upstream" in msg
    assert "ddragon_items" not in msg


@pytest.mark.parametrize("items", [{}, None, []])
def test_an_empty_item_map_raises_naming_it(items):
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_ddragon_counts(_dd(_champs(173), items))
    msg = str(exc.value)
    assert "ddragon_items 0" in msg
    assert "ddragon_champions" not in msg


def test_both_short_are_both_named():
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_ddragon_counts(_dd(_champs(3), _items(7)))
    msg = str(exc.value)
    assert "ddragon_champions 3" in msg and "ddragon_items 7" in msg


def test_throwback_rows_do_not_count_toward_the_floor():
    # A payload of only throwback rows ships an empty snapshot after the
    # partition, so it must not pass on its raw size.
    throwback_champs = _champs(173, key_base=VARIANT_CHAMPION_KEY_FLOOR)
    throwback_items = _items(706, id_base=VARIANT_ITEM_ID_RANGE[0])
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_ddragon_counts(_dd(throwback_champs, _items(706)))
    assert "ddragon_champions 0" in str(exc.value)
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_ddragon_counts(_dd(_champs(173), throwback_items))
    assert "ddragon_items 0" in str(exc.value)


def test_one_below_the_floor_raises_and_the_floor_passes():
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_ddragon_counts(_dd(_champs(dse.DDRAGON_CHAMPIONS_MIN - 1), _items(706)))
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_ddragon_counts(_dd(_champs(173), _items(dse.DDRAGON_ITEMS_MIN - 1)))
    out = dse.check_ddragon_counts(_dd(_champs(dse.DDRAGON_CHAMPIONS_MIN),
                                       _items(dse.DDRAGON_ITEMS_MIN)))
    assert out == {
        "ddragon_champions": {"count": dse.DDRAGON_CHAMPIONS_MIN,
                              "floor": dse.DDRAGON_CHAMPIONS_MIN},
        "ddragon_items": {"count": dse.DDRAGON_ITEMS_MIN, "floor": dse.DDRAGON_ITEMS_MIN},
    }


def test_every_committed_snapshot_is_clear_of_the_floors():
    data_root = ROOT / "data" / "daemon_slayer"
    snapshots = sorted(p for p in data_root.iterdir()
                       if p.is_dir() and (p / "manifest.json").exists()
                       and (p / "champions.json").exists() and (p / "items.json").exists())
    assert len(snapshots) >= 10, "the baseline was measured over 10 snapshots"
    for snap in snapshots:
        champs = json.loads((snap / "champions.json").read_text(encoding="utf-8"))
        items = json.loads((snap / "items.json").read_text(encoding="utf-8"))
        manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
        out = dse.check_ddragon_counts(_dd(champs["data"], items["data"]))
        assert "override_reason" not in out, snap.name
        assert out["ddragon_champions"]["count"] == manifest["ddragon_champion_count"], snap.name
        assert out["ddragon_items"]["count"] == manifest["ddragon_item_count"], snap.name


# --- the override --------------------------------------------------------------

def test_the_override_accepts_and_logs_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_ddragon_counts(_dd({}, _items(706)),
                                   override_reason="RM-999 adjudication")
    assert out["override_reason"] == "RM-999 adjudication"
    assert out["ddragon_champions"] == {"count": 0, "floor": dse.DDRAGON_CHAMPIONS_MIN}
    warnings = " ".join(r.getMessage() for r in caplog.records
                        if r.levelno == logging.WARNING)
    assert "RM-910" in warnings and "RM-999 adjudication" in warnings


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_a_blank_override_reason_does_not_override(reason):
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_ddragon_counts(_dd({}, _items(706)), override_reason=reason)


def test_an_unneeded_override_is_not_recorded():
    out = dse.check_ddragon_counts(_dd(_champs(173), _items(706)),
                                   override_reason="not needed")
    assert "override_reason" not in out


# --- main(): the gate runs right after the DDragon fetch --------------------------

def _wire_main(monkeypatch, tmp_path, champions, items, argv):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: _dd(champions, items))
    calls: list[str] = []

    def _record(name, result):
        def _fn(*a, **k):
            calls.append(name)
            return result() if callable(result) else result
        return _fn

    monkeypatch.setattr(dse, "discover_chunks", _record("discover_chunks",
                                                        ("u/scen.js", "u/aram.js")))
    monkeypatch.setattr(dse, "fetch_arena_augments", _record("fetch_arena_augments", {}))
    monkeypatch.setattr(dse, "fetch_meraki_items", _record("fetch_meraki_items", {}))
    monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay",
                        _record("fetch_meraki_perlevel_overlay", {}))
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", "99.1.1", *argv])
    return data_root, calls


@pytest.mark.parametrize("champions, items, named", [
    ({}, _items(706), "ddragon_champions"),
    (_champs(173), {}, "ddragon_items"),
])
def test_main_exits_non_zero_and_fetches_and_writes_nothing_on_a_short_ddragon(
        monkeypatch, tmp_path, caplog, champions, items, named):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root, calls = _wire_main(monkeypatch, tmp_path, champions, items, [])
    rc = dse.main()
    assert rc == dse.EXIT_UPSTREAM_SHORT
    assert not data_root.exists() or not any(data_root.rglob("*"))
    assert calls == [], f"fetched past a short DDragon map: {calls}"
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-910" in errors and named in errors


def test_main_skips_an_already_extracted_patch_before_the_gate(monkeypatch, tmp_path):
    # The skip path writes nothing but current.txt and fetches nothing more,
    # so it stays ahead of the gate (an unchanged no-op on a re-run).
    data_root, calls = _wire_main(monkeypatch, tmp_path, {}, {}, [])
    (data_root / "99.1.1").mkdir(parents=True)
    (data_root / "99.1.1" / "manifest.json").write_text("{}", encoding="utf-8")
    assert dse.main() == 0
    assert calls == []
