"""
tests/snapshot_panels/test_session_text_contrast.py
S144-U-201 (s144 uiux): every text line on the Session view reaches its
WCAG contrast floor on its resolved surface, in every theme, at the
1920x1080 baseline and the 923x1280 companion window.

THE DEFECT. MEASURED headless under /?ui_mock=1#session before the fix
(colours resolved by the browser and composited over the stacked
backgrounds, lane doc traps 3 and 4 - the PAIR is fg on its own surface,
here the chip's --surface-3 and the card head's --surface-2):
- the TREND chip for a B grade (16 px / 800, not WCAG large text) painted
  the bare --accent-2: 2.60:1 ember, 2.56 bloodmoon, 2.77 arcane - the
  theme a fresh install boots on. The B chip is in the ui_mock fixture, so
  the shipped mock render showed it;
- the F chip painted the bare --bad: 3.66 hextech, 3.79 ember, 3.79
  bloodmoon, 3.31 moonlit, 3.28 arcane; only terminal passed (4.59);
- the PATCH card head's "from <patch>" line (.pi-from, 16 px / 400,
  --text-faint on the head's --surface-2): 4.46 hextech, 4.39 ember, 4.48
  moonlit, 4.31 arcane.
The S / A / C / D chips and the card body's other --text-faint lines (on
the card's own surface) measured 4.88:1 or more.

THE FIX (web/css/panels/header.css, web/css/panels/patch_impact.css): the
B and F chip TEXT is the grade hue mixed 60 percent into --text in oklab -
the same mix the Home RECENT row's grade cell uses for its D / F letters
(`.home-recent-grade.F`) - while the chip BORDER keeps the bare grade hue,
so the grade still reads by colour; .pi-from takes --text-dim. After: B
5.05 to 11.32, F 5.54 to 7.78, .pi-from at or over AA in every theme.

The trend strip is fed every grade letter (S A B C D F) through the real
renderer (`_renderSessionTrend`, by routing the ui_mock session fixture's
match grades), and the patch card is fed a populated payload in the
`patch_impact.test.mjs` shape, so every chip class and every card line is
on the page the sweep reads.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_ROOT = Path(__file__).resolve().parents[2]
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 1080), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_AA_LARGE = 3.0
# Newest first, as the session feed sends them; every letter the trend
# strip has a rule for, so each chip class is rendered.
_GRADES = ["F", "D", "C", "B", "A", "S"]
_HUE = {"S": "--accent", "A": "--good", "B": "--accent-2",
        "C": "--info", "D": "--warn", "F": "--bad"}

_JINX = {
    "champion_id": 222, "champion": "Jinx", "name": "Jinx",
    "games": 81, "wins": 53, "winrate": 65.1, "play_share": 4.0,
    "change_count": 2,
    "champion_changes": [{"field": "stats.attackdamage", "old": 59,
                          "new": 57}],
    "ability_changes": [], "build_changes": [],
    "item_changes": [{"item_id": "3153", "name": "Blade of the Ruined King",
                      "fields": [{"field": "gold.total", "old": 3200,
                                  "new": 3100}]}],
}
_QUIET = {
    "champion_id": 18, "champion": "Tristana", "name": "Tristana",
    "games": 61, "wins": 40, "winrate": 71.4, "play_share": 3.0,
    "change_count": 0, "champion_changes": [], "ability_changes": [],
    "build_changes": [], "item_changes": [],
}
_PATCH = {
    "ok": True, "mode": "aram", "old_patch": "16.13.1",
    "new_patch": "16.14.1", "n_matches": 2044, "changed_items": 8,
    "reason": None, "champions": [_JINX, _QUIET],
}


def _session_fixture() -> str:
    data = json.loads(
        (_ROOT / "web" / "data" / "ui_mock" / "session.json")
        .read_text(encoding="utf-8"))
    matches = data["matches"]
    assert len(matches) >= len(_GRADES), "fixture lost its match rows"
    for m, g in zip(matches, _GRADES):
        m["grade"] = g
    return json.dumps(data)


_MEASURE = """async (hue) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const host = document.getElementById('view-session');
  const row = (e) => {
    const s = surface(e);
    const cs = getComputedStyle(e);
    return {
      cls: String(e.className), text: e.textContent.trim().slice(0, 40),
      fg: s ? over(rgba(cs.color), s) : null, bg: s,
      border: rgba(cs.borderTopColor),
      size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
    };
  };
  const all = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
  const chips = [...host.querySelectorAll('.session-trend-chip')]
    .filter((e) => e.checkVisibility()).map(row);
  const root = getComputedStyle(document.documentElement);
  const tokens = {};
  for (const [g, name] of Object.entries(hue)) {
    tokens[g] = rgba(root.getPropertyValue(name).trim());
  }
  tokens.text = rgba(root.getPropertyValue('--text').trim());
  const one = (sel) => {
    const e = host.querySelector(sel);
    return e && e.checkVisibility() ? row(e) : null;
  };
  return {
    all, chips, tokens,
    from: one('#patch-impact-card .pi-from'),
    head: one('#patch-impact-card .session-card-head'),
  };
}"""


def _measure(mock_server, pw_browser, theme, vp):
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    body = _session_fixture()
    page.route("**/data/ui_mock/session.json", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    page.route("**/api/patch-impact", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(_PATCH)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#session",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.querySelectorAll('#session-trend-strip "
            f".session-trend-chip').length === {len(_GRADES)}",
            timeout=10_000)
        page.wait_for_selector("#patch-impact-card .pi-row", state="visible",
                               timeout=10_000)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        got = page.evaluate(_MEASURE, _HUE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _large(row):
    return row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)


@pytest.mark.parametrize("theme", _THEMES)
def test_every_trend_grade_chip_reaches_aa(theme, measured, mock_server,
                                           pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    chips = got["chips"]
    assert [c["text"] for c in chips] == _GRADES[::-1], chips
    for c in chips:
        assert c["bg"] is not None, (theme, c)
        # 16 px / 800 is not WCAG large text: the 4.5 floor applies.
        assert not _large(c), c
        ratio = _ratio(c["fg"], c["bg"])
        assert ratio >= _AA, (
            f"trend chip {c['text']} {ratio:.2f}:1 on {theme} "
            f"(fg {c['fg']}, bg {c['bg']}), under AA {_AA}")


@pytest.mark.parametrize("theme", _THEMES)
def test_every_chip_border_keeps_its_grade_hue(theme, measured, mock_server,
                                               pw_browser):
    """The text lift must not erase the grade colour: every chip's border
    is still its bare grade token, and no chip's text collapses to plain
    --text."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    tokens = got["tokens"]
    for c in got["chips"]:
        want = tokens[c["text"]]
        assert [round(v) for v in c["border"][:3]] == \
            [round(v) for v in want[:3]], (theme, c, want)
        assert [round(v) for v in c["fg"][:3]] != \
            [round(v) for v in tokens["text"][:3]], (theme, c)


@pytest.mark.parametrize("theme", _THEMES)
def test_the_patch_from_line_reaches_aa_under_its_head(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    frm, head = got["from"], got["head"]
    assert frm and head, got
    assert frm["text"].startswith("from 16.13.1"), frm
    ratio = _ratio(frm["fg"], frm["bg"])
    assert ratio >= _AA, (
        f".pi-from {ratio:.2f}:1 on {theme} (fg {frm['fg']}, "
        f"bg {frm['bg']}), under AA {_AA}")
    # It stays quieter than the PATCH label it annotates.
    assert frm["weight"] < head["weight"], (frm, head)
    assert frm["fg"][:3] != head["fg"][:3], (frm, head)


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_session_text_line_reaches_its_floor(theme, vp, measured,
                                                   mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    assert len(got["all"]) >= 40, (
        f"Session rendered too little text: {len(got['all'])}")
    low = []
    for row in got["all"]:
        assert row["bg"] is not None, (theme, vp, row)
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            low.append((row["cls"], row["text"], round(ratio, 2), floor))
    assert not low, f"under the WCAG floor on {theme} at {vp}: {low}"
