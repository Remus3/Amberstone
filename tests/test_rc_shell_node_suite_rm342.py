# arch: RM-342 - run the rc-shell Node suite from pytest so CI gates it | section=tests | frozen=no
"""Harness: rc-shell's Node test suite, executed from pytest so CI sees it.

RM-342 (2026-09-04). MEASURED that day: a grep of `.github/workflows/*.yml` for
`rc-shell`, `npm test`, `npm run test` and `node --test` returned ZERO hits, and
no pytest module shelled out to it either. So the 16-file Node suite under
`rc-shell/test/` - 329 assertions, about two seconds - ran in NO CI job at all,
while `tests/test_overlay_a1_slider_apply.py:19` justified its own narrower,
grep-style approach with "the rc-shell node tests cover the shell half". The
repo was leaning on coverage that nothing produced.

That is the `feedback_unrun_gate_is_where_the_bug_hides` shape, one layer up
from RM-212: RM-212 made sure the hand-enumerated file list names every file on
disk, and this module makes sure the enumerated command is actually RUN
somewhere that can block a merge. A perfectly maintained list of tests nobody
executes is still zero coverage.

WHY A PYTEST HARNESS AND NOT A NEW CI STEP
------------------------------------------
`.github/workflows/ci.yml`'s `check` job already runs
`pytest tests/ agents/daemon_slayer/tests/` on push and pull request, so a
module here rides an existing job: no new workflow, no `actions/setup-node`, no
`npm ci`. It also covers the LOCAL `pytest tests` run, which a CI-only step
never would.

Checked before choosing, because a harness that needs an install step is not
free: every `require` across `rc-shell/test/*.test.js` resolves either to a Node
builtin (`node:test`, `node:assert`, `node:fs`, `node:path`, `fs`, `path`,
`url`) or to a relative `../src/*` module. The suite has ZERO third-party
dependencies, so it does not need `rc-shell/node_modules` to exist. All 16 test
files and the `src/` modules they import are tracked, so a fresh checkout has
everything the run needs.

THE FILE LIST IS NOT RETYPED HERE
---------------------------------
`rc-shell/package.json` `scripts.test` is a single `node --test <paths>` string
that enumerates its test files by hand, and
`tests/test_rc_shell_test_script_covers_the_dir_rm212.py` pins that enumeration
against the directory. This module reads that script off disk and runs exactly
what it names. RM-212 therefore keeps the list honest and this runs whatever the
list says; a second hand-typed copy here would just be a second thing to drift.

THIS MODULE ASSERTS RATHER THAN SKIPS WHEN node IS ABSENT
---------------------------------------------------------
That is a deliberate departure from the rest of this tree, where 23 modules use
`shutil.which("node")` as a capability gate and the 2026-07-27 skip audit
classified an external-binary skip as legitimate. The audit is right in general
and wrong for this one module, because here CI IS the subject. A harness whose
entire purpose is "the Node suite runs where a merge is gated", and which
excuses itself when the runner has no Node, reproduces the exact defect it was
written to close one level up and reports a green tick over zero coverage. That
is the shape the still-open RM-214 is about, and that
`reference_guard_can_be_green_while_self_excusing` records.

The departure is also narrow rather than brave. MEASURED 2026-09-04:
`ubuntu-latest` resolves to the GitHub-hosted ubuntu-24.04 image, which ships
Node.js 22.23.2 pre-installed, and `rc-shell/package.json` pins
`"node": ">=18"`, so the runner this rides already satisfies the requirement
with no setup step. Legion runs v24.15.0. If some future runner does not carry
Node, the correct response is to add `actions/setup-node` to that job, not to
soften this into a skip.

COST: one subprocess, about 2.1 seconds of wall clock, run once per module and
cached across the assertions below.
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
SHELL = ROOT / "rc-shell"
PACKAGE = SHELL / "package.json"
NODE = shutil.which("node")

# Node's runner prints its tally with a leading marker that differs by reporter:
# "# pass 329" under TAP, and "<glyph> pass 329" under the spec reporter that
# Node 20+ selects by default (the glyph is U+2139 INFORMATION SOURCE). Accept a
# marker character, a TAP hash, or neither, and anchor the whole line so a test
# NAME can never match.
#
# The obvious spelling for the marker is `\W*`, and it is WRONG - measured
# 2026-09-04. U+2139 has Unicode category Ll, so Python's `\w` matches it and
# `\W` does not; the pattern found nothing, the tally parsed empty, and the only
# reason that was visible is that this module asserts on the tally instead of
# trusting the exit code alone. `feedback_empty_grep_is_a_claim_about_the_pattern`.
_TALLY = re.compile(
    r"^\s*(?:#\s*|\S\s+)?(tests|pass|fail|cancelled|skipped|todo)"
    r"[ \t]+(\d+)[ \t]*$", re.M)

# Generous: the suite measures ~2.1s. This ceiling exists to turn a hang into a
# failure rather than a stuck job, not to police seconds.
_TIMEOUT_S = 300

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
            "rc-shell/package.json has no scripts.test to run. RM-342 exists "
            "because that suite was ungated, and an empty script is the "
            "ungated state again - not a reason to pass."
        )
    if argv[0] != "node" or "--test" not in argv:
        raise AssertionError(
            f"rc-shell/package.json scripts.test is no longer a 'node --test' "
            f"invocation; it reads {_script()!r}. If the runner changed, "
            f"rewrite this harness to drive the new one - do not delete it. "
            f"The gap it closes (a real JS suite that no CI job executes) is "
            f"independent of which runner is used."
        )
    return argv


def _result():
    """Run the enumerated suite once per module and cache the result."""
    if "run" not in _CACHE:
        argv = _argv()
        argv[0] = NODE
        _CACHE["run"] = subprocess.run(
            argv,
            cwd=str(SHELL),
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


class NodeIsAvailable(unittest.TestCase):
    """The capability check, ASSERTED rather than skipped."""

    def test_node_is_on_path(self):
        self.assertIsNotNone(
            NODE,
            "node is not on PATH, so the rc-shell Node suite cannot run here.\n"
            "This module deliberately FAILS instead of skipping. Its whole "
            "purpose is that the suite runs where a merge is gated, so a skip "
            "here would report green over exactly the coverage gap RM-342 "
            "closed - the self-excusing shape RM-214 is open about.\n"
            "GitHub's ubuntu-24.04 image (what ubuntu-latest resolves to) "
            "ships Node.js pre-installed, so .github/workflows/ci.yml needs no "
            "setup step today. If a runner ever lacks Node, add "
            "actions/setup-node to that job - do not soften this into a skip.",
        )


class RcShellNodeSuite(unittest.TestCase):
    """Run what rc-shell/package.json names, and fail when it fails."""

    def test_the_script_is_the_enumerated_node_invocation(self):
        """A parser reading almost nothing would make the run below vacuous."""
        named = [tok for tok in _argv() if tok.endswith(".test.js")]
        self.assertGreaterEqual(
            len(named), 10,
            f"parsed only {len(named)} test paths out of scripts.test "
            f"({_script()!r}); the script format changed, so this harness "
            f"would be executing almost nothing while still reporting green",
        )

    def test_every_named_test_file_exists(self):
        """A phantom name makes node error; failing here says why."""
        missing = [tok for tok in _argv()
                   if tok.endswith(".test.js") and not (SHELL / tok).is_file()]
        self.assertEqual(
            missing, [],
            f"scripts.test names files that are not on disk: {missing}. "
            f"tests/test_rc_shell_test_script_covers_the_dir_rm212.py owns "
            f"keeping that enumeration in sync with rc-shell/test/.",
        )

    def test_the_rc_shell_node_suite_passes(self):
        """The whole point: an rc-shell test failure must fail this suite."""
        proc = _result()
        self.assertEqual(
            proc.returncode, 0,
            f"the rc-shell Node suite failed (exit {proc.returncode}).\n"
            f"Reproduce with:  cd rc-shell && npm test\n"
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
            tally["pass"], 100,
            f"only {tally['pass']} node assertions ran; the suite measured 329 "
            f"on 2026-09-04, so a collapse to a double-digit count means files "
            f"stopped being executed rather than that tests were removed",
        )


if __name__ == "__main__":
    unittest.main()
