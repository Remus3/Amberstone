"""Slice B Task 1 (2026-07-16) - on-hit AP combined-DPS scorer test.

Exercises ``compute_onhit_dps``: the exact-sum invariant against the two
composed engine primitives (``compute_ability_dps`` + ``compute_dps``) on a
real on-hit AP build (Gwen: Nashor's Tooth + Rabadon's Deathcap). Mirrors
the shape of ``test_only_phase_hot01.py`` / ``test_ability_dps.py`` -
``DataSnapshot.load()`` is the real (non-mocked) snapshot loader idiom used
across the DS test suite; there is no ``load_default_snapshot()`` helper.
"""
from __future__ import annotations

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.onhit_dps import compute_onhit_dps

# Nashor's Tooth + Rabadon's - an on-hit AP build for Gwen.
_GWEN_BUILD = ("3115", "3089")


def test_onhit_dps_is_exact_sum_of_two_halves():
    snap = DataSnapshot.load()
    res = compute_onhit_dps(
        snap, "Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    )
    ability = compute_ability_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).total_ability_dps
    auto = compute_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).weighted_dps
    assert res.ability_dps == ability
    assert res.auto_dps == auto
    assert res.onhit_dps == ability + auto
    # Both halves are material for an on-hit AP champ (the whole point).
    assert res.ability_dps > 0.0
    assert res.auto_dps > 0.0


# --- Slice B Task 2 (2026-07-16) - rank_items_by_onhit ranker tests --------
#
# NOTE: the task brief's Step-1 snippet calls a ``load_default_snapshot()``
# helper that does not exist anywhere in this repo (grepped clean). This
# module already established the fix directly above (Task 1's own docstring):
# ``DataSnapshot.load()`` is the real snapshot-loader idiom used across the DS
# test suite. A module-level singleton (mirrors
# ``test_hybrid_enemy_champions.py:55`` ``_SNAPSHOT = DataSnapshot.load()``)
# avoids re-reading the champions/items JSON from disk once per parametrized
# case.
import pytest

from agents.daemon_slayer.onhit_dps import rank_items_by_onhit

_NASHORS = "3115"
_RANK_SNAPSHOT = DataSnapshot.load()


# --- Slice B Task 5 (2026-07-16) - AP/AD axis-coherence gate ---------------
#
# Task 2's xfail (see git history) diagnosed the gap: neither compute_dps nor
# compute_ability_dps credited Gwen/Kayle/KogMaw's on-hit-AP kit mechanic
# (Gwen's Thousand Cuts was excluded from _AA_ROUTED_ON_HIT_KEYS; Kayle/KogMaw
# had no entry at all), so pure-AD on-hit items (Blade of the Ruined King,
# Trinity Force) swamped Nashor's in the ranked top-8 for all three. Tasks 3+4
# fixed the credit gap (Gwen P, Kayle E, KogMaw W now route onto the
# auto-attack cadence via apply_passive_damage=True). That closed most but not
# all of the gap: raw AD items still add marginal DPS the ranker cannot see is
# wasted on an AP champion's kit scaling. ap_ad_coherence penalizes a pure-AD
# candidate's SORT score (not its raw delta_dps - transparency preserved) for
# an AP-axis champion, so the AP on-hit field (Nashor's) surfaces without
# deleting the AD candidates from the result. The mechanism was validated by
# restricting Gwen's pool to AP-tagged items only, which surfaced Nashor's at
# #5 - these per-champ strengths reproduce that with a coherence knob instead
# of a pool restriction. strict xfail is gone: this is a real green assertion
# now, not a placeholder.
@pytest.mark.parametrize("champ,coh", [("Gwen", 1.0), ("Kayle", 0.3), ("KogMaw", 0.6)])
def test_nashors_surfaces_with_coherence(champ, coh):
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    res = rank_items_by_onhit(snap, champ, 13, current_item_ids=(), mode="SR",
                              apply_passive_damage=True, ap_ad_coherence=coh,
                              top_n=8, **T)
    ids = [r.item_id for r in res.ranked]
    assert _NASHORS in ids, f"{champ}: Nashor's absent from onhit top-8: {ids}"


