"""/api/state.lcu.phase carries no truthy non-phase sentinel (RM-382, RM-293b).

RM-367 settled the rule for this field on the CONSUMER contract: a value that
names no LCU gameflow phase must be FALSY, emitted as Python None. Two
producers still broke it after RM-367 shipped:

  * ``lcu/snapshot_shape.shape_snapshot`` emitted ``"Unknown"`` for a
    non-str/non-bytes gameflow body - which is what a FAILED request returns
    (``lcu/lcu_client.py`` answers None, ``dashboard/_lcu_inprocess.py``
    forwards it verbatim), so a single timed-out GET on an otherwise fresh
    snapshot published a truthy non-phase.
  * ``tools/lcu_agent.capture_state`` emitted ``"Offline"`` when the lockfile
    was absent, short-circuiting before the shaper - so fixing the shaper
    alone would have left this half live.

THE DECISION: both join the RM-367 falsy no-phase. Every consumer was read:

  * ``web/js/main.js`` ``_viewAutoDerive`` (``const phase = lcu && lcu.phase``)
    - the s209 sticky-guard inference and the item-281 null-phase in-game
    promotion both test ``!phase``, and NO arm names "Offline" or "Unknown".
    A truthy sentinel only DISARMED them (falls through to ``return prior``).
  * ``web/js/main.js`` ``_homeShouldShow``, the ``lcuPhase`` ctx fed to
    ``web/js/panels/active_match.js`` (``|| "-"``), ``panels/champ_select.js``
    and ``panels/team_context.js`` compare against real phase names only, so
    None and the sentinels render identically there.
  * ``dashboard/_cs_retention.py`` ``_CLEAR_PHASES`` holds neither sentinel
    nor None - no behaviour change.
  * ``agents/agent2_backend/file_ingest._compute_effective_mode`` compares
    against ChampSelect / GameStart / InProgress only - no change.
  * ``tools/lcu_agent`` ``_maybe_refresh_team_context`` /
    ``_maybe_ingest_last_match`` read ``state.get("phase") or ""`` - no change.
  * ``dashboard/routes_state._timed_build_state`` and ``tools/rc_facts.py``
    print the phase for diagnostics (``or "?"``). These are the ONLY
    consumers that lose a word: a closed client now reads ``phase=?``.
  * ``web/legacy_index.html`` (``?ui=legacy`` fallback only) had a label for
    both sentinels; a falsy phase now takes its pre-existing no-phase branch.

"Client closed" stays STRUCTURALLY distinguishable without a truthy phase:
both producers stamp ``lcu_port`` if and only if a connection exists
(``tools/lcu_agent.capture_state`` after ``ensure_lcu_conn``,
``dashboard/_lcu_inprocess.lcu_summary_inprocess`` after ``client._port``),
so an offline snapshot is ``config`` + ``ts`` with no ``lcu_port``. That is
pinned below rather than a new key no consumer asked for.

RM-293(b): the bytes branch decoded with a bare strict ``bytes.decode()``, so
an invalid-UTF-8 body raised out of the shaper and cost the whole snapshot for
the tick. The fix returns None, NOT ``errors="replace"``: a replaced body is a
truthy garbage string - exactly the sentinel class this file forbids.

All authored content here is 7-bit ASCII.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import lcu_agent as agent  # noqa: E402
from dashboard.view_router_state import (  # noqa: E402
    derive_view,
    update_game_started,
)
from lcu.snapshot_shape import (  # noqa: E402
    _reset_mastery_cache_for_tests,
    _reset_summoner_lookup_cache_for_tests,
    shape_snapshot,
)

_PHASE = "/lol-gameflow/v1/gameflow-phase"


def _fake_request(phase_body):
    def request(method, path, body=None):
        if path == _PHASE:
            return phase_body, None
        return None, "404"

    return request


def _reset() -> None:
    _reset_mastery_cache_for_tests()
    _reset_summoner_lookup_cache_for_tests()


def _shape(phase_body) -> dict:
    _reset()
    try:
        return shape_snapshot(_fake_request(phase_body), {})
    finally:
        _reset()


def _offline_agent_snapshot() -> dict:
    _reset()
    try:
        with mock.patch.object(agent, "ensure_lcu_conn", return_value=False):
            return agent.capture_state()
    finally:
        _reset()


class ShaperUnreadableBodyIsNoPhaseTest(unittest.TestCase):
    """Site (1): the shaper's non-str/non-bytes branch."""

    def test_failed_request_body_is_not_a_truthy_phase(self):
        """A failed GET answers None; pre-fix this published "Unknown"."""
        self.assertIsNone(_shape(None)["phase"])

    def test_every_non_text_body_type_is_no_phase(self):
        for body in ({"phase": "Lobby"}, ["Lobby"], 0, 1, 1.5, True):
            with self.subTest(body=body):
                self.assertIsNone(_shape(body)["phase"])

    def test_breadcrumb_follows_phase(self):
        snap = _shape(None)
        self.assertIsNone(snap["cs_debug"]["raw_phase"])

    def test_real_phase_untouched(self):
        self.assertEqual(_shape('"ChampSelect"')["phase"], "ChampSelect")
        self.assertEqual(_shape(b'"InProgress"')["phase"], "InProgress")
        self.assertEqual(_shape('"None"')["phase"], "None")


