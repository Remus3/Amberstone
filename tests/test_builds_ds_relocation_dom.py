"""QA 2026-07-03 B20/B22: DS profile / knobs / stat-check relocation guard.

Operator rulings B20 + B22 (docs/qa/CHAMP_SELECT_QA_2026-07-03.md) move the
three remaining champ-select DS cards - DS profile (csv-sugg-ds-profile),
DS knobs (csv-ds-knobs), DS stat-check (csv-ds-statcheck) - onto the
Builds/DS surface: the Active Match BUILD pane (#view-active-match
.am-pane-build), joining the CS3 relocated family (combo / sweep / matchup /
relscore, commit 074c68d0). This mirrors the CS3 pattern exactly: same mount
ids kept, render fns unchanged, each card fed the SAME synthetic
champ-select-shaped state (_amDsSyntheticCs) built from the LIVE champion
the operator is playing.

The champ-select SIDE of the move (mount-div removal + call-site removal in
champ_select.js) is slice A's deliverable and is guarded in its tests; this
file pins the RECEIVING side only:

  - the 3 mount ids are PRESENT in the #view-active-match region, inside the
    BUILD pane, clustered AFTER the CS3 family, hidden by default.
  - active_match.js imports + invokes each module's existing render fn and
    feeds it the synthetic live-champion cs.
  - 5-phase static basics on the placements: tokens-only font sizes in the
    3 panel stylesheets (TYPOGRAPHY), knob strips keep their --hit-min
    reservation + no pointer rule without --hit-min (HIT-TARGETS), ASCII
    hygiene on every touched file (ASCII). STRUCTURE / HIERARCHY are the
    region-slice placement checks above.

Grep + region-slice smoke checks - cheap, fast. Mirrors
tests/test_cs3_panel_relocation_dom.py + the floor-guard precedent in
tests/test_active_match_child_panel_floor_guard.py.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
ACTIVE_MATCH_JS = WEB / "js" / "panels" / "active_match.js"
PANEL_CSS = (
    WEB / "css" / "panels" / "ds_profile.css",
    WEB / "css" / "panels" / "ds_knobs.css",
    WEB / "css" / "panels" / "ds_statcheck.css",
)

# The three cards relocated by QA B20/B22 (same ids as their champ-select
# incarnation - the CS3 precedent keeps ids so render fns need no change).
RELOCATED_MOUNT_IDS = (
    'id="csv-sugg-ds-profile"',
    'id="csv-ds-knobs"',
    'id="csv-ds-statcheck"',
)

# The CS3 family already living in the BUILD pane; the new cards cluster
# after it.
CS3_LAST_MOUNT_ID = 'id="csv-ds-relscore"'


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _region(html: str, start_marker: str, end_marker: str) -> str:
    start = html.index(start_marker)
    end = html.index(end_marker)
    assert start < end, f"{start_marker!r} not before {end_marker!r}"
    return html[start:end]


class RegionPlacementTests(unittest.TestCase):
    """STRUCTURE + HIERARCHY: mounts live in the BUILD pane of the
    active-match region, clustered with (after) the CS3 family, hidden."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(INDEX_HTML)
        cls.am_region = _region(
            cls.html, 'id="view-active-match"', 'id="activity-strip"'
        )
        # BUILD pane slice: from the build pane opener to the next pane
        # (the overlay-only ovds pane).
        cls.build_pane = _region(
            cls.am_region, "am-pane-build", 'id="am-pane-ovds"'
        )

    def test_relocated_mounts_present_in_active_match(self) -> None:
        for mid in RELOCATED_MOUNT_IDS:
            self.assertIn(
                mid, self.am_region,
                f"{mid} should be mounted in the active-match region "
                "(QA B20/B22)",
            )

    def test_relocated_mounts_inside_build_pane(self) -> None:
        for mid in RELOCATED_MOUNT_IDS:
            self.assertIn(
                mid, self.build_pane,
                f"{mid} should sit inside the BUILD pane (CS3 family home)",
            )

    def test_relocated_mounts_cluster_after_cs3_family(self) -> None:
        anchor = self.build_pane.index(CS3_LAST_MOUNT_ID)
        for mid in RELOCATED_MOUNT_IDS:
            self.assertGreater(
                self.build_pane.index(mid), anchor,
                f"{mid} should cluster after the CS3 family "
                f"({CS3_LAST_MOUNT_ID})",
            )

    def test_relocated_mounts_hidden_by_default(self) -> None:
        for mid in RELOCATED_MOUNT_IDS:
            idx = self.build_pane.index(mid)
            self.assertIn(
                "hidden", self.build_pane[idx:idx + 80],
                f"{mid} must ship hidden (data-gated, honest no-data)",
            )

    def test_mounts_keep_their_panel_classes(self) -> None:
        # The per-panel stylesheets key off these classes; the relocation
        # must carry them so the cards stay styled on the new surface.
        for cls_name in ('class="ds-profile"', 'class="ds-knobs"',
                         'class="ds-statcheck"'):
            self.assertIn(cls_name, self.build_pane)


