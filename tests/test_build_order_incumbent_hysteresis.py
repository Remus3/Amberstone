"""DS build-suggestion stability, fix (b) - incumbent hysteresis in _pick_top_safe.

PD -> Kraken instability (2026-07-06 spec): the greedy planner returns rows[0]
per slot, so a level tick that crosses two close items (repro: Kraken 122.3 ->
Hexoptics 124.5 at lvl 12->13) genuinely flips the displayed pick even though
the two are within noise. Fix (b) threads an OPTIONAL incumbent (the currently
displayed pick) + a margin into _pick_top_safe: keep the incumbent unless the
top challenger beats it by more than the margin. ADDITIVE - with no incumbent
passed, the function is byte-identical to the old rows[0] behavior.
"""
import unittest

from core.build_order import _pick_top_safe, plan_build_order


def _row(item_id, delta, shares_dead=False, dead_key="", name=None):
    return {
        "item_id": item_id,
        "item_name": name or f"i{item_id}",
        "delta": delta,
        "delta_dps": delta,
        "shares_dead_unique": shares_dead,
        "dead_unique_key": dead_key,
    }


class PickTopSafeIncumbentTests(unittest.TestCase):
    def test_no_incumbent_returns_top_row_bytecompat(self):
        rows = [_row("A", 124.5), _row("B", 122.3)]
        chosen, fam, ex = _pick_top_safe(rows)
        self.assertEqual(chosen["item_id"], "A")
        self.assertEqual((fam, ex), ("", ""))

    def test_incumbent_kept_when_challenger_within_margin(self):
        # Kraken (incumbent) 122.3 vs Hexoptics 124.5 = +1.8% < 3% -> keep Kraken.
        rows = [_row("Hexoptics", 124.5), _row("Kraken", 122.3)]
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="Kraken", incumbent_margin=0.03)
        self.assertEqual(chosen["item_id"], "Kraken")

    def test_incumbent_dropped_when_challenger_beats_margin(self):
        rows = [_row("Big", 200.0), _row("Kraken", 100.0)]  # +100% >> 3%
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="Kraken", incumbent_margin=0.03)
        self.assertEqual(chosen["item_id"], "Big")

    def test_incumbent_is_the_top_row_no_change(self):
        rows = [_row("Kraken", 124.5), _row("B", 100.0)]
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="Kraken")
        self.assertEqual(chosen["item_id"], "Kraken")

    def test_incumbent_absent_from_rows_falls_back_to_top(self):
        rows = [_row("A", 124.5), _row("B", 122.3)]
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="GONE")
        self.assertEqual(chosen["item_id"], "A")

    def test_dead_unique_incumbent_is_not_clung_to(self):
        # An incumbent that now collides with a locked unique must NOT be kept.
        rows = [_row("A", 124.5), _row("Kraken", 122.3, shares_dead=True, dead_key="LW")]
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="Kraken")
        self.assertEqual(chosen["item_id"], "A")

    def test_nonpositive_delta_incumbent_is_not_clung_to(self):
        # A regressed incumbent (delta <= 0) yields to a real positive pick.
        rows = [_row("A", 50.0), _row("Kraken", 0.0)]
        chosen, _, _ = _pick_top_safe(rows, incumbent_id="Kraken")
        self.assertEqual(chosen["item_id"], "A")


def _fake_engine(rows_by_call):
    """A rank_fn returning a fixed 'ranked' list per 1-based engine-call index."""
    state = {"n": 0}

    def eng(champion, archetype, **kw):
        state["n"] += 1
        return {
            "ok": True,
            "scorer": "dps",
            "archetype": archetype,
            "ranked": rows_by_call.get(state["n"], []),
            "fell_back": False,
        }

    return eng


def _engine_row(item_id, delta):
    return {
        "item_id": item_id,
        "item_name": item_id,
        "delta": delta,
        "gold": 3000,
        "shares_dead_unique": False,
        "dead_unique_key": "",
        "unique_passive_key": "",
    }


class PlanBuildOrderIncumbentTests(unittest.TestCase):
    """The incumbent threads end-to-end: plan_build_order maps the displayed
    engine-pick sequence onto each slot's _pick_top_safe."""

    def test_planner_keeps_slot1_incumbent_within_margin(self):
        eng = _fake_engine({1: [_engine_row("Hexoptics", 124.5), _engine_row("Kraken", 122.3)]})
        res = plan_build_order(
            "Jinx", "carry", level=13, owned_item_ids=[], mode="SR",
            slots=1, inject_boots=False, rank_fn=eng, incumbent=["Kraken"],
        )
        self.assertEqual([s.item_id for s in res.order], ["Kraken"])

    def test_planner_switches_when_challenger_beats_margin(self):
        eng = _fake_engine({1: [_engine_row("Big", 200.0), _engine_row("Kraken", 100.0)]})
        res = plan_build_order(
            "Jinx", "carry", level=13, owned_item_ids=[], mode="SR",
            slots=1, inject_boots=False, rank_fn=eng, incumbent=["Kraken"],
        )
        self.assertEqual([s.item_id for s in res.order], ["Big"])

    def test_planner_without_incumbent_is_greedy_top1_bytecompat(self):
        eng = _fake_engine({1: [_engine_row("Hexoptics", 124.5), _engine_row("Kraken", 122.3)]})
        res = plan_build_order(
            "Jinx", "carry", level=13, owned_item_ids=[], mode="SR",
            slots=1, inject_boots=False, rank_fn=eng,
        )
        self.assertEqual([s.item_id for s in res.order], ["Hexoptics"])

    def test_planner_drops_owned_ids_from_incumbent_so_slots_align(self):
        # The panel echoes the full displayed order; an already-owned id in it
        # must be dropped so the remaining incumbent ids line up 1:1 with the
        # engine picks (the boots id is dropped the same way).
        eng = _fake_engine({1: [_engine_row("Hexoptics", 124.5), _engine_row("Kraken", 122.3)]})
        res = plan_build_order(
            "Jinx", "carry", level=13, owned_item_ids=["1001"], mode="SR",
            slots=2, inject_boots=False, rank_fn=eng,
            incumbent=["1001", "Kraken"],  # 1001 owned -> dropped -> Kraken is slot 1
        )
        self.assertEqual(res.order[0].item_id, "Kraken")


if __name__ == "__main__":
    unittest.main()
