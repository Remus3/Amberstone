"""Drift guard for item 240 part-3: SR build chooser cards-left + nested
rune panel + per-category LCU push + per-champion persistence.

Spec: docs/CHAMP_SELECT_UI_SPEC.md section 3 (3a-3e). The dashboard is a
no-framework ESM app driven by string-template renders, so the standing
house pattern (mirrored from tests/test_csv_rune_push_on_selection_change.py
+ tests/test_lcu_item_sets_wipe_stale.py) is to grep the source for the
load-bearing render fns / element ids / wiring anchors / CSS classes that a
future refactor must not rip out, plus a Python-level round-trip of the
{variantKey, runeKey} persistence contract's shape.

Coverage:
 3a - the nested rune panel render fn + the 2-column collapsed layout.
 3b - GREEN (.is-selected sticky) + AMBER (.is-recommended) border classes;
      the recommended marker re-points on a build-card click without moving
      the sticky green; on-recommended -> green-only (no amber).
 3c - per-champion {variantKey, runeKey} persistence: variant choice stays in
      the item_build-shared rc-ingame-build-<champ> plain-string key (so the
      in-game build chooser pre-select is unbroken), rune choice in a SEPARATE
      sibling rc-cs-rune-<champ> key; back-compat = a champ with no rune key
      returns "".
 3d - header control: [PUSH] button + 3 inline [x] Runes/Spells/Build
      checkboxes; GLOBAL push-flag localStorage key; default first-run ALL
      UNCHECKED (opt-in).
 3e - push semantics: uncheck->check pushes that category immediately; while
      checked a subsequent selection change pushes it; uncheck fires no push;
      [PUSH] force-pushes all checked categories. Per-category LCU verbs:
      Runes->apply_runes (via the apply route push_runes gate), Spells->
      set_summoner_spell (both slots), Build->apply_item_sets_batch (via the
      apply route push_items gate + the colon-form variant key).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CHAMP_SELECT_JS = REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"
CHAMP_SELECT_CSS = REPO_ROOT / "web" / "css" / "panels" / "champ_select_view.css"
MOCK_SR = REPO_ROOT / "web" / "data" / "ui_mock" / "champ_select_sr.json"
ROUTES_LOADOUT = REPO_ROOT / "dashboard" / "routes_loadout.py"


def _fn_body(text: str, sig: str) -> str:
    """Return the brace-balanced body of a top-level `function <sig> {`."""
    start = text.index(sig)
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace : i + 1]
    raise AssertionError(f"unbalanced braces after {sig!r}")


class RunePanel3aTests(unittest.TestCase):
    """3a: nested rune panel render fn + 2-column collapsed layout."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.css = CHAMP_SELECT_CSS.read_text(encoding="utf-8")

    def test_rune_panel_render_fn_exists(self):
        self.assertIn(
            "function _csvRunePanelHtml(", self.js,
            "missing _csvRunePanelHtml - the nested rune panel render fn "
            "(3a). Without it the cards-right rune column does not render.",
        )

    def test_collapsed_two_column_wrapper(self):
        # The collapsed-variant return must wrap the path-list + rune
        # panel in a 2-column grid (cards left, runes right).
        body = _fn_body(self.js, "function _csvBuildVariantRowsHtml(")
        self.assertIn("csv-build-collapsed-cols", body,
            "collapsed variant must wrap cards + rune panel in the "
            "csv-build-collapsed-cols 2-column grid (3a).")
        self.assertIn("_csvRunePanelHtml(", body,
            "collapsed variant render must mount the rune panel beside "
            "the build-path cards (3a).")

    def test_css_two_column_grid_present(self):
        self.assertIn(".csv-build-collapsed-cols", self.css,
            "missing .csv-build-collapsed-cols CSS - the 2-column grid.")
        # grid-template-columns gives the cards 1fr + a right rune rail.
        m = re.search(
            r"\.csv-build-collapsed-cols\s*\{[^}]*grid-template-columns:[^;]*1fr",
            self.css, re.DOTALL)
        self.assertIsNotNone(m,
            ".csv-build-collapsed-cols must be a grid with a flex-grow "
            "cards column + a rune rail.")

    def test_css_rune_panel_classes_present(self):
        for cls in (".csv-rune-panel", ".csv-rune-opt", ".csv-rune-opt-list",
                    ".csv-rune-opt-name", ".csv-rune-opt-icon"):
            self.assertIn(cls, self.css, f"missing rune-panel CSS class {cls}")


