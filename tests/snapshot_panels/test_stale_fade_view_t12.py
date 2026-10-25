"""
tests/snapshot_panels/test_stale_fade_view_t12.py

s136-T12 computed-style proof of the gentle stale / idle dim (static pins:
tests/test_stale_fade_gentle_t12.py). Drives the REAL staleness sweep: the
test ages state.lastTouch through the page's own lib/state.js module instance
and waits for main.js applyStaleness (500 ms tick) to stamp the stage class,
then reads getComputedStyle - no class is hand-stamped on a panel root.

Measured before the change (same probe): dashboard body 0.6 / 0.45 +
grayscale(0.4); overlay #rn-lead effective opacity 0.45 at severe and 0.054
at severe + idle; idle recede 0.12 on every widget.
"""
from __future__ import annotations

import pytest

FLOOR = 0.85

# Age a panel's lastTouch until the sweep shows the wanted class, then return
# the computed read. Re-ages inside the wait so a state envelope that re-touches
# the panel mid-wait cannot leave the read on a fresh panel.
_AGE_AND_READ = """async ([key, pid, age, klass, child]) => {
  const m = await import('/js/lib/state.js');
  const root = document.getElementById(pid);
  for (let i = 0; i < 60 && !root.classList.contains(klass); i++) {
    m.state.lastTouch[key] = Date.now() / 1000 - age;
    await new Promise((r) => setTimeout(r, 100));
  }
  const eff = (el) => { let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement)
      o *= parseFloat(getComputedStyle(n).opacity);
    return o; };
  const body = root.querySelector('.panel-body');
  const badge = root.querySelector('.staleness');
  const out = { has: root.classList.contains(klass),
    opacity: parseFloat(getComputedStyle(body).opacity),
    filter: getComputedStyle(body).filter,
    badge: badge.textContent, badgeClass: badge.className };
  if (child) {
    const c = document.getElementById(child);
    const a = getComputedStyle(c, '::after');
    out.eff = eff(c);
    out.after = { content: a.content, display: a.display, color: a.color,
      fontSize: a.fontSize, pe: a.pointerEvents, tt: a.textTransform };
  }
  return out;
}"""

_NO_TRANSITIONS = "*, *::before, *::after { transition: none !important; }"

# Geometry of the #rn-lead pill, read only once the page has SETTLED. The s136
# verifier measured the first cut racing the Lato swap (web/css/dashboard.css
# loads it with display=swap): "before" read the fallback face (line 140.89px
# wide, tag 21px tall), "after" the loaded one (138.22 / 19) - a font race,
# not a layout change. Settled = layout forced (so the pill's faces are
# requested), document.fonts.ready awaited (the S136 T11 idiom in
# test_overlay_tft_view._wait_tft), then the same geometry on two consecutive
# reads, each two animation frames apart. The panel's staleness age is held
# for the whole wait (age 0 = fresh, re-stamped so the 4 s sweep cannot flip it
# mid-wait), and the stage the read ran under is returned for the caller to pin.
_SETTLED_LEAD_GEO = """async ([age, want]) => {
  const m = await import('/js/lib/state.js');
  const e = document.getElementById('rn-lead');
  const root = document.getElementById('right-now');
  const raf = () => new Promise((r) => requestAnimationFrame(() => r()));
  const stage = () => root.classList.contains('severe') ? 'severe'
    : (root.classList.contains('stale') ? 'stale' : '');
  const r = (s) => { const q = e.querySelector(s).getBoundingClientRect();
    return [q.x, q.y, q.width, q.height]; };
  const read = () => ({ line: r('.rc-lead-line'), tag: r('.rc-lead-tag'),
    h: e.getBoundingClientRect().height, overflow: e.scrollHeight - e.clientHeight });
  let prev = null;
  for (let i = 0; i < 60; i++) {
    m.state.lastTouch.right_now = Date.now() / 1000 - age;
    read();                                   // force layout: request the faces
    await document.fonts.ready;
    await raf(); await raf();
    const cur = read();
    const key = JSON.stringify(cur);
    if (stage() === want && document.fonts.status === 'loaded' && key === prev) {
      return Object.assign(cur, { settled: true, cls: stage() });
    }
    prev = stage() === want ? key : null;
    await new Promise((res) => setTimeout(res, 50));
  }
  return Object.assign(read(), { settled: false, cls: stage() });
}"""


def _open(mock_server, pw_browser, overlay: bool):
    from tests.snapshot_panels.conftest import _WS_STUB
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    q = "&overlay=1" if overlay else ""
    page.goto(mock_server.url + "/?ui_mock=1&mode=sr" + q,
              wait_until="domcontentloaded", timeout=15_000)
    if overlay:
        page.wait_for_function(
            "document.body && document.body.dataset.shell === 'overlay'"
            " && document.getElementById('rn-lead').classList.contains('ovx-widget')",
            timeout=10_000)
    page.add_style_tag(content=_NO_TRANSITIONS)
    return ctx, page


