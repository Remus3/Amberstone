"""
tests/snapshot_regressions/test_snapshot_authority.py
Phase 3 Step 2 -- Deterministic snapshot regression harness.

Covers:
  A. Snapshot translation goldens (SR/ARAM/TFT/Client)
  B. Envelope authority and mode transitions
  C. Derived compatibility surfaces
  D. Non-TFT raw-dict fallback closure
  E. TFT runtime authority boundary

No live Riot API, no Anthropic API, no Tk, no internet.
No live project artifact mutation.
Project root resolved relative to this file.
"""
import json
import sys
import unittest
from pathlib import Path

# Resolve project root from this file's location (tests/snapshot_regressions/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.game_snapshot import (
    GameEnvelope, ClientSnapshot, RiftSnapshot, AramSnapshot, TftSnapshot,
    MODE_CLIENT, MODE_SR, MODE_ARAM, MODE_TFT, MODE_ARENA, MODE_BRAWL,
    ALL_MODES, mode_from_game_mode_string,
)
from game_reader import GameReader
from tft.tft_state_reader import TftStateReader
from tests.fixtures.state_dicts import SR_STATE, ARAM_STATE, TFT_STATE, ARENA_STATE, BRAWL_STATE

_GOLDEN_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "snapshots"


def _load_golden(name: str) -> dict:
    return json.loads((_GOLDEN_DIR / name).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# A. Snapshot translation goldens
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshotTranslationGoldens(unittest.TestCase):
    """Verify translation helpers produce payloads that match golden fixtures."""

    # -- A1. ClientSnapshot ---------------------------------------------------

    def test_client_envelope_snapshot_type(self):
        """GameEnvelope.client() produces a ClientSnapshot payload."""
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)
        self.assertIsInstance(env.payload, ClientSnapshot)
        d = env.payload.to_dict()
        self.assertEqual(d["snapshot_type"], "client")

    def test_client_golden(self):
        g = _load_golden("client_golden.json")
        env = GameEnvelope.client()
        d = env.payload.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(env.mode, g["mode"])

    # -- A2. SR / RiftSnapshot ------------------------------------------------

    def test_sr_translation_type(self):
        """to_rift_snapshot returns a RiftSnapshot instance."""
        s = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIsInstance(s, RiftSnapshot)

    def test_sr_golden_fields(self):
        g = _load_golden("sr_golden.json")
        s = GameReader.to_rift_snapshot(SR_STATE)
        d = s.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(d["game_mode"],     g["game_mode"])
        self.assertEqual(d["champion"],      g["champion"])
        self.assertEqual(d["level"],         g["level"])
        self.assertEqual(d["gold"],          g["gold"])
        self.assertEqual(d["cs"],            g["cs"])
        self.assertEqual(d["hp_pct"],        g["hp_pct"])
        self.assertEqual(d["kda"],           g["kda"])
        self.assertEqual(d["items"],         g["items"])
        self.assertEqual(d["ally_comp"],     g["ally_comp"])
        self.assertEqual(d["enemy_comp"],    g["enemy_comp"])

    def test_sr_raw_state_stored(self):
        """RiftSnapshot must store raw_state for legacy consumers."""
        s = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIsNotNone(s.raw_state)
        self.assertIsInstance(s.raw_state, dict)

    def test_sr_none_input_returns_none(self):
        """to_rift_snapshot(None) returns None immediately."""
        self.assertIsNone(GameReader.to_rift_snapshot(None))

    # -- A3. ARAM / AramSnapshot ----------------------------------------------

    def test_aram_translation_type(self):
        s = GameReader.to_aram_snapshot(ARAM_STATE)
        self.assertIsInstance(s, AramSnapshot)

    def test_aram_golden_fields(self):
        g = _load_golden("aram_golden.json")
        s = GameReader.to_aram_snapshot(ARAM_STATE)
        d = s.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(d["game_mode"],     g["game_mode"])
        self.assertEqual(d["champion"],      g["champion"])
        self.assertEqual(d["level"],         g["level"])
        self.assertEqual(d["gold"],          g["gold"])
        self.assertEqual(d["hp_pct"],        g["hp_pct"])
        # AramSnapshot.to_dict() does not include kda; check via snapshot field directly
        self.assertEqual(s.kda,              g["kda"])
        self.assertEqual(d["items"],         g["items"])
        self.assertEqual(d["ally_comp"],     g["ally_comp"])
        self.assertEqual(d["enemy_comp"],    g["enemy_comp"])

    def test_aram_raw_state_stored(self):
        s = GameReader.to_aram_snapshot(ARAM_STATE)
        self.assertIsNotNone(s.raw_state)
        self.assertIsInstance(s.raw_state, dict)

    def test_aram_none_input_returns_none(self):
        self.assertIsNone(GameReader.to_aram_snapshot(None))

    # -- A4. TFT / TftSnapshot ------------------------------------------------

    def test_tft_translation_type(self):
        s = TftStateReader.to_tft_snapshot(TFT_STATE)
        self.assertIsInstance(s, TftSnapshot)

    def test_tft_golden_fields(self):
        g = _load_golden("tft_golden.json")
        s = TftStateReader.to_tft_snapshot(TFT_STATE)
        d = s.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(d["game_mode"],     g["game_mode"])
        self.assertEqual(d["level"],         g["level"])
        self.assertEqual(d["gold"],          g["gold"])

    def test_tft_raw_state_stored(self):
        s = TftStateReader.to_tft_snapshot(TFT_STATE)
        self.assertIsNotNone(s.raw_state)
        self.assertIsInstance(s.raw_state, dict)

    def test_tft_none_input_returns_none(self):
        self.assertIsNone(TftStateReader.to_tft_snapshot(None))

    # -- A5. Arena / RiftSnapshot (CHERRY mode) --------------------------------

    def test_arena_translation_type(self):
        s = GameReader.to_rift_snapshot(ARENA_STATE)
        self.assertIsInstance(s, RiftSnapshot)

    def test_arena_golden_fields(self):
        g = _load_golden("arena_golden.json")
        s = GameReader.to_rift_snapshot(ARENA_STATE)
        d = s.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(d["game_mode"],     g["game_mode"])
        self.assertEqual(d["champion"],      g["champion"])
        self.assertEqual(d["level"],         g["level"])
        self.assertEqual(d["gold"],          g["gold"])
        self.assertEqual(d["hp_pct"],        g["hp_pct"])
        self.assertEqual(d["items"],         g["items"])
        self.assertEqual(d["ally_comp"],     g["ally_comp"])
        self.assertEqual(d["enemy_comp"],    g["enemy_comp"])

    def test_arena_raw_state_stored(self):
        s = GameReader.to_rift_snapshot(ARENA_STATE)
        self.assertIsNotNone(s.raw_state)
        self.assertIsInstance(s.raw_state, dict)

    # -- A6. Brawl / RiftSnapshot (NEXUSBLITZ mode) ----------------------------

    def test_brawl_translation_type(self):
        s = GameReader.to_rift_snapshot(BRAWL_STATE)
        self.assertIsInstance(s, RiftSnapshot)

    def test_brawl_golden_fields(self):
        g = _load_golden("brawl_golden.json")
        s = GameReader.to_rift_snapshot(BRAWL_STATE)
        d = s.to_dict()
        self.assertEqual(d["snapshot_type"], g["snapshot_type"])
        self.assertEqual(d["game_mode"],     g["game_mode"])
        self.assertEqual(d["champion"],      g["champion"])
        self.assertEqual(d["level"],         g["level"])
        self.assertEqual(d["gold"],          g["gold"])
        self.assertEqual(d["hp_pct"],        g["hp_pct"])
        self.assertEqual(d["items"],         g["items"])
        self.assertEqual(d["ally_comp"],     g["ally_comp"])
        self.assertEqual(d["enemy_comp"],    g["enemy_comp"])

    def test_brawl_raw_state_stored(self):
        s = GameReader.to_rift_snapshot(BRAWL_STATE)
        self.assertIsNotNone(s.raw_state)
        self.assertIsInstance(s.raw_state, dict)


