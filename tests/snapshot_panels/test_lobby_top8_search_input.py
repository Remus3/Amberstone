"""
tests/snapshot_panels/test_lobby_top8_search_input.py
The Pre-Game Lobby "My Top 8" search box meets the v2.1 floors (session 144,
lane uiux, RM-979).

web/css/panels/header.css .lv-top8-search-input carried `font-size: 14px`,
`padding: 4px 6px` and `outline: none` with no :focus-visible rule anywhere.
Measured in headless Chromium at the 1920x920 baseline on /?ui_mock=1#lobby:
the input computed 14px (the row around it is already on --fs-xs, 16), it was
25px tall against the 42px --hit-min floor, and focusing it drew no ring at
all - a keyboard user tabbing into the one text field on the page could not
see where focus landed. No operator exception covers any of the three.

Rule pinned here, by COMPUTED value (a grep cannot see an invalid var()):
- the input computes at or above the resolved --fs-xs;
- its box is at least the resolved --hit-min tall;
- focused, it matches :focus-visible and draws a solid outline of at least
  2px whose colour is the resolved --accent;
- the search row still reads as one row (the add button's centre sits inside
  the input's vertical band) and the page gains no horizontal overflow.

Drive path: /?ui_mock=1#lobby, the same recipe and landing signal as
test_lobby_view.py (#lv-queue-name leaves its "-" placeholder).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_READ = """() => {
  const probe = (prop, v) => {
    const d = document.createElement("span");
    d.style.display = "block";
    d.style[prop] = "var(" + v + ")";
    document.body.appendChild(d);
    const cs = getComputedStyle(d);
    const out = prop === "color" ? cs.color : parseFloat(cs[prop]);
    d.remove();
    return out;
  };
  const inp = document.getElementById("lv-top8-search-input");
  const add = document.getElementById("lv-top8-search-add");
  inp.focus();
  const cs = getComputedStyle(inp);
  const ri = inp.getBoundingClientRect();
  const ra = add.getBoundingClientRect();
  return {
    fsXs: probe("fontSize", "--fs-xs"),
    hitMin: probe("height", "--hit-min"),
    accent: probe("color", "--accent"),
    fontSize: parseFloat(cs.fontSize),
    height: ri.height,
    focused: document.activeElement === inp,
    focusVisible: inp.matches(":focus-visible"),
    outlineStyle: cs.outlineStyle,
    outlineWidth: parseFloat(cs.outlineWidth),
    outlineColor: cs.outlineColor,
    inputTop: ri.top,
    inputBottom: ri.bottom,
    addMid: ra.top + ra.height / 2,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
  };
}"""


@pytest.fixture(scope="module")
def lobby_search(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1#lobby",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const q = document.querySelector('#lv-queue-name');"
            " const t = q ? q.textContent.trim() : '';"
            " return t !== '' && t !== '-'; })()",
            timeout=10_000,
        )
        yield page.evaluate(_READ), errors
    finally:
        page.close()
        ctx.close()


def test_search_input_text_is_on_the_fs_xs_floor(lobby_search):
    r, errors = lobby_search
    assert r["fsXs"] >= 16, r
    assert r["fontSize"] >= r["fsXs"], r
    assert errors == []


def test_search_input_is_a_hit_min_target(lobby_search):
    r, _ = lobby_search
    assert r["hitMin"] >= 42, r
    assert r["height"] >= r["hitMin"], r


def test_search_input_shows_a_focus_ring(lobby_search):
    r, _ = lobby_search
    assert r["focused"] and r["focusVisible"], r
    assert r["outlineStyle"] == "solid", r
    assert r["outlineWidth"] >= 2, r
    assert r["outlineColor"] == r["accent"], r


def test_search_row_stays_one_row_without_overflow(lobby_search):
    r, _ = lobby_search
    assert r["inputTop"] <= r["addMid"] <= r["inputBottom"], r
    assert r["overflowX"] is False, r
