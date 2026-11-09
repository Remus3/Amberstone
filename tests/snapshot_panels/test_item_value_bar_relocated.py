"""
tests/snapshot_panels/test_item_value_bar_relocated.py
S144-U-255 (s144 uiux): the R117 F1 team item-value bar (#gold-diff,
map_state.js renderItemValueDiff) renders under the Active Match map on
the dashboard, on the 16 px --fs-xs floor, and its label and number reach
the WCAG 1.4.3 AA text floor (4.5:1) in all six themes, at the 1920x920
baseline and the 923x1280 companion window; it stays hidden in Arena and
TFT, where an ally-vs-rest item sum is not a team lead.

THE DEFECT. MEASURED headless under /?ui_mock=1&mode=sr#active-match by
driving renderItemValueDiff with a lean live roster (the
dashboard/_liveclient.py _lean_roster shape: allPlayers[].team / items,
activePlayer.summonerName) and the real web/data/items_costs.json: the
function lifted the bar's .hidden class and wrote "+4,200", yet the bar
had no layout box in any view. It sat in the #minimap panel inside the
top-level <main>, which header.css hides for every VIEW_ID and overlay.css
hides in the overlay shell (the cause of S144-U-227 / U-245 / U-246 /
U-254). So the lens R117 shipped had never been seen. Its label was also
a hard-coded 13 px --text-faint and its number 15 px, both under the
--fs-xs floor.

THE FIX. index.html moves the node into the Active Match MAP pane, after
#am-map-body (whose innerHTML the map render replaces); overlay.css
already keeps that pane off the HUD, so the in-game surface does not
change. The rules move from grid.css to active_match.css, scoped
#view-active-match, with the label on --fs-xs --text-dim and the number on
--fs-sm. renderItemValueDiff hides the bar when body[data-mode] is arena
or tft.

Checked per theme and viewport: the bar is shown inside the MAP pane with
no horizontal overflow, the label and both number states reach 4.5:1 on
the resolved pane surface at opacity 1, the number is louder than its
label, and the Arena / TFT / no-roster renders hide it.
"""
import re

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
_HIDDEN_CASES = ["arena", "tft", "noroster"]

