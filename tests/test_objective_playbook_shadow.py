# Tests for core/objective_playbook_shadow.py - the RC2 P5.5 (WS3) do-not-flip-
# blind shadow writer. Records the deterministic playbook directive alongside the
# native Haiku `objective` prose so a future served-objective flip can be
# agreement-gated before it changes any served output.
#
# Covers: record shape + fields, native_objective capture, None-playbook record,
# coarse-state dedup, the exact-game_time freshness guard, and fail-soft (never
# raises, bad input -> None).
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import core.objective_playbook_shadow as ops


def _read(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        ops._LAST_SIG.clear()
        ops._LAST_GT.clear()

    def test_writes_record_with_fields(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            play = {"tag": "playbook_dragon", "line": "Drake: ...", "eta_s": 20.0, "kind": "playbook"}
            rec = ops.log_objective_playbook(
                "sr", "Aatrox", playbook=play, native_objective="take drake",
                lead_state="ahead", phase="mid", game_time_s=300.0, path=p,
            )
            self.assertIsNotNone(rec)
            rows = _read(p)
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual(r["mode"], "sr")
            self.assertEqual(r["my_champion"], "Aatrox")
            self.assertEqual(r["playbook_tag"], "playbook_dragon")
            self.assertEqual(r["playbook_line"], "Drake: ...")
            self.assertEqual(r["native_objective"], "take drake")
            self.assertEqual(r["lead_state"], "ahead")
            self.assertEqual(r["phase"], "mid")
            self.assertEqual(r["game_time_s"], 300.0)
            self.assertIn("engine_version", r)
            self.assertIn("ts", r)

    def test_none_playbook_still_records(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            rec = ops.log_objective_playbook(
                "sr", "Aatrox", playbook=None, native_objective="contest baron",
                lead_state="behind", phase="late", game_time_s=1300.0, path=p,
            )
            self.assertIsNotNone(rec)
            r = _read(p)[0]
            self.assertIsNone(r["playbook_tag"])
            self.assertIsNone(r["playbook_line"])
            self.assertEqual(r["native_objective"], "contest baron")

    def test_requires_champion(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            self.assertIsNone(ops.log_objective_playbook("sr", "", playbook=None, path=p))
            self.assertIsNone(ops.log_objective_playbook("sr", None, playbook=None, path=p))
            self.assertFalse(p.exists())


class DedupTests(unittest.TestCase):
    def setUp(self) -> None:
        ops._LAST_SIG.clear()
        ops._LAST_GT.clear()

    def test_same_coarse_state_dedups(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            play = {"tag": "playbook_dragon", "line": "Drake: x", "eta_s": 20.0}
            a = ops.log_objective_playbook("sr", "Aatrox", playbook=play,
                                           native_objective="drake", lead_state="ahead",
                                           phase="mid", game_time_s=300.0, path=p)
            # Same coarse bucket + identical directive -> dedup (advance gt by 1s
            # so the exact-equality freshness guard does not also fire).
            b = ops.log_objective_playbook("sr", "Aatrox", playbook=play,
                                           native_objective="drake", lead_state="ahead",
                                           phase="mid", game_time_s=301.0, path=p)
            self.assertIsNotNone(a)
            self.assertIsNone(b)
            self.assertEqual(len(_read(p)), 1)

    def test_changed_directive_logs_new_row(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            p1 = {"tag": "playbook_dragon", "line": "Drake: x", "eta_s": 20.0}
            p2 = {"tag": "playbook_dragon", "line": "Drake: free, take it now", "eta_s": 20.0}
            ops.log_objective_playbook("sr", "Aatrox", playbook=p1, lead_state="ahead",
                                       phase="mid", game_time_s=300.0, path=p)
            ops.log_objective_playbook("sr", "Aatrox", playbook=p2, lead_state="ahead",
                                       phase="mid", game_time_s=301.0, path=p)
            self.assertEqual(len(_read(p)), 2)

    def test_exact_game_time_freshness_guard(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "ob.jsonl"
            p1 = {"tag": "playbook_dragon", "line": "Drake: x", "eta_s": 20.0}
            p2 = {"tag": "playbook_baron", "line": "Baron: y", "eta_s": 10.0}
            ops.log_objective_playbook("sr", "Aatrox", playbook=p1, game_time_s=300.0, path=p)
            # Frozen game_time (post-game cache tail) suppresses even a changed
            # directive - exact game_time_s equality to the last LOGGED tick.
            b = ops.log_objective_playbook("sr", "Aatrox", playbook=p2, game_time_s=300.0, path=p)
            self.assertIsNone(b)
            self.assertEqual(len(_read(p)), 1)


class FailSoftTests(unittest.TestCase):
    def test_never_raises_on_garbage(self) -> None:
        try:
            self.assertIsNone(ops.log_objective_playbook(object(), object(), playbook=object()))
        except Exception as exc:  # noqa: BLE001
            self.fail(f"log_objective_playbook raised: {exc!r}")


if __name__ == "__main__":
    unittest.main()
