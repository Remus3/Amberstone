"""
tests/snapshot_panels/test_ui_mock_active_match_complete.py
The Active Match BUILD pane at a finished build (session 144, lane uiux,
S144-U-215; queue defect B#3, docs/qa/UI_UX_QUEUE_2026-07-21.md).

web/data/ui_mock/active_match_complete.json is an SR game at 31:20 with all
six item slots filled, coach.daemon_slayer_picks [] and coach.item_build "".
Measured on the headless render before this slice, dashboard and overlay:
#am-build-body still held the index.html scaffold line "DS engine ranks +
owned items list will render here mid-game." - mid-game. Root cause:
_renderAmBuildBody's retain-last-good guard (_shouldRetainBuild, the
2026-06-29 flicker fix) counted ANY pane content as a good paint, so with
no picks and no Meta / Ultimate rows it kept the static scaffold forever.
The same path runs live whenever the DS rerank, /api/build-order and the
ultimate order all come back empty (a finished build, or DS :8860 down).

Contract pinned here:
  - the scaffold line never survives a live render; the named build module
    (Daemon Slayer / Meta Build / Ultimate Build rows plus the SHAPER
    counters, whose renderShaperStrip clears its own row label) paints
    instead;
  - an empty Daemon Slayer row beside a full inventory says so
    ("All six item slots full") in the existing .bm-strip.bm-empty style,
    instead of a bare label over a blank strip;
  - the retain guard still keeps a REAL paint over a transient empty tick
    (the flicker fix it exists for);
  - positive control: the SR fixture (picks, three items) paints icons in
    the Daemon Slayer row and no full-inventory line.

Drive path: /?ui_mock=1&mode=<m>[&overlay=1]#active-match with an empty
/api/state; the landed render stamps "phase InProgress" into #am-sub.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_SCAFFOLD = "will render here mid-game"
_FULL = "All six item slots full"
_ROW_LABELS = ["Daemon Slayer", "Meta Build", "Ultimate Build"]
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

_SURFACES = {
    "dashboard": "",
    "overlay": "&overlay=1",
}

_BUILD_JS = """() => {
  const b = document.getElementById('am-build-body');
  const live = b.querySelector('.bm-live .bm-strip');
  return {
    text: b.textContent,
    labels: Array.from(b.querySelectorAll('.bm-module > .bm-row > .bm-row-label'))
      .map(e => e.textContent),
    shaper: !!b.querySelector('.bm-module > .bm-shaper .bm-shaper-strip'),
    liveEmpty: live ? live.classList.contains('bm-empty') : null,
    liveText: live ? live.textContent : null,
    liveIcons: live ? live.children.length : null,
    // The line fits its strip and the strip its pane (the overlay's w-build
    // strip is nowrap inside a 412 px widget).
    liveFits: !!live && live.scrollWidth <= live.clientWidth
      && live.getBoundingClientRect().right
        <= b.getBoundingClientRect().right + 0.5,
    liveVisible: !!live && live.getClientRects().length > 0,
  };
}"""


def _open(pw_browser, mock_server, mode: str, extra: str = ""):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}{extra}#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    page.wait_for_function(
        "!!document.querySelector('#am-build-body .bm-module')",
        timeout=10_000,
    )
    page.evaluate("() => document.fonts.ready.then(() => true)")
    return ctx, page, errors


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_complete_build_paints_the_module_not_the_scaffold(
        surface, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "complete",
                              _SURFACES[surface])
    try:
        assert page.evaluate("document.getElementById('am-sub').textContent") \
            == "SR - Jinx - 31:20 - phase InProgress"
        r = page.evaluate(_BUILD_JS)
        assert _SCAFFOLD not in r["text"], r["text"][:200]
        assert r["labels"] == _ROW_LABELS, r["labels"]
        assert r["shaper"], r
        assert r["liveEmpty"] is True, r
        assert r["liveText"] == _FULL, r
        assert r["liveVisible"] and r["liveFits"], r
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{surface}]: {errors[:3]}"


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_picks_fixture_keeps_icons_and_no_full_line(
        surface, mock_server, pw_browser):
    """Positive control: picks present, three items owned."""
    ctx, page, errors = _open(pw_browser, mock_server, "sr",
                              _SURFACES[surface])
    try:
        r = page.evaluate(_BUILD_JS)
        assert _SCAFFOLD not in r["text"]
        assert r["labels"] == _ROW_LABELS, r["labels"]
        assert r["shaper"], r
        assert r["liveEmpty"] is False, r
        assert r["liveIcons"] >= 1, r
        assert _FULL not in r["text"]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{surface}]: {errors[:3]}"


_STYLE_JS = """() => {
  const s = document.querySelector('#am-build-body .bm-live .bm-strip.bm-empty');
  const lab = document.querySelector('#am-build-body .bm-live > .bm-row-label');
  // Resolve every colour through a canvas pixel: themes.css declares
  // surfaces as oklch(), whose computed string is not rgb (lane doc trap 3).
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1);
    cx.fillStyle = '#000';
    cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const lum = (c) => {
    const [r, g, b] = rgba(c).slice(0, 3).map(v => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  let bgEl = s, bg = 'rgba(0, 0, 0, 0)';
  while (bgEl) {
    const c = getComputedStyle(bgEl).backgroundColor;
    if (rgba(c)[3] === 1) { bg = c; break; }
    bgEl = bgEl.parentElement;
  }
  const fg = getComputedStyle(s).color;
  const L1 = lum(fg), L2 = lum(bg);
  const cs = getComputedStyle(s);
  const r = s.getBoundingClientRect();
  const body = document.getElementById('am-build-body').getBoundingClientRect();
  return {
    fontPx: parseFloat(cs.fontSize),
    labelPx: parseFloat(getComputedStyle(lab).fontSize),
    contrast: (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05),
    bgFound: !!bgEl,
    bgId: bgEl ? (bgEl.id || bgEl.className) : '',
    fg: rgba(fg),
    bg: rgba(bg),
    stripH: r.height,
    oneLine: s.scrollWidth <= s.clientWidth,
    inside: r.left >= body.left - 0.5 && r.right <= body.right + 0.5,
    docFits: document.documentElement.scrollWidth
      <= document.documentElement.clientWidth,
  };
}"""


def _measure(mock_server, pw_browser, theme):
    """The full-inventory line on the dashboard, booted on `theme` (stamped
    at BOOT via ?theme=, never swapped in-page; RM-1132 audit row in
    test_theme_swap_reads_settled.py)."""
    ctx, page, errors = _open(pw_browser, mock_server, "complete",
                              f"&theme={theme}")
    try:
        booted = page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'")
        r = page.evaluate(_STYLE_JS)
    finally:
        page.close()
        ctx.close()
    return {**r, "booted": booted, "errors": errors}


@pytest.mark.parametrize("theme", _THEMES)
def test_full_line_typography_contrast_and_fit(theme, mock_server, pw_browser):
    """5-phase audit pins on the dashboard at the 1920x920 baseline, in every
    theme: the line is on the --fs-xs floor, AA against its resolved surface
    (the PAIR: --text-dim on the pane background it actually sits on;
    --text-faint measured 4.31:1 there), one line, inside the pane, holding
    the reserved strip height (46 px floor of .bm-row .bm-strip:empty), and
    no horizontal overflow."""
    r = _measure(mock_server, pw_browser, theme)
    assert r["booted"] == theme, f"booted on the wrong theme, not {theme}"
    assert r["fontPx"] >= 16, r
    assert r["fontPx"] <= r["labelPx"], r
    assert r["bgFound"], r
    assert r["contrast"] >= 4.5, (theme, r)
    assert r["oneLine"] and r["inside"] and r["docFits"], r
    assert r["stripH"] >= 46, r
    assert not r["errors"], f"JS errors [{theme}]: {r['errors'][:3]}"


_RETAIN_JS = """async () => {
  const m = await import('/js/panels/active_match.js');
  const el = document.createElement('div');
  el.innerHTML = '<div class="am-empty">scaffold</div>';
  document.body.appendChild(el);
  const ctx = { mode: 'sr' };
  const owned = ['3006', '3087', '3085'];
  const picks = [{ name: "Rabadon's Deathcap", item_id: 3089, delta_dps: 100 }];
  // 1. scaffold + champion, nothing to rank -> the module replaces it.
  m._renderAmBuildBody(el, { champion: 'Jinx', level: 11 }, ctx, null, owned);
  const first = el.textContent;
  // 2. a real paint with picks, then a transient empty tick -> kept.
  m._renderAmBuildBody(el, { champion: 'Jinx', level: 11,
    daemon_slayer_picks: picks }, ctx, null, owned);
  const painted = el.innerHTML;
  m._renderAmBuildBody(el, {}, ctx, null, owned);
  const kept = el.innerHTML === painted;
  // 3. six ids but no liveclient (the coach items_display fallback, which can
  // carry the trinket) -> no full-inventory line; the server's own six-id
  // owned_item_ids -> the line. S144-U-216: a liveclient block whose server
  // list is empty and whose roster has no row for the active player (the
  // server could not match them) must not borrow the six name-resolved ids
  // the caller passes - the count comes from the block itself.
  const six = ['3006', '6676', '3031', '3036', '3085', '3340'];
  // Each on a fresh pane: on a painted one the retain guard keeps the paint.
  const paneFor = (lc) => {
    const p = document.createElement('div');
    document.body.appendChild(p);
    m._renderAmBuildBody(p, { champion: 'Jinx', level: 18 }, ctx, lc, six);
    const t = p.textContent;
    p.remove();
    return t;
  };
  const noLc = paneFor(null);
  const withLc = paneFor({ allPlayers: [], owned_item_ids: six.slice(0, 6) });
  const unmatched = paneFor({
    activePlayer: { summonerName: 'Renamed', riotIdGameName: 'Renamed' },
    allPlayers: [{ summonerName: 'Other', riotIdGameName: 'Other',
      items: six.map((id, slot) => ({ itemID: +id, slot })) }],
    owned_item_ids: [],
  });
  // The lean roster's own row: five slotted items plus the slot-6 trinket.
  const fivePlusTrinket = paneFor({
    activePlayer: { summonerName: 'Me', riotIdGameName: 'Me' },
    allPlayers: [{ summonerName: 'Me', riotIdGameName: 'Me',
      items: ['3006', '6676', '3031', '3036', '3085'].map(
        (id, slot) => ({ itemID: +id, slot })).concat([{ itemID: 3340, slot: 6 }]) }],
    owned_item_ids: [],
  });
  el.remove();
  return { first, kept, hadIcon: painted.indexOf('3089') >= 0, noLc, withLc,
    unmatched, fivePlusTrinket };
}"""


def test_retain_guard_keeps_a_real_paint_but_never_the_scaffold(
        mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "sr")
    try:
        r = page.evaluate(_RETAIN_JS)
        assert "scaffold" not in r["first"], r
        assert "Daemon Slayer" in r["first"], r
        assert r["hadIcon"], r
        assert r["kept"], r
        assert _FULL not in r["noLc"], r
        assert _FULL in r["withLc"], r
        assert _FULL not in r["unmatched"], r
        assert _FULL not in r["fivePlusTrinket"], r
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
