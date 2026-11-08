"""
tests/snapshot_panels/test_build_insights_chart_text_contrast.py
S144-U-205 (s144 uiux): every text line on every Build Insights tab reaches
its WCAG contrast floor on its resolved surface, in every theme, at the
1920x920 baseline and the 923x1280 companion window.

Found by a sweep that opened all nine tabs (the cycle 191 sweep read the
Items tab only). Three defects, all on chart tabs:
  - the Game Length and Snowball "worse" value and lean chip
    (.dw-val/.dw-chip.dw-bad, .se-val/.se-chip.se-bad, bare --signal-bad)
    sat under AA in arcane, moonlit and (by a hair) hextech;
  - the Game Length champion filter's ALL button (.dw-champ-clear) and the
    OP Score arc chips' Wins / Losses word (.op-arc-side) were --text-faint
    on --surface-3, 3.64 to 3.94:1 in five themes;
  - the OP Score and Game Flow charts' axis labels (.op-ylab / .op-xlab,
    .pf-ylab / .pf-xlab), the same --text-faint on the same --surface-3,
    painted through `fill`, which a colour-only sweep never reads; under
    AA wherever they render under large-text size (the 923 px window).

Drive path: /?ui_mock=1&theme=<t>#build-insights, the recipe and landing
signal of test_build_insights_review_r30._open_bi; each tab opens through
its real tab button.

The good / bad / dim states are measured on the one real rendered value
and chip of each chart: the test stamps the class exactly as the panel
renders it (`dw-val dw-bad`, `se-chip se-good`, ...), reads the computed
colour, and puts the class back. SVG text is measured on its `fill`.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_SHEET = "*, *::before, *::after { transition: none !important; }"
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_TABS = ["items", "skills", "runes", "spells", "duration", "snowball",
         "flow", "opscore", "bench"]
_AA = 4.5
_AA_LARGE = 3.0

_ROW = _HELPERS + """
  const isSvg = (e) => e instanceof SVGElement;
  const row = (e) => {
    const s = surface(e);
    const cs = getComputedStyle(e);
    const paint = isSvg(e) ? cs.fill : cs.color;
    return {
      cls: String(e.className.baseVal ?? e.className),
      tag: e.tagName, svg: isSvg(e),
      text: e.textContent.trim().slice(0, 40),
      fg: s ? over(rgba(paint), s) : null, bg: s,
      border: rgba(cs.borderTopColor),
      // SVG type is in viewBox user units: the rendered glyph size is the
      // user-unit size times the vertical screen scale.
      size: parseFloat(cs.fontSize)
        * (isSvg(e) ? Math.abs(e.getScreenCTM().d) : 1),
      weight: parseInt(cs.fontWeight, 10),
      inactive: !!e.closest(
        ':disabled, [aria-disabled="true"], .is-disabled'),
    };
  };
  const root = getComputedStyle(document.documentElement);
  const tok = (n) => rgba(root.getPropertyValue(n).trim());
