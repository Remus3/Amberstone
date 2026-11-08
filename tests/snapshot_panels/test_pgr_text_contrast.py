"""
tests/snapshot_panels/test_pgr_text_contrast.py
S144-U-206 (s144 uiux): every text line on every Post Game Review tab
(AI Analysis, Graph, Build), HTML and SVG, reaches its WCAG contrast floor
on its resolved surface, in every theme, at the 1920x920 baseline and the
923x1280 companion window, for an SR match and an Arena match (the Arena
fixture's own player is the losing side's SVP, so the self row carries the
SVP badge).

Found by a sweep of all three tabs; every defect sat on the Build tab:
  - the self row (.lm-tc-row-me) and the MVP card filled with the whole
    --hextech-border tint, a 16-34 percent BORDER token, so the row's
    level, CS and #rank cells (--text-dim) read 3.67-4.36:1 in five themes
    and the MVP word and its tier (--accent) 3.47 arcane, 4.35 terminal;
  - the player tag (.lm-tc-tag, --text-faint) 2.42-3.32:1 on that tint;
  - SVP text (bare --accent-2) 3.00-3.75:1 in ember, bloodmoon and arcane,
    1.75 where the self row is the SVP;
  - the DEFEAT word (bare --bad) 4.44 arcane, 4.48 moonlit;
  - the LANE MATCHUP behind delta (bare --signal-bad) 3.89-4.45 in five
    themes.
The win-probability, GPI and spike SVG charts (fill-painted text) were
measured clean in the same sweep.

Drive path: /?ui_mock=1&mode=<m>&theme=<t>#last-match, the recipe and
landing signal of test_pgr_review_r30._open_pgr; each tab opens through its
real tab button.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_build_insights_chart_text_contrast import (
    _ROW, _low, _over, _same,
)
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_MODES = ["sr", "arena"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_TABS = ["ai-analysis", "graph", "build"]
_AA = 4.5

_ALL = """async () => {
  await document.fonts.ready;
""" + _ROW + """
  const host = document.getElementById('view-last-match');
  return [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
}"""

# The fixed marks, each with the bare token it still has to carry.
_MARKS = """async () => {
""" + _ROW + """
  const q = (s) => document.querySelector('#view-last-match ' + s);
  const one = (s) => { const e = q(s); return e ? row(e) : null; };
  const cs = (s, p) => { const e = q(s);
    return e ? rgba(getComputedStyle(e)[p]) : null; };
  const me = q('.lm-tc-row.lm-tc-row-me');
  const other = q('.lm-tc-row:not(.lm-tc-row-me)');
  return {
    tag: one('.lm-tc-row-me .lm-tc-tag'),
    name: one('.lm-tc-row-me .lm-tc-name'),
    me_bg: me ? surface(me) : null,
    other_bg: other ? surface(other) : null,
    me_border: cs('.lm-tc-row.lm-tc-row-me', 'borderTopColor'),
    defeat: one('.lm-tc-group-result[data-result="loss"]'),
    defeat_border: cs('.lm-tc-group-result[data-result="loss"]',
                      'borderTopColor'),
    behind: one('.plc-delta.plc-behind'),
    behind_bar: cs('.plc-row[data-lead="behind"] .plc-bar-mine',
                   'backgroundColor'),
    svp: one('.lm-tc-score[data-kind="svp"] .lm-tc-score-badge'),
    svp_card: one('.lm-tc-mvp[data-kind="svp"] .lm-tc-mvp-badge'),
    svp_crown: cs('.lm-tc-mvp[data-kind="svp"] .lm-tc-mvp-crown', 'fill'),
    svp_frame: cs('.lm-tc-mvp[data-kind="svp"]', 'borderLeftColor'),
    mvp: one('.lm-tc-mvp[data-kind="mvp"] .lm-tc-mvp-badge'),
    rank: one('.lm-tc-score[data-kind="rank"] .lm-tc-score-badge'),
    tok: {text: tok('--text'), dim: tok('--text-dim'), bad: tok('--bad'),
          sbad: tok('--signal-bad'), accent: tok('--accent'),
          accent2: tok('--accent-2')},
  };
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
    got = {"tabs": {}}
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode={mode}&theme={theme}#last-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "(() => { const t = document.querySelector('#lm-mode-tag');"
            " return !!t && t.textContent.trim() !== ''"
            " && t.textContent.trim() !== '-'; })()", timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        # The tabs transition colour and border: with transitions off every
        # read below is the settled value (RM-1132).
        page.add_style_tag(content=_SHEET)
        land = {"build": "#lm-tc-ally-list .lm-tc-row"}
        if mode == "sr":
            # The win-probability chart is an SR-only card.
            land["ai-analysis"] = "#pgr-winprob-mount .pwp-ylab"
        for tab in _TABS:
            page.click(f"#lm-tabbed-section .lm-tab[data-tab='{tab}']")
            if tab in land:
                page.wait_for_selector(land[tab], timeout=10_000)
            page.wait_for_selector(
                "#view-last-match .plc-delta" if tab == "build"
                else "#lm-tabbed-section", timeout=10_000)
            got["tabs"][tab] = page.evaluate(_ALL)
            if tab == "build":
                got["marks"] = page.evaluate(_MARKS)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, mode, vp):
    key = (theme, mode, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode, vp)
    return measured[key]


def _red(fg):
    r, g, b = fg[:3]
    return r - max(g, b)


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_pgr_tab_text_line_reaches_its_floor(
        theme, mode, vp, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode, vp)
    low = {}
    for tab in _TABS:
        rows = got["tabs"][tab]
        # Anchor: every tab paints text (an empty sweep would pass).
        assert len(rows) >= 20, (tab, len(rows))
        bad = _low(rows)
        if bad:
            low[tab] = bad
    seen = {r["cls"] for rows in got["tabs"].values() for r in rows}
    # The fixed classes, and the SVG chart text, were all read.
    for want in ("lm-tc-tag", "lm-tc-lvl", "lm-tc-cs", "lm-tc-score-badge",
                 "lm-tc-mvp-badge", "lm-tc-group-result", "plc-behind"):
        assert any(want in c for c in seen), (want, sorted(seen))
    if mode == "sr":
        assert "pwp-ylab" in seen, sorted(seen)
        assert any(r["svg"] for r in got["tabs"]["ai-analysis"]), "no SVG"
    assert not low, f"{theme} {mode} {vp}: {low}"


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_fixed_marks_keep_their_role_and_hue(
        theme, mode, measured, mock_server, pw_browser):
    m = _get(measured, mock_server, pw_browser, theme, mode,
             _VIEWPORTS[0])["marks"]
    t = m["tok"]
    for key in ("tag", "name", "me_bg", "other_bg", "defeat", "behind",
                "behind_bar", "svp", "svp_card", "svp_crown"):
        assert m[key] is not None, (key, m)
    # The SR match has both cards; the Arena fixture has no MVP card.
    assert (m["mvp"] is not None) == (mode == "sr"), (mode, m["mvp"])
    # The self row is still marked: its own tint and the --accent frame.
    # (measured 20 or more on some channel in every theme at the half tint)
    assert max(abs(m["me_bg"][i] - m["other_bg"][i]) for i in range(3)) >= 12, (
        m["me_bg"], m["other_bg"])
    assert _same(m["me_border"], t["accent"]), (m["me_border"], t["accent"])
    # The tag is secondary: --text-dim, under the name it follows.
    tag, name = m["tag"], m["name"]
    assert _same(tag["fg"], _over(t["dim"], tag["bg"])), (tag, t["dim"])
    assert _ratio(tag["fg"], tag["bg"]) < _ratio(name["fg"], name["bg"])
    # DEFEAT and the behind delta still read red; frame and bar stay bare.
    assert _red(m["defeat"]["fg"]) >= 60, m["defeat"]["fg"]
    assert _same(m["defeat_border"], t["bad"]), (m["defeat_border"], t["bad"])
    assert _red(m["behind"]["fg"]) >= 60, m["behind"]["fg"]
    assert _same(m["behind_bar"], t["sbad"]), (m["behind_bar"], t["sbad"])
    # SVP text is its own mark: not the MVP gold, not a #rank grey, and the
    # SVP card's crown and frame keep bare --accent-2.
    for key in ("svp", "svp_card"):
        row = m[key]
        if m["mvp"] is not None:
            assert not _same(row["fg"], m["mvp"]["fg"], tol=12), (key, row)
        if m["rank"] is not None:
            assert not _same(row["fg"], m["rank"]["fg"], tol=12), (key, row)
        assert _ratio(row["fg"], row["bg"]) >= _AA, (key, row)
    assert _same(m["svp_crown"], t["accent2"]), (m["svp_crown"], t["accent2"])
    assert _same(m["svp_frame"], t["accent2"]), (m["svp_frame"], t["accent2"])
