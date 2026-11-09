"""
tests/snapshot_panels/test_lobby_narrow_reflow.py
At 720 px and under (300% zoom of the 1920x920 baseline is 640 wide, 400% is
480; WCAG 1.4.10 reflows at 320) the Pre-Game Lobby's QUEUE and PARTY cards
fit the view, and no Lobby card has content past its own frame (s144 lane
uiux, RM-1775; RM-1774 did the view heads).

Measured before the fix (ui_mock, headless Chromium): the Lobby grid is one
1fr track below 1200 px, and a 1fr track cannot shrink below its widest
card's min-content. The PARTY member rows are a six-track grid (name |
lane prefs | role | rank | top champs | a fixed 120 px action column) whose
min-content is 700 px, so every card was 734 px wide at every narrow width:
69 px past the view at 720, 149 at 640, 309 at 480, 429 at 360, and the
whole view scrolled sideways. The QUEUE buttons (two lane buttons, Cancel,
Find Match, 110 px each) held one row of 470 px, so inside a fitted card
they would run 56 px past at 480.

Contract pinned here, ui_mock lobby, at 640x900, 480x800, 360x740 and
320x640:
  - the QUEUE and PARTY cards lie inside the view's content box;
  - no displayed descendant of any Lobby card reaches past that card's
    frame (MAINS and TOP 8 reflow in RM-1776, pinned with populated
    rows by test_lobby_mains_top8_narrow_reflow.py);
  - the PARTY card's duo-synergy block (RM-881, the queue lane's row, so
    its CSS is not edited here) fits at 640 / 480 / 360; at 320 its four
    32 px icons run about 11 px past the card, pinned as a strict xfail so
    the fix that lands there turns this file red until the mark is lifted;
  - a PARTY row does not scroll sideways, every member name keeps at least
    6em (or its whole text), and the action buttons keep their 26 px box
    at the row's right edge;
  - the QUEUE buttons keep their 110x64 box, and the two lane buttons stay
    side by side.
Above the line (842x900; the Lobby's line is 840 px since S144-U-197, pinned
by test_lobby_reflow_line_fit.py) the rows keep the RM-975 desktop template:
the six-track PARTY grid and a one-row QUEUE.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_NARROW = ((640, 900), (480, 800), (360, 740), (320, 640))
_WIDE = (842, 900)
_IDS = [str(s[0]) for s in _NARROW]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """() => {
  const sec = document.getElementById("view-lobby");
  if (!sec || getComputedStyle(sec).display === "none") return null;
  const scs = getComputedStyle(sec);
  const sr = sec.getBoundingClientRect();
  const content = {
    l: sr.left + parseFloat(scs.borderLeftWidth) + parseFloat(scs.paddingLeft),
    r: sr.right - parseFloat(scs.borderRightWidth)
      - parseFloat(scs.paddingRight),
  };
  const shown = (e) => getComputedStyle(e).display !== "none"
    && getComputedStyle(e).visibility !== "hidden"
    && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const cards = {};
  for (const c of sec.querySelectorAll(".lobby-view-card")) {
    const key = Array.from(c.classList)
      .find((k) => k.startsWith("lobby-view-card-")).slice(16);
    const cr = c.getBoundingClientRect();
    const past = [];
    const duo = [];
    for (const d of c.querySelectorAll("*")) {
      if (!shown(d)) continue;
      const r = d.getBoundingClientRect();
      if (r.right > cr.right + 1 || r.left < cr.left - 1) {
        (d.closest(".lv-duosyn") ? duo : past).push([d.tagName + "." + String(d.className).slice(0, 48),
                   Math.round(r.left), Math.round(r.right),
                   Math.round(cr.left), Math.round(cr.right)]);
      }
    }
    cards[key] = {box: box(c), past: past.slice(0, 6), n: past.length,
                  duo: duo.slice(0, 6), nDuo: duo.length};
  }
  const rows = Array.from(sec.querySelectorAll(
    ".lobby-members-list .lobby-member-row")).filter(shown).map((li) => {
    const name = li.querySelector(".lobby-member-name");
    const em = parseFloat(getComputedStyle(name || li).fontSize);
    const act = li.querySelector(".lobby-member-actions");
    const lr = li.getBoundingClientRect();
    const lcs = getComputedStyle(li);
    return {
      sw: li.scrollWidth, cw: li.clientWidth,
      actGap: lr.right - parseFloat(lcs.borderRightWidth)
        - parseFloat(lcs.paddingRight) - act.getBoundingClientRect().right,
      display: getComputedStyle(li).display,
      tracks: getComputedStyle(li).gridTemplateColumns,
      name: name ? {w: name.getBoundingClientRect().width,
                    sw: name.scrollWidth, em} : null,
      actions: Array.from(li.querySelectorAll(
        ".lv-member-action, .lv-member-action-spacer"))
        .map((a) => [a.getBoundingClientRect().width,
                     a.getBoundingClientRect().height]),
    };
  });
  const qc = sec.querySelector(".lobby-view-queue-controls");
  const qbtns = Array.from(qc.querySelectorAll(".lq-btn")).filter(shown)
    .map((b) => ({cls: String(b.className), ...box(b)}));
  return {
    content, cards, rows, qbtns,
    qwrap: getComputedStyle(qc).flexWrap,
    lanes: Array.from(qc.querySelectorAll(".lq-lane-pair .lq-btn"))
      .filter(shown).map(box),
  };
}"""


def _read(pw_browser, url, size):
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
            "document.body.dataset.view === 'lobby' && document"
            ".querySelectorAll('.lobby-members-list .lobby-member-row"
            "[data-member-idx]').length >= 2",
            timeout=10_000,
        )
        page.evaluate(_SETTLE)
        got = page.evaluate(_READ)
    finally:
        ctx.close()
    assert not errors, f"page errors at {size}: {errors[:3]}"
    return got


@pytest.fixture(scope="module")
def narrow(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return {s: _read(pw_browser, mock_server.url, s) for s in _NARROW}


@pytest.fixture(scope="module")
def wide(mock_server, pw_browser):
    mock_server._store["data"] = {}
    return _read(pw_browser, mock_server.url, _WIDE)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("card", ("queue", "party"))
def test_queue_and_party_cards_fit_the_view(narrow, size, card):
    r = narrow[size]
    assert r is not None, size
    b = r["cards"][card]["box"]
    assert b["l"] >= r["content"]["l"] - 1, (size, card, b, r["content"])
    assert b["r"] <= r["content"]["r"] + 1, (size, card, b, r["content"])


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
@pytest.mark.parametrize("card", ("queue", "party", "mainchamps", "friends"))
def test_no_card_content_reaches_past_its_frame(narrow, size, card):
    c = narrow[size]["cards"][card]
    assert c["n"] == 0, (size, card, c["past"])


@pytest.mark.parametrize("size", _NARROW[:3], ids=_IDS[:3])
def test_duo_synergy_fits_the_party_card(narrow, size):
    c = narrow[size]["cards"]["party"]
    assert c["nDuo"] == 0, (size, c["duo"])


@pytest.mark.xfail(strict=True, reason=(
    "RM-881 (queue lane): the duo-synergy cells keep four 32 px icons in"
    " a row, which cannot fit the 320 px PARTY card"))
def test_duo_synergy_fits_the_party_card_at_320(narrow):
    c = narrow[(320, 640)]["cards"]["party"]
    assert c["nDuo"] == 0, c["duo"]


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_party_rows_hold_names_and_action_boxes(narrow, size):
    rows = narrow[size]["rows"]
    assert len(rows) == 5, rows
    for row in rows:
        assert row["sw"] <= row["cw"] + 1, (size, row)
        # The action buttons stay pinned to the row's right edge.
        assert abs(row["actGap"]) < 1, (size, row)
        for w, h in row["actions"]:
            assert abs(w - 26) < 0.5 and abs(h - 26) < 0.5, (size, row)
    named = [row["name"] for row in rows if row["name"]]
    assert len(named) >= 2, rows
    for n in named:
        assert n["w"] + 0.5 >= min(n["sw"], 6 * n["em"]), (size, n)


@pytest.mark.parametrize("size", _NARROW, ids=_IDS)
def test_queue_buttons_keep_their_box_and_lanes_stay_paired(narrow, size):
    r = narrow[size]
    assert r["qbtns"], r
    for b in r["qbtns"]:
        assert abs(b["w"] - 110) < 0.5 and abs(b["h"] - 64) < 0.5, (size, b)
    if len(r["lanes"]) == 2:
        a, b = r["lanes"]
        assert abs(a["t"] - b["t"]) < 0.5, (size, r["lanes"])


def test_desktop_template_is_unchanged_above_the_line(wide):
    assert wide["qwrap"] == "nowrap", wide["qwrap"]
    for row in wide["rows"]:
        assert row["display"] == "grid", row
        assert len(row["tracks"].split()) == 6, row
    tops = {round(b["t"]) for b in wide["qbtns"]}
    assert len(tops) == 1, wide["qbtns"]
