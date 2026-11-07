"""
tests/snapshot_panels/test_last_match_hero_narrow.py
The Post Game Review hero card (identity cluster, Detailed stats, the
rank-tier comparison) and the Quick Review columns fit a narrow window
(s144 lane uiux, RM-1783; the U-172 FUTURE row "the hero identity row
and its stats disclosure keep a 472 px min-content ... the Quick Review
columns run past the view"). 400% zoom of the 1920x920 baseline is 480
wide; WCAG 1.4.10 reflows at 320.

Measured before the fix (headless Chromium, ?ui_mock=1&mode=<sr|aram|
arena>#last-match, Detailed stats open):
  - .lm-hero-identity was a 7-track grid (72px + six auto tracks) with a
    472 px min-content in SR / ARAM (425 in Arena), so the one-column
    hero track (<= 1200) grew past the hero card from about 600 down and
    #view-last-match scrolled sideways from 560 (SR / ARAM) / 480 (Arena)
    down: identity and the stats disclosure ran to x 545 at 480;
  - the champion name's container (.lm-hero-name, min-width 0) was
    squeezed into a 0 px track at 480 and under, so the name was drawn
    over the KDA block beside it;
  - with a rank tier picked, the 4-column comparison grid ran to x 545
    as well (four 66-72 px columns plus the dashed separator);
  - the three Quick Review columns put the third past the view from 560
    (SR) / 480 (ARAM, Arena) down.

Contract pinned in all three modes at 1920x920, 1200x900, 722x900,
720x900, 640x900, 560x900, 480x800, 400x800, 360x740 and 320x640, with
the rank tier off and with "gold" picked (the 1201-1390 band with a tier
picked is a separate, pre-existing FUTURE row and is not pinned here):
  - no page error; the view does not scroll sideways;
  - every visible part of the hero lies inside the hero's content box;
  - the champion name is drawn (non-zero box), lies inside the hero and
    is drawn over no other identity part;
  - the identity parts and the stat / rank cells keep reading order;
  - every Quick Review column lies inside the view's content box;
  - above 720 nothing moves: the identity is the 7-track grid, Detailed
    stats and the rank comparison are 4-track grids and the Quick Review
    columns sit side by side on one line;
  - at 720 and under the identity wraps (flex) and the Quick Review
    columns stack, full width, in order;
  - at 560 and under the stat and rank grids are 2 tracks with no dashed
    left separator, and the rank selector keeps the 42 px hit floor.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_SIZES = ((1920, 920), (1200, 900), (722, 900), (720, 900), (640, 900),
          (560, 900), (480, 800), (400, 800), (360, 740), (320, 640))
_MODES = ("sr", "aram", "arena")
_TIERS = ("", "gold")
_WRAP_MAX = 720
_TWO_MAX = 560
_CASES = [(w, h, m, t) for (w, h) in _SIZES for m in _MODES for t in _TIERS]
_IDS = [f"{m}-{w}-{t or 'off'}" for (w, h, m, t) in _CASES]

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_PREP = """(tier) => {
  document.getElementById("lm-hero-stats-details").open = true;
  const s = document.getElementById("lm-rank-select");
  s.value = tier;
  s.dispatchEvent(new Event("change"));
}"""

_READ = """() => {
  const v = document.getElementById("view-last-match");
  const box = (el) => {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    return [r.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
            r.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight)];
  };
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height};
  };
  const shown = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0; };
  const label = (el) => (el.id || el.className || el.tagName).toString()
    .slice(0, 40);
  const hero = v.querySelector(".lm-hero");
  const heroParts = [...hero.querySelectorAll("*")].filter(shown)
    .map((el) => Object.assign({k: label(el)}, rect(el)));
  const ident = v.querySelector(".lm-hero-identity");
  const grid = v.querySelector(".lm-hero-stats-grid");
  const rank = v.querySelector(".lm-hero-rank-compare");
  const tracks = (el) => getComputedStyle(el).gridTemplateColumns
    .split(" ").filter(Boolean).length;
  const cells = (el) => [...el.children].filter(shown)
    .map((c) => Object.assign({k: c.textContent.trim().replace(/\\s+/g, " ")
      .slice(0, 20)}, rect(c)));
  const parts = (el) => [...el.children].filter(shown)
    .map((c) => Object.assign({k: label(c)}, rect(c)));
  const qc =v.querySelector(".lm-qr-cols");
  const sel = document.getElementById("lm-rank-select");
  return {
    view: [v.scrollWidth, v.clientWidth], viewBox: box(v),
    heroBox: box(hero), heroParts,
    name: rect(document.getElementById("lm-champion-name")),
    identDisplay: getComputedStyle(ident).display,
    identTracks: tracks(ident), ident: parts(ident),
    gridTracks: tracks(grid), grid: cells(grid),
    gridBorder: getComputedStyle(grid).borderLeftStyle,
    detailsBorder: getComputedStyle(
      document.getElementById("lm-hero-stats-details")).borderLeftStyle,
    rankEmpty: rank.classList.contains("is-empty"),
    rankTracks: tracks(rank), rank: cells(rank),
    rankBorder: getComputedStyle(rank).borderLeftStyle,
    selH: sel.getBoundingClientRect().height,
    qr: [...qc.children].filter(shown).map(rect), qrBox: box(qc),
  };
}"""


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def hero_at(request, mock_server, pw_browser):
    w, h, mode, tier = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const t = document.getElementById('lm-mode-tag');"
            " return t && t.textContent.trim() !== '-'; })()",
            timeout=10_000)
        page.evaluate(_PREP, tier)
        page.evaluate(_SETTLE)
        data = page.evaluate(_READ)
    finally:
        page.close()
        ctx.close()
    return w, f"{mode} {w} tier={tier or 'off'}", tier, data, errors


def _in_order(parts):
    """Each later box is on the same line further right, or lower."""
    bad = []
    for a, b in zip(parts, parts[1:]):
        same_line = abs(a["t"] - b["t"]) < 2 or (
            a["t"] < b["b"] and b["t"] < a["b"])
        if not ((same_line and b["l"] >= a["r"] - 1) or b["t"] >= a["b"] - 1):
            bad.append(f"{a['k']} -> {b['k']}")
    return bad


def test_no_page_errors(hero_at):
    _w, tag, _t, _d, errors = hero_at
    assert errors == [], f"{tag}: {errors}"


def test_rank_state_matches_the_tier(hero_at):
    _w, tag, tier, d, _e = hero_at
    assert d["rankEmpty"] is (tier == ""), f"{tag}: is-empty {d['rankEmpty']}"


def test_view_does_not_scroll_sideways(hero_at):
    _w, tag, _t, d, _e = hero_at
    sw, cw = d["view"]
    assert sw <= cw + 1, f"{tag}: view scrolls sideways {sw} > {cw}"


def test_every_hero_part_inside_the_hero(hero_at):
    _w, tag, _t, d, _e = hero_at
    left, right = d["heroBox"]
    out = [f"{p['k']} {p['l']:.0f}-{p['r']:.0f}" for p in d["heroParts"]
           if p["l"] < left - 1 or p["r"] > right + 1]
    assert not out, f"{tag}: hero box {left:.0f}-{right:.0f}: {out[:6]}"


def test_champion_name_is_drawn(hero_at):
    _w, tag, _t, d, _e = hero_at
    n = d["name"]
    assert n["w"] >= 20 and n["h"] >= 20, (
        f"{tag}: champion name box {n['w']:.0f}x{n['h']:.0f}")
    left, right = d["heroBox"]
    assert left - 1 <= n["l"] and n["r"] <= right + 1, (
        f"{tag}: name {n['l']:.0f}-{n['r']:.0f} outside {left:.0f}-{right:.0f}")
    # The name container's track was squeezed to 0 px at 480 and under,
    # so the name was drawn over the KDA block beside it.
    assert any(p["k"] == "lm-hero-name" for p in d["ident"]), f"{tag}: no name"
    over = [p["k"] for p in d["ident"] if p["k"] != "lm-hero-name"
            and min(n["r"], p["r"]) - max(n["l"], p["l"]) > 1
            and min(n["b"], p["b"]) - max(n["t"], p["t"]) > 1]
    assert not over, f"{tag}: champion name drawn over {over}"


_RANK_NARROW = ["-", "KDA", "Vision", "CS", "Tanked", "Damage", "CS/min",
                "Sustain"]


def test_identity_and_cells_keep_reading_order(hero_at):
    w, tag, _t, d, _e = hero_at
    # portrait, name, KDA, result, grade; the eight stat cells
    assert len(d["ident"]) == 5, f"{tag}: identity {[p['k'] for p in d['ident']]}"
    assert len(d["grid"]) == 8, f"{tag}: {len(d['grid'])} stat cells"
    assert not _in_order(d["ident"]), f"{tag}: identity {_in_order(d['ident'])}"
    assert not _in_order(d["grid"]), f"{tag}: stats {_in_order(d['grid'])}"
    if d["rankEmpty"]:
        return
    if w > _TWO_MAX:
        assert not _in_order(d["rank"]), f"{tag}: rank {_in_order(d['rank'])}"
        return
    # Two per line: the selector, then the KDA + KP% pair (the wide
    # layout's first column), then the six tier averages row-major.
    seen = [c["k"].split(" ")[0] for c in
            sorted(d["rank"], key=lambda c: (round(c["t"]), c["l"]))]
    assert seen == _RANK_NARROW, f"{tag}: rank reads {seen}"


def test_quick_review_columns_inside_the_view(hero_at):
    _w, tag, _t, d, _e = hero_at
    left, right = d["viewBox"]
    assert len(d["qr"]) == 3, f"{tag}: {len(d['qr'])} Quick Review columns"
    out = [f"{q['l']:.0f}-{q['r']:.0f}" for q in d["qr"]
           if q["l"] < left - 1 or q["r"] > right + 1]
    assert not out, f"{tag}: view box {left:.0f}-{right:.0f}: {out}"


def test_layout_above_720_is_unchanged(hero_at):
    w, tag, _t, d, _e = hero_at
    if w <= _WRAP_MAX:
        return  # not this case: narrow layout
    assert d["identDisplay"] == "grid" and d["identTracks"] == 7, (
        f"{tag}: identity {d['identDisplay']} {d['identTracks']} tracks")
    assert d["gridTracks"] == 4, f"{tag}: stats {d['gridTracks']} tracks"
    assert d["detailsBorder"] == "dashed", f"{tag}: {d['detailsBorder']}"
    if not d["rankEmpty"]:
        assert d["rankTracks"] == 4, f"{tag}: rank {d['rankTracks']} tracks"
        assert d["rankBorder"] == "dashed", f"{tag}: {d['rankBorder']}"
    tops = {round(q["t"]) for q in d["qr"]}
    assert len(tops) == 1, f"{tag}: Quick Review columns not on one line"


def test_identity_wraps_and_quick_review_stacks_at_720(hero_at):
    w, tag, _t, d, _e = hero_at
    if w > _WRAP_MAX:
        return  # not this case: wide layout
    assert d["identDisplay"] == "flex", f"{tag}: {d['identDisplay']}"
    qr = d["qr"]
    lefts = {round(q["l"]) for q in qr}
    assert len(lefts) == 1, f"{tag}: Quick Review lefts {sorted(lefts)}"
    for a, b in zip(qr, qr[1:]):
        assert b["t"] >= a["b"] - 1, f"{tag}: Quick Review not stacked"
    left, right = d["qrBox"]
    assert all(q["w"] >= right - left - 1 for q in qr), (
        f"{tag}: a stacked Quick Review column is not full width")


def test_stat_grids_go_two_per_line_at_560(hero_at):
    w, tag, _t, d, _e = hero_at
    if w > _TWO_MAX:
        assert d["gridTracks"] == 4, f"{tag}: stats {d['gridTracks']} tracks"
        return
    assert d["gridTracks"] == 2, f"{tag}: stats {d['gridTracks']} tracks"
    assert d["gridBorder"] == "none" and d["detailsBorder"] == "none", (
        f"{tag}: separator {d['gridBorder']} / {d['detailsBorder']}")
    if not d["rankEmpty"]:
        assert d["rankTracks"] == 2, f"{tag}: rank {d['rankTracks']} tracks"
        assert d["rankBorder"] == "none", f"{tag}: {d['rankBorder']}"
    assert d["selH"] >= 42 - 0.5, f"{tag}: rank select {d['selH']:.1f} tall"


# The historical Post Game Review (#view-historical-pgr) shares the hero
# classes; its stats grid sits straight in the hero (no disclosure) and
# starts with a spacer cell (.lm-hero-stat-blank) that lines it up with
# a rank column the historical view does not have.
_HIST_SIZES = ((1920, 920), (722, 900), (560, 900), (480, 800), (320, 640))

_HIST_READ = """() => {
  const v = document.getElementById("view-historical-pgr");
  const hero = v.querySelector(".lm-hero");
  const cs = getComputedStyle(hero), hr = hero.getBoundingClientRect();
  const left = hr.left + parseFloat(cs.borderLeftWidth)
    + parseFloat(cs.paddingLeft);
  const right = hr.right - parseFloat(cs.borderRightWidth)
    - parseFloat(cs.paddingRight);
  const shown = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0; };
  const out = [...hero.querySelectorAll("*")].filter(shown)
    .filter((el) => { const r = el.getBoundingClientRect();
      return r.left < left - 1 || r.right > right + 1; })
    .map((el) => (el.id || el.className).toString().slice(0, 40));
  const grid = hero.querySelector(".lm-hero-stats-grid");
  const cells = [...grid.children].filter(shown).map((c) => {
    const r = c.getBoundingClientRect();
    return {k: c.textContent.trim().split(/\\s+/)[0], l: r.left,
            r: r.right, t: r.top, b: r.bottom};
  });
  return {height: v.getBoundingClientRect().height,
          view: [v.scrollWidth, v.clientWidth], out, cells,
          tracks: getComputedStyle(grid).gridTemplateColumns.split(" ")
            .filter(Boolean).length,
          blank: v.querySelector(".lm-hero-stat-blank")
            .getBoundingClientRect().width};
}"""


@pytest.fixture(scope="module", params=_HIST_SIZES,
                ids=[f"hist-{w}" for (w, _h) in _HIST_SIZES])
def hist_at(request, mock_server, pw_browser):
    w, h = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr#historical-pgr",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.getElementById('view-historical-pgr')"
            ".getBoundingClientRect().height > 0", timeout=10_000)
        page.evaluate(_SETTLE)
        data = page.evaluate(_HIST_READ)
    finally:
        page.close()
        ctx.close()
    return w, data, errors


def test_historical_hero_fits_and_reflows(hist_at):
    w, d, errors = hist_at
    tag = f"historical {w}"
    assert errors == [], f"{tag}: {errors}"
    sw, cw = d["view"]
    assert sw <= cw + 1, f"{tag}: view scrolls sideways {sw} > {cw}"
    assert not d["out"], f"{tag}: outside the hero: {d['out'][:6]}"
    seen = [c["k"] for c in d["cells"]]
    assert len(seen) >= 7, f"{tag}: stat cells {seen}"
    if w > _TWO_MAX:
        assert d["tracks"] == 4 and d["blank"] > 0, (
            f"{tag}: {d['tracks']} tracks, spacer {d['blank']}")
    else:
        assert d["tracks"] == 2, f"{tag}: {d['tracks']} tracks"
        assert d["blank"] == 0, f"{tag}: spacer cell drawn, a line starts empty"
        assert seen[0] == "Vision", f"{tag}: first cell {seen[:2]}"
        assert not _in_order(d["cells"]), f"{tag}: {_in_order(d['cells'])}"
