"""
tests/snapshot_panels/test_view_menu_items.py
RM-1084 last residue (s144 uiux): the title dropdown's view menu
(#view-menu .view-menu-item, web/index.html, styled in
web/css/panels/header.css, marked by main.js _viewUpdateMenuActive) joins
the tab bar sweep of test_tab_bars_selected_state.py. Measured with the menu
OPEN under /?ui_mock=1#history at 1920x920 on all six themes; the History
row is the current view.

The view rows are held to the rules every tab bar meets (CUE, SALIENCE, AA
on its own fill, resolved through the canvas readback that module owns),
plus what the 5-phase audit asks of every clickable and what a menu owes a
screen reader:
  - FOCUS: a keyboard-focused row, current or not, draws the one system ring
    (--focus-ring as its box-shadow, outline none), never a private outline.
  - HIT: each row, the Auto row included, is at least --hit-min tall.
  - CURRENT: the current view's row carries aria-current="page" and no other
    row does, so the cue is not colour-only.
The Auto row is a different kind of action (dashed border, its own colour);
it is held to HIT and FOCUS only, never counted as a view row.
"""
import pytest

from tests.snapshot_panels.test_tab_bars_selected_state import (
    _MEASURE,
    _THEMES,
    _lum,
    _open,
    _ratio,
)

_VIEW = "history"
_ROWS = "#view-menu .view-menu-item:not(.view-menu-clear)"
_ALL = "#view-menu .view-menu-item"
_LABELS = [
    "Home", "Pre-Game Lobby", "Champ Select", "Active Match",
    "Post Game Review", "Session", "History", "Replay",
    "User Builds", "Build Insights", "Settings",
]


@pytest.fixture(scope="module")
def menu_page(mock_server, pw_browser):
    ctx, page, errors = _open(
        pw_browser, mock_server, _VIEW, None, "#history-scope-tabs .view-tab",
    )
    try:
        page.click("#view-trigger")
        page.wait_for_function(
            f"document.querySelector({_ALL!r}).getBoundingClientRect().width > 0",
            timeout=10_000,
        )
        yield page, errors
    finally:
        page.close()
        ctx.close()


@pytest.fixture(scope="module")
def measured(menu_page):
    page, errors = menu_page
    by_theme = page.evaluate(_MEASURE, [_ROWS, _THEMES])
    page.evaluate("document.documentElement.removeAttribute('data-theme')")
    return by_theme, errors


def _split(measured, theme):
    by_theme, _errors = measured
    rows = by_theme[theme]
    sel = [t for t in rows if t["selected"]]
    other = [t for t in rows if not t["selected"]]
    # Anchors: the full row list in order, every row laid out, exactly the
    # History row current, none focused (a shadow below is the row's own).
    assert [t["label"] for t in rows] == _LABELS, [t["label"] for t in rows]
    assert all(t["width"] > 0 and t["height"] > 0 for t in rows)
    assert [t["label"] for t in sel] == ["History"], [t["label"] for t in sel]
    assert not any(t["focused"] for t in rows), f"{theme}: focus held"
    return sel[0], other


def test_measured_every_theme(measured):
    by_theme, errors = measured
    assert sorted(by_theme) == sorted(_THEMES)
    assert not errors, errors[:3]
    fills = {tuple(t["fill"]) for rows in by_theme.values() for t in rows}
    assert len(fills) >= 3, f"row fills did not vary by theme: {fills}"


@pytest.mark.parametrize("theme", _THEMES)
def test_current_row_carries_its_own_fill(measured, theme):
    sel, other = _split(measured, theme)
    for o in other:
        assert sel["fill"] != o["fill"], (
            f"{theme}: current fill {sel['fill']} == {o['label']!r} {o['fill']}"
        )


@pytest.mark.parametrize("theme", _THEMES)
def test_current_row_is_the_brightest(measured, theme):
    sel, other = _split(measured, theme)
    for o in other:
        assert _lum(sel["text"]) > _lum(o["text"]), (
            f"{theme}: current text {sel['text']} (L={_lum(sel['text']):.3f}) "
            f"not brighter than {o['label']!r} text {o['text']} "
            f"(L={_lum(o['text']):.3f})"
        )


