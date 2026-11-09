"""Run web/js/lib/overlay_settings.test.mjs under `node --test` (S144-T true-audit).

The web/js/lib node tests have no globbing runner (tests/test_web_panels_node_suite.py
covers web/js/panels only) and CI runs no bare `node --test`, so without this
wrapper the behaviour tests for the overlay-settings helper would never run in
the gated suite. It asserts the runner exit code, a zero fail count AND a pass
floor, so a runner that silently executes nothing cannot read as green.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE_TEST = ROOT / "web" / "js" / "lib" / "overlay_settings.test.mjs"
NODE = shutil.which("node")

# Measured at authoring: 26 tests. A floor, not an exact count, so adding a
# test never needs this file edited; dropping below it means the runner lost
# most of the file.
_PASS_FLOOR = 26


def test_node_test_file_exists() -> None:
    assert NODE_TEST.is_file(), f"missing {NODE_TEST}"


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_overlay_settings_node_suite_passes() -> None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run(
        [NODE, "--test", str(NODE_TEST.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=flags,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"node --test exited {proc.returncode}\n{out[-4000:]}"
    passed = re.search(r"^\S* ?pass (\d+)$", out, re.MULTILINE)
    failed = re.search(r"^\S* ?fail (\d+)$", out, re.MULTILINE)
    assert passed and failed, f"no pass / fail summary in node output\n{out[-4000:]}"
    assert int(failed.group(1)) == 0, out[-4000:]
    assert int(passed.group(1)) >= _PASS_FLOOR, (
        f"only {passed.group(1)} node tests passed (floor {_PASS_FLOOR})\n{out[-4000:]}"
    )
