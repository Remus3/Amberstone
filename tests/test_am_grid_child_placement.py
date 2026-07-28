# arch: R213 - every visible .am-grid child must carry an explicit grid placement | section=web | frozen=no
"""Structural guard over the active-match dashboard grid.

`#view-active-match .am-grid` is a named-area grid (`grid-template-areas`).
A direct child with no `grid-area` and no hide rule is auto-placed by the
browser into an IMPLICIT row: a position no stylesheet declares, that no
reviewer can find by grepping, and that silently re-flows the day the template
areas change.

R213 measured exactly one such child: `#aram-balance-panel`, whose own markup
comment claimed "active_match.css pins it to the left column under BUILD" while
`active_match.css` never mentioned it. (Measured caveat, so no one re-derives a
stronger claim from this file: the implicit row did NOT squeeze the 1fr panes -
the grid is content-sized by the MAP pane - so this is a declared-placement and
bounded-height fix, not a height recovery.) The guard below derives the
population from the markup + the stylesheets on disk rather than hardcoding
that one id, so the next unplaced child fails here instead of in a live game.

Valid dispositions for a direct child:
  HIDDEN_ATTR - carries `hidden` (overlay-only mount, lifted to position:fixed
                by overlay_layout.js and never in dashboard grid flow)
  CSS_HIDDEN  - a stylesheet sets `display: none` for it
  PLACED      - a stylesheet assigns it a `grid-area`
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "web" / "index.html"
CSS_DIR = REPO / "web" / "css"

# Measured 2026-07-28. A change here means the grid gained or lost a child and
# the dispositions below must be re-read, not silently re-baselined.
EXPECTED_DIRECT_CHILDREN = 13

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}


class _AmGridChildren(HTMLParser):
    """Collects the DIRECT children of the first `.am-grid` element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._grid_depth: int | None = None
        self.children: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self._grid_depth is not None and self._depth == self._grid_depth + 1:
            self.children.append({
                "tag": tag,
                "id": a.get("id") or "",
                "classes": classes,
                "hidden": "hidden" in a,
                "style": (a.get("style") or ""),
            })
        if self._grid_depth is None and "am-grid" in classes:
            self._grid_depth = self._depth
        self._depth += 1

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        self._depth -= 1
        if self._grid_depth is not None and self._depth == self._grid_depth:
            self._grid_depth = None


def _css_rules() -> list[tuple[str, str]]:
    """(selector_text, declaration_body) for every rule under web/css."""
    rules: list[tuple[str, str]] = []
    for path in sorted(CSS_DIR.rglob("*.css")):
        text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"), flags=re.S)
        for chunk in text.split("}"):
            if "{" not in chunk:
                continue
            sel, _, body = chunk.rpartition("{")
            sel = sel.rsplit("}", 1)[-1]
            rules.append((" ".join(sel.split()), body))
    return rules


def _selector_tokens(child: dict) -> list[str]:
    toks = ["#" + child["id"]] if child["id"] else []
    toks += ["." + c for c in child["classes"]]
    return toks


def _disposition(child: dict, rules: list[tuple[str, str]]) -> str:
    if child["hidden"]:
        return "HIDDEN_ATTR"
    toks = _selector_tokens(child)
    if not toks:
        return "UNPLACED"
    hidden = False
    for sel, body in rules:
        if not any(t in sel for t in toks):
            continue
        flat = "".join(body.split())
        # A placement outranks a hide rule: a pane can be display:none in one
        # shell and grid-placed in another, and only the placement matters here.
        if "grid-area:" in flat:
            return "PLACED"
        hidden = hidden or "display:none" in flat
    return "CSS_HIDDEN" if hidden else "UNPLACED"


def _children() -> list[dict]:
    parser = _AmGridChildren()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser.children


def test_am_grid_population_is_the_measured_one():
    assert len(_children()) == EXPECTED_DIRECT_CHILDREN


def test_every_visible_am_grid_child_has_an_explicit_placement():
    rules = _css_rules()
    unplaced = [
        (c["id"] or " ".join(c["classes"]))
        for c in _children()
        if _disposition(c, rules) == "UNPLACED"
    ]
    assert unplaced == [], (
        "auto-placed into an implicit .am-grid row (add a grid-area, a "
        f"display:none rule, or the hidden attribute): {unplaced}"
    )


def test_the_guard_can_actually_fail():
    """Non-tautology proof: an invented child with no CSS is UNPLACED."""
    rules = _css_rules()
    ghost = {"tag": "div", "id": "am-r213-ghost", "classes": [],
             "hidden": False, "style": ""}
    assert _disposition(ghost, rules) == "UNPLACED"
    real = {"tag": "div", "id": "", "classes": ["am-pane", "am-pane-build"],
            "hidden": False, "style": ""}
    assert _disposition(real, rules) == "PLACED"
