"""
tests/snapshot_panels/test_lobby_mains_tabs.py
RM-1084 residue (s144 uiux): the Lobby YOUR MAINS / PARTY MAINS tab pair
(.lv-mainchamps-tabs .lv-mc-tab, web/index.html, styled in
web/css/panels/header.css, toggled by main.js _renderMains) joins the tab
bar sweep of test_tab_bars_selected_state.py, measured under
/?ui_mock=1#lobby at 1920x920 on all six themes.

The bar is held to the same three rules as every other tab bar (CUE,
SALIENCE, AA on its own fill, resolved through the canvas readback that
module owns), plus the two the 5-phase audit asks of every clickable:
  - FOCUS: a keyboard-focused tab, selected or not, draws the one system
    ring (--focus-ring as its box-shadow, outline none), never the UA
    outline alone.
  - HIT: each tab is at least --hit-min tall.
"""
import pytest

from tests.snapshot_panels.test_tab_bars_selected_state import (
    _MEASURE,
    _THEMES,
    _lum,
    _open,
    _ratio,
)

_SEL = ".lv-mainchamps-tabs .lv-mc-tab"


@pytest.fixture(scope="module")
def lobby_page(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "lobby", None, _SEL)
    try:
        yield page, errors
    finally:
        page.close()
        ctx.close()


@pytest.fixture(scope="module")
def measured(lobby_page):
    page, errors = lobby_page
    by_theme = page.evaluate(_MEASURE, [_SEL, _THEMES])
    page.evaluate("document.documentElement.removeAttribute('data-theme')")
    return by_theme, errors


def _split(measured, theme):
    by_theme, _errors = measured
    tabs = by_theme[theme]
    sel = [t for t in tabs if t["selected"]]
    other = [t for t in tabs if not t["selected"]]
    assert [t["label"] for t in tabs] == ["YOUR MAINS", "PARTY MAINS"], tabs
    assert all(t["width"] > 0 and t["height"] > 0 for t in tabs)
    assert len(sel) == 1 and len(other) == 1, [t["label"] for t in sel]
    assert not any(t["focused"] for t in tabs), f"{theme}: focus held"
    return sel[0], other[0]


def test_measured_every_theme(measured):
    by_theme, errors = measured
    assert sorted(by_theme) == sorted(_THEMES)
    assert not errors, errors[:3]
    fills = {tuple(t["fill"]) for tabs in by_theme.values() for t in tabs}
    assert len(fills) >= 3, f"tab fills did not vary by theme: {fills}"


@pytest.mark.parametrize("theme", _THEMES)
def test_selected_tab_carries_its_own_fill(measured, theme):
    sel, other = _split(measured, theme)
    assert sel["fill"] != other["fill"], (
        f"{theme}: selected fill {sel['fill']} == unselected {other['fill']}"
    )


@pytest.mark.parametrize("theme", _THEMES)
def test_selected_tab_is_the_brighter_one(measured, theme):
    sel, other = _split(measured, theme)
    assert _lum(sel["text"]) > _lum(other["text"]), (
        f"{theme}: selected text {sel['text']} not brighter than "
        f"{other['label']!r} text {other['text']}"
    )


@pytest.mark.parametrize("theme", _THEMES)
def test_tab_text_clears_aa_on_its_own_fill(measured, theme):
    for t in _split(measured, theme):
        r = _ratio(t["text"], t["fill"])
        assert r >= 4.5, (
            f"{theme}: {t['label']!r} text {t['text']} on fill {t['fill']} "
            f"is {r:.2f}:1"
        )


def test_tabs_clear_the_hit_floor(lobby_page):
    page, _errors = lobby_page
    rows = page.evaluate(
        """(sel) => {
          const probe = document.createElement('div');
          probe.style.height = 'var(--hit-min)';
          document.body.appendChild(probe);
          const floor = probe.getBoundingClientRect().height;
          probe.remove();
          return Array.from(document.querySelectorAll(sel)).map((el) => ({
            label: (el.textContent || '').trim(),
            height: el.getBoundingClientRect().height,
            floor,
          }));
        }""",
        _SEL,
    )
    assert len(rows) == 2
    for r in rows:
        assert r["floor"] >= 40, f"--hit-min resolved {r['floor']}"
        assert r["height"] >= r["floor"], (
            f"{r['label']!r} is {r['height']}px tall, floor {r['floor']}px"
        )


def test_tabs_draw_the_system_focus_ring(lobby_page):
    page, _errors = lobby_page
    # A key press puts Chromium in keyboard modality, so a programmatic
    # focus() then matches :focus-visible as a Tab would.
    page.keyboard.press("Shift")
    rows = page.evaluate(
        """(sel) => {
          const probe = document.createElement('div');
          probe.style.boxShadow = 'var(--focus-ring)';
          document.body.appendChild(probe);
          const ring = getComputedStyle(probe).boxShadow;
          probe.remove();
          const out = Array.from(document.querySelectorAll(sel)).map((el) => {
            el.focus();
            const cs = getComputedStyle(el);
            return {
              label: (el.textContent || '').trim(),
              selected: el.getAttribute('aria-selected') === 'true',
              visible: el.matches(':focus-visible'),
              outline: cs.outlineStyle,
              shadow: cs.boxShadow,
              ring,
            };
          });
          if (document.activeElement) document.activeElement.blur();
          return out;
        }""",
        _SEL,
    )
    assert [r["selected"] for r in rows] == [True, False], rows
    for r in rows:
        assert r["ring"] not in ("", "none"), f"--focus-ring resolved {r['ring']!r}"
        assert r["visible"], f"{r['label']!r} did not match :focus-visible"
        assert r["outline"] == "none", f"{r['label']!r} outline {r['outline']!r}"
        assert r["shadow"] == r["ring"], (
            f"{r['label']!r} focused shadow {r['shadow']!r} != ring {r['ring']!r}"
        )
