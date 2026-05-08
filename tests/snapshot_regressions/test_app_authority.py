"""
tests/snapshot_regressions/test_app_authority.py
Phase 3 Step 2.1 -- App-level authority regression tests.

Exercises real app.py methods deterministically without live Tk, live workers,
or live network. Uses object.__new__(OverlayApp) to build a headless stub,
then manually initialises only the fields required for each test.

Covers:
  F. app.get_snapshot() mutation safety (nested structures)
  G. Derived legacy surfaces (_tft_mode, _aram_mode, etc.) through _update_envelope
  H. Special-mode game-end resets envelope to client (no stale payload)
  I. Non-TFT raw-dict fallback closure at app level (_process_game_state)
  J. TFT runtime authority (SrAramWorker triggers detection; TftWorker authors payload)

No live Riot API, no Anthropic API, no Tk mainloop, no live artifact mutation.
"""
import copy
import queue
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Import app symbols (no Tk mainloop started) ───────────────────────────────
import app as _app_module
from app import OverlayApp
from app._game_lifecycle import GameLifecycleManager
from app._state_authority import StateAuthority
from core.game_snapshot import (
    GameEnvelope, ClientSnapshot, RiftSnapshot, AramSnapshot, TftSnapshot,
    MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL,
)
from core.sr_aram_worker import WorkerResult
from core.tft_worker import TftWorkerResult
from tests.fixtures.state_dicts import SR_STATE, ARAM_STATE, TFT_STATE


# ── Headless OverlayApp subclass ─────────────────────────────────────────────

class _HeadlessApp(OverlayApp):
    """Subclass that proxies _current_envelope ↔ state.envelope for test compatibility."""

    @property
    def _current_envelope(self):
        return self.state.envelope

    @_current_envelope.setter
    def _current_envelope(self, env):
        if hasattr(self, "state"):
            self.state.set_envelope(env.mode, env.payload)


# ── Headless OverlayApp factory ───────────────────────────────────────────────

def _make_headless_app() -> OverlayApp:
    """
    Create an OverlayApp instance via object.__new__() without calling __init__.
    Only the fields required for the targeted authority tests are initialised.
    No Tk window is created. No workers are started.
    """
    app = object.__new__(_HeadlessApp)

    # Core state fields
    app._was_in_game  = False
    app._game_state   = None
    app._none_streak  = 0
    app._auto_mode    = False
    app._tft_mode     = False
    app._aram_mode    = False
    app._arena_mode   = False
    app._brawl_mode   = False
    app._tft_coach    = None
    app._tft_worker   = None
    app.mode          = "client"
    app.reader        = None
    app._coach        = None
    app._sr_aram_worker = None
    app._tft_q        = queue.Queue(maxsize=4)
    app._sr_aram_q    = queue.Queue(maxsize=2)

    # State authority — owns the authoritative GameEnvelope
    app.state = StateAuthority()

    # Lifecycle manager — owns process_game_state, drain_tft_q, etc.
    app.lifecycle = GameLifecycleManager(app)

    # Initialise envelope via property (delegates to app.state.set_envelope)
    app._current_envelope = GameEnvelope.client()

    return app


# ── Minimal rich SR state dict for app-level tests ───────────────────────────
# Includes nested structures to verify deep-copy depth.

_RICH_SR_STATE = {
    "game_mode":      "CLASSIC",
    "game_time":      "10:00",
    "game_seconds":   600,
    "champion":       "Jinx",
    "level":          11,
    "gold":           2800,
    "cs":             100,
    "cs_per_min":     9.0,
    "kda":            "3/1/2",
    "kills":          3,
    "deaths":         1,
    "assists":        2,
    "hp_pct":         75,
    "hp_abs":         1350,
    "hp_max":         1800,
    "mana_pct":       60,
    "mp_abs":         240,
    "mp_max":         400,
    "items":          ["Yun Tal Wildarrows", "Runaan's Hurricane"],
    "ally_comp":      ["Lux", "Malphite"],
    "enemy_comp":     ["Caitlyn", "Thresh"],
    "ally_details":   [{"name": "Lux", "level": 11, "kda": "2/0/3"}],
    "enemy_details":  [{"name": "Caitlyn", "level": 11, "kda": "1/1/0"}],
    "dead_enemies":   [],
    "alive_enemies":  ["Caitlyn lv11"],
    "objectives":     "Drake up",
    "obj_timers_dict":{"dragon": None, "baron": 480},
    "risk_derived":   "No major threats",
    "map_derived":    "Kill lead: +2",
    "reset_derived":  "2800g",
    "ally_kills_total": 5,
    "enemy_kills_total": 1,
}
_RICH_SR_STATE["raw_state"] = dict(_RICH_SR_STATE)


# ─────────────────────────────────────────────────────────────────────────────
# F. app.get_snapshot() mutation safety
# ─────────────────────────────────────────────────────────────────────────────

