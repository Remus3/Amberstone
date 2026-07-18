"""An unpaired enemy damage share must not silently kill the recommendation.

`core.daemon_slayer_client` exposes five ranking entry points that each default
BOTH ``enemy_ad_share`` and ``enemy_ap_share`` to 0.5 independently. The engine
requires the pair to sum to <= 1.0 (documented at
``daemon_slayer_client.py:279``), so a caller that supplies only the side it
actually knows ships 0.77 + 0.5 = 1.27, the server rejects the body, and
``_post_json`` maps that to None. The caller sees "engine unreachable" and
renders NO recommendation at all - a silent, total failure from a perfectly
reasonable call.

Measured before the fix (live 1.219.0, Thresh / tank / L16 / SR / top=200):

    {}                                        -> 141 rows
    {"enemy_ad_share": 0.77}                  -> None          <-- the defect
    {"enemy_ad_share": 0.77, "ap": 0.23}      -> 141 rows

This matters now because the archetype-objective work feeds REAL enemy
compositions instead of a synthetic 50/50. Measured over the rewind corpus,
50.1 percent of 1286 real team comps carry an AD share outside [0.40, 0.60], so
roughly half of real comps would hit this path.

The fix derives the missing partner (``ap = 1.0 - ad``) rather than validating
and raising: the shares are a partition of one enemy team's damage, so the
complement is the only sensible reading, and a mid-game coach must degrade to a
usable answer rather than to nothing. Supplying BOTH values is unchanged.
"""

import unittest

from core import daemon_slayer_client as dsc


class ResolveSharesTests(unittest.TestCase):
    """Unit-level contract for the share-pair resolver."""

    def test_neither_supplied_keeps_the_neutral_split(self) -> None:
        self.assertEqual(dsc._resolve_enemy_shares(None, None), (0.5, 0.5))

    def test_only_ad_supplied_derives_the_complement(self) -> None:
        ad, ap = dsc._resolve_enemy_shares(0.77, None)
        self.assertAlmostEqual(ad, 0.77)
        self.assertAlmostEqual(ap, 0.23)

    def test_only_ap_supplied_derives_the_complement(self) -> None:
        ad, ap = dsc._resolve_enemy_shares(None, 0.8)
        self.assertAlmostEqual(ad, 0.2)
        self.assertAlmostEqual(ap, 0.8)

    def test_both_supplied_are_passed_through_untouched(self) -> None:
        self.assertEqual(dsc._resolve_enemy_shares(0.6, 0.4), (0.6, 0.4))

    def test_both_supplied_summing_under_one_is_not_renormalized(self) -> None:
        """A deliberate sub-unit split (true damage remainder) must survive."""
        self.assertEqual(dsc._resolve_enemy_shares(0.5, 0.3), (0.5, 0.3))

    def test_an_over_unit_pair_is_renormalized_rather_than_rejected(self) -> None:
        ad, ap = dsc._resolve_enemy_shares(0.8, 0.8)
        self.assertLessEqual(ad + ap, 1.0 + 1e-9)
        self.assertAlmostEqual(ad, ap)

    def test_out_of_range_inputs_are_clamped(self) -> None:
        self.assertEqual(dsc._resolve_enemy_shares(1.4, None), (1.0, 0.0))
        self.assertEqual(dsc._resolve_enemy_shares(-0.3, None), (0.0, 1.0))

    def test_resolved_pair_always_satisfies_the_engine_contract(self) -> None:
        """Whatever goes in, what comes out is a body the engine will accept."""
        candidates = [None, -1.0, 0.0, 0.23, 0.5, 0.77, 1.0, 2.0]
        for ad in candidates:
            for ap in candidates:
                with self.subTest(ad=ad, ap=ap):
                    r_ad, r_ap = dsc._resolve_enemy_shares(ad, ap)
                    self.assertGreaterEqual(r_ad, 0.0)
                    self.assertGreaterEqual(r_ap, 0.0)
                    self.assertLessEqual(r_ad, 1.0)
                    self.assertLessEqual(r_ap, 1.0)
                    self.assertLessEqual(r_ad + r_ap, 1.0 + 1e-9)


class UnpairedShareBodyTests(unittest.TestCase):
    """The emitted request body must be engine-legal for an unpaired call.

    Asserted on the BODY rather than on a live ranking so the test is
    deterministic and runs with the engine down.
    """

    def _capture_body(self, **kwargs) -> dict:
        seen: dict = {}

        def _fake_post(path, body, timeout=None):  # noqa: ARG001
            seen.update(body)
            return None

        original = dsc._post_json
        dsc._post_json = _fake_post
        try:
            dsc.rank_for_primary_archetype(
                "Thresh", "tank", level=16, item_ids=[], mode="SR", **kwargs
            )
        finally:
            dsc._post_json = original
        return seen

    def test_unpaired_ad_share_emits_a_legal_pair(self) -> None:
        body = self._capture_body(enemy_ad_share=0.77)
        self.assertAlmostEqual(body["enemy_ad_share"], 0.77)
        self.assertAlmostEqual(body["enemy_ap_share"], 0.23)
        self.assertLessEqual(
            body["enemy_ad_share"] + body["enemy_ap_share"],
            1.0 + 1e-9,
            "unpaired share still emits an over-unit pair; the engine will "
            "reject this body and the caller will render no recommendation",
        )

    def test_default_call_is_byte_identical_to_the_old_neutral_split(self) -> None:
        body = self._capture_body()
        self.assertEqual(body["enemy_ad_share"], 0.5)
        self.assertEqual(body["enemy_ap_share"], 0.5)

    def test_explicit_pair_is_passed_through(self) -> None:
        body = self._capture_body(enemy_ad_share=0.6, enemy_ap_share=0.4)
        self.assertAlmostEqual(body["enemy_ad_share"], 0.6)
        self.assertAlmostEqual(body["enemy_ap_share"], 0.4)


if __name__ == "__main__":
    unittest.main()
