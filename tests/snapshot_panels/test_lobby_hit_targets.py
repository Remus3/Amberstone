"""
tests/snapshot_panels/test_lobby_hit_targets.py
RM-338 - an oversized hit-target overlay must not cover a neighbouring
control.

THE DEFECT. web/css/panels/header.css gives .lv-top8-reorder-btn a
transparent ::before overlay so a visually tiny chevron still clears the
fingertip floor. The button is 26x14 and the overlay was 44x44, so it
extended 15px past the button in BOTH vertical directions. The two
reorder chevrons are stacked 1px apart inside .lv-top8-reorder, which
means each overlay covered its sibling ENTIRELY. Neither element sets
z-index, so `down` - later in DOM order - won hit testing over the whole
of `up`, and every "move up" control in the Top 8 was dead to the mouse.

MEASURED at HEAD 2026-09-04 with document.elementFromPoint at each
control's own centre, over a 3-entry seed: 3 of 3 `up` chevrons reported
their sibling `down` button as the hit target, disabled or not. Keyboard
activation still worked, which is exactly why this shipped - the panel
looks and reads fine, and only a pointer finds it.

THE FIX follows the in-repo precedent one ruleset up rather than
inventing a second pattern: .lv-member-action (header.css:1489) already
solved the same problem by bounding its overlay in the axis where a
neighbour sits (30px wide, the button-plus-gap pitch) and expanding it
only in the axis with room (44px tall). For the reorder pair the crowded
axis is VERTICAL, so each chevron anchors its overlay to its own OUTER
edge and claims only the slack on that side.

Geometry MEASURED on the 1920x1080 baseline, not assumed:
  .lv-top8-row       y 424 h 39   (list gap 4px -> 43px row pitch)
  .lv-top8-reorder   y 429 h 29   (5px row padding above and below)
  up                 y 429 h 14
  down               y 444 h 14   (1px seam at 443/444)
So each chevron has 5px of row padding plus half of the 4px inter-row
gap = 7px of genuinely free space on its outer side. 14 + 7 = 21px, and
the two 21px overlays tile one 43px row exactly, abutting the next row's
pair rather than overlapping it.

WHY BOTH DIRECTIONS ARE ASSERTED. A "fix" that merely gave `up` a higher
z-index would pass the `up` assertion and silently kill `down` instead -
the same defect with the victims swapped. The `down` half of this module
is therefore the load-bearing one, and it is GREEN at HEAD by design.

SIBLING SWEEP. The same oversized-overlay idiom appears at other sites,
so test_no_oversized_overlay_covers_a_neighbour does not name selectors:
it walks the whole rendered lobby, finds every element whose ::before or
::after is absolutely positioned and larger than its own box, and
asserts each one still owns its own centre. Root-cause coverage rather
than a list that goes stale the next time someone adds an overlay.

Harness mirrors test_lobby_render_stability.py exactly (same opener,
same /api/top8 seeding, same LCU envelope) - the reorder controls are
server-backed, so they are driven through the real store rather than by
poking module-private state. The LCU envelope additionally carries
main_champs so the YOUR MAINS list renders its own .lv-mc-copy overlays
into the same sweep.
"""
import copy
from pathlib import Path

from tests.snapshot_panels.test_lobby_render_stability import (
    _POLL_LCU,
    _TOP8_SEED,
    _open_lobby_stability,
)

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web"

# YOUR MAINS rows. _renderMains reads state.latest.lcu.main_champs
# directly (main.js:4278) - the ui_mock lobby fixture's `mains` key does
# NOT reach it - so the mains overlays only enter the sweep when the
# polled envelope carries them.
_MAIN_CHAMPS = {
    "champions": [
        {"name": "Jinx", "overall": {"games": 40, "wins": 22},
         "averaged": {"total_kda": "6/3/9"},
         "last_match": {"result": "WIN", "kda": "6/3/9"}},
        {"name": "Vayne", "overall": {"games": 30, "wins": 14},
         "averaged": {"total_kda": "4/5/7"},
         "last_match": {"result": "LOSS", "kda": "4/5/7"}},
        {"name": "Tristana", "overall": {"games": 20, "wins": 12},
         "averaged": {"total_kda": "8/2/5"},
         "last_match": {"result": "WIN", "kda": "8/2/5"}},
    ]
}

