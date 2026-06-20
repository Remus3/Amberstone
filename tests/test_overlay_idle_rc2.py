"""Tests for web/js/lib/overlay_idle.js - RC2 Phase 4.2 overlay auto-hide.

The non-intrusive overlay recedes when nothing is happening: after no coach
content change AND no pointer activity for ~8s the renderer stamps
data-rc-idle="1" on the body and overlay.css drops the dock to a low opacity;
any coach change or hover snaps it back to full. A hard hide mid-game would
remove coaching, so 4.2's "auto-hide" is an opacity recede, not display:none.

Mirrors tests/test_dashboard_condense_rc2.py: node require()s the CJS export
and pins the pure decision (isIdle + planIdle) plus the DOM apply
(applyIdleAttr) against a tiny hand-rolled stub (jsdom/playwright absent on CI).
A second class greps the wiring (main.js init + overlay.css idle rule) and ASCII.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IDLE_JS = REPO_ROOT / "web" / "js" / "lib" / "overlay_idle.js"
MAIN_JS = REPO_ROOT / "web" / "js" / "main.js"
OVERLAY_CSS = REPO_ROOT / "web" / "css" / "overlay.css"
NODE = shutil.which("node")

# Minimal body stub: setAttribute / removeAttribute / getAttribute over a dict.
_DOM_STUB = """
function mkBody() {
  return {
    _a: {},
    setAttribute: function (k, v) { this._a[k] = String(v); },
    removeAttribute: function (k) { delete this._a[k]; },
    getAttribute: function (k) { return k in this._a ? this._a[k] : null; },
  };
}
"""


def _run_js(snippet: str) -> str:
    require_path = IDLE_JS.as_posix()
    program = (
        f"const {{ IDLE_ATTR, IDLE_DELAY_MS, isIdle, planIdle, applyIdleAttr }} "
        f"= require({json.dumps(require_path)});\n"
        f"{_DOM_STUB}\n{snippet}\n"
    )
    proc = subprocess.run(
        [NODE, "-e", program], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        )
    return proc.stdout.strip()


@unittest.skipUnless(NODE, "node not on PATH - JS helper is static, skip")
class OverlayIdleLogicTest(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(IDLE_JS.is_file(), f"missing {IDLE_JS}")

    def test_exports_present(self):
        out = _run_js(
            "console.log(JSON.stringify("
            "[typeof IDLE_ATTR, typeof IDLE_DELAY_MS, typeof isIdle, "
            "typeof planIdle, typeof applyIdleAttr]));"
        )
        self.assertEqual(
            json.loads(out),
            ["string", "number", "function", "function", "function"],
        )

    def test_idle_attr_name(self):
        out = _run_js("console.log(IDLE_ATTR);")
        self.assertEqual(out, "data-rc-idle")

    # ----- isIdle: the single decision -----
    def test_not_idle_before_delay(self):
        # last=1000, now=1000+5000, delay=8000 -> not idle
        out = _run_js("console.log(JSON.stringify(isIdle(1000, 6000, 8000)));")
        self.assertFalse(json.loads(out))

    def test_idle_after_delay(self):
        out = _run_js("console.log(JSON.stringify(isIdle(1000, 9001, 8000)));")
        self.assertTrue(json.loads(out))

    def test_idle_exact_boundary(self):
        # now - last == delay -> idle (>=)
        out = _run_js("console.log(JSON.stringify(isIdle(1000, 9000, 8000)));")
        self.assertTrue(json.loads(out))

    def test_idle_default_delay_when_garbage(self):
        # non-finite delay falls back to IDLE_DELAY_MS; 999999 since last -> idle
        out = _run_js(
            "console.log(JSON.stringify(isIdle(0, 999999, null)));"
        )
        self.assertTrue(json.loads(out))

    def test_idle_non_finite_last_is_active(self):
        # a never-stamped lastActivity (null) reads as just-active -> not idle
        out = _run_js("console.log(JSON.stringify(isIdle(null, 999999, 8000)));")
        self.assertFalse(json.loads(out))

    # ----- planIdle: pure next-state from prev + now -----
    def test_plan_marks_idle_when_stale(self):
        out = _run_js(
            "console.log(JSON.stringify(planIdle("
            "{lastActivityMs: 1000, idle: false}, 20000, 8000)));"
        )
        data = json.loads(out)
        self.assertTrue(data["idle"])

    def test_plan_stays_active_when_fresh(self):
        out = _run_js(
            "console.log(JSON.stringify(planIdle("
            "{lastActivityMs: 1000, idle: false}, 2000, 8000)));"
        )
        self.assertFalse(json.loads(out)["idle"])

    # ----- applyIdleAttr: DOM pass against the stub -----
    def test_apply_sets_and_clears_attr(self):
        out = _run_js(
            "const b = mkBody();\n"
            "applyIdleAttr(b, true);\n"
            "const on = b.getAttribute(IDLE_ATTR);\n"
            "applyIdleAttr(b, false);\n"
            "const off = b.getAttribute(IDLE_ATTR);\n"
            "console.log(JSON.stringify([on, off]));"
        )
        self.assertEqual(json.loads(out), ["1", None])

    def test_apply_idempotent(self):
        out = _run_js(
            "const b = mkBody();\n"
            "applyIdleAttr(b, true);\n"
            "applyIdleAttr(b, true);\n"
            "console.log(b.getAttribute(IDLE_ATTR));"
        )
        self.assertEqual(out, "1")

    def test_apply_null_body_safe(self):
        out = _run_js("console.log(JSON.stringify(applyIdleAttr(null, true)));")
        self.assertEqual(json.loads(out), False)


@unittest.skipUnless(NODE, "node not on PATH")
class OverlayIdleWiringTest(unittest.TestCase):
    def test_main_inits_overlay_idle(self):
        js = MAIN_JS.read_text(encoding="utf-8")
        self.assertIn("overlay_idle.js", js)
        self.assertIn("initOverlayIdle", js)

    def test_overlay_css_has_idle_rule(self):
        css = OVERLAY_CSS.read_text(encoding="utf-8")
        self.assertIn("data-rc-idle", css)

    def test_idle_js_is_ascii(self):
        raw = IDLE_JS.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as e:  # pragma: no cover
            self.fail(f"overlay_idle.js has non-ASCII byte: {e}")


if __name__ == "__main__":
    unittest.main()