# A lean live roster (dashboard/_liveclient.py _lean_roster): synthetic
# names, real item ids. Ally on-board value 7,900 (3031 + 3006 + 3074),
# enemy 3,700 (3157 + 1055), so the bar reads +4,200 for ORDER. No style
# read here, so the RM-1132 probe in test_theme_swap_reads_settled.py sees
# the page after this render, at the _MEASURE read.
_DRIVE = """async (me) => {
  const find = (s) => performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes(s));
  const urls = ['/panels/map_state.js', '/lib/state.js', '/lib/items_index.js']
    .map(find);
  if (urls.some((u) => !u)) return {err: 'module not loaded', urls};
  const [ms, st, ix] = await Promise.all(urls.map((u) => import(u)));
  for (let i = 0; i < 200 && !ix.ITEM_COSTS.ready; i++) {
    await new Promise((r) => setTimeout(r, 25));
  }
  if (!ix.ITEM_COSTS.ready) return {err: 'item costs never loaded'};
  const row = (name, team, ids) => ({
    summonerName: name, riotIdGameName: name, championName: 'X',
    rawChampionName: 'X', team, level: 11,
    items: ids.map((id, slot) => ({itemID: id, slot})),
    scores: {kills: 0, deaths: 0, assists: 0},
  });
  const roster = [
    row('You', 'ORDER', [3031, 3006]), row('Ally2', 'ORDER', [3074]),
    row('Ally3', 'ORDER', []), row('Ally4', 'ORDER', []),
    row('Ally5', 'ORDER', []),
    row('Foe1', 'CHAOS', [3157]), row('Foe2', 'CHAOS', [1055]),
    row('Foe3', 'CHAOS', []), row('Foe4', 'CHAOS', []),
    row('Foe5', 'CHAOS', []),
  ];
  window.__ivbRender = (who, mode) => {
    document.body.dataset.mode = mode;
    st.state.latest = {...(st.state.latest || {}),
      liveclient: who ? {allPlayers: roster,
                         activePlayer: {summonerName: who,
                                        riotIdGameName: who}} : null};
    ms.renderItemValueDiff({});
  };
  window.__ivbRender(me, 'sr');
  return {ok: true};
}"""

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const root = getComputedStyle(document.documentElement);
  const tok = (name) => rgba(root.getPropertyValue(name).trim());
  const wrap = document.getElementById('gold-diff');
  const val = document.getElementById('gold-diff-val');
  const fill = document.getElementById('gold-diff-fill');
  if (!wrap || !val || !fill) return {err: 'no #gold-diff'};
  const label = wrap.querySelector('.gold-diff-label');
  const pane = wrap.closest('.am-pane-map');
  const styleOf = (e) => {
    const cs = getComputedStyle(e);
    const s = surface(e);
    const fg = rgba(cs.color);
    return {color: fg, fg: s ? over(fg, s) : null, bg: s,
            size: parseFloat(cs.fontSize), weight: cs.fontWeight,
            opacity: parseFloat(cs.opacity)};
  };
  // The fill's gradient, against a probe painted with bare --bad.
  const probe = document.createElement('div');
  probe.style.backgroundImage =
    'linear-gradient(90deg, var(--bad) 0%, transparent 100%)';
  fill.parentElement.appendChild(probe);
  const want = getComputedStyle(probe).backgroundImage;
  probe.remove();
  const wr = wrap.getBoundingClientRect();
  const pr = pane ? pane.getBoundingClientRect() : null;
  return {theme: document.documentElement.dataset.theme || 'hextech',
          legacy: !!document.querySelector('#minimap #gold-diff'),
          inPane: !!pane,
          xs: parseFloat(root.getPropertyValue('--fs-xs')),
          sm: parseFloat(root.getPropertyValue('--fs-sm')),
          dim: tok('--text-dim'), good: tok('--good'),
          shown: wrap.checkVisibility(), text: val.textContent,
          cls: val.className, label: styleOf(label), value: styleOf(val),
          fillCls: fill.className,
          fillBare: getComputedStyle(fill).backgroundImage === want,
          fillImage: getComputedStyle(fill).backgroundImage,
          rect: [wr.left, wr.top, wr.right, wr.bottom],
          pane: pr ? [pr.left, pr.top, pr.right, pr.bottom] : null,
          paneOverflow: pane ? pane.scrollWidth - pane.clientWidth : null,
          docOverflow: document.documentElement.scrollWidth - innerWidth};
}"""

# Each non-two-team render after a fresh SR render: is the bar gone?
_HIDDEN = """() => {
  const wrap = document.getElementById('gold-diff');
  const out = {};
  for (const [k, who, mode] of [['arena', 'You', 'arena'],
                                ['tft', 'You', 'tft'],
                                ['noroster', null, 'sr']]) {
    window.__ivbRender('You', 'sr');
    const before = wrap.checkVisibility();
    window.__ivbRender(who, mode);
    out[k] = {before, shown: wrap.checkVisibility(),
              cls: wrap.classList.contains('hidden')};
  }
  window.__ivbRender('You', 'sr');
  return out;
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {}
        for me, key in (("You", "ahead"), ("Foe1", "behind")):
            drove = page.evaluate(_DRIVE, me)
            assert "err" not in drove, drove
            got[key] = page.evaluate(_MEASURE)
            assert "err" not in got[key], got[key]
        got["hidden"] = page.evaluate(_HIDDEN)
        got["theme"] = got["ahead"]["theme"]
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_bar_renders_inside_the_map_pane(theme, vp, measured,
                                             mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    a = got["ahead"]
    assert not a["legacy"], "the bar is still in the never-rendered #minimap"
    assert a["inPane"], a
    assert a["shown"], a
    assert re.fullmatch(r"\+4,?200", a["text"]), a["text"]
    assert a["cls"] == "gd-ahead", a
    left, top, right, bottom = a["rect"]
    pl, pt, pr, pb = a["pane"]
    assert pl <= left and right <= pr and pt <= top and bottom <= pb, a
    assert a["paneOverflow"] <= 0 and a["docOverflow"] <= 0, a


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_label_and_number_reach_aa(theme, vp, measured, mock_server,
                                   pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    for name, r in (("label", got["ahead"]["label"]),
                    ("ahead", got["ahead"]["value"]),
                    ("behind", got["behind"]["value"])):
        assert r["bg"] is not None, (name, r)
        assert r["opacity"] == 1, (name, r)
        ratio = _ratio(r["fg"], r["bg"])
        assert ratio >= _AA, f"{theme} {vp} {name}: {ratio:.2f}:1 under {_AA}"


@pytest.mark.parametrize("theme", _THEMES)
def test_type_floor_tokens_and_hierarchy(theme, measured, mock_server,
                                         pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    tok = got["ahead"]
    assert tok["xs"] == 16.0 and tok["sm"] == 18.0, (tok["xs"], tok["sm"])
    lab, ahead = tok["label"], tok["value"]
    behind = got["behind"]
    assert lab["size"] == tok["xs"], (theme, lab)
    assert lab["color"] == tok["dim"], (theme, lab["color"], tok["dim"])
    assert ahead["size"] == tok["sm"], (theme, ahead)
    assert ahead["color"] == tok["good"], (theme, ahead["color"])
    assert re.fullmatch(r"-4,?200", behind["text"]), behind["text"]
    assert behind["cls"] == "gd-behind", behind
    # The RM-1550 red-text lift: still red by hue (red leads green and blue),
    # while the fill behind it keeps bare --bad.
    r, g, b = behind["value"]["fg"][:3]
    assert r - max(g, b) >= 60, (theme, behind["value"]["fg"])
    assert "behind" in behind["fillCls"].split(), behind
    assert behind["fillBare"], (theme, behind["fillImage"])
    # The signed number is the thing to read; its label stays quieter.
    assert int(ahead["weight"]) > int(lab["weight"]), (ahead, lab)
    assert ahead["size"] > lab["size"], (ahead, lab)


@pytest.mark.parametrize("case", _HIDDEN_CASES)
def test_the_bar_hides_outside_a_two_team_roster(case, measured, mock_server,
                                                 pw_browser):
    got = _get(measured, mock_server, pw_browser, _THEMES[0], _VIEWPORTS[0])
    r = got["hidden"][case]
    assert r["before"], r  # anchored: the SR render showed it first
    assert not r["shown"], r
    assert r["cls"], r
