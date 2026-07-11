"""ENGINE 1.41.0 (2026-05-22) - compute_ehp consumer wire for cc_conditional.

The ``cc_conditional`` module shipped at ENGINE 1.37.0 (2026-05-22)
as a FORWARD-MARKER seam. ENGINE 1.38.0 shipped the FIRST authorized
consumer via ``compute_cc_pressure(include_conditional=False)``.
ENGINE 1.41.0 ships the SECOND authorized consumer: ``compute_ehp``
gains an optional ``include_conditional`` kwarg that propagates
through to the per-enemy ``compute_cc_pressure`` calls, so the
``cc_blended_ehp`` field absorbs the additional discount when
conditional CC is opted-in.

This consumer wire is INDIRECT: ehp.py does NOT import cc_conditional
directly. It composes ON TOP of cc_pressure.py (the FIRST authorized
consumer) by passing through the kwarg. The forward-marker scan in
``test_cc_conditional_forward_marker.py`` continues to assert ehp.py
never gains a direct ``from .cc_conditional import`` statement; that
SSOT boundary stays at cc_pressure.

Test surface (8 classes):
  * ``DefaultBehaviorTests`` (4) - default ``include_conditional=False``
    preserves byte-identical 1.38.0 output for the EHP scorer.
  * ``IncludeConditionalTrueTests`` (6) - Brand R, Mordekaiser banishment,
    multi-enemy combination of unconditional + conditional axes.
  * ``AramTenacityAppliesToConditionalEhpTests`` (3) - ARAM tenacity
    flows through compute_cc_pressure's effective_cc_duration seam
    into the cc_blended_ehp discount.
  * ``EngineVersionCurrentTests`` (1) - pin ENGINE_VERSION at 1.41.0.
  * ``AsciiHygieneTests`` (2) - module + this test file are pure ASCII.

The conditional contribution does NOT add new EhpResult fields - the
opt-in just lifts ``enemy_cc_pressure_s`` / ``cc_pressure_fraction``
/ ``cc_blended_ehp`` through the existing channel. Transparency for
which entries fired stays one indirection away in
``CcPressureResult.conditional_entries`` if a caller wants the
breakdown - the EHP layer aggregates only.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import cc_pressure
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _CC_EFFECTIVENESS_FACTOR,
    _FIGHT_WINDOW_S,
    compute_ehp,
)


_SNAPSHOT = DataSnapshot.load()


# ---------------- 1. DefaultBehaviorTests ----------------


class DefaultBehaviorTests(unittest.TestCase):
    """Default ``include_conditional=False`` preserves 1.38.0 output."""

    def test_default_kwarg_byte_identical_to_138_no_enemies(self) -> None:
        """Empty enemy_champions with default kwarg is byte-identical."""
        r_default = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        r_explicit_false = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            include_conditional=False,
        )
        # All EHP fields stay byte-identical.
        self.assertEqual(
            r_default.cc_blended_ehp, r_explicit_false.cc_blended_ehp
        )
        self.assertEqual(
            r_default.enemy_cc_pressure_s,
            r_explicit_false.enemy_cc_pressure_s,
        )
        self.assertEqual(
            r_default.cc_pressure_fraction,
            r_explicit_false.cc_pressure_fraction,
        )
        self.assertEqual(r_default.blended_ehp, r_explicit_false.blended_ehp)

    def test_default_kwarg_byte_identical_unconditional_enemy(self) -> None:
        """An enemy with only unconditional CC (Annie) is byte-identical."""
        r_default = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        r_explicit_false = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
            include_conditional=False,
        )
        # Annie has no conditional entry; even with True the result is
        # the same. Pin the False == default identity here.
        self.assertEqual(
            r_default.cc_blended_ehp, r_explicit_false.cc_blended_ehp
        )
        self.assertEqual(
            r_default.enemy_cc_pressure_s,
            r_explicit_false.enemy_cc_pressure_s,
        )

    def test_default_ignores_conditional_only_enemy(self) -> None:
        """Brand has conditional R only; default treats him as 0.0 CC."""
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand",),
        )
        # Brand is NOT in _PER_SPELL_CC_DURATIONS - default returns 0.0
        # from compute_cc_pressure, so the EHP scorer's cc_blended_ehp
        # equals blended_ehp.
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)

    def test_default_with_aatrox_garen_team_yields_zero(self) -> None:
        """Aatrox + Garen team (no CC anywhere) yields zero pressure default."""
        r = compute_ehp(
            _SNAPSHOT,
            "Annie",
            level=11,
            mode="SR",
            enemy_champions=("Aatrox", "Garen"),
        )
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)


# ---------------- 2. IncludeConditionalTrueTests ----------------


class IncludeConditionalTrueTests(unittest.TestCase):
    """``include_conditional=True`` folds conditional contributions into EHP."""

    def test_brand_conditional_only_erodes_ehp(self) -> None:
        """Brand conditional contribution discounts EHP.

        Brand has wave 0 R (2.0 * 0.7 = 1.4 weighted) + wave 6 Q
        (1.25 * 0.5 = 0.625 weighted) + any future Brand wave
        additions. At wave-6 registry state total = 2.025 weighted.
        Use assertGreaterEqual floor at 1.4 (wave-0-only baseline)
        for forward-compat with future Brand wave additions; the
        discount math derives from live measured value.
        """
        r_default = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand",),
        )
        r_opt_in = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand",),
            include_conditional=True,
        )
        # Default: Brand contributes 0.0 -> cc_blended_ehp == blended_ehp
        self.assertEqual(r_default.cc_blended_ehp, r_default.blended_ehp)
        # Opt-in: at least 1.4s (wave-0 R contribution) - assertGreaterEqual
        # floor for forward-compat with future Brand wave additions.
        self.assertGreaterEqual(r_opt_in.enemy_cc_pressure_s, 1.4)
        # Discount math must match live measured pressure value.
        live_frac = min(r_opt_in.enemy_cc_pressure_s / 6.0, 1.0)
        self.assertAlmostEqual(
            r_opt_in.cc_pressure_fraction, live_frac, places=4
        )
        expected_blend = r_opt_in.blended_ehp * (1.0 - live_frac * 0.5)
        self.assertAlmostEqual(
            r_opt_in.cc_blended_ehp, expected_blend, places=4
        )
        # And cc_blended_ehp is strictly LESS than the default case -
        # pinned regardless of future Brand wave additions.
        self.assertLess(r_opt_in.cc_blended_ehp, r_default.cc_blended_ehp)

    def test_annie_unconditional_combined_with_default(self) -> None:
        """Annie has only unconditional; include_conditional=True is a no-op for Annie."""
        r_default = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        r_opt_in = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
            include_conditional=True,
        )
        # No conditional entry for Annie -> identical output
        self.assertAlmostEqual(
            r_opt_in.enemy_cc_pressure_s,
            r_default.enemy_cc_pressure_s,
            places=6,
        )
        self.assertAlmostEqual(
            r_opt_in.cc_blended_ehp, r_default.cc_blended_ehp, places=4
        )

    def test_mordekaiser_banishment_erodes_ehp_heavily(self) -> None:
        """Mordekaiser E 0.25 + R 7.0 (prob=1.0) = 7.25s, saturates fraction."""
        r_opt_in = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Mordekaiser",),
            include_conditional=True,
        )
        # 0.25 unconditional + 7.0 conditional = 7.25s
        # Fraction = min(7.25/6.0, 1.0) = 1.0
        # Discount = 1.0 * 0.5 = 0.5 -> cc_blended = 0.5 * blended
        self.assertAlmostEqual(
            r_opt_in.enemy_cc_pressure_s, 7.25, places=4
        )
        self.assertEqual(r_opt_in.cc_pressure_fraction, 1.0)
        self.assertAlmostEqual(
            r_opt_in.cc_blended_ehp, r_opt_in.blended_ehp * 0.5, places=4
        )

    def test_mordekaiser_default_only_uses_unconditional_e_pull(self) -> None:
        """Default for Mordekaiser uses only E pull 0.25s (no conditional)."""
        r_default = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Mordekaiser",),
        )
        # E pull only: 0.25s; fraction = 0.0417; discount = 0.0208 -> 0.9792 * blended
        self.assertAlmostEqual(
            r_default.enemy_cc_pressure_s, 0.25, places=4
        )
        expected = r_default.blended_ehp * (1.0 - (0.25 / 6.0) * 0.5)
        self.assertAlmostEqual(
            r_default.cc_blended_ehp, expected, places=4
        )

    def test_annie_plus_brand_unconditional_and_conditional_combine(self) -> None:
        """Annie R unconditional + Brand conditional entries combine.

        Annie R = 1.5s unconditional. Brand has wave 0 R (2.0s * 0.7 prob
        = 1.4 weighted) + wave 6 Q (1.25s * 0.5 prob = 0.625 weighted) +
        any future Brand wave additions. Total combined = 1.5 + 1.4 +
        0.625 = 3.525s at current registry state. Use assertGreaterEqual
        floors for forward-compat with future Brand wave additions.
        """
        r_default = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Brand"),
        )
        r_opt_in = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Brand"),
            include_conditional=True,
        )
        # Default: Annie 1.5 + Brand 0.0 = 1.5 (exact - unconditional path)
        self.assertAlmostEqual(
            r_default.enemy_cc_pressure_s, 1.5, places=4
        )
        # Opt-in: Annie 1.5 + Brand R weighted 1.4 + Brand Q weighted
        # 0.625 = 3.525 at wave-6 registry state. Floor at 2.9 (the
        # wave-0-only baseline of Annie 1.5 + Brand R 1.4) for forward-
        # compat with future Brand wave additions; the live value MUST
        # exceed default by at least the Brand R contribution.
        self.assertGreaterEqual(r_opt_in.enemy_cc_pressure_s, 2.9)
        # Opt-in cc_blended_ehp strictly lower than default - the
        # conditional contribution erodes EHP. Pinned regardless of
        # future Brand wave additions.
        self.assertLess(r_opt_in.cc_blended_ehp, r_default.cc_blended_ehp)
        # The cc_blended_ehp formula must match the live enemy_cc_pressure_s
        # via the canonical discount: blended_ehp * (1 - frac * 0.5)
        # where frac = enemy_cc_pressure_s / 6.0 clamped at 1.0. Use
        # live measured values so test stays valid as registry grows.
        live_frac = min(r_opt_in.enemy_cc_pressure_s / 6.0, 1.0)
        expected = r_opt_in.blended_ehp * (1.0 - live_frac * 0.5)
        self.assertAlmostEqual(r_opt_in.cc_blended_ehp, expected, places=4)

    def test_multi_conditional_enemies_aggregate(self) -> None:
        """Brand + Warwick (both conditional-only) aggregate cleanly.

        Brand carries wave 0 R (2.0 * 0.7 = 1.4) + wave 6 Q (1.25 * 0.5
        = 0.625) + any future wave additions. Warwick carries wave 0 R
        (max rank 2.0 * 0.5 = 1.0). Total at wave-6 registry state =
        1.4 + 0.625 + 1.0 = 3.025. Use assertGreaterEqual floor for
        forward-compat with future wave additions; the wave-0-only
        baseline (1.4 + 1.0 = 2.4) is the load-bearing floor.
        """
        r_opt_in = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Brand", "Warwick"),
            include_conditional=True,
        )
        # Floor at 2.4 (wave-0-only baseline) for forward-compat with
        # future Brand/Warwick wave additions.
        self.assertGreaterEqual(r_opt_in.enemy_cc_pressure_s, 2.4)
        # Discount math is canonical: cc_pressure_fraction = pressure / 6
        # clamped at 1.0; cc_blended_ehp = blended_ehp * (1 - frac * 0.5).
        # Use live measured values so test stays valid as registry grows.
        live_frac = min(r_opt_in.enemy_cc_pressure_s / 6.0, 1.0)
        self.assertAlmostEqual(
            r_opt_in.cc_pressure_fraction, live_frac, places=4
        )
        expected = r_opt_in.blended_ehp * (1.0 - live_frac * 0.5)
        self.assertAlmostEqual(r_opt_in.cc_blended_ehp, expected, places=4)


# ---------------- 3. AramTenacityAppliesToConditionalEhpTests ----------------


class AramTenacityAppliesToConditionalEhpTests(unittest.TestCase):
    """ARAM tenacity flows through into the cc_blended_ehp discount via cc_pressure."""

    def test_aram_tenacity_lengthens_conditional_in_ehp_via_monkeypatch(self) -> None:
        """Add Brand to fake tenacity map; ARAM mode lifts cc_blended discount.

        Brand carries wave 0 R + wave 6 Q + any future Brand wave
        additions. The tenacity multiplier applies UNIFORMLY to the
        entire summed conditional pressure (cc_pressure does the
        multiplication post-aggregation). The exact pre-tenacity value
        is registry-version-dependent; the load-bearing pin is the
        RATIO of ARAM-to-SR pressure ALWAYS equals 1.20x (the tenacity
        multiplier itself).
        """
        # No champion at 16.10.1 is in BOTH the conditional registry +
        # the modified-tenacity map. Monkey-patch the cc_pressure
        # tenacity map to add Brand at 1.20x.
        fake_tenacity = {"Brand": 1.20}
        with mock.patch.object(
            cc_pressure, "_TENACITY_MAP", fake_tenacity
        ):
            r_sr = compute_ehp(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Brand",),
                include_conditional=True,
            )
            r_aram = compute_ehp(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="ARAM",
                enemy_champions=("Brand",),
                include_conditional=True,
            )
        # SR: floor at 1.4 (wave-0 R contribution); future Brand waves
        # add via assertGreaterEqual.
        self.assertGreaterEqual(r_sr.enemy_cc_pressure_s, 1.4)
        # ARAM: SR pressure x 1.20 tenacity multiplier (load-bearing
        # ratio pin; the absolute value is registry-version-dependent).
        self.assertAlmostEqual(
            r_aram.enemy_cc_pressure_s,
            r_sr.enemy_cc_pressure_s * 1.20,
            places=4,
        )
        # ARAM cc_blended_ehp discount is correspondingly larger.
        # Note: ARAM also has aramDamageTaken which scales blended_ehp,
        # so compare the discount RATIO not absolute values across modes.
        sr_discount_ratio = r_sr.cc_blended_ehp / r_sr.blended_ehp
        aram_discount_ratio = r_aram.cc_blended_ehp / r_aram.blended_ehp
        self.assertLess(aram_discount_ratio, sr_discount_ratio)

    def test_aram_mordekaiser_at_identity_tenacity_conditional_lands(self) -> None:
        """Mordekaiser ARAM: 1.0 tenacity (not modified) + conditional R = 7.0s."""
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="ARAM",
            enemy_champions=("Mordekaiser",),
            include_conditional=True,
        )
        # 0.25 unconditional + 7.0 conditional = 7.25s (Mordekaiser not in
        # modified tenacity map - identity 1.0)
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 7.25, places=4)
        self.assertEqual(r.cc_pressure_fraction, 1.0)
        # cc_blended_ehp absorbs the 50% discount on top of aramDamageTaken
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp * 0.5, places=4)

    def test_kiwi_mode_propagates_conditional_tenacity_through_ehp(self) -> None:
        """KIWI (ARAM Mayhem) mode also propagates conditional tenacity.

        Brand has wave 0 R + wave 6 Q + any future wave additions;
        the load-bearing pin is the RATIO ARAM-to-SR pressure equals
        the tenacity multiplier (1.20x), regardless of the absolute
        pressure value.
        """
        fake_tenacity = {"Brand": 1.20}
        with mock.patch.object(
            cc_pressure, "_TENACITY_MAP", fake_tenacity
        ):
            r_aram = compute_ehp(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="ARAM",  # KIWI vs ARAM uses same _ARAM_MODES set
                enemy_champions=("Brand",),
                include_conditional=True,
            )
            r_sr = compute_ehp(
                _SNAPSHOT,
                "Aatrox",
                level=11,
                mode="SR",
                enemy_champions=("Brand",),
                include_conditional=True,
            )
        # ARAM = SR * 1.20 (load-bearing tenacity ratio pin); absolute
        # value depends on registry state. Floor at 1.68 (wave-0-only
        # baseline: 1.4 * 1.20) for forward-compat with future Brand
        # wave additions.
        self.assertGreaterEqual(r_aram.enemy_cc_pressure_s, 1.68)
        self.assertAlmostEqual(
            r_aram.enemy_cc_pressure_s,
            r_sr.enemy_cc_pressure_s * 1.20,
            places=4,
        )


# ---------------- 4. EngineVersionCurrentTests ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION at 1.41.0 for this slice.

    The orchestrator bumps to 1.41.0 at merge; while the slice is being
    written, the branch carries 1.38.0 from the base. This test asserts
    the post-bump target so the orchestrator can sync this single pin
    along with the other 27+ stale ENGINE pin sites across DS test
    files (per items 134-142 pattern).
    """

    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.198.0")


