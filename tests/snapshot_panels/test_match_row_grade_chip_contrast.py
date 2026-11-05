"""
tests/snapshot_panels/test_match_row_grade_chip_contrast.py
RM-1551 (s144 uiux) - the grade chip that leads every History and Session
match row (<span class="home-recent-grade X">, main.js _historyMatchRowEl and
the session renderer) reaches WCAG AA (4.5:1) on its own resolved fill, for
every grade letter, on every row tint, in every theme.

WHAT IS MEASURED (headless Chromium at 1920x920, /?ui_mock=1#history with the
first session row chosen so its win and loss rows paint, and
/?ui_mock=1#session; colours resolved by the browser, oklch and color-mix
included, lane doc trap 3; a translucent chip fill composited over the row
tint and the first opaque ancestor, so the PAIR is measured, never the token,
trap 4). The fixtures hold no F grade and one D, so each rendered chip is
re-classed through all six letters (S A B C D F) in place: the chip CSS is
the subject, the fixture only supplies real row contexts (neutral, win tint,
loss tint). The chip is 16px weight 900 - not WCAG "large" text, so the
4.5:1 bar applies.
Each D / F chip must also keep its hue (reads red), differ from var(--text)
and keep its --bad-soft tint, so a fix can only move the text, never drop the
encoding.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
_GRADES = ("S", "A", "B", "C", "D", "F")


def _themes():
    # "hextech" is the DEFAULT palette at :root (web/css/themes.css header);
    # no [data-theme="hextech"] block exists, so stamping it selects :root.
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    found = set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text))
    return ["hextech"] + sorted(found - {"hextech"})


_THEMES = _themes()

_MEASURE_JS = r"""
async (args) => {
  const [listSel, grades] = args;
  await document.fonts.ready;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, base) => [0, 1, 2].map(
    (i) => top[i] * top[3] + base[i] * (1 - top[3]));
  const fill = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) layers.push(b);
      if (b[3] >= 1) break;
    }
    if (!layers.length || layers[layers.length - 1][3] < 1) return null;
    let acc = layers.pop().slice(0, 3);
    while (layers.length) acc = over(layers.pop(), acc);
    return acc;
  };
  const tok = (name) => {
    const d = document.createElement('div');
    d.style.backgroundColor = `var(${name})`;
    document.body.appendChild(d);
    const c = rgba(getComputedStyle(d).backgroundColor);
    d.remove();
    return c;
  };
  const chips = [];
  for (const row of document.querySelectorAll(listSel + ' > li')) {
    const chip = row.querySelector(':scope > .home-recent-grade');
    if (!chip || !chip.getClientRects().length) continue;
    // A box is not a painted letter: visibility or a zero opacity anywhere
    // up the chain hides it while getClientRects still reports a rect.
    if (getComputedStyle(chip).visibility !== 'visible') continue;
    let shown = true;
    for (let n = chip; n; n = n.parentElement) {
      if (parseFloat(getComputedStyle(n).opacity) === 0) shown = false;
    }
    if (!shown) continue;
    const prev = chip.className;
    const rowKind = row.classList.contains('result-win') ? 'win'
      : row.classList.contains('result-loss') ? 'loss' : 'neutral';
    for (const g of grades) {
      chip.className = 'home-recent-grade ' + g;
      const cs = getComputedStyle(chip);
      chips.push({grade: g, row: rowKind, color: rgba(cs.color),
                  fill: fill(chip), tint: rgba(cs.backgroundColor),
                  fontSize: parseFloat(cs.fontSize),
                  weight: parseInt(cs.fontWeight, 10)});
    }
    chip.className = prev;
  }
  return {text: rgba(getComputedStyle(document.documentElement)
                     .getPropertyValue('--text').trim()),
          badSoft: tok('--bad-soft'), chips};
}
"""


def _lum(c) -> float:
    def ch(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _open(page, url, view, ready):
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(f"document.body.dataset.view === '{view}'",
                           timeout=10_000)
    page.wait_for_function(ready, timeout=10_000)


# Theme flips below must not straddle a colour transition (RM-1132).
_CALM = ("*, *::before, *::after { transition: none !important;"
         " animation: none !important; }")
# view: the match list _MEASURE_JS walks (its rows' chips are re-classed).
_LISTS = {"history": "#history-match-list", "session": "#session-matches"}


def _open_view(page, mock_server, view):
    """Open #history (first session chosen) or #session, transitions off,
    pointer parked, as the measured fixture does."""
    if view == "history":
        _open(page, mock_server.url + "/?ui_mock=1#history", "history",
              "document.querySelector('#history-session-list"
              " .history-session-row')")
        page.click("#history-session-list .history-session-row")
        page.wait_for_function(
            "document.querySelectorAll('#history-match-list"
            " .history-match-row .home-recent-grade').length >= 2",
            timeout=10_000)
    else:
        _open(page, mock_server.url + "/?ui_mock=1#session", "session",
              "document.querySelector('#session-matches .home-recent-grade')")
    page.add_style_tag(content=_CALM)
    page.mouse.move(0, 0)


@pytest.fixture(scope="module")
def measured(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    out = {}
    try:
        for view in ("history", "session"):
            _open_view(page, mock_server, view)
            for t in _THEMES:
                page.evaluate(
                    "(t) => document.documentElement.setAttribute('data-theme', t)",
                    t)
                out[(view, t)] = page.evaluate(
                    _MEASURE_JS, [_LISTS[view], list(_GRADES)])
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return out


def test_theme_scan_anchor(measured):
    assert len(_THEMES) >= 6, _THEMES
    # The theme flip must really repaint, or every theme measures one palette.
    bads = {tuple(measured[("history", t)]["badSoft"]) for t in _THEMES}
    assert len(bads) >= 3, f"theme flip inert: {bads}"


@pytest.mark.parametrize("view", ("history", "session"))
@pytest.mark.parametrize("theme", _THEMES)
def test_every_grade_chip_reaches_aa_on_its_fill(view, theme, measured):
    out = measured[(view, theme)]
    seen = {(c["grade"], c["row"]) for c in out["chips"]}
    # Anchor: every letter really measured, and the History list really
    # carried both result tints (a fix must hold on the loss tint too).
    for g in _GRADES:
        assert any(s[0] == g for s in seen), (view, theme, g, sorted(seen))
    if view == "history":
        rows = {s[1] for s in seen}
        assert {"win", "loss"} <= rows, (theme, rows)
    bad = []
    for c in out["chips"]:
        assert c["fill"] is not None, (view, theme, c)
        ratio = _ratio(c["color"], c["fill"])
        if ratio < 4.5:
            bad.append(
                f"{c['grade']} on {c['row']} row: rgb{tuple(c['color'][:3])}"
                f" on rgb{tuple(round(v) for v in c['fill'])}"
                f" = {ratio:.2f}:1")
    assert not bad, f"{view}/{theme}: below AA 4.5:1: {sorted(set(bad))}"


@pytest.mark.parametrize("theme", _THEMES)
def test_grade_chips_keep_their_hue_and_low_grades_their_tint(theme, measured):
    out = measured[("history", theme)]
    bad = []
    for c in out["chips"]:
        r, g, b = c["color"][:3]
        if c["grade"] in ("A", "B") and not g - max(r, b) >= 30:
            bad.append((c["grade"], "no longer reads green", (r, g, b)))
        if c["grade"] in ("S", "A", "B") and c["color"][:3] == out["text"][:3]:
            bad.append((c["grade"], "plain --text, hue lost"))
        if c["grade"] not in ("D", "F"):
            continue
        if not r - max(g, b) >= 60:
            bad.append((c["grade"], "no longer reads red", (r, g, b)))
        if c["color"][:3] == out["text"][:3]:
            bad.append((c["grade"], "plain --text, hue lost"))
        if c["tint"] != out["badSoft"]:
            bad.append((c["grade"], "tint moved", c["tint"], out["badSoft"]))
    assert not bad, f"{theme}: {bad}"