# Who actually owns the pixel at a control's own centre. Returns a row
# per matched control so a red run names every broken one, not just the
# first.
_HIT_AT_OWN_CENTRE_JS = r"""
(sel) => Array.from(document.querySelectorAll(sel)).map((el) => {
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(
    r.left + r.width / 2, r.top + r.height / 2);
  return {
    action: (el.dataset && el.dataset.action) || '',
    idx: (el.dataset && el.dataset.idx) || '',
    disabled: !!el.disabled,
    rect: {x: Math.round(r.left), y: Math.round(r.top),
           w: Math.round(r.width), h: Math.round(r.height)},
    ownsCentre: !!(hit && (hit === el || el.contains(hit))),
    hitBy: hit
      ? (hit.tagName + '.' + String(hit.className || '') +
         '[' + ((hit.dataset && hit.dataset.action) || '') + ':' +
         ((hit.dataset && hit.dataset.idx) || '') + ']')
      : 'null',
  };
})
"""

# Every element in the rendered page whose ::before / ::after is an
# absolutely positioned box BIGGER than the element itself - i.e. the
# oversized hit-target overlay idiom, found by measurement rather than by
# a hand-kept selector list - plus who owns that element's own centre.
_OVERSIZED_OVERLAY_SWEEP_JS = r"""
() => {
  const out = [];
  for (const el of Array.from(document.querySelectorAll('*'))) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.bottom < 0 || r.top > innerHeight) continue;
    if (r.right < 0 || r.left > innerWidth) continue;
    let over = null;
    for (const p of ['::before', '::after']) {
      const cs = getComputedStyle(el, p);
      if (!cs || cs.content === 'none') continue;
      if (cs.position !== 'absolute') continue;
      if (cs.pointerEvents === 'none') continue;
      const w = parseFloat(cs.width), h = parseFloat(cs.height);
      if (!(w > r.width + 1 || h > r.height + 1)) continue;
      over = p + ' ' + Math.round(w) + 'x' + Math.round(h);
      break;
    }
    if (!over) continue;
    const hit = document.elementFromPoint(
      r.left + r.width / 2, r.top + r.height / 2);
    out.push({
      cls: String(el.className || ''),
      action: (el.dataset && el.dataset.action) || '',
      idx: (el.dataset && el.dataset.idx) || '',
      box: Math.round(r.width) + 'x' + Math.round(r.height),
      overlay: over,
      ownsCentre: !!(hit && (hit === el || el.contains(hit))),
      hitBy: hit ? (hit.tagName + '.' + String(hit.className || '')) : 'null',
    });
  }
  return out;
}
"""

