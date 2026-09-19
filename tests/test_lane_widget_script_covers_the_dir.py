# arch: lane-widget package.json test script must name every test/*.test.js | section=tests | frozen=no
"""Guard: ``lane-widget/package.json`` ``scripts.test`` must name exactly the
``*.test.js`` files that exist in ``lane-widget/test/``.

Direct sibling of ``tests/test_rc_shell_test_script_covers_the_dir_rm212.py``
(RM-212). That script is a single ``node --test <explicit paths>`` string
enumerating its test files BY NAME, and nothing globs the directory. So the
next test file added to ``lane-widget/test/`` would run NOWHERE, with every
signal green - the ``feedback_unrun_gate_is_where_the_bug_hides`` shape, which
this repo has already paid for once in rc-shell.

lane-widget is a brand new package and this guard lands with it, so the trap is
closed before it has ever had a chance to fire. That is the cheapest possible
moment: RM-212 was written years-of-commits after rc-shell's enumeration
started drifting-by-luck-only.

**A DIRECTORY GLOB IS NOT THE FIX, DELIBERATELY.** ``lane-widget/package.json``
pins ``"node": ">=18"`` and directory-mode ``node --test`` semantics differ
across that range, so swapping the invocation would trade a visible drift risk
for an invisible version-dependent one. Keep the enumeration; guard it.

**THIS GUARD ASSERTS RATHER THAN SKIPS WHEN lane-widget IS ABSENT.** A guard
that quietly skips when its subject is missing is green over its own blind
spot, and this repo has paid for that shape before (RM-214 is an open row about
exactly it, and ``reference_guard_can_be_green_while_self_excusing`` records
another). If ``lane-widget/`` is ever removed, this test fails and someone
deletes it on purpose.

SCOPE NOTE: this guard pins the SET. Whether the enumerated command is actually
RUN anywhere that can block a merge is a different question, owned by
``tests/test_lane_widget_node_suite.py``. A perfectly maintained list of tests
nobody executes is still zero coverage, and a perfectly executed list that
omits half the directory is too - the two guards are not redundant.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIDGET = ROOT / "lane-widget"
PACKAGE = WIDGET / "package.json"
TEST_DIR = WIDGET / "test"

# Vacuity floor. The suite is NINE files
# (repos/locks/proctree/heartbeat/model/store/clamp/poll/render); six is about
# two thirds, the same proportion RM-212 chose (10 of 16). This only has to
# catch "the parser is reading nothing, so the set comparison below is
# trivially true". The exact membership is pinned by
# test_script_names_exactly_the_files_on_disk, so a tighter number here would
# add no coverage and would fail on every legitimate file move.
_MIN_FILES = 6


def _script_paths() -> list[str]:
    """The test-file paths named in scripts.test, as posix strings."""
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    script = data.get("scripts", {}).get("test", "")
    if "node --test" not in script:
        raise AssertionError(
            f"lane-widget/package.json scripts.test no longer invokes "
            f"'node --test'; it reads {script!r}. If the runner changed, this "
            f"guard needs rewriting - do not delete it, the enumeration trap "
            f"it closes is independent of which runner is used."
        )
    return [tok for tok in script.split() if tok.endswith(".test.js")]


def _disk_names() -> list[str]:
    return sorted(p.name for p in TEST_DIR.glob("*.test.js"))


class LaneWidgetTestScriptCoversTheDirectory(unittest.TestCase):
    def test_the_subject_exists(self):
        """Assert, never skip. A missing subject is a finding, not an excuse."""
        self.assertTrue(
            WIDGET.is_dir(),
            f"{WIDGET} does not exist. This guard deliberately FAILS rather "
            f"than skipping: a guard that excuses itself when its subject "
            f"vanishes is green over its own blind spot. If lane-widget was "
            f"removed on purpose, delete this test in the same commit.",
        )
        self.assertTrue(PACKAGE.is_file(), f"{PACKAGE} is missing")
        self.assertTrue(TEST_DIR.is_dir(), f"{TEST_DIR} is missing")

    def test_extractors_are_not_vacuous(self):
        """A parser finding nothing would make the equality below trivially true."""
        named, disk = _script_paths(), _disk_names()
        self.assertGreaterEqual(
            len(named), _MIN_FILES,
            f"parsed only {len(named)} test paths out of scripts.test; the "
            f"script format changed and this guard is reading nothing",
        )
        self.assertGreaterEqual(
            len(disk), _MIN_FILES,
            f"found only {len(disk)} *.test.js files in lane-widget/test/; "
            f"the layout changed and this guard is reading nothing",
        )

    def test_every_path_is_under_the_test_dir(self):
        """A named path outside test/ would make the set comparison meaningless."""
        bad = [p for p in _script_paths()
               if not re.fullmatch(r"test/[\w.\-]+\.test\.js", p)]
        self.assertEqual(
            bad, [],
            f"scripts.test names {bad}, which are not of the form "
            f"test/<name>.test.js. This guard compares basenames against "
            f"lane-widget/test/, so a path elsewhere would be silently "
            f"mismatched.",
        )

    def test_script_names_exactly_the_files_on_disk(self):
        named = sorted(pathlib.PurePosixPath(p).name for p in _script_paths())
        disk = _disk_names()
        unrun = [n for n in disk if n not in named]
        phantom = [n for n in named if n not in disk]
        self.assertEqual(
            (unrun, phantom), ([], []),
            "lane-widget/package.json scripts.test is out of sync with "
            "lane-widget/test/.\n"
            f"  on disk but NOT named (these tests run NOWHERE): {unrun}\n"
            f"  named but NOT on disk (node will error): {phantom}\n"
            "Add the file to the 'test' script in lane-widget/package.json, or "
            "remove the stale name. The script enumerates by hand on purpose - "
            "see this module's docstring for why a directory glob is not the fix.",
        )

    def test_no_duplicate_names(self):
        named = [pathlib.PurePosixPath(p).name for p in _script_paths()]
        dupes = sorted({n for n in named if named.count(n) > 1})
        self.assertEqual(
            dupes, [],
            f"scripts.test names these files more than once: {dupes}. A "
            f"duplicate hides a missing file from a naive count comparison.",
        )


if __name__ == "__main__":
    unittest.main()
