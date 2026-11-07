"""
tests/snapshot_panels/test_lobby_mains_copy_box.py
The Pre-Game Lobby MAINS card's copy button keeps its 22x22 box beside the
champion icon at every width, on both tabs (s144 lane uiux, S144-U-177; the
U-166 FUTURE row).

The icon column is 76px (web/css/panels/header.css, .lv-mc-grid-you and
its siblings), sized for icon + gap + button. The champ cell
(.lv-mc-champ) drew a 50px icon, a 6px gap and the 22px button: 78px in a
76px column, so the button - the only flex child free to shrink - drew
20px wide at every width above 400, desktop included. Measured before the
fix (headless Chromium, YOUR MAINS and PARTY MAINS, 1920x920 down to
480x800, and PARTY MAINS at 400 and 320 too): 20 x 22. At 400 and under
YOUR MAINS stacks the button under the icon (50px column), where it kept
its 22px box already; PARTY MAINS keeps it beside the icon there.

Contract pinned at 1920x920, 1280x800, 722x900, 640x900, 480x800, 400x740
and 320x640, on YOUR MAINS (four synthetic mains, the
test_lobby_mains_top8_narrow_reflow.py set; every name synthetic, RM-906)
and on PARTY MAINS (its rows, filled or placeholder, carry the same cell):
  - every copy button is 22 x 22;
  - the button lies inside the champ cell, which lies inside its row;
  - the icon keeps its 50 x 50 box and the button never overlaps it.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_lobby_mains_top8_narrow_reflow import (
    _MAINS,
    _SETTLE,
    _TOP8,
)

_SIZES = ((1920, 920), (1280, 800), (722, 900), (640, 900), (480, 800),
          (400, 740), (320, 640))
_IDS = [f"{w}x{h}" for w, h in _SIZES]
_TABS = ("you", "party")

_READ = """() => {
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const list = document.getElementById("lv-mainchamps-list");
  return {
    tab: list ? list.dataset.tab : null,
    rows: Array.from(document.querySelectorAll(
      "#lv-mainchamps-list .lv-mc-row"))
      .filter((li) => getComputedStyle(li).display !== "none")
      .map((li) => ({
        row: box(li),
        champ: box(li.querySelector(".lv-mc-champ")),
        icon: box(li.querySelector(".lv-mc-icon")),
        copy: box(li.querySelector(".lv-mc-copy")),
      })),
  };
}"""


def _read(pw_browser, url, size, tab):
    ctx = pw_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": size[0], "height": size[1]},
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/?ui_mock=1#lobby", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_function(
            "document.body.dataset.view === 'lobby'"
            " && document.querySelectorAll('#lv-mainchamps-list .lv-mc-copy')"
            ".length >= 1",
            timeout=10_000,
        )
        page.click("#lv-mc-tab-" + tab)
        page.wait_for_function(
            "(t) => { const l = document.getElementById('lv-mainchamps-list');"
            " return !!l && l.dataset.tab === t"
            " && l.querySelectorAll('.lv-mc-copy').length >= 1; }",
            arg=tab, timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size} {tab}: {errors[:3]}"
    return got


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    mock_server._store["data"] = {"lcu": {"top8": _TOP8,
                                          "main_champs": _MAINS}}
    try:
        return {(s, t): _read(pw_browser, mock_server.url, s, t)
                for s in _SIZES for t in _TABS}
    finally:
        mock_server._store["data"] = {}


def _rows(measured, size, tab):
    got = measured[(size, tab)]
    assert got["tab"] == tab, (size, tab, got["tab"])
    rows = got["rows"]
    assert rows, (size, tab)
    if tab == "you":
        assert len(rows) == 4, (size, len(rows))
    return rows


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_copy_button_keeps_its_22px_box(measured, size, tab):
    for row in _rows(measured, size, tab):
        c = row["copy"]
        assert abs(c["w"] - 22) < 0.5, (size, tab, c)
        assert abs(c["h"] - 22) < 0.5, (size, tab, c)


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_copy_button_stays_in_its_cell(measured, size, tab):
    for row in _rows(measured, size, tab):
        c, ch, r = row["copy"], row["champ"], row["row"]
        assert c["l"] >= ch["l"] - 0.5 and c["r"] <= ch["r"] + 0.5, \
            (size, tab, c, ch)
        assert ch["l"] >= r["l"] - 0.5 and ch["r"] <= r["r"] + 0.5, \
            (size, tab, ch, r)


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("size", _SIZES, ids=_IDS)
def test_icon_keeps_its_box_and_the_button_clears_it(measured, size, tab):
    for row in _rows(measured, size, tab):
        i, c = row["icon"], row["copy"]
        assert abs(i["w"] - 50) < 0.5 and abs(i["h"] - 50) < 0.5, \
            (size, tab, i)
        beside = c["l"] >= i["r"] - 0.5
        below = c["t"] >= i["b"] - 0.5
        assert beside or below, (size, tab, i, c)
        # Only YOUR MAINS stacks the button under the icon at 400 and
        # under (header.css, the max-width 400px block).
        assert beside == (size[0] > 400 or tab == "party"), \
            (size, tab, i, c)
