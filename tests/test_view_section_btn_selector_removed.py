"""RM-1134: the dead `.view-section-btn` selector stays removed.

tests/test_view_section_btn_selector_removed.py

RM-1134 (s144 uiux): `.view-section-btn` was a dead selector. No web/
HTML file and no web/ JS module (literal or string-built) ever put the
class on an element; it survived only as a co-selector in three CSS rules
(header.css base + :hover beside `.view-tab`, and the arcane-theme
`.active` underline list in themes.css). The rules stay for `.view-tab`
(the History scope tabs, the one live user); the dead co-selector is gone.

Guards:
  - no web/ source (html / js / mjs / css) names the class again, so a
    refactor cannot quietly resurrect a rule nothing renders;
  - the `.view-tab` base, :hover and arcane `.active` underline rules the
    co-selector shared are still present, so the removal did not take the
    live selector with it.
The rendered half (History scope tabs keep their fill, text, hit floor and
arcane underline) is pinned by tests/snapshot_panels/
test_tab_bars_selected_state.py and test_view_menu_items.py.
"""
import re
from pathlib import Path
from tests import _css_split

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
HEADER_CSS = "web/css/panels/header.css"  # read via tests/_css_split (RM-726 rule 5)
THEMES_CSS = WEB / "css" / "themes.css"

_SUFFIXES = {".html", ".js", ".mjs", ".css"}
_DEAD = "view-section-btn"


def _web_sources():
    return sorted(p for p in WEB.rglob("*")
                  if p.is_file() and p.suffix in _SUFFIXES)


def _selectors_of_rules(css_text):
    # Selector lists of every rule block, comments stripped, whitespace
    # collapsed. Good enough for flat stylesheets (no nesting in web/css).
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    return [" ".join(m.group(1).split())
            for m in re.finditer(r"([^{}]+)\{", css)]


def test_web_sources_enumerated():
    # Anchor: an empty walk would pass the absence check vacuously.
    srcs = _web_sources()
    assert len(srcs) > 50, len(srcs)
    assert set(_css_split.family_paths(HEADER_CSS)) <= set(srcs)
    assert THEMES_CSS in srcs


def test_no_web_source_names_view_section_btn():
    hits = []
    for p in _web_sources():
        text = p.read_text(encoding="utf-8", errors="replace")
        if _DEAD in text:
            hits.append(p.relative_to(REPO).as_posix())
    assert hits == [], f"dead selector {_DEAD!r} named in: {hits}"


def test_view_tab_base_and_hover_rules_survive():
    sels = _selectors_of_rules(_css_split.family_text(HEADER_CSS))
    assert ".view-tab" in sels, "History .view-tab base rule lost"
    assert ".view-tab:hover" in sels, "History .view-tab:hover rule lost"
    assert ".view-tab.active" in sels, "History .view-tab.active rule lost"


def test_arcane_active_underline_keeps_view_tab():
    sels = _selectors_of_rules(THEMES_CSS.read_text(encoding="utf-8"))
    underline = [s for s in sels
                 if ':root[data-theme="arcane"] .view-tab.active' in s]
    assert underline, "arcane .view-tab.active underline rule lost"
    # Still grouped with the other selected-tab bars it shared the rule with.
    assert any(':root[data-theme="arcane"] .home-mode-tab.active' in s
               and ':root[data-theme="arcane"] .view-menu-item.active' in s
               for s in underline)