# ─────────────────────────────────────────────────────────────────────────────
# B. Envelope authority and mode transitions
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvelopeModeTransitions(unittest.TestCase):
    """Verify envelope transitions and stale-state cleanup."""

    def test_all_valid_modes_accepted(self):
        for mode in ALL_MODES:
            env = GameEnvelope(mode=mode)
            self.assertEqual(env.mode, mode)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            GameEnvelope(mode="INVALID_MODE")

    def test_client_to_sr_transition(self):
        """Simulate client->SR transition: envelope mode and payload type change."""
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)
        payload = GameReader.to_rift_snapshot(SR_STATE)
        env = GameEnvelope(mode=MODE_SR, payload=payload)
        self.assertEqual(env.mode, MODE_SR)
        self.assertIsInstance(env.payload, RiftSnapshot)
        self.assertEqual(env.payload.champion, "Jinx")

    def test_client_to_aram_transition(self):
        env = GameEnvelope.client()
        payload = GameReader.to_aram_snapshot(ARAM_STATE)
        env = GameEnvelope(mode=MODE_ARAM, payload=payload)
        self.assertEqual(env.mode, MODE_ARAM)
        self.assertIsInstance(env.payload, AramSnapshot)
        self.assertEqual(env.payload.champion, "Vayne")

    def test_client_to_tft_transition(self):
        env = GameEnvelope.client()
        payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        env = GameEnvelope(mode=MODE_TFT, payload=payload)
        self.assertEqual(env.mode, MODE_TFT)
        self.assertIsInstance(env.payload, TftSnapshot)

    def test_game_end_resets_to_client(self):
        """After SR game ends, envelope resets to client. No stale SR payload."""
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        env = GameEnvelope(mode=MODE_SR, payload=sr_payload)
        self.assertEqual(env.mode, MODE_SR)
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)
        self.assertIsInstance(env.payload, ClientSnapshot)
        self.assertNotIsInstance(env.payload, RiftSnapshot)

    def test_tft_game_end_resets_to_client(self):
        """After TFT game ends, envelope resets to client. No stale TFT payload."""
        tft_payload = TftStateReader.to_tft_snapshot(TFT_STATE)
        env = GameEnvelope(mode=MODE_TFT, payload=tft_payload)
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)
        self.assertIsInstance(env.payload, ClientSnapshot)
        self.assertNotIsInstance(env.payload, TftSnapshot)

    def test_aram_game_end_resets_to_client(self):
        aram_payload = GameReader.to_aram_snapshot(ARAM_STATE)
        env = GameEnvelope(mode=MODE_ARAM, payload=aram_payload)
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)
        self.assertNotIsInstance(env.payload, AramSnapshot)

    def test_mode_string_classic_maps_to_sr(self):
        self.assertEqual(mode_from_game_mode_string("CLASSIC"), MODE_SR)

    def test_mode_string_aram(self):
        self.assertEqual(mode_from_game_mode_string("ARAM"), MODE_ARAM)
        self.assertEqual(mode_from_game_mode_string("ARAM_UNRANKED_5X5"), MODE_ARAM)

    def test_mode_string_tft(self):
        self.assertEqual(mode_from_game_mode_string("TFT"), MODE_TFT)
        self.assertEqual(mode_from_game_mode_string("TFT_Double_Up"), MODE_TFT)

    def test_mode_string_arena(self):
        self.assertEqual(mode_from_game_mode_string("CHERRY"), MODE_ARENA)
        self.assertEqual(mode_from_game_mode_string("ARENA"), MODE_ARENA)

    def test_mode_string_brawl(self):
        self.assertEqual(mode_from_game_mode_string("NEXUSBLITZ"), MODE_BRAWL)
        self.assertEqual(mode_from_game_mode_string("ULTBOOK"), MODE_BRAWL)
        self.assertEqual(mode_from_game_mode_string("URF"), MODE_BRAWL)

    def test_mode_string_unknown_defaults_sr(self):
        self.assertEqual(mode_from_game_mode_string("UNKNOWN_MODE"), MODE_SR)
        self.assertEqual(mode_from_game_mode_string(""), MODE_SR)


