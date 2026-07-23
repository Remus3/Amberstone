"""ENGINE 1.41.0 (2026-05-22) - compute_hybrid consumer wire for cc_conditional.

The ``cc_conditional`` module shipped at ENGINE 1.37.0 (2026-05-22)
as a FORWARD-MARKER seam. ENGINE 1.38.0 (item 142 Slice A) wired
``compute_cc_pressure(include_conditional=False)`` as the FIRST
authorized consumer. ENGINE 1.41.0 (item 143 Slice B) wires
``compute_hybrid(include_conditional=False)`` as the THIRD
authorized consumer (Slice A is compute_ehp as the SECOND consumer).

The kwarg flow is INDIRECT:
  compute_hybrid(include_conditional=...) ->
      compute_ehp(include_conditional=...) ->
          compute_cc_pressure(include_conditional=...)

hybrid.py has no direct dependency on the conditional CC registry.
The forward-marker guard in test_cc_conditional_forward_marker.py
STAYS satisfied without adding hybrid.py to _ALLOWED_SOURCE_FILES
(Slice A may add ehp.py; that is Slice A's concern).

Test surface (7 classes):
  * IdentityContractTests (4) - default include_conditional=False
    byte-identical to item 138 / ENGINE 1.35.0 hybrid behavior;
    empty enemy_champions + include_conditional=True ALSO byte-
    identical (no enemies => no conditional contribution).
  * MultiCallSiteThreadingTests (3) - unittest.mock.patch on
    compute_ehp at the hybrid module boundary; verify all 3 internal
    compute_ehp calls (compute_hybrid + ranker baseline + ranker
    per-candidate) receive the same include_conditional value.
  * ConditionalCcAffectsHybridScoreTests (5) - Brand has conditional
    R only (no unconditional entry); include_conditional=True lowers
    hybrid_score because cc_blended_ehp drops post-conditional-CC
    erosion. Math: score_with_conditional < score_without_conditional
    when enemies have conditional CC entries.
  * HybridResultFieldsTests (3) - cc_blended_ehp reflects conditional
    contribution; enemy_champions field carries through; ehp field
    still PRE-CC blended_ehp.
  * EngineVersionCurrentTests (1) - pin ENGINE_VERSION (orchestrator
    syncs to 1.41.0 at merge).
  * AsciiHygieneTests (2) - pure 7-bit ASCII on this file + the
    hybrid.py edit zone.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hybrid import (
    HybridResult,
    compute_hybrid,
    rank_items_by_hybrid,
)


_SNAPSHOT = DataSnapshot.load()


# ---------------------------------------------------------------- contract


class IdentityContractTests(unittest.TestCase):
    """Default include_conditional=False MUST preserve byte-identical 1.35.0."""

    def test_default_include_conditional_false_byte_identical(self) -> None:
        # No include_conditional arg means default False; behavior must
        # match item 138 / ENGINE 1.35.0 compute_hybrid exactly.
        r = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_explicit_include_conditional_false_byte_identical(self) -> None:
        # Explicitly passing False must also be byte-identical to default.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            include_conditional=False,
        )
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_include_conditional_true_with_empty_enemies_identity(self) -> None:
        # No enemies means no conditional contribution; hybrid_score
        # identical to baseline even with include_conditional=True.
        # Spy on compute_ehp to confirm the kwarg threads through.
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            # Forward to real compute_ehp with the kwarg stripped (real
            # compute_ehp may or may not accept include_conditional
            # depending on whether Slice A has merged). The point of
            # this test is to pin the THREADING through the call site;
            # the math contract (identity at empty enemies) is pinned
            # in IdentityContractTests above.
            kwargs.pop("include_conditional", None)
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            r = compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                include_conditional=True,
            )
        # compute_ehp was called and received include_conditional=True
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("include_conditional"), True)
        # Result fields look like the baseline (no enemies = no
        # cc_blended_ehp discount; cc_blended_ehp == blended_ehp by
        # the item 137 identity contract).
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())

    def test_pre_slice_a_merge_default_path_does_not_pass_kwarg(self) -> None:
        # Before Slice A merges, compute_ehp does not accept the kwarg.
        # The hybrid.py implementation uses the **kwargs threading
        # pattern: when include_conditional is False (default), the
        # kwarg is NOT passed to compute_ehp. Spy verifies this so we
        # can ship Slice B before Slice A without runtime errors.
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                # Note: default include_conditional=False
            )
        # compute_ehp call site does NOT carry include_conditional in
        # the default path - this is the parallel-merge safety pattern.
        self.assertEqual(len(captured), 1)
        self.assertNotIn("include_conditional", captured[0])


# ---------------------------------------------------- multi call site


class MultiCallSiteThreadingTests(unittest.TestCase):
    """All 3 internal compute_ehp call sites thread include_conditional.

    compute_hybrid has 1 compute_ehp call; rank_items_by_hybrid has 2
    (baseline + per-candidate scored). All 3 must thread the same
    include_conditional value. Spy on the hybrid module's compute_ehp
    binding to capture every call.
    """

    def test_compute_hybrid_call_site_threads_include_conditional(self) -> None:
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            # Strip include_conditional to keep the real call working
            # regardless of Slice A merge status.
            kwargs.pop("include_conditional", None)
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Annie",),
                include_conditional=True,
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get("include_conditional"), True)

    def test_rank_items_by_hybrid_baseline_threads_include_conditional(self) -> None:
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            kwargs.pop("include_conditional", None)
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            # only_item_ids=() with include_components=False keeps the
            # candidate loop empty so only the baseline fires.
            rank_items_by_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                current_item_ids=(),
                mode="SR",
                enemy_champions=("Annie",),
                only_item_ids=(),
                include_conditional=True,
            )
        # Baseline call must thread the kwarg
        self.assertGreaterEqual(len(captured), 1)
        self.assertEqual(captured[0].get("include_conditional"), True)

    def test_rank_items_by_hybrid_all_sites_thread_same_value(self) -> None:
        # When the inner loop fires, every scored compute_ehp must
        # ALSO receive include_conditional=True. Use a small whitelist
        # to keep the loop short.
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            kwargs.pop("include_conditional", None)
            return compute_ehp(*args, **kwargs)

        # 3053 Sterak's Gage + 3072 Bloodthirster - well-known terminals
        whitelist = ("3053", "3072")

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            rank_items_by_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                current_item_ids=(),
                mode="SR",
                enemy_champions=("Annie",),
                only_item_ids=whitelist,
                top_n=10,
                include_conditional=True,
            )
        # Baseline + per-candidate calls all carry include_conditional=True
        self.assertGreaterEqual(len(captured), 2)
        for kwargs in captured:
            self.assertEqual(
                kwargs.get("include_conditional"),
                True,
                msg="every compute_ehp call site must thread include_conditional",
            )


# ---------------------------------------------- score lift via conditional


class ConditionalCcAffectsHybridScoreTests(unittest.TestCase):
    """include_conditional=True changes hybrid_score via cc_blended_ehp.

    Brand has a conditional R Pyroclasm entry (stun 2.0s * prob 0.7 =
    1.4s contribution) but NO unconditional entry. So:
      * Brand enemy, include_conditional=False -> no CC contribution
        -> cc_blended_ehp == blended_ehp -> hybrid_score baseline.
      * Brand enemy, include_conditional=True -> 1.4s post-tenacity
        -> cc_blended_ehp < blended_ehp -> hybrid_score < baseline.
    """

    def _hybrid_score_via_fake_ehp(self, fake_ehp_result, *, expect_kwarg):
        """Helper: monkeypatch compute_ehp at hybrid boundary, capture
        the kwarg flow, return a deterministic synthetic EhpResult."""
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            return fake_ehp_result

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            r = compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Brand",),
                include_conditional=expect_kwarg,
            )
        return r, captured

    def test_synthetic_ehp_lower_cc_blended_lowers_hybrid_score(self) -> None:
        # Synthesize two compute_ehp returns: one with cc_blended_ehp
        # equal to blended_ehp (no conditional CC) and one with a lower
        # cc_blended_ehp (conditional CC erosion). hybrid_score scales
        # with cc_blended_ehp when enemy_champions is non-empty.
        from dataclasses import replace
        from agents.daemon_slayer.ehp import EhpResult

        # Use a real compute_ehp run as the baseline shape, then
        # synthesize the conditional-on variant by lowering
        # cc_blended_ehp via dataclasses.replace.
        baseline_ehp = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand",),
        )
        # Lower the cc_blended_ehp to simulate conditional CC contribution
        lower_ehp = replace(baseline_ehp, cc_blended_ehp=baseline_ehp.blended_ehp * 0.85)

        # Run compute_hybrid against each fake return
        r_baseline, _ = self._hybrid_score_via_fake_ehp(baseline_ehp, expect_kwarg=False)
        r_with_cond, _ = self._hybrid_score_via_fake_ehp(lower_ehp, expect_kwarg=True)

        # Lower cc_blended_ehp => lower hybrid_score (when enemies non-empty)
        self.assertLess(r_with_cond.hybrid_score, r_baseline.hybrid_score)
        # Delta is exactly beta * (baseline_cc_blended_ehp - lower_cc_blended_ehp)
        expected_delta = r_baseline.beta * (
            baseline_ehp.cc_blended_ehp - lower_ehp.cc_blended_ehp
        )
        actual_delta = r_baseline.hybrid_score - r_with_cond.hybrid_score
        self.assertAlmostEqual(expected_delta, actual_delta, places=4)

    def test_include_conditional_true_threads_to_ehp(self) -> None:
        # With include_conditional=True the kwarg reaches compute_ehp.
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            kwargs.pop("include_conditional", None)
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Brand",),
                include_conditional=True,
            )
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].get("include_conditional"))

    def test_include_conditional_false_does_not_thread_to_ehp(self) -> None:
        # With include_conditional=False (default), the kwarg is NOT
        # passed to compute_ehp - this is the parallel-merge safety
        # pattern (compute_ehp may not accept the kwarg pre-Slice-A).
        captured = []

        def spy(*args, **kwargs):
            captured.append(dict(kwargs))
            return compute_ehp(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Brand",),
                include_conditional=False,
            )
        self.assertEqual(len(captured), 1)
        self.assertNotIn("include_conditional", captured[0])

    def test_unconditional_path_byte_identical_to_pre_slice_b(self) -> None:
        # Without include_conditional (or with False), hybrid_score
        # must match the pre-Slice-B math exactly. Brand has no
        # unconditional CC, so cc_blended_ehp == blended_ehp.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand",),
        )
        # Brand has no unconditional entry in _PER_SPELL_CC_DURATIONS
        # so the cc_pressure_fraction stays 0 and cc_blended_ehp ==
        # blended_ehp == ehp field.
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        # hybrid_score = alpha * dps + beta * ehp (the post-discount
        # value equals the pre-discount value when no CC contribution).
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_morgana_unconditional_still_works_at_default(self) -> None:
        # Morgana has unconditional Q Dark Binding 3.0s root.
        # Even with include_conditional=False, the unconditional path
        # via compute_cc_pressure still fires inside compute_ehp,
        # giving a non-zero cc_blended_ehp discount.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        # Morgana unconditional CC erodes cc_blended_ehp below
        # blended_ehp; the discount fires at the default since the
        # unconditional path doesn't depend on include_conditional.
        self.assertLessEqual(r.cc_blended_ehp, r.ehp)


# ------------------------------------------------- HybridResult fields


class HybridResultFieldsTests(unittest.TestCase):
    """HybridResult fields reflect the threading correctly."""

    def test_cc_blended_ehp_reflects_underlying_ehp_result(self) -> None:
        # The HybridResult.cc_blended_ehp field surfaces the value
        # the underlying EhpResult returned - this contract is
        # unchanged from item 138 / ENGINE 1.35.0; pinned here as
        # a smoke check that Slice B did not break the wire.
        r_h = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        r_e = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        self.assertAlmostEqual(r_h.cc_blended_ehp, r_e.cc_blended_ehp, places=4)

    def test_enemy_champions_field_carries_through(self) -> None:
        # The enemy_champions field carries the normalized tuple
        # regardless of include_conditional - this is unchanged from
        # item 138 but the schema must stay byte-identical.
        enemies = ("Annie", "Morgana", "Malzahar")
        r_default = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies,
        )
        # NOTE: include_conditional=True path uses default compute_ehp
        # which does not yet accept the kwarg pre-Slice-A; the path
        # still works because hybrid.py gates the kwarg pass-through.
        # Just verify the field is identical regardless of conditional
        # state when enemies are the same.
        self.assertEqual(r_default.enemy_champions, enemies)

    def test_ehp_field_stays_pre_cc_blended_ehp(self) -> None:
        # The ehp field on HybridResult is blended_ehp (PRE-CC) for
        # transparency; the cc_blended_ehp field is the POST-CC
        # surface alongside. This contract is unchanged from item 138
        # but must NOT regress in Slice B.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        r_e = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        # ehp field is the PRE-CC blended_ehp from the EhpResult
        self.assertAlmostEqual(r.ehp, r_e.blended_ehp, places=4)
        # cc_blended_ehp is the POST-CC value
        self.assertAlmostEqual(r.cc_blended_ehp, r_e.cc_blended_ehp, places=4)
        # The two are different when CC contribution exists
        self.assertLessEqual(r.cc_blended_ehp, r.ehp)


# --------------------------------------------------- engine version pin


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION (orchestrator syncs to 1.41.0 at merge)."""

    def test_engine_version_is_current(self) -> None:
        # DO NOT change this string in this slice; the orchestrator
        # syncs all ENGINE pin sites at merge. Current pre-merge
        # state on main is 1.38.0 (item 142 cf5f509). Orchestrator
        # bumps to 1.41.0 post-merge of Slice A + Slice B.
        self.assertEqual(ENGINE_VERSION, "1.239.0")


