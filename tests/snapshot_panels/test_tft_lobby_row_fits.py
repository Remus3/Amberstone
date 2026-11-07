"""
tests/snapshot_panels/test_tft_lobby_row_fits.py
The TFT Active Match LOBBY keeps every player's HP number on screen as the
MAP pane narrows (s144 lane uiux, RM-1767).

The lobby row (web/js/panels/active_match.js _amTftLobbyNode) was a fixed
`3.2em 6em minmax(8em, 28em) 3em` grid in web/css/panels/active_match.css: a
410 px floor. Measured on the tft_round fixture, the lobby wrapper is 333 px at
768x1024, 264 px at 640x900 and 179 px at 480x800, so every row spilled out of
it: the HP number (the value the panel exists for) sat 15 to 223 px past the
wrapper's right edge, behind a horizontal scrollbar inside a fixed-height box,
and that scrollbar plus the eyebrow wrapping to two or three lines pushed the
8th row out of view. At the 1920x920 baseline nothing was wrong.

Contract pinned here:
  - the 1920x920 baseline is unchanged: 57.6 / 108 / 504 / 54 px columns, the
    bar shown (control);
  - wherever the wrapper is at least 148 px wide (place + HP + padding), no
    row leaves the wrapper (no horizontal scroller), and the place and the HP
    text are whole;
  - the HP bar is a redundant picture of the HP number, so it gives way
    first: it is either at least 3em (54 px) wide or not rendered at all;
  - "You" / "Opponent" is whole wherever the wrapper is at least 256 px wide
    (a narrower one may ellipsise it; the row's aria-label carries it whole);
  - the eyebrow stays one line (ellipsised, its full text in title), so the
    eight rows fit the fixed wrapper without a vertical scroll at every size
    above, and the wrapper height never moves (no reflow).

Drive path: /?ui_mock=1&mode=tft_round#active-match (web/data/ui_mock/
active_match_tft_round.json, a recorded S134 round row: eight players, the
local player 5th at 78 HP).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MEASURE = r"""
async () => {
  await document.fonts.ready;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const wrap = document.querySelector('#am-map-body .am-tft-lobby-wrap');
  const wr = wrap.getBoundingClientRect();
  const head = wrap.querySelector('.am-tft-sec');
  const cell = (r, cls) => {
    const c = r.querySelector('.' + cls);
    const b = c.getBoundingClientRect();
    return {text: c.textContent, left: b.left, right: b.right, width: b.width,
            scroll: c.scrollWidth, client: c.clientWidth,
            display: getComputedStyle(c).display};
  };
  const rows = Array.from(wrap.querySelectorAll('.am-tft-lob-row')).map(r => {
    const b = r.getBoundingClientRect();
    return {left: b.left, right: b.right, label: r.getAttribute('aria-label'),
            place: cell(r, 'am-tft-lob-place'), who: cell(r, 'am-tft-lob-who'),
            bar: cell(r, 'am-tft-lob-bar'), hp: cell(r, 'am-tft-lob-hp')};
  });
  const fsSm = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--fs-sm'));
  const cs = getComputedStyle(head);
  return {wrapLeft: wr.left, wrapRight: wr.right, wrapW: wrap.clientWidth,
          wrapScrollW: wrap.scrollWidth, wrapH: wrap.clientHeight,
          wrapScrollH: wrap.scrollHeight, fsSm,
          cols: getComputedStyle(wrap.querySelector('.am-tft-lob-row'))
            .gridTemplateColumns,
          head: {text: head.textContent, title: head.title,
                 h: head.getBoundingClientRect().height,
                 lineH: parseFloat(cs.lineHeight)},
          rows,
          docOverflow: document.documentElement.scrollWidth
                       > document.documentElement.clientWidth};
}
"""

_SIZES = [(1920, 920), (1440, 900), (1199, 920), (1024, 768), (923, 1280),
          (768, 1024), (640, 900), (480, 800), (320, 700)]

_HP = ["83", "81", "80", "79", "78", "75", "62", "60"]


def _measure(pw_browser, mock_server, w: int, h: int) -> dict:
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=tft_round#active-match",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_function(
            "document.querySelectorAll('#am-map-body .am-tft-lob-row')"
            ".length === 8",
            timeout=10_000,
        )
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert m["fsSm"] == 18, m["fsSm"]
    assert [r["hp"]["text"] for r in m["rows"]] == _HP, m["rows"]
    return m


def test_baseline_columns_unchanged(mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, 1920, 920)
    cols = [float(c.rstrip("px")) for c in m["cols"].split()]
    assert len(cols) == 4, m["cols"]
    for got, want in zip(cols, [57.6, 108.0, 504.0, 54.0]):
        assert abs(got - want) < 0.5, m["cols"]
    for r in m["rows"]:
        assert r["bar"]["display"] == "block" and r["bar"]["width"] > 400, r
    assert m["wrapScrollW"] <= m["wrapW"], m
    assert m["wrapScrollH"] <= m["wrapH"], m


@pytest.mark.parametrize("w,h", _SIZES)
def test_hp_number_stays_inside_the_lobby(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    if m["wrapW"] < 148:
        return  # not this case: lobby Npx is narrower than place + HP
    assert m["wrapScrollW"] <= m["wrapW"], (
        f"{w}x{h}: lobby rows overflow the {m['wrapW']}px wrapper "
        f"({m['wrapScrollW']}px, cols {m['cols']})")
    for r in m["rows"]:
        assert r["right"] <= m["wrapRight"] + 0.5, (w, h, r)
        for key in ("place", "hp"):
            c = r[key]
            assert c["scroll"] <= c["client"], (
                f"{w}x{h}: {key} '{c['text']}' cut {c['client']}/{c['scroll']}")
            assert c["right"] <= m["wrapRight"] + 0.5, (
                f"{w}x{h}: {key} '{c['text']}' past the wrapper edge")
    assert not m["docOverflow"], f"{w}x{h}: horizontal page overflow"


@pytest.mark.parametrize("w,h", _SIZES)
def test_bar_gives_way_whole_or_not_at_all(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    if m["wrapW"] < 148:
        return  # not this case: lobby Npx is narrower than place + HP
    for r in m["rows"]:
        bar = r["bar"]
        if bar["display"] == "none":
            continue
        assert bar["width"] >= 3 * m["fsSm"] - 0.5, (
            f"{w}x{h}: HP bar squeezed to {bar['width']:.1f}px")


@pytest.mark.parametrize("w,h", _SIZES)
def test_who_label_is_whole_when_there_is_room(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    you = [r for r in m["rows"] if r["who"]["text"] == "You"]
    assert len(you) == 1 and you[0]["label"] == "5th, You, 78 HP", m["rows"]
    for r in m["rows"]:
        assert r["who"]["text"] in ("You", "Opponent"), r
        assert r["who"]["text"] in r["label"], r
    if m["wrapW"] < 256:
        return  # not this case: lobby Npx may ellipsise the label
    cut = [r["who"]["text"] for r in m["rows"]
           if r["who"]["scroll"] > r["who"]["client"]]
    assert not cut, f"{w}x{h}: lobby labels cut: {cut}"


@pytest.mark.parametrize("w,h", _SIZES)
def test_eyebrow_is_one_line_and_rows_fit_the_fixed_box(
        w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    # No reflow: the wrapper is the fixed eyebrow + eight-row box (272 px at
    # the v2.1 tokens) at every width.
    assert m["wrapH"] == 272, m["wrapH"]
    head = m["head"]
    assert head["text"].startswith("LOBBY - 8 of 8 alive"), head
    assert head["title"] == head["text"], head
    assert head["h"] <= head["lineH"] + 0.5, (
        f"{w}x{h}: lobby eyebrow wraps to {head['h']:.1f}px")
    if m["wrapW"] < 148:
        return  # not this case: lobby Npx is narrower than place + HP
    assert m["wrapScrollH"] <= m["wrapH"], (
        f"{w}x{h}: 8th row pushed out of the lobby box "
        f"({m['wrapScrollH']}/{m['wrapH']}px)")
