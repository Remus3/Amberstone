"""Tests for web/js/lib/status.js - the RC2 B1 threshold->status helper.

The helper is vanilla JS (Grafana-style threshold model) consumed by the
dashboard as an ES module. This characterization suite drives node to
require() the CommonJS export and asserts the threshold mapping so the
per-panel magic-number migration (op_score, player_gpi, cost-tile,
cooldown_watch) has a pinned contract.

Skips cleanly when node is unavailable so it never hard-fails CI on a
runner without a JS toolchain (the dashboard itself needs node only at
author time; the helper ships as static JS).

Research: docs/research/RC2_RESEARCH_nonleague_uiux.md section B1.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_JS = REPO_ROOT / "web" / "js" / "lib" / "status.js"
NODE = shutil.which("node")


def _run_js(snippet: str) -> str:
    """Run a node snippet that has `statusFor`/`statusVar` in scope.

    The helper is require()'d from its absolute path; the snippet's last
    statement should console.log a JSON-serializable result.
    """
    # Forward-slash the path so it is a valid JS string literal on Windows
    # (backslashes would be escape sequences inside the require() argument).
    require_path = STATUS_JS.as_posix()
    program = (
        f"const {{ statusFor, statusVar }} = require({json.dumps(require_path)});\n"
        f"{snippet}\n"
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
class StatusHelperTest(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(STATUS_JS.is_file(), f"missing {STATUS_JS}")

    def test_exports_present(self):
        out = _run_js(
            "console.log(JSON.stringify("
            "[typeof statusFor, typeof statusVar]));"
        )
        self.assertEqual(json.loads(out), ["function", "function"])

    # ----- higher_is_better (default direction) -----
    def test_higher_is_better_good(self):
        out = _run_js(
            "console.log(statusFor(9, { good: 8, warn: 6 }));")
        self.assertEqual(out, "good")

    def test_higher_is_better_boundary_good_inclusive(self):
        # value == good boundary is "good" (>=).
        out = _run_js(
            "console.log(statusFor(8, { good: 8, warn: 6 }));")
        self.assertEqual(out, "good")

    def test_higher_is_better_warn(self):
        out = _run_js(
            "console.log(statusFor(7, { good: 8, warn: 6 }));")
        self.assertEqual(out, "warn")

    def test_higher_is_better_boundary_warn_inclusive(self):
        out = _run_js(
            "console.log(statusFor(6, { good: 8, warn: 6 }));")
        self.assertEqual(out, "warn")

    def test_higher_is_better_bad(self):
        out = _run_js(
            "console.log(statusFor(3, { good: 8, warn: 6 }));")
        self.assertEqual(out, "bad")

    # ----- lower_is_better -----
    def test_lower_is_better_good(self):
        # deaths: 1 <= 2 good.
        out = _run_js(
            "console.log(statusFor(1, "
            "{ good: 2, warn: 5, higherIsBetter: false }));")
        self.assertEqual(out, "good")

    def test_lower_is_better_warn(self):
        out = _run_js(
            "console.log(statusFor(4, "
            "{ good: 2, warn: 5, higherIsBetter: false }));")
        self.assertEqual(out, "warn")

    def test_lower_is_better_bad(self):
        out = _run_js(
            "console.log(statusFor(9, "
            "{ good: 2, warn: 5, higherIsBetter: false }));")
        self.assertEqual(out, "bad")

    # ----- defensive / fail-loud -----
    def test_non_finite_value_is_bad(self):
        for bad_val in ("NaN", "undefined", "Infinity", "'abc'"):
            out = _run_js(
                f"console.log(statusFor({bad_val}, {{ good: 8, warn: 6 }}));")
            self.assertEqual(out, "bad", f"{bad_val} should be bad")

    def test_null_thresholds_is_bad(self):
        out = _run_js("console.log(statusFor(9, null));")
        self.assertEqual(out, "bad")

    def test_malformed_thresholds_is_bad(self):
        out = _run_js(
            "console.log(statusFor(9, { good: 'x', warn: 6 }));")
        self.assertEqual(out, "bad")

    # ----- statusVar mapping to --signal-* tokens -----
    def test_status_var_good(self):
        out = _run_js("console.log(statusVar('good'));")
        self.assertEqual(out, "var(--signal-good)")

    def test_status_var_warn(self):
        out = _run_js("console.log(statusVar('warn'));")
        self.assertEqual(out, "var(--signal-warn)")

    def test_status_var_bad(self):
        out = _run_js("console.log(statusVar('bad'));")
        self.assertEqual(out, "var(--signal-bad)")

    def test_status_var_unknown_is_dim(self):
        out = _run_js("console.log(statusVar('nonsense'));")
        self.assertEqual(out, "var(--signal-dim)")


if __name__ == "__main__":
    unittest.main()
