"""ENGINE 1.35.0 (2026-05-22) - compute_hybrid enemy_champions kwarg.

Item 138 carry (a) engine-consumer slice. ``compute_hybrid`` is the
FIRST DS-engine SCORER consumer of ``cc_blended_ehp`` (the field shipped
item 137 / ENGINE 1.32.0 -> 1.33.0 via ``compute_ehp``). The kwarg
threads enemy champion ids into compute_ehp; when non-empty, the
hybrid_score reads cc_blended_ehp in place of blended_ehp.

Contract:
  * Default (empty tuple) preserves byte-identical behavior with all
    pre-1.35.0 callers (compute_ehp identity contract: empty
    enemy_champions -> cc_blended_ehp == blended_ehp).
  * Non-empty enemy_champions -> hybrid_score uses the CC-discounted
    EHP value; the delta is exactly beta * (blended_ehp - cc_blended_ehp).
  * The new cc_blended_ehp + enemy_champions fields on HybridResult
    surface the discounted value + the input tuple for transparency.

Test surface:
  * IdentityContractTests - default kwarg / empty tuple / None / empty
    list all return cc_blended_ehp == ehp == blended_ehp; hybrid_score
    unchanged from pre-1.35.0 math.
  * EnemyChampionsScoringTests - lift direction (more CC = lower
    hybrid_score), exact delta magnitude, cc_blended_ehp + enemy_champions
    field semantics, mode-agnostic SR identity.
  * MultiCallSiteThreadingTests - all 3 internal compute_ehp call sites
    (compute_hybrid + 2 in rank_items_by_hybrid) receive the same
    enemy_champions tuple.
  * MalformedEnemyChampionsTests - None / blank / unknown / list vs
    tuple input - all silently skipped or accepted per compute_ehp
    fail-soft contract.
  * HybridResultFieldsTests - cc_blended_ehp + enemy_champions field
    defaults + to_dict round-trip + equality semantics.
  * EngineVersionCurrentTests - ENGINE_VERSION pinned to current
    branch (orchestrator bumps at merge).
  * AsciiHygieneTests - pure ASCII on this file + the hybrid.py edit
    zone.
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
    """Default behavior must be byte-identical with pre-1.35.0."""

    def test_default_enemy_champions_preserves_identity(self) -> None:
        # Without the kwarg the new field stays at the cc_blended_ehp ==
        # ehp identity (via the compute_ehp item 137 contract). The
        # hybrid_score is unchanged from pre-1.35.0 math.
        r = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())
        # hybrid_score = alpha * dps + beta * ehp (since cc_blended_ehp == ehp)
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_empty_tuple_explicit_identity(self) -> None:
        r = compute_hybrid(
            _SNAPSHOT, "Aatrox", level=11, mode="SR", enemy_champions=()
        )
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_none_coerced_via_or_empty(self) -> None:
        # Passing None must coerce to empty tuple via ``or ()`` - this is
        # the same shape as item_list normalization. Without this, the
        # tuple comprehension would raise TypeError on None.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=None,  # type: ignore[arg-type]
        )
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())

    def test_empty_list_treated_as_empty_tuple(self) -> None:
        # Empty list normalizes to empty tuple; identity preserved.
        r = compute_hybrid(
            _SNAPSHOT, "Aatrox", level=11, mode="SR", enemy_champions=[]
        )
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())


# ---------------------------------------------------------- scoring + lift


class EnemyChampionsScoringTests(unittest.TestCase):
    """Lift direction + exact magnitude + field semantics."""

    def test_lift_direction_more_cc_lowers_hybrid_score(self) -> None:
        # 3 heavy-CC enemies sum 7s of pressure (Annie R 1.5 + Morgana Q
        # 3.0 + Malzahar R 2.5); clamped to 1.0 fraction; CC factor 0.5;
        # cc_blended_ehp = blended_ehp * 0.5. hybrid_score MUST decrease
        # relative to the no-enemy baseline.
        r_baseline = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        r_with_cc = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana", "Malzahar"),
        )
        self.assertLess(r_with_cc.hybrid_score, r_baseline.hybrid_score)

    def test_exact_delta_equals_beta_times_ehp_discount(self) -> None:
        # The delta in hybrid_score must equal beta * (blended_ehp -
        # cc_blended_ehp) exactly - any deviation indicates the wrong
        # field is being multiplied or the dps weight is leaking in.
        r0 = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        r1 = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana", "Malzahar"),
        )
        # dps is identical between r0 and r1 (compute_dps is unaffected
        # by enemy_champions); only the ehp_for_score branch shifts.
        self.assertAlmostEqual(r0.dps, r1.dps, places=4)
        expected_delta = r0.beta * (r0.ehp - r1.cc_blended_ehp)
        actual_delta = r0.hybrid_score - r1.hybrid_score
        self.assertAlmostEqual(expected_delta, actual_delta, places=4)

    def test_cc_blended_ehp_field_set_from_ehp_result(self) -> None:
        # The HybridResult.cc_blended_ehp field surfaces the value the
        # underlying EhpResult returned - not a recomputation.
        r_h = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana"),
        )
        r_e = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana"),
        )
        self.assertAlmostEqual(r_h.cc_blended_ehp, r_e.cc_blended_ehp, places=4)

    def test_enemy_champions_field_preserves_tuple_input(self) -> None:
        # The HybridResult.enemy_champions field carries the normalized
        # tuple verbatim (after str coercion).
        enemies = ("Annie", "Morgana", "Malzahar")
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies,
        )
        self.assertEqual(r.enemy_champions, enemies)

    def test_sr_mode_with_enemy_champions_still_changes_score(self) -> None:
        # ARAM tenacity multiplies in for ARAM/KIWI modes; SR is
        # identity tenacity=1.0 but the CC discount itself still
        # applies. The point: hybrid_score still moves in SR.
        r_baseline = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        r_with_cc = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",),
        )
        # Morgana Q 3.0s / 6s fight = 0.5 fraction * 0.5 factor = 25%
        # EHP loss. Score must decrease.
        self.assertLess(r_with_cc.hybrid_score, r_baseline.hybrid_score)


# ---------------------------------------------------- multi call site


class MultiCallSiteThreadingTests(unittest.TestCase):
    """The kwarg must reach every internal compute_ehp call site.

    compute_hybrid has 1 compute_ehp call; rank_items_by_hybrid has 2
    (baseline + per-candidate scored). Using unittest.mock.patch on the
    compute_ehp symbol in the hybrid module, we capture call kwargs and
    assert each one received the same enemy_champions tuple. This pins
    that future refactors of either function keep all 3 sites synced.
    """

    def test_compute_hybrid_call_site_receives_enemy_champions(self) -> None:
        enemies = ("Annie", "Morgana")
        # Use a wrapper so we capture-then-delegate to the real fn.
        original = compute_ehp
        captured: list[tuple] = []

        def spy(*args, **kwargs):
            captured.append((args, dict(kwargs)))
            return original(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            compute_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=enemies,
            )
        self.assertEqual(len(captured), 1)
        _args, kwargs = captured[0]
        self.assertEqual(kwargs.get("enemy_champions"), enemies)

    def test_rank_items_by_hybrid_baseline_call_site_receives_enemy(self) -> None:
        enemies = ("Annie",)
        original = compute_ehp
        captured: list[tuple] = []

        def spy(*args, **kwargs):
            captured.append((args, dict(kwargs)))
            return original(*args, **kwargs)

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            # only_item_ids=set() with include_components=False keeps
            # the candidate loop empty so only the baseline fires.
            rank_items_by_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                current_item_ids=(),
                mode="SR",
                enemy_champions=enemies,
                only_item_ids=(),
            )
        # First call is the baseline.
        self.assertGreaterEqual(len(captured), 1)
        _args, kwargs = captured[0]
        self.assertEqual(kwargs.get("enemy_champions"), enemies)

    def test_rank_items_by_hybrid_scored_call_sites_receive_enemy(self) -> None:
        # With a couple of candidates whitelisted via only_item_ids,
        # the inner loop fires - every scored compute_ehp must also
        # receive the same tuple.
        enemies = ("Morgana",)
        original = compute_ehp
        captured: list[tuple] = []

        def spy(*args, **kwargs):
            captured.append((args, dict(kwargs)))
            return original(*args, **kwargs)

        # 3053 Sterak's Gage + 3072 Bloodthirster are well-known
        # terminals; pick a small whitelist to keep the loop small.
        whitelist = ("3053", "3072")

        with patch("agents.daemon_slayer.hybrid.compute_ehp", side_effect=spy):
            rank_items_by_hybrid(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                current_item_ids=(),
                mode="SR",
                enemy_champions=enemies,
                only_item_ids=whitelist,
                top_n=10,
            )
        # At least one call beyond the baseline must fire.
        self.assertGreaterEqual(len(captured), 2)
        for _args, kwargs in captured:
            self.assertEqual(
                kwargs.get("enemy_champions"),
                enemies,
                msg="every compute_ehp call site must thread enemy_champions",
            )


# --------------------------------------------------- malformed inputs


class MalformedEnemyChampionsTests(unittest.TestCase):
    """Fail-soft contract on degenerate input shapes (matches compute_ehp)."""

    def test_none_entries_silently_skipped(self) -> None:
        # compute_cc_pressure handles ``if e`` filtering inside compute_ehp;
        # surfaces as cc_blended_ehp computed only over truthy entries.
        # Annie alone contributes 1.5s; (None, Annie, None) should match.
        # We can't compare to "Annie only" directly because compute_ehp's
        # ``if e`` filter applies per-entry inside the registry sum, so
        # this just pins the no-raise contract + nonzero pressure.
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=(None, "Annie", None),  # type: ignore[arg-type]
        )
        # None coerces to "None" via str() in our normalizer - so the
        # field carries the coerced values, but cc_blended_ehp depends on
        # the underlying registry where unknown ids contribute 0.0.
        # The test is: no exception raised, score still computable.
        self.assertIsInstance(r, HybridResult)
        self.assertEqual(len(r.enemy_champions), 3)

    def test_blank_string_entries_silently_skipped(self) -> None:
        # Blank strings -> compute_cc_pressure returns empty result for
        # unknown id; total pressure unchanged from "Annie only".
        r_blank = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("", "Annie", ""),
        )
        r_solo = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        # Both should produce the same cc_blended_ehp because blanks
        # contribute 0.0 to the pressure sum (matches compute_ehp).
        self.assertAlmostEqual(
            r_blank.cc_blended_ehp, r_solo.cc_blended_ehp, places=4
        )

    def test_unknown_champion_ids_silently_skipped(self) -> None:
        # Unknown champion ids contribute 0.0 to compute_cc_pressure
        # (matches the registry's "no entry = no CC" rule). The score
        # should equal the baseline + the single known champion's
        # contribution.
        r_unknown_only = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("UnknownChamp1", "UnknownChamp2"),
        )
        # Unknown-only -> 0 pressure -> identity to baseline.
        r_baseline = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertAlmostEqual(
            r_unknown_only.cc_blended_ehp, r_baseline.ehp, places=4
        )

    def test_tuple_and_list_both_accepted(self) -> None:
        enemies_tuple = ("Annie", "Morgana")
        enemies_list = ["Annie", "Morgana"]
        r_tuple = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies_tuple,
        )
        r_list = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies_list,
        )
        # Same iterable contents -> identical math.
        self.assertAlmostEqual(
            r_tuple.cc_blended_ehp, r_list.cc_blended_ehp, places=4
        )
        self.assertAlmostEqual(r_tuple.hybrid_score, r_list.hybrid_score, places=4)
        # Normalized to tuple-of-str regardless of input shape.
        self.assertEqual(r_tuple.enemy_champions, ("Annie", "Morgana"))
        self.assertEqual(r_list.enemy_champions, ("Annie", "Morgana"))


# ------------------------------------------------- HybridResult fields


class HybridResultFieldsTests(unittest.TestCase):
    """The 2 new HybridResult fields + their defaults + to_dict shape."""

    def test_default_field_values_on_empty_enemies(self) -> None:
        # cc_blended_ehp default is 0.0 in the dataclass def, but
        # compute_hybrid always populates it from ehp_result.cc_blended_ehp
        # (which equals blended_ehp by identity when empty). So the
        # default actually surfaces only on a directly-constructed
        # HybridResult (rare); compute_hybrid always sets it.
        r = compute_hybrid(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertEqual(r.cc_blended_ehp, r.ehp)
        self.assertEqual(r.enemy_champions, ())

    def test_to_dict_includes_new_fields(self) -> None:
        # The to_dict round-trip must carry the 2 new fields with the
        # right types (float + list-of-str).
        enemies = ("Annie", "Morgana")
        r = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies,
        )
        d = r.to_dict()
        self.assertIn("cc_blended_ehp", d)
        self.assertIn("enemy_champions", d)
        self.assertIsInstance(d["cc_blended_ehp"], float)
        self.assertIsInstance(d["enemy_champions"], list)
        self.assertEqual(d["enemy_champions"], ["Annie", "Morgana"])
        self.assertAlmostEqual(d["cc_blended_ehp"], r.cc_blended_ehp, places=4)

    def test_equality_between_two_results_with_same_inputs(self) -> None:
        # Frozen dataclass equality is field-by-field; same inputs ->
        # same result. (Not a HybridResult __eq__ override test per se;
        # the dataclass(frozen=True) default __eq__ covers it.)
        enemies = ("Annie", "Morgana")
        r1 = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies,
        )
        r2 = compute_hybrid(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=enemies,
        )
        self.assertEqual(r1, r2)


# --------------------------------------------------- engine version pin


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION to the current branch value (orchestrator bumps)."""

    def test_engine_version_is_current(self) -> None:
        # DO NOT change this string in this slice; the orchestrator
        # syncs all ENGINE pin sites at merge. Current pre-merge state
        # on main is 1.35.0.
        self.assertEqual(ENGINE_VERSION, "1.39.0")


