"""SERVED-path twin of the raw-slot-count build-order index defect.

Commit 5f1b6d5c fixed this on the SHADOW path only (the ARAM deterministic
assembler's ``reset_item``) and deliberately left the served path alone.

The defect: ``dashboard/_liveclient.py`` builds ``owned_items`` /
``owned_item_ids`` from EVERY inventory slot - trinket, Health Potions,
Refillable included - so ``len(items)`` is a SLOT count, not build progress.
A curated build order is exactly 6 entries, so indexing it by the slot count
names the wrong item as soon as a potion is held and returns nothing at all
once six slots are used. Every player carries a trinket, so the served
next-item value was wrong or absent essentially always.

The served consumer is the recall callout ("Back now - afford X"), which
``core.event_callouts.next_callouts`` emits for SR only (_RECALL_MODES), so
the SERVED fixtures here are SR. The measured shape is the same one 5f1b6d5c
recorded on ARAM: Kalista's balanced order is
['3153', '3006', '3085', '3302', '6672', '3036'] in BOTH tables, so a player
holding 4 legendaries plus a trinket plus a Health Potion indexes at 6
(off the end -> None) where the honest index is 4 (Yun Tal Wildarrows).

Most assertions read the value the served callout generator actually receives
(a ``next_callouts`` spy) rather than the rendered callout list, because
``next_callouts`` caps its output at 3 rows and an active drake / level-spike
row can legitimately crowd the recall row out. One end-to-end test pins the
rendered line so the spy cannot drift from what a user sees.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard import _deterministic_coaching as dc  # noqa: E402

# Kalista's balanced order, in order. Ids and names both, because the helper
# matches on ids with a name fallback and both paths are exercised here.
_ORDER_IDS = ["3153", "3006", "3085", "3302", "3032", "3036"]
_ORDER_NAMES = [
    "Blade of The Ruined King",
    "Berserker's Greaves",
    "Runaan's Hurricane",
    "Terminus",
    "Yun Tal Wildarrows",
    "Lord Dominik's Regards",
]
_TRINKET_ID = "3363"        # Farsight Alteration
_TRINKET_NAME = "Farsight Alteration"
_POTION_ID = "2003"         # Health Potion
_POTION_NAME = "Health Potion"

# Yun Tal Wildarrows total gold, pinned so the fixture cannot drift silently.
# 16.15.1 reranked Kalista slot 5 from Kraken Slayer (6672) to Yun Tal (3032) -
# a DATA-driven flip (engine 1.268.0 unchanged; the CDragon ratio sidecar went
# from 838 to 858 mechanical blocks). Both cost 3000.
_NEXT_ITEM_COST = 3000


def _stub_laning(monkeypatch):
    """The DS matchup call is networked; the next-item index does not need it."""
    monkeypatch.setattr(dc, "laning_choices", lambda gs, mode="SR", **kw: [])


def _spy_next_callouts(monkeypatch) -> dict:
    """Capture the next-item name/cost the served callout generator receives."""
    real = dc.next_callouts
    seen: dict = {}

    def _spy(mode, gt, lvl, item_count, **kw):
        seen["item_count"] = item_count
        seen["next_item_name"] = kw.get("next_item_name")
        seen["next_item_cost"] = kw.get("next_item_cost")
        return real(mode, gt, lvl, item_count, **kw)

    monkeypatch.setattr(dc, "next_callouts", _spy)
    return seen


def _gs(n_build_items: int, *, ids: bool = True, gold: int = 6000) -> dict:
    """Kalista game_state holding ``n_build_items`` legendaries + trinket + potion."""
    owned_ids = [*_ORDER_IDS[:n_build_items], _TRINKET_ID, _POTION_ID]
    owned_names = [*_ORDER_NAMES[:n_build_items], _TRINKET_NAME, _POTION_NAME]
    gs = {
        "my_champion": "Kalista",
        "game_time_s": 1500.0,
        "level": 16,
        "items": owned_names,
        "gold": gold,
        "enemy_comp": [],
        "enemy_item_ids": [],
        "ally_item_ids": [],
    }
    if ids:
        gs["my_item_ids"] = owned_ids
    return gs


def _recall_lines(out: dict) -> list[str]:
    return [str(c.get("line") or "") for c in (out.get("callouts") or [])
            if c.get("kind") == "recall"]


# ---------------------------------------------------------------------------
# The primitive: characterization of the two indexes.
# ---------------------------------------------------------------------------

def test_raw_slot_count_over_indexes_and_correct_index_resolves():
    """Pins the exact before/after the served fix turns on.

    6 = the raw slot count (4 legendaries + trinket + potion) -> off the end of
    a 6-entry order -> None. 4 = the honest build progress -> Yun Tal Wildarrows.
    """
    assert dc._next_build_item("Kalista", "sr", 6) is None
    resolved = dc._next_build_item("Kalista", "sr", 4)
    assert resolved is not None
    assert resolved[0] == "Yun Tal Wildarrows"
    assert resolved[1] == _NEXT_ITEM_COST


def test_owned_build_item_count_ignores_trinket_and_potion():
    gs = _gs(4)
    assert dc._owned_build_item_count(
        "Kalista", "sr", gs["my_item_ids"], gs["items"]) == 4


# ---------------------------------------------------------------------------
# The served path.
# ---------------------------------------------------------------------------

def test_served_next_item_survives_trinket_and_potions(monkeypatch):
    """RED before the fix: 6 slots ran off the end and served no next item."""
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    dc._compute_uncached(_gs(4), "sr")
    assert seen["next_item_name"] == "Yun Tal Wildarrows"
    assert seen["next_item_cost"] == _NEXT_ITEM_COST
    # The count reaching next_callouts is the item-spike axis, a separate
    # question with its own primitive (see test_item_spike_legendary_count.py).
    # 3, not 6: the 4 held order items include Berserker's Greaves, and boots are
    # not a power spike.
    assert seen["item_count"] == 3


def test_served_recall_line_names_the_right_item(monkeypatch):
    """End-to-end: the rendered callout a user reads names the right item.

    Held at 5 order items (4 legendaries + boots) rather than 4 because of the
    max_n=3 cap this module's docstring already flags. Correcting the item-spike
    count restored the ACTIVE spike rows that the inflated slot count had been
    deleting, and at 3 legendaries that row ties with the drake + lvl-16 rows and
    fills the third slot. Above the 3-item spike no spike row exists, so the
    recall row renders and the assertion still pins a NAME."""
    _stub_laning(monkeypatch)
    out = dc._compute_uncached(_gs(5), "sr")
    lines = _recall_lines(out)
    assert lines, "no served recall callout - the next item resolved to None"
    assert any("Lord Dominik's Regards" in ln for ln in lines), lines


def test_served_next_item_uses_name_fallback_when_ids_absent(monkeypatch):
    """A coach payload can carry item NAMES only; the index must still land."""
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    dc._compute_uncached(_gs(4, ids=False), "sr")
    assert seen["next_item_name"] == "Yun Tal Wildarrows"


def test_served_next_item_does_not_skip_an_unowned_item(monkeypatch):
    """At 3 legendaries the pre-fix index (5 slots) pointed at Lord Dominik's
    while Terminus was still unbought; the corrected index must not skip."""
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    dc._compute_uncached(_gs(3), "sr")
    assert seen["next_item_name"] == "Terminus"


def test_served_recall_still_withheld_when_gold_short(monkeypatch):
    """Resolving the right item must not turn the callout into an always-on row -
    it is still an affordability directive."""
    _stub_laning(monkeypatch)
    out = dc._compute_uncached(_gs(4, gold=10), "sr")
    assert _recall_lines(out) == []


# ---------------------------------------------------------------------------
# Edge cases that must stay sane (no raise, no bogus item).
# ---------------------------------------------------------------------------

def test_empty_inventory_points_at_the_first_item(monkeypatch):
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    gs = _gs(0)
    gs["items"] = []
    gs["my_item_ids"] = []
    dc._compute_uncached(gs, "sr")
    assert seen["next_item_name"] == "Blade of The Ruined King"
    assert seen["item_count"] == 0


def test_trinket_and_potion_only_still_points_at_the_first_item(monkeypatch):
    """The pre-fix index read 2 slots as 2 completed items and served the THIRD
    order entry to a player who had bought nothing."""
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    dc._compute_uncached(_gs(0), "sr")
    assert seen["next_item_name"] == "Blade of The Ruined King"


def test_complete_six_item_build_serves_no_next_item(monkeypatch):
    """Nothing left to buy -> no next item -> no recall callout, and no raise.

    Emitting some other item-free line here would be a behaviour ADDITION and
    is deliberately out of scope."""
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    out = dc._compute_uncached(_gs(6), "sr")
    assert seen["next_item_name"] is None
    assert seen["next_item_cost"] is None
    assert _recall_lines(out) == []
    assert isinstance(out.get("callouts"), list)


def test_champion_with_no_build_order_row_is_fail_soft(monkeypatch):
    _stub_laning(monkeypatch)
    seen = _spy_next_callouts(monkeypatch)
    gs = _gs(4)
    gs["my_champion"] = "NotAChampionZZZ"
    out = dc._compute_uncached(gs, "sr")
    assert seen["next_item_name"] is None
    assert set(out) == {"choices", "callouts", "lead_projection"}
    assert _recall_lines(out) == []


def test_missing_champion_and_items_is_fail_soft(monkeypatch):
    _stub_laning(monkeypatch)
    out = dc._compute_uncached(
        {"game_time_s": 60.0, "level": 2, "gold": 500}, "sr")
    assert set(out) == {"choices", "callouts", "lead_projection"}
    assert _recall_lines(out) == []


def test_aram_served_path_does_not_raise(monkeypatch):
    """ARAM has no recall callout (_RECALL_MODES is SR-only), so the ARAM served
    next-item value is computed and discarded - but the new index call runs on
    every ARAM tick and must stay fail-soft."""
    _stub_laning(monkeypatch)
    out = dc._compute_uncached(_gs(4), "aram")
    assert set(out) == {"choices", "callouts", "lead_projection"}
    assert _recall_lines(out) == []


# ---------------------------------------------------------------------------
# Sibling site: the HZ choice shadow logger indexed the same order by
# _completed_item_count(lc), which is the same raw slot count.
# ---------------------------------------------------------------------------

def test_shadow_choice_logger_passes_build_progress_next_item(tmp_path, monkeypatch):
    import core.precomputed_laning_coach as plc

    seen: dict = {}

    def _spy(champ, enemy, level, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(plc, "resolve_enemy",
                        lambda champ, comp, mode, payload=None: "Darius")
    monkeypatch.setattr(plc, "precomputed_choices", _spy)

    coach = {"champion": "Kalista", "level": 16, "game_time_s": 1500.0}
    lc = {
        "champion": "Kalista",
        "enemy_team": ["Darius"],
        "owned_items": [*_ORDER_NAMES[:4], _TRINKET_NAME, _POTION_NAME],
        "owned_item_ids": [*_ORDER_IDS[:4], _TRINKET_ID, _POTION_ID],
    }
    dc.shadow_log_precomputed_choices(
        coach, lc, "sr", path=tmp_path / "choice.jsonl")

    assert seen, "precomputed_choices was never reached"
    assert seen["next_item"] is not None, "next_item fell off the end of the order"
    assert seen["next_item"][0] == "Yun Tal Wildarrows"
    # The recorded item_count axis stays the raw slot count - it is the
    # item_state lookup axis the seed table was generated against, not a
    # build-progress pointer.
    assert seen["item_count"] == 6
