# arch: rc-shell package.json test script must name every test/*.test.js | section=tests | frozen=no
"""Guard: ``rc-shell/package.json`` ``scripts.test`` must name exactly the
``*.test.js`` files that exist in ``rc-shell/test/``.

RM-212 (2026-08-15, shipped 2026-09-04). That script is a single
``node --test <explicit paths>`` string enumerating its test files BY NAME, and
nothing globbed the directory. So the next test file added to ``rc-shell/test/``
would run NOWHERE, with every signal green - the
`feedback_unrun_gate_is_where_the_bug_hides` shape, and already recorded as
institutional knowledge (`reference_rc_shell_test_script_enumerates_files`)
without ever being converted into a check.

The list was in sync when this guard was written (16 named, 16 on disk, set
difference empty in both directions). The trap was real but unrealised, which is
the cheapest possible moment to close it.

**A DIRECTORY GLOB IS NOT THE FIX, DELIBERATELY.** ``rc-shell/package.json``
pins ``"node": ">=18"`` and directory-mode ``node --test`` semantics differ
across that range, so swapping the invocation would trade a visible drift risk
for an invisible version-dependent one. Measured 2026-09-04 on Node v24.15.0:
``node --test test/`` does not reproduce the enumerated run cleanly here either.
Keep the enumeration; guard it.

**THIS GUARD ASSERTS RATHER THAN SKIPS WHEN rc-shell IS ABSENT.** A guard that
quietly skips when its subject is missing is green over its own blind spot, and
this repo has paid for that shape before (RM-214 is an open row about exactly
it, and `reference_guard_can_be_green_while_self_excusing` records another). If
``rc-shell/`` is ever removed, this test fails and someone deletes it on
purpose.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHELL = ROOT / "rc-shell"
PACKAGE = SHELL / "package.json"
TEST_DIR = SHELL / "test"


def _script_paths() -> list[str]:
    """The test-file paths named in scripts.test, as posix strings."""
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    script = data.get("scripts", {}).get("test", "")
    if "node --test" not in script:
        raise AssertionError(
            f"rc-shell/package.json scripts.test no longer invokes "
            f"'node --test'; it reads {script!r}. If the runner changed, this "
            f"guard needs rewriting - do not delete it, the enumeration trap it "
            f"closes is independent of which runner is used."
        )
    return [tok for tok in script.split() if tok.endswith(".test.js")]


def _disk_names() -> list[str]:
    return sorted(p.name for p in TEST_DIR.glob("*.test.js"))


class RcShellTestScriptCoversTheDirectory(unittest.TestCase):
    def test_the_subject_exists(self):
        """Assert, never skip. A missing subject is a finding, not an excuse."""
        self.assertTrue(
            SHELL.is_dir(),
            f"{SHELL} does not exist. This guard deliberately FAILS rather than "
            f"skipping: a guard that excuses itself when its subject vanishes is "
            f"green over its own blind spot. If rc-shell was removed on purpose, "
            f"delete this test in the same commit.",
        )
        self.assertTrue(PACKAGE.is_file(), f"{PACKAGE} is missing")
        self.assertTrue(TEST_DIR.is_dir(), f"{TEST_DIR} is missing")

    def test_extractors_are_not_vacuous(self):
        """A parser finding nothing would make the equality below trivially true."""
        named, disk = _script_paths(), _disk_names()
        self.assertGreaterEqual(
            len(named), 10,
            f"parsed only {len(named)} test paths out of scripts.test; the "
            f"script format changed and this guard is reading nothing",
        )
        self.assertGreaterEqual(
            len(disk), 10,
            f"found only {len(disk)} *.test.js files in rc-shell/test/; the "
            f"layout changed and this guard is reading nothing",
        )

    def test_every_path_is_under_the_test_dir(self):
        """A named path outside test/ would make the set comparison meaningless."""
        bad = [p for p in _script_paths() if not re.fullmatch(r"test/[\w.\-]+\.test\.js", p)]
        self.assertEqual(
            bad, [],
            f"scripts.test names {bad}, which are not of the form "
            f"test/<name>.test.js. This guard compares basenames against "
            f"rc-shell/test/, so a path elsewhere would be silently mismatched.",
        )

    def test_script_names_exactly_the_files_on_disk(self):
        named = sorted(pathlib.PurePosixPath(p).name for p in _script_paths())
        disk = _disk_names()
        unrun = [n for n in disk if n not in named]
        phantom = [n for n in named if n not in disk]
        self.assertEqual(
            (unrun, phantom), ([], []),
            "rc-shell/package.json scripts.test is out of sync with "
            "rc-shell/test/.\n"
            f"  on disk but NOT named (these tests run NOWHERE): {unrun}\n"
            f"  named but NOT on disk (node will error): {phantom}\n"
            "Add the file to the 'test' script in rc-shell/package.json, or "
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