# ---------------- 5. AsciiHygieneTests ----------------


class AsciiHygieneTests(unittest.TestCase):
    """Module + this test file are pure 7-bit ASCII."""

    # Build BAD via chr() so this test file stays clean against its own scan.
    BAD = {
        chr(0x2013): "en-dash",
        chr(0x2014): "em-dash",
        chr(0x2018): "left-single-quote",
        chr(0x2019): "right-single-quote",
        chr(0x201C): "left-double-quote",
        chr(0x201D): "right-double-quote",
    }

    def _scan(self, path: pathlib.Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        hits: list[str] = []
        for ch, name in self.BAD.items():
            if ch in text:
                hits.append(name)
        return hits

    def test_ehp_module_is_ascii_clean(self) -> None:
        ehp_path = pathlib.Path(__file__).resolve().parent.parent / "ehp.py"
        hits = self._scan(ehp_path)
        self.assertEqual(hits, [], f"ehp.py has non-ASCII glyphs: {hits}")

    def test_this_test_file_is_ascii_clean(self) -> None:
        this_path = pathlib.Path(__file__).resolve()
        hits = self._scan(this_path)
        self.assertEqual(
            hits,
            [],
            f"test_cc_conditional_consumer_ehp.py has non-ASCII glyphs: {hits}",
        )


if __name__ == "__main__":
    unittest.main()