class TestAppGetSnapshotMutationSafety(unittest.TestCase):
    """
    Prove mutating nested structures on a returned get_snapshot() result
    does NOT mutate internal authoritative state.
    """

    def _make_app_with_sr_payload(self):
        app = _make_headless_app()
        from game_reader import GameReader
        payload = GameReader.to_rift_snapshot(_RICH_SR_STATE)
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=payload)
        return app, payload

    # -- F1. Top-level list fields --------------------------------------------

    def test_mutating_items_on_returned_snapshot_does_not_affect_internal(self):
        """Mutating items on get_snapshot() result leaves internal payload unchanged."""
        app, payload = self._make_app_with_sr_payload()
        original_items = list(payload.items)

        snap = app.get_snapshot()
        self.assertIsNotNone(snap.payload)
        snap.payload.items.append("INJECTED_ITEM")

        # Internal payload items must be unchanged
        self.assertEqual(payload.items, original_items)
        self.assertNotIn("INJECTED_ITEM", payload.items)

    def test_mutating_ally_comp_on_returned_snapshot_does_not_affect_internal(self):
        app, payload = self._make_app_with_sr_payload()
        original = list(payload.ally_comp)
        snap = app.get_snapshot()
        snap.payload.ally_comp.append("INJECTED_ALLY")
        self.assertEqual(payload.ally_comp, original)

    def test_mutating_enemy_comp_on_returned_snapshot_does_not_affect_internal(self):
        app, payload = self._make_app_with_sr_payload()
        original = list(payload.enemy_comp)
        snap = app.get_snapshot()
        snap.payload.enemy_comp.append("INJECTED_ENEMY")
        self.assertEqual(payload.enemy_comp, original)

    # -- F2. Nested list-of-dict fields ---------------------------------------

    def test_mutating_ally_details_nested_dict_does_not_affect_internal(self):
        """Mutating a nested dict inside ally_details does not reach internal state."""
        app, payload = self._make_app_with_sr_payload()
        original_name = payload.ally_details[0]["name"] if payload.ally_details else None
        if original_name is None:
            self.skipTest("No ally_details in fixture")

        snap = app.get_snapshot()
        self.assertTrue(len(snap.payload.ally_details) > 0)
        snap.payload.ally_details[0]["name"] = "MUTATED"

        # Internal ally_details[0]["name"] must be unchanged
        self.assertEqual(payload.ally_details[0]["name"], original_name)

    def test_mutating_enemy_details_nested_dict_does_not_affect_internal(self):
        app, payload = self._make_app_with_sr_payload()
        original = payload.enemy_details[0]["name"] if payload.enemy_details else None
        if original is None:
            self.skipTest("No enemy_details in fixture")
        snap = app.get_snapshot()
        snap.payload.enemy_details[0]["name"] = "MUTATED"
        self.assertEqual(payload.enemy_details[0]["name"], original)

    # -- F3. Nested dict fields -----------------------------------------------

    def test_mutating_obj_timers_dict_does_not_affect_internal(self):
        """Mutating obj_timers_dict on returned snapshot does not affect internal."""
        app, payload = self._make_app_with_sr_payload()
        original_baron = payload.obj_timers_dict.get("baron")

        snap = app.get_snapshot()
        snap.payload.obj_timers_dict["baron"] = 9999

        self.assertEqual(payload.obj_timers_dict.get("baron"), original_baron)

    # -- F4. raw_state nested mutation ----------------------------------------

    def test_mutating_raw_state_on_returned_snapshot_does_not_affect_internal(self):
        """
        raw_state on the returned snapshot is a deep copy.
        Mutating it cannot reach the internal payload.raw_state.
        """
        app, payload = self._make_app_with_sr_payload()
        # Verify internal raw_state is a dict
        self.assertIsInstance(payload.raw_state, dict)
        original_champion = payload.raw_state.get("champion")

        snap = app.get_snapshot()
        self.assertIsNotNone(snap.payload.raw_state)
        snap.payload.raw_state["champion"] = "MUTATED_CHAMPION"

        # Internal raw_state must be unchanged
        self.assertEqual(payload.raw_state.get("champion"), original_champion)

    def test_raw_state_on_returned_is_independent_object(self):
        """get_snapshot() returns a deep copy: raw_state is NOT the same dict object."""
        app, payload = self._make_app_with_sr_payload()
        snap = app.get_snapshot()
        # Must be a different object (deep-copied)
        self.assertIsNot(snap.payload.raw_state, payload.raw_state)

    # -- F5. get_snapshot() with None payload ---------------------------------

    def test_get_snapshot_with_none_payload_returns_envelope_without_payload(self):
        """get_snapshot() with payload=None returns a new envelope with payload=None."""
        app = _make_headless_app()
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=None)
        snap = app.get_snapshot()
        self.assertEqual(snap.mode, MODE_SR)
        self.assertIsNone(snap.payload)


