"""
tests/snapshot_panels/test_ds_matchup_grid_fits.py
The Active Match DS matchup danger grid keeps every row whole as the BUILD
pane narrows (s144 lane uiux, RM-1768).

The grid row (web/js/panels/ds_matchup.js _gridHtml, styled by
web/css/panels/ds_matchup.css .dsm-grid-cell) was a fixed
`3.5em minmax(0, 1fr) 6.5em 3.5em` grid: 216 px of fixed tracks plus three
8 px gaps, 16 px of padding and a 3 px rule, so 259 px before the champion
column gets a single pixel. Measured on the sr / aram / arena ui_mock
fixtures, the BUILD pane is 258 px wide at 640x900 and 183 px at 480x800, and
the pane is overflow: hidden, so the swing column was cut 5 px at 640 and the
verdict and swing 16 to 80 px at 480, with the champion name squeezed to a
zero-width column. The 1920x920 baseline was fine.

Contract pinned here:
  - the 1920x920 baseline is unchanged: one line per row, four tracks
    (56 / 1fr / 104 / 56 px) (control);
  - under a 360 px list (the 768 window) a row is two lines of three
    tracks, and at every size every row sits inside the BUILD pane with no
    page overflow (since RM-1772 the panes stack full width at 720 px and
    under, so the 640 / 480 windows give a 544 / 384 px list, one line);
  - at every size, every cell of every row sits inside its row, and the
    role, the verdict ("BACK OFF" is the widest) and the swing are whole;
  - the champion name (at most 10 characters, _shortName) is whole and on
    one line, never broken mid-word;
  - a row is the same height pending ("-" sentinels) and landed, at every
    size (no reflow on data arrival).

Drive path: /?ui_mock=1&mode=sr#active-match, then the real renderer
(renderDsMatchup) against its real mount #csv-sugg-ds-matchup with
synthetic rows (hand-written champion slugs, no Riot ids), the pattern
test_ds_matchup_text_contrast.py uses.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MEASURE = """async (forcePageRender) => {
  await document.fonts.ready;
  const m = await import('/js/panels/ds_matchup.js');
  const host = document.getElementById('csv-sugg-ds-matchup');
  // RM-2032: detach the page's two render sources from this host before the
  // measure: the fetch-land scheduler, and the id both page paths find it by
  // (no stylesheet selects it by id, so the layout is unchanged).
  m.setDsMatchupScheduler(null);
  host.removeAttribute('id');
  const landed = (b, v, s) => ({ok: true, champ_a: 'Jinx', champ_b: b,
    verdict: v, swing_pct: s, pct_a_removed: 0.3, pct_b_removed: 0.55,
    notes: [], a_can_full_combo: false});
  const row = (champ, role, lane, p) => ({champ, champA: 'Jinx', role,
    isLane: lane, payload: p});
  const grid = [
    row('Kaisa', 'BOTTOM', true, landed('Kaisa', 'all_in', 100)),
    row('Mordekaiser', 'TOP', false, landed('Mordekaiser', 'back_off', 20)),
    row('TwistedFate', 'MIDDLE', false, landed('TwistedFate', 'even', 50)),
    row('LeeSin', 'JUNGLE', false, landed('LeeSin', 'trade', 55)),
    row('Thresh', 'UTILITY', false, landed('Thresh', 'back_off', 0)),
  ];
  const pending = grid.map((c) => row(c.champ, c.role, c.isLane, null));
  const frame = () => new Promise(
    (r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
  const read = () => [...host.querySelectorAll('.dsm-grid-cell')].map((li) => {
    const b = li.getBoundingClientRect();
    const cell = (cls) => {
      const c = li.querySelector('.' + cls);
      const r = c.getBoundingClientRect();
      return {text: c.textContent, left: r.left, right: r.right, top: r.top,
              h: r.height, scroll: c.scrollWidth, client: c.clientWidth,
              lineH: parseFloat(getComputedStyle(c).lineHeight)};
    };
    return {left: b.left, right: b.right, h: b.height,
            cols: getComputedStyle(li).gridTemplateColumns,
            role: cell('dsm-grid-role'), champ: cell('dsm-grid-champ'),
            verdict: cell('dsm-grid-verdict'), swing: cell('dsm-grid-swing')};
  });
  m._resetDsMatchup();
  m.renderDsMatchup(host, null, pending);
  await frame();
  const p = read();
  m._resetDsMatchup();
  m.renderDsMatchup(host, landed('Kaisa', 'all_in', 100), grid);
  if (forcePageRender) {
    // RM-2032 control: the page's own render path landing between the
    // render and the read (as a state envelope or a fetch land does).
    m.renderDsMatchupForChampSelect({my_champion: 222, their_team: [
      {championId: 266, assignedPosition: 'top'}]}, 'csv-sugg-ds-matchup');
  }
  await frame();
  const l = read();
  const list = host.querySelector('.dsm-grid-list');
  const pane = host.closest('.am-pane');
  const pr = pane.getBoundingClientRect();
  return {pending: p, landed: l, listW: list.clientWidth,
          paneW: pane.clientWidth, paneLeft: pr.left, paneRight: pr.right,
          docOverflow: document.documentElement.scrollWidth
                       > document.documentElement.clientWidth};
}"""

_SIZES = [(1920, 920), (1440, 900), (1199, 920), (1024, 768), (923, 1280),
          (768, 1024), (640, 900), (480, 800)]

_CHAMPS = ["Kaisa", "Mordekaise", "TwistedFat", "LeeSin", "Thresh"]
_VERDICTS = ["ALL IN", "BACK OFF", "EVEN", "TRADE", "BACK OFF"]

_CACHE: dict = {}


def _measure(pw_browser, mock_server, w: int, h: int,
             force_page_render: bool = False) -> dict:
    key = (w, h, force_page_render)
    if key in _CACHE:
        return _CACHE[key]
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=sr#active-match",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_function(
            "(() => { const g = document.querySelector("
            "'#csv-sugg-ds-matchup .dsm-grid');"
            " return !!g && g.checkVisibility(); })()",
            timeout=10_000,
        )
        m = page.evaluate(_MEASURE, force_page_render)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors at {w}x{h}: {errors[:3]}"
    assert [r["champ"]["text"] for r in m["landed"]] == _CHAMPS, m["landed"]
    assert [r["verdict"]["text"] for r in m["landed"]] == _VERDICTS, m
    assert [r["verdict"]["text"] for r in m["pending"]] == ["-"] * 5, m
    _CACHE[key] = m
    return m


def test_a_page_render_between_render_and_read_cannot_repaint_the_measure(
        mock_server, pw_browser):
    """RM-2032. The page renders into the same host on its own (each state
    envelope through renderDsMatchupForChampSelect, a fetch land through the
    scheduler), so a page render landing between renderDsMatchup and read()
    repainted the synthetic grid (seen in test_layout_follows_the_list_width
    [1440-900] at s151 and test_baseline_is_one_line_four_tracks under -n 6
    at s152). Force exactly that render; the measure must still read its own
    five rows (_measure asserts the champions and verdicts)."""
    _measure(pw_browser, mock_server, 1440, 900, force_page_render=True)


def test_baseline_is_one_line_four_tracks(mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, 1920, 920)
    for r in m["landed"]:
        cols = [float(c.rstrip("px")) for c in r["cols"].split()]
        assert len(cols) == 4, r["cols"]
        assert abs(cols[0] - 56) < 0.5 and abs(cols[2] - 104) < 0.5, r["cols"]
        assert abs(cols[3] - 56) < 0.5, r["cols"]
        tops = {round(r[k]["top"]) for k in ("role", "champ", "verdict",
                                             "swing")}
        assert max(tops) - min(tops) <= 4, r


@pytest.mark.parametrize("w,h", _SIZES)
def test_layout_follows_the_list_width(w, h, mock_server, pw_browser):
    """One line of four tracks from a 360 px list up; two lines of three
    tracks under it (the 768 window), and every row stays inside the BUILD
    pane, whose overflow: hidden is what cut the cells. RM-1772 (landed after
    this test) stacks the Active Match panes in one full-width column at
    720 px and under, so only a window above 720 and at or under 768 still
    gives a list under 360 px."""
    m = _measure(pw_browser, mock_server, w, h)
    narrow = m["listW"] < 360
    assert narrow == (720 < w <= 768), (w, m["listW"])
    assert not m["docOverflow"], w
    for r in m["pending"] + m["landed"]:
        assert len(r["cols"].split()) == (3 if narrow else 4), (w, r["cols"])
        assert r["left"] >= m["paneLeft"] - 0.5, (w, r["left"], m["paneLeft"])
        assert r["right"] <= m["paneRight"] + 0.5, (w, r["right"],
                                                    m["paneRight"])


@pytest.mark.parametrize("state", ["pending", "landed"])
@pytest.mark.parametrize("w,h", _SIZES)
def test_every_cell_stays_inside_its_row(w, h, state, mock_server,
                                         pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    for r in m[state]:
        for k in ("role", "champ", "verdict", "swing"):
            c = r[k]
            assert c["left"] >= r["left"] - 0.5, (w, k, c, r["left"])
            assert c["right"] <= r["right"] + 0.5, (w, k, c, r["right"])


@pytest.mark.parametrize("state", ["pending", "landed"])
@pytest.mark.parametrize("w,h", _SIZES)
def test_role_verdict_and_swing_are_whole(w, h, state, mock_server,
                                          pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    for r in m[state]:
        for k in ("role", "verdict", "swing"):
            c = r[k]
            assert c["scroll"] <= c["client"] + 0.5, (w, k, c)
            assert c["h"] <= c["lineH"] * 1.5, (w, k, c)


@pytest.mark.parametrize("w,h", _SIZES)
def test_champion_name_is_whole_on_one_line(w, h, mock_server, pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    for state in ("pending", "landed"):
        for r in m[state]:
            c = r["champ"]
            assert c["client"] > 0, (w, state, c)
            assert c["scroll"] <= c["client"] + 0.5, (w, state, c)
            assert c["h"] <= c["lineH"] * 1.5, (w, state, c)


@pytest.mark.parametrize("w,h", _SIZES)
def test_row_height_does_not_move_when_data_lands(w, h, mock_server,
                                                  pw_browser):
    m = _measure(pw_browser, mock_server, w, h)
    for p, ln in zip(m["pending"], m["landed"]):
        assert abs(p["h"] - ln["h"]) < 0.5, (w, p["h"], ln["h"])
