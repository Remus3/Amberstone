"""
tests/snapshot_panels/test_settings_checkbox_hit_targets.py
RM-1016 (s144 uiux): every checkbox on the Settings view is a 24x24 box,
below the 42px --hit-min floor (web/css/tokens.css). The design rule beside
both tokens says the visible control may be smaller as long as its <label>
wrapper pads to --hit-min and IS the click target (web/css/panels/header.css
`.settings-row`; web/css/panels/panel_visibility.css `.pv-cell`). An earlier
sweep listed "Settings checkboxes are 24x24" for triage; this file is the
check that the label really is the target, and the pin that keeps it so.

Measured in headless Chromium under /?ui_mock=1#settings, 1920x920 and
923x1280, with Dev mode on and two synthetic spend gates routed in:
- 8 static rows (CLIENT SETTINGS / DISPLAY / API SPEND GATES) wrap their box
  in label.settings-row, 51px tall;
- the JS-built spend gates (web/js/panels/dev.js renderSpendGates) use
  label.settings-row spend-gate-row, 81px tall with a two-line explain;
- the 17 PANEL VISIBILITY cells (web/js/panels/panel_visibility.js) use
  label.pv-cell, 42px tall;
- a real pointer click at the far edge of each label, outside the box,
  toggled its checkbox (every one, both widths);
- keyboard focus paints a 2px box-shadow ring on every one.
So no defect: the label is the target. Before this file the only guard was
test_settings_view.py test_settings_toggle_present, which checks the FIRST
row only, against 40px, and never clicks. This one fails if any checkbox
loses its label wrapper, a label drops under --hit-min, a click outside the
box stops toggling, or a box loses its focus ring.

RM-1061 (s144 uiux): the view painted TWO different checkbox focus rings.
The .settings-row boxes (static rows and spend gates) drew a one-off
`0 0 0 2px var(--accent), 0 0 8px var(--glow)` (web/css/panels/header.css)
while the PANEL VISIBILITY cells drew the system `--focus-ring` token
(web/css/tokens.css, re-declared per theme in web/css/themes.css;
web/css/panels/panel_visibility.css), so one Tab walk down the page switched
ring colour halfway (measured on the default arcane theme: a muted violet
accent plus a cyan glow, then a cyan 2px ring; on hextech a gold accent,
then a blue ring). Ruling: every checkbox in #view-settings draws
the system token, the ring the Replay filter checkboxes (RM-1017) and the
panel-visibility tabs already use, because it is the one value each theme
tunes for its own surfaces. The last test below pins one computed ring
across every checkbox, equal to the resolved token, on every theme.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VIEWPORTS = [(1920, 920), (923, 1280)]

# Synthetic /api/spend/gates payload (shape: dashboard/routes_coach.py
# _serve_spend_gates; one gate with a cost line, one without), so Dev mode
# builds its label rows. No live data is involved.
_GATES = {
    "gates": {
        "aram": {
            "label": "ARAM coach",
            "explain": "Coaching calls during ARAM games",
            "disabled": False,
        },
        "vision": {
            "label": "Vision",
            "explain": "Vision reads for OCR misses",
            "disabled": True,
        },
    },
    "per_match": {"aram": {"usd": 0.0123, "tokens": 4567, "n": 2}},
}

_TOKENS = """
() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;visibility:hidden;'
    + 'height:var(--hit-min)';
  document.body.appendChild(probe);
  const hit = parseFloat(getComputedStyle(probe).height);
  probe.remove();
  return hit;
}
"""

# Every rendered checkbox in the view: its own box and its label's box.
_BOXES = """
() => {
  const out = [];
  const all = document.querySelectorAll('#view-settings input[type=checkbox]');
  all.forEach((cb, i) => {
    const r = cb.getBoundingClientRect();
    if (!r.width) return;
    const lab = cb.closest('label');
    const lr = lab ? lab.getBoundingClientRect() : null;
    out.push({
      i, id: cb.id || cb.dataset.pvPanel || '',
      kind: lab ? lab.className : '(no label)',
      cbW: r.width, cbH: r.height,
      labW: lr ? lr.width : 0, labH: lr ? lr.height : 0,
    });
  });
  return out;
}
"""


def _open(pw_browser, mock_server, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route(
        "**/api/spend/gates*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(_GATES)
        ),
    )
    # RM-1222: the auto-accept control keeps a click only once the save echoes
    # the choice. The mock server's `{}` is a failed save, so the control went
    # back, and the read right after the click raced that revert (RM-1506: the
    # race went red once a request stopped costing a trip through Python).
    page.route(
        "**/api/lcu/auto-accept",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": True, "enabled": json.loads(route.request.post_data)["enabled"]}),
        ),
    )
    page.goto(
        mock_server.url + "/?ui_mock=1#settings",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "document.body.dataset.view === 'settings' && "
        "document.querySelector('#panel-visibility-card .pv-cell') !== null",
        timeout=10_000,
    )
    # Dev mode on, so the spend-gate rows render (and are measured too).
    if not page.is_checked("#set-dev-mode"):
        page.click("#set-dev-mode")
    page.wait_for_selector("#spend-gates-list .spend-gate-row", timeout=10_000)
    return ctx, page, errors


def _kinds(boxes):
    return {
        "settings-row": sum(1 for b in boxes if b["kind"] == "settings-row"),
        "spend-gate-row": sum(1 for b in boxes if "spend-gate-row" in b["kind"]),
        "pv-cell": sum(1 for b in boxes if b["kind"] == "pv-cell"),
    }


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_settings_checkbox_label_clears_hit_min(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        hit = page.evaluate(_TOKENS)
        boxes = page.evaluate(_BOXES)
    finally:
        page.close()
        ctx.close()
    assert hit >= 42, f"--hit-min resolved to {hit}px"
    # Anchor: an empty or half-built view must not pass. 8 static rows,
    # both synthetic gates, and the panel-visibility grid.
    kinds = _kinds(boxes)
    assert kinds["settings-row"] == 8, f"static settings rows: {kinds}"
    assert kinds["spend-gate-row"] == 2, f"spend-gate rows: {kinds}"
    assert kinds["pv-cell"] >= 10, f"panel-visibility cells: {kinds}"
    bad = [b for b in boxes if b["kind"] == "(no label)"]
    assert not bad, f"checkbox without a <label> wrapper: {bad[:3]}"
    for b in boxes:
        # The box itself is the small visible control the rule allows ...
        assert b["cbH"] < hit, f"premise: box {b} already clears --hit-min"
        # ... and its label is the full fingertip target.
        assert b["labH"] >= hit - 0.5, (
            f"{b['kind']} #{b['id']} label {b['labH']}px < --hit-min {hit}px"
        )
        assert b["labW"] >= hit - 0.5, (
            f"{b['kind']} #{b['id']} label {b['labW']}px wide < --hit-min"
        )
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_click_on_label_outside_the_box_toggles(mock_server, pw_browser, vp):
    """A real pointer click 4px inside the label's far corner, well clear of
    the 24px box, toggles the checkbox. The point is checked to land inside
    the label and outside the checkbox before clicking."""
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    failures = []
    clicked = 0
    try:
        sel = "#view-settings input[type=checkbox]"
        for i in range(len(page.query_selector_all(sel))):
            # Re-query each step: a spend-gate click re-renders the gate
            # list (dev.js renderSpendGates after its POST), detaching the
            # handles taken before it.
            h = page.query_selector_all(sel)[i]
            if not h.is_visible():
                continue
            # Dev mode is the precondition of this fixture; toggling it off
            # would unmount the gate rows still to be clicked.
            if h.get_attribute("id") == "set-dev-mode":
                continue
            h.evaluate("e => e.closest('label').scrollIntoView({block: 'center'})")
            pt = h.evaluate(
                """e => {
                  const lr = e.closest('label').getBoundingClientRect();
                  const x = lr.right - 4, y = lr.bottom - 4;
                  const at = document.elementFromPoint(x, y);
                  return {x, y, inLabel: !!at && e.closest('label').contains(at),
                          onBox: at === e};
                }"""
            )
            name = h.get_attribute("id") or h.get_attribute("data-pv-panel") or "gate"
            if not pt["inLabel"] or pt["onBox"]:
                failures.append(f"{name}: probe point {pt}")
                continue
            before = h.is_checked()
            page.mouse.click(pt["x"], pt["y"])
            after = h.evaluate("e => e.checked")
            clicked += 1
            if after == before:
                failures.append(f"{name}: label click did not toggle")
            elif h.evaluate("e => !!e.closest('.spend-gate-row')"):
                # The gate re-renders from the routed payload; wait for it.
                page.wait_for_function("e => !e.isConnected", arg=h, timeout=5_000)
            else:
                page.mouse.click(pt["x"], pt["y"])  # restore
    finally:
        page.close()
        ctx.close()
    assert clicked >= 20, f"only {clicked} checkboxes clicked"
    assert not failures, failures[:5]
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_settings_checkbox_shows_a_focus_ring(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        # One keyboard press sets keyboard modality, so .focus() below
        # matches :focus-visible the way Tab traversal does.
        page.keyboard.press("Tab")
        rings = page.evaluate(
            """() => {
              const out = [];
              const all = document.querySelectorAll(
                '#view-settings input[type=checkbox]');
              for (const cb of all) {
                if (!cb.getBoundingClientRect().width) continue;
                cb.focus();
                const cs = getComputedStyle(cb);
                out.push({id: cb.id || cb.dataset.pvPanel || 'gate',
                          fv: cb.matches(':focus-visible'),
                          shadow: cs.boxShadow});
              }
              return out;
            }"""
        )
    finally:
        page.close()
        ctx.close()
    assert len(rings) >= 20, f"only {len(rings)} checkboxes measured"
    bad = [r for r in rings if not r["fv"] or "0px 0px 0px 2px" not in r["shadow"]]
    assert not bad, f"checkbox without a 2px focus ring: {bad[:3]}"
    assert not errors, f"JS errors: {errors[:3]}"


# Every theme the picker offers (web/js/lib/theme.js THEMES). hextech is the
# ABSENCE of the attribute; the others stamp <html data-theme>.
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

_RINGS_BY_THEME = """
(themes) => {
  const root = document.documentElement;
  const view = document.getElementById('view-settings');
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    // The token as the browser resolves it, read through a probe inside
    // the view so it inherits exactly what the checkboxes inherit.
    const probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;visibility:hidden;'
      + 'box-shadow:var(--focus-ring)';
    view.appendChild(probe);
    const token = getComputedStyle(probe).boxShadow;
    probe.remove();
    const rings = [];
    for (const cb of view.querySelectorAll('input[type=checkbox]')) {
      if (!cb.getBoundingClientRect().width) continue;
      cb.focus();
      const lab = cb.closest('label');
      rings.push({id: cb.id || cb.dataset.pvPanel || 'gate',
                  kind: lab ? lab.className : '(no label)',
                  fv: cb.matches(':focus-visible'),
                  shadow: getComputedStyle(cb).boxShadow});
    }
    out[t] = {token, rings};
  }
  return out;
}
"""


@pytest.mark.parametrize("vp", VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_settings_checkbox_draws_the_one_system_focus_ring(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        page.keyboard.press("Tab")  # keyboard modality, as above
        by_theme = page.evaluate(_RINGS_BY_THEME, _THEMES)
    finally:
        page.close()
        ctx.close()
    assert sorted(by_theme) == sorted(_THEMES), by_theme.keys()
    tokens = set()
    for theme, got in by_theme.items():
        token, rings = got["token"], got["rings"]
        # Anchor: the token resolved to a real 2px ring, and the whole view
        # was measured (8 static rows + 2 gates + the panel grid).
        assert "0px 0px 0px 2px" in token, f"{theme}: --focus-ring = {token!r}"
        kinds = _kinds(rings)
        assert kinds["settings-row"] == 8, f"{theme}: {kinds}"
        assert kinds["spend-gate-row"] == 2, f"{theme}: {kinds}"
        assert kinds["pv-cell"] >= 10, f"{theme}: {kinds}"
        assert all(r["fv"] for r in rings), f"{theme}: not :focus-visible"
        shadows = {r["shadow"] for r in rings}
        off = [r for r in rings if r["shadow"] != token]
        assert shadows == {token}, (
            f"{theme}: {len(shadows)} distinct checkbox rings; token {token!r};"
            f" first off-token: {off[:2]}"
        )
        tokens.add(token)
    # The comparison is not vacuous: the token really changes with the
    # theme, so a hard-coded colour would fail on at least one theme.
    assert len(tokens) >= 3, f"--focus-ring did not vary by theme: {tokens}"
    assert not errors, f"JS errors: {errors[:3]}"


# S144-U-178 (s144 uiux): every .settings-row checkbox is a flex item with
# the default flex-shrink 1 beside a text span that breaks between words, so
# from 720px down the box gave up its width to the text: measured 13x24 on
# Dev mode, Dev UI mock data, Force Flash on Snowball and the three champ
# select auto-push rows at 480 and under, 19.4x24 on Dev mode at 720 (the
# "Dev mode checkbox draws smaller than the gate checkboxes" row, U-169).
# A squeezed native checkbox paints a narrow box beside its square
# neighbours. Ruling: the visible control keeps its declared square at every
# width; the text wraps instead. This pins it on the widths the narrow-reflow
# file covers, plus the two desktop widths above.
NARROW_VIEWPORTS = [(1920, 920), (923, 1280), (720, 900), (480, 900), (320, 900)]

_SIZES = """
() => {
  const out = [];
  for (const cb of document.querySelectorAll(
      '#view-settings input[type=checkbox]')) {
    const r = cb.getBoundingClientRect();
    if (!r.width) continue;
    const lab = cb.closest('label');
    out.push({id: cb.id || cb.dataset.pvPanel || 'gate',
              kind: lab ? lab.className : '(no label)',
              w: Math.round(r.width * 10) / 10,
              h: Math.round(r.height * 10) / 10});
  }
  return out;
}
"""


@pytest.mark.parametrize("vp", NARROW_VIEWPORTS, ids=lambda v: f"{v[0]}x{v[1]}")
def test_every_settings_checkbox_keeps_its_square_box_at_every_width(
    mock_server, pw_browser, vp
):
    ctx, page, errors = _open(pw_browser, mock_server, vp)
    try:
        sizes = page.evaluate(_SIZES)
    finally:
        page.close()
        ctx.close()
    # Anchor: the whole view was measured, Dev mode row included.
    kinds = _kinds(sizes)
    assert kinds["settings-row"] == 8, f"static settings rows: {kinds}"
    assert kinds["spend-gate-row"] == 2, f"spend-gate rows: {kinds}"
    assert kinds["pv-cell"] >= 10, f"panel-visibility cells: {kinds}"
    assert any(s["id"] == "set-dev-mode" for s in sizes), sizes[:3]
    rows = [s for s in sizes if "settings-row" in s["kind"]]
    off = [s for s in rows if s["w"] != 24 or s["h"] != 24]
    assert not off, f"{vp}: settings-row checkbox not 24x24: {off}"
    # One size across the view: a row box never draws smaller than another.
    assert len({(s["w"], s["h"]) for s in sizes}) == 1, (
        f"{vp}: checkbox sizes differ: {sorted({(s['w'], s['h']) for s in sizes})}"
    )
    assert not errors, f"JS errors: {errors[:3]}"
