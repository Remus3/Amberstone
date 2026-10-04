"""core/recycle_bin.py - CHECKED send-to-Recycle-Bin (RM-640, fleet rule 9).

Windows silently PERMANENTLY deletes a file that is too large for the bin
(or any file on a volume whose bin is disabled) even when FOF_ALLOWUNDO is
set. recycle_checked() therefore refuses BEFORE the shell call whenever it
cannot prove the bin will take the file, and after the call it confirms the
item actually landed in the bin by reading the bin's own index.

No test here touches a real file or the real Recycle Bin: every OS call goes
through an injected fake API, and the fake's delete only flips state.
"""
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import core.recycle_bin as rb

GB = 10**9


class FakeApi:
    """Stands in for the shell. `delete` never touches the disk."""

    def __init__(self, *, size=1 * GB, kind="file", policy=(50 * GB, False),
                 delete_rc=0, lands=True, vanishes=True):
        self.size_ = size
        self.kind_ = kind
        self.policy_ = policy
        self.delete_rc = delete_rc
        self.lands = lands
        self.vanishes = vanishes
        self.deleted = []
        self.present = True

    def kind(self, path):
        return self.kind_ if self.present else None

    def size(self, path):
        return self.size_

    def bin_policy(self, path):
        return self.policy_

    def delete_allow_undo(self, path):
        self.deleted.append(str(path))
        if self.delete_rc == 0 and self.vanishes:
            self.present = False
        return self.delete_rc

    def exists(self, path):
        return self.present

    def now(self):
        self.now_calls = getattr(self, "now_calls", 0) + 1
        assert not self.deleted, "clock must be read BEFORE the shell call"
        return 1000.0

    def bin_contains(self, path, since=None):
        self.since_seen = since
        return bool(self.deleted) and self.lands


# Drive-less synthetic path: the fake API never resolves or touches it.
P = Path("synthetic") / "not-a-real-dir" / "match.mp4"


def test_happy_path_recycles_and_confirms():
    api = FakeApi()
    res = rb.recycle_checked(P, api=api)
    assert res.ok, res.detail
    assert res.method == rb.METHOD_RECYCLE_BIN
    assert api.deleted == [str(P)]
    # the landing check is bounded by the pre-call clock read
    assert api.since_seen == 1000.0


def test_refuses_when_file_larger_than_bin_capacity():
    api = FakeApi(size=60 * GB, policy=(50 * GB, False))
    res = rb.recycle_checked(P, api=api)
    assert not res.ok
    assert "too large" in res.detail
    assert api.deleted == [], "must refuse BEFORE the shell call"


def test_refuses_when_bin_nukes_on_delete():
    api = FakeApi(policy=(50 * GB, True))
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and api.deleted == []


def test_refuses_when_bin_policy_unreadable():
    # e.g. a volume with no BitBucket key, or a network path: no proof the
    # bin exists, so fail closed rather than risk a silent nuke.
    api = FakeApi(policy=None)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and api.deleted == []


def test_refuses_non_regular_file():
    for kind in ("link", "dir", None):
        api = FakeApi(kind=kind)
        res = rb.recycle_checked(P, api=api)
        assert not res.ok and api.deleted == [], kind


def test_reports_nuke_when_file_gone_but_not_in_bin():
    api = FakeApi(lands=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok
    assert res.nuked is True
    assert "NOT found in the Recycle Bin" in res.detail


def test_shell_error_is_failure():
    api = FakeApi(delete_rc=0x78)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and not res.nuked


def test_still_present_after_call_is_failure():
    api = FakeApi(vanishes=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and "still present" in res.detail


def test_shfileop_flags_never_drop_allowundo():
    assert rb.SHFILEOP_FLAGS & rb.FOF_ALLOWUNDO
    for f in (rb.FOF_NOCONFIRMATION, rb.FOF_SILENT, rb.FOF_NOERRORUI):
        assert rb.SHFILEOP_FLAGS & f


def _filetime(epoch: float) -> int:
    return int((epoch + 11644473600) * 10**7)


def _i_file_v2(original: str, deleted_at: float = 0.0) -> bytes:
    name = original + "\0"
    ft = _filetime(deleted_at) if deleted_at else 0
    return (struct.pack("<qqqi", 2, 123, ft, len(name))
            + name.encode("utf-16-le"))


def test_parse_index_record_reads_deletion_time(tmp_path):
    orig = str(tmp_path / "V" / "a.mp4")
    rec = rb.parse_index_record(_i_file_v2(orig, 1_700_000_000.0))
    assert rec[0] == orig
    assert abs(rec[1] - 1_700_000_000.0) < 1e-3


def test_older_record_of_same_path_does_not_count_as_landed(tmp_path):
    # An earlier recycle of the same path left a $I record; a NEW call that
    # nuked the file must not be confirmed by that stale record.
    sid = tmp_path / "S-1-5-21-0"
    sid.mkdir()
    m = str(tmp_path / "V" / "m.mp4")
    (sid / "$IOLD.mp4").write_bytes(_i_file_v2(m, 1000.0))
    assert not rb.index_dirs_contain([sid], m, since=5000.0)
    (sid / "$INEW.mp4").write_bytes(_i_file_v2(m, 5000.5))
    assert rb.index_dirs_contain([sid], m, since=5000.0)
    # FILETIME rounding just under the clock read is tolerated
    (sid / "$INEW.mp4").write_bytes(_i_file_v2(m, 4999.0))
    assert rb.index_dirs_contain([sid], m, since=5000.0)


def _i_file_v1(original: str) -> bytes:
    raw = original.encode("utf-16-le")
    return struct.pack("<qqq", 1, 123, 0) + raw + b"\0" * (520 - len(raw))


def test_parse_index_file_v1_and_v2(tmp_path):
    orig = str(tmp_path / "Videos" / "m1.mp4")
    assert rb.parse_index_file(_i_file_v2(orig)) == orig
    assert rb.parse_index_file(_i_file_v1(orig)) == orig
    assert rb.parse_index_file(b"junk") is None


def test_index_dir_contains_matches_by_normcase(tmp_path):
    sid = tmp_path / "S-1-5-21-0"
    sid.mkdir()
    orig = str(tmp_path / "Videos" / "M1.mp4")
    (sid / "$IABC123.mp4").write_bytes(_i_file_v2(orig))
    (sid / "$RABC123.mp4").write_bytes(b"payload")
    assert rb.index_dirs_contain([sid], orig)
    # Case-insensitive exactly where the OS path rules are (Windows).
    assert rb.index_dirs_contain([sid], orig.lower()) == (
        os.path.normcase("A") == os.path.normcase("a"))
    assert not rb.index_dirs_contain([sid], str(tmp_path / "Videos" / "m2.mp4"))
