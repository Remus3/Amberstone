"""
tests/snapshot_panels/test_user_builds_rune_tabs.py
RM-1084 (s144 uiux): the User Builds rune page builder paints two tab
bars, #ub-rp-tabs (primary tree) and #ub-rp-sec-trees (secondary tree), each
a role="tablist" in web/index.html. Measured defects at the time of filing:
  - the primary tabs (main.js _ubRpRenderTabs) carried role="tab" but never
    aria-selected, so the selected tree was announced as unselected;
  - the secondary bar's buttons (_ubRpRenderSecTrees) carried NO role at all,
    so the tablist had no tab children (ARIA required-children);
  - neither button drew the one system focus ring (tokens.css --focus-ring),
    only the UA outline;
  - every tab's caption was --text, selected or not, so the selected tree
    was no brighter than its siblings (the RM-1083 salience rule).

Drive path: /?ui_mock=1#user-builds, pick Tristana, + Add build, then pick
Precision primary and Sorcery secondary. /api/dictionary/runes is served the
TRACKED DDragon dump data/meta/ddragon_runes.json (the real route's file,
dashboard/routes_dictionary.py _RUNES_PATH), so the five trees are real data.

Colours are RESOLVED, not grepped (canvas readback over the composited
ancestor backgrounds, as in test_tab_bars_selected_state.py), with
transitions off for the read. The caption colour is read off the caption
span, the node that actually paints the text.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_tab_bars_selected_state import (
    _THEMES,
    _lum,
    _ratio,
)

VIEWPORT = {"width": 1920, "height": 920}
_RUNES = Path(__file__).resolve().parents[2] / "data" / "meta" / "ddragon_runes.json"
_TREES = sorted(t["key"] for t in json.loads(_RUNES.read_text(encoding="utf-8")))
_PRIMARY = "Precision"
_SECONDARY = "Sorcery"
_BARS = {
    "primary": "#ub-rp-tabs > button",
    "secondary": "#ub-rp-sec-trees > button",
}

_MEASURE = """
([sel, themes]) => {
  const root = document.documentElement;
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const g = cv.getContext('2d', {willReadFrequently: true});
  const px = (layers) => {
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = '#000'; g.fillRect(0, 0, 1, 1);
    for (const c of layers) { g.fillStyle = c; g.fillRect(0, 0, 1, 1); }
    const d = g.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
  };
  const stack = (el) => {
    const out = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      out.unshift(getComputedStyle(n).backgroundColor);
    }
    return out;
  };
  if (document.activeElement) document.activeElement.blur();
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    out[t] = Array.from(document.querySelectorAll(sel)).map((el) => {
      const cap = el.querySelector('span') || el;
      const fill = px(stack(el));
      const r = el.getBoundingClientRect();
      return {
        label: (el.textContent || '').trim(),
        selected: el.classList.contains('active'),
        disabled: el.disabled,
        fill,
        text: px(['rgb(' + fill.join(',') + ')', getComputedStyle(cap).color]),
        width: r.width,
        height: r.height,
      };
    });
  }
  return out;
}
"""


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VIEWPORT)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    body = _RUNES.read_bytes()
    page.route(
        "**/api/dictionary/runes",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body,
        ),
    )
    page.goto(
        mock_server.url + "/?ui_mock=1#user-builds",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }"
    )
    page.fill("#ub-champion-input", "Tristana")
    page.dispatch_event("#ub-champion-input", "change")
    page.wait_for_selector(".ub-build-row", timeout=10_000)
    page.click("#ub-add-btn")
    page.wait_for_function(
        f"document.querySelectorAll({_BARS['primary']!r}).length === {len(_TREES)}",
        timeout=10_000,
    )
    page.click(f"#ub-rp-tabs > button[data-tree={_PRIMARY!r}]")
    page.click(f"#ub-rp-sec-trees > button[data-tree={_SECONDARY!r}]")
    page.wait_for_function(
        f"document.querySelector('#ub-rp-sec-trees > button.active')"
        f" && document.querySelector('#ub-rp-sec-trees > button.active')"
        f".dataset.tree === {_SECONDARY!r}",
        timeout=5_000,
    )
    return ctx, page, errors


@pytest.fixture(scope="module")
def rendered(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        aria = page.evaluate(
            """(bars) => Object.fromEntries(Object.entries(bars).map(([k, sel]) => [
              k, Array.from(document.querySelectorAll(sel)).map((el) => ({
                tree: el.dataset.tree,
                role: el.getAttribute('role'),
                selected: el.getAttribute('aria-selected'),
                active: el.classList.contains('active'),
                disabled: el.disabled,
              })),
            ]))""",
            _BARS,
        )
        lists = page.evaluate(
            """() => ['#ub-rp-tabs', '#ub-rp-sec-trees'].map(
              (s) => document.querySelector(s).getAttribute('role'))"""
        )
        # Keyboard modality, so a programmatic focus() matches
        # :focus-visible as a Tab would.
        page.keyboard.press("Shift")
        rings = page.evaluate(
            """(bars) => {
              const probe = document.createElement('div');
              probe.style.boxShadow = 'var(--focus-ring)';
              document.body.appendChild(probe);
              const ring = getComputedStyle(probe).boxShadow;
              probe.remove();
              const sel = Object.values(bars).join(', ');
              return Array.from(document.querySelectorAll(sel))
                .filter((el) => !el.disabled)
                .map((el) => {
                  el.focus();
                  const cs = getComputedStyle(el);
                  return {
                    tree: el.dataset.tree,
                    focused: el === document.activeElement,
                    visible: el.matches(':focus-visible'),
                    outline: cs.outlineStyle,
                    shadow: cs.boxShadow,
                    ring,
                  };
                });
            }""",
            _BARS,
        )
        colours = {k: page.evaluate(_MEASURE, [sel, _THEMES]) for k, sel in _BARS.items()}
    finally:
        page.close()
        ctx.close()
    return {"aria": aria, "lists": lists, "rings": rings, "colours": colours,
            "errors": errors}


def test_rendered_without_errors(rendered):
    assert not rendered["errors"], rendered["errors"][:3]
    assert rendered["lists"] == ["tablist", "tablist"], rendered["lists"]
    for bar, tabs in rendered["aria"].items():
        assert sorted(t["tree"] for t in tabs) == _TREES, (bar, tabs)


@pytest.mark.parametrize("bar,picked", [("primary", _PRIMARY), ("secondary", _SECONDARY)])
def test_every_tree_button_is_a_tab_with_aria_selected(rendered, bar, picked):
    tabs = rendered["aria"][bar]
    for t in tabs:
        assert t["role"] == "tab", f"{bar}: {t['tree']} role {t['role']!r}"
        want = "true" if t["tree"] == picked else "false"
        assert t["selected"] == want, (
            f"{bar}: {t['tree']} aria-selected {t['selected']!r}, want {want!r}"
        )
        # aria-selected and the .active paint never disagree.
        assert (t["selected"] == "true") == t["active"], (bar, t)


def test_secondary_bar_disables_the_primary_tree(rendered):
    sec = {t["tree"]: t for t in rendered["aria"]["secondary"]}
    assert sec[_PRIMARY]["disabled"], sec[_PRIMARY]
    assert [k for k, t in sec.items() if t["disabled"]] == [_PRIMARY], sec


def test_tree_tabs_draw_the_system_focus_ring(rendered):
    rings = rendered["rings"]
    # Five primary tabs plus four enabled secondary tabs.
    assert len(rings) == 2 * len(_TREES) - 1, rings
    for r in rings:
        assert r["ring"] not in ("", "none"), f"--focus-ring resolved {r['ring']!r}"
        assert r["focused"] and r["visible"], f"{r['tree']}: not :focus-visible"
        assert r["outline"] == "none", f"{r['tree']}: outline {r['outline']!r}"
        assert r["shadow"] == r["ring"], (
            f"{r['tree']}: focused shadow {r['shadow']!r} != ring {r['ring']!r}"
        )


_CASES = [(b, t) for b in _BARS for t in _THEMES]


def _split(rendered, bar, theme):
    tabs = rendered["colours"][bar][theme]
    assert len(tabs) == len(_TREES), f"{bar}/{theme}: {len(tabs)} tabs"
    assert all(t["width"] > 0 and t["height"] > 0 for t in tabs), bar
    sel = [t for t in tabs if t["selected"]]
    assert len(sel) == 1, f"{bar}/{theme}: selected {[t['label'] for t in sel]}"
    return sel[0], [t for t in tabs if not t["selected"]]


def test_colour_readback_varies_by_theme(rendered):
    fills = {tuple(t["fill"]) for tabs in rendered["colours"]["primary"].values()
             for t in tabs if not t["selected"]}
    assert len(fills) >= 3, f"tab fills did not vary by theme: {fills}"


@pytest.mark.parametrize("bar,theme", _CASES)
def test_selected_tree_has_its_own_fill(rendered, bar, theme):
    sel, other = _split(rendered, bar, theme)
    for o in other:
        assert sel["fill"] != o["fill"], (
            f"{bar}/{theme}: selected {sel['label']!r} fill {sel['fill']} "
            f"matches {o['label']!r}"
        )


@pytest.mark.parametrize("bar,theme", _CASES)
def test_selected_tree_caption_is_the_brightest(rendered, bar, theme):
    sel, other = _split(rendered, bar, theme)
    for o in other:
        assert _lum(sel["text"]) > _lum(o["text"]), (
            f"{bar}/{theme}: selected {sel['label']!r} text {sel['text']} "
            f"(L={_lum(sel['text']):.3f}) is not brighter than {o['label']!r} "
            f"text {o['text']} (L={_lum(o['text']):.3f})"
        )


@pytest.mark.parametrize("bar,theme", _CASES)
def test_tree_caption_clears_aa_on_its_own_fill(rendered, bar, theme):
    sel, other = _split(rendered, bar, theme)
    # A disabled control is exempt from WCAG 1.4.3 (the secondary bar's
    # copy of the primary tree), so it is not measured here.
    for t in [sel, *other]:
        if t["disabled"]:
            continue
        r = _ratio(t["text"], t["fill"])
        assert r >= 4.5, (
            f"{bar}/{theme}: {t['label']!r} text {t['text']} on its fill "
            f"{t['fill']} is {r:.2f}:1"
        )