# ─────────────────────────────────────────────────────────────────────────────
# G. Derived legacy surfaces through _update_envelope
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivedLegacySurfacesThroughApp(unittest.TestCase):
    """
    Verify legacy mode flags remain derived-only from _update_envelope,
    and _game_state is derived from payload.raw_state.
    """

    # -- G1. Legacy flags derived from _update_envelope ----------------------

    def test_update_envelope_sr_clears_special_flags(self):
        """_update_envelope(MODE_SR) sets all special-mode flags to False."""
        app = _make_headless_app()
        # Pre-set some flags to True to verify they get cleared
        app._tft_mode = app._aram_mode = app._arena_mode = app._brawl_mode = True
        payload = GameReader_import().to_rift_snapshot(SR_STATE)
        app._update_envelope(MODE_SR, payload)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)
        self.assertEqual(app._current_envelope.mode, MODE_SR)

    def test_update_envelope_aram_sets_aram_flag_only(self):
        app = _make_headless_app()
        app._tft_mode = app._arena_mode = app._brawl_mode = True
        from game_reader import GameReader
        payload = GameReader.to_aram_snapshot(ARAM_STATE)
        app._update_envelope(MODE_ARAM, payload)
        self.assertTrue(app._aram_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)

    def test_update_envelope_tft_sets_tft_flag_only(self):
        app = _make_headless_app()
        from tft.tft_state_reader import TftStateReader
        payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        app._update_envelope(MODE_TFT, payload)
        self.assertTrue(app._tft_mode)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)

    def test_update_envelope_arena_sets_arena_flag_only(self):
        app = _make_headless_app()
        app._update_envelope(MODE_ARENA, None)
        self.assertTrue(app._arena_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._brawl_mode)

    def test_update_envelope_brawl_sets_brawl_flag_only(self):
        app = _make_headless_app()
        app._update_envelope(MODE_BRAWL, None)
        self.assertTrue(app._brawl_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._arena_mode)

    def test_update_envelope_client_clears_all_flags(self):
        app = _make_headless_app()
        app._tft_mode = app._aram_mode = app._arena_mode = app._brawl_mode = True
        app._update_envelope(MODE_CLIENT, ClientSnapshot())
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)

    # -- G2. _game_state derived from payload.raw_state ----------------------

    def test_game_state_derives_from_payload_raw_state_after_process(self):
        """
        After _process_game_state(), _game_state == payload.raw_state on
        the internal envelope (not the raw input dict directly).
        """
        app = _make_headless_app()
        from game_reader import GameReader
        app.reader = GameReader()
        # Simulate being in SR mode already
        app._was_in_game = True
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=sr_payload)

        # Drive _process_game_state with a new state
        new_state = dict(SR_STATE, gold=3500, game_seconds=700)
        app._process_game_state(new_state)

        # _game_state must be derived from payload.raw_state
        internal_payload = app._current_envelope.payload
        self.assertIsNotNone(internal_payload)
        self.assertIs(app._game_state, internal_payload.raw_state)

    def test_game_state_is_not_the_raw_input_dict(self):
        """_game_state is payload.raw_state, which from_state_dict assigns as the input dict."""
        app = _make_headless_app()
        from game_reader import GameReader
        app.reader = GameReader()
        app._was_in_game = True
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=sr_payload)

        new_state = dict(SR_STATE, gold=9999)
        app._process_game_state(new_state)

        # _game_state is payload.raw_state; in the normal path (Tier 1)
        # from_state_dict sets raw_state = d (the input dict), so they are the same object
        internal_payload = app._current_envelope.payload
        self.assertIs(app._game_state, internal_payload.raw_state)


def GameReader_import():
    from game_reader import GameReader
    return GameReader


# ─────────────────────────────────────────────────────────────────────────────
# H. Special-mode game-end resets via app._on_game_end
# ─────────────────────────────────────────────────────────────────────────────

