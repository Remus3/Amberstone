"""
tests/snapshot_panels/test_lobby_mains_placeholder_contrast.py
S144-U-238 (s144 uiux): the Pre-Game Lobby's two last unmeasured dimmed
states reach their WCAG floors in all six themes:
- the PARTY MAINS empty slot (#lv-mainchamps-list .lv-mc-row.is-placeholder,
  the four dashed rows a solo lobby paints) - every "-" line reaches its
  text floor (1.4.3) on its resolved surface, ancestor opacity folded in;
- the offline / empty-slot status ring (.lv-top8-dot-off, a hollow ring in
  --dim) - a non-text state indicator, so 3:1 against the row it sits on
  (1.4.11), ring opacity and row opacity folded in.

S144-U-237 (cycle 232) filed both as FUTURE: the placeholder rows never
render under plain /?ui_mock=1#lobby (YOUR MAINS is the default tab), and
the ring was never read against 1.4.11. This test clicks PARTY MAINS (the
state envelope carries no lcu.lobby, so party_size is 0 and all four slots
are placeholders) and answers /api/top8 with SYNTHETIC entries (RM-906: no
real ids) so offline rings render.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"

_TOP8 = {"ok": True, "entries": [
    {"riot_id": "Alpha#AAA", "summoner_name": "Alpha", "games_with_me": 41,
     "preferred_role": "TOP", "is_online": True, "user_tag": "duo",
     "rank": {"tier": "GOLD", "division": "II", "lp": 40}},
    {"riot_id": "Bravo#BBB", "summoner_name": "Bravo", "games_with_me": 12,
     "preferred_role": "JUNGLE", "is_online": False, "user_tag": "flex",
     "rank": {"tier": "PLATINUM", "division": "IV", "lp": 12}},
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
            alpha: alpha(el), fg: s ? over(fg, s) : null, bg: s,
            px: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
            inactive: !!el.closest(':disabled, [aria-disabled="true"]')};
  };
  const list = document.getElementById('lv-mainchamps-list');
  const rows = [...list.querySelectorAll('.lv-mc-row.is-placeholder')];
  const texts = rows.flatMap((r) => [...r.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(line));
  const rings = [...document.querySelectorAll(
      '#lv-top8-list .lv-top8-dot-off')]
    .filter((e) => e.checkVisibility())
    .map((e) => {
      const cs = getComputedStyle(e);
      const ring = rgba(cs.borderTopColor);
      ring[3] *= alpha(e);
      const s = surface(e.parentElement);
      const row = e.closest('li');
      return {row: row ? String(row.className) : '',
              width: parseFloat(cs.borderTopWidth),
              style: cs.borderTopStyle, alpha: alpha(e),
              fg: s ? over(ring, s) : null, bg: s};
    });
  const named = [...document.querySelectorAll(
      '#lv-top8-list .lv-top8-name')]
    .find((n) => n.textContent.trim() === 'Alpha');
  const root = getComputedStyle(document.documentElement);
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    tab: list.dataset.tab, rows: rows.length,
    dashed: rows.map((r) => getComputedStyle(r).borderTopStyle),
    texts, rings,
    online: named ? line(named) : null,
    dim: rgba(root.getPropertyValue('--text-dim').trim()),
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
    page.route("**/api/top8*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_TOP8)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#lobby",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#lv-top8-list .lv-top8-name').length === 2",
            timeout=10_000,
        )
        page.click("#lv-mc-tab-party")
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#lv-mainchamps-list .lv-mc-row.is-placeholder').length === 4",
            timeout=10_000,
        )
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
def test_party_mains_placeholder_lines_reach_their_floor(
        theme, measured, mock_server, pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    assert got["theme"] == theme, "theme did not apply"
    assert got["tab"] == "party", got["tab"]
    assert got["rows"] == 4, got["rows"]
    rows = [r for r in got["texts"] if not r["inactive"]]
    # Anchor: 4 rows x 6 "-" lines (name, champ, mastery, points, result,
    # kda); an empty sweep would pass.
    assert len(rows) == 4 * 6, [r["text"] for r in rows]
    low = []
    for r in rows:
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        assert r["px"] >= 14, f"{r['cls']} {r['text']!r} at {r['px']}px"
        floor = 3.0 if _large(r) else 4.5
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < floor:
            low.append((r["cls"], r["text"], round(ratio, 2), floor))
    assert not low, f"{theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_offline_status_ring_reaches_non_text_floor(
        theme, measured, mock_server, pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    rings = got["rings"]
    # Anchor: Bravo's offline row plus the 6 empty Top 8 slots.
    offline = [r for r in rings if "is-offline" in r["row"]]
    empty = [r for r in rings if "is-placeholder" in r["row"]]
    assert len(offline) == 1, rings
    assert len(empty) == 6, rings
    low = []
    for r in rings:
        assert r["fg"] and r["bg"], f"no resolved surface under {r}"
        assert r["style"] == "solid" and r["width"] >= 2, r
        ratio = _ratio(r["fg"], r["bg"])
        if ratio < 3.0:
            low.append((r["row"], round(ratio, 2)))
    assert not low, f"{theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_placeholder_stays_secondary(theme, measured, mock_server,
                                     pw_browser):
    """The lift must not flatten the panel: the empty slot keeps its dashed
    border, and every "-" paints --text-dim, under an online --text name."""
    got = _got(measured, mock_server, pw_browser, theme)
    assert set(got["dashed"]) == {"dashed"}, got["dashed"]
    on = got["online"]
    assert on, "online Top 8 name not rendered"
    for r in got["texts"]:
        if r["inactive"]:
            continue
        assert all(abs(r["fg"][i] - got["dim"][i]) <= 3 for i in range(3)), (
            theme, r, got["dim"])
        assert _lum(r["fg"]) < _lum(on["fg"]), (theme, r)
