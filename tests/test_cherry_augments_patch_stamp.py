"""The Arena augment catalogue must be refetched when its patch stamp is stale.

MEASURED 2026-09-20 (DS refresh 16.15.1 -> 16.18.1): every patch dir from
16.10.1 on carried a byte-identical ``cherry_augments.json`` stamped
``rc_patch`` 16.10.1, fetched 2026-05-18. Against the live CDragon feed it
lacked ~90 current augments and carried ~92 removed ones. Root cause:
``augment_external_source._refresh_meta`` short-circuited on "file exists",
and each refresh copied the old file forward, so the fetch never ran again.
The file's own ``rc_patch`` now has to match the patch it serves.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.augment_external_source as X

_REPO = Path(__file__).resolve().parents[1]


def _cherry(ids):
    return [{"id": i, "nameTRA": f"Aug {i}", "rarity": "kGold",
             "augmentSmallIconPath": f"/x/{i}.png"} for i in ids]


class StaleStampRefetch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "tp").mkdir()
        self._p = [
            mock.patch.object(X, "_DS_DATA_DIR", self.root),
            mock.patch.object(X, "_current_patch", lambda: "tp"),
        ]
        for p in self._p:
            p.start()
        X.reset_cache()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()
        X.reset_cache()
        self._td.cleanup()

    def _seed(self, rc_patch, ids):
        snap = X._build_meta(rc_patch, _cherry(ids))
        (self.root / "tp" / "cherry_augments.json").write_text(
            json.dumps(snap), encoding="utf-8")

    def test_copied_forward_file_with_old_stamp_is_refetched(self):
        self._seed("16.10.1", [1, 2])
        calls = []

        def fetch(url, timeout):
            calls.append(url)
            return _cherry([1, 2, 3])

        with mock.patch.object(X, "_http_get", fetch):
            table = X.refresh_meta_cache(force=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(table.name(3), "Aug 3")
        disk = json.loads((self.root / "tp" / "cherry_augments.json").read_text(
            encoding="utf-8"))
        self.assertEqual(disk["rc_patch"], "tp")

    def test_matching_stamp_does_not_fetch(self):
        self._seed("tp", [1, 2])
        with mock.patch.object(X, "_http_get",
                               mock.Mock(side_effect=AssertionError("fetched"))):
            table = X.refresh_meta_cache(force=False)
        self.assertEqual(table.name(1), "Aug 1")

    def test_stale_file_still_serves_during_an_outage(self):
        self._seed("16.10.1", [1, 2])
        with mock.patch.object(X, "_http_get",
                               mock.Mock(side_effect=X.AugmentSourceError("down"))):
            table = X.refresh_meta_cache(force=False)
        self.assertTrue(table.has_data)
        self.assertEqual(table.name(2), "Aug 2")


def test_committed_current_catalogue_is_stamped_for_its_patch():
    ds = _REPO / "data" / "daemon_slayer"
    patch = (ds / "current.txt").read_text(encoding="utf-8").strip()
    snap = json.loads((ds / patch / "cherry_augments.json").read_text(
        encoding="utf-8"))
    assert snap["rc_patch"] == patch
    assert snap["count"] == len(snap["augments"]) > 100
