"""Hermetic tests for the DSP10 consolidated mismatch report.

Synthesize a tiny CrossEval + ChampModeWin by hand (no real db, no engine) and assert
the consolidation surfaces an above-baseline winner DS buries, orders the worst champs
by mean_lift, and stays anchor-matched. feedback_clean_checkout_probe-safe.
"""
import json

from ops.audit.ds_perm_swarm import (
    ChampMismatch,
    ChampModeWin,
    PermConfig,
    champ_mismatch,
    consolidate,
)
from ops.audit.ds_perm_swarm.cross_eval_loader import cross_eval_from_dict
from ops.audit.ds_perm_swarm.win_anchor import ItemWinRate


def _ce(name, top_ids, emp_items, anchor="ARAM", scorer="burst", arch="assassin"):
    grid = [
        {"rank": i + 1, "id": iid, "name": f"Item{iid}", "score": 1.0 - i * 0.1,
         "d_ehp": 0.0, "d_dps": 0.0, "gold": 3000}
        for i, iid in enumerate(top_ids)
    ]
    return cross_eval_from_dict({
        "champion": name,
        "archetype": {"primary": arch, "source": "default"},
        "scorer": scorer,
        "anchor_mode": anchor,
        "comp_grid": {"ad_squishy": grid},
        "empirical": {anchor: {"all": {"n": 50, "wr": 50.0, "items": emp_items}}},
    })


def _cmw(name, mode, n, wins, items):
    return ChampModeWin(
        champion=name, mode=mode, n=n, wins=wins,
        baseline_wr=round(100.0 * wins / n, 4) if n else None,
        items={i.item_id: i for i in items},
    )


def test_champ_mismatch_surfaces_buried_winner():
    # DS ranks 3003 (#1, loses 30%); above-baseline winner 4444 (65%) is in the
    # empirical block but NOT in DS top-K -> must surface; component 5555 (n=3) gated out.
    ce = _ce("C", ["3003", "7777"], [
        {"id": "3003", "name": "Bad", "n": 20, "wr": 30.0},
        {"id": "4444", "name": "Buried", "n": 15, "wr": 65.0},
        {"id": "5555", "name": "Thin", "n": 3, "wr": 80.0},
    ])
    cmw = _cmw("C", "ARAM", 50, 25, [ItemWinRate("3003", 20, 6)])
    m = champ_mismatch(ce, cmw, PermConfig(min_item_n=5))
    assert isinstance(m, ChampMismatch)
    assert m.champion == "C" and m.mode == "ARAM" and m.scorer == "burst"
    assert m.mean_lift is not None and m.mean_lift < 0  # DS favors a loser
    buried_ids = {b.id for b in m.buried_winners}
    assert buried_ids == {"4444"}  # 3003 is favored, 5555 too thin
    bw = m.buried_winners[0]
    assert bw.wr == 65.0 and bw.lift_over_baseline == 15.0
    # DS-top carries the live rewind n/wr for favored items; 7777 has none
    top = {v.id: v for v in m.ds_top}
    assert top["3003"].rewind_n == 20 and top["3003"].rewind_wr == 30.0
    assert top["7777"].rewind_n == 0 and top["7777"].rewind_wr is None


def test_champ_mismatch_no_buried_when_ds_favors_winners():
    # DS ranks the winner 4444 #1 -> nothing above-baseline is buried.
    ce = _ce("D", ["4444", "7777"], [
        {"id": "4444", "name": "Good", "n": 15, "wr": 65.0},
        {"id": "3003", "name": "Loser", "n": 20, "wr": 30.0},
    ])
    cmw = _cmw("D", "ARAM", 50, 25, [ItemWinRate("4444", 15, 10)])
    m = champ_mismatch(ce, cmw, PermConfig(min_item_n=5))
    assert m.buried_winners == ()


def test_consolidate_orders_worst_and_is_anchor_matched():
    bad = _ce("Bad", ["3003", "7777"], [
        {"id": "3003", "name": "Bad", "n": 20, "wr": 30.0},
        {"id": "4444", "name": "Buried", "n": 15, "wr": 65.0},
    ])
    good = _ce("Good", ["1001", "7777"], [
        {"id": "1001", "name": "Win", "n": 20, "wr": 70.0},
    ])
    win = {
        ("Bad", "ARAM"): _cmw("Bad", "ARAM", 50, 25, [ItemWinRate("3003", 20, 6)]),
        ("Good", "ARAM"): _cmw("Good", "ARAM", 50, 25, [ItemWinRate("1001", 20, 14)]),
        # an SR row exists but Bad/Good anchor ARAM, so consolidate must ignore it
        ("Bad", "SR"): _cmw("Bad", "SR", 9, 1, [ItemWinRate("3003", 9, 0)]),
    }
    rep = consolidate({"Bad": bad, "Good": good}, win, PermConfig(min_item_n=5), worst_n=10)
    json.dumps(rep)  # serializable
    assert rep["n_consolidated"] == 2  # only the two ARAM-anchored rows, SR ignored
    worst = rep["worst"]
    assert worst[0]["champion"] == "Bad"  # lowest mean_lift first
    assert worst[0]["mean_lift"] < worst[1]["mean_lift"]
    assert all(r["mode"] == "ARAM" for r in worst)
