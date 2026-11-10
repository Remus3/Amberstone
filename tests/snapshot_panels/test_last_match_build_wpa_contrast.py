"""
tests/snapshot_panels/test_last_match_build_wpa_contrast.py
S144-U-236 (s144 uiux): every text line of the last-match "Your build -
graded by your career" WPA strip (#pgr-build-wpa-mount,
web/js/panels/pgr_build_wpa.js, styled in web/css/panels/pgr_build_wpa.css)
reaches its WCAG floor on its resolved surface in all six themes, in both
states a chip can paint: an item with career WPA (+ / - value chip) and an
item without it (the "no data" chip, .pbw-chip.pbw-na).

MEASURED headless under /?ui_mock=1&mode=sr#last-match at 1920x920 before
the fix: the "no data" chip (16 px / 400, so the 4.5:1 floor applies)
painted --text-dim at opacity 0.6 over the strip card, about 3.3:1. No
documented exception covers it (docs/ outside the archive name .pbw-na only
in this program's FUTURE line; LEDGER 702's R47 audit of the panel checked
the font floor, not contrast), and this program already rejected dimming a
label by opacity because it sinks text under its floor (S144-U-235, the
S144 minimap stale-row ruling). "no data" is information the operator
reads (this buy has under 20 career purchases), not a disabled control.
The same sweep found the negative value chip (16 px / 700, bare
--signal-bad) at 3.89 to 4.45:1 in five themes. Ruling: "no data" paints
the oklab midpoint of --text-faint and --text-dim with no opacity
(--text-faint alone reads 4.31 to 4.48 on this --surface-2 card, the
S144-U-233 finding, and full --text-dim outshines the negative grade); the
negative value takes the RM-1550 red-text lift and its confidence segments
keep bare --signal-bad.

The mock fixture embeds no career maps, so the strip fetches the live
routes; this test answers /api/item-wpa and /api/skill-wpa itself with
SYNTHETIC career rows for two of the fixture's six final items (one
positive, one negative) and the reviewed champion's three basics, so both
chip states and the max-order row render. Opacity of every ancestor is
multiplied in (the shared _HELPERS read() does not fold it) and the
colour is composited over the stacked backgrounds, lane doc traps 3 and 4.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"

# Synthetic career rows (RM-906: no real ids). Item ids are the SR
# fixture's own final items; champion 103 is its reviewed champion.
_ITEMS = {"ok": True, "items": [
    {"item_id": 3157, "name": "Zhonya's Hourglass", "wpa": 0.031, "n": 42},
    {"item_id": 3089, "name": "Rabadon's Deathcap", "wpa": -0.024, "n": 31},
]}
_SKILLS = {"ok": True, "items": [
    {"champion_id": 103, "skill": "Q", "wpa": 0.018, "n": 64},
    {"champion_id": 103, "skill": "W", "wpa": -0.011, "n": 22},
    {"champion_id": 103, "skill": "E", "wpa": 0.004, "n": 25},
]}

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const line = (el) => {
    const cs = getComputedStyle(el);
    const fg = rgba(cs.color);
    fg[3] *= alpha(el);
    const s = surface(el);
    return {cls: String(el.className), text: el.textContent.trim(),
            fg: s ? over(fg, s) : null, bg: s,
            px: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10)};
  };
  const host = document.getElementById('pgr-build-wpa-mount');
  const rows = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(line);
  const q = (s) => { const e = host.querySelector(s);
    return e && e.checkVisibility() ? line(e) : null; };
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    hidden: host.hidden,
    rows,
    na: q('.pbw-chip.pbw-na'),
    naCount: host.querySelectorAll('.pbw-chip.pbw-na').length,
    pos: q('.pbw-item .pbw-chip.pbw-pos .pbw-chip-val'),
    neg: q('.pbw-item .pbw-chip.pbw-neg .pbw-chip-val'),
    label: q('.pbw-item-row .pbw-strip-label'),
    negSeg: (() => { const e = host.querySelector(
      '.pbw-item .pbw-seg.is-on.pbw-neg');
      return e ? rgba(getComputedStyle(e).backgroundColor) : null; })(),
    sbad: rgba(getComputedStyle(document.documentElement)
      .getPropertyValue('--signal-bad').trim()),
  };
}"""


def _large(row) -> bool:
    return row["px"] >= 24 or (row["px"] >= 18.66 and row["weight"] >= 700)


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    def _answer(body):
        return lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(body))

    page.route("**/api/item-wpa*", _answer(_ITEMS))
    page.route("**/api/skill-wpa*", _answer(_SKILLS))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#last-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_selector(
            "#pgr-build-wpa-mount .pbw-skill-row", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _got(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_every_build_wpa_line_reaches_its_floor(theme, measured, mock_server,
                                                pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    assert got["theme"] == theme, "theme did not apply"
    assert not got["hidden"], "build WPA strip hidden under the SR mock"
    # Anchor: both chip states and the strip chrome were read (an empty
    # sweep would pass). Four of the six final items carry no career row.
    assert got["naCount"] == 4, got["naCount"]
    for key in ("na", "pos", "neg", "label"):
        assert got[key] is not None, f"{key} not rendered"
    assert got["na"]["text"] == "no data", got["na"]["text"]
    seen = {r["cls"] for r in got["rows"]}
    for want in ("pbw-title", "pbw-sub", "pbw-strip-label", "pbw-chip-val",
                 "pbw-skill-key", "pbw-na"):
        assert any(want in c for c in seen), (want, sorted(seen))
    low = []
    for r in got["rows"]:
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        assert r["px"] >= 16, f"{r['cls']} {r['text']!r} at {r['px']}px"
        floor = 3.0 if _large(r) else 4.5
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < floor:
            low.append((r["cls"], r["text"], round(ratio, 2), floor))
    assert not low, f"{theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_no_data_chip_stays_quieter_than_values_and_label(
        theme, measured, mock_server, pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    na = got["na"]
    assert na and na["fg"], "no data chip not rendered"
    # "no data" is secondary: it reads dimmer than the strip label it sits
    # beside and dimmer than either value chip, so a real grade still
    # outshines the absence of one.
    for key in ("label", "pos", "neg"):
        other = got[key]
        assert _lum(na["fg"]) < _lum(other["fg"]), (
            f"{theme}: 'no data' is not dimmer than {other['text']!r}")


@pytest.mark.parametrize("theme", _THEMES)
def test_negative_chip_still_reads_red(theme, measured, mock_server,
                                       pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    neg, seg, sbad = got["neg"], got["negSeg"], got["sbad"]
    assert neg and neg["fg"] and seg, "negative chip not rendered"
    r, g, b = neg["fg"][:3]
    # The lifted value is still red by hue (red leads by a wide margin).
    assert r - max(g, b) >= 60, (theme, neg["fg"])
    # The confidence segment keeps bare --signal-bad.
    assert all(abs(seg[i] - sbad[i]) <= 3 for i in range(3)), (seg, sbad)
