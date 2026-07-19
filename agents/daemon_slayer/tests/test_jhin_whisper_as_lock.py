"""RED-first regression for Jhin's Whisper passive: AS-lock + AS/crit -> AD.

Grounded 2026-07-12 against data/daemon_slayer/16.13.1 (patch 16.13.1):
  - Jhin base AD = 61 (level 1), AS = 0.625, attackspeedperlevel = 0.
  - Whisper: attack speed is LOCKED (cannot rise from items); Jhin instead
    gains bonus AD = (level% + 0.30 per 1% bonus AS + 0.35 per 1% crit) of his
    BASE attack damage.
  - Wiki raw (Template:Data_Jhin/Whisper?action=raw, re-verified 2026-07-12):
    level% table 4;5;6;7;8;9;10;11;12;14;16;20;24;28;32;36;40;44 ;
    "0.3% per 1% bonus attack speed" ; "0.35% per 1% critical strike chance" ;
    "attack speed cannot increase except by leveling up".

Control champions MUST stay byte-identical - the override is an explicit
per-champion dict, NEVER an automatic attackspeedperlevel==0 rule:
  - Jinx (0.625 / asperlvl 1): AS still scales with an AS item.
  - KogMaw (0.665 / asperlvl 2.65): AS still scales.
  - Belveth (0.85 / asperlvl 0): SAME zero-AS-growth signature as Jhin but
    UNCAPPED AS scaling - proves perlevel==0 is not the trigger.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion

_SNAP = DataSnapshot.load()

# Pure single-stat items (verified via aggregate_item_stats on 16.13.1):
_DAGGER = "1042"       # pure attack speed 0.10 (no crit, no AD)
_CLOAK = "1018"        # pure crit 0.15 (no AS, no AD)
_RUNAANS = "3085"      # 0.40 AS + 0.25 crit (AS component wasted; crit kept)


def _jhin(level, items=()):
    return build_champion(_SNAP, "Jhin", level, list(items), "SR")


# ---- Part A: AS-lock ------------------------------------------------------

def test_jhin_as_locked_with_as_items():
    naked = _jhin(18, [])
    with_runaans = _jhin(18, [_RUNAANS])
    with_dagger = _jhin(18, [_DAGGER])
    # Naked AS is the flat base 0.625 (attackspeedperlevel == 0).
    assert naked.stats["as"] == pytest.approx(0.625, abs=1e-6)
    # AS never rises from item attack speed - it stays locked at naked value.
    assert with_runaans.stats["as"] == pytest.approx(naked.stats["as"], abs=1e-6)
    assert with_dagger.stats["as"] == pytest.approx(0.625, abs=1e-6)


# ---- Part A: bonus AS -> AD (base-AD % conversion) ------------------------

def test_jhin_bonus_as_converts_to_ad():
    # Dagger = pure 10% AS. The ONLY AD delta vs naked is the AS->AD conversion
    # 0.30 * 0.10 * base_ad (base_ad = 61 at level 1).
    naked = _jhin(1, [])
    with_dagger = _jhin(1, [_DAGGER])
    base_ad = naked.base_stats["ad"]
    expected = 0.30 * 0.10 * base_ad
    assert with_dagger.stats["ad"] - naked.stats["ad"] == pytest.approx(expected, abs=1e-6)


# ---- Part A: crit -> AD, crit chance preserved ----------------------------

def test_jhin_crit_converts_to_ad_and_crit_preserved():
    # Cloak of Agility = pure 15% crit. AD delta = 0.35 * 0.15 * base_ad and the
    # crit chance is NOT consumed (still there for crit damage - no double count).
    naked = _jhin(1, [])
    with_cloak = _jhin(1, [_CLOAK])
    base_ad = naked.base_stats["ad"]
    expected = 0.35 * 0.15 * base_ad
    assert with_cloak.stats["ad"] - naked.stats["ad"] == pytest.approx(expected, abs=1e-6)
    assert with_cloak.stats["crit"] == pytest.approx(0.15, abs=1e-6)


# ---- Part A: innate level AD present even naked ----------------------------

def test_jhin_innate_level_ad_present_even_naked():
    # Whisper's level% is innate: naked Jhin already gains level% of base AD
    # (4% at level 1, 44% at level 18).
    naked1 = _jhin(1, [])
    naked18 = _jhin(18, [])
    assert naked1.stats["ad"] == pytest.approx(naked1.base_stats["ad"] * 1.04, abs=1e-6)
    assert naked18.stats["ad"] == pytest.approx(naked18.base_stats["ad"] * 1.44, abs=1e-6)


# ---- Part A: registry is Jhin-only ----------------------------------------

def test_as_lock_entry_is_jhin_only():
    from agents.daemon_slayer._passive_as_lock_overrides import as_lock_entry
    assert as_lock_entry("Jhin") is not None
    for other in ("Jinx", "KogMaw", "Belveth", "Caitlyn", "Aatrox"):
        assert as_lock_entry(other) is None


# ---- Part A integration: the lock propagates to the DPS scorer -------------

def _dps_delta(champ, item_id):
    from agents.daemon_slayer.dps import compute_dps
    base = compute_dps(
        _SNAP, champ, level=18, mode="SR", target_armor=80.0, item_ids=[],
    ).weighted_dps
    withi = compute_dps(
        _SNAP, champ, level=18, mode="SR", target_armor=80.0, item_ids=[item_id],
    ).weighted_dps
    return withi - base


def test_jhin_pure_as_item_dps_gain_is_suppressed():
    # The lock reaches the DPS scorer that rank/beam use: a pure attack-speed
    # item (Dagger) gains Jhin far LESS DPS than it gains a normal marksman
    # (Caitlyn) - Jhin's only gain is the small AS->AD conversion, not attack
    # rate. And a pure-CRIT item (which Jhin DOES convert well) out-gains the
    # pure-AS item for Jhin. NOTE: this is why Runaan's Hurricane (AS + 25% crit
    # + multi-target bolts) legitimately stays a strong Jhin item post-fix - only
    # its raw attack speed is neutralized, not its crit / bolts.
    assert _dps_delta("Jhin", _DAGGER) < _dps_delta("Caitlyn", _DAGGER)
    assert _dps_delta("Jhin", _CLOAK) > _dps_delta("Jhin", _DAGGER)


# ---- Part B: boots override -----------------------------------------------

def test_jhin_select_boots_swiftness():
    from core.build_order import _select_boots
    assert _select_boots("marksman", 0.0, 0.0, mode="SR", champion="Jhin") == (
        "3009", "Boots of Swiftness",
    )


def _dps_rank_fn(champion, archetype, **kw):
    """In-process mirror of ``rank_for_primary_archetype``'s default route.

    ``plan_build_order``'s stock ``rank_fn`` is the HTTP client for the local
    :8893 engine, so leaving it unset makes this test require a live server:
    it passes on a dev box that happens to be running one and returns None
    (engine unreachable at engine call 1) everywhere else. CI can never
    satisfy it - ``ensure_running`` spawns with Windows-only ``creationflags``
    and dies on the Linux runner - which is why only the nightly full-suite
    job saw it. Injecting the scorer in-process is the same seam
    test_build_recommendation_p1l5.py and test_double_pen_mutex.py already
    use, and it exercises the genuine engine math rather than a stub.

    "marksman" matches no named branch of the real router, so it falls
    through to ``rank_items`` / scorer "dps"; this mirrors that branch and
    its response envelope.
    """
    from agents.daemon_slayer.rank import rank_items

    ranked = rank_items(
        _SNAP, champion,
        level=kw["level"],
        current_item_ids=kw.get("item_ids") or [],
        mode=kw.get("mode", "SR"),
        target_armor=kw.get("target_armor", 0.0),
        target_mr=kw.get("target_mr", 0.0),
        target_max_hp=kw.get("target_max_hp", 0.0),
        target_bonus_hp=kw.get("target_bonus_hp", 0.0),
        top_n=kw.get("top", 8),
        sort_by=kw.get("sort_by", "delta"),
        filter_shared_uniques=kw.get("filter_shared_uniques", True),
    ).ranked
    return {
        "ok": True,
        "scorer": "dps",
        "archetype": (archetype or "").strip().lower(),
        "fell_back": False,
        "ranked": [
            {
                "item_id": x.item_id,
                "item_name": x.item_name,
                "delta": x.delta_dps,
                "gold": x.gold,
                "shares_dead_unique": x.shares_dead_unique,
                "dead_unique_key": x.dead_unique_key,
                "unique_passive_key": x.unique_passive_key,
            }
            for x in ranked
        ],
    }


def test_jhin_plan_build_order_uses_swiftness_boots():
    from core.build_order import plan_build_order
    res = plan_build_order("Jhin", "marksman", level=18, owned_item_ids=[],
                           mode="SR", rank_fn=_dps_rank_fn)
    assert res is not None
    ids = [s.item_id for s in res.order]
    boots = next(
        (i for i in ids if i in {"3006", "3009", "3020", "3047", "3111", "3158"}),
        None,
    )
    assert boots == "3009"


# ---- Control champions: MUST stay byte-identical --------------------------

@pytest.mark.parametrize("champ", ["Jinx", "KogMaw", "Belveth"])
def test_control_as_still_scales_with_as_item(champ):
    # Belveth shares Jhin's attackspeedperlevel == 0 signature yet has UNCAPPED
    # AS scaling; the override must not touch it (explicit-dict, not auto-rule).
    naked = build_champion(_SNAP, champ, 11, [], "SR").stats["as"]
    with_as = build_champion(_SNAP, champ, 11, [_DAGGER], "SR").stats["as"]
    assert with_as > naked


def test_control_jinx_keeps_berserkers_boots():
    from core.build_order import _select_boots
    assert _select_boots("marksman", 0.0, 0.0, mode="SR", champion="Jinx")[0] == "3006"
