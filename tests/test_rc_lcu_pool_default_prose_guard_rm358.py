# arch: guard that RC_LCU_POOL prose cannot contradict the measured default | section=test | frozen=no
"""RM-358 / RM-365 guard - source prose may not claim RC_LCU_POOL is default-OFF
while pool_enabled() returns True for an unset environment.

WHY THIS GUARD EXISTS. The E7 flip on 2026-06-30 (validated live 2026-07-01,
LEDGER item-709) made pooling DEFAULT-ON, but three prose sites kept saying
DEFAULT-OFF. That is not a typo class: RM-345 was originally triaged as
"latent behind a flag" on the strength of exactly this comment and was only
re-graded to live-today after somebody measured the default. A stale comment
that DOWNGRADES a live defect is a process hazard, so the prose and the code
get pinned to each other here.

THE PREMISE IS DERIVED, NOT HARDCODED. The guard first measures the live
default by calling pool_enabled() with the env var unset. Only when that is
True is default-OFF prose wrong. If the default is ever deliberately flipped
back to OFF, this guard's premise disappears and it stops demanding the
prose say ON - it does not need editing to stay correct.

THE FROZEN HALF IS RECORDED, NOT SUPPRESSED. lcu/lcu_client.py is on the
CLAUDE.md frozen list, so its stale comment could not be repaired in the
commit that shipped this guard. It is listed in _FROZEN_PENDING with the row
that owns it. Two separate tests keep that registry honest: an entry is only
legal for a file that is ACTUALLY on the frozen list (so the registry cannot
become a general silencing hatch), and every entry must still be stale (so
whoever eventually gets the adjudicated frozen-file grant is forced to retire
the exemption in the same commit as the fix, rather than leaving a dead
suppression behind).
"""
from __future__ import annotations

import io
import os
import re
import tokenize
import unittest
from pathlib import Path
from unittest import mock

from core import lcu_pool

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The flag whose documented default and real default must agree.
FLAG = "RC_LCU_POOL"

#: Phrases that CLAIM a default of off. Deliberately literal: a bare "opt-in"
#: or "opts in" is NOT matched, because it is suggestive rather than a claim
#: about the default (an unset env opts in today) and core/lcu_pool.py:235 and
#: lcu/lcu_client.py:176 both use it defensibly. Matching a bare "off" would
#: false-positive on prose like "verify=off loopback context".
#:
#: The re-wordings below were added after the RM-358 verifier gate demonstrated
#: that the first draft matched only the literal spelling the tree happened to
#: use, so a paraphrase would have walked straight through it.
_DEFAULT_OFF_CLAIM = re.compile(
    r"default[\s\-_:]*off"
    r"|defaults?\s+(?:to\s+)?off"
    r"|off\s+by\s+default"
    r"|disabled\s+by\s+default"
    r"|opt[\s\-]?in\s+only"
    r"|not\s+(?:enabled|on|pooled)\s+(?:unless|until)"
    r"|until\s+the\s+operator\s+opts\s+in",
    re.IGNORECASE,
)

#: KNOWN LIMIT, stated so nobody mistakes this guard for total coverage. A
#: claim is only seen when the flag NAME and the claim share one prose block
#: (a run of consecutive comment lines, or one string literal). A comment that
#: says "pooling is disabled by default" with the flag named a paragraph away
#: is invisible here. Widening past that would need real dataflow, and the
#: cost of a miss is a stale comment rather than a broken runtime - so the
#: narrow, false-positive-free version is the deliberate trade.

#: Known-stale prose that a FROZEN file carries, mapped to the row that owns it.
#: An entry here is a debt that is recorded, not a defect that is forgiven.
_FROZEN_PENDING = {
    "lcu/lcu_client.py": (
        "RM-358 - the DEFAULT-OFF (RC_LCU_POOL) comment in _request. The file is "
        "on the CLAUDE.md frozen list, so repairing it needs an adjudicating "
        "agent that did not author the change plus explicit operator approval."
    ),
}


