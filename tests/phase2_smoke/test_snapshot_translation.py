"""
tests/phase2_smoke/test_snapshot_translation.py
Smoke tests for snapshot translation helpers (no live API, no Tk).
Exercises GameReader.to_rift_snapshot, to_aram_snapshot,
and TftStateReader.to_tft_snapshot with fixture state dicts.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.fixtures.state_dicts import SR_STATE, ARAM_STATE, TFT_STATE


class TestRiftSnapshotTranslation(unittest.TestCase):

    def test_to_rift_snapshot_returns_non_none(self):
        from game_reader import GameReader
        result = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIsNotNone(result)

    def test_to_rift_snapshot_has_raw_state(self):
        from game_reader import GameReader
        result = GameReader.to_rift_snapshot(SR_STATE)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.raw_state)

    def test_to_rift_snapshot_none_input_returns_none(self):
        from game_reader import GameReader
        self.assertIsNone(GameReader.to_rift_snapshot(None))

    def test_to_rift_snapshot_empty_dict_non_fatal(self):
        from game_reader import GameReader
        result = GameReader.to_rift_snapshot({})
        # May return a default snapshot or None — must not raise
        # (None is acceptable; crash is not)
        pass  # no exception = pass


class TestAramSnapshotTranslation(unittest.TestCase):

    def test_to_aram_snapshot_returns_non_none(self):
        from game_reader import GameReader
        result = GameReader.to_aram_snapshot(ARAM_STATE)
        self.assertIsNotNone(result)

    def test_to_aram_snapshot_has_raw_state(self):
        from game_reader import GameReader
        result = GameReader.to_aram_snapshot(ARAM_STATE)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.raw_state)

    def test_to_aram_snapshot_none_input_returns_none(self):
        from game_reader import GameReader
        self.assertIsNone(GameReader.to_aram_snapshot(None))


class TestTftSnapshotTranslation(unittest.TestCase):

    def test_to_tft_snapshot_returns_non_none(self):
        from tft.tft_state_reader import TftStateReader
        result = TftStateReader.to_tft_snapshot(TFT_STATE)
        self.assertIsNotNone(result)

    def test_to_tft_snapshot_has_raw_state(self):
        from tft.tft_state_reader import TftStateReader
        result = TftStateReader.to_tft_snapshot(TFT_STATE)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.raw_state)

    def test_to_tft_snapshot_none_input_returns_none(self):
        from tft.tft_state_reader import TftStateReader
        self.assertIsNone(TftStateReader.to_tft_snapshot(None))


class TestGameEnvelopeTypes(unittest.TestCase):
    """GameEnvelope and payload types are importable with no live deps."""

    def test_imports(self):
        from core.game_snapshot import (
            GameEnvelope, RiftSnapshot, AramSnapshot,
            TftSnapshot, ClientSnapshot,
            MODE_SR, MODE_ARAM, MODE_TFT, MODE_CLIENT,
        )

    def test_client_snapshot_default(self):
        from core.game_snapshot import ClientSnapshot, GameEnvelope, MODE_CLIENT
        env = GameEnvelope.client()
        self.assertEqual(env.mode, MODE_CLIENT)

    def test_rift_snapshot_from_state_dict(self):
        from core.game_snapshot import RiftSnapshot
        s = RiftSnapshot.from_state_dict(SR_STATE)
        self.assertIsNotNone(s)

    def test_aram_snapshot_from_state_dict(self):
        from core.game_snapshot import AramSnapshot
        s = AramSnapshot.from_state_dict(ARAM_STATE)
        self.assertIsNotNone(s)

    def test_tft_snapshot_from_state_dict(self):
        from core.game_snapshot import TftSnapshot
        s = TftSnapshot.from_state_dict(TFT_STATE)
        self.assertIsNotNone(s)


if __name__ == "__main__":
    unittest.main()
