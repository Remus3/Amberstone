"""
tests/snapshot_panels/test_overlay_build_rerank_clip.py
S144-U-280 (s144 uiux): in the overlay shell the BUILD widget (w-build,
doctrine section 4: "next-item rerank") shows its rerank module - the
Daemon Slayer ranks, the Meta Build and Ultimate Build rows and the shaper
strip - inside its own clip in every mode, and the shaper strip's
"shaper preview unavailable" note (.bm-shaper-note, ds_shaper.js) reaches
the WCAG 1.4.3 AA text floor (4.5:1) live and in the idle recede in all six
themes.

THE DEFECT. QA ledger FUTURE (e) filed .bm-shaper-note at about 4.2 - 4.4:1
idle; the S144-U-279 sweep then read it 1.00:1. Re-measured headless (mock
server, ?ui_mock=1&mode=<sr|aram|mayhem|arena>&overlay=1, 1920x1080): the
note is not a contrast miss at all, it is CLIPPED. QA 2026-07-03 B20/B22
relocated the eight-axis profile, the fight-model card and the Stat Sandbox
onto the BUILD pane after overlay.css wrote its "GPU-light: DS-analysis
widgets off" rule, so the overlay painted two of them: the fight-model card
(162 px) and the Stat Sandbox form (342 px) took 504 px of the 594 px
widget, whose .am-pane box is overflow: hidden. #am-build-body
(flex 1 1 auto, min-height 0) was squeezed to 28 - 56 px and pushed below
the widget's bottom edge (top 1001 - 1121 against a widget bottom of 1064),
so every rerank row - Daemon Slayer at top 1015 - 1135, the shaper note at
1418 - 1538 - painted outside the clip, in every mode and theme. The widget
showed the fight-model card twice over (w-ovds is the overlay's own
fight-model pane) and a four-input what-if form, and none of its job.

THE FIX (web/css/overlay.css section 3, the GPU-light rule). .ds-profile,
.ds-knobs and .ds-statcheck join .ds-sweep / .ds-matchup / .ds-combo /
.ds-relscore off in the overlay BUILD pane. The dashboard copies are
untouched (the rule is body[data-shell="overlay"] only). After: the rerank
module sits inside the clip in all four modes; the capability-gap chip
(sr) still sits above it.

Contrast pair (the S144-U-275 / S144-U-278 method): the ink, with any
opacity inside the widget folded in, over the backgrounds of the line and
of every ancestor up to its widget whose box contains the line, then the
widget opacity, over a game pixel G in {0, 64, 128, 192, 255}, against the
same chain without the ink.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_overlay_hotkey_hint_contrast import _worst

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["sr", "aram", "mayhem", "arena"]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
_W = '.ovx-widget[data-ovx-id="w-build"]'
# The rerank rows, in render order (active_match.js build module).
_ROWS = ["bm-live", "bm-meta", "bm-ult", "bm-shaper"]
# The dashboard DS cards the overlay BUILD pane does not paint.
_OFF = ["ds-sweep", "ds-matchup", "ds-combo", "ds-relscore", "ds-profile",
        "ds-knobs", "ds-statcheck"]

# One synchronous read per idle state: no poll can repaint between the
# note read, the box reads and the opacity reads.
_READ = """([idle, wsel, rows, off]) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const box = (r) => ({left: r.left, right: r.right, top: r.top,
                       bottom: r.bottom});
  const w = document.querySelector(wsel);
  if (!w) return null;
  // The widget's clip: its padding box (overflow hidden on the .am-pane).
  const wr = w.getBoundingClientRect();
  const clip = {left: wr.left + w.clientLeft, top: wr.top + w.clientTop};
  clip.right = clip.left + w.clientWidth;
  clip.bottom = clip.top + w.clientHeight;
  const rowBoxes = rows.map((c) => {
    const el = w.querySelector('.bm-row.' + c);
    return el ? {cls: c, box: box(el.getBoundingClientRect())} : {cls: c};
  });
  const offDisplay = off.map((c) => {
    const el = w.querySelector(':scope > .' + c);
    return [c, el ? getComputedStyle(el).display : 'absent'];
  });
  const notes = [];
  for (const h of w.querySelectorAll('.bm-shaper-note')) {
    const hb = h.getBoundingClientRect();
    const layers = [];
    let inner = 1;
    for (let n = h; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const b = rgba(cs.backgroundColor);
      if (b[3] > 0 && inside(n.getBoundingClientRect(), hb)) layers.push(b);
      if (n === w) break;
      inner *= parseFloat(cs.opacity);
    }
    let wop = 1;
    for (let n = w; n; n = n.parentElement) {
      wop *= parseFloat(getComputedStyle(n).opacity);
    }
    const cs = getComputedStyle(h);
    notes.push({text: h.textContent.trim(), color: rgba(cs.color),
                inner: inner, layers: layers, wop: wop,
                size: parseFloat(cs.fontSize), box: box(hb),
                inClip: inside(clip, hb)});
  }
  const ovds = document.querySelector('.ovx-widget[data-ovx-id="w-ovds"]');
  return {clip: clip, rows: rowBoxes, off: offDisplay, notes: notes,
          ovds: !!(ovds && ovds.checkVisibility())};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url
                  + f"/?ui_mock=1&mode={mode}&overlay=1&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'", timeout=10_000)
        # The note is the shaper strip's last paint; the rerank rows and
        # the fight-model pane are on the page before it.
        page.wait_for_selector(f"{_W} .bm-shaper-note", state="attached",
                               timeout=10_000)
        page.wait_for_selector('.ovx-widget[data-ovx-id="w-ovds"]',
                               state="visible", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        args = [_W, _ROWS, _OFF]
        got = {"live": page.evaluate(_READ, [0, *args]),
               "idle": page.evaluate(_READ, [1, *args])}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    assert got["live"] and got["idle"], "w-build is not on the page"
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


def _inside(clip, b):
    return (b["left"] >= clip["left"] - 0.5
            and b["right"] <= clip["right"] + 0.5
            and b["top"] >= clip["top"] - 0.5
            and b["bottom"] <= clip["bottom"] + 0.5)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_every_rerank_row_sits_inside_the_widget_clip(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)["live"]
    clip = got["clip"]
    # A real clip: the widget's fixed box, not a zero or unbounded one.
    assert 300 < clip["bottom"] - clip["top"] < 1080, clip
    bad = []
    for r in got["rows"]:
        # Every row is on the page, so an empty read cannot pass.
        assert "box" in r, f"{theme} {mode}: .bm-row.{r['cls']} absent"
        b = r["box"]
        assert b["bottom"] > b["top"], (r["cls"], b)
        if not _inside(clip, b):
            bad.append(f".{r['cls']} top {b['top']:.0f} bottom"
                       f" {b['bottom']:.0f}")
    assert not bad, (
        f"{theme} {mode}: outside the w-build clip (top {clip['top']:.0f},"
        f" bottom {clip['bottom']:.0f}): " + "; ".join(bad))


@pytest.mark.parametrize("mode", _MODES)
def test_the_dashboard_ds_cards_stay_off_and_the_fight_model_pane_stays(
        mode, measured, mock_server, pw_browser):
    # The overlay BUILD pane paints none of the dashboard DS cards; the
    # overlay keeps its own fight-model pane (w-ovds).
    got = _get(measured, mock_server, pw_browser, "hextech", mode)["live"]
    assert len(got["off"]) == len(_OFF), got["off"]
    painted = [c for c, d in got["off"] if d not in ("none", "absent")]
    assert not painted, f"{mode}: painted in w-build: {painted}"
    assert any(d == "none" for _c, d in got["off"]), (
        f"{mode}: no card mounted, the read proves nothing: {got['off']}")
    assert got["ovds"], f"{mode}: the fight-model pane w-ovds is not visible"


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_shaper_note_is_in_the_clip_and_reaches_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    bad = []
    for state in ("live", "idle"):
        notes = got[state]["notes"]
        assert len(notes) == 1, (state, notes)
        x = notes[0]
        assert x["text"] == "shaper preview unavailable", x["text"]
        assert x["size"] == 16.0, x["size"]
        assert x["layers"], (state, x)
        assert x["inClip"], (
            f"{theme} {mode} {state}: the note is outside the w-build clip"
            f" (top {x['box']['top']:.0f})")
        ratio = _worst(x)
        if ratio < _AA:
            bad.append(f"{state} {ratio:.2f}:1 (ink {x['color']},"
                       f" wop {x['wop']:.2f})")
    # The idle pair is honest only if the widget really recedes.
    assert got["live"]["notes"][0]["wop"] == 1.0
    assert 0 < got["idle"]["notes"][0]["wop"] < 1.0
    assert not bad, f"{theme} {mode}: " + "; ".join(bad)