class RuneBorders3bTests(unittest.TestCase):
    """3b: GREEN sticky + AMBER recommended border classes + re-point."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.css = CHAMP_SELECT_CSS.read_text(encoding="utf-8")

    def test_panel_emits_selected_and_recommended_classes(self):
        body = _fn_body(self.js, "function _csvRunePanelHtml(")
        self.assertIn("is-selected", body,
            "rune panel must mark the operator's sticky rune choice "
            "with is-selected (GREEN, 3b).")
        self.assertIn("is-recommended", body,
            "rune panel must mark the active build card's recommended "
            "rune with is-recommended (AMBER, 3b).")

    def test_on_recommended_suppresses_amber(self):
        # When the operator is already on the recommended rune, the amber
        # is withheld (green only). The guard variable is onRecommended.
        body = _fn_body(self.js, "function _csvRunePanelHtml(")
        self.assertIn("onRecommended", body,
            "rune panel must compute onRecommended so the amber is "
            "withheld when the sticky choice == recommended (3b: green "
            "only, no second color).")
        # isRecommended must be gated on NOT onRecommended AND NOT selected.
        self.assertRegex(
            body,
            r"isRecommended\s*=\s*o\.key === recommendedRuneKey && !onRecommended && !isSelected",
            "is-recommended must be withheld both when the option is the "
            "sticky selection and when the operator is already on the "
            "recommended rune (3b).")

    def test_card_click_repoints_recommended_not_selected(self):
        # The path-row click handler must re-point the amber marker to the
        # active card's keystone WITHOUT moving the green sticky marker.
        body = _fn_body(self.js, "function _csvWireBuildVariants(")
        self.assertIn("_repointRecommendedRune", body,
            "build-card click must re-point the recommended (amber) rune "
            "marker (3b).")
        self.assertIn("data-card-keystone", self.js,
            "each build-path card must carry data-card-keystone so the "
            "click can re-point the amber marker to its keystone (3b).")

    def test_css_green_and_amber_borders(self):
        m_sel = re.search(
            r"\.csv-rune-opt\.is-selected\s*\{[^}]*border-color:\s*#4ade80",
            self.css, re.DOTALL)
        self.assertIsNotNone(m_sel,
            ".csv-rune-opt.is-selected must use the GREEN border-color "
            "(#4ade80) for the sticky rune choice (3b).")
        m_rec = re.search(
            r"\.csv-rune-opt\.is-recommended\s*\{[^}]*border-color:\s*#fbbf24",
            self.css, re.DOTALL)
        self.assertIsNotNone(m_rec,
            ".csv-rune-opt.is-recommended must use the AMBER border-color "
            "(#fbbf24) for the recommended rune (3b).")


class HeaderControl3dTests(unittest.TestCase):
    """3d: [PUSH] button + 3 category checkboxes, RIGHT-aligned, GLOBAL
    persisted flags, default first-run all-unchecked."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.css = CHAMP_SELECT_CSS.read_text(encoding="utf-8")

    def test_push_button_element_id(self):
        self.assertIn('id="csv-builds-push-btn"', self.js,
            "missing the [PUSH] button (#csv-builds-push-btn) on the "
            "chooser header control (3d).")

    def test_three_category_checkboxes(self):
        self.assertIn('class="csv-builds-push-cb"', self.js,
            "missing the per-category push checkboxes (3d).")
        self.assertIn('data-push-cat=', self.js,
            "push checkboxes must carry data-push-cat so the wiring "
            "knows which category to push (3d).")
        # All three categories must be the iterable source.
        self.assertRegex(
            self.js,
            r'_CSV_PUSH_CATS\s*=\s*\["runes",\s*"spells",\s*"build"\]',
            "the 3 categories must be runes/spells/build (3d).")

    def test_global_push_flag_storage_key(self):
        # GLOBAL (not per-champion) key.
        self.assertIn('"rc-cs-push-flags"', self.js,
            "push-flag persistence must use a GLOBAL key rc-cs-push-flags "
            "(3d - not per-champion).")
        self.assertIn("function _csvGetPushFlags(", self.js)
        self.assertIn("function _csvSetPushFlag(", self.js)

    def test_default_first_run_all_unchecked(self):
        # _csvGetPushFlags falls back to all-false on missing/corrupt.
        body = _fn_body(self.js, "function _csvGetPushFlags(")
        self.assertRegex(
            body,
            r"off\s*=\s*\{\s*runes:\s*false,\s*spells:\s*false,\s*build:\s*false\s*\}",
            "default first-run push flags MUST be all-false (3d opt-in: "
            "nothing auto-pushes until the operator checks a box).")
        # Missing key returns the off blob.
        self.assertIn("if (!raw) return off;", body,
            "missing push-flags key must return all-off (3d).")

    def test_css_header_control_right_aligned(self):
        m = re.search(
            r"\.csv-builds-head\s*\{[^}]*justify-content:\s*space-between",
            self.css, re.DOTALL)
        self.assertIsNotNone(m,
            ".csv-builds-head must space-between so the push control is "
            "RIGHT-aligned to the title (3d).")
        self.assertIn(".csv-builds-push-btn", self.css)
        self.assertIn(".csv-builds-push-cat", self.css)


