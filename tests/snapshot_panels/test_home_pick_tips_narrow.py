"""
tests/snapshot_panels/test_home_pick_tips_narrow.py
RM-1434 (s144 uiux) - the Tonight's Pick values stay whole in a narrow
window (WCAG 1.4.10 reflow, 320 CSS px wide).

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix: each Good / Bad / Ugly value (#home-pick-good, -bad, -ugly) is a
one-line ellipsis box (white-space: nowrap; text-overflow: ellipsis) in a
`96px 1fr` row. At 320x256 the value box was 136 px wide and held 218 / 173 /
191 px of text, so all three coaching tips ended in "..." and their numbers'
meaning was cut off. At 480x230 the box is 296 px, so the backend's longest
real tip, the small-sample caveat built by
dashboard/builders_home.py _home_pick_tips ("Small sample - 2 games, play
more for tips"), ellipsized there too. The champion name (fs-lg, nowrap
ellipsis) had 162 px beside the portrait at 320, under "Heimerdinger"
(177 px) and "Nunu & Willump" (207 px).

THE FIX (web/css/panels/home.css, inside the RM-1431 narrow blocks, so
1920x920 and the 923x1280 companion are untouched): under 720px a value wraps
instead of ellipsizing; under 440px the label sits above its value, so the
value gets the whole card width, and the champion name and reason sit under
the portrait, so the name (still one line) gets the card width (248 px).

What is checked: at 768x368, 640x307, 480x230 and 320x256, for the fixture
tips, the small-sample caveat and long two-word and one-word champion
names, every value and the
name are whole (scrollWidth within clientWidth, the box inside the card) and
the label of each row is still on screen beside or above its value; at
1920x920 and 923x1280 the authored one-line layout is pinned by computed
values, and on every host each tip row is a 96 px label beside a value track
that takes the rest of the row, with no fixture tip cut (RM-1657).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "home.json"

# The longest tip strings dashboard/builders_home.py _home_pick_tips can
# build: the 2-game caveat, and a two-digit KDA over a two-digit sample.
_SMALL_SAMPLE = {"good": "", "bad": "",
                 "ugly": "Small sample - 2 games, play more for tips"}
_WIDE_TIPS = {"good": "12.4 avg KDA over 14 games",
              "bad": "10.5 deaths per game",
              "ugly": "10.2 CS/min to sharpen"}

_CASES = {
    "fixture": {},
    "small_sample": {"tips": _SMALL_SAMPLE},
    "wide_tips_long_name": {"tips": _WIDE_TIPS, "champion": "Nunu & Willump"},
    "one_word_name": {"champion": "Heimerdinger"},
}

_NARROW = [(768, 368), (640, 307), (480, 230), (320, 256)]

_PROBE = """
() => {
  const card = document.getElementById('home-coach-pick').getBoundingClientRect();
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return {sw: el.scrollWidth, cw: el.clientWidth, l: r.left, r: r.right,
            t: r.top, b: r.bottom, text: el.textContent};
  };
  const rows = Array.from(document.querySelectorAll('.home-pick-tip-row')).map((row) => ({
    label: box(row.querySelector('.home-pick-tip-label')),
    value: box(row.querySelector('.home-pick-tip-value')),
  }));
  return {card: {l: card.left, r: card.right, t: card.top, b: card.bottom},
          champ: box(document.getElementById('home-coach-pick-champ')),
          reason: box(document.getElementById('home-coach-pick-reason')),
          rows};
}
"""


def _ctx(pw_browser, vp):
    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def _open(page, mock_server, overrides):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["tonight_pick"] = {**payload["tonight_pick"], **overrides}
    body = json.dumps(payload)

    def _fulfill(r):
        r.fulfill(status=200, content_type="application/json", body=body)
    # Home fetches the ui_mock file and then /api/home/summary; both get the
    # same payload so the second pass cannot clobber the first.
    page.route("**/data/ui_mock/home.json", _fulfill)
    page.route("**/api/home/summary", _fulfill)
    mock_server._store["data"] = {}
    page.goto(mock_server.url + "/?ui_mock=1#home",
              wait_until="domcontentloaded", timeout=15_000)
    want = payload["tonight_pick"]["champion"]
    page.wait_for_function(
        "(n) => { const e = document.getElementById('home-coach-pick-champ');"
        " return e && e.textContent.trim() === n"
        " && document.getElementById('home-pick-ugly').textContent.trim() !== '-'; }",
        arg=want, timeout=10_000)
    return payload["tonight_pick"]


def _whole(b, card):
    return (b["sw"] <= b["cw"] + 1 and b["l"] >= card["l"] - 0.5
            and b["r"] <= card["r"] + 0.5 and b["t"] >= card["t"] - 0.5
            and b["b"] <= card["b"] + 0.5)


@pytest.mark.parametrize("case", list(_CASES))
@pytest.mark.parametrize("vp", _NARROW, ids=lambda v: f"{v[0]}x{v[1]}")
def test_pick_values_stay_whole_in_a_narrow_window(mock_server, pw_browser, vp, case):
    ctx, page, errors = _ctx(pw_browser, vp)
    try:
        pick = _open(page, mock_server, _CASES[case])
        st = page.evaluate(_PROBE)
        card = st["card"]
        tips = pick["tips"]
        texts = [r["value"]["text"] for r in st["rows"]]
        want = [tips[k] or "-" for k in ("good", "bad", "ugly")]
        assert texts == want, f"anchor: rendered tips {texts} != {want}"
        for row in st["rows"]:
            v, lab = row["value"], row["label"]
            assert _whole(v, card), (
                f"{vp} {case}: the tip {v['text']!r} is cut (scroll {v['sw']} >"
                f" box {v['cw']}, or outside the card {card}): {v}")
            assert _whole(lab, card) and lab["sw"] <= lab["cw"] + 1, (
                f"{vp} {case}: the label {lab['text']!r} is cut: {lab}")
            beside = lab["r"] <= v["l"] + 0.5
            above = lab["b"] <= v["t"] + 0.5
            assert beside or above, (
                f"{vp} {case}: the label {lab['text']!r} overlaps its value: {row}")
        assert _whole(st["champ"], card), (
            f"{vp} {case}: the champion name {st['champ']['text']!r} is cut:"
            f" {st['champ']}")
        assert _whole(st["reason"], card), (
            f"{vp} {case}: the reason line is cut: {st['reason']}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


_AUTHORED_JS = """
() => {
  const cs = (el) => getComputedStyle(el);
  const v = document.getElementById('home-pick-good');
  const row = v.closest('.home-pick-tip-row');
  const champ = document.getElementById('home-coach-pick-champ');
  const tracks = cs(row).gridTemplateColumns.split(' ').map((x) => parseFloat(x));
  return {
    rowCols: tracks.map((x) => Math.round(x)).join(' '),
    valueWs: cs(v).whiteSpace, valueOverflow: cs(v).textOverflow,
    champWs: cs(champ).whiteSpace,
    cardH: Math.round(document.getElementById('home-coach-pick')
      .getBoundingClientRect().height),
    tracks, rowW: row.clientWidth, gap: parseFloat(cs(row).columnGap),
    cut: Array.from(document.querySelectorAll('.home-pick-tip-value'))
      .filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent),
  };
}
"""

# Computed at HEAD before the fix (RM-1434): the narrow blocks must not
# reach the desktop or the companion.
_AUTHORED = {
    (1920, 920): {"rowCols": "96 1023", "valueWs": "nowrap",
                  "valueOverflow": "ellipsis", "champWs": "nowrap", "cardH": 132},
    (923, 1280): {"rowCols": "96 683", "valueWs": "nowrap",
                  "valueOverflow": "ellipsis", "champWs": "nowrap", "cardH": 212},
}

# RM-1657: at 1920x920 the pick body is `auto 1fr` (home.css
# .home-coach-pick-body), so the intro column is as wide as its reason line and
# the tips' value track is the card width minus that line. The line joins its
# parts with U+00B7 dots, which the RM-1078 stub font (U+0020..U+007E only)
# leaves to the host's fallback face, so the track is a host fact: CI run
# 42136608451 read "96 1008" where Windows reads "96 1023". Off Windows that
# track is not pinned there; the label track is, and on every host the value
# track takes the rest of the row and no fixture tip is cut. At 923x1280 the
# body is one column and the track (683) read the same on both.
_TEXT_SIZED_TRACK = {(1920, 920)}


def _pinned(vp, st):
    if sys.platform == "win32" or vp not in _TEXT_SIZED_TRACK:
        return st
    return {**st, "rowCols": st["rowCols"].split(" ")[0]}


@pytest.mark.parametrize("vp", list(_AUTHORED), ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_authored_pick_layout_is_unchanged(mock_server, pw_browser, vp):
    ctx, page, errors = _ctx(pw_browser, vp)
    try:
        _open(page, mock_server, {})
        st = page.evaluate(_AUTHORED_JS)
        tracks = st["tracks"]
        assert len(tracks) == 2 and tracks[0] == 96, (
            f"{vp}: a tip row is not a 96 px label beside its value: {st}")
        assert abs(tracks[0] + st["gap"] + tracks[1] - st["rowW"]) <= 1, (
            f"{vp}: the value track does not take the rest of the row: {st}")
        assert st["cut"] == [], f"{vp}: a fixture tip is cut: {st}"
        got = {k: st[k] for k in _AUTHORED[vp]}
        assert _pinned(vp, got) == _pinned(vp, _AUTHORED[vp]), (
            f"{vp}: the authored pick layout moved: {got}")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