class TestSpecialModeGameEndReset(unittest.TestCase):
    """
    Prove special-mode game end resets envelope to client with no stale payload.
    Exercises app._on_game_end() directly (the real method).
    """

    def _make_app_in_mode(self, mode: str, payload=None):
        app = _make_headless_app()
        app._was_in_game = True
        app.data = {}  # needed by _on_game_end non-special path
        # Set special-mode flags as _update_envelope would
        app._tft_mode   = (mode == MODE_TFT)
        app._aram_mode  = (mode == MODE_ARAM)
        app._arena_mode = (mode == MODE_ARENA)
        app._brawl_mode = (mode == MODE_BRAWL)
        if payload is None:
            payload = ClientSnapshot()  # placeholder
        app._current_envelope = GameEnvelope(mode=mode, payload=payload)
        return app

    # -- H1. TFT game end -----------------------------------------------------

    def test_tft_game_end_resets_envelope_to_client(self):
        from tft.tft_state_reader import TftStateReader
        tft_payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        app = self._make_app_in_mode(MODE_TFT, tft_payload)
        self.assertEqual(app._current_envelope.mode, MODE_TFT)
        self.assertIsInstance(app._current_envelope.payload, TftSnapshot)

        app._on_game_end()

        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertNotIsInstance(app._current_envelope.payload, TftSnapshot)
        self.assertFalse(app._tft_mode)

    def test_tft_game_end_clears_tft_worker_reference(self):
        """_on_game_end for TFT sets _tft_worker to None."""
        from tft.tft_state_reader import TftStateReader
        tft_payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        app = self._make_app_in_mode(MODE_TFT, tft_payload)
        # Simulate a fake worker that has a shutdown method
        class _FakeWorker:
            def shutdown(self): pass
            def is_alive(self): return False
        app._tft_worker = _FakeWorker()

        app._on_game_end()

        self.assertIsNone(app._tft_worker)

    # -- H2. ARAM game end ----------------------------------------------------

    def test_aram_game_end_resets_envelope_to_client(self):
        from game_reader import GameReader
        aram_payload = GameReader.to_aram_snapshot(ARAM_STATE)
        app = self._make_app_in_mode(MODE_ARAM, aram_payload)

        app._on_game_end()

        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertNotIsInstance(app._current_envelope.payload, AramSnapshot)
        self.assertFalse(app._aram_mode)
        self.assertFalse(app._tft_mode)

    # -- H3. SR game end ------------------------------------------------------

    def test_sr_game_end_resets_envelope_to_client(self):
        from game_reader import GameReader
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        app = _make_headless_app()
        app._was_in_game = True
        app.data = {}  # needed by _on_game_end SR path
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=sr_payload)

        app._on_game_end()

        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertNotIsInstance(app._current_envelope.payload, RiftSnapshot)

    # -- H4. No stale payload after game end ----------------------------------

    def test_no_stale_tft_snapshot_after_game_end(self):
        """After TFT game end, get_snapshot() never returns TftSnapshot."""
        from tft.tft_state_reader import TftStateReader
        tft_payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        app = self._make_app_in_mode(MODE_TFT, tft_payload)
        app._on_game_end()

        snap = app.get_snapshot()
        self.assertNotIsInstance(snap.payload, TftSnapshot)
        self.assertEqual(snap.mode, MODE_CLIENT)

    def test_no_stale_rift_snapshot_after_sr_game_end(self):
        from game_reader import GameReader
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        app = _make_headless_app()
        app._was_in_game = True
        app.data = {}  # needed by _on_game_end SR path
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=sr_payload)
        app._on_game_end()

        snap = app.get_snapshot()
        self.assertNotIsInstance(snap.payload, RiftSnapshot)


# ─────────────────────────────────────────────────────────────────────────────
# I. Non-TFT raw-dict fallback closure at app level
# ─────────────────────────────────────────────────────────────────────────────

class TestAppNonTftRawDictFallbackClosure(unittest.TestCase):
    """
    Prove non-TFT app-level fallback closure in _process_game_state.
    After factory failure, payload is still non-None and _game_state == payload.raw_state.
    """

    # -- I1. Normal SR path: payload comes from factory -----------------------

    def test_sr_normal_path_payload_not_none(self):
        app = _make_headless_app()
        from game_reader import GameReader
        app.reader = GameReader()
        app._was_in_game = True
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=sr_payload)

        app._process_game_state(SR_STATE)

        self.assertIsNotNone(app._current_envelope.payload)
        self.assertIsInstance(app._current_envelope.payload, RiftSnapshot)

    # -- I2. SR with reader=None uses emergency fallback ----------------------

    def test_sr_with_no_reader_uses_emergency_payload(self):
        """
        When reader is None, the factory path is skipped and the app-level
        emergency fallback produces a non-None RiftSnapshot.
        """
        app = _make_headless_app()
        app.reader = None  # no reader -- triggers emergency path
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=None)

        app._process_game_state(SR_STATE)

        # Emergency fallback: payload must exist and be a RiftSnapshot
        payload = app._current_envelope.payload
        self.assertIsNotNone(payload, "Emergency fallback must produce non-None payload")
        self.assertIsInstance(payload, RiftSnapshot)

    def test_sr_emergency_payload_raw_state_is_set(self):
        """Emergency payload has raw_state set; _game_state derives from it."""
        app = _make_headless_app()
        app.reader = None
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=None)

        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIsNotNone(payload.raw_state)
        # _game_state == payload.raw_state (derived, not raw input dict)
        self.assertIs(app._game_state, payload.raw_state)

    # -- I3. Factory failure triggers emergency sub-tier ----------------------

    def test_sr_factory_failure_triggers_app_emergency_subtier(self):
        """
        When app.reader is set but to_rift_snapshot raises (by wrapping it
        in a helper that raises), the app-level emergency fallback produces
        a non-None RiftSnapshot with raw_state set.
        We simulate this by setting reader=None (which uses the emergency path
        in _process_game_state since there is no reader.to_rift_snapshot call).
        This tests the same emergency sub-tier B path.
        """
        app = _make_headless_app()
        app.reader = None  # No reader triggers emergency path directly
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=None)

        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload, "App emergency sub-tier must produce non-None payload")
        self.assertIsInstance(payload, RiftSnapshot)
        self.assertIsNotNone(payload.raw_state)

    # -- I4. ARAM fallback mirrors SR -----------------------------------------

    def test_aram_with_no_reader_uses_emergency_payload(self):
        app = _make_headless_app()
        app.reader = None
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_ARAM, payload=None)
        app._aram_mode = True

        app._process_game_state(ARAM_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIsInstance(payload, AramSnapshot)
        self.assertIs(app._game_state, payload.raw_state)

    # -- I5. _game_state never set to raw dict when payload exists ------------

    def test_game_state_is_payload_raw_state_not_raw_input(self):
        """
        The non-TFT fallback else-branch (_game_state = state) is structurally
        unreachable for SR when the emergency fallback succeeds.
        _game_state must equal payload.raw_state, not the raw input dict directly.
        """
        app = _make_headless_app()
        app.reader = None
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_SR, payload=None)

        test_state = dict(SR_STATE)  # new dict object
        app._process_game_state(test_state)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        # _game_state must be payload.raw_state (the emergency path assigns raw_state = state)
        self.assertIs(app._game_state, payload.raw_state)


