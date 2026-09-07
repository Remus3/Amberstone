# arch: prefer-CDragon semantic block-matcher structural invariants | section=ds-tests | frozen=no
"""Structural invariants for the prefer-CDragon ratio block-matcher (default ON).

``_apply_cdragon_ratio_preference`` re-sources Meraki damage-block ratios from the
CDragon mechanical sidecar. The original positional ``zip`` mis-paired multi-block
abilities (a transform form's calc onto the wrong block, a tooltip aggregate onto a
per-instance block) and double-counted AD (CDragon ``total_ad_pct`` appended beside
Meraki ``bonus_ad_pct``). These tests pin the SEMANTIC matcher's structural
invariants - they instantiate ``AbilitiesSnapshot.load(prefer_cdragon_ratios=True)``
directly and assert no same-family double-count, stable block counts, and that the
known ambiguous multi-block abilities (Ambessa Q, Gwen R, Udyr R) fall back to
Meraki rather than mis-pair. The default (flag OFF) path is covered by
``test_cdragon_ratio_preference.py``.

The three live-snapshot tests SKIP when the committed CDragon sidecar is absent for
the current patch (a fresh clone / partial checkout) so they never silently pass as
a vacuous no-op - the synthetic tmp_path tests carry the matcher assertions either
way.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import (
    _CDRAGON_RATIO_SIDECAR,
    _DEFAULT_DATA_ROOT,
    AbilitiesSnapshot,
)

_AD_FIELDS = ("total_ad_pct", "bonus_ad_pct")
_HP_FIELDS = ("caster_max_hp_pct", "target_max_hp_pct")
_KEYS = ("P", "Q", "W", "E", "R")


def _current_patch() -> str | None:
    pointer = _DEFAULT_DATA_ROOT / "current.txt"
    if not pointer.exists():
        return None
    return pointer.read_text(encoding="utf-8").strip() or None


def _require_live_sidecar() -> None:
    """Fail (never skip) when the current-patch sidecar is not on disk.

    2026-07-27 skip audit: both halves are TRACKED -
    data/daemon_slayer/current.txt and
    data/daemon_slayer/<patch>/cdragon_ability_ratios.json are committed.
    Absence therefore means a committed artifact was deleted or the patch
    pointer moved ahead of its extract - exactly the drift these tests exist
    to catch.
    """
    patch = _current_patch()
    assert patch, f"tracked patch pointer {_DEFAULT_DATA_ROOT / 'current.txt'} is missing or empty"
    sidecar = _DEFAULT_DATA_ROOT / patch / _CDRAGON_RATIO_SIDECAR
    assert sidecar.exists(), (
        f"current.txt points at patch {patch!r} but the tracked CDragon sidecar "
        f"{sidecar} is not committed"
    )


def _live_pair():
    """The current committed snapshot loaded flag-OFF and flag-ON.

    ``prefer_cdragon_ratios`` now defaults ON (the cutover), so the Meraki
    baseline must be requested EXPLICITLY with the flag forced OFF - a bare
    ``load()`` would return the CDragon-preferred snapshot and make off==on.
    """
    off = AbilitiesSnapshot.load(prefer_cdragon_ratios=False)
    on = AbilitiesSnapshot.load(prefer_cdragon_ratios=True)
    return off, on


def test_live_sidecar_actually_re_sources():
    """Guard the guard: flag-ON must differ from flag-OFF for at least one form,
    proving the sidecar is loaded and the invariant tests below are non-vacuous."""
    _require_live_sidecar()
    off, on = _live_pair()
    changed = 0
    for cid in off.champion_ids():
        for key in _KEYS:
            for a, b in zip(off.get_abilities(cid).get(key, ()),
                            on.get_abilities(cid).get(key, ())):
                if a.damage_blocks != b.damage_blocks:
                    changed += 1
    assert changed > 0, "flag-ON identical to flag-OFF - sidecar not exercised"


def test_no_same_family_double_count_flag_on():
    """No damage block may carry two fields from one stat family (AD or HP)."""
    _require_live_sidecar()
    _off, on = _live_pair()
    ad_double = []
    hp_double = []
    for cid in on.champion_ids():
        for key in _KEYS:
            for form in on.get_abilities(cid).get(key, ()):
                for b in form.damage_blocks:
                    if sum(getattr(b, f) is not None for f in _AD_FIELDS) > 1:
                        ad_double.append((cid, key, b.attribute))
                    if sum(getattr(b, f) is not None for f in _HP_FIELDS) > 1:
                        hp_double.append((cid, key, b.attribute))
    assert not ad_double, f"AD double-count blocks: {ad_double[:10]}"
    assert not hp_double, f"HP double-count blocks: {hp_double[:10]}"


def test_block_count_invariant_flag_on():
    """Re-sourcing never adds or drops a damage block."""
    _require_live_sidecar()
    off, on = _live_pair()
    bad = []
    for cid in off.champion_ids():
        for key in _KEYS:
            fo = off.get_abilities(cid).get(key, ())
            fn = on.get_abilities(cid).get(key, ())
            assert len(fo) == len(fn)
            for a, b in zip(fo, fn):
                if len(a.damage_blocks) != len(b.damage_blocks):
                    bad.append((cid, key))
    assert not bad, f"block-count changed: {bad[:10]}"


@pytest.mark.parametrize("cid,key", [("Ambessa", "Q"), ("Gwen", "R"), ("Udyr", "R")])
def test_known_ambiguous_multiblock_falls_back(cid, key):
    """The three known structural-failure abilities fall back to Meraki verbatim.

    Each has a Meraki<->CDragon block cardinality / signature mismatch the matcher
    cannot disambiguate, so the whole form must keep the Meraki ratios unchanged.
    """
    _require_live_sidecar()
    off, on = _live_pair()
    a = off.get_ability(cid, key, 0)
    b = on.get_ability(cid, key, 0)
    assert a.damage_blocks == b.damage_blocks


_PATCH = "98.8.8"


def _write(root: Path, meraki_blocks: list, cd_blocks: list) -> None:
    (root / "current.txt").write_text(_PATCH, encoding="utf-8")
    pd = root / _PATCH
    pd.mkdir(parents=True, exist_ok=True)
    meraki_doc = {
        "version": _PATCH, "fetched_at": "t", "source": "t",
        "data": {"Test": {"Q": [{
            "key": "Q", "name": "n", "form_index": 0,
            "damage_type": "MAGIC", "parse_status": "ok",
            "damage_blocks": meraki_blocks,
        }]}},
    }
    cd_doc = {"patch": _PATCH, "generated_note": "t",
              "champions": {"Test": {"Q": cd_blocks}}}
    (pd / "champion_abilities.json").write_text(json.dumps(meraki_doc), encoding="utf-8")
    (pd / "cdragon_ability_ratios.json").write_text(json.dumps(cd_doc), encoding="utf-8")


def _load_on(root: Path):
    return AbilitiesSnapshot.load(
        patch=_PATCH, data_root=root, prefer_cdragon_ratios=True
    )


def test_multiblock_distinct_signature_pairs_and_routes(tmp_path: Path) -> None:
    # Meraki: blkAP {base, ap}, blkAD {base, bonus_ad}. CDragon: c_ap {base, ap},
    # c_ad {base, total_ad}. Distinct signatures -> clean bijection. CDragon
    # total_ad must ROUTE onto Meraki bonus_ad (no second AD field appears).
    meraki = [
        {"attribute": "AP", "attribute_kind": "damage",
         "base": [1, 2, 3, 4, 5], "ap_pct": [10, 10, 10, 10, 10]},
        {"attribute": "AD", "attribute_kind": "damage",
         "base": [5, 6, 7, 8, 9], "bonus_ad_pct": [30, 30, 30, 30, 30]},
    ]
    cd = [
        {"name": "c_ap", "resolution": "mechanical",
         "base": [11, 12, 13, 14, 15], "ap_pct": [20, 20, 20, 20, 20]},
        {"name": "c_ad", "resolution": "mechanical",
         "base": [50, 60, 70, 80, 90], "total_ad_pct": [60, 60, 60, 60, 60]},
    ]
    _write(tmp_path, meraki, cd)
    form = _load_on(tmp_path).get_ability("Test", "Q", 0)
    b_ap, b_ad = form.damage_blocks
    assert b_ap.base == (11, 12, 13, 14, 15)
    assert b_ap.ap_pct == (20, 20, 20, 20, 20)
    assert b_ad.base == (50, 60, 70, 80, 90)
    assert b_ad.bonus_ad_pct == (60, 60, 60, 60, 60)  # routed onto existing family
    assert b_ad.total_ad_pct is None  # no second AD field -> no double-count


def test_cardinality_mismatch_falls_back(tmp_path: Path) -> None:
    # 1 Meraki damage block, 2 CDragon mechanical blocks -> ambiguous -> Meraki kept.
    meraki = [
        {"attribute": "D", "attribute_kind": "damage",
         "base": [1, 2, 3, 4, 5], "ap_pct": [10, 10, 10, 10, 10]},
    ]
    cd = [
        {"name": "a", "resolution": "mechanical",
         "base": [9, 9, 9, 9, 9], "ap_pct": [99, 99, 99, 99, 99]},
        {"name": "b", "resolution": "mechanical",
         "base": [8, 8, 8, 8, 8], "ap_pct": [88, 88, 88, 88, 88]},
    ]
    _write(tmp_path, meraki, cd)
    form = _load_on(tmp_path).get_ability("Test", "Q", 0)
    b = form.damage_blocks[0]
    assert b.base == (1, 2, 3, 4, 5)
    assert b.ap_pct == (10, 10, 10, 10, 10)
