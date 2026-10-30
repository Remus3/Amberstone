"""
tests/snapshot_panels/test_lm_hero_stats_disclosure.py
RM-1136 (s144 uiux): the Post Game Review "Detailed stats" disclosure
(web/index.html <summary class="lm-hero-stats-summary"> inside
#lm-hero-stats-details, styled in web/css/panels/last_match.css) is the only
control in the PGR hero row, and nothing pinned it.

MEASURED under /?ui_mock=1&mode=<sr|aram|arena|brawl>#last-match at
1920x1080 before the fix: the summary was 19px tall on all four modes and all
six themes, under the resolved --hit-min (42px), and a keyboard-focused
summary drew only the UA outline. The 5-phase audit's HIT-TARGETS phase asks
both of every clickable, so the summary now takes the floor and draws the one
system ring (--focus-ring as its box-shadow, outline none), the pattern the
Lobby mains tabs (test_lobby_mains_tabs.py) and User Builds tabs use.

The disclosure stays a native <details> with no JS wiring, so the keyboard
contract is the browser's own: Enter on the focused summary opens it and the
8-stat grid shows. That is pinned too, because a display change on a
<summary> is the edit most likely to break native toggling.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MODES = ["sr", "aram", "arena", "brawl"]
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SEL = "#lm-hero-stats-details > .lm-hero-stats-summary"

_FLOOR = """() => {
  // Absolute, so a flex-column body cannot shrink the probe below the token.
  const probe = document.createElement('div');
  probe.style.position = 'absolute';
  probe.style.height = 'var(--hit-min)';
  document.body.appendChild(probe);
  const floor = probe.getBoundingClientRect().height;
  probe.remove();
  return floor;
}"""

_RING = """() => {
  const probe = document.createElement('div');
  probe.style.boxShadow = 'var(--focus-ring)';
  document.body.appendChild(probe);
  const ring = getComputedStyle(probe).boxShadow;
  probe.remove();
  return ring;
}"""


def _open(mock_server, pw_browser, mode, theme="hextech"):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}&theme={theme}#last-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "(() => { const t = document.getElementById('lm-mode-tag');"
        " const v = t ? t.textContent.trim() : '';"
        " return v !== '' && v !== '-'; })()",
        timeout=10_000,
    )
    page.evaluate("document.fonts.ready")
    return ctx, page, errors


@pytest.mark.parametrize("mode", _MODES)
def test_summary_clears_the_hit_floor(mock_server, pw_browser, mode):
    ctx, page, errors = _open(mock_server, pw_browser, mode)
    try:
        floor = page.evaluate(_FLOOR)
        box = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " const r = el.getBoundingClientRect();"
            " return {text: el.textContent.trim(), w: r.width, h: r.height,"
            " open: el.parentElement.open}; }",
            _SEL,
        )
        overflow = page.evaluate(
            "document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
    finally:
        page.close()
        ctx.close()
    assert floor >= 40, f"--hit-min resolved {floor}"
    assert box["text"] == "Detailed stats", box
    assert box["open"] is False, f"{mode}: the disclosure must load collapsed"
    assert box["w"] >= floor, f"{mode}: summary is {box['w']}px wide"
    assert box["h"] >= floor, (
        f"{mode}: 'Detailed stats' is {box['h']}px tall, floor {floor}px"
    )
    assert overflow <= 0, f"{mode}: horizontal overflow {overflow}px"
    assert not errors, errors[:3]


@pytest.mark.parametrize("theme", _THEMES)
def test_summary_draws_the_system_focus_ring(mock_server, pw_browser, theme):
    ctx, page, errors = _open(mock_server, pw_browser, "sr", theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        ring = page.evaluate(_RING)
        page.keyboard.press("Shift")
        got = page.evaluate(
            "(sel) => { const el = document.querySelector(sel); el.focus();"
            " const cs = getComputedStyle(el);"
            " const out = {focused: document.activeElement === el,"
            " visible: el.matches(':focus-visible'),"
            " outline: cs.outlineStyle, shadow: cs.boxShadow};"
            " el.blur(); return out; }",
            _SEL,
        )
    finally:
        page.close()
        ctx.close()
    assert ring not in ("", "none"), f"--focus-ring resolved {ring!r}"
    assert got["focused"] and got["visible"], got
    assert got["shadow"] == ring, (
        f"{theme}: focused summary box-shadow {got['shadow']!r}, ring {ring!r}"
    )
    assert got["outline"] == "none", (
        f"{theme}: focused summary still draws the UA outline ({got['outline']})"
    )
    assert not errors, errors[:3]


def test_enter_on_the_focused_summary_opens_the_grid(mock_server, pw_browser):
    # A closed <details> hides its content with content-visibility, which
    # leaves a stale layout box on the grid, so read checkVisibility() and
    # the disclosure's own height (summary only when closed), never the
    # grid's rect.
    read = (
        "() => { const d = document.getElementById('lm-hero-stats-details');"
        " const s = d.querySelector('summary');"
        " const g = d.querySelector('.lm-hero-stats-grid');"
        " return {open: d.open, shown: g.checkVisibility(),"
        " grows: d.getBoundingClientRect().height"
        " > s.getBoundingClientRect().height + 1,"
        " focused: document.activeElement === s}; }"
    )
    ctx, page, errors = _open(mock_server, pw_browser, "sr")
    try:
        page.focus(_SEL)
        before = page.evaluate(read)
        page.keyboard.press("Enter")
        after = page.evaluate(read)
    finally:
        page.close()
        ctx.close()
    assert before == {"open": False, "shown": False, "grows": False,
                      "focused": True}, before
    assert after["open"] is True, "Enter on the focused summary did not open it"
    assert after["shown"] and after["grows"], (
        f"the open disclosure did not show the stats grid: {after}"
    )
    assert after["focused"] is True, "focus left the summary when it toggled"
    assert not errors, errors[:3]
