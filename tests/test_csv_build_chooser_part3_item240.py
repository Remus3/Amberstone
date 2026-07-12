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
 3a/3b - SUPERSEDED by item-1 Phase 2 (rune-follows-build). The per-build-card
      nested rune panel + its amber-recommended-vs-green-selected border model
      were replaced by ONE champ-wide rune SIDE panel (sibling of .csv-builds)
      whose selected page FOLLOWS the active build and whose recommended page
      ALWAYS carries the star (independent of selection). New guard =
      tests/test_champ_select_rune_follows_build.py; the old 3a/3b grep pins
      (RunePanel3aTests + RuneBorders3bTests) were removed here.
 3c - per-champion {variantKey, runeKey} persistence: variant choice stays in
      the item_build-shared rc-ingame-build-<champ> plain-string key (so the
      in-game build chooser pre-select is unbroken), rune choice in a SEPARATE
      sibling rc-cs-rune-<champ> key; back-compat = a champ with no rune key
      returns "".
 3d - SUPERSEDED by item-1 Phase 5 (auto-push toggles relocated to Settings).
      The in-panel [PUSH] button + 3 header checkboxes + the rc-cs-push-flags
      opt-in blob were replaced by 3 default-ON toggles in the CHAMP SELECT
      settings card (flat keys rc-cs-push-{runes,spells,build}, inverted dev.js
      binder, _csvGetPushFlags default-ON). New guard =
      tests/test_csv_push_toggles_phase5.py; the HeaderControl3dTests grep pins
      + the two in-panel-wiring 3e tests were removed here.
 3e - push SEMANTICS (per-category LCU verbs) still hold + are pinned below;
      the in-panel checkbox / [PUSH]-button WIRING pins were removed with 3d
      (Phase 5). Per-category verbs: Runes->apply_runes (apply route push_runes
      gate), Spells->set_summoner_spell (both slots), Build->apply_item_sets_batch
      (apply route push_items gate + the colon-form variant key).
"""

from __future__ import annotations

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


# HeaderControl3dTests (the in-panel [PUSH] button + 3 header checkboxes +
# the rc-cs-push-flags opt-in blob + the all-false default + the push-ctrl
# CSS) was REMOVED here - item-1 Phase 5 relocated the auto-push toggles to the
# CHAMP SELECT settings card (default-ON, flat keys). New guard =
# tests/test_csv_push_toggles_phase5.py.


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

    # test_checkbox_change_pushes_on_check_only + test_push_button_force_pushes_
    # checked were REMOVED here - item-1 Phase 5 deleted the in-panel checkbox /
    # [PUSH]-button wiring inside _csvWireBuildVariants (the toggles moved to the
    # settings card). The per-category verbs above + the build-selection auto-
    # push (flags.build) remain the live push paths.

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
    champ-wide rune SIDE panel (item-1 Phase 2) resolves >1 distinct
    selectable page (the multi-page follow-the-build behavior is
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
            "side panel's multiple selectable pages.")
        keystones = [p.get("keystone") for p in paths]
        self.assertTrue(all(keystones),
            "every mock build path must carry a keystone so the rune "
            "side panel resolves a page per build.")
        self.assertGreaterEqual(len(set(keystones)), 2,
            "mock build paths must carry >=2 DISTINCT keystones so the "
            "side panel offers >=2 distinct selectable pages (the "
            "follow-the-build + always-star behavior is visible).")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii_clean(self):
        raw = Path(__file__).read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(b, 128, f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
