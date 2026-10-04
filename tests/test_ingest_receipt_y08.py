"""Y-08: per-game ingest receipt plus the match-ingest freshness card.

External reference M (behaviour only; nothing copied). Before this change the
post-game live writer (``lib/rewind_live_writer.py``) had no success log at
all - the comment beside its wire in ``app/_game_lifecycle.py`` says so - and
``scripts/rewind_catchup.py`` ``pending_retry_counts`` / ``last_run_outcome``
had no consumer outside the script. So "did my last game land in the rewind
DB" had no answer short of opening sqlite.

Pinned here:

* every status the writer can END a chain with is classified by NAME, and an
  unknown status is never counted as success (guard over the writer source,
  fails on an empty enumeration, positive control below);
* a chain end appends exactly one receipt; an intermediate staged attempt and
  a "nothing to do" end (another chain owns the target) append none;
* appending never raises into the writer, whatever the disk does;
* the read-only builder renders a fresh tree with an explicit "no receipt
  yet" basis line and the SAME row keys as a populated tree (no reflow), and
  never leaks the Riot ID the pin file carries.

Every Riot call is a fake; no fixture names a real player.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import ops_panels  # noqa: E402
from lib import ingest_receipt as ir  # noqa: E402
from lib import rewind_live_writer as rlw  # noqa: E402
from tests.test_rewind_live_writer_target_pin import (  # noqa: E402
    PREV_ID,
    TARGET_GAME,
    TARGET_ID,
    _FakeTimer,
    _PinBase,
)

WRITER_SRC = (ROOT / "lib" / "rewind_live_writer.py").read_text(encoding="utf-8")

# Status literals the writer can put in a result dict. Three spellings exist
# in the source: a dict literal, the staged ``_next("...")`` helper and the
# cap-reached overwrite ``out["status"] = "..."``.
_STATUS_RES = (
    re.compile(r'"status":\s*"([a-z_]+)"'),
    re.compile(r'_next\(\s*"([a-z_]+)"'),
    re.compile(r'out\["status"\]\s*=\s*"([a-z_]+)"'),
)


def writer_statuses(src: str = WRITER_SRC) -> set[str]:
    found: set[str] = set()
    for rx in _STATUS_RES:
        found.update(rx.findall(src))
    return found


class StatusVocabularyTests(unittest.TestCase):

    def test_enumeration_is_not_empty(self):
        """An empty scan would make the coverage guard below pass vacuously."""
        found = writer_statuses()
        self.assertGreaterEqual(len(found), 15, sorted(found))
        for anchor in ("ok", "already_present", "event_mode_excluded",
                       "target_not_indexed", "not_indexed_retry_scheduled"):
            self.assertIn(anchor, found)

    def test_every_writer_status_is_classified_by_name(self):
        unclassified = {s for s in writer_statuses()
                        if ir.classify(s) == ir.CLASS_UNKNOWN
                        and not ir.is_non_terminal(s)}
        self.assertEqual(unclassified, set(),
                         "writer emits statuses the receipt cannot name")

    def test_guard_goes_red_on_a_planted_unknown_status(self):
        """Positive control: a new writer status nobody classified is caught."""
        planted = WRITER_SRC + '\n_X = {"status": "brand_new_outcome"}\n'
        unclassified = {s for s in writer_statuses(planted)
                        if ir.classify(s) == ir.CLASS_UNKNOWN
                        and not ir.is_non_terminal(s)}
        self.assertEqual(unclassified, {"brand_new_outcome"})

    def test_unknown_status_is_never_success(self):
        for s in ("brand_new_outcome", "", "OK", "ok ", "success", None, 7):
            self.assertEqual(ir.classify(s), ir.CLASS_UNKNOWN, s)
            self.assertFalse(ir.is_success(s), s)

    def test_only_ingested_statuses_are_success(self):
        self.assertTrue(ir.is_success("ok"))
        self.assertTrue(ir.is_success("already_present"))
        for s in ("event_mode_excluded", "target_not_indexed", "error",
                  "no_detail", "short_game", "staged_cap_reached"):
            self.assertFalse(ir.is_success(s), s)

    def test_classes_are_disjoint(self):
        seen: dict[str, str] = {}
        for cls, members in ir.STATUS_CLASSES.items():
            for s in members:
                self.assertNotIn(s, seen, f"{s} in {seen.get(s)} and {cls}")
                seen[s] = cls

    def test_nothing_to_do_ends_are_not_recorded(self):
        self.assertFalse(ir.should_record("not_indexed_retry_scheduled"))
        self.assertFalse(ir.should_record("awaiting_pin_retry_scheduled"))
        self.assertFalse(ir.should_record("duplicate_target"))
        self.assertTrue(ir.should_record("ok"))
        # An unknown terminal status IS recorded - hiding it is the defect.
        self.assertTrue(ir.should_record("brand_new_outcome"))


class AppendNeverRaisesTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="y08_rcpt_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_row_shape(self):
        path = self.tmp / "r.jsonl"
        ok = ir.append_receipt(
            {"status": "ok", "match_id": TARGET_ID, "pinned": True},
            scheduled_at=1000.0, attempt=2, now=1300.5, path=path)
        self.assertTrue(ok)
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["target"], TARGET_ID)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["elapsed_s"], 300.5)
        self.assertIs(row["parked"], False)
        self.assertEqual(row["ts"], 1300.5)
        for key in ("v", "pinned", "fallback", "cause"):
            self.assertIn(key, row)

    def test_append_only(self):
        path = self.tmp / "r.jsonl"
        for i in range(3):
            ir.append_receipt({"status": "ok", "match_id": f"NA1_{i}"},
                              scheduled_at=0.0, attempt=0, now=float(i), path=path)
        targets = [json.loads(x)["target"]
                   for x in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(targets, ["NA1_0", "NA1_1", "NA1_2"])

    def test_path_is_a_directory(self):
        self.assertFalse(ir.append_receipt({"status": "ok"}, path=self.tmp))

    def test_parent_is_a_file(self):
        blocker = self.tmp / "file"
        blocker.write_text("x", encoding="utf-8")
        self.assertFalse(ir.append_receipt({"status": "ok"},
                                           path=blocker / "r.jsonl"))

    def test_garbage_result_shapes(self):
        path = self.tmp / "r.jsonl"
        for bad in (None, 5, "ok", [], {"status": object()},
                    {"status": "ok", "match_id": object()},
                    {"status": "ok", "attempt": "x"}):
            ir.append_receipt(bad, scheduled_at=float("nan"),
                              attempt="nope", path=path)  # must not raise

    def test_open_raising_anything_is_swallowed(self):
        with mock.patch.object(ir, "_append_line",
                               side_effect=RuntimeError("disk on fire")):
            self.assertFalse(ir.append_receipt({"status": "ok"},
                                               path=self.tmp / "r.jsonl"))

    def test_nothing_to_do_writes_no_row(self):
        path = self.tmp / "r.jsonl"
        self.assertFalse(ir.append_receipt(
            {"status": "duplicate_target", "match_id": TARGET_ID}, path=path))
        self.assertFalse(ir.append_receipt(
            {"status": "not_indexed_retry_scheduled"}, path=path))
        self.assertFalse(path.exists())

    def test_reader_skips_malformed_lines(self):
        path = self.tmp / "r.jsonl"
        path.write_text('{"status": "ok", "ts": 1}\nnot json\n[1]\n'
                        '{"status": "error", "ts": 2}\n{"trunc', encoding="utf-8")
        rows = ir.read_receipts(path)
        self.assertEqual([r["status"] for r in rows], ["ok", "error"])

    def test_conftest_redirects_the_live_receipt_path(self):
        """No test in the suite may append to the real ops/runtime log."""
        live = ROOT / "ops" / "runtime" / ir.RECEIPT_PATH.name
        self.assertNotEqual(ir.RECEIPT_PATH.resolve(), live.resolve())


class WriterHookTests(_PinBase):
    """The receipt is written where each staged chain ENDS, exactly once."""

    def setUp(self):
        super().setUp()
        self.rpath = self.tmp / "receipts.jsonl"
        p = mock.patch.object(ir, "RECEIPT_PATH", self.rpath)
        p.start()
        self.addCleanup(p.stop)

    def rows(self):
        if not self.rpath.exists():
            return []
        return [json.loads(x) for x in self.rpath.read_text(encoding="utf-8").splitlines()]

    def test_ok_after_a_retry_writes_one_receipt_at_the_end(self):
        self.seed(PREV_ID)
        self.write_pin()
        self.riot([[PREV_ID], [TARGET_ID, PREV_ID]])
        r1 = self.first_attempt(scheduled_at=time.time() - 30)
        self.assertEqual(r1["status"], "not_indexed_retry_scheduled")
        self.assertEqual(self.rows(), [], "an intermediate attempt wrote a receipt")
        r2 = _FakeTimer.created[0].fire()
        self.assertEqual(r2["status"], "ok", r2)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], TARGET_ID)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["attempts"], 2)
        self.assertGreaterEqual(rows[0]["elapsed_s"], 30.0)
        self.assertIs(rows[0]["parked"], False)
        self.assertIs(rows[0]["pinned"], True)

    def test_never_indexed_chain_receipt_is_parked(self):
        self.seed(PREV_ID)
        self.write_pin()
        self.riot([[PREV_ID]])
        result = self.first_attempt()
        while result["status"].endswith("_retry_scheduled"):
            self.assertEqual(self.rows(), [])
            result = _FakeTimer.created[-1].fire()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "target_not_indexed")
        self.assertIs(rows[0]["parked"], True)
        self.assertEqual(rows[0]["attempts"], len(rlw.STAGED_DELAYS_S) + 1)

    def test_event_mode_receipt(self):
        self.write_pin(queue_id=2400, game_mode="KIWI")
        self.riot([[PREV_ID]])
        self.first_attempt()
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["event_mode_excluded"])
        self.assertEqual(rows[0]["target"], TARGET_ID)

    def test_duplicate_chain_writes_no_receipt(self):
        self.write_pin()
        self.riot([[PREV_ID]])
        self.first_attempt(chain="chain-a")
        r = self.first_attempt(chain="chain-b")
        self.assertEqual(r["status"], "duplicate_target")
        self.assertEqual(self.rows(), [])

    def test_receipt_failure_never_reaches_the_writer(self):
        self.seed(TARGET_ID)
        self.write_pin()
        self.riot([[TARGET_ID]])
        with mock.patch.object(ir, "_append_line",
                               side_effect=OSError("read-only volume")):
            r = self.first_attempt()
        self.assertEqual(r["status"], "already_present")

    def test_receipt_module_import_failure_never_reaches_the_writer(self):
        self.seed(TARGET_ID)
        self.write_pin()
        self.riot([[TARGET_ID]])
        with mock.patch.dict(sys.modules, {"lib.ingest_receipt": None}):
            r = self.first_attempt()
        self.assertEqual(r["status"], "already_present")


class BuilderTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="y08_card_"))
        self.paths = {
            "receipt_path": self.tmp / "ops" / "runtime" / "receipts.jsonl",
            "state_path": self.tmp / "data" / "rewind_catchup.state.json",
            "db_path": self.tmp / "data" / "rewind_history.db",
            "pin_path": self.tmp / "ops" / "runtime" / "last_game_end.json",
        }
        env = mock.patch.dict("os.environ", {"RC_RIOT_PLATFORM": "NA1"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, now=2_000_000_000.0):
        return ops_panels.compute_ingest_freshness(now=now, **self.paths)

    def make_db(self, *rows, retry=()):
        from scripts.rewind_scraper import SCHEMA
        from scripts.rewind_catchup import RETRY_TABLE_SQL
        self.paths["db_path"].parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.paths["db_path"]))
        try:
            conn.executescript(SCHEMA)
            conn.execute(RETRY_TABLE_SQL)
            conn.executemany(
                "INSERT INTO matches (match_id, game_end_ts) VALUES (?, ?)", rows)
            conn.executemany(
                "INSERT INTO fetch_retry (match_id, kind) VALUES (?, ?)", retry)
            conn.commit()
        finally:
            conn.close()

    def write_receipts(self, *rows):
        p = self.paths["receipt_path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_fresh_tree_has_explicit_no_receipt_basis(self):
        out = self.build()
        self.assertTrue(out["ok"])
        self.assertIsNone(out["last_receipt"])
        self.assertIn("no receipt yet", out["basis"])
        self.assertEqual(out["tally"]["rows"], 0)
        self.assertEqual(out["tally"]["success"], 0)
        self.assertEqual(out["catchup"]["last_run_outcome"], None)
        self.assertEqual(out["retry_backlog"]["total"], 0)
        self.assertEqual(out["lag"]["state"], "no_pin")
        self.assertFalse(any(p.exists() for p in self.paths.values()),
                         "the read-only builder created a file")

    def test_row_keys_identical_fresh_and_populated(self):
        """No reflow: the card has the same rows whether or not data exists."""
        fresh = self.build()
        self.make_db(("NA1_1", 1), retry=(("NA1_9", "timeline"),))
        self.write_receipts({"status": "ok", "target": "NA1_1", "ts": 1.0,
                             "attempts": 1, "elapsed_s": 90.0, "parked": False})
        full = self.build()
        self.assertEqual([r["key"] for r in fresh["rows"]],
                         [r["key"] for r in full["rows"]])
        self.assertGreaterEqual(len(fresh["rows"]), 5)
        for r in fresh["rows"] + full["rows"]:
            self.assertEqual(set(r), {"key", "label", "value", "state"})
            self.assertIn(r["state"], ("ok", "amber", "red", "unknown"))
            self.assertTrue(r["value"])

    def test_tally_by_name_and_unknown_is_not_success(self):
        self.write_receipts(
            {"status": "ok", "target": "NA1_1", "ts": 1.0},
            {"status": "already_present", "target": "NA1_2", "ts": 2.0},
            {"status": "event_mode_excluded", "target": "NA1_3", "ts": 3.0},
            {"status": "brand_new_outcome", "target": "NA1_4", "ts": 4.0},
            {"status": "target_not_indexed", "target": "NA1_5", "ts": 5.0,
             "parked": True},
        )
        out = self.build()
        t = out["tally"]
        self.assertEqual(t["rows"], 5)
        self.assertEqual(t["success"], 2)
        self.assertEqual(t["by_status"]["brand_new_outcome"], 1)
        self.assertEqual(t["by_class"][ir.CLASS_UNKNOWN], 1)
        self.assertEqual(t["by_class"][ir.CLASS_INGESTED], 2)
        last = out["last_receipt"]
        self.assertEqual(last["status"], "target_not_indexed")
        self.assertIs(last["success"], False)
        self.assertIs(last["parked"], True)

    def test_unknown_last_receipt_is_never_rendered_ok(self):
        self.write_receipts({"status": "brand_new_outcome", "target": "NA1_4",
                             "ts": 4.0})
        out = self.build()
        self.assertIs(out["last_receipt"]["success"], False)
        row = {r["key"]: r for r in out["rows"]}["last_receipt"]
        self.assertNotEqual(row["state"], "ok")

    def test_catchup_state_and_backlog(self):
        sp = self.paths["state_path"]
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({
            "last_run_at": "2026-09-27T09:00:00Z", "last_run_outcome": "hydrated",
            "last_run_rc": 0, "puuid": "secret-puuid", "riot_id": "Someone#TAG"}),
            encoding="utf-8")
        self.make_db(retry=(("NA1_7", "timeline"), ("NA1_8", "timeline"),
                            ("NA1_9", "match")))
        out = self.build()
        self.assertEqual(out["catchup"]["last_run_outcome"], "hydrated")
        self.assertEqual(out["catchup"]["last_run_at"], "2026-09-27T09:00:00Z")
        self.assertEqual(out["retry_backlog"]["by_kind"],
                         {"match": 1, "timeline": 2})
        self.assertEqual(out["retry_backlog"]["total"], 3)
        blob = json.dumps(out)
        self.assertNotIn("secret-puuid", blob)
        self.assertNotIn("Someone", blob)

    def test_state_without_outcome_reads_unrecorded(self):
        sp = self.paths["state_path"]
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"last_run_at": "2026-09-27T09:00:00Z"}),
                      encoding="utf-8")
        out = self.build()
        self.assertIsNone(out["catchup"]["last_run_outcome"])
        self.assertEqual(out["catchup"]["state"], "unrecorded")

    def _pin(self, game_id=TARGET_GAME, queue_id=450, written_at=None,
             mode="ARAM"):
        p = self.paths["pin_path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "game_id": game_id, "queue_id": queue_id, "game_mode": mode,
            "game_name": "Hidden Name", "tag_line": "HID",
            "written_at": written_at if written_at is not None else 1_999_999_000.0,
        }), encoding="utf-8")

    def test_lag_caught_up(self):
        self._pin()
        self.make_db((TARGET_ID, 1_999_998_000_000))
        out = self.build()
        self.assertEqual(out["lag"]["state"], "caught_up")
        self.assertEqual(out["lag"]["last_eog_target"], TARGET_ID)
        self.assertNotIn("Hidden Name", json.dumps(out))

    def test_lag_behind(self):
        self._pin(written_at=1_999_999_000.0)
        self.make_db((PREV_ID, 1_999_990_000_000))
        out = self.build(now=2_000_000_000.0)
        lag = out["lag"]
        self.assertEqual(lag["state"], "behind")
        self.assertEqual(lag["behind_s"], 1000.0)
        self.assertEqual(lag["newest_match_id"], PREV_ID)
        self.assertNotIn("Hidden Name", json.dumps(out))

    def test_lag_event_mode_is_excluded_not_behind(self):
        self._pin(queue_id=2400, mode="KIWI")
        self.make_db((PREV_ID, 1))
        self.assertEqual(self.build()["lag"]["state"], "excluded")

    def test_garbage_everywhere_never_raises(self):
        for key in ("receipt_path", "state_path", "pin_path"):
            p = self.paths[key]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfe{{{ not json")
        self.paths["db_path"].parent.mkdir(parents=True, exist_ok=True)
        self.paths["db_path"].write_bytes(b"not a sqlite file at all" * 10)
        out = self.build()
        self.assertTrue(out["ok"])
        self.assertIsNone(out["last_receipt"])
        self.assertIn(out["lag"]["state"], ("no_pin", "unknown"))


class CardWiringTests(unittest.TestCase):
    """Backend row list, JS row list and the page mount must agree."""

    def test_js_row_keys_match_backend(self):
        src = (ROOT / "web" / "js" / "panels" / "ops_panels.js").read_text(
            encoding="utf-8")
        m = re.search(r"export const INGEST_KEYS = \[([^\]]*)\]", src)
        self.assertIsNotNone(m, "INGEST_KEYS not found in ops_panels.js")
        js_keys = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
        self.assertEqual(js_keys, ops_panels.INGEST_ROW_KEYS)

    def test_page_mounts_the_card_and_route_is_registered(self):
        html = (ROOT / "web" / "ops.html").read_text(encoding="utf-8")
        self.assertIn('id="ingest-freshness-panel"', html)
        from dashboard import routes_ops_panels as r
        handlers = [h for _m, h in r.GET_ROUTES]
        self.assertIn(r._serve_ingest_freshness, handlers)
        self.assertEqual(r.POST_ROUTES, [],
                         "Y-08 is read-only: no retry/give-up POST shipped")


if __name__ == "__main__":
    unittest.main()
