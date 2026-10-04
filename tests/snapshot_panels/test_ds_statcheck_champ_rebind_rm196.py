"""
tests/snapshot_panels/test_ds_statcheck_champ_rebind_rm196.py
RM-196 - the ds_statcheck knob strip bound champId in a closure that was
never rebound, so after a truthy-to-truthy champion change the typed values
were written under the OLD champion's key and silently discarded.

REACHABILITY (settled 2026-10-03, the row's step 1): the active-match mount
(web/js/panels/active_match.js, the `if (!synthetic)` branch above the
`renderDsStatcheck(statcheck, synthetic)` call) only sets `hidden = true`
between games - it never calls renderDsStatcheck with a falsy champion, so
the `!champId` clear path in ds_statcheck.js never runs and the strip
survives from one game's champion into the next. The defect is LIVE.

Drives ONE mount through champ 222 (Jinx) then 22 (Ashe) with NO reset in
between, and asserts the strip re-renders empty for 22 and that an edit
then lands under champion 22 (observed as the knob in 22's fetch URL).
"""

_STUB = """
(function () {
  window.__dssUrls = [];
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/ds-statcheck') >= 0) {
      window.__dssUrls.push(url);
      return Promise.resolve(new Response(
        JSON.stringify({ok: true, dps: 1, stats: {ad: 1}, inputs: {}, count: 1}),
        {status: 200, headers: {'Content-Type': 'application/json'}}));
    }
    return _f.apply(this, arguments);
  };
})();
"""


def _type_armor(page, value):
    page.evaluate(
        """(v) => {
          const inp = document.querySelector(
            '#rm196-dss input[data-knob="target_armor"]');
          inp.value = v;
          inp.dispatchEvent(new Event('input', {bubbles: true}));
        }""",
        value,
    )
    page.wait_for_timeout(600)  # past the 280 ms debounce + re-render


def test_knob_edit_follows_champion_change(mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True,
                                 viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_STUB)
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        """async () => {
          try {
            const m = await import('/js/panels/cc_conditional_pressure.js');
            const n = m.resolveChampNames([222, 22]);
            return !!(n && n.length === 2 && n[0] && n[1]);
          } catch (e) { return false; }
        }""",
        timeout=10_000,
    )
    try:
        page.evaluate(
            """async () => {
              const el = document.createElement('div');
              el.id = 'rm196-dss';
              document.body.appendChild(el);
              const m = await import('/js/panels/ds_statcheck.js');
              m._resetDsStatcheck();
              window.__cs = {my_champion: 222, queue_id: 420};
              m.setDsStatcheckScheduler(
                () => m.renderDsStatcheck(el, window.__cs));
              m.renderDsStatcheck(el, window.__cs);
            }"""
        )
        page.wait_for_selector('#rm196-dss input[data-knob="target_armor"]')
        _type_armor(page, "120")
        urls = page.evaluate("window.__dssUrls")
        assert any("target_armor=120" in u for u in urls), urls

        # Champion change on the SAME mount, no reset, no falsy tick.
        page.evaluate(
            """async () => {
              const m = await import('/js/panels/ds_statcheck.js');
              window.__cs = {my_champion: 22, queue_id: 420};
              window.__dssUrls = [];
              m.renderDsStatcheck(document.getElementById('rm196-dss'),
                                  window.__cs);
            }"""
        )
        val = page.eval_on_selector(
            '#rm196-dss input[data-knob="target_armor"]', "e => e.value")
        assert val == "", f"strip kept champ 222's knob for champ 22: {val!r}"

        _type_armor(page, "80")
        urls = page.evaluate("window.__dssUrls")
        ashe = [u for u in urls if "target_armor=80" in u]
        assert ashe, f"edit for champ 22 never reached its fetch: {urls}"
        assert all("target_armor=120" not in u for u in urls), urls
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
