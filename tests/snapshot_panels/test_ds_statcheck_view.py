"""
tests/snapshot_panels/test_ds_statcheck_view.py
DS stat-sandbox panel (#csv-ds-statcheck) 5-phase fixture-audit guard +
populated VISUAL capture (R26, 2026-06-23).

ds_statcheck (web/js/panels/ds_statcheck.js, competitor lift #5) is a
champ-select central-pane panel: the operator edits the TARGET (enemy)
armor / MR / HP / bonus-HP knobs and the panel shows the resolved champion
stat block + the engine DPS vs that what-if target. It shipped WITHOUT the
5-phase fixture audit, so it carried two findings the audit corrects:

  - HIT-TARGETS (MUST-FIX): the 4 editable number inputs rendered ~21px tall
    (4px+6px padding, 13px text) - half the --hit-min 42px every audited
    input (Settings / User-Builds worked examples) enforces.
  - TYPOGRAPHY (cluster-consistency): the panel used --fs-2xs (13px) for 7
    label / metadata elements while every sibling DS panel in the SAME
    central pane (ds_knobs / ds_profile / ds_relscore / cc_pairing) uses
    --fs-xs (16px) / --fs-sm (18px) and zero --fs-2xs. The audit lifts the
    7 usages to --fs-xs so the panel reads at the cluster baseline.

The champ_select_* ui_mock fixtures do not lock my_champion (the accessor
the panel gates on), so - mirroring test_ds_relscore_view.py - we drive the
real renderDsStatcheck directly against the live #csv-ds-statcheck mount with
a synthetic locked champ and a stubbed /api/ds-statcheck payload (everything
else passes through to the mock server), then assert the populated structure
+ the two audit fixes (input hit-height + readable font), and screenshot the
rendered panel.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Deterministic /api/ds-statcheck payload - all 10 _STAT_ROWS keys present so
# the full stat block renders (ap:0 is non-null -> the row still paints).
_STATCHECK_STUB = """
(function () {
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/ds-statcheck') >= 0) {
      const body = {
        ok: true, champion: 'Jinx',
        dps: 412.5, phase: 'mid',
        stats: {
          ad: 110.0, attack_speed: 1.25, crit_chance: 0.5, ap: 0.0,
          hp: 1850.0, armor: 55.0, mr: 38.0, avg_attack_dmg: 95.0,
          raw_attack_dps: 380.0, per_attack_on_hit_damage: 15.0
        },
        inputs: {
          target_armor: 95, target_mr: 63, target_hp: 0, target_bonus_hp: 0,
          level: 11, mode: 'SR', armor_source: 'auto', mr_source: 'auto'
        },
        count: 1
      };
      return Promise.resolve(new Response(
        JSON.stringify(body),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      ));
    }
    return _f.apply(this, arguments);
  };
})();
"""


def test_ds_statcheck_panel_populated(mock_server, pw_browser):
    """Render the panel populated and assert the audited structure + the two
    fixture-audit fixes (hit-target input height + readable font). RED before
    the ds_statcheck.css audit (inputs ~21px tall, 13px font)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_STATCHECK_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # ds_statcheck stays on champ-select (champ_select.js: "ds-statcheck stay
    # on champ-select for the pick"); the #champ-select hash is honored by the
    # view router even with empty SSE state (mirrors the sibling precedents).
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
        wait_until="domcontentloaded", timeout=15_000,
    )

    # Wait for the champion index so resolveChampNames([222]) -> 'Jinx'
    # (the panel hides until the locked champ resolves to a name).
    page.wait_for_function(
        """async () => {
          try {
            const m = await import('/js/panels/cc_conditional_pressure.js');
            const n = m.resolveChampNames ? m.resolveChampNames([222]) : [];
            return !!(n && n.length && n[0]);
          } catch (e) { return false; }
        }""",
        timeout=10_000,
    )

    # Render the real panel into its live mount with a synthetic locked champ;
    # the stubbed /api/ds-statcheck lands and paints the readout.
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/ds_statcheck.js');
          if (m._resetDsStatcheck) m._resetDsStatcheck();
          const el = document.getElementById('csv-ds-statcheck');
          m.renderDsStatcheck(el, { my_champion: 222, queue_id: 420 });
        }"""
    )

    # Wait for the fetch onLand re-render: the DPS hero value + the stat rows.
    page.wait_for_function(
        "document.querySelector('#csv-ds-statcheck .dss-dps-value') && "
        "document.querySelectorAll('#csv-ds-statcheck .dss-row').length >= 10",
        timeout=10_000,
    )

    try:
        block = page.locator("#csv-ds-statcheck")
        assert block.is_visible(), "#csv-ds-statcheck not visible after render"

        # STRUCTURE: title + 4 editable knobs + DPS hero + full stat block.
        assert page.locator("#csv-ds-statcheck .dss-title").inner_text().strip() == (
            "Stat Sandbox"
        ), "panel title"
        assert page.locator("#csv-ds-statcheck .dss-knob input").count() == 4, (
            "expected 4 editable target knobs"
        )
        assert page.locator("#csv-ds-statcheck .dss-dps-value").inner_text().strip() == (
            "412.5"
        ), "DPS hero value"
        assert page.locator("#csv-ds-statcheck .dss-row").count() == 10, (
            "expected the full 10-row stat block"
        )

        # HIT-TARGETS (MUST-FIX): every editable input clears the --hit-min
        # 42px floor. RED before the css audit (inputs rendered ~21px).
        heights = page.eval_on_selector_all(
            "#csv-ds-statcheck .dss-knob input",
            "els => els.map(e => e.getBoundingClientRect().height)",
        )
        assert heights and all(h >= 42 for h in heights), (
            f"editable inputs below the --hit-min 42px floor: {heights}"
        )

        # TYPOGRAPHY: the editable input text + a representative metadata label
        # clear the cluster --fs-xs (16px) baseline. RED before the audit (13px).
        in_fs = page.eval_on_selector(
            "#csv-ds-statcheck .dss-knob input",
            "e => parseFloat(getComputedStyle(e).fontSize)",
        )
        assert in_fs >= 16, f"input font below the 16px cluster baseline: {in_fs}"
        name_fs = page.eval_on_selector(
            "#csv-ds-statcheck .dss-name",
            "e => parseFloat(getComputedStyle(e).fontSize)",
        )
        assert name_fs >= 16, f"stat-row label below the 16px baseline: {name_fs}"

        SCREENSHOTS.mkdir(exist_ok=True)
        block.screenshot(path=str(SCREENSHOTS / "ds-statcheck_panel.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