# ─────────────────────────────────────────────────────────────────────────────
# C. Derived compatibility surfaces
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivedCompatibilitySurfaces(unittest.TestCase):
    """
    Verify derived surface contracts.

    IMPORTANT: to_dict() returns LIVE list references from the snapshot,
    not defensive copies. Mutation safety is the responsibility of
    app.get_snapshot() (deep copy), NOT of to_dict(). These tests document
    and lock down the actual contract.
    """

    def test_is_in_game_derived_from_mode(self):
        """is_in_game semantics are derived from mode, not stored."""
        client_env = GameEnvelope.client()
        self.assertTrue(client_env.mode == MODE_CLIENT)
        sr_env = GameEnvelope(mode=MODE_SR, payload=GameReader.to_rift_snapshot(SR_STATE))
        self.assertNotEqual(sr_env.mode, MODE_CLIENT)

    def test_mode_is_not_derived_from_payload_type(self):
        """Envelope mode is explicit, not inferred from payload type."""
        env = GameEnvelope(mode=MODE_SR, payload=GameReader.to_rift_snapshot(SR_STATE))
        self.assertEqual(env.mode, MODE_SR)
        env2 = GameEnvelope(mode=MODE_CLIENT, payload=ClientSnapshot())
        self.assertEqual(env2.mode, MODE_CLIENT)

    # -- C2. to_dict() returns live list references (not defensive copies) ----

    def test_rift_to_dict_items_is_same_list(self):
        """
        RiftSnapshot.to_dict() returns the same list object as s.items.
        Documents the live-reference contract. Mutation safety is app.get_snapshot()'s job.
        """
        s = GameReader.to_rift_snapshot(SR_STATE)
        d = s.to_dict()
        self.assertIs(d["items"], s.items)

    def test_aram_to_dict_ally_comp_is_same_list(self):
        """AramSnapshot.to_dict() returns the same ally_comp list object."""
        s = GameReader.to_aram_snapshot(ARAM_STATE)
        d = s.to_dict()
        self.assertIs(d["ally_comp"], s.ally_comp)

    def test_tft_to_dict_items_is_same_list(self):
        """TftSnapshot.to_dict() returns the same items list object."""
        s = TftStateReader.to_tft_snapshot(TFT_STATE)
        d = s.to_dict()
        self.assertIs(d["items"], s.items)

    def test_envelope_to_dict_payload_items_is_live_list(self):
        """GameEnvelope.to_dict() payload dict references live snapshot lists."""
        sr_payload = GameReader.to_rift_snapshot(SR_STATE)
        env = GameEnvelope(mode=MODE_SR, payload=sr_payload)
        d = env.to_dict()
        self.assertIs(d["payload"]["items"], sr_payload.items)

    # -- C3. Slots contract ---------------------------------------------------

    def test_direct_field_mutation_on_snapshot_is_possible(self):
        """
        Snapshots use __slots__ but are not frozen. Single-writer contract
        (game_reader/app.py only) is enforced by convention, not runtime locks.
        """
        s = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIn("champion", RiftSnapshot.__slots__)
        s.champion = "MutatedChamp"
        self.assertEqual(s.champion, "MutatedChamp")
        s.champion = "Jinx"
        self.assertEqual(s.champion, "Jinx")

    def test_rift_raw_state_is_input_dict(self):
        """RiftSnapshot.raw_state mirrors the dict passed to from_state_dict.
        Audit 2026-04-28 (deferred-frozen): producer-side defensive copy
        means raw_state is now value-equal but not identity-equal — that
        is the safety contract."""
        s = RiftSnapshot.from_state_dict(SR_STATE)
        self.assertEqual(s.raw_state, SR_STATE)
        self.assertIsNot(s.raw_state, SR_STATE)

    def test_aram_raw_state_is_input_dict(self):
        s = AramSnapshot.from_state_dict(ARAM_STATE)
        self.assertEqual(s.raw_state, ARAM_STATE)
        self.assertIsNot(s.raw_state, ARAM_STATE)


