"""RM-164 - scorer-ARCHETYPE provenance on every HZ-B1 precompute cell.

WHY THIS EXISTS
    ``core.build_order_precompute`` ranks every cell under ONE scorer archetype,
    resolved per champion by ``core.archetype_picks.get_archetype_for`` (an
    operator pick when one is set, else the DDragon-tag default). Until this
    slice the cell recorded the comp-archetype axis + the enemy-context bias but
    NOT the scorer it was ranked under, so a future consumer reading the table at
    request time had no way to notice that the operator had since overridden the
    champion's archetype - it would serve a build ranked by the OLD scorer while
    every other surface routed to the new one, silently.

    That is the failure most likely to make a Lane B coach flip unsafe (RM-164,
    filed 2026-08-06, LEDGER 1203), so the provenance lands BEFORE any consumer
    is wired, not with it.

WHAT IS ASSERTED
    (a) every generated cell carries the archetype it was actually ranked under -
        the explicit override when one is passed, the resolved primary otherwise;
    (b) a cell whose recorded archetype differs from the requested one is
        DETECTABLE through a consumer-side check this module owns
        (``archetype_status``), which is THREE-valued so a pre-provenance table
        reads UNKNOWN rather than falsely fresh or falsely stale;
    (c) the schema addition does not reorder or change any ranking - asserted on
        the COMPUTED order (identical to a direct ``plan_build_order`` call under
        the same injected ranker) and on the kwargs that actually reach the
        engine, never on a cross-item comparison.

No live engine: the shipped ``plan_build_order`` takes an injectable ``rank_fn``,
so a deterministic stub stands in for the :8860 dispatcher.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop  # noqa: E402
from tests.test_build_order_precompute import (  # noqa: E402
    _fake_rank_fn,
    load_shipped_table,
)

_RANKED = ["3153", "3071", "3074", "3033", "3036", "6333"]


# --------------------------------------------------------------------------- #
# (a) every cell carries the archetype it was ranked under
# --------------------------------------------------------------------------- #
class CellRecordsItsArchetypeTests(unittest.TestCase):

    def test_cell_records_the_explicit_archetype_it_was_ranked_under(self):
        """An explicit ``archetype=`` is what ranked the cell, so it is what the
        cell must record - not the champion's resolved default."""
        cell = bop.compute_cell(
            "Aatrox", "frontline_heavy", mode="SR",
            archetype="bruiser", level=11, rank_fn=_fake_rank_fn(_RANKED),
        )
        self.assertEqual(cell[bop.ARCHETYPE_KEY], "bruiser")
        # And it is genuinely the ranked-under value, not a constant: a second
        # cell ranked under a different scorer records that one.
        other = bop.compute_cell(
            "Aatrox", "frontline_heavy", mode="SR",
            archetype="tank", level=11, rank_fn=_fake_rank_fn(_RANKED),
        )
        self.assertEqual(other[bop.ARCHETYPE_KEY], "tank")

    def test_cell_records_the_resolved_primary_when_not_overridden(self):
        """Production passes no ``archetype``; the cell must record whatever
        ``archetype_for`` resolved, which is the operator pick when one is set."""
        expected = bop.archetype_for("Aatrox")
        cell = bop.compute_cell(
            "Aatrox", "mixed", mode="SR", level=11,
            rank_fn=_fake_rank_fn(_RANKED),
        )
        self.assertEqual(cell[bop.ARCHETYPE_KEY], expected)

    def test_every_cell_of_a_generated_table_carries_an_archetype(self):
        champs = ["Aatrox", "Annie", "Caitlyn"]
        payload = bop.generate_table(
            champs, mode="SR", level=11, rank_fn=_fake_rank_fn(_RANKED),
        )
        orders = payload["build_orders"]
        seen = 0
        for champ, classes in orders.items():
            for comp, cell in classes.items():
                arch = cell.get(bop.ARCHETYPE_KEY)
                self.assertTrue(
                    isinstance(arch, str) and arch.strip(),
                    f"{champ}/{comp} carries no scorer-archetype provenance",
                )
                seen += 1
        self.assertEqual(seen, len(champs) * len(bop.COMP_ARCHETYPES))

    def test_archetype_is_constant_across_the_comp_axis_for_one_champion(self):
        """The comp axis describes the ENEMY; it never changes which scorer the
        champion reads. A per-comp divergence would mean the provenance was
        recomputed per cell instead of recording the one used."""
        payload = bop.generate_table(
            ["Caitlyn"], mode="SR", level=11, rank_fn=_fake_rank_fn(_RANKED),
        )
        classes = next(iter(payload["build_orders"].values()))
        recorded = {cell[bop.ARCHETYPE_KEY] for cell in classes.values()}
        self.assertEqual(len(recorded), 1, f"archetype diverged: {recorded}")