# How far, in whole pixels, elementFromPoint still resolves to a control
# (or a descendant) walking outward from its own centre along each axis.
# This is the EFFECTIVE hit target, which is the quantity the audit floor
# is about - the CSS box is not.
_EFFECTIVE_EXTENT_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const owns = (x, y) => {
    const h = document.elementFromPoint(x, y);
    return !!(h && (h === el || el.contains(h)));
  };
  if (!owns(cx, cy)) return {ownsCentre: false};
  const walk = (dx, dy) => {
    let n = 0;
    for (let i = 1; i <= 120; i++) {
      if (!owns(cx + dx * i, cy + dy * i)) break;
      n = i;
    }
    return n;
  };
  const left = walk(-1, 0), right = walk(1, 0);
  const up = walk(0, -1), down = walk(0, 1);
  return {
    ownsCentre: true,
    left: left, right: right, up: up, down: down,
    width: left + right + 1, height: up + down + 1,
  };
}
"""


def _open_top8(mock_server, pw_browser):
    """Lobby view with a 3-entry Top 8, a live party roster and a
    populated YOUR MAINS list - every panel that carries an oversized
    hit-target overlay, rendered at once."""
    lcu = copy.deepcopy(_POLL_LCU)
    lcu["main_champs"] = _MAIN_CHAMPS
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, top8=_TOP8_SEED, poll=True,
        ui_mock=False, lcu=lcu,
    )
    page.wait_for_function(
        "document.querySelectorAll("
        "'#lv-top8-list .lv-top8-reorder-btn').length >= 6",
        timeout=15_000,
    )
    page.wait_for_function(
        "document.querySelectorAll('.lv-mc-copy').length >= 3",
        timeout=15_000,
    )
    return ctx, page, errors


def _fmt(rows):
    return "\n".join(
        "    {action}[idx={idx}] box={rect} ownsCentre={own} hitBy={by}"
        .format(action=r["action"] or "-", idx=r["idx"] or "-",
                rect=r["rect"], own=r["ownsCentre"], by=r["hitBy"])
        for r in rows
    )


# --------------------------------------------------------------------
# The defect itself - both halves.
# --------------------------------------------------------------------
def test_top8_up_control_owns_its_own_hit_target(mock_server, pw_browser):
    """RED at HEAD. Each `up` chevron must be the element under its own
    centre; at HEAD the sibling `down` overlay owns all three."""
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        rows = page.evaluate(
            _HIT_AT_OWN_CENTRE_JS,
            "#lv-top8-list .lv-top8-reorder-btn[data-action=\"up\"]",
        )
        assert len(rows) == 3, f"expected 3 up controls, got {len(rows)}"
        dead = [r for r in rows if not r["ownsCentre"]]
        assert not dead, (
            f"{len(dead)} of {len(rows)} Top-8 `up` controls are dead to "
            "the mouse - elementFromPoint at their own centre returns a "
            "different element:\n" + _fmt(rows)
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 up hit target]: {errors[:3]}"


def test_top8_down_control_owns_its_own_hit_target(mock_server, pw_browser):
    """GREEN at HEAD, and load-bearing.

    `down` is the control that currently WINS the overlap. Pinning it
    here is what stops the cheap non-fix: raising `up` above `down` with
    a z-index would satisfy the sibling test and simply move the dead
    control, which this catches."""
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        rows = page.evaluate(
            _HIT_AT_OWN_CENTRE_JS,
            "#lv-top8-list .lv-top8-reorder-btn[data-action=\"down\"]",
        )
        assert len(rows) == 3, f"expected 3 down controls, got {len(rows)}"
        dead = [r for r in rows if not r["ownsCentre"]]
        assert not dead, (
            f"{len(dead)} of {len(rows)} Top-8 `down` controls are dead to "
            "the mouse - the reorder overlap was inverted, not "
            "removed:\n" + _fmt(rows)
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 down hit target]: {errors[:3]}"


def test_top8_reorder_overlay_does_not_reach_its_sibling(
    mock_server, pw_browser
):
    """The overlays must stop before the sibling control, not merely
    spare its centre pixel.

    Owning your own centre is necessary but not sufficient - an overlay
    could swallow all but the exact centre of its sibling and the two
    tests above would still pass. So assert the stronger property: at no
    point inside the other chevron's box does hit testing resolve to
    this one.

    The scan is INSET by 3px at each end of the sibling box, and that
    inset is measured, not defensive padding. On the boundary rows
    between the two stacked controls - y 442 and 443 of an `up` box
    spanning [429,443) - document.elementFromPoint and
    document.elementsFromPoint DISAGREE in this Chromium build: the
    singular API reports `down` while the plural API reports `up` and
    then the .lv-top8-reorder gap, and the two agree on every other
    pixel of the column (measured 2026-09-04 over y 425-470). A
    per-pixel assertion right at the seam would therefore pin a platform
    hit-test rounding artefact rather than the defect. 3px clears the
    measured 2px band with a pixel to spare and still covers the middle
    8px of each 14px control - at HEAD the losing chevron owns NONE of
    its own box, centre included, so the inset costs the assertion no
    power."""
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        bad = page.evaluate(r"""
        (inset) => {
          const out = [];
          const stacks = Array.from(document.querySelectorAll(
            '#lv-top8-list .lv-top8-reorder'));
          stacks.forEach((stack, i) => {
            const up = stack.querySelector('[data-action="up"]');
            const dn = stack.querySelector('[data-action="down"]');
            if (!up || !dn) { out.push('row ' + i + ': missing pair');
                              return; }
            [[up, dn, 'up'], [dn, up, 'down']].forEach(([a, b, name]) => {
              const rb = b.getBoundingClientRect();
              const cx = rb.left + rb.width / 2;
              const lo = Math.ceil(rb.top) + inset;
              const hi = rb.bottom - inset;
              for (let y = lo; y < hi; y++) {
                const h = document.elementFromPoint(cx, y);
                if (h && (h === a || a.contains(h))) {
                  out.push('row ' + i + ': `' + name + '` owns pixel y=' +
                           y + ' inside the sibling box [' +
                           Math.round(rb.top) + ',' +
                           Math.round(rb.bottom) + ')');
                  break;
                }
              }
            });
          });
          return out;
        }
        """, 3)
        assert bad == [], (
            "a reorder overlay still reaches into the sibling control box: " +
            str(bad)
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 reorder seam]: {errors[:3]}"


def test_top8_reorder_keeps_an_enlarged_hit_target(mock_server, pw_browser):
    """The fix must not be "delete the overlay".

    The overlay is a deliberate hit-target floor, so removing it trades
    one audit defect for another. Assert the MEASURED effective target
    of each chevron is materially larger than its 26x14 visible box:
    wider than 26px horizontally (the overlay's whole point) and taller
    than the 14px box vertically.

    MEASURED after the fix by walking elementFromPoint out from each
    control's own centre: `up` 41x21, `down` 41x22 (41 rather than the
    CSS 44 because the last 3px on the right belong to the `remove`
    overlay, which is later in DOM order). Before the fix `up` measured
    nothing at all - it did not own even its own centre. The floors
    below sit under those numbers rather than on them, so a small
    layout shift does not turn this into a brittle pin."""
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        got = {}
        for name in ("up", "down"):
            got[name] = page.evaluate(
                _EFFECTIVE_EXTENT_JS,
                "#lv-top8-list .lv-top8-reorder-btn"
                f"[data-action=\"{name}\"][data-idx=\"1\"]",
            )
        for name, ext in got.items():
            assert ext and ext.get("ownsCentre"), (
                f"`{name}` does not own its own centre: {ext!r}"
            )
            assert ext["width"] >= 36, (
                f"`{name}` effective hit width collapsed to "
                f"{ext['width']}px (visible box is 26px) - the "
                f"horizontal expansion was lost: {ext!r}"
            )
            assert ext["height"] >= 18, (
                f"`{name}` effective hit height is {ext['height']}px, "
                "no better than the 14px visible box - the overlay was "
                f"deleted rather than bounded: {ext!r}"
            )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 reorder extent]: {errors[:3]}"


# --------------------------------------------------------------------
# Root-cause sweep - every oversized overlay on the page, not a list.
# --------------------------------------------------------------------
def test_no_oversized_overlay_covers_a_neighbour(mock_server, pw_browser):
    """Generalised RM-338: any element carrying an absolutely positioned
    ::before / ::after larger than itself must still be the element
    under its own centre.

    Selector-free by construction, so a future overlay is covered the
    day it is added. The count floor keeps it from passing vacuously if
    a render regression empties the panels."""
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        rows = page.evaluate(_OVERSIZED_OVERLAY_SWEEP_JS)
        assert len(rows) >= 20, (
            "oversized-overlay sweep found only "
            f"{len(rows)} controls - the lobby panels did not render, so "
            "this assertion would be vacuous: " + str(rows[:5])
        )
        dead = [r for r in rows if not r["ownsCentre"]]
        assert not dead, (
            f"{len(dead)} of {len(rows)} controls with an oversized "
            "hit-target overlay are covered by a neighbour:\n" +
            "\n".join("    " + str(r) for r in dead)
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [overlay sweep]: {errors[:3]}"


def test_lv_fr_overlay_ruleset_still_has_no_markup():
    """Tripwire for the one sibling site that could not be measured.

    header.css carries the same 44x44 ::before idiom on .lv-fr-copy /
    .lv-fr-invite - two 24x24 buttons in ADJACENT 28px grid columns of
    .lv-fr-row, which is the horizontal form of exactly this defect.
    MEASURED 2026-09-04: nothing in web/ ever emits those classes, so
    zero elements exist and the rules are unreachable. They are left
    untouched rather than "fixed" blind.

    If someone wires the friends row up, this goes red and points them
    at the measurement instead of letting a second dead control ship."""
    producers = []
    for path in sorted(WEB.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".js", ".html", ".json", ".mjs"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if "lv-fr-copy" in text or "lv-fr-invite" in text:
            producers.append(str(path.relative_to(ROOT)))
    assert producers == [], (
        "web/ now emits .lv-fr-copy / .lv-fr-invite markup (" +
        ", ".join(producers) + "). Those rules still carry the RM-338 "
        "44x44 ::before overlay on 24x24 buttons that sit ~34px apart "
        "in adjacent grid columns. Measure the hit targets with "
        "document.elementFromPoint and bound the overlay in the "
        "horizontal axis before shipping the markup."
    )


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in this
    slice's authored test file.

    Deliberately NOT extended to header.css: that file predates the rule
    and already carries 9 non-ASCII bytes (a U+2715 glyph in a `content`
    string among them), so asserting over the whole stylesheet would be
    a pre-existing red rather than a guard on this slice. The ASCII of
    the CSS lines this slice adds is checked against the diff, not the
    file."""
    raw = Path(__file__).read_bytes()
    offenders = sorted({b for b in raw if b > 0x7F})
    assert not offenders, f"non-ASCII byte(s) in {__file__}: {offenders[:5]}"
