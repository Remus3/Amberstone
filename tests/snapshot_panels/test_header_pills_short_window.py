"""
tests/snapshot_panels/test_header_pills_short_window.py
RM-1437 (s144 uiux) - on Active Match the in-game header pills leave the
view room in a small window, and the footer stays inside the window.

THE DEFECT. MEASURED in headless Chromium under
/?ui_mock=1&mode=sr#active-match with live-shaped pill values (100% WIN,
DEEP ENEMY zone, a 32:45 clock, CS 245, vision 48, a "<heart> 12:45:33 PM"
heartbeat). Below 1200px the header row wraps (header.css, R30) and every
pill kept its desktop slot: 43px tall and as wide as the 1920 row allows
(WIN 125, zone 142, clock 107, CS 185, vision 72, heartbeat 147). The header
was 106 / 157 / 157 / 259 px tall at 720x346 / 640x307 / 480x230 / 320x256,
so the Active Match view kept 196 / 106 / 29 / 8 px, and at 320x256 the
footer ended 55px below the window (its status row cut off).

THE FIX. web/css/panels/header.css, @media (max-width: 720px): each pill is
a compact slot - 34px tall (the row's min-height), 8px side padding, width
auto with a min-width that holds its widest usual value - so the pills pack
into fewer rows. The text keeps its 21px size (a zoomed reader keeps the
zoom). The min-widths keep the static-pill rule at this size: the "-"
placeholders, a short value and the widest usual value all give the same
slot map, so a value arriving does not reflow the row.

What is checked, on SR Active Match at 720x346, 640x307, 480x230 and
320x256 (and TFT at 320x256):
- the footer lies whole inside the window, and the view keeps a measured
  floor of room;
- the header is no taller than its measured fixed height;
- the pills are 34px, below the 43px trigger, and none clips its text;
- the slot map is the same for the placeholders, short values and the
  widest usual values;
- above 720px (721x346, 923x1280, 1920x920) every pill keeps its desktop
  slot, so nothing moves there.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import _new_page

_URL = "/?ui_mock=1&mode={mode}#active-match"
_PILLS = ("win-pill", "zone-pill", "game-time", "cs-pill", "vis-pill", "heartbeat")

# Measured after the fix (header height cap, view-room floor). At HEAD the
# header was 106 / 157 / 157 / 259 and the view 196 / 106 / 29 / 8.
_SMALL = {
    (720, 346): (97, 200),
    (640, 307): (97, 160),
    (480, 230): (139, 40),
    (320, 256): (181, 30),
}
_DESKTOP = [(721, 346), (923, 1280), (1920, 920)]
_DESKTOP_W = {"win-pill": 125, "zone-pill": 142, "game-time": 107,
              "cs-pill": 185, "vis-pill": 72, "heartbeat": 147}

# Synthetic values (no real game data): placeholder, short, live-shaped and
# the widest usual value of each pill.
_SETS = {
    "placeholder": {"win": "-", "zone": "-", "time": "", "cs": "-", "vis": "-",
                    "hb": "\u2665 -"},
    "short": {"win": "9%", "zone": "- DMZ", "time": "1:05", "cs": "5", "vis": "8",
              "hb": "\u2665 1:05:33 AM"},
    "live": {"win": "100%", "zone": "\u26d4 DEEP ENEMY", "time": "32:45",
             "cs": "245", "vis": "48", "hb": "\u2665 12:45:33 PM"},
    "widest": {"win": "100%", "zone": "\u26a0 ENEMY ZONE", "time": "59:59",
               "cs": "999", "vis": "999", "hb": "\u2665 12:58:58 PM"},
}

_FILL = """
(v) => {
  document.body.dataset.mode = v.mode;
  const wp = document.getElementById('win-pill');
  wp.className = 'win-pill win-even';
  document.getElementById('win-pct-val').textContent = v.win;
  document.getElementById('zone-pill').className = 'zone-pill zone-enemy';
  document.getElementById('zone-label').textContent = v.zone;
  document.getElementById('game-time').textContent = v.time;
  document.getElementById('cs-val').textContent = v.cs;
  document.getElementById('vis-val').textContent = v.vis;
  const hb = document.getElementById('heartbeat');
  hb.className = 'hb hb-connected';
  hb.textContent = v.hb;
}
"""

_PROBE = """
(ids) => {
  const de = document.documentElement;
  const vh = de.clientHeight, vw = de.clientWidth;
  const h = document.querySelector('header').getBoundingClientRect();
  const f = document.querySelector('footer').getBoundingClientRect();
  const v = document.getElementById('view-active-match').getBoundingClientRect();
  const t = document.getElementById('view-trigger').getBoundingClientRect();
  const pills = {};
  for (const id of ids) {
    const e = document.getElementById(id);
    if (!e.getClientRects().length) continue;
    const b = e.getBoundingClientRect();
    pills[id] = {l: b.left, t: b.top, w: b.width, h: b.height,
                 r: b.right, b: b.bottom,
                 clip: e.scrollWidth > e.clientWidth + 1};
  }
  return {vw, vh, docOverflow: de.scrollWidth - vw,
          headerH: h.height, footTop: f.top, footBottom: f.bottom,
          viewH: v.height, triggerH: t.height, pills};
}
"""


def _open(pw_browser, mock_server, vp, mode, values):
    ctx, page, errors = _new_page(pw_browser, mock_server, vp)
    page.goto(mock_server.url + _URL.format(mode=mode),
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_selector("#view-trigger", state="visible", timeout=10_000)
    page.wait_for_function(
        "() => document.body.dataset.view === 'active-match'", timeout=10_000)
    page.wait_for_timeout(300)
    page.evaluate(_FILL, {**values, "mode": mode})
    page.wait_for_timeout(150)
    return ctx, page, errors


def _probe(page):
    return page.evaluate(_PROBE, list(_PILLS))


@pytest.mark.parametrize("vp", list(_SMALL), ids=lambda v: f"{v[0]}x{v[1]}")
def test_small_window_keeps_footer_and_view_room(vp, pw_browser, mock_server):
    ctx, page, errors = _open(pw_browser, mock_server, vp, "sr", _SETS["live"])
    try:
        st = _probe(page)
    finally:
        ctx.close()
    cap, floor = _SMALL[vp]
    label = f"sr {vp[0]}x{vp[1]}"
    assert st["docOverflow"] <= 0, f"{label}: page scrolls sideways {st['docOverflow']}px"
    assert st["footBottom"] <= st["vh"] + 0.5, (
        f"{label}: the footer ends {st['footBottom'] - st['vh']:.0f}px below"
        " the window")
    assert st["headerH"] <= cap + 0.5, (
        f"{label}: the header is {st['headerH']:.0f}px tall (cap {cap})")
    assert st["viewH"] >= floor, (
        f"{label}: the Active Match view keeps {st['viewH']:.0f}px (floor {floor})")
    assert set(st["pills"]) == set(_PILLS), f"{label}: pills shown {sorted(st['pills'])}"
    for pid, p in st["pills"].items():
        assert abs(p["h"] - 34) <= 0.5, f"{label}: {pid} is {p['h']}px tall, want 34"
        assert not p["clip"], f"{label}: {pid} clips its text"
        assert p["l"] >= -0.5 and p["r"] <= st["vw"] + 0.5, f"{label}: {pid} off the window"
    assert st["triggerH"] >= 42, f"{label}: the view trigger is {st['triggerH']}px"
    assert not errors, errors


@pytest.mark.parametrize("vp", list(_SMALL), ids=lambda v: f"{v[0]}x{v[1]}")
def test_small_window_slot_map_ignores_the_values(vp, pw_browser, mock_server):
    maps = {}
    for name, values in _SETS.items():
        ctx, page, errors = _open(pw_browser, mock_server, vp, "sr", values)
        try:
            st = _probe(page)
        finally:
            ctx.close()
        for pid, p in st["pills"].items():
            assert not p["clip"], f"{name} {vp}: {pid} clips its text"
        maps[name] = {pid: (round(p["l"]), round(p["t"]), round(p["w"]))
                      for pid, p in st["pills"].items()}
        maps[name]["header"] = round(st["headerH"])
    base = maps["placeholder"]
    for name, m in maps.items():
        moved = {k: (base.get(k), m.get(k)) for k in set(base) | set(m)
                 if base.get(k) != m.get(k)}
        assert not moved, (
            f"{vp[0]}x{vp[1]}: the {name} values move the header slot map"
            f" against the placeholders: {moved}")


def test_tft_small_window_keeps_footer(pw_browser, mock_server):
    ctx, page, errors = _open(pw_browser, mock_server, (320, 256), "tft", _SETS["live"])
    try:
        st = _probe(page)
    finally:
        ctx.close()
    assert st["footBottom"] <= st["vh"] + 0.5, "tft 320x256: footer below the window"
    assert st["viewH"] >= 80, f"tft 320x256: the view keeps {st['viewH']:.0f}px"


@pytest.mark.parametrize("vp", _DESKTOP, ids=lambda v: f"{v[0]}x{v[1]}")
def test_wider_windows_keep_the_desktop_slots(vp, pw_browser, mock_server):
    ctx, page, errors = _open(pw_browser, mock_server, vp, "sr", _SETS["live"])
    try:
        st = _probe(page)
    finally:
        ctx.close()
    for pid, want in _DESKTOP_W.items():
        p = st["pills"][pid]
        assert abs(p["w"] - want) <= 0.5, f"{vp}: {pid} is {p['w']}px wide, want {want}"
        assert abs(p["h"] - 43) <= 0.5, f"{vp}: {pid} is {p['h']}px tall, want 43"
    assert st["footBottom"] <= st["vh"] + 0.5
