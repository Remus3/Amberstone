"""
tests/snapshot_panels/test_last_match_hero_mid_width.py
The Post Game Review hero card above the 1200 px stack breakpoint, where
it is three sections side by side (identity | Detailed stats | rank-tier
comparison) - s144 lane uiux, RM-1784 (the U-173 FUTURE row "with a
rank tier picked the three-column hero overflows the view from 1201 to
about 1390 px").

Measured before the fix (headless Chromium, ?ui_mock=1&mode=<sr|aram|
arena>#last-match, a tier picked):
  - with Detailed stats open the three sections' min-content (identity
    472 + stats 363 + rank 345 + two 18 px gaps = 1216 px in SR / ARAM,
    1169 in Arena) is wider than the hero from 1201 to 1389 px (SR /
    ARAM; 1279 Arena): the rank comparison ran to x 1289 past a hero
    whose content box ends at 1127 (1201 px) and #view-last-match
    scrolled sideways (1270 > 1163);
  - the "estimate / reference - not measured" caption, which
    last_match.js inserts after the rank grid as a hero child, was
    auto-placed in row 2 column 1 - under the IDENTITY cluster at every
    width above 1200, up to 1300 px from the tier averages it qualifies.

Contract pinned in all three modes at 1201 .. 1920 px, with Detailed
stats open + "gold", closed + "gold", and open + tier off:
  - no page error; the view does not scroll sideways; every visible part
    of the hero lies inside the hero's content box;
  - the caption (tier picked) lies under the rank comparison, right
    edges flush, and over no other hero section;
  - from 1440 up, and in the closed / tier-off states at every width,
    the three sections stay side by side on one row (nothing moves);
  - from 1201 to 1439 with Detailed stats open and a tier picked the
    rank comparison drops under the Detailed stats, right edges flush,
    and keeps its 4-column grid.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_WIDTHS = (1201, 1240, 1280, 1320, 1360, 1389, 1400, 1439, 1440, 1600,
           1920)
_MODES = ("sr", "aram", "arena")
_STATES = (("open", True, "gold"), ("shut", False, "gold"),
           ("off", True, ""))
_DROP_MAX = 1439

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_PREP = """([open, tier]) => {
  document.getElementById("lm-hero-stats-details").open = open;
  const s = document.getElementById("lm-rank-select");
  s.value = tier;
  s.dispatchEvent(new Event("change"));
}"""

_READ = """() => {
  const v = document.getElementById("view-last-match");
  const hero = v.querySelector(".lm-hero");
  const cs = getComputedStyle(hero), hr = hero.getBoundingClientRect();
  const rect = (el) => { const r = el.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height}; };
  const shown = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0; };
  const parts = [...hero.querySelectorAll("*")].filter(shown).map((el) =>
    Object.assign({k: (el.id || el.className || el.tagName).toString()
      .slice(0, 40)}, rect(el)));
  const note = document.getElementById("lm-rank-estimate-note");
  const rank = hero.querySelector(".lm-hero-rank-compare");
  return {
    view: [v.scrollWidth, v.clientWidth],
    heroBox: [hr.left + parseFloat(cs.borderLeftWidth)
                + parseFloat(cs.paddingLeft),
              hr.right - parseFloat(cs.borderRightWidth)
                - parseFloat(cs.paddingRight)],
    heroTracks: cs.gridTemplateColumns.split(" ").filter(Boolean).length,
    parts,
    ident: rect(hero.querySelector(".lm-hero-identity")),
    details: rect(document.getElementById("lm-hero-stats-details")),
    rank: rect(rank),
    rankEmpty: rank.classList.contains("is-empty"),
    rankTracks: getComputedStyle(rank).gridTemplateColumns.split(" ")
      .filter(Boolean).length,
    note: note && shown(note) && !note.hidden ? rect(note) : null,
  };
}"""


@pytest.fixture(scope="module", params=_MODES)
def mode_rows(request, mock_server, pw_browser):
    """One page per mode, resized through every width and state."""
    mode = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    rows = {}
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => { const t = document.getElementById('lm-mode-tag');"
            " return t && t.textContent.trim() !== '-'; })()",
            timeout=10_000)
        for state, opened, tier in _STATES:
            page.evaluate(_PREP, [opened, tier])
            for w in _WIDTHS:
                page.set_viewport_size({"width": w, "height": 900})
                page.evaluate(_SETTLE)
                rows[(state, w)] = page.evaluate(_READ)
    finally:
        page.close()
        ctx.close()
    return mode, rows, errors


def _each(mode_rows):
    mode, rows, _e = mode_rows
    for (state, w), d in rows.items():
        yield f"{mode} {w} {state}", state, w, d


def test_no_page_errors(mode_rows):
    mode, rows, errors = mode_rows
    assert errors == [], f"{mode}: {errors}"
    # Every width x state was measured, so no check below passes on an
    # empty run.
    assert len(rows) == len(_WIDTHS) * len(_STATES), f"{mode}: {len(rows)}"


def test_rank_state_matches_the_tier(mode_rows):
    bad = [tag for tag, state, _w, d in _each(mode_rows)
           if d["rankEmpty"] is not (state == "off")]
    assert not bad, f"is-empty wrong at {bad}"


def test_view_does_not_scroll_sideways(mode_rows):
    bad = [f"{tag}: {d['view'][0]} > {d['view'][1]}"
           for tag, _s, _w, d in _each(mode_rows)
           if d["view"][0] > d["view"][1] + 1]
    assert not bad, f"view scrolls sideways: {bad[:6]}"


def test_every_hero_part_inside_the_hero(mode_rows):
    bad = []
    for tag, _s, _w, d in _each(mode_rows):
        left, right = d["heroBox"]
        out = [f"{p['k']} {p['l']:.0f}-{p['r']:.0f}" for p in d["parts"]
               if p["l"] < left - 1 or p["r"] > right + 1]
        if out:
            bad.append(f"{tag} (hero {left:.0f}-{right:.0f}): {out[:3]}")
    assert not bad, f"past the hero: {bad[:6]}"


def _overlap(a, b):
    return (min(a["r"], b["r"]) - max(a["l"], b["l"]) > 1
            and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 1)


def test_estimate_caption_sits_under_the_rank_grid(mode_rows):
    bad = []
    for tag, state, _w, d in _each(mode_rows):
        n = d["note"]
        if state == "off":
            continue
        if n is None:
            bad.append(f"{tag}: no caption")
            continue
        r = d["rank"]
        if n["t"] < r["b"] - 1:
            bad.append(f"{tag}: caption top {n['t']:.0f} above rank "
                       f"bottom {r['b']:.0f}")
        if abs(n["r"] - r["r"]) > 1:
            bad.append(f"{tag}: caption right {n['r']:.0f} vs rank "
                       f"{r['r']:.0f}")
        if n["l"] < r["l"] - 1:
            bad.append(f"{tag}: caption left {n['l']:.0f} under the "
                       f"section left of rank {r['l']:.0f}")
        for k in ("ident", "details"):
            if _overlap(n, d[k]):
                bad.append(f"{tag}: caption over {k}")
    assert not bad, bad[:6]


def _side_by_side(d):
    i, s, r = d["ident"], d["details"], d["rank"]
    return s["l"] >= i["r"] - 1 and r["l"] >= s["r"] - 1 and (
        r["t"] < s["b"] and s["t"] < r["b"] and i["t"] < r["b"])


def test_three_sections_side_by_side_where_they_fit(mode_rows):
    bad = []
    for tag, state, w, d in _each(mode_rows):
        if state == "open" and w <= _DROP_MAX:
            continue
        if d["heroTracks"] != 3 or not _side_by_side(d):
            bad.append(f"{tag}: {d['heroTracks']} tracks")
    assert not bad, f"three-section row broken: {bad[:6]}"


def test_rank_drops_under_detailed_stats_in_the_mid_band(mode_rows):
    bad = []
    for tag, state, w, d in _each(mode_rows):
        if state != "open" or w > _DROP_MAX:
            continue
        s, r = d["details"], d["rank"]
        if d["heroTracks"] != 2:
            bad.append(f"{tag}: {d['heroTracks']} hero tracks")
        if r["t"] < s["b"] - 1:
            bad.append(f"{tag}: rank top {r['t']:.0f} above stats "
                       f"bottom {s['b']:.0f}")
        if abs(r["r"] - s["r"]) > 1:
            bad.append(f"{tag}: rank right {r['r']:.0f} vs stats "
                       f"{s['r']:.0f}")
        if _overlap(r, d["ident"]):
            bad.append(f"{tag}: rank over identity")
        if d["rankTracks"] != 4:
            bad.append(f"{tag}: rank {d['rankTracks']} tracks")
    assert not bad, bad[:6]