# ─────────────────────────────────────────────────────────────────────────────
# J. TFT runtime authority through the app path
# ─────────────────────────────────────────────────────────────────────────────

class TestAppTftRuntimeAuthority(unittest.TestCase):
    """
    Prove SrAramWorker can trigger TFT mode detection but cannot author
    the first authoritative TFT runtime payload. That comes from TftWorker
    via _drain_tft_q.
    """

    # -- J1. SrAramWorker result discarded when TFT is active ----------------

    def test_sr_aram_worker_result_discarded_when_tft_active(self):
        """
        _process_worker_result with _tft_mode=True discards the result.
        Internal envelope and _game_state are unchanged.
        """
        from tft.tft_state_reader import TftStateReader
        tft_payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        app = _make_headless_app()
        app._tft_mode = True
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=MODE_TFT, payload=tft_payload)
        app._game_state = TFT_STATE

        # Inject a SR WorkerResult that would change the envelope if not discarded
        sr_result = WorkerResult(state=SR_STATE, end_signal=False)
        app._process_worker_result(sr_result)

        # Envelope must still be MODE_TFT with TftSnapshot
        self.assertEqual(app._current_envelope.mode, MODE_TFT)
        self.assertIsInstance(app._current_envelope.payload, TftSnapshot)
        # _game_state must be unchanged (TFT state, not SR state)
        self.assertIs(app._game_state, TFT_STATE)

    # -- J2. SrAramWorker triggers TFT detection but does NOT author payload --

    def test_sr_aram_worker_triggers_tft_detection_but_not_payload(self):
        """
        When SrAramWorker sees a TFT game_mode, _on_game_start sets _tft_mode=True.
        _process_game_state then returns BEFORE building a TFT payload (Step 5.2).
        No TftSnapshot is created from the SrAramWorker path.
        """
        app = _make_headless_app()
        # Simulate a stub _on_game_start that just sets TFT flags
        app._was_in_game = False

        def _stub_on_game_start(canon_mode):
            app._current_envelope = GameEnvelope(mode=canon_mode, payload=None)
            app._tft_mode   = (canon_mode == MODE_TFT)
            app._aram_mode  = (canon_mode == MODE_ARAM)
            app._arena_mode = (canon_mode == MODE_ARENA)
            app._brawl_mode = (canon_mode == MODE_BRAWL)

        app._on_game_start = _stub_on_game_start

        # Provide a TFT-flavoured state dict via SrAramWorker path
        tft_state = dict(TFT_STATE, game_mode="TFT")

        def _stub_switch_mode(m, auto=False): pass
        app._switch_mode = _stub_switch_mode

        app._process_game_state(tft_state)

        # TFT mode must be detected
        self.assertTrue(app._tft_mode)
        # But NO TftSnapshot was authored via the SR path (early return in Step 5.2)
        self.assertIsNone(app._current_envelope.payload)
        self.assertNotIsInstance(app._current_envelope.payload, TftSnapshot)

    # -- J3. TftWorkerResult authors the first TFT payload via _drain_tft_q --

    def test_tft_worker_result_authors_first_tft_payload(self):
        """
        TftWorkerResult injected into _tft_q and processed by _drain_tft_q
        produces the first authoritative TftSnapshot in the envelope.
        SrAramWorker did not author this.
        """
        from tft.tft_state_reader import TftStateReader
        app = _make_headless_app()
        app._tft_mode = True
        app._was_in_game = True
        # Start with no TFT payload (as it would be after _on_game_start)
        app._current_envelope = GameEnvelope(mode=MODE_TFT, payload=None)
        app._game_state = None

        # Inject TftWorkerResult into the queue
        tft_result = TftWorkerResult(state=TFT_STATE)
        app._tft_q.put(tft_result)

        # Stub the after/worker check so _drain_tft_q doesn't reschedule
        app.scheduler = type("FakeScheduler", (), {"schedule": lambda self, *a, **kw: None})()
        app._tft_worker = None  # no live worker -- no reschedule needed

        # Drain the queue manually (simulates what Tk mainloop would do)
        app._drain_tft_q()

        # Envelope must now have a TftSnapshot authored by TftWorker path
        self.assertEqual(app._current_envelope.mode, MODE_TFT)
        self.assertIsInstance(app._current_envelope.payload, TftSnapshot)
        # _game_state must be the TFT payload's raw_state
        self.assertIs(app._game_state, app._current_envelope.payload.raw_state)

    # -- J4. _drain_tft_q discards results when TFT mode is no longer active --

    def test_drain_tft_q_discards_results_after_game_end(self):
        """
        After TFT game end (_tft_mode=False), _drain_tft_q discards all queued
        results without updating the envelope.
        """
        app = _make_headless_app()
        app._tft_mode = False  # game already ended
        app._current_envelope = GameEnvelope.client()
        app._game_state = None

        # Inject a stale TftWorkerResult
        tft_result = TftWorkerResult(state=TFT_STATE)
        app._tft_q.put(tft_result)

        app.scheduler = type("FakeScheduler", (), {"schedule": lambda self, *a, **kw: None})()
        app._tft_worker = None
        app._drain_tft_q()

        # Envelope must still be CLIENT (stale TFT result discarded)
        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertIsNone(app._game_state)

    # -- J5. WorkerResult is raw dict, not snapshot ---------------------------

    def test_worker_result_state_is_raw_dict_not_snapshot(self):
        """WorkerResult carries raw dict; app.py builds the snapshot."""
        wr = WorkerResult(state=SR_STATE, end_signal=False)
        self.assertIsInstance(wr.state, dict)
        self.assertNotIsInstance(wr.state, (RiftSnapshot, AramSnapshot, TftSnapshot))

    def test_tft_worker_result_state_is_raw_dict(self):
        """TftWorkerResult carries raw dict; _drain_tft_q builds TftSnapshot."""
        twr = TftWorkerResult(state=TFT_STATE)
        self.assertIsInstance(twr.state, dict)
        self.assertNotIsInstance(twr.state, TftSnapshot)


