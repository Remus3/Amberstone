"""Consumer tests: core.build_order._select_boots OFF parity + ON re-rank + plan threading."""
from __future__ import annotations

from core.build_order import _DEFAULT_BOOTS_BY_ARCHETYPE, _select_boots, plan_build_order


def test_off_is_byte_identical_marksman_lockdown():
    # OFF: DPS-axis champ is hard-pinned to Berserker's regardless of comp.
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="SR",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=False)
    assert iid == "3006"


def test_off_parity_grid_unchanged():
    # Pin the current heuristic outputs (OFF path) for a representative grid.
    cases = [
        (("marksman", 0.0, 0.0, "SR"), "3006"),
        (("mage", 0.0, 0.0, "SR"), "3020"),
        (("tank", 0.0, 0.0, "SR"), "3047"),
        (("assassin", 0.0, 0.0, "SR"), "3158"),
        (("carry", 0.0, 70.0, "SR"), "3006"),    # carry IS dps-axis -> Mercury's rule skipped
        (("bruiser", 0.0, 70.0, "SR"), "3111"),   # not dps-axis + mr>=60 -> Mercury's
        (("mage", 120.0, 0.0, "SR"), "3020"),     # caster exempt from Steelcaps
        (("tank", 120.0, 0.0, "SR"), "3047"),     # not caster + armor>=100 -> Steelcaps
    ]
    for (arch, armor, mr, mode), expected in cases:
        iid, _ = _select_boots(arch, armor, mr, mode=mode, assume_boot_utility=False)
        assert iid == expected, (arch, armor, mr, iid)


def test_on_neutral_comp_matches_off_default_all_archetypes():
    # Prior-alignment invariant: with a neutral comp the ON path must reproduce
    # the OFF archetype default for EVERY archetype (no gratuitous flips).
    for arch in _DEFAULT_BOOTS_BY_ARCHETYPE:
        off, _ = _select_boots(arch, 0.0, 0.0, mode="SR", assume_boot_utility=False)
        on, _ = _select_boots(arch, 0.0, 0.0, mode="SR",
                              enemy_ad_share=0.5, enemy_ap_share=0.5,
                              assume_boot_utility=True)
        assert on == off, (arch, off, on)


def test_on_marksman_lockdown_flips_to_mercurys():
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="SR",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=True)
    assert iid == "3111"


def test_on_arena_mirror_applied():
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="CHERRY",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=True)
    assert iid == "223111"


# --- Task 3: plan_build_order threading (stub ranker; boots injected separately) ---

def _stub_rank_fn(champion, archetype, **kwargs):
    # Real rank_fn contract: positional (champion, archetype) + kwargs, returns
    # {"scorer", "ranked": [rows]}. One damage row is enough - boots are injected
    # separately by _select_boots at slot 2.
    return {"scorer": "dps", "ranked": [
        {"item_id": "3031", "item_name": "Infinity Edge", "delta": 100.0,
         "gold": 3450, "unique_passive_key": "", "dead_unique_key": "",
         "shares_dead_unique": False},
    ]}


def _boot_of(res):
    return next((s.item_id for s in res.order if s.item_id in {
        "3006", "3009", "3020", "3047", "3111", "3158"}), None)


def test_plan_build_order_off_keeps_default_boot():
    res = plan_build_order(
        "Kalista", "marksman", level=11, owned_item_ids=[], mode="SR",
        target_mr=70.0, rank_kwargs={"enemy_ad_share": 0.2, "enemy_ap_share": 0.8},
        rank_fn=_stub_rank_fn, assume_boot_utility=False,
    )
    assert _boot_of(res) == "3006"


def test_plan_build_order_on_flips_boot_for_comp():
    res = plan_build_order(
        "Kalista", "marksman", level=11, owned_item_ids=[], mode="SR",
        target_mr=70.0, rank_kwargs={"enemy_ad_share": 0.2, "enemy_ap_share": 0.8},
        rank_fn=_stub_rank_fn, assume_boot_utility=True,
    )
    assert _boot_of(res) == "3111"
