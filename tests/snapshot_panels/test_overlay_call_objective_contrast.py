"""
tests/snapshot_panels/test_overlay_call_objective_contrast.py
S144-U-288 (s144 uiux): the w-call OBJECTIVE footer (the macro line under the
ACTION verb, #am-call-body > div[data-call-line="objective"]) reaches the
WCAG 1.4.3 AA text floor (4.5:1) over any game pixel, both while the call
widget is live and in the idle recede, in all six themes and every League
mode whose fixture carries an objective.

THE DEFECT (QA ledger FUTURE (d)). Measured headless (mock server,
?ui_mock=1&mode=<sr|aram|mayhem|arena>&overlay=1, 1920x1080, six themes): the
footer painted rgba(--ovx-text, 0.55) on the call pane's backing. Numbers are
in docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md under S144-U-288.

Contrast pair (the S144-U-275 / S144-U-278 / S144-U-279 method): the ink, with
any opacity inside the widget folded in, over the backgrounds of the line and
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
_CALL = '.ovx-widget[data-ovx-id="w-call"] #am-call-body > div'
_LINES = {
    "objective": f'{_CALL}[data-call-line="objective"] > span:last-child',
    "action": f'{_CALL}[data-call-line="action"] > span:last-child',
}

# One synchronous read per idle state: no poll can repaint between the line
# reads and the opacity reads.
_READ = """([idle, sels]) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const out = {};
  for (const [key, sel] of Object.entries(sels)) {
    const h = document.querySelector(sel);
    if (!h || !h.checkVisibility()) continue;
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
    const wb = w.getBoundingClientRect();
    out[key] = {text: h.textContent.trim(), color: rgba(cs.color),
                inner: inner, layers: layers, wop: wop,
                size: parseFloat(cs.fontSize),
                weight: parseInt(cs.fontWeight, 10),
                clamp: cs.webkitLineClamp,
                w: hb.width, h: hb.height,
                inWidget: hb.top >= wb.top - 0.5
                  && hb.bottom <= wb.bottom + 0.5};
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
        for sel in _LINES.values():
            page.wait_for_selector(sel, state="visible", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, [0, _LINES]),
               "idle": page.evaluate(_READ, [1, _LINES])}
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
def test_call_objective_footer_reaches_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    bad = []
    for state in ("live", "idle"):
        x = got[state].get("objective")
        # The footer is on the page, so an empty read cannot pass.
        assert x and x["text"], (state, got[state])
        ratio = _worst(x)
        if ratio < _AA:
            bad.append(f"{state} {ratio:.2f}:1 (ink {x['color']},"
                       f" wop {x['wop']:.2f},"
                       f" {len(x['layers'])} backing layers)")
    assert not bad, f"{theme} {mode}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_recede_is_real_and_the_footer_stays_the_quiet_tier(
        theme, measured, mock_server, pw_browser):
    # The idle pair is honest only if the widget really recedes and the
    # footer has a backing to read against. Hierarchy: the footer stays
    # below the ACTION verb on every channel (ink alpha, size, weight), it
    # keeps neutral white ink (the band hues belong to the verb row), it
    # keeps its 3-line clamp and its box stays inside the call widget.
    got = _get(measured, mock_server, pw_browser, theme, "sr")
    obj, act = got["live"]["objective"], got["live"]["action"]
    idle = got["idle"]["objective"]
    assert obj["wop"] == 1.0, obj["wop"]
    assert 0 < idle["wop"] < 1.0, idle["wop"]
    assert obj["layers"], obj
    assert obj["inner"] == 1.0, obj["inner"]
    assert obj["color"][:3] == [255, 255, 255], obj["color"]
    assert act["color"][:3] == [255, 255, 255], act["color"]
    assert 0.55 < obj["color"][3] < act["color"][3] == 1.0, (
        obj["color"], act["color"])
    assert obj["color"][3] <= 0.75, obj["color"]
    assert obj["size"] == 12.0 and obj["size"] < act["size"], (
        obj["size"], act["size"])
    assert obj["weight"] < act["weight"], (obj["weight"], act["weight"])
    assert obj["clamp"] == "3", obj["clamp"]
    assert obj["w"] > 0 and obj["h"] > 0, obj
    assert obj["inWidget"], obj
