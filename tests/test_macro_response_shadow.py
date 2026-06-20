# Tests for core/macro_response_shadow.py - the RC2 P5.7 (WS4) do-not-flip-blind
# shadow log. Records the deterministic macro response row alongside the native
# Haiku objective prose for a future served-field flip's agreement gate.
#
# Covers: a fresh write (fields verbatim), a None-macro silent-tick record,
# coarse-state dedup, the exact-game_time freshness guard, and fail-soft.
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import core.macro_response_shadow as mrs


class LogMacroResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        mrs._LAST_SIG.clear()
        mrs._LAST_GT.clear()

    def test_writes_record_with_fields(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            macro = {"tag": "macro_lost_objective", "line": "Baron lost - defend",
                     "eta_s": None, "kind": "macro_response"}
            rec = mrs.log_macro_response(
                "sr", "Aatrox", macro=macro, native_objective="hold base",
                lead_state="behind", phase="late", game_time_s=1310.0, path=p)
            self.assertIsNotNone(rec)
            rows = [json.loads(x) for x in
                    p.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["macro_tag"], "macro_lost_objective")
            self.assertEqual(rows[0]["macro_line"], "Baron lost - defend")
            self.assertEqual(rows[0]["native_objective"], "hold base")
            self.assertEqual(rows[0]["lead_state"], "behind")
            self.assertIn("engine_version", rows[0])

    def test_none_macro_still_records(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            rec = mrs.log_macro_response(
                "sr", "Aatrox", macro=None, native_objective="take drake",
                lead_state="even", phase="mid", game_time_s=700.0, path=p)
            self.assertIsNotNone(rec)
            rows = [json.loads(x) for x in
                    p.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["macro_tag"])
            self.assertEqual(rows[0]["native_objective"], "take drake")

    def test_no_champion_returns_none(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            self.assertIsNone(mrs.log_macro_response("sr", "", path=p))
            self.assertFalse(p.exists())

    def test_coarse_dedup_skips_same_sig(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            macro = {"tag": "macro_stagnation", "line": "Stalled - side lane"}
            r1 = mrs.log_macro_response("sr", "Aatrox", macro=macro,
                                        lead_state="even", game_time_s=1400.0, path=p)
            # Same 5s bucket + same fields -> deduped (game_time nudged so the
            # freshness guard does not fire instead).
            r2 = mrs.log_macro_response("sr", "Aatrox", macro=macro,
                                        lead_state="even", game_time_s=1402.0, path=p)
            self.assertIsNotNone(r1)
            self.assertIsNone(r2)
            rows = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(rows), 1)

    def test_exact_game_time_freshness_guard(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "m.jsonl"
            macro = {"tag": "macro_stagnation", "line": "Stalled - side lane"}
            r1 = mrs.log_macro_response("sr", "Aatrox", macro=macro,
                                        game_time_s=1400.0, path=p)
            # Byte-identical game_time (frozen post-game snapshot) -> suppressed.
            r2 = mrs.log_macro_response("sr", "Aatrox", macro=macro,
                                        game_time_s=1400.0, path=p)
            self.assertIsNotNone(r1)
            self.assertIsNone(r2)

    def test_failsoft_on_bad_path(self) -> None:
        # A path whose parent cannot be created -> None, never raises.
        bad = Path("\x00bad") / "x.jsonl"
        try:
            out = mrs.log_macro_response("sr", "Aatrox", game_time_s=1.0, path=bad)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"log_macro_response raised: {exc!r}")
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
