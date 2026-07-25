"""A-07 / RM-82 TERM 2 - passive (P) aura damage credit in the mage scorer.

RED-FIRST test module for the ``apply_passive_aura_damage`` seam.

Background (all three facts probed on disk before this file was authored):

* ``ability_dps.SPELL_KEYS`` is ``("Q","W","E","R")`` and the per-spell loop
  (``ability_dps.py`` ``for key in SPELL_KEYS``) never visits ``P``, so no P
  damage has ever reached ``compute_ability_dps`` / ``/rank-mage``.
* Only ONE champion (Aphelios) carries any P ``damage_blocks`` in
  ``data/daemon_slayer/16.14.1/champion_abilities.json``; the real P-damage
  lane is the hand-authored ``_PASSIVE_DAMAGE_OVERRIDES`` registry, whose only
  consumers are ``dps.py`` (AA cadence) and ``onhit_dps.py``.
* Mordekaiser had NO registry entry at all, so Darkness Rise - his signature
  and dominant damage source - was invisible to his own scorer.

Why a NEW flag name and not the existing ``apply_passive_damage``: the two are
NOT semantically identical. ``apply_passive_damage`` injects every one of the
registry's entries into the abilities snapshot regardless of cadence, and 25 of
the 32 are ``on_hit`` entries whose sustained DPS belongs on the AUTO-ATTACK
clock (``dps.py`` already routes those) - crediting them on the ability clock
here would double-count against ``compute_dps``. ``apply_passive_aura_damage``
credits ONLY the ``per_second`` sustained-aura cadence, whose authored
magnitude already IS a per-second rate.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    per_second_aura_entry,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAPSHOT = DataSnapshot.load()

# Acceptance-criterion params (the row's own, verbatim).
_ACC = {
    "level": 13,
    "mode": "SR",
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2400.0,
    "target_bonus_hp": 1200.0,
}
_ACC_ITEMS = ("3047",)  # Plated Steelcaps

# Champions the acceptance criterion names as REQUIRED byte-identical controls.
_CONTROL_CHAMPS = ("Ahri", "Annie", "Anivia")


def _total(champ: str, **kw) -> float:
    return compute_ability_dps(
        _SNAPSHOT, champion_id=champ, item_ids=_ACC_ITEMS, **_ACC, **kw
    ).total_ability_dps


# --- registry -------------------------------------------------------------


def test_mordekaiser_darkness_rise_is_registered():
    entry = _PASSIVE_DAMAGE_OVERRIDES.get(("Mordekaiser", "P", 0))
    assert entry is not None, "Mordekaiser P absent from _PASSIVE_DAMAGE_OVERRIDES"
    assert entry.cadence == "per_second"
    assert entry.damage_type == "MAGIC"
    assert entry.attribute == "Darkness Rise"


def test_darkness_rise_coefficients_match_the_16_14_1_feed():
    # Verbatim 16.14.1 champion_abilities.json Mordekaiser P effects text:
    # "5 (+ 30% AP) (+ 1% : 5% (based on level) of target's maximum health)
    #  magic damage every second".
    entry = _PASSIVE_DAMAGE_OVERRIDES[("Mordekaiser", "P", 0)]
    assert entry.ap_pct == 30.0
    assert entry.base[0] == pytest.approx(5.0)
    assert entry.base[-1] == pytest.approx(5.0)
    assert entry.target_max_hp_pct[0] == pytest.approx(1.0)
    assert entry.target_max_hp_pct[-1] == pytest.approx(5.0)


def test_per_second_aura_accessor_is_mordekaiser_only_today():
    assert per_second_aura_entry("Mordekaiser") is not None
    for champ in _CONTROL_CHAMPS + ("Ziggs", "Lux", "Darius", "Twitch"):
        assert per_second_aura_entry(champ) is None, champ
    assert per_second_aura_entry("") is None


# --- the seam -------------------------------------------------------------


def test_seam_off_is_byte_identical_for_mordekaiser():
    absent = _total("Mordekaiser")
    explicit_off = _total("Mordekaiser", apply_passive_aura_damage=False)
    assert explicit_off == absent


def test_seam_on_raises_mordekaiser_baseline():
    off = _total("Mordekaiser", apply_passive_aura_damage=False)
    on = _total("Mordekaiser", apply_passive_aura_damage=True)
    assert on > off, f"Darkness Rise credited nothing: off={off} on={on}"


def test_seam_on_appends_a_p_spell_row_with_per_second_cadence():
    res = compute_ability_dps(
        _SNAPSHOT, champion_id="Mordekaiser", item_ids=_ACC_ITEMS,
        apply_passive_aura_damage=True, **_ACC,
    )
    p_rows = [s for s in res.per_spell if s.key == "P"]
    assert len(p_rows) == 1
    row = p_rows[0]
    assert row.casts_per_sec == 1.0
    assert row.casts_per_sec_source == "per_second_aura"
    assert row.dps > 0.0
    assert row.dps == pytest.approx(row.post_mitigation_damage_per_cast)


def test_seam_off_appends_no_p_row():
    res = compute_ability_dps(
        _SNAPSHOT, champion_id="Mordekaiser", item_ids=_ACC_ITEMS, **_ACC,
    )
    assert [s for s in res.per_spell if s.key == "P"] == []


# --- blast radius by construction ----------------------------------------

_REGISTRY_P_CHAMPS = frozenset(
    k[0] for k in _PASSIVE_DAMAGE_OVERRIDES if k[1] == "P"
)


def _roster() -> tuple[str, ...]:
    return tuple(sorted(_SNAPSHOT.champions.keys()))


def test_blast_radius_only_registry_p_champions_can_move():
    """With the seam ON, every champion OUTSIDE the P-keyed registry set is
    byte-identical. Proven over the WHOLE roster, not a sample."""
    moved = []
    for champ in _roster():
        if champ in _REGISTRY_P_CHAMPS:
            continue
        try:
            off = _total(champ)
            on = _total(champ, apply_passive_aura_damage=True)
        except (KeyError, ValueError):
            continue
        if on != off:
            moved.append((champ, off, on))
    assert not moved, f"non-registry champions moved under the seam: {moved}"


@pytest.mark.parametrize("champ", _CONTROL_CHAMPS)
def test_acceptance_controls_are_byte_identical(champ):
    """Ahri / Annie / Anivia have no registry entry - the acceptance criterion
    says any movement here is a REFUTATION, not a pass."""
    assert _total(champ, apply_passive_aura_damage=True) == _total(champ)


# --- route passthrough (spy) ---------------------------------------------

server._CACHE.set(_SNAPSHOT)

_MAGE_ROUTE_BODY = {
    "champion": "Mordekaiser", "level": 13, "mode": "SR",
    "items": ["3047"],
    "target_armor": 100.0, "target_mr": 60.0,
    "target_max_hp": 2400.0, "target_bonus_hp": 1200.0,
    "top": 200,
}


@pytest.mark.parametrize(
    "body_extra, expected",
    [
        ({}, False),                                    # ABSENT -> default OFF
        ({"apply_passive_aura_damage": False}, False),  # explicit False
        ({"apply_passive_aura_damage": True}, True),    # explicit True
    ],
)
def test_route_rank_mage_forwards_the_kwarg(monkeypatch, body_extra, expected):
    """Spy the kwarg actually REACHING compute_ability_dps through the route.

    This is the proof-of-path the row demands: if crediting Darkness Rise moves
    zero ranks, a no-op must be shown to come from the new code path having RUN,
    not from the flag being silently dropped between the HTTP body and the
    scorer.
    """
    from agents.daemon_slayer import ability_dps as _ad

    seen: list[object] = []
    real = _ad.compute_ability_dps

    def _spy(*args, **kwargs):
        seen.append(kwargs.get("apply_passive_aura_damage", "ABSENT"))
        return real(*args, **kwargs)

    monkeypatch.setattr(_ad, "compute_ability_dps", _spy)
    out = server._route_rank_mage(dict(_MAGE_ROUTE_BODY, **body_extra))
    assert isinstance(out["ranked"], list) and out["ranked"]
    assert seen, "compute_ability_dps was never called through /rank-mage"
    assert set(seen) == {expected}, f"kwarg seen at scorer: {set(seen)}"


def test_route_rank_mage_seam_changes_mordekaiser_baseline():
    off = server._route_rank_mage(dict(_MAGE_ROUTE_BODY))
    on = server._route_rank_mage(
        dict(_MAGE_ROUTE_BODY, apply_passive_aura_damage=True)
    )
    assert on["baseline_ability_dps"] > off["baseline_ability_dps"]