# ─────────────────────────────────────────────────────────────────────────────
# D. Non-TFT raw-dict fallback closure
# ─────────────────────────────────────────────────────────────────────────────

class TestNonTftRawDictFallbackClosure(unittest.TestCase):
    """
    Verify the three-tier factory fallback closure for SR/ARAM.
    Uses monkeypatching to force failures without modifying production code.
    """

    def test_rift_tier1_normal_path(self):
        """Normal: from_state_dict succeeds, returns full RiftSnapshot."""
        s = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIsInstance(s, RiftSnapshot)
        self.assertEqual(s.champion, "Jinx")
        self.assertIsNotNone(s.raw_state)

    def test_rift_tier2_fallback_on_from_state_dict_failure(self):
        """
        When from_state_dict raises, Tier 2 (tolerant manual construction) runs.
        Tier 2 sets raw_state and best-effort fields.
        """
        orig = RiftSnapshot.from_state_dict

        def _raise(d):
            raise RuntimeError("forced tier1 failure")

        RiftSnapshot.from_state_dict = staticmethod(_raise)
        try:
            s = GameReader.to_rift_snapshot(SR_STATE)
            self.assertIsNotNone(s, "Tier 2/3 fallback must not return None")
            self.assertIsInstance(s, RiftSnapshot)
            self.assertIsNotNone(s.raw_state)
        finally:
            RiftSnapshot.from_state_dict = staticmethod(orig)

    def test_rift_tier2_fallback_sets_best_effort_fields(self):
        """Tier 2 fallback populates champion, game_mode, level, gold, hp_pct."""
        orig = RiftSnapshot.from_state_dict

        def _raise(d):
            raise RuntimeError("forced tier1 failure")

        RiftSnapshot.from_state_dict = staticmethod(_raise)
        try:
            s = GameReader.to_rift_snapshot(SR_STATE)
            self.assertIsNotNone(s)
            # Tier 2 sets these best-effort fields from the state dict
            self.assertEqual(s.champion, SR_STATE["champion"])
            self.assertEqual(s.gold,     SR_STATE["gold"])
            self.assertEqual(s.hp_pct,   SR_STATE["hp_pct"])
        finally:
            RiftSnapshot.from_state_dict = staticmethod(orig)

    def test_rift_emergency_raw_state_only_bypasses_init(self):
        """
        emergency_raw_state_only uses object.__new__(), bypassing __init__.
        Called by app.py when all factory tiers are exhausted.
        """
        orig_init = RiftSnapshot.__init__

        def _raise_init(self_):
            raise RuntimeError("__init__ disabled for test")

        RiftSnapshot.__init__ = _raise_init
        try:
            # emergency_raw_state_only bypasses __init__ entirely
            s = RiftSnapshot.emergency_raw_state_only(SR_STATE)
            self.assertIsNotNone(s)
            self.assertIsInstance(s, RiftSnapshot)
            # Audit 2026-04-28 (deferred-frozen): value-equal, not identity
            self.assertEqual(s.raw_state, SR_STATE)
        finally:
            RiftSnapshot.__init__ = orig_init

    def test_rift_none_short_circuits_before_tiers(self):
        """None state_dict returns None immediately, no tier is attempted."""
        self.assertIsNone(GameReader.to_rift_snapshot(None))

    def test_aram_tier2_fallback_on_failure(self):
        orig = AramSnapshot.from_state_dict

        def _raise(d):
            raise RuntimeError("forced aram tier1 failure")

        AramSnapshot.from_state_dict = staticmethod(_raise)
        try:
            s = GameReader.to_aram_snapshot(ARAM_STATE)
            self.assertIsNotNone(s)
            self.assertIsInstance(s, AramSnapshot)
            self.assertIsNotNone(s.raw_state)
        finally:
            AramSnapshot.from_state_dict = staticmethod(orig)

    def test_rift_emergency_raw_state_only(self):
        """emergency_raw_state_only produces a valid RiftSnapshot with raw_state.
        Audit 2026-04-28 (deferred-frozen): value-equal, not identity."""
        s = RiftSnapshot.emergency_raw_state_only(SR_STATE)
        self.assertIsNotNone(s)
        self.assertIsInstance(s, RiftSnapshot)
        self.assertEqual(s.raw_state, SR_STATE)

    def test_aram_emergency_raw_state_only(self):
        s = AramSnapshot.emergency_raw_state_only(ARAM_STATE)
        self.assertIsNotNone(s)
        self.assertIsInstance(s, AramSnapshot)
        self.assertEqual(s.raw_state, ARAM_STATE)


