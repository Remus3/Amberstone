"""RM-807 (d): the extractor must fail loudly when the Meraki bulk items or the
CDragon Arena augment upstream comes back empty or short.

``fetch_meraki_items`` turned an empty upstream dict into ``count: 0`` and
``fetch_arena_augments`` turned an empty (or non-dict) dump into an empty list,
and both were written into ``items_meraki.json`` / ``arena_augments.json`` and
the manifest exactly like real data. Every committed snapshot 16.10.1 ..
16.21.1 carries 320 Meraki items and 220-227 Arena augments, so a count under
half of that measured minimum is an upstream reset or a shape drift, not a
patch.

``main()`` now exits ``EXIT_UPSTREAM_SHORT`` with a named reason after those two
fetches and before the per-champion Meraki overlay fetch and any write. The one
way past it is ``--allow-short-upstream REASON``, which logs a WARNING and
records the override (reason, floors, counts) in the manifest.

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


def _meraki(n: int) -> dict:
    return {"count": n, "items": {str(1000 + i): {"name": f"Item{i}"} for i in range(n)}}


def _augments(n: int) -> dict:
    return {"count": n, "augments": [{"id": i, "name": f"Aug{i}"} for i in range(n)]}


# --- the floors ----------------------------------------------------------------

def test_floors_and_exit_code():
    assert dse.MERAKI_ITEMS_MIN == 160
    assert dse.ARENA_AUGMENTS_MIN == 110
    assert dse.EXIT_UPSTREAM_SHORT not in (0, dse.EXIT_ARAM_NEUTRAL,
                                           dse.EXIT_LOLMATH_ONLY_NO_SNAPSHOT,
                                           dse.EXIT_LOLMATH_DEGENERATE)


@pytest.mark.parametrize("payload", [{"count": 0, "items": {}}, {"count": 0}, {}, None])
def test_an_empty_meraki_items_payload_raises_naming_it(payload):
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_upstream_counts(_augments(225), payload)
    msg = str(exc.value)
    assert "RM-807" in msg
    assert "meraki_items 0" in msg
    assert "--allow-short-upstream" in msg
    assert "arena_augments" not in msg


@pytest.mark.parametrize("payload", [{"count": 0, "augments": []}, {"count": 0}, {}, None])
def test_an_empty_arena_augments_payload_raises_naming_it(payload):
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_upstream_counts(payload, _meraki(320))
    msg = str(exc.value)
    assert "arena_augments 0" in msg
    assert "meraki_items" not in msg


def test_both_short_are_both_named():
    with pytest.raises(dse.ShortUpstreamError) as exc:
        dse.check_upstream_counts(_augments(3), _meraki(7))
    msg = str(exc.value)
    assert "arena_augments 3" in msg and "meraki_items 7" in msg


def test_the_count_is_measured_from_the_payload_not_its_count_key():
    # A stale or forged "count" must not pass an empty body.
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_upstream_counts({"count": 225, "augments": []}, _meraki(320))
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_upstream_counts(_augments(225), {"count": 320, "items": {}})


def test_one_below_the_floor_raises_and_the_floor_passes():
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_upstream_counts(_augments(dse.ARENA_AUGMENTS_MIN - 1), _meraki(320))
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_upstream_counts(_augments(225), _meraki(dse.MERAKI_ITEMS_MIN - 1))
    out = dse.check_upstream_counts(_augments(dse.ARENA_AUGMENTS_MIN),
                                    _meraki(dse.MERAKI_ITEMS_MIN))
    assert out["arena_augments"]["count"] == dse.ARENA_AUGMENTS_MIN
    assert out["meraki_items"]["count"] == dse.MERAKI_ITEMS_MIN
    assert "override_reason" not in out


def test_every_committed_snapshot_is_clear_of_the_floors():
    data_root = ROOT / "data" / "daemon_slayer"
    snapshots = sorted(p for p in data_root.iterdir()
                       if p.is_dir() and (p / "items_meraki.json").exists())
    assert len(snapshots) >= 10, "the baseline was measured over 10 snapshots"
    for snap in snapshots:
        meraki = json.loads((snap / "items_meraki.json").read_text(encoding="utf-8"))
        augs = json.loads((snap / "arena_augments.json").read_text(encoding="utf-8"))
        out = dse.check_upstream_counts(augs, meraki)
        assert "override_reason" not in out, snap.name


# --- the override --------------------------------------------------------------

def test_the_override_accepts_and_logs_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="daemon_slayer_extract")
    out = dse.check_upstream_counts(_augments(0), _meraki(320),
                                    override_reason="RM-999 adjudication")
    assert out["override_reason"] == "RM-999 adjudication"
    assert out["arena_augments"] == {"count": 0, "floor": dse.ARENA_AUGMENTS_MIN}
    warnings = " ".join(r.getMessage() for r in caplog.records
                        if r.levelno == logging.WARNING)
    assert "RM-807" in warnings and "RM-999 adjudication" in warnings


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_blank_override_reason_does_not_override(reason):
    with pytest.raises(dse.ShortUpstreamError):
        dse.check_upstream_counts(_augments(0), _meraki(320), override_reason=reason)


def test_an_unneeded_override_is_not_recorded():
    out = dse.check_upstream_counts(_augments(225), _meraki(320),
                                    override_reason="not needed")
    assert "override_reason" not in out


# --- main(): the gate runs before the overlay fetch and any write ----------------

CLEAN_DAMAGE = {f"Champ{i:03d}": {"physical": 0.8, "magical": 0.1, "trued": 0.1}
                for i in range(173)}
CLEAN_SKILLS = {f"Champ{i:03d}": ["Q", "E", "W", "Q", "R"] for i in range(173)}
CLEAN_ARAM = {f"Champ{i:03d}": {"aramDamageDealt": 1.05} for i in range(173)}


def _lolmath():
    return dse.LolmathExtract(
        cooldowns={"Aatrox": {"Q": [4.0]}}, roles={"Aatrox": ["FIGHTER"]},
        ratings={}, lane_positions=["top"], scenarios={"aatrox": [{}]},
        chunk_url="u/scen.js", chunk_bytes=1,
        aram_modifiers={}, damage_distribution={}, skill_orders={},
        data_chunk_url="", data_chunk_bytes=0,
    )


def _wire_main(monkeypatch, tmp_path, augments, meraki, argv):
    data_root = tmp_path / "data" / "daemon_slayer"
    monkeypatch.setattr(dse, "ROOT", tmp_path)
    monkeypatch.setattr(dse, "DATA_ROOT", data_root)
    monkeypatch.setattr(dse, "fetch_ddragon", lambda: dse.DDragonSnapshot(
        version="99.1.1",
        champions={"Aatrox": {"key": "266", "name": "Aatrox", "stats": {}}},
        items={},
    ))
    monkeypatch.setattr(dse, "discover_chunks",
                        lambda *a, **k: ("u/scen.js", "u/aram.js"))
    monkeypatch.setattr(dse, "fetch_chunk", lambda url: "")
    monkeypatch.setattr(dse, "extract_from_bodies",
                        lambda bodies, preferred: _lolmath())
    monkeypatch.setattr(dse, "extract_data_blocks", lambda bodies, preferred: {
        "aram_modifiers": CLEAN_ARAM,
        "damage_distribution": CLEAN_DAMAGE,
        "skill_orders": CLEAN_SKILLS,
        "data_chunk_url": "u/aram.js",
        "data_chunk_bytes": 1,
        "block_sources": {"aram_modifiers": "u/aram.js"},
    })
    overlay_calls: list[int] = []

    def _overlay(ids):
        overlay_calls.append(len(ids))
        return {}

    monkeypatch.setattr(dse, "fetch_meraki_perlevel_overlay", _overlay)
    monkeypatch.setattr(dse, "fetch_arena_augments", lambda: augments)
    monkeypatch.setattr(dse, "fetch_meraki_items", lambda: meraki)
    monkeypatch.setattr(sys, "argv", ["daemon_slayer_extract.py", "--patch", "99.1.1", *argv])
    return data_root, overlay_calls


@pytest.mark.parametrize("augments, meraki, named", [
    (_augments(225), _meraki(0), "meraki_items"),
    (_augments(0), _meraki(320), "arena_augments"),
])
def test_main_exits_non_zero_and_writes_nothing_on_a_short_upstream(
        monkeypatch, tmp_path, caplog, augments, meraki, named):
    caplog.set_level(logging.ERROR, logger="daemon_slayer_extract")
    data_root, overlay_calls = _wire_main(monkeypatch, tmp_path, augments, meraki, [])
    rc = dse.main()
    assert rc == dse.EXIT_UPSTREAM_SHORT
    assert not data_root.exists() or not any(data_root.rglob("*"))
    assert overlay_calls == [], "the per-champion overlay fetch ran before the gate"
    errors = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "RM-807" in errors and named in errors


def test_main_override_writes_and_records_the_override(monkeypatch, tmp_path):
    reason = "RM-999 adjudication: CDragon arena dump reset"
    data_root, overlay_calls = _wire_main(monkeypatch, tmp_path, _augments(0), _meraki(320),
                                          ["--allow-short-upstream", reason])
    assert dse.main() == 0
    assert overlay_calls == [1]
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    rec = manifest["upstream_short_override"]
    assert rec["flag"] == "--allow-short-upstream"
    assert rec["reason"] == reason
    assert rec["arena_augments"] == {"count": 0, "floor": dse.ARENA_AUGMENTS_MIN}
    assert rec["meraki_items"] == {"count": 320, "floor": dse.MERAKI_ITEMS_MIN}


def test_main_clean_upstream_records_no_override(monkeypatch, tmp_path):
    data_root, _ = _wire_main(monkeypatch, tmp_path, _augments(225), _meraki(320), [])
    assert dse.main() == 0
    manifest = json.loads((data_root / "99.1.1" / "manifest.json").read_text(encoding="utf-8"))
    assert "upstream_short_override" not in manifest
    assert manifest["arena_augments"]["count"] == 225
    assert manifest["meraki_items"]["count"] == 320