class ActiveMatchInvocationTests(unittest.TestCase):
    """active_match.js renders the three cards off the SAME synthetic
    live-champion cs the CS3 family reads (_amDsSyntheticCs)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.am = _read(ACTIVE_MATCH_JS)

    def test_imports_profile_render_entry(self) -> None:
        self.assertIn("renderDsProfileForChampSelect", self.am)
        self.assertIn("from './ds_profile.js'", self.am)

    def test_imports_knobs_render_entry(self) -> None:
        self.assertIn("renderDsKnobs", self.am)

    def test_imports_statcheck_render_entry(self) -> None:
        self.assertIn("renderDsStatcheck", self.am)
        self.assertIn("from './ds_statcheck.js'", self.am)

    def test_profile_fed_synthetic_cs(self) -> None:
        self.assertRegex(
            self.am,
            re.compile(r"renderDsProfileForChampSelect\(\s*synthetic"),
            "ds-profile must read the synthetic live-champion cs",
        )

    def test_knobs_fed_synthetic_cs(self) -> None:
        self.assertRegex(
            self.am,
            re.compile(r"renderDsKnobs\([^)]*synthetic"),
            "ds-knobs must read the synthetic live-champion cs",
        )

    def test_statcheck_fed_synthetic_cs(self) -> None:
        self.assertRegex(
            self.am,
            re.compile(r"renderDsStatcheck\([^)]*synthetic"),
            "ds-statcheck must read the synthetic live-champion cs",
        )

    def test_profile_scheduler_wired(self) -> None:
        # On-land repaint parity with the CS3 sweep/matchup schedulers.
        self.assertIn("setDsProfileScheduler", self.am)

    def test_statcheck_scheduler_wired(self) -> None:
        self.assertIn("setDsStatcheckScheduler", self.am)

    def test_cards_hidden_when_no_live_champion(self) -> None:
        # The between-games hide list must include the three new mounts.
        idx = self.am.index("function _amRenderDsCluster")
        body = self.am[idx:idx + 2500]
        for mount in ("csv-sugg-ds-profile", "csv-ds-knobs",
                      "csv-ds-statcheck"):
            self.assertIn(
                mount, body,
                f"{mount} must be handled inside _amRenderDsCluster "
                "(render + between-games hide)",
            )

    def test_synthetic_helper_still_exists(self) -> None:
        self.assertIn("_amDsSyntheticCs", self.am)


class TypographyTokenTests(unittest.TestCase):
    """TYPOGRAPHY: every font-size in the three panel stylesheets is a
    design token (var(--fs-*)) - no raw px sizes ride along to the new
    surface."""

    _FONT_RE = re.compile(r"font-size:\s*([^;]+);")

    def test_font_sizes_are_tokens_only(self) -> None:
        for css_path in PANEL_CSS:
            css = _read(css_path)
            for m in self._FONT_RE.finditer(css):
                self.assertIn(
                    "var(--fs-", m.group(1),
                    f"{css_path.name}: font-size {m.group(1)!r} is not a "
                    "design token",
                )

    def test_scan_has_teeth(self) -> None:
        self.assertIsNotNone(self._FONT_RE.search("font-size: 12px;"))
        m = self._FONT_RE.search("font-size: var(--fs-xs, 16px);")
        self.assertIn("var(--fs-", m.group(1))


class HitTargetTests(unittest.TestCase):
    """HIT-TARGETS: the interactive knob strips keep their --hit-min
    reservation; no cursor:pointer rule ships without --hit-min."""

    @staticmethod
    def _pointer_rules_without_hitmin(css: str) -> list[str]:
        bad: list[str] = []
        for chunk in css.split("}"):
            if "{" not in chunk:
                continue
            sel, body = chunk.split("{", 1)
            if "cursor: pointer" not in body and "cursor:pointer" not in body:
                continue
            if "var(--hit-min" not in body:
                bad.append(sel.strip())
        return bad

    def test_knob_inputs_reserve_hit_min(self) -> None:
        for name in ("ds_knobs.css", "ds_statcheck.css"):
            css = _read(WEB / "css" / "panels" / name)
            self.assertIn(
                "var(--hit-min", css,
                f"{name}: knob inputs must reserve min-height "
                "var(--hit-min)",
            )

    def test_no_pointer_rule_without_hitmin(self) -> None:
        for css_path in PANEL_CSS:
            self.assertEqual(
                [], self._pointer_rules_without_hitmin(_read(css_path)),
                f"{css_path.name}: cursor:pointer rule(s) lack "
                "min-height var(--hit-min)",
            )

    def test_pointer_scan_has_teeth(self) -> None:
        self.assertEqual(
            [".btn"],
            self._pointer_rules_without_hitmin(".btn { cursor: pointer; }"),
        )
        self.assertEqual(
            [],
            self._pointer_rules_without_hitmin(
                ".btn { cursor: pointer; min-height: var(--hit-min); }"
            ),
        )


class AsciiHygieneTests(unittest.TestCase):
    """ASCII: no em/en-dashes or smart quotes in any touched file (the
    CLAUDE.md hard rule). BAD set via chr() so this file stays clean."""

    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D), chr(0x2026))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_index_html_is_ascii(self) -> None:
        self.assertEqual(self._scan(INDEX_HTML), [])

    def test_active_match_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(ACTIVE_MATCH_JS), [])

    def test_panel_css_files_are_ascii(self) -> None:
        for css_path in PANEL_CSS:
            self.assertEqual(self._scan(css_path), [], css_path.name)

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()