# ─────────────────────────────────────────────────────────────────────────────
# E. TFT runtime authority boundary
# ─────────────────────────────────────────────────────────────────────────────

class TestTftRuntimeAuthorityBoundary(unittest.TestCase):
    """
    Verify that TFT runtime authority flows from TftWorker/TftStateReader,
    not from SrAramWorker or GameReader.
    """

    def test_tft_state_uses_tft_snapshot_not_rift(self):
        """TFT state dicts must produce TftSnapshot, never RiftSnapshot."""
        tft_state = dict(TFT_STATE)
        s = TftStateReader.to_tft_snapshot(tft_state)
        self.assertIsInstance(s, TftSnapshot)
        self.assertNotIsInstance(s, RiftSnapshot)
        self.assertNotIsInstance(s, AramSnapshot)

    def test_rift_factory_never_produces_tft_snapshot(self):
        """
        Regardless of game_mode field, to_rift_snapshot returns RiftSnapshot (or None).
        SR worker cannot produce TFT authority payloads.
        """
        tft_like_dict = dict(SR_STATE, game_mode="TFT")
        s = GameReader.to_rift_snapshot(tft_like_dict)
        if s is not None:
            self.assertIsInstance(s, RiftSnapshot)
            self.assertNotIsInstance(s, TftSnapshot)

    def test_tft_envelope_holds_tft_snapshot(self):
        """GameEnvelope with MODE_TFT holds TftSnapshot, not RiftSnapshot."""
        tft_snap = TftStateReader.to_tft_snapshot(TFT_STATE)
        env = GameEnvelope(mode=MODE_TFT, payload=tft_snap)
        self.assertEqual(env.mode, MODE_TFT)
        self.assertIsInstance(env.payload, TftSnapshot)
        sr_snap = GameReader.to_rift_snapshot(SR_STATE)
        self.assertNotIsInstance(sr_snap, TftSnapshot)

    def test_tft_game_mode_string_resolves_to_tft_mode(self):
        """mode_from_game_mode_string correctly routes TFT strings."""
        for gm in ("TFT", "TFT_DOUBLE_UP", "TFTSTANDARDIZATIONTEST"):
            self.assertEqual(
                mode_from_game_mode_string(gm), MODE_TFT,
                f"Expected MODE_TFT for game_mode={gm!r}"
            )

    def test_tft_mode_detection_case_insensitive(self):
        self.assertEqual(mode_from_game_mode_string("tft"), MODE_TFT)
        self.assertEqual(mode_from_game_mode_string("Tft_Double_Up"), MODE_TFT)

    def test_sr_aram_worker_result_is_raw_dict_not_snapshot(self):
        """
        SrAramWorker emits WorkerResult with raw state dict, not a snapshot.
        app.py creates the snapshot after mode detection.
        TftSnapshot is NEVER produced by the SR/ARAM translation path.
        """
        from core.sr_aram_worker import WorkerResult
        wr = WorkerResult(state=SR_STATE, end_signal=False)
        self.assertIsInstance(wr.state, dict)
        self.assertNotIsInstance(wr.state, (RiftSnapshot, AramSnapshot, TftSnapshot))

        # Simulate what app.py does
        mode = mode_from_game_mode_string(wr.state.get("game_mode", "CLASSIC"))
        if mode == MODE_SR:
            snap = GameReader.to_rift_snapshot(wr.state)
            self.assertIsInstance(snap, RiftSnapshot)
            self.assertNotIsInstance(snap, TftSnapshot)
        elif mode == MODE_ARAM:
            snap = GameReader.to_aram_snapshot(wr.state)
            self.assertIsInstance(snap, AramSnapshot)
            self.assertNotIsInstance(snap, TftSnapshot)

    def test_tft_worker_result_state_produces_tft_snapshot(self):
        """TftWorkerResult.state is also a raw dict; TftStateReader translates it."""
        from core.tft_worker import TftWorkerResult
        twr = TftWorkerResult(state=TFT_STATE)
        self.assertIsInstance(twr.state, dict)
        snap = TftStateReader.to_tft_snapshot(twr.state)
        self.assertIsInstance(snap, TftSnapshot)
        self.assertNotIsInstance(snap, RiftSnapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
