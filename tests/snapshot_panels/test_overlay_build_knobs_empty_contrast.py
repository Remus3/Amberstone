"""
tests/snapshot_panels/test_overlay_build_knobs_empty_contrast.py
S144-U-279 (s144 uiux): the build widget's fight-model empty line
(.dsk-empty, "resolving fight model..." / "no items rank under this fight
model", web/js/panels/ds_knobs.js) reaches the WCAG 1.4.3 AA text floor
(4.5:1) over any game pixel, both while w-build is live and in the idle
recede, in all six themes; its twin in the fight-model pane (w-ovds
.ovds-empty and the .ovset-cap "OVERLAY" caption, S144-U-272) holds AA in
the recede too.

THE DEFECT. MEASURED headless (mock server, ?ui_mock=1&mode=<sr|aram|
mayhem|arena>&overlay=1, 1920x1080, six themes): .dsk-empty painted
--faint, which on the w-build nested backing read AA live (4.88 hextech -
5.35 terminal) but 3.81 hextech, 3.85 arcane, 3.88 ember, 3.95 bloodmoon,
3.98 moonlit and 4.10 terminal in the idle recede (overlay.css section 6,
widget opacity 0.85), the same in every mode. The fight-model pane's own
empty line (.ovds-empty) had already moved to --text-dim in S144-U-272 and
reads 4.69 idle at its worst, so the two "resolving fight model..." lines
on one screen sat on different ink tiers.

THE FIX (web/css/panels/ds_knobs.css). .dsk-empty takes --text-dim, the
S144-U-243 / S144-U-272 empty-state tier. After, worst over six themes:
w-build 6.98 live / 5.24 idle; w-ovds unchanged at 6.37 / 4.69. The
dashboard champ-select copy of the card (#csv-ds-knobs) shares the rule and
only gains contrast.

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
# The lines read, as (widget id, class): the mock never resolves a fight
# model, so every field shows both panes in their empty state.
_TARGETS = [
    ("w-build", "dsk-empty"),
    ("w-ovds", "ovds-empty"),
    ("w-ovds", "ovset-cap"),
]
_SEL = ", ".join(f'.ovx-widget[data-ovx-id="{w}"] .{c}' for w, c in _TARGETS)

# One synchronous read per idle state: no poll can repaint between the
# line reads and the opacity reads.
_READ = """([idle, sel]) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const out = [];
  for (const h of document.querySelectorAll(sel)) {
    if (!h.checkVisibility()) continue;
    const w = h.closest('.ovx-widget');
    if (!w) continue;
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
    out.push({id: w.dataset.ovxId, cls: h.className,
              text: h.textContent.trim(), color: rgba(cs.color),
              inner: inner, layers: layers, wop: wop,
              size: parseFloat(cs.fontSize), w: hb.width, h: hb.height});
  }
  return out;
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
        for wid, cls in _TARGETS:
            page.wait_for_selector(
                f'.ovx-widget[data-ovx-id="{wid}"] .{cls}',
                state="visible", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, [0, _SEL]),
               "idle": page.evaluate(_READ, [1, _SEL])}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_fight_model_empty_line_reaches_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    bad = []
    for state in ("live", "idle"):
        lines = got[state]
        # Every target is on the page, so an empty read cannot pass.
        assert {(x["id"], x["cls"]) for x in lines} == set(_TARGETS), (
            state, lines)
        for x in lines:
            ratio = _worst(x)
            if ratio < _AA:
                bad.append(f"{state} {x['id']} .{x['cls']} {x['text']!r}"
                           f" {ratio:.2f}:1 (ink {x['color']},"
                           f" wop {x['wop']:.2f},"
                           f" {len(x['layers'])} backing layers)")
    assert not bad, f"{theme} {mode}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_recede_is_real_and_both_empty_lines_share_one_tier(
        theme, measured, mock_server, pw_browser):
    # The idle pair is honest only if the widgets really recede and the
    # line has a backing to read against; the two "resolving fight
    # model..." lines (build widget and fight-model pane) are one ink
    # tier, at the --fs-xs body size, with a real box.
    got = _get(measured, mock_server, pw_browser, theme, "sr")
    live = {(x["id"], x["cls"]): x for x in got["live"]}
    idle = {(x["id"], x["cls"]): x for x in got["idle"]}
    for key, x in live.items():
        assert x["wop"] == 1.0, (key, x["wop"])
        assert 0 < idle[key]["wop"] < 1.0, (key, idle[key]["wop"])
        assert x["layers"], (key, x)
        assert x["inner"] == 1.0, (key, x["inner"])
        assert x["size"] == 16.0, (key, x["size"])
        assert x["w"] > 0 and x["h"] > 0, (key, x)
    dsk = live[("w-build", "dsk-empty")]
    ovds = live[("w-ovds", "ovds-empty")]
    assert dsk["text"] == ovds["text"] == "resolving fight model...", (
        dsk["text"], ovds["text"])
    assert dsk["color"] == ovds["color"], (dsk["color"], ovds["color"])