def test_coherence_off_is_byte_identical():
    """The OFF path must be provably byte-identical, not merely plausible.

    Ranks once with ``ap_ad_coherence`` OMITTED and once with an explicit 0.0,
    then compares the FULL ordered row list as (item_id, delta_dps) pairs, so a
    silent reordering OR a delta change is caught. Mirrors the real default-off
    pattern at ``test_cost_aware_top_f2.py:60-62``.

    Before 2026-07-18 this test asserted only that one item was present after a
    single ranking call. It never built a second ranking, so it would have
    stayed green even if the 0.0 path had stopped being byte-identical.

    The final assertion gives the comparison TEETH. Gwen is AP-axis, so an
    active gate MUST reorder her ranking; without that check a byte-identity
    assertion can pass vacuously against a comparison that detects nothing.
    """
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)

    def _rows(**kw):
        res = rank_items_by_onhit(
            _RANK_SNAPSHOT, "Gwen", 13, current_item_ids=(), mode="SR",
            apply_passive_damage=True, top_n=12, **T, **kw
        )
        return [(r.item_id, r.delta_dps) for r in res.ranked]

    omitted = _rows()
    assert omitted == _rows(ap_ad_coherence=0.0), (
        "ap_ad_coherence=0.0 is not byte-identical to the omitted default"
    )

    # A pure-AD item (BotRK 3153) is NOT gated when coherence is off.
    assert "3153" in [item_id for item_id, _ in omitted]

    assert _rows(ap_ad_coherence=1.0) != omitted, (
        "comparison is insensitive - it would not catch a broken OFF path"
    )


def test_onhit_ranked_row_splits_are_consistent():
    res = rank_items_by_onhit(
        _RANK_SNAPSHOT, "Gwen", level=13, current_item_ids=(), mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0, top_n=8,
    )
    r = res.ranked[0]
    # new_dps == ability_dps + auto_dps for each row (the sum invariant holds per candidate).
    assert abs(r.new_dps - (r.ability_dps + r.auto_dps)) < 1e-6


# --- Slice B Task 3 (2026-07-16) - Gwen P on-hit credit + apply_passive_damage
# threading ------------------------------------------------------------------
#
# compute_onhit_dps gains an apply_passive_damage param (default False,
# forwarded only into the composed compute_dps call - compute_ability_dps has
# no such param since it skips the P slot). Gwen ("Gwen", "P", 0) joins
# _AA_ROUTED_ON_HIT_KEYS so A Thousand Cuts' on-hit magic now routes onto the
# AUTO-ATTACK cadence when the flag is on, raising auto_dps (and therefore
# onhit_dps) relative to the flag-off baseline.
def test_gwen_p_credited_raises_auto_half_when_passive_on():
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    off = compute_onhit_dps(snap, "Gwen", 13, item_ids=("3115",), mode="SR",
                            apply_passive_damage=False, **T)
    on = compute_onhit_dps(snap, "Gwen", 13, item_ids=("3115",), mode="SR",
                           apply_passive_damage=True, **T)
    # Crediting Gwen P (now allowlisted) raises the auto half via on-hit magic.
    assert on.auto_dps > off.auto_dps
    assert on.onhit_dps > off.onhit_dps