class PushSemantics3eTests(unittest.TestCase):
    """3e: per-category push verbs + uncheck->check immediate push +
    [PUSH] force-push + auto-push gating."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")
        cls.routes = ROUTES_LOADOUT.read_text(encoding="utf-8")

    def test_push_category_dispatcher_exists(self):
        self.assertIn("function _csvPushCategory(", self.js,
            "missing _csvPushCategory - the per-category push dispatcher "
            "(3e).")
        self.assertIn("function _csvPushCheckedCategories(", self.js,
            "missing _csvPushCheckedCategories - the [PUSH] button force-"
            "push of all checked categories (3e).")

    def test_build_category_pushes_items_only(self):
        body = _fn_body(self.js, "function _csvPushCategory(")
        # Build -> apply route with push_items only.
        self.assertRegex(
            body,
            r'cat === "build"[\s\S]*?push_runes: false, push_items: true, push_summoners: false',
            "the Build category must push ONLY the item set (push_items "
            "true, runes/summoners false) - 3e.")

    def test_runes_category_pushes_runes_only(self):
        body = _fn_body(self.js, "function _csvPushCategory(")
        self.assertRegex(
            body,
            r'cat === "runes"[\s\S]*?push_runes: true, push_items: false, push_summoners: false',
            "the Runes category must push ONLY the rune page (push_runes "
            "true, items/summoners false) - 3e.")

    def test_spells_category_uses_set_summoner_spell(self):
        body = _fn_body(self.js, "function _csvPushCategory(")
        self.assertIn('cmd: "set_summoner_spell", slot: 1', body,
            "the Spells category must push both summoner slots via "
            "set_summoner_spell (3e).")
        self.assertIn('cmd: "set_summoner_spell", slot: 2', body,
            "the Spells category must push BOTH slots (D + F) - 3e.")

    def test_active_build_selection_uses_colon_form(self):
        # The push must use the colon-form composed key so the resolver
        # overlays the active path's items/runes (3e).
        body = _fn_body(self.js, "function _csvActiveBuildSelection(")
        self.assertIn('composedKey = `${v.key}:${pathKey}`', body,
            "_csvActiveBuildSelection must build the <variant>:<path-key> "
            "colon form so the resolver overlays the active path (3e).")

    def test_checkbox_change_pushes_on_check_only(self):
        body = _fn_body(self.js, "function _csvWireBuildVariants(")
        # The change handler persists then pushes ONLY when on==true.
        self.assertIn("_csvSetPushFlag(cat, on);", body,
            "checkbox change must persist the flag (3e).")
        self.assertRegex(
            body,
            r"if \(on && champion\) \{[\s\S]*?_csvPushCategory\(champion, mode, cat, variants\)",
            "uncheck->check must push that category immediately; uncheck "
            "fires no push (3e).")

    def test_push_button_force_pushes_checked(self):
        body = _fn_body(self.js, "function _csvWireBuildVariants(")
        self.assertIn("_csvPushCheckedCategories(champion, mode, variants)", body,
            "the [PUSH] button must force-push all currently-checked "
            "categories (3e).")

    def test_apply_route_honors_per_category_flags(self):
        # The backend apply route must gate each enqueue on its push flag
        # (the per-category push relies on this).
        self.assertIn('if push_runes: _enqueue(resolved.get("rune_cmd"))', self.routes)
        self.assertIn('if push_items: _enqueue(resolved.get("item_cmd"))', self.routes)
        self.assertIn('if push_summ:  _enqueue(resolved.get("summ_cmd"))', self.routes)

    def test_apply_loadout_accepts_push_flags(self):
        # _csvApplyLoadout grew a pushFlags param so the per-category push
        # can gate items vs runes vs summoners.
        self.assertIn(
            "function _csvApplyLoadout(champion, variantKey, mode, "
            "overrideSummoners, overrideRunes, overrideItems, pushFlags)",
            self.js,
            "_csvApplyLoadout must accept a pushFlags arg for per-category "
            "gating (3e); default (omitted) still pushes all three.")
        # Default omitted -> all three true (legacy click + userbuild
        # path unchanged).
        body = _fn_body(self.js, "function _csvApplyLoadout(")
        self.assertIn(
            "const wantRunes = (pf.push_runes !== undefined) ? !!pf.push_runes : true;",
            body,
            "omitted pushFlags must default to pushing all three (back-"
            "compat with the legacy single-variant + userbuild click).")


class Persistence3cTests(unittest.TestCase):
    """3c: per-champion {variantKey, runeKey} persistence + back-compat."""

    @classmethod
    def setUpClass(cls):
        cls.js = CHAMP_SELECT_JS.read_text(encoding="utf-8")

    def test_rune_choice_uses_separate_sibling_key(self):
        # The build choice MUST stay in the item_build-shared
        # rc-ingame-build-<champ> key (plain string) so the in-game
        # chooser pre-select is unbroken; the rune choice lives in a
        # SEPARATE rc-cs-rune-<champ> key.
        self.assertIn(
            'function _csvRuneStorageKey(champion) { return "rc-cs-rune-" + (champion || ""); }',
            self.js,
            "rune choice must persist under a SEPARATE rc-cs-rune-<champ> "
            "sibling key (3c) - NOT folded into rc-ingame-build (which "
            "item_build.js reads as a plain variant string).")
        self.assertIn("function _csvSavedRuneChoice(", self.js)
        self.assertIn("function _csvSaveRuneChoice(", self.js)

    def test_build_choice_key_unchanged_for_item_build_compat(self):
        # _csvStorageKey + _csvSaveChoice must still write the plain
        # variant string under rc-ingame-build-<champ> (item_build.js's
        # _ibStorageKey reads the exact same key).
        self.assertIn(
            'function _csvStorageKey(champion) { return "rc-ingame-build-" + (champion || ""); }',
            self.js,
            "the build choice key must stay rc-ingame-build-<champ> for "
            "item_build.js cross-panel pre-select compat (3c).")
        body = _fn_body(self.js, "function _csvSaveChoice(")
        self.assertIn(
            "localStorage.setItem(_csvStorageKey(champion), variantKey)", body,
            "_csvSaveChoice must write the variant key as a PLAIN string "
            "(not a JSON blob) so item_build.js still parses it (3c).")

    def test_saved_selection_accessor_returns_pair(self):
        body = _fn_body(self.js, "function _csvSavedSelection(")
        self.assertIn("variantKey: _csvSavedChoice(champion)", body)
        self.assertIn("runeKey:    _csvSavedRuneChoice(champion)", body)


class PersistenceRoundTrip3cTests(unittest.TestCase):
    """3c: Python-level round-trip + back-compat of the persistence
    contract's SHAPE.

    We can't run the browser localStorage, but the contract is simple
    enough to model: build choice -> rc-ingame-build-<champ> (plain
    string), rune choice -> rc-cs-rune-<champ> (plain string). The
    invariants tested here mirror the JS helpers' behavior so a future
    schema change that folds the rune into the build blob (breaking
    item_build.js) trips this test."""

    def setUp(self):
        # In-memory localStorage stand-in keyed exactly like the JS.
        self.store: dict[str, str] = {}

    def _build_key(self, champ: str) -> str:
        return "rc-ingame-build-" + (champ or "")

    def _rune_key(self, champ: str) -> str:
        return "rc-cs-rune-" + (champ or "")

    def _save_choice(self, champ: str, variant: str) -> None:
        self.store[self._build_key(champ)] = variant

    def _save_rune(self, champ: str, rune: str) -> None:
        self.store[self._rune_key(champ)] = rune

    def _saved_selection(self, champ: str) -> dict:
        return {
            "variantKey": self.store.get(self._build_key(champ), ""),
            "runeKey":    self.store.get(self._rune_key(champ), ""),
        }

    def test_round_trip_variant_and_rune(self):
        self._save_choice("Jinx", "sr-collapsed:on-hit")
        self._save_rune("Jinx", "Hail of Blades")
        sel = self._saved_selection("Jinx")
        self.assertEqual(sel["variantKey"], "sr-collapsed:on-hit")
        self.assertEqual(sel["runeKey"], "Hail of Blades")

    def test_back_compat_variant_only_entry(self):
        # A champ saved BEFORE part-3 has only the build key; the rune
        # accessor must return "" (no exception, no folding).
        self._save_choice("Caitlyn", "sr-collapsed:crit")
        sel = self._saved_selection("Caitlyn")
        self.assertEqual(sel["variantKey"], "sr-collapsed:crit")
        self.assertEqual(sel["runeKey"], "",
            "a variant-only legacy entry must yield an empty runeKey "
            "(back-compat, 3c).")

    def test_keys_are_disjoint(self):
        # The two keys must never collide (else writing a rune clobbers
        # the build choice item_build.js reads).
        self.assertNotEqual(self._build_key("X"), self._rune_key("X"))


class MockFixture3aTests(unittest.TestCase):
    """The SR mock fixture carries distinct per-path keystones so the
    rune panel renders >1 option (and the amber-vs-green behavior is
    demonstrable in ?ui_mock=1)."""

    @classmethod
    def setUpClass(cls):
        import json
        cls.data = json.loads(MOCK_SR.read_text(encoding="utf-8"))

    def test_jinx_paths_carry_distinct_keystones(self):
        bv = self.data.get("build_variants", {})
        rows = bv.get("Jinx|sr") or []
        self.assertTrue(rows, "mock missing Jinx|sr build_variants")
        paths = rows[0].get("build_paths") or []
        self.assertGreaterEqual(len(paths), 2,
            "Jinx collapsed variant needs >=2 paths to demo the rune "
            "panel (3a).")
        keystones = [p.get("keystone") for p in paths]
        self.assertTrue(all(keystones),
            "every mock build path must carry a keystone so the rune "
            "panel renders per-card runes (3a).")
        self.assertGreaterEqual(len(set(keystones)), 2,
            "mock build paths must carry >=2 DISTINCT keystones so the "
            "amber-recommended-vs-green-selected behavior is visible "
            "(3b).")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii_clean(self):
        raw = Path(__file__).read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(b, 128, f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
