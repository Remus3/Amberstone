# arch: prefer-CDragon-mechanical-ratios load seam (default ON, item 320) | section=ds-tests | frozen=no
"""DS ability-ratio re-source: prefer mechanical CDragon blocks, fall back to Meraki.

The DS engine's per-ability damage ratios come from the FROZEN Meraki dump
(``data/daemon_slayer/<patch>/champion_abilities.json``). The
``tools/daemon_slayer_cdragon_ratio_extract.py`` sidecar
(``cdragon_ability_ratios.json``) re-sources those ratios from the LIVE
CommunityDragon character bins. ``AbilitiesSnapshot.load(prefer_cdragon_ratios=...)`` prefers the sidecar's
``resolution == "mechanical"`` blocks per-field and falls back to Meraki
everywhere else.

The flag now DEFAULTS ON (the cutover): a bare ``load()`` re-sources from the
CDragon sidecar. ``prefer_cdragon_ratios=False`` forces the legacy Meraki-only
path, and a missing / fallback sidecar is still a no-op (Meraki authoritative).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import AbilitiesSnapshot

_PATCH = "99.9.9"

# Meraki snapshot ratios (authoritative when the flag is OFF).
_MERAKI_AP = [50.0, 55.0, 60.0, 65.0, 70.0]
_MERAKI_BASE = [10.0, 20.0, 30.0, 40.0, 50.0]
# CDragon mechanical re-source (preferred when the flag is ON).
_CD_AP = [75.0, 80.0, 85.0, 90.0, 95.0]
_CD_BASE = [11.0, 22.0, 33.0, 44.0, 55.0]


def _meraki_doc() -> dict:
    return {
        "version": _PATCH,
        "fetched_at": "test",
        "source": "test",
        "data": {
            "Lux": {
                "Q": [
                    {
                        "key": "Q",
                        "name": "Light Binding",
                        "form_index": 0,
                        "damage_type": "MAGIC",
                        "parse_status": "ok",
                        "damage_blocks": [
                            {
                                "attribute": "Damage",
                                "attribute_kind": "damage",
                                "base": list(_MERAKI_BASE),
                                "ap_pct": list(_MERAKI_AP),
                            }
                        ],
                    }
                ]
            }
        },
    }


def _cdragon_doc(*, resolution: str = "mechanical", ap: bool = True) -> dict:
    block: dict = {
        "name": "QDamage",
        "base": list(_CD_BASE),
        "resolution": resolution,
        "calc_type": "GameCalculation",
    }
    if ap:
        block["ap_pct"] = list(_CD_AP)
    return {
        "patch": _PATCH,
        "generated_note": "test",
        "champions": {"Lux": {"Q": [block]}},
    }


def _write(root: Path, *, with_sidecar: bool, **cd_kwargs) -> None:
    (root / "current.txt").write_text(_PATCH, encoding="utf-8")
    pd = root / _PATCH
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "champion_abilities.json").write_text(json.dumps(_meraki_doc()), encoding="utf-8")
    if with_sidecar:
        (pd / "cdragon_ability_ratios.json").write_text(
            json.dumps(_cdragon_doc(**cd_kwargs)), encoding="utf-8"
        )


def _lux_q_block(snap: AbilitiesSnapshot):
    form = snap.get_ability("Lux", "Q", 0)
    dmg = form.damage_blocks_only()
    assert dmg, "expected one Lux Q damage block"
    return dmg[0]


def test_default_now_prefers_cdragon(tmp_path: Path) -> None:
    # The cutover flipped the default ON: a bare load() re-sources from CDragon.
    _write(tmp_path, with_sidecar=True)
    snap = AbilitiesSnapshot.load(patch=_PATCH, data_root=tmp_path)
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_CD_AP)
    assert b.base == tuple(_CD_BASE)


def test_explicit_off_uses_meraki(tmp_path: Path) -> None:
    # prefer_cdragon_ratios=False forces the legacy Meraki-only path.
    _write(tmp_path, with_sidecar=True)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=False
    )
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_MERAKI_AP)
    assert b.base == tuple(_MERAKI_BASE)


def test_flag_on_prefers_cdragon_mechanical(tmp_path: Path) -> None:
    _write(tmp_path, with_sidecar=True)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=True
    )
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_CD_AP)
    assert b.base == tuple(_CD_BASE)


def test_flag_on_missing_sidecar_falls_back(tmp_path: Path) -> None:
    _write(tmp_path, with_sidecar=False)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=True
    )
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_MERAKI_AP)
    assert b.base == tuple(_MERAKI_BASE)


def test_flag_on_fallback_block_keeps_meraki(tmp_path: Path) -> None:
    _write(tmp_path, with_sidecar=True, resolution="fallback")
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=True
    )
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_MERAKI_AP)
    assert b.base == tuple(_MERAKI_BASE)


def test_flag_on_per_field_fallback(tmp_path: Path) -> None:
    # CDragon resolved base but NOT ap_pct -> base re-sourced, ap_pct keeps Meraki.
    _write(tmp_path, with_sidecar=True, ap=False)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=True
    )
    b = _lux_q_block(snap)
    assert b.base == tuple(_CD_BASE)
    assert b.ap_pct == tuple(_MERAKI_AP)


def test_cdragon_root_override(tmp_path: Path) -> None:
    # Meraki under data_root; sidecar under a separate cdragon_root.
    (tmp_path / "current.txt").write_text(_PATCH, encoding="utf-8")
    pd = tmp_path / _PATCH
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "champion_abilities.json").write_text(json.dumps(_meraki_doc()), encoding="utf-8")
    cd_root = tmp_path / "cd"
    (cd_root / _PATCH).mkdir(parents=True, exist_ok=True)
    (cd_root / _PATCH / "cdragon_ability_ratios.json").write_text(
        json.dumps(_cdragon_doc()), encoding="utf-8"
    )
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, prefer_cdragon_ratios=True, cdragon_root=cd_root
    )
    b = _lux_q_block(snap)
    assert b.ap_pct == tuple(_CD_AP)
