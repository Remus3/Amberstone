"""
tests/snapshot_panels/test_ds_cards_muted_text_contrast.py
RM-1143 (s144 uiux): the muted status lines on the Active Match DS
relative-score card (#csv-ds-relscore, web/js/panels/ds_relscore.js,
styled by web/css/panels/ds_relscore.css) and on the Builds SHAPER row
(web/js/panels/ds_shaper.js, web/css/panels/ds_shaper.css) reach WCAG AA on
their resolved surface, on all six themes.

MEASURED headless under /?ui_mock=1&mode=sr&theme=<t>#active-match at
1920x1080 before the fix (16px weight 400 text, so the 4.5:1 floor applies;
colours resolved by the browser and composited over the stacked backgrounds,
lane doc traps 3 and 4):
  .bm-shaper-note "shaper preview unavailable"   4.26 to 4.39:1
    (hextech, ember, bloodmoon, moonlit, arcane; terminal 4.52)
  .dsr-empty "resolving relative power..." and
    "no items rank for this build"              4.50 to 4.52:1
    (moonlit and arcane a hair under 4.5, so it failed there too; the
    secondary-tint check below pins it on every theme)
Both were white at 0.45 alpha, the one muted tint below the 0.55 the rest of
the DS cards use for secondary text (.dsr-head-sub, .dsr-gold, .dsp-head-sub,
.dsso-ult). They now take that 0.55. Every other text line on both surfaces
already measured 6.05:1 or better and is pinned here too, so a later edit
cannot drop one of them under the floor either.

The relscore card is driven through its real renderer against its real mount
(synthetic locked champion 51 and a routed /api/ds-relscore, the pattern
test_ds_relscore_view.py uses). The SHAPER row is the one active_match.js
paints itself; /api/ds-shape is routed to ok:false for the unavailable note
and to a synthetic ok payload for the landed preview lines.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

_RELSCORE = {"ok": True, "champion": "Caitlyn", "count": 2, "rows": [
    {"item_id": "3031", "name": "Infinity Edge", "delta_dps": 210.4,
     "score_pct": 100.0, "gold": 3450},
    {"item_id": "6672", "name": "Kraken Slayer", "delta_dps": 147.3,
     "score_pct": 70.0, "gold": 3100},
]}
_SHAPE_OK = {"ok": True,
             "baseline_pct": {"damage": 40, "survivability": 30, "utility": 30},
             "shaped_pct": {"damage": 50, "survivability": 25, "utility": 25}}

# Return every visible element that owns a text node under the host, as
# [state, className, text, textRGB, surfaceRGB]. Colours go through a 1px
# canvas (oklch included) and the text is composited over the stacked
# backgrounds down to the first opaque one.
_HELPERS = """
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, bot) => [0, 1, 2].map(
    (i) => top[i] * top[3] + bot[i] * (1 - top[3])).concat([1]);
  const surface = (el) => {
    const stack = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) stack.push(b);
      if (b[3] >= 1) break;
    }
    let acc = (stack.length && stack[stack.length - 1][3] >= 1)
      ? stack.pop() : null;
    if (!acc) return null;
    while (stack.length) acc = over(stack.pop(), acc);
    return acc;
  };
  const read = (state, host) => [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map((e) => {
      const s = surface(e);
      return [state, e.className, e.textContent,
              s ? over(rgba(getComputedStyle(e).color), s) : null, s];
    });
"""

# Pass "pending" + "landed": render, read the in-flight resolving line, wait
# for the routed rows. Pass "empty": the route now answers rows: [].
_MEASURE_RELSCORE = """async (phase) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const m = await import('/js/panels/ds_relscore.js');
  const host = document.getElementById('csv-ds-relscore');
  const cs = {my_champion: 51, queue_id: 420};
  const want = phase === 'landed' ? '.dsr-row' : '.dsr-empty';
  const out = [];
  m._resetDsRelscore();
  m.renderDsRelscore(host, cs);
  // The fetch is still in flight: the rows hold the resolving line.
  if (phase === 'landed') out.push(...read('pending', host));
  await new Promise((r) => {
    const t0 = Date.now();
    const done = () => phase === 'landed' ? !!host.querySelector(want)
      : /no items/.test(host.textContent);
    const tick = () => (done() || Date.now() - t0 > 5000)
      ? r() : setTimeout(tick, 50);
    tick();
  });
  out.push(...read(phase, host));
  return {hidden: host.hidden, rows: out};
}"""

_MEASURE_SHAPER = """async (state) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const host = document.querySelector('#view-active-match .bm-shaper');
  if (!host) return {rows: []};
  return {rows: read(state, host)};
}"""


def _open(mock_server, pw_browser, theme, shape_body):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    flags = {"empty": False}

    def relscore(route):
        # Ranked rows, or (once the test flips the flag) an ok payload with
        # no rows, the "no items" line.
        body = (dict(_RELSCORE, rows=[], count=0) if flags["empty"]
                else _RELSCORE)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    page.route("**/api/ds-relscore*", relscore)
    page.route("**/api/ds-shape*", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(shape_body)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        """async () => { try {
          const m = await import('/js/panels/cc_conditional_pressure.js');
          const n = m.resolveChampNames ? m.resolveChampNames([51]) : [];
          return !!(n && n.length && n[0]); } catch (e) { return false; } }""",
        timeout=10_000,
    )
    assert page.evaluate(
        "document.documentElement.dataset.theme || 'hextech'"
    ) == theme, f"booted on the wrong theme, not {theme}"
    return ctx, page, errors, flags


def _wait_shaper(page, cls):
    page.wait_for_function(
        f"!!document.querySelector('#view-active-match .bm-shaper .{cls}')",
        timeout=10_000,
    )


def _measure(mock_server, pw_browser, theme):
    rows = []
    ctx, page, errors, flags = _open(mock_server, pw_browser, theme,
                                     {"ok": False})
    try:
        _wait_shaper(page, "bm-shaper-note")
        rows += page.evaluate(_MEASURE_SHAPER, "shaper-unavailable")["rows"]
        for phase in ("landed", "empty"):
            flags["empty"] = phase == "empty"
            got = page.evaluate(_MEASURE_RELSCORE, phase)
            assert not got["hidden"], f"relscore card hidden ({phase})"
            rows += got["rows"]
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    ctx, page, errors, _ = _open(mock_server, pw_browser, theme, _SHAPE_OK)
    try:
        _wait_shaper(page, "bm-shaper-line")
        rows += page.evaluate(_MEASURE_SHAPER, "shaper-landed")["rows"]
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return rows


def _by(rows, state, cls):
    return [r for r in rows if r[0] == state and cls in r[1].split()]


@pytest.mark.parametrize("theme", _THEMES)
def test_ds_card_text_reaches_aa(mock_server, pw_browser, theme):
    rows = _measure(mock_server, pw_browser, theme)
    # An empty measurement must not pass: anchor every state's lines.
    assert [r[2] for r in _by(rows, "pending", "dsr-empty")] == [
        "resolving relative power..."], rows
    assert len(_by(rows, "landed", "dsr-item")) == 2, rows
    assert len(_by(rows, "landed", "dsr-gold")) == 2, rows
    assert [r[2] for r in _by(rows, "empty", "dsr-empty")] == [
        "no items rank for this build"], rows
    assert [r[2] for r in _by(rows, "shaper-unavailable",
                              "bm-shaper-note")] == [
        "shaper preview unavailable"], rows
    assert len(_by(rows, "shaper-unavailable", "bm-shaper-label")) == 3
    assert len(_by(rows, "shaper-landed", "bm-shaper-line")) == 3, rows
    for state, cls, text, fg, bg in rows:
        assert fg is not None and bg is not None, (
            f"{theme}/{state}: {cls} {text!r} has no opaque surface"
        )
        ratio = _ratio(fg, bg)
        assert ratio >= 4.5, (
            f"{theme}/{state}: .{cls} {text!r}"
            f" rgb{tuple(round(v) for v in fg[:3])} on"
            f" rgb{tuple(round(v) for v in bg[:3])} = {ratio:.2f}:1,"
            " below AA 4.5:1"
        )


@pytest.mark.parametrize("theme", ["hextech", "bloodmoon"])
def test_muted_lines_stay_secondary(mock_server, pw_browser, theme):
    rows = _measure(mock_server, pw_browser, theme)

    def r(row):
        return _ratio(row[3], row[4])

    # A status line is secondary: it never reads brighter than the card's
    # own title, nor than the reading it stands in for.
    title = _by(rows, "pending", "dsr-head-title")
    sub = _by(rows, "pending", "dsr-head-sub")
    assert len(title) == len(sub) == 1, rows
    for state in ("pending", "empty"):
        (empty,) = _by(rows, state, "dsr-empty")
        assert r(empty) < r(title[0]), (theme, state, r(empty))
        # ...but it is no dimmer than the card's own secondary text: the old
        # 0.45 tint sat on the AA floor (4.50:1) under a 6.07:1 subtitle.
        assert r(empty) >= r(sub[0]) - 0.05, (
            f"{theme}/{state}: .dsr-empty {r(empty):.2f}:1 below the"
            f" .dsr-head-sub tint {r(sub[0]):.2f}:1"
        )
        for item in _by(rows, "landed", "dsr-item"):
            assert r(empty) < r(item), (theme, state, r(empty), r(item))
    (note,) = _by(rows, "shaper-unavailable", "bm-shaper-note")
    for line in _by(rows, "shaper-landed", "bm-shaper-line"):
        assert r(note) < r(line), (theme, r(note), r(line))
    for label in _by(rows, "shaper-unavailable", "bm-shaper-label"):
        assert r(note) < r(label), (theme, r(note), r(label))
