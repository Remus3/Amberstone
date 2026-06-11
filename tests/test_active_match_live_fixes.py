"""Active Match live-game fixes (operator 2026-06-10) - characterization.

Pins the three operator-reported defects on the Active Match view,
characterized from the 2026-06-10 ARAM-Mayhem game's final snapshot
(data/aram_coaching_data.json: champion=Viktor level=18 items=null
items_display="Rod of Ages, Shadowflame, ..." - six finished legendaries):

1. DS ENGINE + SPIKE PIPS read ``p.items`` - a field live coach payloads
   NEVER carry (the owned-items field is ``items_display``, a comma-joined
   display-NAME string; ``items`` exists only in the ui_mock fixtures,
   which is why page audits never caught it). Result live: the DS rerank
   POSTed an empty inventory all game and the item pips counted 0 finished
   items (frozen at "first item" NEXT while six legendaries were owned).
   Fix: active_match.js extracts numeric ids from the liveclient block
   (slot >= 6 trinket excluded), falls back to resolving items_display
   names through the ITEMS index, and derives the finished-item count from
   ITEM_COSTS gold (>= 2000g) instead of min(len(items), 3).

2. Champion canonicalization: the coach payload champion is a Live Client
   DISPLAY name ("Tahm Kench"); DS registries key canonical DDragon ids
   ("TahmKench"). /api/spike-markers, /api/ds-preview and /api/ds-combo
   now bridge via core.archetype_picks.canonical_champion_id (canonical
   ids pass through unchanged - champ-select callers unaffected).

3. MAP pane rendered nothing live in ARAM/Mayhem: the status text + any
   per-enemy signal sat behind an ``img.naturalWidth`` guard and the
   shared-vision branch drew nothing per-enemy (Live Client emits
   position "NONE" - no coordinates exist). The text layers (ticking
   game clock + per-enemy roster with respawn / MIA / zone chips) now
   update independent of the base image; coordinate dots stay gated on
   real positions (no fabricated coordinates).

4. CDS rail: visual-only hide on the dashboard grid ("remove a field" is
   visual-only). JS / route / payload wiring stays; the overlay threat
   panelset (which re-shows .am-pane-cd with !important) is untouched.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ACTIVE_MATCH_JS = WEB / "js" / "panels" / "active_match.js"
ACTIVE_MATCH_CSS = WEB / "css" / "panels" / "active_match.css"
OVERLAY_CSS = WEB / "css" / "overlay.css"
INDEX_HTML = WEB / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class _SendStub:
    """Captures route _send calls (mirrors test_routes_spike_markers)."""

    def __init__(self, path: str = "") -> None:
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body

    def parsed(self) -> dict:
        return json.loads((self.last_body or b"{}").decode("utf-8"))


# ---------------------------------------------------------------------------
# 2. Champion canonicalization at the three DS route entries
# ---------------------------------------------------------------------------

class SpikeMarkersCanonicalChampionTests(unittest.TestCase):
    """Display-name champion resolves to the canonical DDragon id."""

    def setUp(self) -> None:
        from dashboard import routes_spike_markers as rt
        rt._reset_caches()
        self.rt = rt

    def _get(self, path: str) -> _SendStub:
        h = _SendStub(path=path)
        self.rt._serve_spike_markers(h)
        return h

    def test_display_name_is_canonicalized(self) -> None:
        h = self._get(
            "/api/spike-markers?champion=Tahm%20Kench&level=8&item_count=1")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["champion"], "TahmKench")

    def test_canonical_id_passes_through(self) -> None:
        h = self._get("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["champion"], "Jinx")


class DsPreviewCanonicalChampionTests(unittest.TestCase):
    """The dispatcher receives the canonical id, not the display name."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_display_name_is_canonicalized(self, mock_arch, mock_disp) -> None:
        from dashboard.routes_state import _serve_ds_preview_post
        mock_arch.return_value = {"primary": "tank"}
        mock_disp.return_value = {
            "ok": True, "scorer": "ehp", "archetype": "tank", "ranked": [],
        }
        h = _SendStub()
        _serve_ds_preview_post(
            h, {"champion": "Tahm Kench", "mode": "ARAM", "level": 12})
        self.assertEqual(h.last_status, 200)
        self.assertTrue(mock_disp.called)
        self.assertEqual(
            mock_disp.call_args.kwargs.get("champion"), "TahmKench")