class ShaperInvalidUtf8IsNoPhaseTest(unittest.TestCase):
    """RM-293(b): an invalid-UTF-8 bytes body must not raise out."""

    def test_invalid_utf8_body_does_not_raise(self):
        snap = _shape(b'"\xff\xfeLobby"')
        self.assertIn("ts", snap, "the rest of the snapshot must still build")

    def test_invalid_utf8_body_is_no_phase_not_replacement_garbage(self):
        self.assertIsNone(_shape(b'"\xff\xfeLobby"')["phase"])
        self.assertIsNone(_shape(b"\x80")["phase"])


class AgentOfflineIsNoPhaseTest(unittest.TestCase):
    """Site (2): the agent's lockfile-absent short-circuit."""

    def test_offline_phase_is_falsy_none(self):
        self.assertIsNone(_offline_agent_snapshot()["phase"])

    def test_client_closed_stays_structurally_distinguishable(self):
        """No truthy phase needed: offline == no ``lcu_port`` key."""
        st = _offline_agent_snapshot()
        self.assertNotIn("lcu_port", st)
        self.assertIn("config", st)
        self.assertIn("ts", st)


class ProducerOutputFiresTheNoPhaseArmsTest(unittest.TestCase):
    """Drive the view-router mirror with the PRODUCERS' actual output.

    ``dashboard/view_router_state`` is the pytest mirror of
    ``web/js/main.js`` ``_viewAutoDerive``; the JS half is ``!phase`` on
    ``lcu && lcu.phase``, where None serialises to ``null`` - falsy.
    """

    def _producer_phases(self):
        return {
            "shaper-failed-request": _shape(None)["phase"],
            "shaper-invalid-utf8": _shape(b"\xff")["phase"],
            "agent-offline": _offline_agent_snapshot()["phase"],
        }

    def test_s209_sticky_guard_arm_fires(self):
        for name, phase in self._producer_phases().items():
            with self.subTest(producer=name):
                self.assertEqual(update_game_started(phase, "champ-select", live=True), "in-progress")

    def test_item_281_promotion_arm_fires(self):
        """The live bite: game running, League client closed or wedged."""
        for name, phase in self._producer_phases().items():
            with self.subTest(producer=name):
                self.assertEqual(update_game_started(phase, None, live=True, mode="aram"), "in-progress")
                res = derive_view(phase, "aram", None, live=True)
                self.assertEqual(res.view, "active-match")
                self.assertEqual(res.game_started, "in-progress")

    def test_live_gate_still_holds(self):
        for name, phase in self._producer_phases().items():
            with self.subTest(producer=name):
                self.assertEqual(update_game_started(phase, "champ-select", live=False), "champ-select")


# -- census: no NEW hard-coded phase string without a decision --------------

# Producers of the /api/state.lcu snapshot (agent relay path + in-process
# path + the shared shaper). A hard-coded ``"phase"`` string value in any of
# them is a sentinel by construction - a real phase is always READ from LCU.
_PRODUCERS = (
    "lcu/snapshot_shape.py",
    "tools/lcu_agent.py",
    "dashboard/_lcu_inprocess.py",
)

# Deliberately empty. Adding a string here IS the decision the row demands:
# prove every ``!phase`` arm in web/js/main.js handles it first.
_ALLOWED_PHASE_LITERALS: frozenset = frozenset()


def _phase_writes(tree: ast.AST):
    """Yield (lineno, value_node) for every write of the ``"phase"`` key."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == "phase"
                ):
                    yield node.lineno, node.value
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "phase":
                    yield node.lineno, v


class PhaseSentinelCensusTest(unittest.TestCase):
    def test_no_producer_hardcodes_a_phase_string(self):
        offenders = []
        writes_per_file = {}
        for rel in _PRODUCERS:
            path = _PROJECT_ROOT / rel
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            writes_per_file[rel] = 0
            for lineno, value in _phase_writes(tree):
                writes_per_file[rel] += 1
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value not in _ALLOWED_PHASE_LITERALS
                ):
                    offenders.append(f"{rel}:{lineno} {value.value!r}")
        # Anchor: an empty enumeration would pass vacuously. The two files
        # that WRITE the field must each have been seen writing it (the
        # in-process path delegates to the shaper and writes none itself).
        self.assertGreaterEqual(writes_per_file["lcu/snapshot_shape.py"], 1)
        self.assertGreaterEqual(writes_per_file["tools/lcu_agent.py"], 1)
        self.assertEqual(offenders, [])

    def test_census_catches_a_planted_sentinel(self):
        """Positive control: the scanner flags the exact pre-fix shape."""
        planted = ast.parse('state = {}\nstate["phase"] = "Offline"\n')
        found = [v.value for _, v in _phase_writes(planted) if isinstance(v, ast.Constant)]
        self.assertEqual(found, ["Offline"])
        planted_dict = ast.parse('x = {"phase": "Unknown"}\n')
        found = [v.value for _, v in _phase_writes(planted_dict) if isinstance(v, ast.Constant)]
        self.assertEqual(found, ["Unknown"])


if __name__ == "__main__":
    unittest.main()