def _frozen_files_from_claude_md():
    """The frozen list, parsed from CLAUDE.md rather than copied.

    Copying it would let this guard drift out of agreement with the policy it
    leans on, which is the exact failure class the guard is about.
    """
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "**Frozen files**" in line:
            block = "\n".join(lines[idx:idx + 8])
            return {m.replace("\\", "/") for m in re.findall(r"`([^`]+)`", block)}
    raise AssertionError("CLAUDE.md no longer carries a '**Frozen files**' block")


def _prose_blocks(path):
    """Yield (first_lineno, text) for every comment run and string literal.

    Consecutive comment lines are joined into ONE block so a claim split
    across lines is still seen whole - the live stale comments spell
    "DEFAULT-OFF (RC_LCU_POOL)" on one line and the rest on the next. String
    literals are already single tokens, which is how a module docstring
    carrying the flag name and the claim in different sentences is caught.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    blocks = []
    pending = None  # [start_lineno, last_lineno, [texts]]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise AssertionError(f"{path} did not tokenize: {exc}") from exc
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            line = tok.start[0]
            if pending is not None and line == pending[1] + 1:
                pending[1] = line
                pending[2].append(tok.string)
            else:
                if pending is not None:
                    blocks.append((pending[0], " ".join(pending[2])))
                pending = [line, line, [tok.string]]
        elif tok.type == tokenize.STRING:
            blocks.append((tok.start[0], tok.string))
    if pending is not None:
        blocks.append((pending[0], " ".join(pending[2])))
    return blocks


def _scope_files():
    """Every tracked .py that mentions the flag, minus this guard itself.

    Deliberately DERIVED rather than a hardcoded list: a new module that picks
    up the flag is in scope the day it is written. The guard file is excluded
    because it necessarily carries both the flag name and the claim phrases as
    test data.
    """
    here = Path(__file__).resolve()
    found = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = path.parts
        if any(p in (".git", "_archive", "node_modules", "Share") for p in parts):
            continue
        if path.resolve() == here:
            continue
        try:
            if FLAG in path.read_text(encoding="utf-8", errors="replace"):
                found.append(path)
        except OSError:
            continue
    return sorted(found)


def _stale_claims():
    """(relative_posix_path, lineno, text) for every default-OFF claim about the flag."""
    offenders = []
    for path in _scope_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, text in _prose_blocks(path):
            if FLAG.lower() not in text.lower():
                continue
            if _DEFAULT_OFF_CLAIM.search(text):
                offenders.append((rel, lineno, " ".join(text.split())))
    return offenders


class TestPoolDefaultPremise(unittest.TestCase):
    """The guard's premise, measured from the code rather than assumed."""

    def test_unset_env_pools_so_default_off_prose_would_be_false(self):
        env = {k: v for k, v in os.environ.items() if k != FLAG}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertNotIn(FLAG, os.environ)
            self.assertTrue(
                lcu_pool.pool_enabled(),
                "premise broken: an unset env no longer pools, so this guard's "
                "demand that prose say default-ON is no longer correct",
            )

    def test_explicit_zero_still_forces_the_legacy_path(self):
        with mock.patch.dict(os.environ, {FLAG: "0"}):
            self.assertFalse(lcu_pool.pool_enabled())


class TestScopeIsNotEmpty(unittest.TestCase):
    """An empty scan is a claim about the PATTERN, never about the tree."""

    def test_scope_covers_the_modules_that_route_through_the_pool(self):
        scanned = {p.relative_to(REPO_ROOT).as_posix() for p in _scope_files()}
        for expected in ("core/lcu_pool.py", "lcu/lcu_client.py", "game_reader/poller.py"):
            self.assertIn(expected, scanned, f"{expected} fell out of the guard's scope")

    def test_prose_extraction_actually_returns_blocks(self):
        blocks = _prose_blocks(REPO_ROOT / "core" / "lcu_pool.py")
        self.assertGreater(len(blocks), 5, "tokenizer returned no prose - the scan is inert")
        self.assertTrue(
            any(FLAG in text for _, text in blocks),
            "the flag name appears in no extracted prose block, so a claim about "
            "it could never be detected",
        )