"""

_ALL = """async () => {
  await document.fonts.ready;
""" + _ROW + """
  const host = document.getElementById('view-build-insights');
  return [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
}"""

# Stamp good / bad / dim on the chart's real value and chip, then restore.
_STATES = """async (pre) => {
""" + _ROW + """
  const out = {};
  for (const part of ['val', 'chip']) {
    const e = document.querySelector(
      '#view-build-insights .' + pre + '-' + part);
    if (!e) continue;
    const keep = e.className;
    for (const k of ['good', 'bad', 'dim']) {
      e.className = pre + '-' + part + ' ' + pre + '-' + k;
      out[part + ':' + k] = row(e);
    }
    e.className = keep;
  }
  return {states: out, good: tok('--signal-good'), bad: tok('--signal-bad'),
          dim: tok('--signal-dim')};
}"""

_MARKS = """async (sel) => {
""" + _ROW + """
  return {rows: [...document.querySelectorAll(sel)]
      .filter((e) => e.checkVisibility()).map(row),
    text: tok('--text'), dim: tok('--text-dim')};
}"""


def _measure(mock_server, pw_browser, theme, vp):
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
            mock_server.url + f"/?ui_mock=1&theme={theme}#build-insights",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.querySelector('#bi-table-mount table.bi-table')"
            " !== null", timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        # The tabs and the clear button transition colour (0.15 s): with
        # transitions off every read below is the settled value (RM-1132).
        page.add_style_tag(content=_SHEET)
        # Every tab paints from an async fetch: wait for its own content, not
        # a fixed sleep (a read before it lands measures "loading...").
        land = {
            "items": "#bi-table-mount table.bi-table",
            "skills": "#bi-skill-table-mount table.bi-table",
            "runes": "#bi-rune-table-mount table.bi-table",
            "spells": "#bi-spell-table-mount table.bi-table",
            "bench": "#bi-bench-mount table.cb-table",
            "duration": "#bi-duration-mount .dw-val",
            "snowball": "#bi-snowball-mount .se-val",
            "opscore": "#bi-opscore-mount .op-arc-side",
            "flow": "#bi-flow-mount .pf-ylab",
        }
        for tab in _TABS:
            page.click(f"#bi-tabs .bi-tab[data-bi-tab='{tab}']")
            page.wait_for_selector(land[tab], timeout=10_000)
            got["tabs"][tab] = page.evaluate(_ALL)
            if tab in ("duration", "snowball"):
                got[tab] = page.evaluate(
                    _STATES, "dw" if tab == "duration" else "se")
            if tab == "duration":
                got["clear"] = page.evaluate(
                    _MARKS, "#bi-duration-mount .dw-champ-clear")
                btn = page.locator("#bi-duration-mount .dw-champ-clear")
                btn.hover()
                got["clear_hover"] = page.evaluate(
                    _MARKS, "#bi-duration-mount .dw-champ-clear")
                page.mouse.move(0, 0)
            if tab == "opscore":
                got["side"] = page.evaluate(
                    _MARKS, "#bi-opscore-mount .op-arc-side")
                got["axis"] = page.evaluate(
                    _MARKS, "#bi-opscore-mount .op-ylab,"
                    " #bi-opscore-mount .op-xlab")
            if tab == "flow":
                got["flow_axis"] = page.evaluate(
                    _MARKS, "#bi-flow-mount .pf-ylab, #bi-flow-mount .pf-xlab")
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


def _low(rows):
    out = []
    for row in rows:
        if row["inactive"]:
            continue
        assert row["bg"] is not None, row
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            out.append((row["cls"], row["text"], round(ratio, 2), floor))
    return out


def _same(a, b, tol=3):
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


def _over(top, bot):
    return [top[i] * top[3] + bot[i] * (1 - top[3]) for i in range(3)]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_build_insights_tab_text_line_reaches_its_floor(
        theme, vp, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    low = {}
    for tab in _TABS:
        rows = got["tabs"][tab]
        # Anchor: every tab paints text (an empty sweep would pass).
        assert len(rows) >= 5, (tab, rows)
        bad = _low(rows)
        if bad:
            low[tab] = bad
    # The chart tabs carry the fixed classes; prove they were read.
    seen = {r["cls"] for t in ("duration", "snowball", "opscore", "flow")
            for r in got["tabs"][t]}
    for want in ("dw-champ-clear", "op-arc-side", "op-ylab", "pf-ylab"):
        assert any(want in c for c in seen), (want, sorted(seen))
    assert not low, f"{theme} {vp}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_chart_value_and_chip_states_reach_aa_and_keep_their_hue(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    low = {}
    for tab in ("duration", "snowball"):
        m = got[tab]
        st = m["states"]
        assert set(st) == {f"{p}:{k}" for p in ("val", "chip")
                           for k in ("good", "bad", "dim")}, sorted(st)
        for key, row in st.items():
            ratio = _ratio(row["fg"], row["bg"])
            if ratio < _AA:
                low[f"{tab} {key}"] = round(ratio, 2)
        for part in ("val", "chip"):
            bad = st[f"{part}:bad"]
            r, g, b = bad["fg"][:3]
            # The worse value still reads red, not a washed pink-grey.
            assert r - max(g, b) >= 60, (tab, part, bad["fg"])
            # good / dim keep their bare signal tokens.
            for k in ("good", "dim"):
                row = st[f"{part}:{k}"]
                assert _same(row["fg"], _over(m[k], row["bg"])), (
                    tab, part, k, row["fg"], m[k])
        # The bad chip's frame keeps the bare --signal-bad hue.
        chip = st["chip:bad"]
        assert _same(chip["border"], m["bad"]), (tab, chip["border"], m["bad"])
    assert not low, f"{theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_filter_clear_arc_side_and_axis_labels_are_secondary_at_aa(
        theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    groups = {"clear": got["clear"], "side": got["side"], "axis": got["axis"],
              "flow_axis": got["flow_axis"]}
    assert len(groups["clear"]["rows"]) == 1, groups["clear"]
    assert [r["text"] for r in groups["side"]["rows"]] == ["Wins", "Losses"]
    assert len(groups["axis"]["rows"]) >= 4, groups["axis"]
    assert len(groups["flow_axis"]["rows"]) >= 4, groups["flow_axis"]
    low = {}
    for name, m in groups.items():
        for row in m["rows"]:
            ratio = _ratio(row["fg"], row["bg"])
            if ratio < _AA:
                low[f"{name} {row['text']}"] = round(ratio, 2)
            # Secondary: --text-dim, and under --text on the same surface.
            assert _same(row["fg"], _over(m["dim"], row["bg"])), (
                name, row["text"], row["fg"], m["dim"])
            assert _ratio(row["fg"], row["bg"]) < _ratio(
                _over(m["text"], row["bg"]) + [1], row["bg"]), (name, row)
    hov = got["clear_hover"]["rows"][0]
    assert _ratio(hov["fg"], hov["bg"]) >= _AA, hov
    assert not _same(hov["fg"], got["clear"]["rows"][0]["fg"]), hov
    assert not low, f"{theme}: {low}"
