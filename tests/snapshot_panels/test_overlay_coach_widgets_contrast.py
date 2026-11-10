"""
tests/snapshot_panels/test_overlay_coach_widgets_contrast.py
S144-U-302 (s144 uiux): every text line of the three coach widgets the
?ui_mock=1 overlay never paints - w-lead (#rn-lead macro lead pill), w-callouts
(#rn-callouts ETA rows) and w-choices (#rn-choices A/B pick chips) - reaches
the WCAG 1.4.3 AA text floor on its own backing in all six themes, over any
game pixel, both while the widget is live and in the idle recede.

WHY. S144-U-299 swept every League overlay widget ?ui_mock=1 paints and
S144-U-301 added the w-call objective chips off a live envelope. These three
stayed dark in both: the B4 gate (web/js/lib/live_directive_gate.js
directivesAllowed) blanks their imperatives whenever a live feed is up, and the
ui_mock fixtures carry no lead_projection, callouts or choices. They do paint
in a no-feed window (champ select, loading, a relay gap). The sweep drives
their render modules directly (callouts.js renderLead / renderCallouts,
coach_choices.js renderCoachChoices) with a no-feed state, as
test_overlay_hotkey_hint_contrast.py already does for the A/B pick.

Values are the real generator strings: core/lead_projection.py directive
table (ahead / behind / even lines, slight / clear / large magnitudes) and
core/event_callouts.py objective lines (an active NOW row, an ETA row, and a
third row with no ETA that the overlay density clamp hides).

THE DEFECTS. Live every line held AA. In the idle recede (widget opacity
0.85) over a white game pixel, four lines fell under 4.5:1 in all six themes
(the --ovx-* palette is theme-independent, so every theme read the same):
- the upcoming callout ETA chip ("1:35"), gold 0.85 ink on the base 0.06
  white wash: 3.94:1;
- the NOW callout chip, cyan ink on a 0.18 cyan tint: 4.15:1;
- the lead pill tag ("behind - clear"), rgba(--ovx-text, 0.55): 4.14:1;
- the per-chip Alt+N pick key on w-choices, 0.55 ink on the 0.06 wash:
  4.11:1.

THE FIX (web/css/overlay.css, overlay-scoped). Both ETA chips and the pick
key sit on rgba(--ovx-bg-nested, 0.9), the inset-row backing (the S144-U-301
objective chip and S144-U-278 reminder precedents); the hue stays on the ink
and the NOW border. The lead tag and the pick key take the 0.70 reminder ink.
After, worst idle: upcoming ETA 4.91, lead tag 5.64, NOW 6.62, pick key 7.10.

Contrast pair: the S144-U-299 method (_READ, _worst; _READ reads each line
with getComputedStyle, SVG text by its fill), the ink with every inner
opacity folded in, over every backing of the line and its ancestors up to
the widget whose box contains it, then the widget opacity, over a game pixel
G in {0, 64, 128, 192, 255}. Large text (24 px, or 18.66 px at weight 700 or
more; WCAG 1.4.3) is held at 3:1, everything else at 4.5:1.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_overlay_hotkey_hint_contrast import _worst
from tests.snapshot_panels.test_overlay_league_text_contrast import (
    _READ,
    _SHEET,
    _THEMES,
)

_AA = 4.5
_LARGE_FLOOR = 3.0
_COACH = ("w-lead", "w-callouts", "w-choices")
_LEADS = ("ahead", "behind", "even")

# Real generator strings (see the module docstring for the source tables).
_LEAD = {
    "ahead": {"state": "ahead", "magnitude": "large",
              "line": "Big lead: dive or roam, snowball it now."},
    "behind": {"state": "behind", "magnitude": "clear",
               "line": "Behind: farm safe under tower, scale up."},
    "even": {"state": "even", "magnitude": "slight",
             "line": "Even: trade for prio, track the jungler."},
}
_CALLOUTS = [
    {"tag": "herald", "kind": "objective", "eta_s": 0,
     "line": "Herald UP now - take it"},
    {"tag": "baron", "kind": "objective", "eta_s": 95,
     "line": "Baron up 20:00 - ward river"},
    {"tag": "dragon", "kind": "objective", "eta_s": None,
     "line": "Drake spawns 5:00 - set up vision"},
]
_CHOICES = [
    {"key": "A", "label": "Trade", "confidence": "high"},
    {"key": "B", "label": "Back off", "confidence": "mid"},
    {"key": "C", "label": "Roam mid", "confidence": "low"},
]

# Render with a no-feed state (no liveclient, so directivesAllowed is true),
# place the field, then read both idle states in one synchronous pass.
_RENDER = """async (arg) => {
  const C = await import('/js/panels/callouts.js');
  const K = await import('/js/panels/coach_choices.js');
  const st = {mode_key: 'sr', lead_projection: arg.lead,
              callouts: arg.callouts, coach: {choices: arg.choices}};
  C.renderLead(st);
  C.renderCallouts(st);
  K.renderCoachChoices(st);
  if (arg.selected) {
    const chip = document.querySelector('#rn-choices .rc-chip');
    if (chip) chip.classList.add('rc-selected');
  }
  (await import('/js/lib/overlay_layout.js')).placeOverlayField();
}"""

_READ_W = _READ.replace(
    "size: parseFloat(cs.fontSize)}",
    "size: parseFloat(cs.fontSize), weight: parseFloat(cs.fontWeight)}")
assert _READ_W != _READ, "the weight read did not splice into _READ"


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, lead):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url
                  + f"/?ui_mock=1&mode=sr&overlay=1&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'", timeout=10_000)
        page.wait_for_selector(
            '.ovx-widget[data-ovx-id="w-call"] #am-call-body > div',
            state="visible", timeout=10_000)
        page.evaluate(_RENDER, {"lead": _LEAD[lead], "callouts": _CALLOUTS,
                                "choices": _CHOICES,
                                "selected": lead == "ahead"})
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ_W, 0),
               "idle": page.evaluate(_READ_W, 1)}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, lead):
    key = (theme, lead)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, lead)
    return measured[key]


def _floor(ln):
    large = ln["size"] >= 24 or (ln["size"] >= 18.66 and ln["weight"] >= 700)
    return _LARGE_FLOOR if large else _AA


@pytest.mark.parametrize("lead", _LEADS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_coach_widget_line_reaches_aa_live_and_idle(
        theme, lead, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, lead)
    low = []
    for state in ("live", "idle"):
        widgets = got[state]
        # Anchor: a widget that failed to paint would pass the loop.
        for wid in _COACH:
            assert widgets.get(wid), f"{state}: {wid} read no text"
        texts = {wid: [ln["text"] for ln in widgets[wid]] for wid in _COACH}
        # _READ keeps the first 28 characters of each line.
        assert _LEAD[lead]["line"][:28] in texts["w-lead"], texts["w-lead"]
        assert "NOW" in texts["w-callouts"], texts["w-callouts"]
        assert "1:35" in texts["w-callouts"], texts["w-callouts"]
        assert {"A", "B", "C"} <= set(texts["w-choices"]), texts["w-choices"]
        if state == "idle":
            assert all(0 < ln["wop"] < 1.0
                       for wid in _COACH for ln in widgets[wid]), state
        for wid in _COACH:
            for ln in widgets[wid]:
                assert not ln["aria"], (wid, ln)
                ratio = _worst(ln)
                if ratio < _floor(ln):
                    low.append((state, wid, ln["cls"], ln["text"],
                                round(ratio, 2), ln["color"],
                                ln["layers"][:2]))
    assert not low, f"{theme} {lead}: {low}"


_NESTED = [10, 14, 20]


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_eta_and_pick_key_chips_sit_on_the_nested_backing(
        theme, measured, mock_server, pw_browser):
    # Palette law (doctrine section 5): each chip's own backing is the
    # inset-row --ovx-bg-nested at 0.9, not a white wash or a hue tint; the
    # hue rides the ink (NOW cyan, upcoming faint gold), the pick key and the
    # lead tag stay neutral at the 0.70 reminder tier.
    got = _get(measured, mock_server, pw_browser, theme, "behind")
    live = got["live"]
    by_cls = {}
    for wid in _COACH:
        for ln in live[wid]:
            by_cls.setdefault(ln["cls"], []).append(ln)
    want_ink = {
        "rc-co-eta rc-co-now": [10, 200, 185, 1.0],
        "rc-co-eta": [200, 170, 110, 0.85],
        "rc-hotkey": [255, 255, 255, 0.70],
    }
    for cls, ink in want_ink.items():
        lines = by_cls.get(cls)
        assert lines, (cls, sorted(by_cls))
        for ln in lines:
            own = ln["layers"][0]
            assert own[:3] == _NESTED and abs(own[3] - 0.9) < 0.01, ln
            assert ln["color"][:3] == ink[:3], ln
            assert abs(ln["color"][3] - ink[3]) < 0.01, ln
    tag = by_cls["rc-lead-tag"][0]
    assert tag["color"][:3] == [255, 255, 255], tag
    assert abs(tag["color"][3] - 0.70) < 0.01, tag
