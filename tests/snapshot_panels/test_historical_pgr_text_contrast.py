"""
tests/snapshot_panels/test_historical_pgr_text_contrast.py
S144-U-207 (s144 uiux): every text line on the ARCHIVE Post Game Review
(#view-historical-pgr: head, hero, stat grid, team roster) reaches its WCAG
contrast floor on its resolved surface, in every theme, at the 1920x920
baseline and the 923x1280 companion window, for an SR match and an Arena
match.

The archive view shares the live view's .lm-tc-* roster CSS that
S144-U-206 lifted, but it carries its own head (.hpgr-tag, .hpgr-back) and
was never measured. At rest it measured clean (worst 4.88:1). The defects
sat in STATES no ui_mock fixture renders, all in last_match.css and so
shared by the live view (#view-last-match) and the archive:
  - the hero match score's "OK" tier (bare --accent-2): the 16 px tier word
    3.05 ember, 3.00 bloodmoon, 3.28 arcane on --surface;
  - its "Bad" tier (bare --bad): 4.14 hextech, 4.45 ember, 4.44 bloodmoon,
    3.93 moonlit, 3.89 arcane;
  - the KP% / Damage benchmark LOW sub-line (bare --signal-bad, 18 px
    regular): 4.48 moonlit, 4.44 arcane;
  - the MVP / SVP card's "Bad" tier (bare --bad), the same class as the
    hero's (S144-U-206 lifted only its "OK" tier).
test_state_marks_reach_their_floor_and_keep_their_hue stamps each state on
the real nodes (data-tier, data-result, the bench class) and reads it back.

Drive path: the test_pgr_roster_reflow._open_archive recipe - History under
?ui_mock=1, first session row, first match row - with /api/last-match
answered by the ui_mock last_match_<mode>.json fixture; the live view by
/?ui_mock=1&mode=sr#last-match.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_build_insights_chart_text_contrast import (
    _AA, _AA_LARGE, _ROW, _large, _low, _same,
)
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio
from tests.snapshot_panels.test_pgr_roster_reflow import _MOCK

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_MODES = ["sr", "arena"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]

_ALL = """async () => {
  await document.fonts.ready;
""" + _ROW + """
  const host = document.getElementById('view-historical-pgr');
  return [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
}"""


def _measure(mock_server, pw_browser, theme, mode, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    body = (_MOCK / f"last_match_{mode}.json").read_text(encoding="utf-8")
    page.route("**/api/last-match*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#history",
            wait_until="domcontentloaded", timeout=15_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        page.locator("#history-session-list .history-session-row").first.click()
        page.locator("#history-match-list .history-match-row").first.click()
        page.wait_for_selector("#view-historical-pgr", state="visible",
                               timeout=10_000)
        page.wait_for_function(
            "document.querySelectorAll('#hpgr-tc-table .lm-tc-row').length"
            " >= 4", timeout=10_000)
        rows = page.evaluate(_ALL)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return rows


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, mode, vp):
    key = (theme, mode, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode, vp)
    return measured[key]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_archive_pgr_text_line_reaches_its_floor(
        theme, mode, vp, measured, mock_server, pw_browser):
    rows = _get(measured, mock_server, pw_browser, theme, mode, vp)
    # Anchor: the view paints its head, hero and roster (an empty sweep
    # would pass).
    assert len(rows) >= 40, len(rows)
    seen = {r["cls"] for r in rows}
    for want in ("hpgr-tag", "hpgr-back", "lm-tc-name", "lm-tc-tag",
                 "lm-tc-lvl", "lm-tc-cs", "lm-tc-score-badge",
                 "lm-tc-group-result"):
        assert any(want in c for c in seen), (want, sorted(seen))
    low = _low(rows)
    assert not low, f"{theme} {mode} {vp}: {low}"


# Stamp every state on the real nodes, read it, restore nothing (the page
# is discarded). Transitions are off so a read never lands mid-fade.
_STATES = """async (vid) => {
""" + _ROW + """
  const v = document.getElementById(vid);
  const out = {};
  const sc = v.querySelector('.lm-hero-score');
  sc.hidden = false;
  for (const k of ['excellent', 'good', 'ok', 'bad']) {
    sc.dataset.tier = k;
    out['hero-value:' + k] = row(sc.querySelector('.lm-hero-score-value'));
    out['hero-tier:' + k] = row(sc.querySelector('.lm-hero-score-tier'));
  }
  const rs = v.querySelector('.lm-hero-result');
  rs.hidden = false;
  rs.textContent = 'DEFEAT';
  for (const k of ['win', 'loss', 'neutral']) {
    rs.dataset.result = k;
    out['result:' + k] = row(rs);
    out['result-border:' + k] = rgba(getComputedStyle(rs).borderTopColor);
  }
  const b = v.querySelector('.lm-bench-sub');
  b.hidden = false;
  b.textContent = 'LOW - p50 52';
  for (const k of ['avg', 'high', 'low']) {
    b.classList.remove('lm-bench-high', 'lm-bench-low');
    if (k !== 'avg') b.classList.add('lm-bench-' + k);
    out['bench:' + k] = row(b);
  }
  for (const card of v.querySelectorAll('.lm-tc-mvp:not([hidden])')) {
    const ms = card.querySelector('.lm-tc-mvp-score');
    if (!ms) continue;
    ms.hidden = false;
    for (const k of ['excellent', 'good', 'ok', 'bad']) {
      ms.dataset.tier = k;
      const pre = 'card-' + card.dataset.kind;
      out[pre + '-value:' + k] = row(ms.querySelector('.lm-tc-mvp-score-value'));
      out[pre + '-tier:' + k] = row(ms.querySelector('.lm-tc-mvp-score-tier'));
    }
  }
  out.tok = {text: tok('--text'), dim: tok('--text-dim'), bad: tok('--bad'),
             good: tok('--good'), accent: tok('--accent'),
             accent2: tok('--accent-2')};
  return out;
}"""


def _open_live(page, url, theme):
    page.goto(url + f"/?ui_mock=1&mode=sr&theme={theme}#last-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(() => { const t = document.querySelector('#lm-mode-tag');"
        " return !!t && t.textContent.trim() !== ''"
        " && t.textContent.trim() !== '-'; })()", timeout=10_000)
    page.click("#lm-tabbed-section .lm-tab[data-tab='build']")
    page.wait_for_selector("#lm-tc-ally-list .lm-tc-row", timeout=10_000)
    return "view-last-match"


def _open_archive(page, url, theme):
    body = (_MOCK / "last_match_sr.json").read_text(encoding="utf-8")
    page.route("**/api/last-match*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    page.goto(url + f"/?ui_mock=1&mode=sr&theme={theme}#history",
              wait_until="domcontentloaded", timeout=15_000)
    page.locator("#history-session-list .history-session-row").first.click()
    page.locator("#history-match-list .history-match-row").first.click()
    page.wait_for_function(
        "document.querySelectorAll('#hpgr-tc-table .lm-tc-row').length >= 4",
        timeout=10_000)
    return "view-historical-pgr"


def _red(fg):
    r, g, b = fg[:3]
    return r - max(g, b)


@pytest.mark.parametrize("view", ["live", "archive"])
@pytest.mark.parametrize("theme", _THEMES)
def test_state_marks_reach_their_floor_and_keep_their_hue(
        theme, view, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        opener = _open_live if view == "live" else _open_archive
        vid = opener(page, mock_server.url, theme)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        page.add_style_tag(content=_SHEET)
        m = page.evaluate(_STATES, vid)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    t = m.pop("tok")
    borders = {k: m.pop(k) for k in list(m) if k.startswith("result-border:")}
    # Anchor: every stamped node was found. The MVP / SVP cards are a live
    # view part only; the archive view has none.
    for key in ("hero-tier:ok", "hero-tier:bad", "result:loss", "bench:low"):
        assert key in m, (key, sorted(m))
    cards = {k for k in m if k.startswith("card-")}
    if view == "live":
        for key in ("card-mvp-tier:bad", "card-svp-tier:bad"):
            assert key in cards, (key, sorted(m))
    else:
        assert not cards, sorted(cards)
    low = {}
    for key, row in m.items():
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            low[key] = (round(ratio, 2), floor)
    assert not low, f"{theme} {view}: {low}"
    # Each tier is still its own mark: OK is not the Excellent gold, Bad
    # and LOW still read red, and the value matches its tier word.
    for pre in ["hero"] + sorted({k.split("-value:")[0] for k in m
                                  if k.startswith("card-")
                                  and "-value:" in k}):
        ok, exc = m[f"{pre}-tier:ok"], m[f"{pre}-tier:excellent"]
        assert not _same(ok["fg"], exc["fg"], tol=12), (pre, ok, exc)
        assert _red(m[f"{pre}-tier:bad"]["fg"]) >= 60, (pre, m[f"{pre}-tier:bad"])
        for k in ("excellent", "good", "ok", "bad"):
            assert _same(m[f"{pre}-value:{k}"]["fg"],
                         m[f"{pre}-tier:{k}"]["fg"]), (pre, k)
    assert _red(m["bench:low"]["fg"]) >= 60, m["bench:low"]
    assert _red(m["result:loss"]["fg"]) >= 60, m["result:loss"]
    # Frames keep their bare signal tokens.
    assert _same(borders["result-border:loss"], t["bad"]), (borders, t["bad"])
    assert _same(borders["result-border:win"], t["good"]), (borders, t["good"])