class DsComboCanonicalChampionTests(unittest.TestCase):
    """The combo compute receives the canonical id."""

    def test_display_name_is_canonicalized(self) -> None:
        from dashboard import routes_ds_combo as rt
        rt._reset_caches()
        seen: dict = {}

        def _fake_compute(champion, *args, **kwargs):
            seen["champion"] = champion
            return {"ok": True, "champion": champion, "hits": [],
                    "totals": {"total_raw": 0.0, "total_mitigated": 0.0,
                               "duration_s": 0.0},
                    "count": 0}

        with mock.patch.object(rt, "_compute", side_effect=_fake_compute):
            h = _SendStub(path="/api/ds-combo?champion=Tahm%20Kench&seq=Q,W")
            rt._serve_ds_combo(h)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(seen.get("champion"), "TahmKench")


# ---------------------------------------------------------------------------
# 1. Owned-items extraction + finished-item count (frontend source pins)
# ---------------------------------------------------------------------------

class OwnedItemsExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(ACTIVE_MATCH_JS)

    def test_dead_p_items_read_removed(self) -> None:
        # The exact expression that pinned the bug: live payloads have no
        # `items` array, so this read produced [] for the whole game.
        self.assertNotIn("Array.isArray(p.items) ? p.items : []", self.src)

    def test_owned_ids_helper_defined_and_wired(self) -> None:
        self.assertIn("function _amOwnedItemIds(", self.src)
        self.assertIn("_amOwnedItemIds(p, lc)", self.src)

    def test_items_display_fallback_present(self) -> None:
        self.assertIn("items_display", self.src)

    def test_imports_item_costs_and_resolvers(self) -> None:
        m = re.search(r"import\s*\{([^}]*)\}\s*from '\.\./lib/items_index\.js'",
                      self.src)
        self.assertIsNotNone(m, "items_index import missing")
        names = m.group(1)
        for needed in ("ITEM_COSTS", "_resolveItemId", "_splitItemList"):
            self.assertIn(needed, names)

    def test_completed_count_replaces_min_len_proxy(self) -> None:
        # min(len, 3) counted boots/potions/components as finished
        # legendaries; the completed count keys on ITEM_COSTS gold.
        self.assertNotIn("Math.min(items.length, 3)", self.src)
        self.assertIn("function _amCompletedItemCount(", self.src)
        self.assertGreaterEqual(
            self.src.count("_amCompletedItemCount("), 2,
            "_amCompletedItemCount defined but never invoked - the spike "
            "markers must consume it")

    def test_spike_markers_receive_owned_ids(self) -> None:
        self.assertIn("_renderSpikeMarkersFromCtx(ctx, p, ownedIds)", self.src)


# ---------------------------------------------------------------------------
# 3. Map pane: text layers independent of the base image + truthful roster
# ---------------------------------------------------------------------------

class MapPaneTruthfulRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(ACTIVE_MATCH_JS)
        cls.css = _read(ACTIVE_MATCH_CSS)

    def test_text_update_runs_before_image_guard(self) -> None:
        body = self.src.split("function _amDrawOverlay(")[1]
        text_call = body.find("_amUpdateMapText(vs)")
        img_guard = body.find("naturalWidth")
        self.assertGreater(text_call, -1, "_amUpdateMapText not called")
        self.assertGreater(img_guard, -1)
        self.assertLess(text_call, img_guard,
                        "status/roster must update before the img guard - "
                        "a missing base image froze the panel on "
                        "'loading vision...'")

    def test_roster_mount_in_js_and_css(self) -> None:
        self.assertIn("am-map-roster", self.src)
        self.assertIn("am-map-roster", self.css)

    def test_roster_surfaces_respawn_and_mia(self) -> None:
        self.assertIn("respawn_in_s", self.src)
        self.assertIn("missing_for_s", self.src)

    def test_status_line_carries_ticking_clock(self) -> None:
        self.assertIn("function _amClock(", self.src)

    def test_arena_base_is_static_asset_with_crop_fallback(self) -> None:
        # Scope to the _AM_MAP_FILE literal (the file has other `arena:`
        # keys, e.g. _SPK_MODE_MAP). Item 396 made the patch segment
        # dynamic (_amMapImg builds /data/ddragon/<ITEMS.version>/img/map/)
        # so stale mirror dirs can be pruned; arena stays a static asset.
        block = self.src.split("_AM_MAP_FILE = {")[1].split("};")[0]
        m = re.search(r"arena:\s*\"([^\"]+)\"", block)
        self.assertIsNotNone(m)
        self.assertEqual("map30.png", m.group(1))
        builder = self.src.split("function _amMapImg(")[1].split("\n}")[0]
        self.assertIn("/img/map/", builder)
        # The live-crop mode is NOT deleted - it stays the onerror
        # fallback (serves the vision server's 1-PC self-grab crop).
        self.assertIn("/api/minimap-crop?mode=", self.src)

    def test_no_image_fallback_keeps_panel_visible(self) -> None:
        self.assertIn("am-map-noimg", self.src)
        self.assertIn("am-map-noimg", self.css)


# ---------------------------------------------------------------------------
# 4. CDS rail: visual-only hide
# ---------------------------------------------------------------------------

class CdsVisualHideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(ACTIVE_MATCH_CSS)
        cls.js = _read(ACTIVE_MATCH_JS)
        cls.html = _read(INDEX_HTML)
        cls.overlay = _read(OVERLAY_CSS)

    def test_cd_pane_hidden_on_dashboard(self) -> None:
        # The .am-grid hop is load-bearing: cd_ledger.css re-declares
        # display:flex on the bare selector and imports AFTER this file,
        # so an equal-specificity hide loses on order (caught live in the
        # first snapshot capture - the pane auto-placed below the grid).
        m = re.search(
            r"#view-active-match \.am-grid \.am-pane-cd\s*\{[^}]*"
            r"display:\s*none", self.css)
        self.assertIsNotNone(m, ".am-pane-cd must be display:none via the "
                                ".am-grid-scoped selector (visual-only "
                                "hide that outranks cd_ledger.css)")

    def test_grid_reflows_without_cd_rail(self) -> None:
        self.assertNotIn("280px", self.css)
        self.assertIn('"call  map"', self.css)
        self.assertIn('"build map"', self.css)

    def test_markup_and_js_wiring_kept(self) -> None:
        # Operator rule: 'remove a field' is visual-only - the mount, the
        # render dispatch and the summoner_cooldowns payload stay wired.
        self.assertIn('id="cd-ledger-body"', self.html)
        self.assertIn('id="cd-ledger-head"', self.html)
        self.assertIn("am-pane-cd", self.html)
        self.assertIn("renderCooldownLedger(", self.js)
        self.assertIn("attachCooldownLedgerHandlers(", self.js)

    def test_overlay_threat_panelset_reshow_untouched(self) -> None:
        m = re.search(
            r'\[data-panelset="threat"\] #view-active-match \.am-pane-cd'
            r"\s*\{[^}]*display:\s*block\s*!important", self.overlay)
        self.assertIsNotNone(m, "overlay threat panelset must keep its CDS "
                                "surface (display: block !important)")


class AsciiHygieneTests(unittest.TestCase):
    def test_touched_files_are_ascii(self) -> None:
        targets = [
            Path(__file__),
            ACTIVE_MATCH_JS,
            ACTIVE_MATCH_CSS,
            ROOT / "dashboard" / "routes_spike_markers.py",
            ROOT / "dashboard" / "routes_ds_combo.py",
        ]
        for p in targets:
            raw = p.read_bytes()
            offenders = [b for b in raw if b > 0x7F]
            self.assertFalse(
                offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}")


if __name__ == "__main__":
    unittest.main()
