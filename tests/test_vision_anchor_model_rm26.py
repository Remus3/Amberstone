"""RM-26 anchor model: scale-by-height plus a per-region anchor offset.

WHY THIS EXISTS. ``derive_scaled_regions`` uses one ratio per axis, so a
1920x1080 baseline stretched to an ultrawide base widens every box by
dst_w/1920 while League itself anchors most of the HUD to a screen EDGE and
scales it by HEIGHT. Measured best-anchor error against each region's own
true width: 16:9 2560x1440 exactly 0.00x, 21:9 median 0.45x max ~4.9x, 32:9
5120x1440 median 1.32x max 14.19x (LEDGER 1227).

WHAT IS PROVEN HERE AND WHAT IS NOT. The 16:9 identity below is validated
against real data - the operator's hand-calibrated 1080p baseline and the
2560x1440 reference stills in data/vision_calib_reference. The per-region
ANCHOR CLASSIFICATION is a model and is NOT validated: at 16:9 the width
ratio equals the height ratio, so left / center / right anchoring all produce
the byte-identical box and no 16:9 frame can discriminate between them. That
is why the anchor model is opt-in and why derive_profile still defaults to
the proportional path. One native full-screen 21:9 or 32:9 still is the only
thing that can settle the classification.
"""

import json
import unittest
from pathlib import Path

from core import vision_profiles as vp

_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_BASE = [1920, 1080]


def _real_regions() -> dict:
    """The operator's hand-calibrated 1080p baseline, read off disk."""
    return json.loads(
        (_ROOT / "data" / "vision_regions.json").read_text(encoding="utf-8")
    )


class TestAnchorClassification(unittest.TestCase):
    def test_every_real_region_has_an_explicit_anchor(self):
        missing = sorted(set(_real_regions()) - set(vp.REGION_ANCHORS))
        self.assertEqual([], missing)

    def test_registry_names_no_region_that_does_not_exist(self):
        extra = sorted(set(vp.REGION_ANCHORS) - set(_real_regions()))
        self.assertEqual([], extra)

    def test_anchor_values_are_from_the_declared_vocabulary(self):
        for name, (horiz, vert) in vp.REGION_ANCHORS.items():
            self.assertIn(horiz, ("left", "center", "right"), name)
            self.assertIn(vert, ("top", "bottom"), name)

    def test_unregistered_region_falls_back_to_geometric_thirds(self):
        # Fail-soft: a region added to the JSON without a registry entry must
        # still derive rather than raise.
        self.assertEqual(("left", "top"),
                         vp.classify_anchor("nope", [10, 10, 30, 30], _LEGACY_BASE))
        self.assertEqual(("right", "bottom"),
                         vp.classify_anchor("nope", [1800, 900, 1900, 1000],
                                            _LEGACY_BASE))
        self.assertEqual(("center", "top"),
                         vp.classify_anchor("nope", [940, 10, 980, 30],
                                            _LEGACY_BASE))


class TestSameAspectIsIdentity(unittest.TestCase):
    """The 16:9 half, validated against real regions and a real capture base."""

    def test_matches_proportional_scaling_on_every_real_region_at_2560x1440(self):
        regions = _real_regions()
        proportional = vp.derive_scaled_regions(regions, _LEGACY_BASE, [2560, 1440])
        anchored = vp.derive_anchored_regions(regions, _LEGACY_BASE, [2560, 1440])
        self.assertEqual(proportional, anchored)

    def test_2560x1440_is_a_base_we_actually_hold_reference_stills_for(self):
        # CAPABILITY skip, not a masked defect (LEDGER 1228 B5 rule):
        # data/vision_calib_reference/ is gitignored at .gitignore:315 and is
        # UNTRACKED by design - the stills are local operator captures, so a
        # clone has none and CI can never have any. Asserted where they exist
        # (Legion), skipped where they provably cannot.
        ref_dir = _ROOT / "data" / "vision_calib_reference"
        stills = list(ref_dir.glob("2560x1440_*.jpg")) if ref_dir.is_dir() else []
        if not stills:
            self.skipTest("no local calibration stills - gitignored capture dir")
        self.assertTrue(stills, "the 16:9 identity claim is anchored to real frames")

    def test_identity_holds_for_all_six_anchor_combinations(self):
        box = {"probe": [800, 400, 900, 460]}
        proportional = vp.derive_scaled_regions(box, _LEGACY_BASE, [3840, 2160])
        for horiz in ("left", "center", "right"):
            for vert in ("top", "bottom"):
                with self.subTest(anchor=(horiz, vert)):
                    out = vp.derive_anchored_regions(
                        box, _LEGACY_BASE, [3840, 2160],
                        anchors={"probe": (horiz, vert)})
                    self.assertEqual(proportional, out)


class TestVerticalAnchorIsArithmeticallyInert(unittest.TestCase):
    """A finding, not an omission. Under scale-by-height,
    dst_h - (src_h - y) * (dst_h/src_h) reduces to y * (dst_h/src_h), so a
    bottom anchor and a top anchor are the SAME map. The classification is
    kept because it documents intent and would matter under any future
    non-height-based vertical scale."""

    def test_top_and_bottom_agree_on_every_real_region_at_every_seed_base(self):
        regions = _real_regions()
        for base in vp.SEED_BASES:
            for name, box in regions.items():
                with self.subTest(base=tuple(base), region=name):
                    horiz = vp.REGION_ANCHORS[name][0]
                    top = vp.derive_anchored_regions(
                        {name: box}, _LEGACY_BASE, base,
                        anchors={name: (horiz, "top")})
                    bottom = vp.derive_anchored_regions(
                        {name: box}, _LEGACY_BASE, base,
                        anchors={name: (horiz, "bottom")})
                    self.assertEqual(top, bottom)


