"""s-PGR-S2 (#9) - /api/dictionary/augments.

The Post Game Review roster needs per-player augment icons (ARAM
Mayhem / Arena). This endpoint serves a compact
id -> {name, icon_url, rarity} map built from the patch-versioned
cherry_augments.json snapshot (the same table
core.augment_external_source consumes), transforming the stored LCU
virtual asset path into a fetchable CommunityDragon raw URL.

The serve tests use a stub HTTP handler that captures _send (same
pattern as test_routes_ds_preview_scorer); no live server needed.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from dashboard import routes_dictionary as rd


class _Handler:
    """Stub HTTP handler capturing _send(status, body, content_type, cache_control)."""

    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.content_type = ""
        self.cache_control: str | None = None

    def _send(self, status: int, body: bytes, content_type: str,
              cache_control: str | None = None) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type
        self.cache_control = cache_control

    def json(self) -> dict:
        return json.loads(self.body.decode())


class CdragonIconUrlTests(unittest.TestCase):
    def test_lcu_virtual_path_transforms_to_cdragon_mirror(self):
        out = rd._cdragon_icon_url(
            "/lol-game-data/assets/ASSETS/UX/Cherry/Augments/Icons/ADAPt_small.png"
        )
        self.assertEqual(
            out,
            "https://raw.communitydragon.org/latest/plugins/"
            "rcp-be-lol-game-data/global/default/"
            "assets/assets/ux/cherry/augments/icons/adapt_small.png",
        )

    def test_empty_in_empty_out(self):
        self.assertEqual(rd._cdragon_icon_url(""), "")
        self.assertEqual(rd._cdragon_icon_url(None), "")

    def test_already_relative_path_still_prefixed_and_lowered(self):
        out = rd._cdragon_icon_url("Assets/UX/Foo_small.PNG")
        self.assertTrue(out.startswith(rd._CDRAGON_GAMEDATA_BASE))
        self.assertTrue(out.endswith("assets/ux/foo_small.png"))


class ServeAugmentsTests(unittest.TestCase):
    def test_happy_path_serves_compact_map(self):
        h = _Handler()
        rd._serve_augments(h)
        self.assertEqual(h.status, 200)
        self.assertIn("application/json", h.content_type)
        payload = h.json()
        self.assertIn("augments", payload)
        self.assertIn("patch", payload)
        augs = payload["augments"]
        self.assertGreater(len(augs), 100)  # cherry set is ~554
        # Every row is the compact shape; icon_url is a CDragon URL.
        sample_id = next(iter(augs))
        row = augs[sample_id]
        self.assertEqual(set(row.keys()), {"name", "rarity", "icon_url"})
        self.assertTrue(row["icon_url"].startswith(rd._CDRAGON_GAMEDATA_BASE))

    def test_missing_patch_dir_404(self):
        h = _Handler()
        with mock.patch.object(rd, "_current_ds_patch", return_value="99.99.99"):
            rd._serve_augments(h)
        self.assertEqual(h.status, 404)

    def test_no_patch_resolved_404(self):
        h = _Handler()
        with mock.patch.object(rd, "_current_ds_patch", return_value=""):
            rd._serve_augments(h)
        self.assertEqual(h.status, 404)


class CacheControlTests(unittest.TestCase):
    """Patch-pinned DDragon dumps + cherry_augments rarely change between
    operator-triggered refreshes. The dictionary routes opt out of the
    default `no-store` and serve `public, max-age=86400, immutable` so
    the browser can short-circuit subsequent loads. Saves a measurable
    number of /api/dictionary/* hits per dashboard session."""

    def test_serve_augments_sets_long_cache(self):
        h = _Handler()
        rd._serve_augments(h)
        self.assertEqual(h.status, 200)
        self.assertEqual(h.cache_control, rd._DICT_CACHE_CONTROL)
        self.assertIn("max-age=86400", h.cache_control)
        self.assertIn("immutable", h.cache_control)

    def test_serve_champion_tags_sets_long_cache(self):
        h = _Handler()
        rd._serve_champion_tags(h)
        if h.status == 200:
            self.assertEqual(h.cache_control, rd._DICT_CACHE_CONTROL)

    def test_constant_value(self):
        self.assertEqual(
            rd._DICT_CACHE_CONTROL,
            "public, max-age=86400, immutable",
        )


class ChampionDamageProfileTests(unittest.TestCase):
    """tag1 = the enemy cell's damage-profile chip. Regression (operator-reported
    2026-06-30): Seraphine's DDragon info block is zeroed, so the old
    attack>=magic tie (0>=0) defaulted her to AD. Zero-info champs now fall back
    to their role tags; valid-info champs keep the attack/magic decision."""

    def test_zero_info_mage_support_is_ap(self):
        # Seraphine: zeroed info + Support/Mage tags -> AP (the reported fix).
        self.assertEqual(
            rd._damage_profile_tag("Seraphine", ["Support", "Mage"], 0, 0), "AP")

    def test_zero_info_marksman_is_ad(self):
        # Akshan: zeroed info + Marksman tag -> AD (fallback keeps ADCs AD).
        self.assertEqual(
            rd._damage_profile_tag("Akshan", ["Marksman", "Assassin"], 0, 0), "AD")

    def test_valid_info_ap_mage_with_marksman_tag_unchanged(self):
        # Azir carries a secondary Marksman tag but magic>attack -> stays AP;
        # a tag-first rule would have wrongly flipped him to AD.
        self.assertEqual(
            rd._damage_profile_tag("Azir", ["Mage", "Marksman"], 6, 8), "AP")

    def test_valid_info_ad_marksman_unchanged(self):
        self.assertEqual(
            rd._damage_profile_tag("Ezreal", ["Marksman", "Mage"], 7, 6), "AD")

    def test_cc_override_wins_over_ratings(self):
        self.assertEqual(
            rd._damage_profile_tag("Thresh", ["Support", "Fighter"], 6, 4), "CC")

    def test_burst_override_wins_over_ratings(self):
        self.assertEqual(
            rd._damage_profile_tag("Zed", ["Assassin"], 8, 2), "BURST")


class RouteRegistrationTests(unittest.TestCase):
    def test_augments_route_registered(self):
        matchers = [m for (m, _fn) in rd.GET_ROUTES]
        self.assertTrue(
            any(m("/api/dictionary/augments") for m in matchers),
            "/api/dictionary/augments not in GET_ROUTES",
        )

    def test_augments_route_bound_to_serve_augments(self):
        for m, fn in rd.GET_ROUTES:
            if m("/api/dictionary/augments"):
                self.assertIs(fn, rd._serve_augments)
                return
        self.fail("route not found")


if __name__ == "__main__":
    unittest.main()
