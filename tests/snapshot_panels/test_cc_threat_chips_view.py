"""
tests/snapshot_panels/test_cc_threat_chips_view.py
CC threat chips (cc-blended-ehp-threat + cc-conditional-pressure) VISUAL
snapshot + grid-compliance coverage (R29, 2026-06-23).

The two CC chips (item 139 carry (a) + item 144) stack ADJACENT in the
champ-select My-Pick card and mirror each other (the conditional chip's
data-cc-cond-tier mirrors the blended chip's data-cc-tier). Both shipped
PRE the docs/UI_SCALE_SPEC_V2.md 8-px grid sweep with hardcoded off-grid
spacing (gap 6px, padding 6px 8px, badge padding 1px 5px) + raw 4px card +
3px badge radii. The R29 UI-audit cycle swept BOTH onto the grid
(--space-*) + --panel-radius-sm token, atomically (sweeping one and not its
adjacent mirror would leave the two chips visibly grid-inconsistent in one
card). This is the RED-first guard for that sweep: it asserts the computed
card + badge radius == 10px and the head gap == 8px, which FAIL RED at the
pre-sweep 4px / 3px / 6px and PASS GREEN after.

HOST CANVAS: the chips are class-based (their computed radius/gap come from
the .cc-blended-ehp-threat / .cc-conditional-pressure rules, NOT from the
host view), so we render them into the Active-Match view, NOT champ-select.
The live champ-select render loop re-invokes the per-chip renderers on its
own schedule with the empty (no-champions) real payload and re-HIDES the
chips (the documented counter-box re-render race), which would clobber any
direct render into the champ-select pane. The Active-Match view is the
proven render-quiet, reliably-visible canvas (it settles to InProgress, then
the WS is stubbed - no further state ticks), exactly like the spike_markers
and ds_relscore view-snapshots; the chips' computed CSS is host-independent.

Both renderers take the backend payload DIRECTLY (no fetch) and expose a
_reset*() that clears the sig-dedup cache, so after the host settles we drive
the real renderers into freshly-created production mounts with deterministic
AT-RISK payloads (the LAST DOM write), then assert structure + grid tokens +
the display-only invariant (no interactive elements) + screenshot.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Deterministic AT-RISK (tier=bad) payloads: enemy out-chains ally on both
# chips, so both render the bad-tier accent + the 2 per-side rows + verdict.
_BLENDED_PAYLOAD = {
    "ok": True,
    "tier": "bad",
    "ally_avg_cc_blended_ehp": 2400,
    "enemy_avg_cc_blended_ehp": 2100,
    "ally_total_cc_seconds": 1.5,
    "enemy_total_cc_seconds": 3.0,
}
_CONDITIONAL_PAYLOAD = {
    "ok": True,
    "tier": "bad",
    "ally_total_cc_seconds": 1.2,
    "enemy_total_cc_seconds": 2.8,
}

# One evaluate that builds BOTH production mounts under the settled, visible
# Active-Match view and drives the real renderers (payload-direct, no fetch).
# _reset* clears the sig-dedup cache so the first render paints; the renderer
# sets hidden=false on the ok path (we pre-clear it defensively).
_DRIVE = """
async (p) => {
  const view = document.getElementById('view-active-match');
  function mk(id, cls, attr, val) {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      el.className = cls;
      el.setAttribute(attr, val);
      el.hidden = true;
      view.appendChild(el);
    } else if (!view.contains(el)) {
      // QA 2026-07-03 slice A (B8/B9): the production mounts now live
      // statically inside the champ-select TEAM ANALYSIS cluster (a
      // hidden section on #active-match). Re-parent the mount under the
      // visible Active-Match view so the rendered chips are laid out +
      // screenshot-able, exactly like the pre-QA synthetic mounts.
      view.appendChild(el);
    }
    return el;
  }
  const b = mk('csv-sugg-cc-blended-ehp-threat',
              'cc-blended-ehp-threat', 'data-cc-tier', 'warn');
  const c = mk('csv-sugg-cc-conditional-pressure',
              'cc-conditional-pressure', 'data-cc-cond-tier', 'warn');
  const mB = await import('/js/panels/cc_blended_ehp_threat.js');
  const mC = await import('/js/panels/cc_conditional_pressure.js');
  if (mB._resetCcBlendedEhpThreat) mB._resetCcBlendedEhpThreat();
  if (mC._resetCcConditionalPressure) mC._resetCcConditionalPressure();
  b.hidden = false; c.hidden = false;
  mB.renderCcBlendedEhpThreat(b, p.blended);
  mC.renderCcConditionalPressure(c, p.conditional);
}
"""


def test_cc_threat_chips_render(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # #active-match makes #view-active-match the active, laid-out, render-quiet
    # host view so the rendered chips are visible + screenshot-able.
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    # Let the one-shot active-match mock render settle FIRST (same gate as the
    # spike_markers snapshot): once #am-sub reads InProgress, that pass is done,
    # the WS is stubbed (no further ticks), and our render below is the LAST DOM
    # write - nothing clobbers the appended chips.
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )

    page.evaluate(
        _DRIVE, {"blended": _BLENDED_PAYLOAD, "conditional": _CONDITIONAL_PAYLOAD}
    )

    page.wait_for_function(
        "document.querySelectorAll("
        "'#csv-sugg-cc-blended-ehp-threat .cc-blended-ehp-threat-row').length === 2"
        " && document.querySelectorAll("
        "'#csv-sugg-cc-conditional-pressure .cc-conditional-pressure-row').length === 2",
        timeout=10_000,
    )

    try:
        blended = page.locator("#csv-sugg-cc-blended-ehp-threat")
        conditional = page.locator("#csv-sugg-cc-conditional-pressure")
        assert blended.is_visible(), "blended chip not visible after render"
        assert conditional.is_visible(), "conditional chip not visible after render"

        # Structure: tier attr + head + 2 rows + verdict + AT-RISK badge.
        b_tier = page.eval_on_selector(
            "#csv-sugg-cc-blended-ehp-threat", "el => el.dataset.ccTier"
        )
        assert b_tier == "bad", f"blended data-cc-tier != bad: {b_tier!r}"
        c_tier = page.eval_on_selector(
            "#csv-sugg-cc-conditional-pressure", "el => el.dataset.ccCondTier"
        )
        assert c_tier == "bad", f"conditional data-cc-cond-tier != bad: {c_tier!r}"
        b_badge = page.eval_on_selector(
            "#csv-sugg-cc-blended-ehp-threat .cc-blended-ehp-threat-tier",
            "el => el.textContent.trim()",
        )
        assert b_badge == "AT RISK", f"blended badge != AT RISK: {b_badge!r}"
        c_badge = page.eval_on_selector(
            "#csv-sugg-cc-conditional-pressure .cc-conditional-pressure-tier",
            "el => el.textContent.trim()",
        )
        assert c_badge == "AT RISK", f"conditional badge != AT RISK: {c_badge!r}"
        for sel, cls in (
            ("#csv-sugg-cc-blended-ehp-threat", "cc-blended-ehp-threat"),
            ("#csv-sugg-cc-conditional-pressure", "cc-conditional-pressure"),
        ):
            verdicts = page.eval_on_selector_all(
                f"{sel} .{cls}-verdict", "els => els.length"
            )
            assert verdicts == 1, f"{cls}: expected 1 verdict line, got {verdicts}"

        # Display-only invariant: NO interactive elements in either chip (these
        # are pure read-out chips, so --hit-min deliberately does NOT apply).
        for sel in (
            "#csv-sugg-cc-blended-ehp-threat",
            "#csv-sugg-cc-conditional-pressure",
        ):
            interactive = page.eval_on_selector(
                sel,
                "el => el.querySelectorAll('button,input,select,textarea,a').length",
            )
            assert interactive == 0, f"{sel}: display-only chip has {interactive} controls"

        # Grid-compliance teeth (RED before the R29 sweep, GREEN after):
        #   card radius -> --panel-radius-sm (10px), was raw 4px;
        #   badge radius -> --panel-radius-sm (10px), was raw 3px;
        #   head gap -> --space-2 (8px), was off-grid 6px.
        checks = (
            ("#csv-sugg-cc-blended-ehp-threat",
             "borderTopLeftRadius", "10px", "blended card radius"),
            ("#csv-sugg-cc-blended-ehp-threat .cc-blended-ehp-threat-tier",
             "borderTopLeftRadius", "10px", "blended badge radius"),
            ("#csv-sugg-cc-blended-ehp-threat .cc-blended-ehp-threat-head",
             "columnGap", "8px", "blended head gap"),
            ("#csv-sugg-cc-conditional-pressure",
             "borderTopLeftRadius", "10px", "conditional card radius"),
            ("#csv-sugg-cc-conditional-pressure .cc-conditional-pressure-tier",
             "borderTopLeftRadius", "10px", "conditional badge radius"),
            ("#csv-sugg-cc-conditional-pressure .cc-conditional-pressure-head",
             "columnGap", "8px", "conditional head gap"),
        )
        for sel, prop, want, label in checks:
            got = page.eval_on_selector(sel, f"el => getComputedStyle(el).{prop}")
            assert got == want, f"{label} {prop} != {want}: {got}"

        SCREENSHOTS.mkdir(exist_ok=True)
        blended.screenshot(path=str(SCREENSHOTS / "cc-blended-ehp-threat_chip.png"))
        conditional.screenshot(
            path=str(SCREENSHOTS / "cc-conditional-pressure_chip.png")
        )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