# --------------------------------------------------------------------------- #
# (b) a consumer can DETECT a mismatch against the requested archetype
# --------------------------------------------------------------------------- #
class ConsumerStalenessCheckTests(unittest.TestCase):

    def _cell(self, archetype):
        return {
            "comp_archetype": "mixed",
            "order": ["3153"],
            "bias": {},
            bop.ARCHETYPE_KEY: archetype,
        }

    def test_matching_archetype_reads_fresh(self):
        self.assertEqual(
            bop.archetype_status(self._cell("carry"), "carry"),
            bop.ARCHETYPE_FRESH,
        )

    def test_differing_archetype_is_detected_as_stale(self):
        self.assertEqual(
            bop.archetype_status(self._cell("carry"), "tank"),
            bop.ARCHETYPE_STALE,
        )

    def test_operator_override_makes_a_shipped_cell_read_stale(self):
        """End to end: the cell was ranked under the resolved primary; an
        operator override moves the champion to a different scorer; the consumer
        check fires without re-running the engine."""
        cell = bop.compute_cell(
            "Aatrox", "mixed", mode="SR", level=11,
            rank_fn=_fake_rank_fn(_RANKED),
        )
        ranked_under = cell[bop.ARCHETYPE_KEY]
        override = "enchanter" if ranked_under != "enchanter" else "carry"
        self.assertEqual(
            bop.archetype_status(cell, ranked_under), bop.ARCHETYPE_FRESH,
        )
        self.assertEqual(
            bop.archetype_status(cell, override), bop.ARCHETYPE_STALE,
        )

    def test_pre_provenance_cell_reads_unknown_not_fresh_and_not_stale(self):
        """A table generated before this slice carries no archetype. It must NOT
        read fresh (that would license a consumer to trust it) and must NOT read
        stale (that would blank every cell of a perfectly good table)."""
        legacy = {"comp_archetype": "mixed", "order": ["3153"], "bias": {}}
        self.assertEqual(
            bop.archetype_status(legacy, "carry"), bop.ARCHETYPE_UNKNOWN,
        )

    def test_status_is_total_over_ragged_input(self):
        for cell in (None, [], "carry", {}, {bop.ARCHETYPE_KEY: ""},
                     {bop.ARCHETYPE_KEY: 7}):
            self.assertEqual(
                bop.archetype_status(cell, "carry"), bop.ARCHETYPE_UNKNOWN,
                f"ragged cell {cell!r} did not read unknown",
            )
        for requested in (None, "", "   ", 7):
            self.assertEqual(
                bop.archetype_status(self._cell("carry"), requested),
                bop.ARCHETYPE_UNKNOWN,
                f"ragged request {requested!r} did not read unknown",
            )

    def test_comparison_ignores_case_and_surrounding_space(self):
        self.assertEqual(
            bop.archetype_status(self._cell(" Carry "), "carry"),
            bop.ARCHETYPE_FRESH,
        )

    def test_cell_archetype_is_total(self):
        self.assertEqual(bop.cell_archetype(self._cell("tank")), "tank")
        for cell in (None, [], "tank", {}, {bop.ARCHETYPE_KEY: None},
                     {bop.ARCHETYPE_KEY: 3}):
            self.assertEqual(bop.cell_archetype(cell), "")


