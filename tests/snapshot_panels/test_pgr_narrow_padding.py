"""
tests/snapshot_panels/test_pgr_narrow_padding.py
At 720 px and under the Post Game Review drops its doubled side padding,
so the Build tab rosters get their width back (s144 lane uiux,
S144-U-191; the U-190 FUTURE row "at 320 the Build tab's nested padding
(lm-body 18 px + tabbed section 17 px a side, then group 11 and row 7)
leaves a row 140 px of content").

Measured before the fix (headless Chromium, ui_mock last_match_sr, the
live view on its Build tab and the archive view opened from a History
row, same numbers in both): from the window edge to a roster row's
content there were 90 px a side at every width under 720 - the view's
own 18 px margin, 1 px border and 18 px padding, then #lm-body's 18 px
(a second copy of the view padding), the section card's 1 px border and
16 px padding, the ALLY / ENEMY group's 1 px border and 10 px padding,
and the row's 1 px border and 6 px padding. At 320 that left a row
140 px of content (180 at 360, 300 at 480), so a wrapped SR row ran 8
lines (219 px tall) and an Arena row 9 (272 px). The TFT card (#lm-tft,
the sibling body) carried the same 18 px second copy.

Contract pinned here, live sr / arena / tft and archive sr:
  - 721 px and wider nothing moves: #lm-body / #lm-tft 18 px a side,
    the section cards 16, the roster groups 10;
  - 720 px and under: #lm-body / #lm-tft 0 a side (the view's own 18 px
    padding is the one gutter), the section cards 10, the roster groups
    6; top and bottom padding unchanged at every width;
  - at 320 a roster row has at least 196 px of content (56 px back);
  - no width scrolls the document or the view sideways, and every
    section card and the TFT card stay inside the view's padding box,
    so its gold corner brackets are not clipped.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_pgr_roster_reflow import (
    _SETTLE,
    _open_archive,
    _open_live,
)

_SIZES = ((1920, 920), (1201, 900), (721, 900), (720, 900), (640, 900),
          (480, 800), (360, 740), (320, 640))
_CASES = (("live", "sr"), ("live", "arena"), ("archive", "sr"),
          ("live", "tft"))
_ROW_CONTENT_320 = 196

_READ = """([vid, bid]) => {
  const v = document.getElementById(vid);
  const b = document.getElementById(bid);
  const px = (el) => { const cs = getComputedStyle(el);
    return [parseFloat(cs.paddingLeft), parseFloat(cs.paddingRight),
            parseFloat(cs.paddingTop), parseFloat(cs.paddingBottom)]; };
  const shown = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0; };
  const vcs = getComputedStyle(v), vr = v.getBoundingClientRect();
  const vbox = [vr.left + parseFloat(vcs.borderLeftWidth),
                vr.right - parseFloat(vcs.borderRightWidth)];
  const cards = [...b.querySelectorAll('.lm-section')].filter(shown);
  const row = b.querySelector('.lm-tc-row');
  let content = null;
  if (row && shown(row)) {
    const cs = getComputedStyle(row);
    content = row.getBoundingClientRect().width
      - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
      - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth);
  }
  const outside = [b, ...cards].map((el) => el.getBoundingClientRect())
    .filter((r) => r.left < vbox[0] - 0.5 || r.right > vbox[1] + 0.5)
    .map((r) => [Math.round(r.left), Math.round(r.right)]);
  return {
    doc: [document.documentElement.scrollWidth, innerWidth],
    view: [v.scrollWidth, v.clientWidth],
    body: px(b), hidden: b.hidden,
    sections: cards.map(px),
    groups: [...b.querySelectorAll('.lm-tc-group')].filter(shown).map(px),
    content, outside, vbox,
  };
}"""


def _open_tft(page, url, _mode):
    page.goto(url + "/?ui_mock=1&mode=tft#last-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(() => { const h = document.getElementById('lm-tft');"
        " return !!(h && !h.hidden && h.querySelector('.lm-tft-place'));"
        " })()", timeout=10_000)
    return "view-last-match", "lm-tft"


@pytest.fixture(scope="module", params=_CASES,
                ids=[f"{v}-{m}" for (v, m) in _CASES])
def pgr(request, mock_server, pw_browser):
    view, mode = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    out = {}
    try:
        if mode == "tft":
            vid, bid = _open_tft(page, mock_server.url, mode)
        elif view == "live":
            vid, _t = _open_live(page, mock_server.url, mode)
            bid = "lm-body"
        else:
            vid, _t = _open_archive(page, mock_server.url, mode)
            bid = "hpgr-body"
        for w, h in _SIZES:
            page.set_viewport_size({"width": w, "height": h})
            page.evaluate(_SETTLE)
            out[w] = page.evaluate(_READ, [vid, bid])
    finally:
        page.close()
        ctx.close()
    return f"{view}-{mode}", mode, out, errors


@pytest.mark.parametrize("w", [s[0] for s in _SIZES])
def test_pgr_side_padding_steps_down_at_720(pgr, w):
    tag, mode, out, errors = pgr
    assert errors == [], f"{tag}: {errors[:3]}"
    d = out[w]
    t = f"{tag} {w}"
    narrow = w <= 720
    assert not d["hidden"], f"{t}: body hidden"
    body_side = 0 if narrow else 18
    assert d["body"][:2] == [body_side, body_side], f"{t}: body {d['body']}"
    assert d["body"][2:] == [14, 14], f"{t}: body top / bottom {d['body']}"
    if mode == "tft":
        return
    assert d["sections"], f"{t}: no section card shown"
    side = 10 if narrow else 16
    for p in d["sections"]:
        assert p == [side, side, 12, 12], f"{t}: section {p}"
    assert len(d["groups"]) == 2, f"{t}: {len(d['groups'])} roster groups"
    side = 6 if narrow else 10
    for p in d["groups"]:
        assert p == [side, side, 8, 8], f"{t}: roster group {p}"


@pytest.mark.parametrize("w", [s[0] for s in _SIZES])
def test_pgr_fits_the_view(pgr, w):
    tag, _mode, out, _errors = pgr
    d = out[w]
    t = f"{tag} {w}"
    assert d["doc"][0] <= d["doc"][1], f"{t}: document scrolls {d['doc']}"
    assert d["view"][0] <= d["view"][1] + 1, (
        f"{t}: view scrolls sideways {d['view']}")
    assert not d["outside"], (
        f"{t}: a card past the view's padding box {d['outside']}"
        f" (view {d['vbox']})")


# The TFT card has no roster, so this takes the other cases only (indirect),
# never a skip (tests/test_skip_condition_hygiene.py).
@pytest.mark.parametrize("pgr", [c for c in _CASES if c[1] != "tft"],
                         indirect=True,
                         ids=[f"{v}-{m}" for (v, m) in _CASES if m != "tft"])
def test_roster_row_gets_its_width_back_at_320(pgr):
    tag, mode, out, _errors = pgr
    assert mode != "tft", tag
    content = out[320]["content"]
    assert content is not None, f"{tag}: no roster row at 320"
    assert content >= _ROW_CONTENT_320 - 0.5, (
        f"{tag}: a 320 roster row has {content:.1f} px of content")