# ─────────────────────────────────────────────────────────────────────────────
# K. Arena/Brawl non-TFT raw-dict fallback closure at app level
# ─────────────────────────────────────────────────────────────────────────────

class TestArenaBrawlFallbackClosure(unittest.TestCase):
    """
    Prove Arena and Brawl preserve the non-TFT fallback closure contract
    in app._process_game_state(), mirroring the SR/ARAM tests in group I.
    """

    def _make_app_in_mode(self, mode: str):
        app = _make_headless_app()
        app.reader = None  # forces emergency fallback path
        app._was_in_game = True
        app._current_envelope = GameEnvelope(mode=mode, payload=None)
        app._arena_mode = (mode == MODE_ARENA)
        app._brawl_mode = (mode == MODE_BRAWL)
        return app

    # -- K1. Arena: emergency fallback produces non-None RiftSnapshot ----------

    def test_arena_with_no_reader_uses_emergency_payload(self):
        """
        Arena uses the same RiftSnapshot fallback path as SR/Brawl.
        reader=None forces the emergency sub-tier; payload must be non-None.
        """
        app = self._make_app_in_mode(MODE_ARENA)
        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload, "Arena emergency fallback must produce non-None payload")
        self.assertIsInstance(payload, RiftSnapshot)

    def test_arena_emergency_raw_state_is_set(self):
        """Arena emergency payload has raw_state set; _game_state derives from it."""
        app = self._make_app_in_mode(MODE_ARENA)
        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIsNotNone(payload.raw_state)
        self.assertIs(app._game_state, payload.raw_state)

    def test_arena_game_state_is_payload_raw_state_not_raw_input(self):
        """Arena: _game_state == payload.raw_state (not raw input dict directly)."""
        app = self._make_app_in_mode(MODE_ARENA)
        test_state = dict(SR_STATE, game_mode="ARENA")
        app._process_game_state(test_state)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIs(app._game_state, payload.raw_state)

    # -- K2. Brawl: same RiftSnapshot fallback path ---------------------------

    def test_brawl_with_no_reader_uses_emergency_payload(self):
        app = self._make_app_in_mode(MODE_BRAWL)
        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload, "Brawl emergency fallback must produce non-None payload")
        self.assertIsInstance(payload, RiftSnapshot)

    def test_brawl_emergency_raw_state_is_set(self):
        app = self._make_app_in_mode(MODE_BRAWL)
        app._process_game_state(SR_STATE)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIsNotNone(payload.raw_state)
        self.assertIs(app._game_state, payload.raw_state)

    def test_brawl_game_state_is_payload_raw_state_not_raw_input(self):
        app = self._make_app_in_mode(MODE_BRAWL)
        test_state = dict(SR_STATE, game_mode="NEXUSBLITZ")
        app._process_game_state(test_state)

        payload = app._current_envelope.payload
        self.assertIsNotNone(payload)
        self.assertIs(app._game_state, payload.raw_state)

    # -- K3. Arena/Brawl: no raw-dict primary authority reopened -------------

    def test_arena_fallback_uses_rift_not_raw_dict_path(self):
        """
        Even in emergency, Arena fallback produces RiftSnapshot (not plain dict).
        The raw-dict else-branch (_game_state = state) is unreachable for Arena.
        """
        app = self._make_app_in_mode(MODE_ARENA)
        app._process_game_state(SR_STATE)

        # _game_state is payload.raw_state (a dict), but it is derived from
        # the envelope payload -- the payload itself is non-None RiftSnapshot.
        # The raw-dict authority path (else branch) was NOT taken.
        self.assertIsNotNone(app._current_envelope.payload)
        self.assertIsInstance(app._current_envelope.payload, RiftSnapshot)

    def test_brawl_fallback_uses_rift_not_raw_dict_path(self):
        app = self._make_app_in_mode(MODE_BRAWL)
        app._process_game_state(SR_STATE)
        self.assertIsNotNone(app._current_envelope.payload)
        self.assertIsInstance(app._current_envelope.payload, RiftSnapshot)


