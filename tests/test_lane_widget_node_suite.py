# arch: run the lane-widget Node suite from pytest so CI gates it | section=tests | frozen=no
"""Harness: lane-widget's Node test suite, executed from pytest so CI sees it.

Direct sibling of ``tests/test_rc_shell_node_suite_rm342.py`` (RM-342), written
for the same reason and at the earliest possible moment. That module exists
because rc-shell's 16-file Node suite ran in NO CI job at all for months - a
grep of ``.github/workflows/*.yml`` for ``npm test`` / ``node --test``
returned zero hits - so the repo was leaning on coverage nothing produced.
``lane-widget/`` is a brand new top-level Electron app with its own Node suite
and exactly the same exposure, and the cheapest time to close that gap is
before the directory has ever been pushed ungated.

WHY A PYTEST HARNESS AND NOT A NEW CI STEP
------------------------------------------
``.github/workflows/ci.yml``'s ``check`` job already runs pytest over
``tests/``, so a module here rides an existing job: no new workflow, no
``actions/setup-node``, no ``npm ci``. It also covers the LOCAL ``pytest tests``
run, which a CI-only step never would.

NO node_modules IS NEEDED, AND THAT WAS CHECKED RATHER THAN ASSUMED
-------------------------------------------------------------------
MEASURED on the day this was written: ``lane-widget/package.json`` declares
``"dependencies": {}`` and ``"devDependencies": {}``; every ``require`` across
``lane-widget/test/*.test.js`` resolves to a Node builtin (``node:test``,
``node:assert``, ``node:assert/strict``, ``node:fs``, ``node:os``,
``node:path``) or to a relative ``../src/*`` module; ``lane-widget/node_modules``
does not exist on this machine AT ALL, and the suite ran green anyway. The only
``require("electron")`` in the package sits in ``src/main.js`` /
``src/preload.js`` / ``src/tray_icon.js``, which the test files never load. So a
fresh checkout with no install step has everything this run needs.

THIS MODULE ASSERTS RATHER THAN SKIPS WHEN node IS ABSENT
---------------------------------------------------------
Carried over verbatim in spirit from RM-342, and for its reason, not its habit.
Elsewhere in this tree ``shutil.which("node")`` is a legitimate capability gate
and the 2026-07-27 skip audit said so. It is wrong for THIS module, because
here CI IS the subject: a harness whose entire purpose is "the Node suite runs
where a merge is gated", and which excuses itself when the runner has no Node,
reproduces one level up the exact defect it was written to close and reports a
green tick over zero coverage - the shape
``reference_guard_can_be_green_while_self_excusing`` records.

The departure is narrow rather than brave: ``ubuntu-latest`` resolves to
GitHub's ubuntu-24.04 image, which ships Node pre-installed, and
``lane-widget/package.json`` pins ``"node": ">=18"``. If some future runner
lacks Node, the correct response is ``actions/setup-node`` on that job, not
softening this into a skip.

THE FILE LIST IS NOT RETYPED HERE
---------------------------------
``lane-widget/package.json`` ``scripts.test`` is a single ``node --test <paths>``
string enumerating its test files by hand, and
``tests/test_lane_widget_script_covers_the_dir.py`` pins that enumeration
against the directory. This module reads the script off disk and runs exactly
what it names. That guard keeps the list honest; this one runs whatever the
list says. A second hand-typed copy here would only be a second thing to drift.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDGET = ROOT / "lane-widget"
PACKAGE = WIDGET / "package.json"
NODE = shutil.which("node")

# Node's runner prints its tally with a leading marker that differs by reporter:
# "# pass 196" under TAP, and "<glyph> pass 196" under the spec reporter that
# Node 20+ selects by default (the glyph is U+2139 INFORMATION SOURCE). Accept a
# marker character, a TAP hash, or neither, and anchor the whole line so a test
# NAME can never match.
#
# The obvious spelling for the marker is `\W*`, and it is WRONG - measured under
# RM-342. U+2139 has Unicode category Ll, so Python's `\w` matches it and `\W`
# does not; the pattern finds nothing and the tally parses empty. Do not
# "simplify" this regex without re-measuring against a real run.
_TALLY = re.compile(
    r"^\s*(?:#\s*|\S\s+)?(tests|pass|fail|cancelled|skipped|todo)"
    r"[ \t]+(\d+)[ \t]*$", re.M)

# Generous: the eight-file suite measured under 0.2s of node time. This ceiling
# turns a hang into a failure rather than a stuck job; it is not there to police
# seconds.
_TIMEOUT_S = 300

# Vacuity floor for the parsed path count. The suite is NINE files
# (repos/locks/proctree/heartbeat/model/store/clamp/poll/render). Six is about
# two thirds of that - the same proportion RM-342 chose (10 of 16). Its job is
# only to catch "the script format changed and this harness is now executing
# almost nothing"; the EXACT set is pinned by
# tests/test_lane_widget_script_covers_the_dir.py, so a tighter number here
# would just duplicate that guard and break on every legitimate file move.
_MIN_NAMED_PATHS = 6

# Pass-count floor. MEASURED on the day this was written: the eight landed test
# files report 196 passing assertions (clamp 12, store 14, poll 18, proctree 23,
# heartbeat 24, repos 26, locks 39, model 40), with render.test.js still landing
# and additive on top.
#
# 120 and not higher, deliberately. The failure this catches is "files stopped
# being EXECUTED", not "some tests were removed". The largest single file is 40
# assertions, so a floor of 120 cannot be tripped by legitimately deleting or
# rewriting any one file, or even the two largest together - but a collapse to
# one or two executed files (the real symptom of a broken enumeration or a
# runner that silently stopped loading paths) lands far below it. A floor near
# 196 would be brittle against normal churn and would get lowered by whoever it
# annoys, which is how a guard becomes decorative. Raise it only against a
# freshly measured run.
_MIN_PASS = 120

_CACHE = {}


def _script():
    """The raw ``scripts.test`` string, off disk."""
    data = json.loads(PACKAGE.read_text(encoding="utf-8"))
    return str(data.get("scripts", {}).get("test", ""))


def _argv():
    """``scripts.test`` tokenised into an argv, with the contract asserted."""
    argv = shlex.split(_script())
    if not argv:
        raise AssertionError(
            "lane-widget/package.json has no scripts.test to run. This module "
            "exists because an unrun suite is zero coverage, and an empty "
            "script is that state again - not a reason to pass."
        )
    if argv[0] != "node" or "--test" not in argv:
        raise AssertionError(
            f"lane-widget/package.json scripts.test is no longer a "
            f"'node --test' invocation; it reads {_script()!r}. If the runner "
            f"changed, rewrite this harness to drive the new one - do not "
            f"delete it. The gap it closes (a real JS suite that no CI job "
            f"executes) is independent of which runner is used."
        )
    return argv


def _result():
    """Run the enumerated suite once per module and cache the result."""
    if "run" not in _CACHE:
        argv = _argv()
        argv[0] = NODE
        _CACHE["run"] = subprocess.run(
            argv,
            cwd=str(WIDGET),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_S,
            check=False,
        )
    return _CACHE["run"]


def _tail(limit=40):
    """The last lines of the run, forced to ASCII for the failure message.

    Node's spec reporter emits check-mark and info glyphs; this repo's authored
    text is 7-bit ASCII and a failure message quoting raw reporter output
    should not be the exception.
    """
    proc = _result()
    blob = (proc.stdout or "") + (proc.stderr or "")
    lines = blob.encode("ascii", "replace").decode("ascii").splitlines()
    return "\n".join(lines[-limit:])


class LaneWidgetSubjectExists(unittest.TestCase):
    """Assert, never skip. A missing subject is a finding, not an excuse."""

    def test_the_package_exists(self):
        self.assertTrue(
            WIDGET.is_dir(),
            f"{WIDGET} does not exist. This harness deliberately FAILS rather "
            f"than skipping: a gate that excuses itself when its subject "
            f"vanishes is green over its own blind spot. If lane-widget was "
            f"removed on purpose, delete this module in the same commit.",
        )
        self.assertTrue(PACKAGE.is_file(), f"{PACKAGE} is missing")

    def test_the_suite_needs_no_npm_install(self):
        """Zero dependencies is load-bearing for running this in CI unmodified.

        If a dependency is ever added, this harness needs an install step and
        the CI story changes - fail loudly at that moment rather than letting a
        later run die on a missing module with a confusing stack.
        """
        data = json.loads(PACKAGE.read_text(encoding="utf-8"))
        deps = dict(data.get("dependencies") or {})
        dev = dict(data.get("devDependencies") or {})
        self.assertEqual(
            (deps, dev), ({}, {}),
            f"lane-widget declared dependencies {deps} / devDependencies {dev}. "
            f"This harness runs the suite with NO npm install, which only "
            f"works while the package is builtins-only. Either drop the "
            f"dependency or add an install step to this harness and to CI - do "
            f"not delete this assertion.",
        )


class NodeIsAvailable(unittest.TestCase):
    """The capability check, ASSERTED rather than skipped."""

    def test_node_is_on_path(self):
        self.assertIsNotNone(
            NODE,
            "node is not on PATH, so the lane-widget Node suite cannot run "
            "here.\nThis module deliberately FAILS instead of skipping. Its "
            "whole purpose is that the suite runs where a merge is gated, so a "
            "skip here would report green over exactly the coverage gap it was "
            "written to close.\nGitHub's ubuntu-24.04 image (what "
            "ubuntu-latest resolves to) ships Node.js pre-installed, so "
            ".github/workflows/ci.yml needs no setup step today. If a runner "
            "ever lacks Node, add actions/setup-node to that job - do not "
            "soften this into a skip.",
        )


class LaneWidgetNodeSuite(unittest.TestCase):
    """Run what lane-widget/package.json names, and fail when it fails."""

    def test_the_script_is_the_enumerated_node_invocation(self):
        """A parser reading almost nothing would make the run below vacuous."""
        named = [tok for tok in _argv() if tok.endswith(".test.js")]
        self.assertGreaterEqual(
            len(named), _MIN_NAMED_PATHS,
            f"parsed only {len(named)} test paths out of scripts.test "
            f"({_script()!r}); the script format changed, so this harness "
            f"would be executing almost nothing while still reporting green",
        )

    def test_every_named_test_file_exists(self):
        """A phantom name is SILENTLY SKIPPED by node - so this is the gate.

        MEASURED on Node v24.15.0 the day this was written:
        ``node --test test/clamp.test.js test/does-not-exist.test.js`` runs the
        file that exists, reports ``pass 12 / fail 0`` and EXITS 0. It does not
        warn and it does not error. The rc-shell sibling's comment here reads
        "a phantom name makes node error", which is not true on this version.

        That makes this assertion the only thing standing between a typo in
        ``scripts.test`` and a whole test file quietly never running again with
        every signal green - the exact ``feedback_unrun_gate_is_where_the_bug_hides``
        shape, one level below the one this module was written for. Do not
        weaken it on the theory that node would have caught it.
        """
        missing = [tok for tok in _argv()
                   if tok.endswith(".test.js") and not (WIDGET / tok).is_file()]
        self.assertEqual(
            missing, [],
            f"scripts.test names files that are not on disk: {missing}. "
            f"tests/test_lane_widget_script_covers_the_dir.py owns keeping "
            f"that enumeration in sync with lane-widget/test/.",
        )

    def test_the_lane_widget_node_suite_passes(self):
        """The whole point: a lane-widget test failure must fail this suite."""
        proc = _result()
        self.assertEqual(
            proc.returncode, 0,
            f"the lane-widget Node suite failed (exit {proc.returncode}).\n"
            f"Reproduce with:  cd lane-widget && npm test\n"
            f"--- last lines of the run ---\n{_tail()}",
        )

    def test_the_run_was_not_vacuous(self):
        """Exit 0 over zero executed tests would be a green tick over nothing."""
        tally = {k: int(v) for k, v in _TALLY.findall(_result().stdout or "")}
        self.assertIn(
            "pass", tally,
            f"could not parse a tally out of the node run, so 'exit 0' is the "
            f"only evidence there is and an empty run would look identical. "
            f"Node's reporter format changed - update _TALLY, do not drop this "
            f"assertion.\n--- last lines of the run ---\n{_tail()}",
        )
        self.assertEqual(
            tally.get("fail"), 0,
            f"the node run reports {tally.get('fail')} failing tests.\n"
            f"--- last lines of the run ---\n{_tail()}",
        )
        self.assertGreaterEqual(
            tally["pass"], _MIN_PASS,
            f"only {tally['pass']} node assertions ran; the eight landed test "
            f"files measured 196 when this harness was written, so a collapse "
            f"below {_MIN_PASS} means files stopped being EXECUTED rather than "
            f"that tests were removed - the largest single file is 40.",
        )


if __name__ == "__main__":
    unittest.main()