# --------------------------------------------------------------------------- #
# (c) the schema addition changes NO ranking
# --------------------------------------------------------------------------- #
class ProvenanceDoesNotPerturbRankingTests(unittest.TestCase):

    def test_order_still_equals_a_direct_plan_build_order_call(self):
        """Assert on the COMPUTED order, per comp class, against the engine call
        the precompute is a re-parameterization of."""
        from core.build_order import plan_build_order

        for comp in bop.COMP_ARCHETYPES:
            with self.subTest(comp=comp):
                bias = bop.bias_for(comp)
                direct, rank_kwargs = bop.split_bias(bias)
                cell = bop.compute_cell(
                    "Aatrox", comp, mode="SR", archetype="bruiser", level=11,
                    rank_fn=_fake_rank_fn(_RANKED),
                )
                ref = plan_build_order(
                    "Aatrox", "bruiser", level=11, owned_item_ids=[], mode="SR",
                    slots=bop.SLOTS, rank_fn=_fake_rank_fn(_RANKED),
                    rank_kwargs=rank_kwargs, **direct,
                )
                self.assertIsNotNone(ref)
                self.assertEqual(cell["order"], [s.item_id for s in ref.order])

    def test_provenance_key_never_reaches_the_engine(self):
        """The stamp is a RECORD of the scorer, not a new ranking input. If it
        leaked into the rank kwargs it could perturb a real dispatcher."""
        seen = []

        def _spy(champion, archetype, **kwargs):
            seen.append(dict(kwargs))
            return _fake_rank_fn(_RANKED)(champion, archetype, **kwargs)

        bop.compute_cell(
            "Aatrox", "mixed", mode="SR", archetype="bruiser", level=11,
            rank_fn=_spy,
        )
        self.assertTrue(seen, "the spy ranker was never called")
        for kwargs in seen:
            self.assertNotIn(bop.ARCHETYPE_KEY, kwargs)

    def test_existing_leaf_keys_are_untouched(self):
        """Additive only: the pre-existing leaf contract still holds exactly."""
        bias = bop.bias_for("poke")
        cell = bop.compute_cell(
            "Aatrox", "poke", mode="SR", archetype="bruiser", level=11,
            rank_fn=_fake_rank_fn(_RANKED),
        )
        self.assertEqual(cell["comp_archetype"], "poke")
        self.assertEqual(cell["bias"], bias)
        self.assertIsInstance(cell["order"], list)


# --------------------------------------------------------------------------- #
# The SHIPPED tables must carry the provenance too - a generator-only stamp
# leaves every committed cell unreadable by the consumer check above.
# --------------------------------------------------------------------------- #
class ShippedTableProvenanceTests(unittest.TestCase):

    def test_every_shipped_cell_carries_a_known_archetype(self):
        for mode_key in ("sr", "aram", "arena"):
            with self.subTest(mode=mode_key):
                payload = load_shipped_table(
                    bop._db_path(mode_key, bop.resolve_patch()),
                    f"HZ-B1 build_orders/{mode_key}",
                )
                orders = payload.get("build_orders") or {}
                self.assertTrue(orders, f"{mode_key}: empty table")
                missing = []
                unknown = []
                for champ, classes in orders.items():
                    for comp, cell in (classes or {}).items():
                        arch = bop.cell_archetype(cell)
                        if not arch:
                            missing.append(f"{champ}/{comp}")
                        elif arch not in bop.KNOWN_ARCHETYPES:
                            unknown.append(f"{champ}/{comp}={arch}")
                self.assertFalse(
                    missing[:5],
                    f"{mode_key}: {len(missing)} cells carry no scorer-archetype "
                    f"provenance (regen: python -m core.build_order_precompute "
                    f"--static --mode all --champions all); first: {missing[:5]}",
                )
                self.assertFalse(
                    unknown[:5],
                    f"{mode_key}: {len(unknown)} cells record an archetype "
                    f"outside the known set; first: {unknown[:5]}",
                )


if __name__ == "__main__":
    unittest.main()