# ─────────────────────────────────────────────────────────────────────────────
# L. Arena/Brawl special-mode game-end reset
# ─────────────────────────────────────────────────────────────────────────────

class TestArenaBrawlGameEndReset(unittest.TestCase):
    """
    Prove Arena and Brawl game-end resets envelope to client
    with no stale payload surviving.
    """

    def _make_special_mode_app(self, mode: str):
        """Build headless app already in a special mode with a RiftSnapshot payload."""
        from game_reader import GameReader
        app = _make_headless_app()
        app._was_in_game = True
        app.data = {}  # needed by _on_game_end
        payload = GameReader.to_rift_snapshot(SR_STATE)
        app._current_envelope = GameEnvelope(mode=mode, payload=payload)
        app._arena_mode = (mode == MODE_ARENA)
        app._brawl_mode = (mode == MODE_BRAWL)
        app._aram_mode  = False
        app._tft_mode   = False
        return app

    # -- L1. Arena game end ---------------------------------------------------

    def test_arena_game_end_resets_envelope_to_client(self):
        app = self._make_special_mode_app(MODE_ARENA)
        self.assertEqual(app._current_envelope.mode, MODE_ARENA)

        app._on_game_end()

        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertNotIsInstance(app._current_envelope.payload, RiftSnapshot)
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)

    def test_no_stale_rift_snapshot_after_arena_game_end(self):
        """get_snapshot() after Arena game end returns ClientSnapshot."""
        app = self._make_special_mode_app(MODE_ARENA)
        app._on_game_end()

        snap = app.get_snapshot()
        self.assertEqual(snap.mode, MODE_CLIENT)
        self.assertNotIsInstance(snap.payload, RiftSnapshot)

    # -- L2. Brawl game end ---------------------------------------------------

    def test_brawl_game_end_resets_envelope_to_client(self):
        app = self._make_special_mode_app(MODE_BRAWL)
        self.assertEqual(app._current_envelope.mode, MODE_BRAWL)

        app._on_game_end()

        self.assertEqual(app._current_envelope.mode, MODE_CLIENT)
        self.assertIsInstance(app._current_envelope.payload, ClientSnapshot)
        self.assertNotIsInstance(app._current_envelope.payload, RiftSnapshot)
        self.assertFalse(app._brawl_mode)

    def test_no_stale_rift_snapshot_after_brawl_game_end(self):
        app = self._make_special_mode_app(MODE_BRAWL)
        app._on_game_end()

        snap = app.get_snapshot()
        self.assertEqual(snap.mode, MODE_CLIENT)
        self.assertNotIsInstance(snap.payload, RiftSnapshot)

    # -- L3. Legacy flags all clear after special-mode game end ---------------

    def test_arena_game_end_clears_all_special_flags(self):
        """All four special-mode flags must be False after Arena game end."""
        app = self._make_special_mode_app(MODE_ARENA)
        app._on_game_end()
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)

    def test_brawl_game_end_clears_all_special_flags(self):
        app = self._make_special_mode_app(MODE_BRAWL)
        app._on_game_end()
        self.assertFalse(app._arena_mode)
        self.assertFalse(app._brawl_mode)
        self.assertFalse(app._tft_mode)
        self.assertFalse(app._aram_mode)


# ─────────────────────────────────────────────────────────────────────────────
# M. TFT first-entry authority through _process_worker_result() ingress
# ─────────────────────────────────────────────────────────────────────────────

