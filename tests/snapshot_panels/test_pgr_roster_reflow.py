"""
tests/snapshot_panels/test_pgr_roster_reflow.py
The Post Game Review team rosters (the live view's Build tab,
#lm-tc-table, and the archive view's #hpgr-tc-table) fit every window
width (s144 lane uiux, S144-U-190; the U-164 FUTURE row "the archive
Post Game Review body at 320 (417 in 282)").

Measured before the fix (headless Chromium, ui_mock last_match_<mode>
fixtures, the live view on its Build tab, the archive view opened from
a History row):
  - every roster row is an 8-track grid (9 with the augment strip) of
    fixed tracks plus a 200 px item strip, 778 px wide (788 in Arena),
    so each ALLY / ENEMY group held 800 px (810) whatever room it had;
  - from about 880 px down the stacked groups ran past the view: the
    view scrolled sideways 853 in 602 at 640 and 853 in 282 at 320 (863
    in Arena), in SR, ARAM, Arena and Brawl, live and archive alike;
  - from 1201 to about 1720 the side-by-side halves are 520 to 780 px,
    so the ENEMY group ran past the view (1667 in 1163 at 1201, 1667 in
    1662 at 1700);
  - with 4 augments (Arena) one-line, the augment-mode row needed 874 px
    and ran 15 px past each 859 px half at 1920;
  - the LANE MATCHUP card under the live rosters ran past the view from
    about 500 px down (462 in 442 at 480, 382 in 282 at 320): both
    champion sides on one line, and 296 px fixed per metric row.

Contract pinned here, live sr / aram / arena / brawl and archive sr /
arena, at 1920x920, 1760x900, 1700x900, 1440x900, 1201x900, 1000x900,
800x900, 640x900, 480x800, 360x740 and 320x640:
  - no page error; neither the document nor the view scrolls sideways;
  - every visible part of the LANE MATCHUP card lies inside the card;
  - every visible part of a roster lies inside the roster table, and
    every cell lies inside its row's content box;
  - the cells of a row never overlap and keep reading order (a later
    cell sits right of the one before on its line, or on a later line);
  - the player name is drawn at least 40 px wide;
  - ALLY and ENEMY sit side by side only while two whole rows fit (the
    table holds 2 x 800 px plus its gap), and stack otherwise;
  - a row that has its full width (778 px, 808 in augment mode: the
    augment strip wraps inside its track) keeps the one-line grid (8
    tracks, 9 with augments), so 1920 does not move, live Arena with its
    augment icons drawn included; a narrower row wraps its
    cells, and the level, KDA and CS cells keep one left edge down the
    whole roster, ally and enemy (measured from the row's left edge), so
    the columns still read as columns.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
_MOCK = ROOT / "web" / "data" / "ui_mock"

_SIZES = ((1920, 920), (1760, 900), (1700, 900), (1440, 900), (1201, 900),
          (1000, 900), (800, 900), (640, 900), (480, 800), (360, 740),
          (320, 640))
_CASES = [("live", m) for m in ("sr", "aram", "arena", "brawl")] + [
    ("archive", m) for m in ("sr", "arena")]
_GROUP_MIN = 800
_ROW_FULL = 778
_AUG_ROW_FULL = 808
# A 1x1 PNG, so a stubbed augment icon loads offline and keeps its box.
_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
        "FcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

_SETTLE = (
    "document.fonts.ready.then(() => new Promise((ok) =>"
    " requestAnimationFrame(() => requestAnimationFrame(ok))))"
)

_READ = """([vid, tid]) => {
  const v = document.getElementById(vid);
  const t = document.getElementById(tid);
  const rect = (el) => { const r = el.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
            h: r.height}; };
  const inner = (el) => { const cs = getComputedStyle(el),
    r = el.getBoundingClientRect();
    return [r.left + parseFloat(cs.borderLeftWidth)
              + parseFloat(cs.paddingLeft),
            r.right - parseFloat(cs.borderRightWidth)
              - parseFloat(cs.paddingRight)]; };
  // A portrait whose icon fails to load is visibility: hidden but keeps
  // its box, so a part counts while it has a box.
  const shown = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0; };
  const label = (el) => (el.id || String(el.className) || el.tagName)
    .slice(0, 40);
  const tb = inner(t);
  const card = v.querySelector('#pgr-lane-compare-mount .plc-card');
  let plc = null;
  if (card && shown(card)) {
    const cb = inner(card);
    plc = [...card.querySelectorAll('*')].filter(shown)
      .filter((el) => { const r = el.getBoundingClientRect();
        return r.left < cb[0] - 1 || r.right > cb[1] + 1; })
      .map((el) => label(el));
  }
  const out = [...t.querySelectorAll('*')].filter(shown)
    .filter((el) => { const r = el.getBoundingClientRect();
      return r.left < tb[0] - 1 || r.right > tb[1] + 1; })
    .map((el) => [label(el), Math.round(el.getBoundingClientRect().left),
                  Math.round(el.getBoundingClientRect().right), tb]);
  const rows = [...t.querySelectorAll('.lm-tc-row')].map((row) => ({
    side: row.closest('.lm-tc-group').dataset.side,
    box: inner(row), rect: rect(row),
    display: getComputedStyle(row).display,
    tracks: getComputedStyle(row).gridTemplateColumns.split(' ')
      .filter(Boolean).length,
    cells: [...row.children].filter(shown).map((c) =>
      Object.assign({k: String(c.className).split(' ')[0]}, rect(c))),
  }));
  return {
    doc: [document.documentElement.scrollWidth, innerWidth],
    view: [v.scrollWidth, v.clientWidth],
    table: rect(t), hidden: t.hidden,
    cols: getComputedStyle(t).gridTemplateColumns.split(' ')
      .filter(Boolean).length,
    gap: parseFloat(getComputedStyle(t).columnGap) || 0,
    aug: t.dataset.aug === '1',
    groups: [...t.querySelectorAll('.lm-tc-group')].map(rect),
    augs: [...t.querySelectorAll('.lm-tc-aug')].filter(shown).length,
    out, rows, plc,
  };
}"""


def _augment_dictionary(mode):
    raw = json.loads((_MOCK / f"last_match_{mode}.json").read_text(
        encoding="utf-8"))
    match = raw.get("match", raw)
    roster = (match.get("enriched") or {}).get("roster") or []
    ids = {a for r in roster for a in (r.get("augments") or []) if a}
    return {"augments": {str(a): {"name": f"Augment {a}", "rarity": "gold",
                                  "icon_url": _PNG} for a in ids}}


def _open_live(page, url, mode):
    body = json.dumps(_augment_dictionary(mode))
    page.route("**/api/dictionary/augments*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    page.goto(url + f"/?ui_mock=1&mode={mode}#last-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(() => { const t = document.getElementById('lm-mode-tag');"
        " return t && t.textContent.trim() !== '-'; })()", timeout=10_000)
    page.locator(".lm-tab[data-tab=build]").click()
    page.wait_for_function(
        "document.querySelectorAll('#lm-tc-table .lm-tc-row').length >= 4",
        timeout=10_000)
    return "view-last-match", "lm-tc-table"


def _open_archive(page, url, mode):
    body = (_MOCK / f"last_match_{mode}.json").read_text(encoding="utf-8")
    page.route("**/api/last-match*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=body))
    page.goto(url + "/?ui_mock=1&mode=sr#history",
              wait_until="domcontentloaded", timeout=15_000)
    page.locator("#history-session-list .history-session-row").first.click()
    page.locator("#history-match-list .history-match-row").first.click()
    page.wait_for_function(
        "document.querySelectorAll('#hpgr-tc-table .lm-tc-row').length >= 4",
        timeout=10_000)
    return "view-historical-pgr", "hpgr-tc-table"


@pytest.fixture(scope="module", params=_CASES,
                ids=[f"{v}-{m}" for (v, m) in _CASES])
def roster(request, mock_server, pw_browser):
    view, mode = request.param
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    out = {}
    try:
        opener = _open_live if view == "live" else _open_archive
        ids = opener(page, mock_server.url, mode)
        for w, h in _SIZES:
            page.set_viewport_size({"width": w, "height": h})
            page.evaluate(_SETTLE)
            out[w] = page.evaluate(_READ, list(ids))
    finally:
        page.close()
        ctx.close()
    return f"{view}-{mode}", out, errors


def _overlap(a, b):
    return (min(a["r"], b["r"]) - max(a["l"], b["l"]) > 1
            and min(a["b"], b["b"]) - max(a["t"], b["t"]) > 1)


def _check(tag, d):
    assert not d["hidden"], f"{tag}: roster table hidden"
    assert d["doc"][0] <= d["doc"][1], f"{tag}: document scrolls {d['doc']}"
    sw, cw = d["view"]
    assert sw <= cw + 1, f"{tag}: view scrolls sideways {sw} > {cw}"
    assert not d["out"], f"{tag}: past the roster table {d['out'][:4]}"
    assert not d["plc"], f"{tag}: past the lane matchup card {d['plc'][:4]}"
    two_fit = d["table"]["w"] >= 2 * _GROUP_MIN + d["gap"] - 1
    assert d["cols"] == (2 if two_fit else 1), (
        f"{tag}: {d['cols']} roster columns in a {d['table']['w']:.0f} px"
        " table")
    g = d["groups"]
    if d["cols"] == 1:
        assert g[0]["b"] <= g[1]["t"] + 1, f"{tag}: ENEMY not under ALLY"
    else:
        assert abs(g[0]["t"] - g[1]["t"]) <= 1, f"{tag}: halves not level"
    assert len(d["rows"]) >= 4, f"{tag}: {len(d['rows'])} rows"
    lefts = {"lm-tc-lvl": set(), "lm-tc-kda": set(), "lm-tc-cs": set()}
    for i, row in enumerate(d["rows"]):
        rt = f"{tag} {row['side']} row {i}"
        lo, hi = row["box"]
        cells = row["cells"]
        assert len(cells) >= 8, f"{rt}: {len(cells)} cells"
        for c in cells:
            assert c["l"] >= lo - 1 and c["r"] <= hi + 1, (
                f"{rt}: {c['k']} {c['l']:.0f}-{c['r']:.0f} outside"
                f" {lo:.0f}-{hi:.0f}")
            if c["k"] in lefts:
                lefts[c["k"]].add(round(c["l"] - row["rect"]["l"]))
        for a, b in zip(cells, cells[1:]):
            same_line = abs((a["t"] + a["b"]) / 2 - (b["t"] + b["b"]) / 2) < 4
            assert (same_line and b["l"] >= a["r"] - 1) or (
                b["t"] >= a["b"] - 1), (
                f"{rt}: {b['k']} out of reading order after {a['k']}")
        for x, a in enumerate(cells):
            for b in cells[x + 1:]:
                assert not _overlap(a, b), f"{rt}: {a['k']} over {b['k']}"
        name = next(c for c in cells if c["k"] == "lm-tc-name")
        assert name["w"] >= 40, f"{rt}: name {name['w']:.0f} px wide"
        if row["display"] == "grid":
            assert row["tracks"] == (9 if d["aug"] else 8), (
                f"{rt}: {row['tracks']} tracks")
            mids = {round((c["t"] + c["b"]) / 2) for c in cells}
            assert max(mids) - min(mids) <= 2, f"{rt}: grid row not on a line"
        else:
            full = _AUG_ROW_FULL if d["aug"] else _ROW_FULL
            assert row["rect"]["w"] < full, (
                f"{rt}: wrapped a row that had its full width"
                f" {row['rect']['w']:.0f}")
    for k, seen in lefts.items():
        assert max(seen) - min(seen) <= 1, f"{tag}: {k} row offsets {sorted(seen)}"


@pytest.mark.parametrize("w", [s[0] for s in _SIZES])
def test_roster_fits_and_reflows(roster, w):
    tag, out, errors = roster
    assert errors == [], f"{tag}: {errors[:3]}"
    _check(f"{tag} {w}", out[w])


def test_baseline_keeps_two_one_line_halves(roster):
    tag, out, _errors = roster
    d = out[1920]
    assert d["cols"] == 2, f"{tag}: {d['cols']} columns at 1920"
    assert all(r["display"] == "grid" for r in d["rows"]), (
        f"{tag}: a 1920 row is not the one-line grid")


def test_narrowest_row_wraps(roster):
    tag, out, _errors = roster
    d = out[320]
    assert all(r["display"] != "grid" for r in d["rows"]), (
        f"{tag}: a 320 row is still the fixed grid")


def test_live_arena_rows_carry_augments(roster):
    tag, out, _errors = roster
    if tag != "live-arena":
        pytest.skip("augment mode is the live Arena roster")
    for w in (1920, 320):
        d = out[w]
        assert d["aug"], f"{tag} {w}: roster not in augment mode"
        assert d["augs"] >= 8, f"{tag} {w}: {d['augs']} augment icons drawn"


def test_live_lane_matchup_card_is_measured(roster):
    tag, out, _errors = roster
    if tag != "live-sr":
        pytest.skip("the lane matchup card is pinned on the live SR view")
    assert all(out[w]["plc"] is not None for w in (1920, 480, 320)), (
        f"{tag}: lane matchup card not shown")
