"""`tools/repair_spend_ledger.py` - per-bucket synthetic-row recovery.

The ledger stores per-day AGGREGATES, so the recovery is only sound where a
`by_purpose` bucket is provably 100 percent synthetic. These tests pin the
boundary in both directions, because a tool that over-deletes destroys the
operator's real financial history and one that under-deletes leaves the
pollution in place:

  * a bucket at exactly 10-in / 20-out per call at the Haiku price is dropped;
  * a real bucket sharing the SAME purpose name on the SAME day is not;
  * a legacy bucket with no `tokens` key at all is not (the leak always wrote
    that field, so its absence proves the bucket predates the leak);
  * a whole file is never dropped for containing one synthetic bucket;
  * a second run is a no-op (idempotence), and `--dry-run` writes nothing.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import repair_spend_ledger as rsl  # noqa: E402

_SYNTH_USD = 0.000088   # one 10-in / 20-out Haiku 4.5 call


def _synth_bucket(n: int) -> dict:
    return {"calls": n, "usd": round(n * _SYNTH_USD, 6), "tokens": n * 30}


def _day(purposes: dict, model_calls: int, model_tin: int, model_tout: int,
         model_usd: float) -> dict:
    total_usd = round(sum(p["usd"] for p in purposes.values()), 6)
    return {
        "date": "2026-07-28",
        "total_usd": total_usd,
        "calls": sum(p["calls"] for p in purposes.values()),
        "tokens_in": model_tin,
        "tokens_out": model_tout,
        "cache_in": 0,
        "cache_write": 0,
        "by_model": {rsl.SYNTH_MODEL: {
            "calls": model_calls, "usd": model_usd,
            "tokens_in": model_tin, "tokens_out": model_tout,
            "cache_in": 0, "cache_write": 0,
        }},
        "by_purpose": purposes,
    }


class PriceDerivationTests(unittest.TestCase):
    def test_synthetic_price_matches_the_live_pricing_table(self) -> None:
        # Pinned so a MODEL_PRICING edit that changes what the tool deletes
        # fails here rather than silently widening the filter.
        self.assertAlmostEqual(rsl.synth_usd_per_call(), _SYNTH_USD, places=12)


class ClassifyBucketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.price = rsl.synth_usd_per_call()

    def _verdict(self, purpose, bucket):
        return rsl.classify_bucket(purpose, bucket, self.price)

    def test_exact_synthetic_bucket_is_pure(self) -> None:
        self.assertEqual("pure", self._verdict("aram_coach", _synth_bucket(403)))
        self.assertEqual("pure", self._verdict("arena_coach", _synth_bucket(1)))

    def test_real_coach_bucket_is_clean(self) -> None:
        real = {"calls": 930, "usd": 3.807435, "tokens": 2965954}
        self.assertEqual("clean", self._verdict("aram_coach", real))

    def test_legacy_bucket_without_tokens_key_is_clean(self) -> None:
        legacy = {"calls": 306, "usd": 1.264576}
        self.assertEqual("clean", self._verdict("aram_coach", legacy))

    def test_zero_token_value_is_not_treated_as_synthetic(self) -> None:
        # tokens present but 0 with real money attached: not the fingerprint.
        self.assertEqual("clean",
                         self._verdict("aram_coach",
                                       {"calls": 10, "usd": 0.04, "tokens": 0}))

    def test_other_purposes_are_never_touched(self) -> None:
        # Same fingerprint under a purpose the leak cannot produce.
        for purpose in ("sr_coach", "agent7_warm", "vision_relay",
                        "champ_select_coach", "tft_coach"):
            self.assertEqual("clean", self._verdict(purpose, _synth_bucket(50)))

    def test_right_tokens_wrong_price_is_not_pure(self) -> None:
        bucket = _synth_bucket(100)
        bucket["usd"] = round(bucket["usd"] * 2, 6)
        self.assertNotEqual("pure", self._verdict("aram_coach", bucket))

    def test_right_price_wrong_tokens_is_not_pure(self) -> None:
        bucket = _synth_bucket(100)
        bucket["tokens"] = 100 * 31
        self.assertNotEqual("pure", self._verdict("aram_coach", bucket))

    def test_synthetic_dominated_mix_is_flagged_not_dropped(self) -> None:
        # 100 synthetic (3000 tokens) plus one real 1500-token call.
        bucket = {"calls": 101, "usd": round(100 * _SYNTH_USD + 0.004, 6),
                  "tokens": 3000 + 1500}
        self.assertEqual("mixed", self._verdict("aram_coach", bucket))


class RepairDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write(self, name: str, doc: dict) -> Path:
        p = self.dir / name
        p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        return p

    def _mixed_day(self) -> dict:
        """One real lane plus one synthetic lane, as 22 real files carry."""
        real = {"calls": 930, "usd": 3.807435, "tokens": 2965954}
        synth_a = _synth_bucket(39)
        synth_b = _synth_bucket(45)
        doc = _day({"sr_coach": real, "aram_coach": synth_a,
                    "arena_coach": synth_b},
                   model_calls=930 + 39 + 45,
                   model_tin=2_000_000 + 84 * 10,
                   model_tout=965_954 + 84 * 20,
                   model_usd=round(3.807435 + 84 * _SYNTH_USD, 6))
        return doc

    def test_real_lane_survives_and_synthetic_lanes_go(self) -> None:
        path = self._write("2026-06-21.json", self._mixed_day())
        rsl.repair_dir(self.dir, dry_run=False)
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("sr_coach", doc["by_purpose"])
        self.assertEqual(3.807435, doc["by_purpose"]["sr_coach"]["usd"])
        self.assertNotIn("aram_coach", doc["by_purpose"])
        self.assertNotIn("arena_coach", doc["by_purpose"])
        self.assertEqual(930, doc["calls"])
        self.assertEqual(3.807435, doc["total_usd"])
        self.assertEqual(930, doc["by_model"][rsl.SYNTH_MODEL]["calls"])

    def test_file_is_never_deleted_even_when_wholly_synthetic(self) -> None:
        doc = _day({"aram_coach": _synth_bucket(10),
                    "arena_coach": _synth_bucket(20)},
                   model_calls=30, model_tin=300, model_tout=600,
                   model_usd=round(30 * _SYNTH_USD, 6))
        path = self._write("2026-08-04.json", doc)
        rsl.repair_dir(self.dir, dry_run=False)
        self.assertTrue(path.is_file(), "the day-file must survive, zeroed")
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(0, after["calls"])
        self.assertEqual(0.0, after["total_usd"])
        self.assertEqual({}, after["by_purpose"])
        self.assertEqual({}, after["by_model"])
        self.assertEqual("2026-07-28", after["date"], "date must be preserved")

    def test_second_run_is_a_no_op(self) -> None:
        path = self._write("2026-06-21.json", self._mixed_day())
        first = rsl.repair_dir(self.dir, dry_run=False)
        after_first = path.read_bytes()
        second = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(84, first["dropped_calls"])
        self.assertEqual(0, second["dropped_calls"])
        self.assertEqual(0, second["files_changed"])
        self.assertEqual(after_first, path.read_bytes(),
                         "the second run rewrote the file - not idempotent")

    def test_dry_run_writes_nothing(self) -> None:
        path = self._write("2026-06-21.json", self._mixed_day())
        before = path.read_bytes()
        rep = rsl.repair_dir(self.dir, dry_run=True)
        self.assertEqual(84, rep["dropped_calls"])
        self.assertEqual(1, rep["files_changed"])
        self.assertEqual(before, path.read_bytes())

    def test_no_temp_file_is_left_behind(self) -> None:
        self._write("2026-06-21.json", self._mixed_day())
        rsl.repair_dir(self.dir, dry_run=False)
        strays = [p.name for p in self.dir.iterdir() if p.suffix == ".tmp"]
        self.assertEqual([], strays)

    def test_sidecar_files_are_skipped(self) -> None:
        side = self.dir / "recent_matches.json"
        side.write_text(json.dumps({"matches": []}), encoding="utf-8")
        rep = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(0, rep["files_scanned"])
        self.assertEqual([], rep["errors"])

    def test_underwater_model_bucket_is_refused_not_half_written(self) -> None:
        # by_model cannot absorb the subtraction: the tool must leave the file
        # byte-identical and report, rather than write a negative ledger.
        doc = _day({"aram_coach": _synth_bucket(100)},
                   model_calls=10, model_tin=100, model_tout=200,
                   model_usd=round(10 * _SYNTH_USD, 6))
        path = self._write("2026-08-01.json", doc)
        before = path.read_bytes()
        rep = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(0, rep["files_changed"])
        self.assertEqual(before, path.read_bytes())
        self.assertTrue(rep["errors"])

    def test_unreadable_file_is_reported_not_fatal(self) -> None:
        (self.dir / "2026-05-05.json").write_text("{not json", encoding="utf-8")
        self._write("2026-06-21.json", self._mixed_day())
        rep = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(1, rep["files_changed"])
        self.assertTrue(any("2026-05-05" in e for e in rep["errors"]))

    def test_mixed_bucket_is_left_on_disk_and_reported(self) -> None:
        doc = _day({"aram_coach": {"calls": 101,
                                   "usd": round(100 * _SYNTH_USD + 0.004, 6),
                                   "tokens": 4500}},
                   model_calls=101, model_tin=2500, model_tout=2000,
                   model_usd=round(100 * _SYNTH_USD + 0.004, 6))
        path = self._write("2026-07-01.json", doc)
        before = path.read_bytes()
        rep = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(0, rep["dropped_calls"])
        self.assertEqual([{"file": "2026-07-01.json",
                           "purposes": ["aram_coach"]}],
                         rep["mixed_buckets"])


class MatchSidecarTests(unittest.TestCase):
    """`_match_open.json` + `recent_matches.json` - the second leak.

    `core/match_db.py:177` fires `get_tracker().note_match_boundary()` on every
    saved match, and `tests/test_last_match_ingest_gameid.py` drives the real
    `save_match` with only its match DB isolated. Measured on the live tree
    2026-08-06: two records 41 MILLISECONDS apart, all-zero `by_gate`, aram +
    arena only - not two real matches.
    """

    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write(self, name: str, doc) -> Path:
        p = self.dir / name
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_synthetic_only_match_open_snapshot_is_reset(self) -> None:
        p = self._write("_match_open.json", {
            "by_purpose": {"aram_coach": {"calls": 273, "usd": 0.024024},
                           "arena_coach": {"calls": 315, "usd": 0.02772}},
            "ts": 1785899788.5})
        rep = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertTrue(rep["match_open_reset"])
        self.assertEqual({}, json.loads(p.read_text(encoding="utf-8")))

    def test_match_open_with_a_real_purpose_is_left_alone(self) -> None:
        doc = {"by_purpose": {"aram_coach": {"calls": 5, "usd": 0.02},
                              "sr_coach": {"calls": 900, "usd": 3.8}},
               "ts": 1785899788.5}
        p = self._write("_match_open.json", doc)
        before = p.read_bytes()
        rep = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertFalse(rep["match_open_reset"])
        self.assertEqual(before, p.read_bytes())

    def test_zero_cost_aram_arena_records_are_dropped(self) -> None:
        zero = {"arena": {"usd": 0.0, "tokens": 0},
                "aram": {"usd": 0.0, "tokens": 0}}
        p = self._write("recent_matches.json", {"matches": [
            {"ts": 1785899788.487826, "by_gate": zero},
            {"ts": 1785899788.5285976, "by_gate": zero},
        ]})
        rep = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertEqual(2, rep["match_records_dropped"])
        self.assertEqual(0, rep["match_records_kept"])
        self.assertEqual([], json.loads(p.read_text(encoding="utf-8"))["matches"])

    def test_record_with_real_spend_survives(self) -> None:
        p = self._write("recent_matches.json", {"matches": [
            {"ts": 1.0, "by_gate": {"aram": {"usd": 0.0, "tokens": 0}}},
            {"ts": 2.0, "by_gate": {"aram": {"usd": 0.41, "tokens": 90000}}},
        ]})
        rep = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertEqual(1, rep["match_records_dropped"])
        kept = json.loads(p.read_text(encoding="utf-8"))["matches"]
        self.assertEqual([{"ts": 2.0,
                           "by_gate": {"aram": {"usd": 0.41,
                                                "tokens": 90000}}}], kept)

    def test_record_touching_a_non_synthetic_gate_survives(self) -> None:
        # Zero-cost but the gate set proves it was not the aram/arena leak.
        rec = {"ts": 3.0, "by_gate": {"sr": {"usd": 0.0, "tokens": 0}}}
        p = self._write("recent_matches.json", {"matches": [rec]})
        before = p.read_bytes()
        rep = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertEqual(0, rep["match_records_dropped"])
        self.assertEqual(before, p.read_bytes())

    def test_sidecar_pass_is_idempotent(self) -> None:
        zero = {"aram": {"usd": 0.0, "tokens": 0}}
        self._write("_match_open.json",
                    {"by_purpose": {"aram_coach": {"calls": 1, "usd": 0.0001}}})
        rp = self._write("recent_matches.json",
                         {"matches": [{"ts": 1.0, "by_gate": zero}]})
        op = self.dir / "_match_open.json"
        rsl.repair_match_sidecars(self.dir, dry_run=False)
        snap = (op.read_bytes(), rp.read_bytes())
        rep2 = rsl.repair_match_sidecars(self.dir, dry_run=False)
        self.assertFalse(rep2["match_open_reset"])
        self.assertEqual(0, rep2["match_records_dropped"])
        self.assertEqual(snap, (op.read_bytes(), rp.read_bytes()))

    def test_sidecar_dry_run_writes_nothing(self) -> None:
        zero = {"aram": {"usd": 0.0, "tokens": 0}}
        op = self._write("_match_open.json",
                         {"by_purpose": {"aram_coach": {"calls": 1}}})
        rp = self._write("recent_matches.json",
                         {"matches": [{"ts": 1.0, "by_gate": zero}]})
        before = (op.read_bytes(), rp.read_bytes())
        rep = rsl.repair_match_sidecars(self.dir, dry_run=True)
        self.assertTrue(rep["match_open_reset"])
        self.assertEqual(1, rep["match_records_dropped"])
        self.assertEqual(before, (op.read_bytes(), rp.read_bytes()))

    def test_repair_dir_runs_the_sidecar_pass(self) -> None:
        self._write("recent_matches.json", {"matches": [
            {"ts": 1.0, "by_gate": {"aram": {"usd": 0.0, "tokens": 0}}}]})
        rep = rsl.repair_dir(self.dir, dry_run=False)
        self.assertEqual(1, rep["sidecars"]["match_records_dropped"])


class CliTests(unittest.TestCase):
    def test_main_dry_run_on_empty_dir_is_clean_exit(self) -> None:
        with TemporaryDirectory() as td:
            rc = rsl.main(["--spend-dir", td, "--dry-run"])
        self.assertEqual(0, rc)

    def test_main_reports_missing_dir_as_error_exit(self) -> None:
        with TemporaryDirectory() as td:
            missing = str(Path(td) / "nope")
        self.assertEqual(1, rsl.main(["--spend-dir", missing, "--dry-run"]))


if __name__ == "__main__":
    unittest.main()