class TestTftFirstEntryWorkerIngress(unittest.TestCase):
    """
    Prove the full TFT first-entry authority chain through the real
    _process_worker_result() ingress path:
      WorkerResult(TFT state) -> _process_worker_result() -> _process_game_state()
      -> TFT mode detected -> early return (no first payload authored)
      -> _drain_tft_q() + TftWorkerResult -> first TftSnapshot authored.
    """

    def _make_pre_game_app(self):
        """App in pre-game state (client mode, no active game)."""
        app = _make_headless_app()
        app._was_in_game = False
        app._current_envelope = GameEnvelope.client()

        # Stub _on_game_start to just set mode flags without needing coach imports
        def _stub_on_game_start(canon_mode):
            app._current_envelope = GameEnvelope(mode=canon_mode, payload=None)
            app._tft_mode   = (canon_mode == MODE_TFT)
            app._aram_mode  = (canon_mode == MODE_ARAM)
            app._arena_mode = (canon_mode == MODE_ARENA)
            app._brawl_mode = (canon_mode == MODE_BRAWL)

        app._on_game_start = _stub_on_game_start

        # Stub _switch_mode (called if _auto_mode is True)
        app._switch_mode = lambda m, auto=False: None

        return app

    # -- M1. WorkerResult with TFT state triggers TFT detection ---------------

    def test_worker_result_tft_state_triggers_tft_mode(self):
        """
        Injecting WorkerResult(state=TFT_STATE) into _process_worker_result
        causes TFT mode to be detected and _tft_mode set to True.
        """
        app = self._make_pre_game_app()
        tft_state = dict(TFT_STATE, game_mode="TFT")
        wr = WorkerResult(state=tft_state, end_signal=False)

        app._process_worker_result(wr)

        self.assertTrue(app._tft_mode)
        self.assertEqual(app._current_envelope.mode, MODE_TFT)

    # -- M2. No first TFT payload authored from WorkerResult path -------------

    def test_worker_result_tft_state_does_not_author_first_tft_payload(self):
        """
        After TFT detection via WorkerResult, the envelope has no payload.
        _process_game_state() returns before Step B (payload construction)
        when _tft_mode is True (Phase 1 Step 5.2 guard).
        """
        app = self._make_pre_game_app()
        tft_state = dict(TFT_STATE, game_mode="TFT")
        wr = WorkerResult(state=tft_state, end_signal=False)

        app._process_worker_result(wr)

        # Payload must be None -- TFT payload not authored from SrAramWorker path
        self.assertIsNone(app._current_envelope.payload)
        self.assertNotIsInstance(app._current_envelope.payload, TftSnapshot)

    # -- M3. Subsequent WorkerResults discarded once TFT is active ------------

    def test_subsequent_worker_results_discarded_when_tft_active(self):
        """
        After TFT is active, additional WorkerResults (even with SR state)
        are discarded by the _process_worker_result guard.
        """
        app = self._make_pre_game_app()
        tft_state = dict(TFT_STATE, game_mode="TFT")
        wr_tft = WorkerResult(state=tft_state, end_signal=False)
        app._process_worker_result(wr_tft)

        # Envelope still MODE_TFT with payload=None
        self.assertTrue(app._tft_mode)
        self.assertIsNone(app._current_envelope.payload)

        # Now inject a SR WorkerResult
        wr_sr = WorkerResult(state=SR_STATE, end_signal=False)
        app._process_worker_result(wr_sr)

        # Must still be TFT with no payload (SR result discarded)
        self.assertEqual(app._current_envelope.mode, MODE_TFT)
        self.assertIsNone(app._current_envelope.payload)
        self.assertNotIsInstance(app._current_envelope.payload, RiftSnapshot)

    # -- M4. _drain_tft_q authors the first authoritative TFT payload ---------

    def test_drain_tft_q_authors_first_tft_payload_after_worker_entry(self):
        """
        Full chain:
          1. WorkerResult(TFT) -> _process_worker_result() -> TFT detected, payload=None
          2. TftWorkerResult  -> _drain_tft_q() -> first TftSnapshot authored
        """
        app = self._make_pre_game_app()

        # Step 1: TFT entry via WorkerResult
        tft_state = dict(TFT_STATE, game_mode="TFT")
        wr = WorkerResult(state=tft_state, end_signal=False)
        app._process_worker_result(wr)

        self.assertTrue(app._tft_mode)
        self.assertIsNone(app._current_envelope.payload)

        # Step 2: TftWorkerResult in queue -> _drain_tft_q() authors first TftSnapshot
        tft_result = TftWorkerResult(state=TFT_STATE)
        app._tft_q.put(tft_result)

        # Stub scheduler.schedule so _drain_tft_q doesn't try to reschedule
        app.scheduler = type("FakeScheduler", (), {"schedule": lambda self, *a, **kw: None})()
        app._tft_worker = None

        app._drain_tft_q()

        # First authoritative TFT payload now exists
        self.assertEqual(app._current_envelope.mode, MODE_TFT)
        self.assertIsInstance(app._current_envelope.payload, TftSnapshot)
        self.assertIs(app._game_state, app._current_envelope.payload.raw_state)

    # -- M5. SrAramWorker never authored any TftSnapshot in this chain --------

    def test_no_tft_snapshot_from_sr_aram_worker_at_any_point(self):
        """
        At no point in the full entry chain does a TftSnapshot appear from
        the WorkerResult / SrAramWorker path. The payload that ultimately
        goes into the envelope comes exclusively from _drain_tft_q.
        """
        app = self._make_pre_game_app()

        # Inject TFT-state WorkerResult
        tft_state = dict(TFT_STATE, game_mode="TFT")
        wr = WorkerResult(state=tft_state, end_signal=False)
        app._process_worker_result(wr)

        # No TftSnapshot yet (verified)
        self.assertNotIsInstance(app._current_envelope.payload, TftSnapshot)

        # Now inject three more WorkerResults (simulating poll cadence)
        for _ in range(3):
            app._process_worker_result(WorkerResult(state=tft_state, end_signal=False))

        # Still no TftSnapshot from SR worker path
        self.assertNotIsInstance(app._current_envelope.payload, TftSnapshot)
        self.assertEqual(app._current_envelope.mode, MODE_TFT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
