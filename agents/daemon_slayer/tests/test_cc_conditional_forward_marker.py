"""ENGINE 1.37.0 (2026-05-22) - cc_conditional FORWARD-MARKER guard.

The ``cc_conditional`` module ships at 1.37.0 as a FORWARD-MARKER
seam: it carries the schema + machinery + a 10-entry seed but NO
consumer wires to it. These tests pin that boundary so future
agents do not silently wire a consumer in the same engine bump that
ships new conditional CC entries (the operator gate is between the
data lane and the consumer lane).

This mirrors the pre-1.32.0 state of ``_PER_SPELL_CC_DURATIONS``
(seeded at 1.30.0 with no consumer until ``compute_cc_pressure``
shipped at 1.32.0). The conditional axis is operator-gated through
items 138/139/140 carries; the consumer wire is a separate slice.

Coverage classes:
  * ``NoConsumerWireTests`` - no file in ``agents/daemon_slayer/``
    other than the test files imports from ``cc_conditional``.
  * ``DocstringStatesForwardMarkerTests`` - the module docstring
    declares the forward-marker contract so future readers know
    not to wire consumers without operator gating.
"""

from __future__ import annotations

import pathlib
import unittest


# ---------------- repo root + DS package root ----------------


_THIS_FILE = pathlib.Path(__file__).resolve()
_DS_PACKAGE = _THIS_FILE.parent.parent  # agents/daemon_slayer/
_REPO_ROOT = _DS_PACKAGE.parent.parent   # repo root


# Test files allowed to import from cc_conditional. Any other
# .py file under agents/daemon_slayer/ that imports the module
# is a NEW consumer wire and the operator gate has been crossed.
_ALLOWED_TEST_FILES = {
    "test_cc_conditional.py",
    "test_cc_conditional_forward_marker.py",
}


def _iter_ds_python_files() -> list[pathlib.Path]:
    """Return every .py under agents/daemon_slayer/ except __pycache__."""
    out = []
    for p in _DS_PACKAGE.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        out.append(p)
    return out


# ---------------- no-consumer-wire contract ----------------


class NoConsumerWireTests(unittest.TestCase):
    """No file other than the new test files imports cc_conditional.

    This pins the forward-marker boundary. When a future slice wires
    a consumer (e.g. ``compute_cc_pressure`` reads conditional entries
    or a fight-sim weighted-sums them), that slice should update this
    allow-list in the SAME commit and explain the operator gate in
    its CLAUDE.md ledger entry.
    """

    def test_no_unauthorized_consumer_imports(self) -> None:
        offenders = []
        for py_file in _iter_ds_python_files():
            # Skip the cc_conditional module itself.
            if py_file.name == "cc_conditional.py":
                continue
            # Skip allowed test files.
            if py_file.name in _ALLOWED_TEST_FILES:
                continue
            text = py_file.read_text(encoding="utf-8")
            # Two import shapes catch every consumer:
            #   from agents.daemon_slayer.cc_conditional import ...
            #   from .cc_conditional import ...
            #   import agents.daemon_slayer.cc_conditional
            if "cc_conditional" in text:
                offenders.append(py_file.relative_to(_REPO_ROOT))
        self.assertEqual(
            offenders, [],
            (
                "Unauthorized consumer wire to cc_conditional. The module "
                "is a forward-marker seam; the operator gate must be "
                "crossed before any consumer reads it. Offenders: "
                f"{offenders}"
            ),
        )

    def test_cc_pressure_does_not_import_cc_conditional(self) -> None:
        # cc_pressure.py is the most likely future consumer.
        # Pin its current state until the operator authorizes the wire.
        cc_pressure = _DS_PACKAGE / "cc_pressure.py"
        self.assertTrue(
            cc_pressure.exists(),
            "cc_pressure.py missing; expected the unconditional CC "
            "aggregator to exist",
        )
        text = cc_pressure.read_text(encoding="utf-8")
        self.assertNotIn(
            "cc_conditional", text,
            "cc_pressure.py imports cc_conditional; the operator gate "
            "must be crossed before this wire ships",
        )

    def test_ehp_does_not_import_cc_conditional(self) -> None:
        # ehp.py is the other natural consumer (EHP-vs-CC blended).
        ehp_file = _DS_PACKAGE / "ehp.py"
        self.assertTrue(ehp_file.exists(), "ehp.py missing")
        text = ehp_file.read_text(encoding="utf-8")
        self.assertNotIn(
            "cc_conditional", text,
            "ehp.py imports cc_conditional; the operator gate must "
            "be crossed before this wire ships",
        )

    def test_ability_dps_does_not_import_cc_conditional(self) -> None:
        # ability_dps.py owns _PER_SPELL_CC_DURATIONS; the seam is
        # explicitly NOT here either.
        ad_file = _DS_PACKAGE / "ability_dps.py"
        self.assertTrue(ad_file.exists(), "ability_dps.py missing")
        text = ad_file.read_text(encoding="utf-8")
        self.assertNotIn(
            "cc_conditional", text,
            "ability_dps.py imports cc_conditional; the operator "
            "gate must be crossed before this wire ships",
        )

    def test_engine_does_not_import_cc_conditional(self) -> None:
        engine_file = _DS_PACKAGE / "engine.py"
        self.assertTrue(engine_file.exists(), "engine.py missing")
        text = engine_file.read_text(encoding="utf-8")
        self.assertNotIn(
            "cc_conditional", text,
            "engine.py imports cc_conditional; the operator gate "
            "must be crossed before this wire ships",
        )


# ---------------- docstring contract ----------------


class DocstringStatesForwardMarkerTests(unittest.TestCase):
    """The module docstring declares the forward-marker contract.

    Future readers (Claude orchestrators / human ops) should be able
    to grep the module's own docstring for the contract and not have
    to read this test file to learn it.
    """

    def setUp(self) -> None:
        self.module_path = _DS_PACKAGE / "cc_conditional.py"
        self.assertTrue(self.module_path.exists(), "module missing")
        self.text = self.module_path.read_text(encoding="utf-8")

    def test_docstring_mentions_forward_marker(self) -> None:
        # Case-insensitive scan covers FORWARD-MARKER / forward-marker /
        # Forward-Marker variants.
        self.assertIn(
            "FORWARD-MARKER",
            self.text,
            "module docstring does not state the forward-marker contract",
        )

    def test_docstring_says_no_consumer_wires_today(self) -> None:
        # The phrase "no consumer wires to it yet" (or equivalent)
        # should appear so future readers understand the boundary.
        lowered = self.text.lower()
        self.assertTrue(
            (
                "no consumer wires to it yet" in lowered
                or "no consumer wires" in lowered
            ),
            "module docstring does not declare no-consumer-wire state",
        )

    def test_docstring_references_prior_empty_seam_pattern(self) -> None:
        # Should reference the prior empty-seam precedents
        # (STAT_GRANT_CALC_KEYS at 1.22.0 / _PER_SPELL_CC_DURATIONS
        # pre-1.30.0). This grounds the pattern for future readers.
        self.assertIn(
            "STAT_GRANT_CALC_KEYS",
            self.text,
            "module docstring does not reference prior empty-seam pattern",
        )


if __name__ == "__main__":
    unittest.main()
