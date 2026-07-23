"""Overlay HUD micro-lifts (BACKLOG "Overlay HUD micro-lifts", 2026-07-23).

Three precomputed, deterministic overlay lifts - ZERO API, ZERO LLM:

  (a) 90s / 10s double-alert cadence on the OQ16 objective gauges
      (web/js/panels/objective_gauges.js _alertTier -> data-og-alert, styled
      in web/css/panels/objective_gauges.css).
  (b) gold-remaining-to-the-next-DS-recommended-item readout, and
  (c) the free yellow-trinket upgrade nudge as a precomputed rule line,
      both in the NEW w-nextbuy widget:
        web/js/lib/next_buy_model.js   - pure model (node --test coverage in
                                         web/js/lib/next_buy_model.test.mjs)
        web/js/panels/next_buy.js      - thin DOM render
        web/css/panels/next_buy.css (+ @import in web/css/dashboard.css)
        web/index.html mount #am-next-buy as a direct am-grid child
        web/js/lib/overlay_layout.js WIDGETS entry w-nextbuy
        web/js/main.js renderNextBuy at BOTH active-match dispatch sites.

Data contract (grep-verified producers - nothing new server-side):
  - liveclient.gold        <- activePlayer currentGold, dashboard/_liveclient.py:148
  - liveclient.sr_items[]  <- item_advisor.resolve_build, dashboard/_liveclient.py:376,389-396
  - liveclient.owned_items <- dashboard/_liveclient.py:256
  - liveclient.game_time_s <- dashboard/_liveclient.py:144
  - item cost + recipe     <- web/js/lib/items_index.js ITEM_COSTS / ITEM_RECIPES

The trinket rule MIRRORS the server action core/build_planner/replan.py
(kind "upgrade_trinket", 3340 -> 3363, gated stage >= mid) and the stage
function core/build_planner/scoring.stage_for. The DriftPin tests below check
the JS copies against the LIVE Python constants so drift fails CI.

Wrapper idiom mirrors tests/test_objective_gauges_oq16.py +
tests/test_stats_panel_default_role.py: CI does not execute node, so the mjs
coverage is pinned by source-check here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.build_planner import replan as rp
from core.build_planner import scoring as sc

ROOT = Path(__file__).resolve().parents[1]
MODEL_JS = ROOT / "web" / "js" / "lib" / "next_buy_model.js"
MODEL_MJS = ROOT / "web" / "js" / "lib" / "next_buy_model.test.mjs"
PANEL_JS = ROOT / "web" / "js" / "panels" / "next_buy.js"
PANEL_CSS = ROOT / "web" / "css" / "panels" / "next_buy.css"
GAUGE_JS = ROOT / "web" / "js" / "panels" / "objective_gauges.js"
GAUGE_MJS = ROOT / "web" / "js" / "panels" / "objective_gauges.test.mjs"
GAUGE_CSS = ROOT / "web" / "css" / "panels" / "objective_gauges.css"
DASH_CSS = ROOT / "web" / "css" / "dashboard.css"
MAIN_JS = ROOT / "web" / "js" / "main.js"
INDEX_HTML = ROOT / "web" / "index.html"
LAYOUT_JS = ROOT / "web" / "js" / "lib" / "overlay_layout.js"


def _read(p: Path) -> str:
    assert p.is_file(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def _js_num(src: str, key: str) -> float:
    """Pull `key: <number>` out of a JS object literal."""
    m = re.search(rf"\b{re.escape(key)}\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)", src)
    assert m, f"{key} not found in the JS source"
    return float(m.group(1))


# --------------------------------------------------------------------------- #
# (a) OQ16 double-alert cadence
# --------------------------------------------------------------------------- #
class AlertCadenceTests(unittest.TestCase):
    def test_thresholds_present(self):
        js = _read(GAUGE_JS)
        self.assertEqual(_js_num(js, "alertSoonS"), 90.0)
        self.assertEqual(_js_num(js, "alertImminentS"), 10.0)

    def test_alert_tier_helper_and_export(self):
        js = _read(GAUGE_JS)
        self.assertIn("function _alertTier(", js)
        self.assertIn("_alertTier,", js, "the helper must be test-exported")

    def test_only_a_counting_down_dial_alerts(self):
        js = _read(GAUGE_JS)
        # An UP dial is already the loud green state and a "-" dial has no
        # clock - neither may escalate, so the helper bails on any non-eta.
        self.assertIn('if (state !== "eta") return "";', js)

    def test_alert_reaches_the_dom_and_the_dedup_signature(self):
        js = _read(GAUGE_JS)
        self.assertIn("data-og-alert=", js)
        # Without the tier in the sig, a threshold crossing on an otherwise
        # unchanged tick would leave a stale alert in the DOM.
        self.assertIn('`:${d.alert || ""}`', js)

    def test_css_styles_both_tiers_without_moving_geometry(self):
        css = _read(GAUGE_CSS)
        self.assertIn('[data-og-alert="soon"]', css)
        self.assertIn('[data-og-alert="imminent"]', css)
        self.assertIn("og-alert-pulse", css)
        self.assertIn("prefers-reduced-motion", css)
        # No-reflow law: the alert tiers may not touch box geometry.
        alert_block = css[css.index("Double-alert cadence"):]
        for prop in ("width:", "height:", "font-size:", "padding:", "margin:"):
            self.assertNotIn(prop, alert_block,
                             f"alert styling must not set {prop} (reflow)")

    def test_mjs_covers_the_cadence(self):
        mjs = _read(GAUGE_MJS)
        for needle in ("alertSoonS", "alertImminentS", "_alertTier",
                       '"imminent"', '"soon"', "data-og-alert"):
            self.assertIn(needle, mjs)


# --------------------------------------------------------------------------- #
# (b) + (c) the NEXT BUY widget
# --------------------------------------------------------------------------- #
class NextBuyModuleTests(unittest.TestCase):
    def test_files_exist(self):
        for p in (MODEL_JS, MODEL_MJS, PANEL_JS, PANEL_CSS):
            self.assertTrue(p.is_file(), f"{p} missing")

    def test_model_is_pure(self):
        """The model must not fetch or touch the DOM - it is unit-tested under
        node --test, where neither exists."""
        js = _read(MODEL_JS)
        for banned in ("document.", "fetch(", "window."):
            self.assertNotIn(banned, js, f"model must stay pure ({banned})")
        self.assertNotIn("import ", js, "model must not import singletons")

    def test_panel_discipline(self):
        js = _read(PANEL_JS)
        self.assertIn("export function renderNextBuy", js)
        self.assertIn('dataset.shell !== "overlay"', js)   # overlay self-gate
        self.assertIn("nextBuySig", js)                    # sig-dedup
        self.assertIn("export const __test", js)
        # No fetch: every input rides the /api/state envelope.
        self.assertNotIn("fetch(", js)
        # Exactly one DOM write site (inside renderNextBuy).
        self.assertEqual(js.count("mount.innerHTML"), 2,
                         "innerHTML only for the clear + the single render")

    def test_unknown_cost_is_the_sentinel_not_zero(self):
        js = _read(PANEL_JS)
        # An unknown cost must render "-", never 0g / BUY NOW.
        self.assertIn('const known = m.remaining !== null', js)
        self.assertIn('!known ? "-"', js)

    def test_rows_never_disappear(self):
        """No-reflow law: all three rows render every tick; an absent value is
        the '-' sentinel, never a removed row."""
        js = _read(PANEL_JS)
        self.assertIn('_row("item"', js)
        self.assertIn('_row("gold"', js)
        self.assertIn('_row("trinket"', js)
        self.assertIn('m.trinket || "-"', js)
        self.assertIn('m.item || "-"', js)
        css = _read(PANEL_CSS)
        self.assertIn("grid-template-columns: 64px 1fr", css)  # fixed label col

    def test_rerenders_once_the_async_item_dictionaries_land(self):
        """ITEM_COSTS / ITEMS are async fetches. A render that lands first can
        only show "-", and sig-dedup would PIN that sentinel until some other
        field changed (measured 2026-07-23 in the Chromium harness), so the
        panel re-renders on both ready events."""
        js = _read(PANEL_JS)
        self.assertIn('addEventListener("rc:items-ready"', js)
        self.assertIn('addEventListener("rc:item-costs-ready"', js)
        self.assertIn("_sig = null", js, "the re-render must clear the sig")
        # The producer side of the new event.
        idx = _read(ROOT / "web" / "js" / "lib" / "items_index.js")
        self.assertIn('new CustomEvent("rc:item-costs-ready")', idx)

    def test_widget_is_widened_to_fit_the_longest_value(self):
        """Widen-to-fit law (overlay.css): the default 210px ellipsised
        "Farsight Alteration"."""
        css = _read(ROOT / "web" / "css" / "overlay.css")
        self.assertIn('data-ovx-id="w-nextbuy"', css)
        m = re.search(
            r'data-ovx-id="w-nextbuy"\]\s*\{\s*--ovx-w:\s*(\d+)px', css)
        self.assertTrue(m, "w-nextbuy must set --ovx-w")
        self.assertGreaterEqual(int(m.group(1)), 260)

    def test_html_is_escaped(self):
        js = _read(PANEL_JS)
        self.assertIn("function _esc(", js)
        self.assertIn("_esc(value)", js)


class DriftPinTests(unittest.TestCase):
    """The JS mirrors must match the live Python rule they copy."""

    def test_stage_constants_match_scoring_py(self):
        js = _read(MODEL_JS)
        self.assertEqual(_js_num(js, "earlyClockS"), sc._EARLY_CLOCK_S)
        self.assertEqual(_js_num(js, "lateClockS"), sc._LATE_CLOCK_S)
        self.assertEqual(_js_num(js, "midOwned"), sc._MID_OWNED)
        self.assertEqual(_js_num(js, "lateOwned"), sc._LATE_OWNED)

    def test_stage_order_matches_replan_py(self):
        js = _read(MODEL_JS)
        for label, order in rp._STAGE_ORDER.items():
            self.assertIn(f"{label}: {order}", js)

    def test_trinket_gate_matches_replan_py(self):
        js = _read(MODEL_JS)
        cfg_min = re.search(
            r'trinket_upgrade_min_stage:\s*str\s*=\s*"([a-z]+)"',
            _read(ROOT / "core" / "build_planner" / "replan.py"))
        self.assertTrue(cfg_min, "replan trinket_upgrade_min_stage not found")
        self.assertIn(f'NB_TRINKET_MIN_STAGE = "{cfg_min.group(1)}"', js)

    def test_trinket_ids_resolve_to_the_mirrored_names(self):
        """3340 Stealth Ward -> 3363 Farsight Alteration, per the item catalog
        replan itself reads - so the JS names cannot drift from the ids."""
        import json
        raw = json.loads(
            (ROOT / "data" / "meta" / "ddragon_items.json").read_text(
                encoding="utf-8"))
        data = raw.get("data", raw)
        src_name = data[rp._STEALTH_WARD_ID]["name"]
        dst_name = data[rp._FARSIGHT_ID]["name"]
        js = _read(MODEL_JS)
        self.assertIn(src_name.lower(), js,
                      f"NB_TRINKET_FROM must list {src_name}")
        self.assertIn(f'NB_TRINKET_TO = "{dst_name}"', js)

    def test_stage_for_agrees_with_the_python_function(self):
        """Spot-check the JS branch table against scoring.stage_for itself."""
        cases = [(0, 0, "early"), (599, 1, "early"), (600, 0, "mid"),
                 (0, 2, "mid"), (1320, 0, "late"), (0, 4, "late")]
        for clock, owned, expected in cases:
            self.assertEqual(sc.stage_for(float(clock), owned), expected,
                             f"python stage_for({clock},{owned})")
        mjs = _read(MODEL_MJS)
        for clock, owned, expected in cases:
            self.assertIn(f'stageFor({clock}, {owned}), "{expected}"', mjs,
                          f"mjs must pin stageFor({clock},{owned})")


class WiringTests(unittest.TestCase):
    def test_mount_is_a_direct_am_grid_child(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="am-next-buy"', html)
        self.assertIn('class="next-buy" id="am-next-buy" hidden', html)

    def test_layout_registry_entry(self):
        js = _read(LAYOUT_JS)
        self.assertIn('id: "w-nextbuy"', js)
        self.assertIn('sel: "#am-next-buy"', js)

    def test_css_imported(self):
        self.assertIn("@import './panels/next_buy.css';", _read(DASH_CSS))

    def test_main_js_dispatches_at_both_sites(self):
        js = _read(MAIN_JS)
        self.assertIn(
            "import { renderNextBuy } from './panels/next_buy.js';", js)
        self.assertEqual(js.count("renderNextBuy({"), 2,
                         "renderNextBuy must fire at the ui_mock AND live sites")

    def test_mjs_covers_the_model(self):
        mjs = _read(MODEL_MJS)
        for needle in ("goldRemaining", "trinketNudge", "computeNextBuy",
                       "stageFor", "nextItemName", "completedCount"):
            self.assertIn(needle, mjs)
        # The two traps this slice actually hit / could hit.
        self.assertIn("gold: null", mjs)          # Number(null) === 0
        self.assertIn("never goes negative", mjs)


class AsciiTests(unittest.TestCase):
    """Repo hard rule: 7-bit ASCII authored content, no em/en dashes."""

    def test_new_files_are_ascii(self):
        for p in (MODEL_JS, MODEL_MJS, PANEL_JS, PANEL_CSS):
            txt = _read(p)
            bad = [c for c in txt if ord(c) > 127]
            self.assertEqual(bad, [], f"{p} has non-ASCII: {set(bad)}")


if __name__ == "__main__":
    unittest.main()