class TestAnchorOffsetOnUltrawide(unittest.TestCase):
    """The behaviour the model exists for. These pin the ARITHMETIC of the
    anchor map; they do not claim the per-region classification is correct."""

    def test_box_width_scales_by_height_not_by_width(self):
        # 5120x1440 from 1920x1080: height ratio 1.3333, width ratio 2.6667.
        # Proportional stretch doubles the box relative to the HUD art; the
        # anchor model keeps it at the height ratio.
        box = {"timer": [1857, 4, 1903, 26]}
        src_w = 1903 - 1857
        anchored = vp.derive_anchored_regions(box, _LEGACY_BASE, [5120, 1440])
        l, _t, r, _b = anchored["timer"]
        self.assertEqual(int(src_w * (1440 / 1080)), r - l)

        proportional = vp.derive_scaled_regions(box, _LEGACY_BASE, [5120, 1440])
        pl, _, pr, _ = proportional["timer"]
        self.assertGreater(pr - pl, r - l)

    def test_right_anchored_region_keeps_its_distance_from_the_right_edge(self):
        # Tolerance is 1px, not sloppiness: the derived coordinate is
        # int()-truncated as a whole, the same convention derive_scaled_regions
        # and _scale_bbox use, so the recovered gap can sit one pixel wide.
        box = {"timer": [1857, 4, 1903, 26]}
        gap = 1920 - 1903
        anchored = vp.derive_anchored_regions(box, _LEGACY_BASE, [5120, 1440])
        self.assertLess(abs((5120 - anchored["timer"][2]) - gap * (1440 / 1080)), 1)
        # And decisively NOT the proportional answer, which lands ~45px out.
        proportional = vp.derive_scaled_regions(box, _LEGACY_BASE, [5120, 1440])
        self.assertGreater(5120 - proportional["timer"][2], 40)

    def test_left_anchored_region_keeps_its_distance_from_the_left_edge(self):
        box = {"ally_1_hp": [11, 225, 57, 234]}
        anchored = vp.derive_anchored_regions(box, _LEGACY_BASE, [5120, 1440])
        self.assertEqual(int(11 * (1440 / 1080)), anchored["ally_1_hp"][0])

    def test_center_anchored_region_stays_centred(self):
        # A box symmetric about the 1080p midline must stay symmetric about
        # the destination midline.
        box = {"hp": [910, 1044, 1010, 1059]}
        anchored = vp.derive_anchored_regions(box, _LEGACY_BASE, [5120, 1440],
                                              anchors={"hp": ("center", "bottom")})
        # 1px tolerance for the same int() truncation reason as above: both
        # edges truncate downward, so a symmetric pair can land 1px off.
        l, _t, r, _b = anchored["hp"]
        self.assertLessEqual(abs((5120 - r) - l), 1)

    def test_never_mutates_the_input_map(self):
        regions = _real_regions()
        before = json.dumps(regions, sort_keys=True)
        vp.derive_anchored_regions(regions, _LEGACY_BASE, [3440, 1440])
        self.assertEqual(before, json.dumps(regions, sort_keys=True))

    def test_skips_a_malformed_box_like_the_proportional_path(self):
        out = vp.derive_anchored_regions(
            {"good": [1, 2, 3, 4], "bad": [1, 2, 3]}, _LEGACY_BASE, [3440, 1440])
        self.assertEqual(["good"], list(out))


class TestDefaultsAreUnchanged(unittest.TestCase):
    """DEFAULT-OFF. The classification is unvalidated, so nothing on the
    served OCR path may adopt it until a real ultrawide frame exists."""

    def test_derive_profile_still_uses_proportional_scaling_by_default(self):
        prof = vp.derive_profile([3440, 1440], source_regions=_real_regions())
        expected = vp.derive_scaled_regions(_real_regions(), _LEGACY_BASE,
                                            [3440, 1440])
        self.assertEqual(expected, prof["regions"])
        self.assertEqual("derived", prof["source"])

    def test_derive_profile_adopts_the_anchor_model_only_when_asked(self):
        prof = vp.derive_profile([3440, 1440], source_regions=_real_regions(),
                                 anchor_model=True)
        expected = vp.derive_anchored_regions(_real_regions(), _LEGACY_BASE,
                                              [3440, 1440])
        self.assertEqual(expected, prof["regions"])
        self.assertEqual("derived_anchored", prof["source"])

    def test_anchor_model_changes_at_least_one_box_on_an_ultrawide_base(self):
        # Guards against the RM-26 failure mode where the "fix" was
        # arithmetically inert on every crop.
        regions = _real_regions()
        proportional = vp.derive_scaled_regions(regions, _LEGACY_BASE, [3440, 1440])
        anchored = vp.derive_anchored_regions(regions, _LEGACY_BASE, [3440, 1440])
        differing = [k for k in regions if proportional[k] != anchored[k]]
        self.assertTrue(differing)

    def test_seed_profiles_still_writes_proportional_seeds(self):
        # seed_profiles has no anchor_model knob on purpose: seeds land on
        # disk and are promotable to a calibration by an operator clicking
        # Save, so an unvalidated model must not reach them.
        import inspect
        self.assertNotIn("anchor_model",
                         inspect.signature(vp.seed_profiles).parameters)


if __name__ == "__main__":
    unittest.main()