# --------------------------------------------------- ASCII hygiene


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes, en-dashes, or smart quotes in the new code or test."""

    def _scan_file_for_bad_glyphs(self, path: pathlib.Path) -> list[tuple[int, str, str]]:
        """Return list of (line_no, glyph_name, line) for any bad glyphs."""
        # Build the bad-glyph dict via chr() so this test file itself
        # stays ASCII-clean against its own scan (the dict literal would
        # match itself otherwise).
        bad: dict[str, str] = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "left-double-quote",
            chr(0x201D): "right-double-quote",
            chr(0x2018): "left-single-quote",
            chr(0x2019): "right-single-quote",
        }
        findings: list[tuple[int, str, str]] = []
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

    def test_hybrid_module_has_no_smart_quotes_in_new_zone(self) -> None:
        # Scan the entire hybrid.py module; do NOT introduce any of the
        # 6 forbidden glyphs (em / en dashes + smart quotes).
        hybrid_path = (
            pathlib.Path(__file__).resolve().parent.parent / "hybrid.py"
        )
        findings = self._scan_file_for_bad_glyphs(hybrid_path)
        # NOTE: pre-existing non-ASCII bytes elsewhere in the module
        # are tolerated (e.g. the alpha/beta Greek letters in docstrings
        # were there before this slice). We only ban the 6 specific
        # glyphs above; the alpha/beta unicode chars are NOT in that
        # set. So findings must be empty.
        self.assertEqual(
            findings,
            [],
            msg=f"Bad glyphs in hybrid.py: {findings}",
        )


if __name__ == "__main__":
    unittest.main()
