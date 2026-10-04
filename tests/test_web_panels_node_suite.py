# arch: run every web/js/panels/*.test.mjs from pytest so CI gates them | section=tests | frozen=no
"""Harness + covers-the-dir guard: every ``web/js/panels/*.test.mjs``, run by
``node --test`` from pytest.

Y-04 (external reference O + Q) changed the session-hygiene card's contract
(null score, state, flags) and pinned it in
``web/js/panels/session_hygiene.test.mjs``. MEASURED 2026-10-04 at origin/main
d1d078aab: nothing executed that file - no CI step runs ``node --test`` over
``web/js/panels/`` and no pytest module named it, so the JS half of the null
contract would have been a test that runs nowhere. The 22 panel ``.test.mjs``
files measured 238 passing tests / 0 failing on Node v24.15.0 in one run, so
the whole directory can be gated, not just this one file.

THE UNIVERSE IS THE DIRECTORY, NOT A HAND LIST. The paths are globbed off disk
here and handed to node explicitly, so a new ``*.test.mjs`` is gated the moment
it lands, and a hand-typed list cannot drift. Node's own directory mode is NOT
used: it varies by version, and ``node --test`` given a missing path exits 0
silently, which is why every globbed path is asserted to exist and the run is
checked against a per-file floor.

ASSERTS, NEVER SKIPS, WHEN node IS ABSENT - same reason as
``tests/test_lane_widget_node_suite.py``: a gate that excuses itself when its
runner is missing reports green over zero coverage. ubuntu-latest ships Node.

Positive control (recorded in the Y-04 commit): planting the Number(null)=0
defect back into session_hygiene.js turns this module red; restoring it turns
it green.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANELS = ROOT / "web" / "js" / "panels"
NODE = shutil.which("node")

# Same tally regex as tests/test_lane_widget_node_suite.py (RM-342): the spec
# reporter's marker glyph is a Unicode letter, so a \W-based marker fails.
_TALLY = re.compile(
    r"^\s*(?:#\s*|\S\s+)?(tests|pass|fail|cancelled|skipped|todo)"
    r"[ \t]+(\d+)[ \t]*$", re.M)

_TIMEOUT_S = 300

# Vacuity floors. Measured 2026-10-04: 22 files, 238 passing tests. The floors
# only catch "the glob / runner is executing almost nothing"; they are not a
# count pin, so legitimate churn does not trip them.
_MIN_FILES = 15
_MIN_PASS = 150

# Files whose contract a shipped item depends on - must stay in the universe.
_REQUIRED = ("session_hygiene.test.mjs",
             # Y-08: ingest freshness card - fixed rows, in-place render.
             "ops_panels.test.mjs")

_CACHE: dict = {}


def _files() -> list[Path]:
    return sorted(PANELS.glob("*.test.mjs"))


def _result():
    if "run" not in _CACHE:
        argv = [NODE, "--test", *[str(p) for p in _files()]]
        _CACHE["run"] = subprocess.run(
            argv, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT_S, check=False,
        )
    return _CACHE["run"]


def _tally() -> dict:
    proc = _result()
    out = {}
    for key, val in _TALLY.findall((proc.stdout or "") + (proc.stderr or "")):
        out[key] = int(val)
    return out


def _tail(limit=40) -> str:
    proc = _result()
    blob = (proc.stdout or "") + (proc.stderr or "")
    lines = blob.encode("ascii", "replace").decode("ascii").splitlines()
    return "\n".join(lines[-limit:])


class PanelsSuiteUniverse(unittest.TestCase):
    def test_enumeration_is_not_empty(self):
        files = _files()
        self.assertGreaterEqual(
            len(files), _MIN_FILES,
            f"globbed only {len(files)} *.test.mjs under {PANELS}; the layout "
            f"changed and this guard is reading (almost) nothing")

    def test_required_files_are_in_the_universe(self):
        names = {p.name for p in _files()}
        missing = [n for n in _REQUIRED if n not in names]
        self.assertEqual(missing, [], f"required panel tests missing: {missing}")

    def test_every_path_exists(self):
        # node --test exits 0 on a missing path; never hand it one.
        self.assertEqual([p for p in _files() if not p.is_file()], [])


class NodeIsAvailable(unittest.TestCase):
    def test_node_is_on_path(self):
        self.assertIsNotNone(
            NODE,
            "node is not on PATH, so the web/js/panels suite cannot run. This "
            "module FAILS instead of skipping on purpose; add actions/setup-node "
            "to the job rather than softening it.")


class PanelsNodeSuite(unittest.TestCase):
    def test_suite_passes(self):
        proc = _result()
        tally = _tally()
        self.assertEqual(proc.returncode, 0, f"node --test failed:\n{_tail()}")
        self.assertEqual(tally.get("fail"), 0, f"failures:\n{_tail()}")

    def test_suite_actually_ran(self):
        tally = _tally()
        self.assertIn("pass", tally, f"no tally parsed:\n{_tail()}")
        self.assertGreaterEqual(
            tally["pass"], _MIN_PASS,
            f"only {tally.get('pass')} passing tests across {len(_files())} "
            f"files; files stopped being executed:\n{_tail()}")
        self.assertGreaterEqual(
            tally.get("tests", 0), len(_files()),
            "fewer tests than files - at least one file contributed nothing")


if __name__ == "__main__":
    unittest.main()
