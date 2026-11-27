"""
tests/snapshot_panels/_champ_names.py
Wait until the dashboard's champion index names every given champion id.

s172: the DS panel tests waited with an ASYNC predicate (an `await import()` of
cc_conditional_pressure.js inside page.wait_for_function). wait_for_function
does not await a Promise the predicate returns, and a Promise is truthy, so the
wait returned at once (measured on Playwright 1.59 and 1.65) and every such test
raced the champion index load. Where the index lost the race the panel renders
hidden (renderDsStatcheck hides until the locked champion resolves to a name),
and test_ds_statcheck_champ_rebind_rm196 timed out on its knob input on the CI
runner. This imports the module once, then polls a SYNC predicate.
Guard: tests/test_wait_for_function_sync_predicate_s172.py.
"""

_IMPORT = """async () => {
  const m = await import('/js/panels/cc_conditional_pressure.js');
  window.__rcChampNames = m.resolveChampNames;
}"""

_NAMED = """(ids) => {
  const n = window.__rcChampNames(ids);
  return n.length === ids.length && n.every((s) => !!s);
}"""


def wait_for_champ_names(page, ids, timeout=10_000):
    """Block until resolveChampNames(ids) returns a name for every id."""
    ids = [int(i) for i in ids]
    assert ids, "premise: at least one champion id"
    page.evaluate(_IMPORT)
    page.wait_for_function(_NAMED, arg=ids, timeout=timeout)
