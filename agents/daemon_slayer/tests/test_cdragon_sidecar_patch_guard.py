# arch: CDragon ratio-sidecar payload-patch guard (stale-copy detector) | section=ds-tests | frozen=no
"""The CDragon ratio sidecar must not be trusted purely because of its DIRECTORY.

``_load_cdragon_ratio_sidecar`` resolved the sidecar as
``<root>/<patch>/cdragon_ability_ratios.json`` and never read the payload's own
``patch`` field. A patch-refresh commit that copies the previous patch's sidecar
forward verbatim therefore silently RE-ARMS stale ratios as authoritative over
the Meraki snapshot, with no signal anywhere.

That was not hypothetical: ``cdragon_ability_ratios.json`` was byte-identical
across the 16.11.1 / 16.12.1 / 16.13.1 / 16.14.1 directories and every copy
carried ``"patch": "16.11.1"`` internally, while ``current.txt`` was 16.14.1.
The 16.14 re-extract repaired the CURRENT directory only - the three older
directories are still byte-identical 16.11.1 copies - so the guard stays load
bearing against the next copy-forward.

These tests pin the guard:

* the mismatch is DETECTED and logged loudly on every load (no silent re-arm),
* ``strict_cdragon_patch=True`` DROPS the stale sidecar and falls back to Meraki,
* ``strict_cdragon_patch=False`` reproduces the pre-guard apply-anyway behavior,
* the ``cdragon_root`` override seam is validated the same way.

The enforcement default flipped to True alongside the 16.14 re-extract. Both
enforcement outcomes are pinned with the flag passed EXPLICITLY so neither can
be turned into a tautology by a future default flip; exactly one test
(``test_default_is_strict_stale_sidecar_dropped``) reads the default on
purpose, and it is the characterization of WHICH default ships.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    cdragon_sidecar_patch,
)

_PATCH = "99.9.9"
_STALE = "99.6.6"

_MERAKI_AP = [50.0, 55.0, 60.0, 65.0, 70.0]
_CD_AP = [75.0, 80.0, 85.0, 90.0, 95.0]


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
                                "base": [10.0, 20.0, 30.0, 40.0, 50.0],
                                "ap_pct": list(_MERAKI_AP),
                            }
                        ],
                    }
                ]
            }
        },
    }


def _cdragon_doc(payload_patch: str | None) -> dict:
    doc: dict = {
        "generated_note": "test",
        "champions": {
            "Lux": {
                "Q": [
                    {
                        "name": "QDamage",
                        "ap_pct": list(_CD_AP),
                        "resolution": "mechanical",
                        "calc_type": "GameCalculation",
                    }
                ]
            }
        },
    }
    if payload_patch is not None:
        doc["patch"] = payload_patch
    return doc


def _write(root: Path, payload_patch: str | None, *, cd_root: Path | None = None) -> None:
    (root / "current.txt").write_text(_PATCH, encoding="utf-8")
    pd = root / _PATCH
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "champion_abilities.json").write_text(json.dumps(_meraki_doc()), encoding="utf-8")
    sidecar_dir = (cd_root or root) / _PATCH
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / "cdragon_ability_ratios.json").write_text(
        json.dumps(_cdragon_doc(payload_patch)), encoding="utf-8"
    )


def _lux_q_ap(snap: AbilitiesSnapshot) -> tuple:
    form = snap.get_ability("Lux", "Q", 0)
    dmg = form.damage_blocks_only()
    assert dmg, "expected one Lux Q damage block"
    return dmg[0].ap_pct


# --- detector -------------------------------------------------------------


def test_sidecar_patch_reports_payload_field(tmp_path: Path) -> None:
    # The detector reads the payload's OWN patch, not the directory it sits in.
    _write(tmp_path, _STALE)
    assert cdragon_sidecar_patch(tmp_path, _PATCH) == _STALE


def test_sidecar_patch_none_when_absent(tmp_path: Path) -> None:
    (tmp_path / _PATCH).mkdir(parents=True, exist_ok=True)
    assert cdragon_sidecar_patch(tmp_path, _PATCH) is None


# --- loud detection on load ----------------------------------------------


def test_stale_sidecar_logs_loudly(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # A copied-forward sidecar must never re-arm SILENTLY.
    _write(tmp_path, _STALE)
    with caplog.at_level(logging.WARNING, logger="agents.daemon_slayer.abilities"):
        AbilitiesSnapshot.load(patch=_PATCH, data_root=tmp_path)
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert msgs, "stale CDragon sidecar produced no warning"
    assert any(_STALE in m and _PATCH in m for m in msgs), msgs


def test_matching_patch_is_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write(tmp_path, _PATCH)
    with caplog.at_level(logging.WARNING, logger="agents.daemon_slayer.abilities"):
        snap = AbilitiesSnapshot.load(patch=_PATCH, data_root=tmp_path)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert _lux_q_ap(snap) == tuple(_CD_AP)


def test_missing_payload_patch_is_flagged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A sidecar with no ``patch`` key cannot be proven current -> treat as a mismatch.
    _write(tmp_path, None)
    with caplog.at_level(logging.WARNING, logger="agents.daemon_slayer.abilities"):
        AbilitiesSnapshot.load(patch=_PATCH, data_root=tmp_path)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# --- enforcement seam -----------------------------------------------------


def test_strict_drops_stale_sidecar(tmp_path: Path) -> None:
    _write(tmp_path, _STALE)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, strict_cdragon_patch=True
    )
    assert _lux_q_ap(snap) == tuple(_MERAKI_AP)


def test_strict_keeps_matching_sidecar(tmp_path: Path) -> None:
    _write(tmp_path, _PATCH)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, strict_cdragon_patch=True
    )
    assert _lux_q_ap(snap) == tuple(_CD_AP)


def test_strict_drops_sidecar_missing_patch(tmp_path: Path) -> None:
    _write(tmp_path, None)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, strict_cdragon_patch=True
    )
    assert _lux_q_ap(snap) == tuple(_MERAKI_AP)


def test_default_is_strict_stale_sidecar_dropped(tmp_path: Path) -> None:
    # Flipped with the 16.14 re-extract: a sidecar whose payload patch does not
    # match its directory is DROPPED by default and Meraki stays authoritative.
    # On the shipped 16.14.1 data this is a no-op (payload patch == directory);
    # it only bites if a future patch-refresh copies a sidecar forward again.
    _write(tmp_path, _STALE)
    snap = AbilitiesSnapshot.load(patch=_PATCH, data_root=tmp_path)
    assert _lux_q_ap(snap) == tuple(_MERAKI_AP)


def test_non_strict_opt_out_still_applies_stale(tmp_path: Path) -> None:
    # The pre-guard behavior remains reachable for tests that need to reproduce
    # it; only the DEFAULT moved.
    _write(tmp_path, _STALE)
    snap = AbilitiesSnapshot.load(
        patch=_PATCH, data_root=tmp_path, strict_cdragon_patch=False
    )
    assert _lux_q_ap(snap) == tuple(_CD_AP)


# --- sibling: the cdragon_root override seam ------------------------------


def test_cdragon_root_override_is_validated(tmp_path: Path) -> None:
    # The override seam resolves a DIFFERENT root; it must be patch-checked too.
    cd_root = tmp_path / "cd"
    _write(tmp_path, _STALE, cd_root=cd_root)
    assert cdragon_sidecar_patch(cd_root, _PATCH) == _STALE
    snap = AbilitiesSnapshot.load(
        patch=_PATCH,
        data_root=tmp_path,
        cdragon_root=cd_root,
        strict_cdragon_patch=True,
    )
    assert _lux_q_ap(snap) == tuple(_MERAKI_AP)
