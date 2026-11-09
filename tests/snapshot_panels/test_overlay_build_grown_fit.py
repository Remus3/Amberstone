"""
tests/snapshot_panels/test_overlay_build_grown_fit.py
S144-U-283 (s144 uiux): in the overlay shell the bottom-anchored BUILD
widget (w-build) stops growing at the Coach Call widget (w-call) above it,
and a trailing section that no longer fits is dropped WHOLE - its eyebrow
and its strip together - instead of being sliced by the widget clip.

THE DEFECT. QA ledger FUTURE (i) of S144-U-282. S144-U-282 bottom-anchored
w-build (bottom 16 px, growing upward, capped only at H - 32), measured with
the repo fixtures, which never populate the two data-gated build sections:
the DEFENSE row (active_match.js s171.6, shown when the enemy threat crosses
burst >= 5 / ad >= 7 / ap >= 7) and the COUNTER row (R102 counter_hints from
/api/build-plan). Measured headless with both populated (the payloads below
come from the real producers, core/defensive_picks.py and
core/build_planner/situational.py, for the sr fixture's enemy roster), at
1920x1080:
  - sr: w-build top 59 - it grew over w-call (x 180 - 390, y 130 - 320),
    the doctrine's ONE primary widget, by 261 px;
  - aram / mayhem: top 179, again over w-call (bottom 305 / 356);
  - arena: top 137, over w-call (bottom 320).
At the headless-only 920 the box hit its H - 32 cap and the clip sliced the
THREATS strip (sr: strip 918 - 992 against a clip bottom of 903).

THE FIX. web/js/lib/overlay_layout.js: a bottom-anchored tall widget's
--ovx-maxh is capped at the visible primary widget's bottom plus a 12 px gap
whenever the two share a column (TALL_FLOOR_GAP, _tallFloorTop), and
_fitDropGroups then drops the build body's [data-ovx-drop] groups from the
LAST one up (THREATS, then COUNTER, then DEFENSE, then the capability-gap
chip) until the content fits the clip. The rerank module is never dropped.

The payloads are injected with page.route on the two POSTs the build pane
makes; the mock server answers every POST with {} otherwise.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_W = '.ovx-widget[data-ovx-id="w-build"]'
_SHEET = "*, *::before, *::after { transition: none !important; }"

# /api/ds-preview: compute_threat_profile(["Teemo", "Elise", "Ekko",
# "Kaisa", "Blitzcrank"]) and recommend_defensive_items(threat,
# my_champion="Jinx", my_owned_items=[])[:3]. ranked [] keeps the
# fixture's coach picks in the LIVE row (livePicks empty -> coachPicks).
_DS_PREVIEW = {
    "ok": True, "ranked": [],
    "threat": {"ad_threat": 5.6, "ap_threat": 5.8, "burst_threat": 6.0,
               "tank_pressure": 2.0,
               "top_threats": [{"name": "Teemo", "kind": "AP burst"},
                               {"name": "Elise", "kind": "AP burst"},
                               {"name": "Ekko", "kind": "AP burst"}],
               "summary": "burst threat (6/10)"},
    "defensive": [
        {"item_id": "3156", "name": "Maw of Malmortius",
         "category": "lifeline",
         "reason": "30 MR + lifeline shield vs magic damage", "score": 8.2},
        {"item_id": "3053", "name": "Sterak's Gage", "category": "lifeline",
         "reason": "bonus-HP shield + tenacity on burst", "score": 8.2},
        {"item_id": "3102", "name": "Banshee's Veil", "category": "mr",
         "reason": "50 MR + 80 AP + spell shield vs poke/burst",
         "score": 7.3},
    ],
}
# /api/build-plan: counter_build_hints([], EnemyProfile(ad_share 0.44,
# ap_share 0.56, kill_target_armor 95, kill_target_mr 60, heal_sources 2,
# cc_score 6.2, burst_threat 6.0, tank_pressure 2.0)).
_BUILD_PLAN = {
    "ok": True, "live": [], "meta": [],
    "counter_hints": [
        {"criterion": "antiheal", "satisfied": False, "severity": "high",
         "label": "ANTIHEAL", "detail": "2 enemy heal sources",
         "suggest_class": "antiheal"},
        {"criterion": "resist", "satisfied": False, "severity": "med",
         "label": "MR", "detail": "enemy 56% magic", "suggest_class": "mr"},
        {"criterion": "pen_type", "satisfied": False, "severity": "med",
         "label": "LETHALITY", "detail": "kill target 95 armor",
         "suggest_class": "lethality"},
        {"criterion": "tenacity", "satisfied": False, "severity": "med",
         "label": "TENACITY", "detail": "enemy CC 6/10",
         "suggest_class": "tenacity"},
    ],
}

# (mode, viewport, query suffix). 2560x1440 at ovscale 1.333 is the same
# 1080-design-px field on a real 1440p screen, so the zoom math is pinned too.
_CASES = [
    ("sr", (1920, 1080), ""),
    ("aram", (1920, 1080), ""),
    ("mayhem", (1920, 1080), ""),
    ("arena", (1920, 1080), ""),
    ("sr", (2560, 1440), "&ovscale=1.333"),
]
_IDS = [f"{m}-{v[0]}x{v[1]}" for m, v, _ in _CASES]
_GROUPS = ("DEFENSE", "COUNTER", "THREATS")

# One synchronous read: the widget clip and box, the w-call box, every
# visible direct child of the widget and of #am-build-body, and each data
# section (eyebrow + the strip right after it) with its visibility.
_READ = """(wsel) => {
  const box = (r) => ({left: r.left, right: r.right, top: r.top,
                       bottom: r.bottom});
  const vis = (el) => !!el && el.checkVisibility()
    && el.getBoundingClientRect().height > 0.5;
  const w = document.querySelector(wsel);
  if (!w) return null;
  const wr = w.getBoundingClientRect();
  const z = parseFloat(getComputedStyle(document.body).zoom) || 1;
  const clip = {left: wr.left + w.clientLeft * z, top: wr.top + w.clientTop * z};
  clip.right = clip.left + w.clientWidth * z;
  clip.bottom = clip.top + w.clientHeight * z;
  const body = w.querySelector('#am-build-body');
  const shown = [];
  for (const k of [...w.children, ...(body ? body.children : [])]) {
    if (k === body || !vis(k)) continue;
    shown.push({cls: String(k.className || ''),
                text: (k.textContent || '').trim().slice(0, 24),
                box: box(k.getBoundingClientRect())});
  }
  const groups = {};
  for (const k of (body ? body.children : [])) {
    const t = (k.textContent || '').trim();
    for (const g of ['DEFENSE', 'COUNTER', 'THREATS']) {
      if (t.startsWith(g) && !groups[g]) {
        const strip = k.nextElementSibling;
        groups[g] = {eyebrow: vis(k), strip: vis(strip),
                     attached: !!strip};
      }
    }
  }
  const mod = w.querySelector('.bm-module');
  let call = null;
  const c = document.querySelector('.ovx-widget[data-ovx-id="w-call"]');
  if (vis(c)) call = box(c.getBoundingClientRect());
  const dropped = [...w.querySelectorAll('[data-ovx-dropped]')].map(
    (n) => getComputedStyle(n).display);
  return {clip: clip, wbox: box(wr), vh: window.innerHeight, z: z,
          shown: shown, groups: groups, call: call, dropped: dropped,
          sw: w.scrollWidth, cw: w.clientWidth,
          bsw: body ? body.scrollWidth : 0, bcw: body ? body.clientWidth : 0,
          module: mod && vis(mod) ? box(mod.getBoundingClientRect()) : null};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _fulfil_with(body):
    # Playwright calls a route handler with (route, request).
    def handler(route, _request):
        route.fulfill(status=200, content_type="application/json", body=body)
    return handler


def _measure(mock_server, pw_browser, mode, vp, query):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    for path, payload in (("**/api/ds-preview", _DS_PREVIEW),
                          ("**/api/build-plan", _BUILD_PLAN)):
        page.route(path, _fulfil_with(json.dumps(payload)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode={mode}&overlay=1{query}",
            wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'"
            " && document.body.classList.contains('ovx-ready')",
            timeout=10_000)
        # All three data sections are in the DOM (shown or dropped).
        page.wait_for_function(
            """(wsel) => {
              const b = document.querySelector(wsel + ' #am-build-body');
              if (!b) return false;
              const t = [...b.children].map(
                (k) => (k.textContent || '').trim());
              return ['DEFENSE', 'COUNTER', 'THREATS'].every(
                (g) => t.some((s) => s.startsWith(g)));
            }""", arg=_W, timeout=20_000)
        page.add_style_tag(content=_SHEET)
        # The layout observer re-places the field 150 ms after a re-render.
        page.wait_for_timeout(500)
        got = page.evaluate(_READ, _W)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got, "w-build is not on the page"
    return got


def _get(measured, mock_server, pw_browser, case):
    mode, vp, query = case
    key = (mode, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, mode, vp, query)
    return measured[key]


def _inside(clip, b):
    return (b["left"] >= clip["left"] - 0.5
            and b["right"] <= clip["right"] + 0.5
            and b["top"] >= clip["top"] - 0.5
            and b["bottom"] <= clip["bottom"] + 0.5)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_the_grown_widget_stops_below_the_call_widget(
        case, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, case)
    wb, call = got["wbox"], got["call"]
    assert call, f"{case[0]}: w-call is not visible"
    x = min(wb["right"], call["right"]) - max(wb["left"], call["left"])
    assert x > 0, "the two widgets no longer share a column; the case is moot"
    gap = wb["top"] - call["bottom"]
    # 12 design px (TALL_FLOOR_GAP) at the field zoom; never an overlap.
    assert gap >= 12 * got["z"] - 1.0, (
        f"{case[0]} {case[1]}: w-build top {wb['top']:.0f} vs w-call bottom"
        f" {call['bottom']:.0f} (gap {gap:.0f})")


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_the_widget_stays_on_the_bottom_left_corner(
        case, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, case)
    wb, z = got["wbox"], got["z"]
    assert abs(wb["bottom"] - (got["vh"] - 16 * z)) <= 1.5, (case, wb)
    assert abs(wb["left"] - 70 * z) <= 1.5, (case, wb)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_nothing_shown_is_cut_by_the_clip(
        case, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, case)
    assert len(got["shown"]) >= 2, got["shown"]
    cut = [f"{k['cls'] or k['text']!r} {k['box']['top']:.0f}-"
           f"{k['box']['bottom']:.0f}"
           for k in got["shown"] if not _inside(got["clip"], k["box"])]
    assert not cut, (f"{case[0]} {case[1]}: cut at clip bottom"
                     f" {got['clip']['bottom']:.0f}: " + "; ".join(cut))


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_the_rerank_module_is_never_dropped(
        case, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, case)
    assert got["module"], f"{case[0]}: the rerank module is not shown"
    assert _inside(got["clip"], got["module"]), got["module"]


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_a_section_is_shown_or_dropped_whole_from_the_end(
        case, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, case)
    groups = got["groups"]
    assert set(groups) == set(_GROUPS), groups
    order = []
    for g in _GROUPS:
        s = groups[g]
        assert s["attached"], f"{g}: no strip after the eyebrow"
        # Whole: the eyebrow never shows without its strip, or the reverse.
        assert s["eyebrow"] == s["strip"], f"{case[0]} {g} split: {s}"
        order.append(s["eyebrow"])
    # Dropped from the END: once a section is dropped, every later one is.
    assert order == sorted(order, reverse=True), (
        f"{case[0]}: shown {dict(zip(_GROUPS, order))}")


def test_sr_drops_at_least_one_section_at_the_real_height(
        measured, mock_server, pw_browser):
    # Anchor against a vacuous pass: with both data rows in, the sr content
    # (about 1005 px) cannot fit under w-call, so the fit really ran.
    got = _get(measured, mock_server, pw_browser, _CASES[0])
    shown = [g for g in _GROUPS if got["groups"][g]["eyebrow"]]
    assert "THREATS" not in shown, shown
    assert "DEFENSE" in shown, shown


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_a_dropped_section_collapses_and_nothing_overflows_sideways(
        case, measured, mock_server, pw_browser):
    # STRUCTURE (5-phase audit): a dropped node really collapses - the strips
    # carry an inline display:flex, which a plain [hidden]-style rule loses
    # to - and neither the widget nor its body scrolls sideways.
    got = _get(measured, mock_server, pw_browser, case)
    assert all(d == "none" for d in got["dropped"]), got["dropped"]
    assert got["sw"] <= got["cw"], (got["sw"], got["cw"])
    assert got["bsw"] <= got["bcw"], (got["bsw"], got["bcw"])
