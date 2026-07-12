"""Item-1 Phase 2/3 rune-follows-build champ-select frontend pins.

Promotes the champ-select rune panel from a nested per-build-card column to
ONE champ-wide SIDE panel (sibling of .csv-builds) whose selected page FOLLOWS
the active item build with precedence:

    sessionOverride ?? savedDefault ?? recommendedPageId

plus: an unsaved override is DISCARDED on a build change (not restored later),
the recommended page ALWAYS shows a star (even when a different page is
selected), and a Save-as-default button persists to localStorage
rc-cs-rune-default.

Two layers (mirrors the repo's champ_select panel-DOM test convention):
- StaticSourceGuards: grep-style pins that the side-panel symbols exist, the
  old nested rune render (_csvRunePanelHtml / _repointRecommendedRune /
  .csv-rune-opt) is gone, the Phase-6 push helper (_csvPushFollowedRune) exists
  and reverse-maps via pushPageId, and the side-panel wiring now FIRES the
  manual LCU rune push (the Phase-6 flip of the Phase-5 no-push invariant).
- BehaviorTests: extract the pure helpers from the source and run them in node
  (fake localStorage) to prove precedence, override-discard-on-build-change,
  always-star, save-default round-trip, one-option-per-deduped-page, and the
  Phase-6 pushPageId reverse-map (skip a pure-auto page). Skipped when node is
  unavailable.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
CHAMP_SELECT_CSS = ROOT / "web" / "css" / "panels" / "champ_select_view.css"
_NODE = shutil.which("node")

# Stable anchor comment marking the side-panel wiring block (B2/B4).
_SIDE_WIRE_ANCHOR = "// item 1 Phase 2 side-panel wiring (B2/B4):"


def _read_source() -> str:
    return CHAMP_SELECT_JS.read_text(encoding="utf-8")


def _balanced_span(src: str, anchor: str, opens: str, closes: str) -> str:
    """Return the source span from `anchor` through the balanced close of the
    first opening bracket at/after it (tracking only the given bracket kinds).
    Relies on the extracted fragment being brace-balanced - true for the pure
    helpers below."""
    i = src.index(anchor)
    j = i
    while src[j] not in opens:
        j += 1
    depth = 0
    for k in range(j, len(src)):
        c = src[k]
        if c in opens:
            depth += 1
        elif c in closes:
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"unbalanced span for anchor: {anchor!r}")


class StaticSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read_source()
        cls.css = CHAMP_SELECT_CSS.read_text(encoding="utf-8")

    def test_side_panel_symbols_present(self) -> None:
        for sym in (
            "function _csvRuneSidePanelHtml",
            "function _csvSelectedRunePageId",
            "function _csvRecommendedPageId",
            "function _csvRuneOverrideOnBuildChange",
            "function _csvFetchRunePages",
            "_CSV_RUNE_OVERRIDE",
            "csv-rune-side",
            "data-page-id",
        ):
            self.assertIn(sym, self.src, f"missing side-panel symbol: {sym}")

    def test_fetches_rune_pages_route(self) -> None:
        self.assertIn("/api/loadout/rune-pages", self.src)
        self.assertIn("_CSV_RUNEPAGES_CACHE", self.src)

    def test_save_default_helpers_present(self) -> None:
        self.assertIn("function _csvSavedRuneDefault", self.src)
        self.assertIn("function _csvSaveRuneDefault", self.src)
        self.assertIn("rc-cs-rune-default", self.src)
        self.assertIn("csv-rune-save-default", self.src)

    def test_nested_rune_render_removed(self) -> None:
        # The per-build-card nested rune column + its imperative re-point
        # helper + the old option class are fully gone.
        self.assertNotIn("_csvRunePanelHtml", self.src)
        self.assertNotIn("_repointRecommendedRune", self.src)
        self.assertNotIn("csv-rune-opt", self.src)

    def test_phase6_push_helpers_intact(self) -> None:
        # The LCU push path is Phase 6 - its helpers must survive untouched.
        self.assertIn("function _csvPushCategory", self.src)
        self.assertIn("function _csvSaveRuneChoice", self.src)
        self.assertIn("function _csvSavedRuneChoice", self.src)

    def test_side_wiring_fires_rune_push(self) -> None:
        # Phase 6 FLIP: the side-panel option click now DOES fire the manual LCU
        # rune push (via _csvPushFollowedRune) in addition to setting the
        # in-memory override + rescheduling a render. This inverts the Phase-5
        # "side wiring wires no push" invariant.
        block = _balanced_span(self.src, _SIDE_WIRE_ANCHOR, "{", "}")
        self.assertIn("_CSV_RUNE_OVERRIDE = {", block)
        self.assertIn("_csvScheduleRender", block)
        self.assertIn("_csvSaveRuneDefault(", block)
        self.assertIn("_csvPushFollowedRune(", block)

    def test_phase6_push_helper_present_and_wired(self) -> None:
        # Phase 6: the manual rune-push helper exists, gates on the default-ON
        # runes push flag, reverse-maps the selected pageId via pushPageId, and
        # pushes runes-only through the /api/loadout/apply seam.
        self.assertIn("function _csvPushFollowedRune", self.src)
        fn = _balanced_span(self.src, "function _csvPushFollowedRune", "{", "}")
        self.assertIn("_csvGetPushFlags().runes", fn)
        self.assertIn("pushPageId", fn)
        self.assertIn("_csvApplyLoadout(", fn)
        self.assertIn("push_runes: true", fn)
        self.assertIn("push_items: false", fn)

    def test_side_panel_css_present(self) -> None:
        self.assertIn(".csv-rune-side", self.css)
        self.assertIn(".csv-builds-row", self.css)


@unittest.skipUnless(_NODE, "node not on PATH")
class BehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = _read_source()
        # Pure helpers extracted from the live source.
        rec_fn = _balanced_span(src, "function _csvRecommendedPageId", "{", "}")
        sel_fn = _balanced_span(src, "function _csvSelectedRunePageId", "{", "}")
        chg_fn = _balanced_span(
            src, "function _csvRuneOverrideOnBuildChange", "{", "}")
        panel_fn = _balanced_span(src, "function _csvRuneSidePanelHtml", "{", "}")
        savedkey_fn = _balanced_span(
            src, "function _csvRuneDefaultStorageKey", "{", "}")
        saved_fn = _balanced_span(src, "function _csvSavedRuneDefault", "{", "}")
        save_fn = _balanced_span(src, "function _csvSaveRuneDefault", "{", "}")

        harness = (
            "function _csvKeystoneIcon() { return ''; }\n"
            "function keystoneTooltipHtml() { return ''; }\n"
            "const _store = {};\n"
            "const localStorage = {\n"
            "  getItem(k){ return Object.prototype.hasOwnProperty.call(_store,k) ? _store[k] : null; },\n"
            "  setItem(k,v){ _store[k] = String(v); },\n"
            "};\n"
            + rec_fn + "\n" + sel_fn + "\n" + chg_fn + "\n"
            + panel_fn + "\n" + savedkey_fn + "\n" + saved_fn + "\n" + save_fn + "\n"
            + "const CHAMP='Ezreal';\n"
            + "const buildsA=[{buildId:'A',recommendedPageId:'pRec'}];\n"
            + "const buildsAB=[{buildId:'A',recommendedPageId:'pRecA'},"
            + "{buildId:'B',recommendedPageId:'pRecB'}];\n"
            # --- precedence -----------------------------------------------
            + "const over={champ:CHAMP,buildId:'A',pageId:'pOver'};\n"
            + "const prec={\n"
            + "  override: _csvSelectedRunePageId(CHAMP,'A',buildsA,{A:'pSaved'},over),\n"
            + "  saved:    _csvSelectedRunePageId(CHAMP,'A',buildsA,{A:'pSaved'},null),\n"
            + "  rec:      _csvSelectedRunePageId(CHAMP,'A',buildsA,{},null),\n"
            + "};\n"
            # --- override discard on build change --------------------------
            + "let ov={champ:CHAMP,buildId:'A',pageId:'pOver'};\n"
            + "const selWhileA=_csvSelectedRunePageId(CHAMP,'A',buildsAB,{},ov);\n"
            + "ov=_csvRuneOverrideOnBuildChange(ov,CHAMP,'B');\n"
            + "const selAfterB=_csvSelectedRunePageId(CHAMP,'B',buildsAB,{},ov);\n"
            + "const selBackA=_csvSelectedRunePageId(CHAMP,'A',buildsAB,{},ov);\n"
            + "const discard={selWhileA, ovAfter: ov, selAfterB, selBackA};\n"
            # --- always-star + one-option-per-page render ------------------
            + "const pages=[{pageId:'p1',keystone:'a'},{pageId:'p1',keystone:'a'},"
            + "{pageId:'p2',keystone:'b'},{pageId:'p3',keystone:'c'}];\n"
            + "function parse(html){\n"
            + "  const re=/<div class=\"(csv-rune-side-opt[^\"]*)\" data-page-id=\"([^\"]+)\"/g;\n"
            + "  const opts=[]; let m;\n"
            + "  while((m=re.exec(html))!==null){opts.push({pageId:m[2],\n"
            + "    selected:/\\bis-selected\\b/.test(m[1]),\n"
            + "    recommended:/\\bis-recommended\\b/.test(m[1])});}\n"
            + "  return {opts, stars:(html.match(/csv-rune-side-star/g)||[]).length};\n"
            + "}\n"
            + "const recNotSel=parse(_csvRuneSidePanelHtml(CHAMP,'A',pages,"
            + "[{buildId:'A',recommendedPageId:'p2'}],'p3'));\n"
            + "const recIsSel=parse(_csvRuneSidePanelHtml(CHAMP,'A',pages,"
            + "[{buildId:'A',recommendedPageId:'p2'}],'p2'));\n"
            # --- save-default round trip -----------------------------------
            + "_csvSaveRuneDefault('Ezreal','A','p9');\n"
            + "_csvSaveRuneDefault('Lux','A','pX');\n"
            + "const rawStore=_store['rc-cs-rune-default']||'';\n"
            + "const reloaded=_csvSavedRuneDefault('Ezreal');\n"
            # --- Phase 6 pushPageId reverse-map (skip pure-auto page) -------
            # Pure mirror of the reverse-map inside _csvPushFollowedRune: pick
            # the build whose pushPageId (or recommendedPageId fallback for a
            # snapshot-seeded build) equals the selected pageId; a pure-auto
            # page (no pushPageId match) picks nothing so the frozen writer
            # keeps it. The whole helper is not extracted (it touches the cache
            # + fetch); the StaticSourceGuard pins its presence in source.
            + "function reverseMap(builds, selPageId){\n"
            + "  const b=(builds||[]).find((x)=>x &&"
            + " String(x.pushPageId||x.recommendedPageId||'')===String(selPageId));\n"
            + "  return b && b.buildId ? b.buildId : null;\n"
            + "}\n"
            + "const pushBuilds=[{buildId:'own',pushPageId:'pOwn',recommendedPageId:'pAuto'},"
            + "{buildId:'path',pushPageId:'pPath',recommendedPageId:'pPath'}];\n"
            + "const seedBuilds=[{buildId:'seed',recommendedPageId:'pSeed'}];\n"
            + "const revmap={picksOwn:reverseMap(pushBuilds,'pOwn'),"
            + "picksPath:reverseMap(pushBuilds,'pPath'),"
            + "picksNothingForAuto:reverseMap(pushBuilds,'pAuto'),"
            + "picksSeedViaRecommended:reverseMap(seedBuilds,'pSeed')};\n"
            + "process.stdout.write(JSON.stringify({prec, discard, recNotSel,"
            + " recIsSel, rawStore, reloaded, revmap}));\n"
        )
        cls._td = tempfile.mkdtemp()
        cls._harness = Path(cls._td) / "rune_follows_harness.mjs"
        cls._harness.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [_NODE, str(cls._harness)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node harness failed ({proc.returncode}): {proc.stderr}")
        cls.result = json.loads(proc.stdout)

    def test_precedence_order(self) -> None:
        prec = self.result["prec"]
        self.assertEqual(prec["override"], "pOver")   # override wins
        self.assertEqual(prec["saved"], "pSaved")     # then savedDefault
        self.assertEqual(prec["rec"], "pRec")         # then recommended

    def test_build_change_discards_unsaved_override(self) -> None:
        d = self.result["discard"]
        self.assertEqual(d["selWhileA"], "pOver")     # override active on A
        self.assertIsNone(d["ovAfter"])               # discarded on change
        self.assertEqual(d["selAfterB"], "pRecB")     # B shows its own rec
        self.assertEqual(d["selBackA"], "pRecA")      # not restored on return

    def test_star_always_on_recommended(self) -> None:
        # rec (p2) != selected (p3): the rec option carries the star + the
        # is-recommended class even though a different page is selected.
        opts = {o["pageId"]: o for o in self.result["recNotSel"]["opts"]}
        self.assertTrue(opts["p2"]["recommended"])
        self.assertFalse(opts["p2"]["selected"])
        self.assertTrue(opts["p3"]["selected"])
        self.assertFalse(opts["p3"]["recommended"])
        self.assertEqual(self.result["recNotSel"]["stars"], 1)
        # rec == selected: the one option carries BOTH markers.
        sel = {o["pageId"]: o for o in self.result["recIsSel"]["opts"]}
        self.assertTrue(sel["p2"]["recommended"])
        self.assertTrue(sel["p2"]["selected"])

    def test_one_option_per_deduped_page(self) -> None:
        # pages had a duplicate p1 -> render collapses to 3 distinct options.
        ids = [o["pageId"] for o in self.result["recNotSel"]["opts"]]
        self.assertEqual(ids, ["p1", "p2", "p3"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_save_default_persists_and_reloads(self) -> None:
        raw = json.loads(self.result["rawStore"])
        self.assertEqual(raw["Ezreal::A"], "p9")
        self.assertEqual(raw["Lux::A"], "pX")          # other champ coexists
        reloaded = self.result["reloaded"]
        self.assertEqual(reloaded, {"A": "p9"})        # filtered to this champ

    def test_pushpage_reverse_map_and_skip_pure_auto(self) -> None:
        # Phase 6: reverse-map the selected pageId to the build whose pushPageId
        # (or recommendedPageId fallback) matches; a pure-auto page picks nothing.
        rm = self.result["revmap"]
        self.assertEqual(rm["picksOwn"], "own")       # own page -> own build
        self.assertEqual(rm["picksPath"], "path")     # path page -> path build
        self.assertIsNone(rm["picksNothingForAuto"])  # pure-auto page -> skip
        # A snapshot-seeded build without pushPageId still matches via the
        # recommendedPageId fallback.
        self.assertEqual(rm["picksSeedViaRecommended"], "seed")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])

    def test_champ_select_js_is_ascii(self) -> None:
        raw = CHAMP_SELECT_JS.read_bytes()
        bad = [i for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"champ_select.js non-ASCII at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