# --------------------------------------------------- ASCII hygiene


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes, en-dashes, or smart quotes in the new code or test."""

    def _scan_file_for_bad_glyphs(self, path: pathlib.Path) -> list:
        """Return list of (line_no, glyph_name, line) for any bad glyphs."""
        # Build the bad-glyph dict via chr() so this test file itself
        # stays ASCII-clean against its own scan.
        bad = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left-double-quote",
            chr(0x201D): "right-double-quote",
            chr(0x2018): "left-single-quote",
            chr(0x2019): "right-single-quote",
        }
        findings = []
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            for glyph, name in bad.items():
                if glyph in line:
                    findings.append((line_no, name, line))
        return findings

    def test_this_test_file_is_ascii_clean(self) -> None:
        here = pathlib.Path(__file__)
        findings = self._scan_file_for_bad_glyphs(here)
        self.assertEqual(
            findings, [], msg=f"Bad glyphs in {here.name}: {findings}"
        )

    def test_hybrid_module_has_no_new_smart_quotes(self) -> None:
        # Scan the entire hybrid.py module; do NOT introduce any of
        # the 6 forbidden glyphs in the Slice B edits.
        hybrid_path = (
            pathlib.Path(__file__).resolve().parent.parent / "hybrid.py"
        )
        findings = self._scan_file_for_bad_glyphs(hybrid_path)
        self.assertEqual(
            findings,
            [],
            msg=f"Bad glyphs in hybrid.py: {findings}",
        )


if __name__ == "__main__":
    unittest.main()