# --- Slice B Task 4 (2026-07-16) - Kayle E + Kog'Maw W on-hit credit ---------
#
# Kayle E "Starfire Spellblade" passive (bonus magic on every basic attack) and
# Kog'Maw W "Bio-Arcane Barrage" (% target-max-HP bonus magic on-hit, toggle -
# uptime-discounted) join _AA_ROUTED_ON_HIT_KEYS at their REAL slots (E / W, not
# P). aa_routed_on_hit_entry now consults the champ's allowlisted slot (no longer
# P-hardcoded), so apply_passive_damage=True routes their on-hit magic onto the
# AUTO-ATTACK cadence, raising auto_dps (and therefore onhit_dps) over the flag-
# off baseline - so their attack-speed / on-hit itemization finally pays off.
@pytest.mark.parametrize("champ", ["Kayle", "KogMaw"])
def test_kit_onhit_credited_for_kayle_kog(champ):
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    off = compute_onhit_dps(snap, champ, 13, item_ids=("3115",), mode="SR",
                            apply_passive_damage=False, **T)
    on = compute_onhit_dps(snap, champ, 13, item_ids=("3115",), mode="SR",
                           apply_passive_damage=True, **T)
    assert on.auto_dps > off.auto_dps, f"{champ}: kit on-hit not credited"


# --- Slice B Task 6 (2026-07-16) - /rank-onhit server route ----------------
#
# Exposes rank_items_by_onhit over HTTP so later Slice-B tasks can wire the
# RC client + live-validate. Dispatch symbol is _POST_ROUTES (confirmed at
# server.py:2018), not the _ROUTES guess in the original task brief.
def test_rank_onhit_route_registered():
    from agents.daemon_slayer.server import _POST_ROUTES
    assert "/rank-onhit" in _POST_ROUTES


# --- Slice B Task 6 followup (2026-07-16) - invocation-level /rank-onhit
# route coverage --------------------------------------------------------
#
# test_rank_onhit_route_registered (above) only asserts dict membership; it
# never invokes the handler, so it cannot catch a mage-only kwarg leaking
# into rank_items_by_onhit (runtime TypeError) or apply_passive_damage /
# ap_ad_coherence being dropped between the HTTP body and the ranker call.
# In-process, no HTTP - same idiom as test_rank_route_seam_passthrough.py:
# server._CACHE.set(...) seeds the module-level snapshot holder the route
# reads (server.py:181-185 _SnapshotCache.get raises RuntimeError if
# unseeded; server.py:1160 _route_rank_onhit reads snap = _CACHE.get()).
from agents.daemon_slayer import server

server._CACHE.set(_RANK_SNAPSHOT)

_ONHIT_ROUTE_BODY = {
    "champion": "Gwen", "level": 13, "mode": "SR",
    "target_armor": 105.0, "target_mr": 52.0, "target_max_hp": 2430.0,
}


def test_route_rank_onhit_invocation_returns_ranked_list():
    out = server._route_rank_onhit(dict(_ONHIT_ROUTE_BODY))
    assert isinstance(out, dict)
    assert isinstance(out["ranked"], list)
    assert len(out["ranked"]) > 0


def test_route_rank_onhit_forwards_passive_damage_and_coherence():
    # Mirrors test_nashors_surfaces_with_coherence above, but through the
    # ROUTE (body -> _route_rank_onhit -> rank_items_by_onhit) - proves the
    # two Slice-B-only flags actually thread from an HTTP-shaped body, not
    # just at the ranker-function call site.
    body = dict(_ONHIT_ROUTE_BODY, apply_passive_damage=True, ap_ad_coherence=1.0)
    out = server._route_rank_onhit(body)
    ids = [row["item_id"] for row in out["ranked"]]
    assert _NASHORS in ids, f"Nashor's absent from routed onhit ranked list: {ids}"


def test_route_rank_onhit_ignores_stray_mage_only_keys():
    # max_priority / block_strategy are parsed by _route_rank_mage (and the
    # ability-dps/hybrid/tank routes) but _route_rank_onhit's own docstring
    # (server.py:1154-1158) says rank_items_by_onhit has no such params, so
    # they are never read off body. A body that carries them anyway (e.g. a
    # client reusing one options object across rank routes) must not raise -
    # this would fail if the route ever started blindly forwarding **body.
    body = dict(_ONHIT_ROUTE_BODY, max_priority="QWE", block_strategy="first")
    out = server._route_rank_onhit(body)
    assert isinstance(out, dict)
    assert "ranked" in out