@pytest.mark.parametrize("key,pid,stale_at,severe_at", [
    ("right_now", "right-now", 4, 12),
    ("next", "next", 16, 48),
    ("item_build", "item-build", 90, 300),
    ("minimap", "minimap", 4, 12),
])
def test_dashboard_panel_dim_is_gentle_and_badged(
        mock_server, pw_browser, key, pid, stale_at, severe_at):
    ctx, page = _open(mock_server, pw_browser, overlay=False)
    try:
        st = page.evaluate(_AGE_AND_READ, [key, pid, stale_at + 1, "stale", None])
        sv = page.evaluate(_AGE_AND_READ, [key, pid, severe_at + 1, "severe", None])
        assert st["has"] and sv["has"], (st, sv)
        assert st["opacity"] == pytest.approx(0.89), st
        assert sv["opacity"] == pytest.approx(0.85), sv
        assert st["filter"] == "none" and sv["filter"] == "none", (st, sv)
        # The cue: the age badge, stage-classed.
        assert st["badgeClass"] == "staleness stale" and st["badge"].endswith("s")
        assert sv["badgeClass"] == "staleness severe" and sv["badge"].endswith("s")
    finally:
        page.close()
        ctx.close()


def test_minimap_image_stale_is_light_and_captioned(mock_server, pw_browser):
    ctx, page = _open(mock_server, pw_browser, overlay=False)
    try:
        got = page.evaluate("""() => {
          const w = document.getElementById('mm-img-wrap');
          w.classList.remove('hidden'); w.classList.add('stale');
          const img = getComputedStyle(document.getElementById('mm-img'));
          const cap = getComputedStyle(document.getElementById('mm-img-caption'), '::after');
          return { opacity: img.opacity, filter: img.filter, after: cap.content }; }""")
        assert got == {"opacity": "1", "filter": "grayscale(0.15)",
                       "after": '" - STALE"'}, got
    finally:
        page.close()
        ctx.close()


def test_overlay_stale_tag_replaces_the_dim(mock_server, pw_browser):
    ctx, page = _open(mock_server, pw_browser, overlay=True)
    try:
        # The real lead-pill markup (callouts.js renderLead): a flex-wrap row.
        page.evaluate("""() => { const e = document.getElementById('rn-lead');
          e.hidden = false; e.classList.add('rc-lead', 'rc-lead-even');
          e.innerHTML = '<span class="rc-lead-line">Push mid wave then reset</span>'
            + '<span class="rc-lead-tag">EVEN</span>'; }""")
        before = page.evaluate(_SETTLED_LEAD_GEO, [0, ""])
        st = page.evaluate(_AGE_AND_READ, ["right_now", "right-now", 5, "stale", "rn-lead"])
        sv = page.evaluate(_AGE_AND_READ, ["right_now", "right-now", 13, "severe", "rn-lead"])
        after = page.evaluate(_SETTLED_LEAD_GEO, [13, "severe"])
        assert before["settled"] and after["settled"], (before, after)
        assert before["cls"] == "" and after["cls"] == "severe", (before, after)
        # STRUCTURE: the tag takes its own row at the foot - the line and the
        # state tag do not move, the pill grows, nothing scrolls or clips.
        assert after["line"] == before["line"] and after["tag"] == before["tag"], (
            before, after)
        assert after["h"] > before["h"] and after["overflow"] <= 0, (before, after)
        for read in (st, sv):
            assert read["has"], read
            assert read["opacity"] == 1.0 and read["filter"] == "none", read
            a = read["after"]
            assert a["content"] == '"stale"' and a["display"] == "block", a
            assert a["tt"] == "uppercase" and a["pe"] == "none", a
            assert a["fontSize"] == "11px", a          # --fs-ov-head
        assert st["after"]["color"] == "rgba(200, 170, 110, 0.9)", st   # gold
        assert sv["after"]["color"] == "rgb(232, 163, 61)", sv          # warn, not red
        # Idle recede on top of severe: the deepest overlay state.
        page.evaluate("() => document.body.setAttribute('data-rc-idle', '1')")
        deep = page.evaluate(_AGE_AND_READ, ["right_now", "right-now", 13, "severe", "rn-lead"])
        assert deep["eff"] == pytest.approx(FLOOR), deep   # was 0.054
        widgets = page.evaluate("""() => [...document.querySelectorAll('.ovx-widget')]
          .filter((w) => getComputedStyle(w).display !== 'none' && !w.style.opacity)
          .map((w) => parseFloat(getComputedStyle(w).opacity))""")
        assert widgets and all(o == pytest.approx(FLOOR) for o in widgets), widgets
    finally:
        page.close()
        ctx.close()


def test_overlay_fresh_has_no_tag(mock_server, pw_browser):
    ctx, page = _open(mock_server, pw_browser, overlay=True)
    try:
        got = page.evaluate("""async () => {
          const m = await import('/js/lib/state.js');
          m.state.lastTouch.right_now = Date.now() / 1000;
          const root = document.getElementById('right-now');
          for (let i = 0; i < 30 && (root.classList.contains('stale')
               || root.classList.contains('severe')); i++) {
            m.state.lastTouch.right_now = Date.now() / 1000;
            await new Promise((r) => setTimeout(r, 100));
          }
          return getComputedStyle(document.getElementById('rn-lead'), '::after').content; }""")
        assert got == "none", got
    finally:
        page.close()
        ctx.close()