class TestClaimMatcher(unittest.TestCase):
    """The matcher's own branches, exercised directly.

    Every alternation is taken by at least one case here. Without this the
    re-wordings added after the verifier gate would be dead regex - present,
    greppable, and never proven to fire (the RM-357 M4 lesson: a guard on a
    path no test takes is an untested guard).
    """

    MUST_MATCH = (
        "DEFAULT-OFF (RC_LCU_POOL) so the urlopen",   # the shipped spelling
        "RC_LCU_POOL default-OFF gate",
        "the default off state",
        "RC_LCU_POOL defaults off",
        "RC_LCU_POOL defaults to off",
        "pooling is off by default",
        "pooling is disabled by default",
        "opt-in only",
        "opt in only",
        "not enabled unless RC_LCU_POOL is set",
        "not pooled until the pilot enables it",
        "byte-identical until the operator opts in",
    )

    MUST_NOT_MATCH = (
        "opt-in pooled keep-alive reuse",             # suggestive, not a claim
        "a caller actually opts in via RC_LCU_POOL",  # core/lcu_pool.py:235
        "verify=off loopback context",                # bare 'off' is not a claim
        "DEFAULT-ON (RC_LCU_POOL) since the E7 flip",
        "explicit RC_LCU_POOL=0 forces the legacy per-call path",
        "an UNSET env now opts IN",
    )

    def test_every_claim_spelling_is_matched(self):
        for phrase in self.MUST_MATCH:
            with self.subTest(phrase):
                self.assertIsNotNone(_DEFAULT_OFF_CLAIM.search(phrase))

    def test_defensible_prose_is_not_matched(self):
        for phrase in self.MUST_NOT_MATCH:
            with self.subTest(phrase):
                self.assertIsNone(
                    _DEFAULT_OFF_CLAIM.search(phrase),
                    "false positive - this guard must not police prose that "
                    "makes no claim about the default",
                )


class TestNoStaleDefaultOffProse(unittest.TestCase):
    """The row's acceptance: prose and pool_enabled() may not disagree."""

    def test_no_source_prose_claims_default_off(self):
        env = {k: v for k, v in os.environ.items() if k != FLAG}
        with mock.patch.dict(os.environ, env, clear=True):
            if not lcu_pool.pool_enabled():
                self.skipTest("default is OFF, so default-OFF prose is correct")
        unexpected = [o for o in _stale_claims() if o[0] not in _FROZEN_PENDING]
        self.assertEqual(
            [], unexpected,
            "prose claims RC_LCU_POOL is default-OFF, but an unset env pools "
            "(ON since the E7 flip 2026-06-30):\n"
            + "\n".join(f"  {p}:{n} -> {t}" for p, n, t in unexpected),
        )

    def test_the_two_repaired_sites_stay_repaired(self):
        """Named explicitly so a revert names the file instead of a diff."""
        for rel in ("game_reader/poller.py", "tests/test_lcu_pool.py"):
            with self.subTest(rel):
                hits = [o for o in _stale_claims() if o[0] == rel]
                self.assertEqual([], hits, f"{rel} claims default-OFF again: {hits}")


class TestFrozenPendingRegistryStaysHonest(unittest.TestCase):
    """The exemption list is a debt register, not a silencing hatch."""

    def test_every_exemption_names_a_file_on_the_frozen_list(self):
        frozen = _frozen_files_from_claude_md()
        for rel in _FROZEN_PENDING:
            with self.subTest(rel):
                self.assertIn(
                    rel, frozen,
                    f"{rel} is exempted but is NOT on the CLAUDE.md frozen list, so "
                    "the exemption is suppressing a defect that could just be fixed",
                )

    def test_every_exemption_is_still_stale(self):
        stale = {o[0] for o in _stale_claims()}
        for rel, why in _FROZEN_PENDING.items():
            with self.subTest(rel):
                self.assertIn(
                    rel, stale,
                    f"{rel} no longer carries default-OFF prose, so its exemption is "
                    f"dead weight - delete it from _FROZEN_PENDING. Owner: {why}",
                )

    def test_the_frozen_client_is_the_only_outstanding_half(self):
        self.assertEqual({"lcu/lcu_client.py"}, set(_FROZEN_PENDING))


if __name__ == "__main__":
    unittest.main()
