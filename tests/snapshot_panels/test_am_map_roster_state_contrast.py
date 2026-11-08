"""
tests/snapshot_panels/test_am_map_roster_state_contrast.py
The Active Match MAP roster's state words reach WCAG AA on their own row in
every theme (session 144, lane uiux, S144-U-223).

Each roster row (web/js/panels/active_match.js _amUpdateMapText) is a
.am-mr-row on var(--surface-2) whose right-hand .am-mr-state word says what
the vision feed reports for that enemy: a zone ("MID", "on bridge") in the
live green, "MIA 25s" in amber, "DEAD 18s" in red, or "no feed" (S144-U-222)
while the feed is stalled. The words are 16 px / 700 (400 for "no feed"), so
the 4.5:1 normal-text floor applies. Measured on the headless render before
this slice (the S144-U-222 audit's SHOULD-FIX): "DEAD 18s", bare
var(--signal-bad) on --surface-2, read 3.89:1 in the default theme - the
one word on the row whose respawn countdown says when that enemy is back.

Contract pinned here, every theme, at the 1920x920 baseline:
  - every state word (ok / mia / dead / stale) is AA against the row's
    resolved background (the PAIR, lane doc trap 4: the word on
    --surface-2, never the token alone), oklch resolved by the browser
    (trap 3);
  - the state still reads by hue: DEAD keeps red leading green and blue,
    MIA keeps an amber (red and green over blue), the zone word keeps green
    leading red and blue;
  - the state words keep their size and weight (16 px; 700 for MIA and
    DEAD, 400 for the zone word and "no feed").

Drive path: /?ui_mock=1&mode=sr&theme=<t>#active-match with an empty
/api/state and a stand-in /api/vision-state (an SR state at 9:47 with one
enemy seen mid, one 25 s missing and one dead for 18 s). The theme is
stamped at BOOT (?theme=) and never swapped in-page (RM-1132 audit row in
test_theme_swap_reads_settled.py).
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import (
    _MAP_PNG,
    _ROSTER_JS,
    _Feed,
)

_THEMES = ("hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane")

_STATUS_JS = (
    "() => (document.getElementById('am-map-status') || {}).textContent || ''"
)
_FRESH = "9:47 - 1 visible - 1 MIA - 1 dead"
_ROSTER_FRESH = [
    ["Ahri", "ok", "MID"],
    ["Nidalee", "mia", "MIA 25s"],
    ["Lux", "dead", "DEAD 18s"],
]
_ROSTER_STALE = [[n, "stale", "no feed"] for n, _s, _t in _ROSTER_FRESH]


def _vs(t_now):
    """An SR state at 9:47 shaped like core/vision_tracker.py state(): Ahri
    seen mid, Nidalee 25 s gone from the river, Lux dead for 18 s more."""
    def enemy(name, level, **kw):
        row = {"champion": name, "team": "CHAOS", "level": level,
               "is_dead": False, "respawn_in_s": None, "visible": False,
               "missing_for_s": None, "last_seen_pos": None,
               "last_seen_t": 587.0, "last_seen_zone": None}
        row.update(kw)
        return row

    return {
        "t_now": t_now, "game_time": 587.0, "game_mode": "CLASSIC",
        "active_team": "ORDER",
        "enemies": {
            "Ahri": enemy("Ahri", 9, visible=True,
                          last_seen_pos={"x": 7400, "z": 7400},
                          last_seen_zone="MID"),
            "Nidalee": enemy("Nidalee", 8, missing_for_s=25.0,
                             last_seen_pos={"x": 9800, "z": 4400},
                             last_seen_t=562.0, last_seen_zone="RIVER"),
            "Lux": enemy("Lux", 9, is_dead=True, respawn_in_s=18.0),
        },
        "summary": {"visible_count": 1, "missing_count": 1, "dead_count": 1,
                    "total": 3},
    }


# Resolve every colour (oklch included) to sRGB bytes through a canvas and
# return one row per roster entry: state, word colour, its first opaque
# ancestor background, font size and weight.
_MEASURE = """() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgb = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]];
  };
  const opaque = (c) => {
    const m = /rgba?\\(([^)]*)\\)/.exec(c);
    if (!m) return c !== 'transparent';
    const p = m[1].split(/[ ,/]+/).filter(Boolean);
    return p.length < 4 || parseFloat(p[3]) >= 1;
  };
  const surface = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const b = getComputedStyle(n).backgroundColor;
      if (b && b !== 'transparent' && opaque(b)) return rgb(b);
    }
    return null;
  };
  return Array.from(document.querySelectorAll(
    '#am-map-roster .am-mr-row')).map((r) => {
    const s = r.querySelector('.am-mr-state');
    const cs = getComputedStyle(s);
    return {state: r.dataset.state || '', text: s.textContent,
            color: rgb(cs.color), surface: surface(s),
            rowBg: rgb(getComputedStyle(r).backgroundColor),
            px: parseFloat(cs.fontSize), weight: cs.fontWeight};
  });
}"""


def _lum(c) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _measure(mock_server, pw_browser, theme):
    """Boot the SR map on `theme`, read the live rows, then freeze the feed
    past the 10 s stale cut and read the "no feed" rows."""
    mock_server._store["data"] = {}
    feed = _Feed("live", _vs)
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/vision-state*", feed)
    page.route("**/img/map/*", lambda r: r.fulfill(
        status=200, content_type="image/png", body=_MAP_PNG))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_function(
            f"({_STATUS_JS})() === {json.dumps(_FRESH)}", timeout=10_000)
        booted = page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'")
        roster = page.evaluate(_ROSTER_JS)
        live = page.evaluate(_MEASURE)
        feed.kind = "frozen"
        page.clock.run_for(15_000)
        page.wait_for_function(
            f"JSON.stringify(({_ROSTER_JS})()) === "
            f"{json.dumps(json.dumps(_ROSTER_STALE, separators=(',', ':')))}",
            timeout=10_000,
        )
        stale = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    return {"booted": booted, "roster": roster, "live": live, "stale": stale,
            "errors": errors}


def _check_aa(theme, rows):
    for r in rows:
        assert r["surface"] is not None, (theme, r)
        # The word is measured on its own row (--surface-2), never on a pane
        # behind a row that stopped painting its background.
        assert r["surface"] == r["rowBg"], (theme, r)
        ratio = _ratio(r["color"], r["surface"])
        assert ratio >= 4.5, (
            f"{theme}/{r['state']} {r['text']!r}: rgb{tuple(r['color'])} on"
            f" rgb{tuple(r['surface'])} = {ratio:.2f}:1, below AA 4.5:1"
        )


@pytest.mark.parametrize("theme", _THEMES)
def test_roster_state_words_reach_aa_on_their_row(theme, mock_server, pw_browser):
    got = _measure(mock_server, pw_browser, theme)
    assert not got["errors"], got["errors"][:3]
    assert got["booted"] == theme, f"booted on the wrong theme, not {theme}"
    assert got["roster"] == _ROSTER_FRESH, got["roster"]
    # A non-empty measurement: every row of both reads was measured.
    assert [r["state"] for r in got["live"]] == ["ok", "mia", "dead"], got
    assert [r["state"] for r in got["stale"]] == ["stale"] * 3, got
    _check_aa(theme, got["live"])
    _check_aa(theme, got["stale"])


@pytest.mark.parametrize("theme", _THEMES)
def test_roster_state_words_keep_their_hue_and_type(theme, mock_server, pw_browser):
    got = _measure(mock_server, pw_browser, theme)
    assert not got["errors"], got["errors"][:3]
    by = {r["state"]: r for r in got["live"]}
    r, g, b = by["dead"]["color"]
    assert r - max(g, b) >= 60, (theme, "DEAD lost its red", by["dead"])
    r, g, b = by["mia"]["color"]
    assert min(r, g) - b >= 40 and r >= g, (theme, "MIA lost its amber", by["mia"])
    r, g, b = by["ok"]["color"]
    assert g - max(r, b) >= 20, (theme, "the zone word lost its green", by["ok"])
    weight = {"ok": "400", "mia": "700", "dead": "700", "stale": "400"}
    for row in got["live"] + got["stale"]:
        assert row["px"] >= 16, (theme, row)
        assert row["weight"] == weight[row["state"]], (theme, row)
