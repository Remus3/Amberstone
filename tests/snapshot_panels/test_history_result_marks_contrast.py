"""
tests/snapshot_panels/test_history_result_marks_contrast.py
RM-1550 (s144 uiux) - every History view W / L mark reaches WCAG AA
(4.5:1) on its own resolved fill, in every theme.

WHAT IS MEASURED (headless Chromium, /?ui_mock=1#history at 1920x920, the
first session row chosen so its 2 win + 2 loss match rows paint; colours
resolved by the browser, oklch and color-mix included, lane doc trap 3; a
translucent fill composited over the first opaque ancestor, so the PAIR is
measured, never the token, trap 4):
  - the W and L result filter toggles in their ACTIVE state (18px weight
    800 - not WCAG "large" text, so the 4.5:1 bar applies);
  - the leading triangle glyph of a win / loss match row (16px weight 800,
    a ::before on the row) on the row's own result tint;
  - the session row W / L counts (.hs-w / .hs-l).
Each mark must also keep its hue (a loss reads red, a win reads green) and
differ from var(--text), and the tint behind it must still be its own
-soft token, so a fix can only move the text, never drop the encoding.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent


def _themes():
    # "hextech" is the DEFAULT palette at :root (web/css/themes.css header);
    # no [data-theme="hextech"] block exists, so stamping it selects :root.
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    found = set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text))
    return ["hextech"] + sorted(found - {"hextech"})


_THEMES = _themes()

_MEASURE_JS = r"""
async () => {
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
  const marks = [];
  const add = (kind, result, el, pseudo, tintEl) => {
    if (!el || !el.getClientRects().length) return;
    const cs = getComputedStyle(el, pseudo || null);
    // A pseudo mark is rendered only when it has content; its colour still
    // computes without any, so the box check above cannot see a lost glyph.
    if (pseudo && (cs.content === 'none' || cs.content === 'normal'
                   || cs.display === 'none')) return;
    marks.push({kind, result, color: rgba(cs.color), fill: fill(el),
                tint: rgba(getComputedStyle(tintEl || el).backgroundColor),
                fontSize: parseFloat(cs.fontSize),
                weight: parseInt(cs.fontWeight, 10)});
  };
  for (const r of document.querySelectorAll(
      '#history-match-list .history-match-row')) {
    const res = r.dataset.result || '';
    if (res === 'win' || res === 'loss') {
      add('row-glyph', res, r, '::before', r);
    }
  }
  for (const s of document.querySelectorAll(
      '#history-session-list .history-session-row')) {
    add('session-count', 'win', s.querySelector('.hs-w'), null, null);
    add('session-count', 'loss', s.querySelector('.hs-l'), null, null);
  }
  const btns = document.querySelectorAll(
    '#history-filter-result .history-filter-rbtn');
  const prev = Array.from(btns).map((b) => b.className);
  for (const b of btns) {
    const res = b.dataset.result;
    if (res !== 'win' && res !== 'loss') continue;
    btns.forEach((o) => o.classList.remove('active'));
    b.classList.add('active');
    add('filter-toggle', res, b, null, b);
  }
  btns.forEach((o, i) => { o.className = prev[i]; });
  return {text: rgba(getComputedStyle(document.documentElement)
                     .getPropertyValue('--text').trim()),
          goodSoft: tok('--good-soft'), badSoft: tok('--bad-soft'),
          marks};
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
        page.goto(mock_server.url + "/?ui_mock=1#history",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function("document.body.dataset.view === 'history'",
                               timeout=10_000)
        page.wait_for_selector("#history-session-list .history-session-row",
                               timeout=10_000)
        page.click("#history-session-list .history-session-row")
        page.wait_for_function(
            "document.querySelectorAll('#history-match-list"
            " .history-match-row[data-result]').length >= 2",
            timeout=10_000)
        page.add_style_tag(
            content="*, *::before, *::after { transition: none !important;"
            " animation: none !important; }")
        page.mouse.move(0, 0)
        for t in _THEMES:
            page.evaluate(
                "(t) => document.documentElement.setAttribute('data-theme', t)",
                t)
            out[t] = page.evaluate(_MEASURE_JS)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return out


def test_theme_scan_anchor(measured):
    assert len(_THEMES) >= 6, _THEMES
    # The theme flip must really repaint, or every theme measures one palette.
    bads = {tuple(measured[t]["badSoft"]) for t in _THEMES}
    assert len(bads) >= 3, f"theme flip inert: {bads}"


@pytest.mark.parametrize("theme", _THEMES)
def test_every_result_mark_reaches_aa_on_its_fill(theme, measured):
    out = measured[theme]
    kinds = {(m["kind"], m["result"]) for m in out["marks"]}
    # Anchor: every mark class really rendered, both results each.
    for kind in ("row-glyph", "session-count", "filter-toggle"):
        for res in ("win", "loss"):
            assert (kind, res) in kinds, (theme, kind, res, sorted(kinds))
    bad = []
    for m in out["marks"]:
        assert m["fill"] is not None, (theme, m)
        ratio = _ratio(m["color"], m["fill"])
        if ratio < 4.5:
            bad.append(
                f"{m['kind']}/{m['result']}: rgb{tuple(m['color'][:3])} on"
                f" rgb{tuple(round(v) for v in m['fill'])} = {ratio:.2f}:1")
    assert not bad, f"{theme}: below AA 4.5:1: {sorted(set(bad))}"


@pytest.mark.parametrize("theme", _THEMES)
def test_every_result_mark_keeps_its_hue_and_its_tint(theme, measured):
    out = measured[theme]
    bad = []
    for m in out["marks"]:
        r, g, b = m["color"][:3]
        if m["result"] == "loss" and not r - max(g, b) >= 60:
            bad.append((m["kind"], "loss no longer reads red", (r, g, b)))
        if m["result"] == "win" and not g - max(r, b) >= 30:
            bad.append((m["kind"], "win no longer reads green", (r, g, b)))
        if m["color"][:3] == out["text"][:3]:
            bad.append((m["kind"], m["result"], "plain --text, hue lost"))
        if m["kind"] in ("row-glyph", "filter-toggle"):
            want = out["goodSoft"] if m["result"] == "win" else out["badSoft"]
            if m["tint"] != want:
                bad.append((m["kind"], m["result"], "tint moved",
                            m["tint"], want))
    assert not bad, f"{theme}: {bad}"