@pytest.mark.parametrize("theme", _THEMES)
def test_row_text_clears_aa_on_its_own_fill(measured, theme):
    sel, other = _split(measured, theme)
    for t in [sel, *other]:
        r = _ratio(t["text"], t["fill"])
        assert r >= 4.5, (
            f"{theme}: {t['label']!r} text {t['text']} on fill {t['fill']} "
            f"is {r:.2f}:1"
        )


def test_only_the_current_row_is_announced_current(menu_page):
    page, _errors = menu_page
    rows = page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel)).map((el) => [
          (el.textContent || '').trim(), el.getAttribute('aria-current'),
        ])""",
        _ALL,
    )
    assert len(rows) == len(_LABELS) + 1, rows
    for label, cur in rows:
        want = "page" if label == "History" else None
        assert cur == want, f"{label!r} aria-current {cur!r}, want {want!r}"


def test_rows_meet_the_type_floor_and_stay_in_the_viewport(menu_page):
    # TYPOGRAPHY: every row's computed size is at least --fs-xs (it was a
    # hard 15px). STRUCTURE: the open menu, sized to its widest row, stays
    # inside the 1920x920 viewport with no row clipped or wrapped.
    page, _errors = menu_page
    got = page.evaluate(
        """(sel) => {
          const probe = document.createElement('div');
          probe.style.fontSize = 'var(--fs-xs)';
          document.body.appendChild(probe);
          const floor = parseFloat(getComputedStyle(probe).fontSize);
          probe.remove();
          const menu = document.getElementById('view-menu').getBoundingClientRect();
          const rows = Array.from(document.querySelectorAll(sel)).map((el) => ({
            label: (el.textContent || '').trim(),
            size: parseFloat(getComputedStyle(el).fontSize),
            clipped: el.scrollWidth > el.clientWidth,
          }));
          return {floor, rows, right: menu.right, bottom: menu.bottom,
                  vw: innerWidth, vh: innerHeight};
        }""",
        _ALL,
    )
    assert got["floor"] >= 16, f"--fs-xs resolved {got['floor']}"
    assert len(got["rows"]) == len(_LABELS) + 1
    for r in got["rows"]:
        assert r["size"] >= got["floor"], f"{r['label']!r} is {r['size']}px"
        assert not r["clipped"], f"{r['label']!r} clips its label"
    assert got["right"] <= got["vw"] and got["bottom"] <= got["vh"], got


def test_rows_clear_the_hit_floor(menu_page):
    page, _errors = menu_page
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
        _ALL,
    )
    assert len(rows) == len(_LABELS) + 1
    for r in rows:
        assert r["floor"] >= 40, f"--hit-min resolved {r['floor']}"
        assert r["height"] >= r["floor"], (
            f"{r['label']!r} is {r['height']}px tall, floor {r['floor']}px"
        )


@pytest.mark.parametrize("theme", _THEMES)
def test_rows_draw_the_system_focus_ring(menu_page, theme):
    page, _errors = menu_page
    # A key press puts Chromium in keyboard modality, so a programmatic
    # focus() then matches :focus-visible as a Tab would.
    page.keyboard.press("Shift")
    rows = page.evaluate(
        """([sel, theme]) => {
          const root = document.documentElement;
          if (theme === 'hextech') root.removeAttribute('data-theme');
          else root.dataset.theme = theme;
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
              current: el.classList.contains('active'),
              visible: el.matches(':focus-visible'),
              outline: cs.outlineStyle,
              shadow: cs.boxShadow,
              ring,
            };
          });
          if (document.activeElement) document.activeElement.blur();
          root.removeAttribute('data-theme');
          return out;
        }""",
        [_ALL, theme],
    )
    assert len(rows) == len(_LABELS) + 1
    assert sum(r["current"] for r in rows) == 1, rows
    for r in rows:
        assert r["ring"] not in ("", "none"), f"--focus-ring resolved {r['ring']!r}"
        assert r["visible"], f"{theme}: {r['label']!r} not :focus-visible"
        assert r["outline"] == "none", f"{theme}: {r['label']!r} outline {r['outline']!r}"
        assert r["shadow"] == r["ring"], (
            f"{theme}: {r['label']!r} focused shadow {r['shadow']!r} "
            f"!= ring {r['ring']!r}"
        )
