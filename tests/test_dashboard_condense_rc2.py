"""Tests for web/js/lib/condense.js - RC2 Phase 3.6 dashboard condensation.

3.6 is the DASHBOARD counterpart to the overlay condensation (3.1-3.3). The
full :8888 view keeps its density (it is NOT the 460px HUD), but the PRIMARY
coaching panels (RIGHT NOW, NEXT) render fixed supporting KV rows that paint
the "-" no-data sentinel in client / pregame / ARAM / aftergame states - a
dead-dash wall under the live headline. condense.js collapses those empty rows
(the same move STATS already makes via right_now.js _hideEmptyStatRows) so the
glance lands on the rows that carry a value.

Mirrors tests/test_overlay_priority_rc2.py: node require()s the CJS export and
pins the pure decision contract; condenseKvRows is exercised against a tiny
hand-rolled DOM stub (jsdom/playwright are absent on CI). A second grep-style
class confirms right_now.js / next.js import and call the helper.

Skips cleanly when node is unavailable so it never hard-fails CI on a runner
without a JS toolchain (the helper ships as static JS).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONDENSE_JS = REPO_ROOT / "web" / "js" / "lib" / "condense.js"
RIGHT_NOW_JS = REPO_ROOT / "web" / "js" / "panels" / "right_now.js"
NEXT_JS = REPO_ROOT / "web" / "js" / "panels" / "next.js"
NODE = shutil.which("node")

# A tiny hand-rolled DOM stub so condenseKvRows can be exercised in node with
# no jsdom. A KV row = {style, querySelectorAll('span')->[keySpan, valSpan]};
# the root's querySelectorAll('.kv') returns the row list.
_DOM_STUB = """
function mkRow(keyText, valText) {
  const keySpan = { textContent: keyText };
  const valSpan = { textContent: valText };
  return {
    style: { display: '' },
    querySelectorAll: function (sel) { return [keySpan, valSpan]; },
  };
}
function mkRoot(rows) {
  return {
    querySelectorAll: function (sel) { return sel === '.kv' ? rows : []; },
  };
}
"""


def _run_js(snippet: str) -> str:
    require_path = CONDENSE_JS.as_posix()
    program = (
        f"const {{ EMPTY_SENTINELS, isEmptyValue, planKvCondense, "
        f"condenseKvRows }} = require({json.dumps(require_path)});\n"
        f"{_DOM_STUB}\n{snippet}\n"
    )
    proc = subprocess.run(
        [NODE, "-e", program],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        )
    return proc.stdout.strip()


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class CondenseLogicTest(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(CONDENSE_JS.is_file(), f"missing {CONDENSE_JS}")

    def test_exports_present(self):
        out = _run_js(
            "console.log(JSON.stringify("
            "[typeof EMPTY_SENTINELS, typeof isEmptyValue, "
            "typeof planKvCondense, typeof condenseKvRows]));"
        )
        self.assertEqual(
            json.loads(out), ["object", "function", "function", "function"]
        )

    # ----- isEmptyValue: the single decision -----
    def _empty(self, text) -> bool:
        out = _run_js(
            "console.log(JSON.stringify(isEmptyValue(" + json.dumps(text) + ")));"
        )
        return json.loads(out)

    def test_dash_is_empty(self):
        self.assertTrue(self._empty("-"))

    def test_blank_is_empty(self):
        self.assertTrue(self._empty(""))

    def test_dash_pair_is_empty(self):
        self.assertTrue(self._empty("- / -"))

    def test_whitespace_dash_trimmed_is_empty(self):
        self.assertTrue(self._empty("  -  "))

    def test_null_is_empty(self):
        out = _run_js("console.log(JSON.stringify(isEmptyValue(null)));")
        self.assertTrue(json.loads(out))

    def test_real_value_not_empty(self):
        self.assertFalse(self._empty("FOCUS Zed - he has no flash"))

    def test_zero_is_not_empty(self):
        # "0" is a real value (e.g. 0 deaths), never a no-data sentinel.
        self.assertFalse(self._empty("0"))

    def test_custom_sentinels_respected(self):
        out = _run_js(
            "console.log(JSON.stringify(isEmptyValue('n/a', ['n/a'])));"
        )
        self.assertTrue(json.loads(out))

    # ----- planKvCondense: pure parallel hide-plan -----
    def test_plan_maps_values(self):
        out = _run_js(
            "console.log(JSON.stringify(planKvCondense("
            "['-', 'TRADE now', '', 'B']))); "
        )
        self.assertEqual(json.loads(out), [True, False, True, False])

    def test_plan_non_array_is_empty(self):
        out = _run_js("console.log(JSON.stringify(planKvCondense(null)));")
        self.assertEqual(json.loads(out), [])

    # ----- condenseKvRows: DOM pass against the stub -----
    def test_condense_hides_empty_shows_full(self):
        out = _run_js(
            "const rows = [mkRow('Watch', '-'), mkRow('Fight', 'group only'), "
            "mkRow('Base', 'Dark Seal (950g)')];\n"
            "const res = condenseKvRows(mkRoot(rows));\n"
            "console.log(JSON.stringify({res: res, "
            "d: rows.map(r => r.style.display)}));"
        )
        data = json.loads(out)
        self.assertEqual(data["res"], {"visible": 2, "hidden": 1})
        self.assertEqual(data["d"], ["none", "", ""])

    def test_condense_all_empty(self):
        out = _run_js(
            "const rows = [mkRow('Watch', '-'), mkRow('Fight', ''), "
            "mkRow('Base', '- / -')];\n"
            "const res = condenseKvRows(mkRoot(rows));\n"
            "console.log(JSON.stringify({res: res, "
            "d: rows.map(r => r.style.display)}));"
        )
        data = json.loads(out)
        self.assertEqual(data["res"], {"visible": 0, "hidden": 3})
        self.assertEqual(data["d"], ["none", "none", "none"])

    def test_condense_idempotent_reveals_on_relatch(self):
        # A row hidden one tick must re-show the tick its value latches.
        out = _run_js(
            "const r = mkRow('Watch', '-');\n"
            "condenseKvRows(mkRoot([r]));\n"
            "const d1 = r.style.display;\n"
            "r.querySelectorAll('span')[1].textContent = 'WARD river';\n"
            "condenseKvRows(mkRoot([r]));\n"
            "console.log(JSON.stringify([d1, r.style.display]));"
        )
        self.assertEqual(json.loads(out), ["none", ""])

    def test_condense_null_root_safe(self):
        out = _run_js(
            "console.log(JSON.stringify(condenseKvRows(null)));"
        )
        self.assertEqual(json.loads(out), {"visible": 0, "hidden": 0})

    def test_condense_no_kv_rows_safe(self):
        out = _run_js(
            "console.log(JSON.stringify(condenseKvRows(mkRoot([]))));"
        )
        self.assertEqual(json.loads(out), {"visible": 0, "hidden": 0})


@unittest.skipUnless(NODE, "node not on PATH")
class CondenseWiringTest(unittest.TestCase):
    """The primary coaching panels must import + call the shared helper so the
    dash-wall collapse actually runs on the dashboard surface."""

    def test_right_now_wires_condense(self):
        js = RIGHT_NOW_JS.read_text(encoding="utf-8")
        self.assertIn("condense.js", js)
        self.assertIn("condenseKvRows", js)

    def test_next_wires_condense(self):
        js = NEXT_JS.read_text(encoding="utf-8")
        self.assertIn("condense.js", js)
        self.assertIn("condenseKvRows", js)

    def test_condense_js_is_ascii(self):
        raw = CONDENSE_JS.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as e:  # pragma: no cover
            self.fail(f"condense.js has non-ASCII byte: {e}")


if __name__ == "__main__":
    unittest.main()
