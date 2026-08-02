"""RM-128: ground the hand-maintained queue map against Riot's own catalog.

`core/queue_modes.QUEUE_ID_TO_MODE_KEY` is 21 entries typed out from a stashed
post-game LCU payload. CDragon's `queues.json` is the canonical 420-record
superset. Nothing tied the two together, so a retired or re-grouped queue id
could sit in RC's map indefinitely.

Shape of the guard: the daily `tools/upstream_drift_check.py` probe fingerprints
the live catalog (`cdragon_queue_catalog`), and THIS test runs offline against
`data/queue_catalog_snapshot.json`, refreshed by
`--refresh-queue-snapshot` after a human reviews a drift. Offline is
deliberate - a network fetch inside the suite is a flake, and skipping on a
network error is the always-passing-guard failure class this repo already hit.

TWO PARTS OF THE FILED ACCEPTANCE WERE REFUTED BY MEASUREMENT (2026-08-01) and
must not be reinstated:

1. "FAILS if any live kARAM / kAlternativeLeagueGameModes queue id is absent
   from the map" is not implementable. Measured: 16 kARAM and 256
   kAlternativeLeagueGameModes records exist against 21 mapped ids. The
   unmapped remainder is retired and cosmetic content (Doom Bots, old One-for-
   All variants, tutorial ids, id 0 duplicates). That rule is red on day one
   and forever, so it would be switched off, not acted on.

2. "its gameSelectModeGroup is consistent with the mapped mode_key" does not
   hold either: 900 ARURF, 1020 One For All, 1400 Ultimate Spellbook and 1900
   URF map to `sr`, 920 Poro King maps to `aram`, and 1700/1710/1750 map to
   `arena` - all EIGHT of them sit in `kAlternativeLeagueGameModes`. The group
   is a client menu grouping, not a game-mode classifier.

What IS enforceable, and is what this file asserts: every mapped id still
exists upstream, its group is still a non-null and known group, the map and the
snapshot stay in step, and every mode_key is a real dashboard mode.

Deliberate gap, measured by mutation rather than assumed: a REGROUP between two
groups that both already appear in the snapshot (say 450 moving kARAM ->
kSummonersRift) does NOT turn the offline half red, because the snapshot is
re-written from the same upstream it would be compared against. That case is
covered only by the live `cdragon_queue_catalog` fingerprint, which moves on any
id:group change. Do not read the offline assertions as catching it.

ITEM-87 SAFE: live mode detection in `core/game_snapshot.py` is gameMode-STRING
based and never reads queueId, so nothing here touches the settled keystone /
view-router.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import upstream_drift_check as udc  # noqa: E402
from core.queue_modes import QUEUE_ID_TO_MODE_KEY  # noqa: E402

SNAPSHOT_PATH = ROOT / "data" / "queue_catalog_snapshot.json"


def _snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


class SnapshotIntegrityTests(unittest.TestCase):
    def test_snapshot_exists_and_is_the_committed_grounding(self):
        self.assertTrue(SNAPSHOT_PATH.exists(),
                        "run: python tools/upstream_drift_check.py "
                        "--refresh-queue-snapshot")
        snap = _snapshot()
        self.assertEqual(snap["source"], udc.CDRAGON_QUEUES_URL)
        self.assertGreater(snap["entry_count"], 300)
        self.assertEqual(len(snap["fingerprint"]), 16)

    def test_tool_points_at_the_committed_snapshot_path(self):
        self.assertEqual(udc.QUEUE_SNAPSHOT_PATH, SNAPSHOT_PATH)


class QueueMapGroundingTests(unittest.TestCase):
    """The map vs the catalog. Failure here means REVIEW the map, not the test."""

    def setUp(self):
        self.snap = _snapshot()
        self.mapped = self.snap["mapped_queues"]

    def test_map_and_snapshot_cover_the_same_ids(self):
        """Editing QUEUE_ID_TO_MODE_KEY without refreshing the snapshot fails."""
        self.assertEqual(
            {str(q) for q in QUEUE_ID_TO_MODE_KEY},
            set(self.mapped),
            "queue map and snapshot are out of step - re-run "
            "tools/upstream_drift_check.py --refresh-queue-snapshot")

    def test_every_mapped_queue_id_still_exists_upstream(self):
        missing = [qid for qid, rec in self.mapped.items() if not rec["present"]]
        self.assertEqual(missing, [],
                         f"mapped queue ids absent from queues.json: {missing}")

    def test_every_mapped_queue_still_has_its_recorded_group(self):
        for qid, rec in sorted(self.mapped.items()):
            with self.subTest(queue_id=qid):
                self.assertIsNotNone(
                    rec["group"],
                    f"queue {qid} ({rec['name']}) lost its gameSelectModeGroup")
                self.assertIn(rec["group"], self.snap["group_counts"])

    def test_mode_keys_are_real_dashboard_modes(self):
        from dashboard._state_builder import MODE_TO_FILE

        for qid, mode_key in sorted(QUEUE_ID_TO_MODE_KEY.items()):
            with self.subTest(queue_id=qid):
                self.assertIn(mode_key, MODE_TO_FILE)

    def test_snapshot_mode_keys_match_the_live_map(self):
        for qid, mode_key in sorted(QUEUE_ID_TO_MODE_KEY.items()):
            with self.subTest(queue_id=qid):
                self.assertEqual(self.mapped[str(qid)]["mode_key"], mode_key)

    def test_the_four_load_bearing_ids_are_grounded(self):
        """The ids that actually deliver a pre-game coach payload today."""
        for qid, expect_mode in ((450, "aram"), (2400, "aram"),
                                 (1750, "arena"), (420, "sr")):
            with self.subTest(queue_id=qid):
                rec = self.mapped[str(qid)]
                self.assertTrue(rec["present"])
                self.assertEqual(rec["mode_key"], expect_mode)


class CatalogProbeTests(unittest.TestCase):
    """The daily signal itself - offline, over synthetic catalogs."""

    def setUp(self):
        udc._LAST_ERRORS["cdragon_queue_catalog"] = None

    def _cat(self, *pairs):
        return [{"id": qid, "gameSelectModeGroup": grp, "name": f"q{qid}"}
                for qid, grp in pairs]

    def test_fingerprint_ignores_record_order(self):
        a = udc._short_hash(udc._queue_catalog_pairs(
            self._cat((450, "kARAM"), (420, "kSummonersRift"))))
        b = udc._short_hash(udc._queue_catalog_pairs(
            self._cat((420, "kSummonersRift"), (450, "kARAM"))))
        self.assertEqual(a, b)

    def test_fingerprint_ignores_cosmetic_fields(self):
        base = self._cat((450, "kARAM"))
        renamed = [{**base[0], "name": "ARAM (Reworked)", "shortName": "AR"}]
        self.assertEqual(
            udc._short_hash(udc._queue_catalog_pairs(base)),
            udc._short_hash(udc._queue_catalog_pairs(renamed)))

    def test_a_regrouped_queue_moves_the_fingerprint(self):
        before = udc._short_hash(udc._queue_catalog_pairs(
            self._cat((920, "kAlternativeLeagueGameModes"))))
        after = udc._short_hash(udc._queue_catalog_pairs(
            self._cat((920, "kARAM"))))
        self.assertNotEqual(before, after)

    def test_a_new_queue_moves_the_fingerprint(self):
        before = udc._short_hash(udc._queue_catalog_pairs(self._cat((450, "kARAM"))))
        after = udc._short_hash(udc._queue_catalog_pairs(
            self._cat((450, "kARAM"), (2410, "kARAM"))))
        self.assertNotEqual(before, after)

    def test_probe_is_fail_soft_on_a_dead_endpoint(self):
        from unittest import mock

        with mock.patch.object(udc, "fetch_queue_catalog",
                               side_effect=OSError("connection refused")):
            got = udc.probe_cdragon_queue_catalog()   # must not raise
        self.assertIsNone(got)
        self.assertIn("connection refused",
                      udc._LAST_ERRORS["cdragon_queue_catalog"] or "")

    def test_probe_rejects_a_shape_change_instead_of_hashing_junk(self):
        from unittest import mock

        with mock.patch.object(udc, "fetch_queue_catalog",
                               return_value={"queues": []}):
            self.assertIsNone(udc.probe_cdragon_queue_catalog())
        self.assertIsNotNone(udc._LAST_ERRORS["cdragon_queue_catalog"])

    def test_an_errored_catalog_probe_is_never_changed(self):
        fields = udc.compute_fields(
            {"cdragon_queue_catalog": "8039fde2e98fc392"},
            {"cdragon_queue_catalog": None},
            {"cdragon_queue_catalog": "OSError: connection refused"})
        f = next(x for x in fields if x.name == "cdragon_queue_catalog")
        self.assertFalse(f.changed)


if __name__ == "__main__":
    unittest.main()
