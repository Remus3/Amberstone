"""True-audit regressions for core/recycle_bin.py (lane 8, S144-T).

recycle_checked() promises "send ONE file to the Recycle Bin, or refuse" -
a RecycleResult on every path, never an exception. Both callers
(core.vod_retention.apply, tools/progress_watch.reap) loop over many files
and read only the result; an exception escaping mid-batch aborts the loop
and loses the report of every file already recycled before it.

No test here recycles a real file: the shell layer is a fake, and the
WindowsShellApi tests stub winreg / the volume lookups and only stat a
path that cannot exist.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import core.recycle_bin as rb

GB = 10**9
P = Path("synthetic") / "not-a-real-dir" / "match.mp4"
# Drive-less synthetic original path for $I records (never resolved).
SYN = "synthetic\\V\\m.mp4"


class RaisingApi:
    """A fake shell whose named method raises; the rest behave."""

    def __init__(self, raise_in=None, exc=OSError("boom"), *, gone=True,
                 exists_raises=False, lands=True):
        self.raise_in = raise_in
        self.exc = exc
        self.deleted = []
        self.gone = gone
        self.exists_raises = exists_raises
        self.lands = lands

    def _maybe(self, name):
        if self.raise_in == name:
            raise self.exc

    def kind(self, path):
        self._maybe("kind")
        return "file"

    def size(self, path):
        self._maybe("size")
        return 1 * GB

    def bin_policy(self, path):
        self._maybe("bin_policy")
        return (50 * GB, False)

    def now(self):
        self._maybe("now")
        return 1000.0

    def delete_allow_undo(self, path):
        self.deleted.append(str(path))
        self._maybe("delete_allow_undo")
        return 0

    def exists(self, path):
        if self.exists_raises:
            raise OSError("exists boom")
        self._maybe("exists")
        return not (self.deleted and self.gone)

    def bin_contains(self, path, since=None):
        self._maybe("bin_contains")
        return bool(self.deleted) and self.gone and self.lands


# -- F1: an API exception never escapes recycle_checked ------------------------


@pytest.mark.parametrize("where", ["kind", "size", "bin_policy", "now"])
@pytest.mark.parametrize("exc", [OSError("gone"), ValueError("bad"),
                                 TypeError("bad")])
def test_preflight_exception_is_a_refusal_before_the_shell_call(where, exc):
    api = RaisingApi(where, exc)
    res = rb.recycle_checked(P, api=api)
    assert isinstance(res, rb.RecycleResult)
    assert not res.ok and not res.nuked
    assert res.detail.startswith("refused:")
    assert api.deleted == [], "must refuse BEFORE the shell call"


def test_shell_call_exception_file_gone_not_in_bin_halts_as_nuked():
    api = RaisingApi("delete_allow_undo", OSError("ctypes boom"), lands=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok
    assert res.nuked is True, "unconfirmed delete must halt the caller"
    assert "OSError" in res.detail


def test_shell_call_exception_but_fresh_bin_record_is_a_landing():
    # The $I record stamped after the pre-call clock read IS the proof the
    # module trusts; a raise from the ctypes wrapper does not undo it.
    api = RaisingApi("delete_allow_undo", OSError("ctypes boom"))
    res = rb.recycle_checked(P, api=api)
    assert res.ok and not res.nuked
    assert "raised OSError" in res.detail


def test_shell_call_exception_with_file_present_is_plain_failure():
    api = RaisingApi("delete_allow_undo", OSError("ctypes boom"), gone=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and res.nuked is False
    assert "still present" in res.detail


def test_shell_call_non_integer_rc_is_confirmed_not_formatted():
    class StrRc(RaisingApi):
        def delete_allow_undo(self, path):
            self.deleted.append(str(path))
            return "0"

    res = rb.recycle_checked(P, api=StrRc(lands=False))
    assert not res.ok and res.nuked is True


def test_shell_call_exception_unreadable_presence_not_in_bin_halts():
    api = RaisingApi("delete_allow_undo", OSError("ctypes boom"),
                     exists_raises=True, lands=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and res.nuked is True


def test_confirm_bin_index_exception_after_shell_success_halts():
    api = RaisingApi("bin_contains", OSError("confirm boom"))
    res = rb.recycle_checked(P, api=api)
    assert api.deleted == [str(P)]
    assert not res.ok
    assert res.nuked is True, "cannot prove the landing - caller must halt"
    assert "raised OSError" in res.detail


def test_confirm_exists_exception_falls_through_to_the_bin_proof():
    api = RaisingApi("exists", OSError("confirm boom"))
    res = rb.recycle_checked(P, api=api)
    assert res.ok, res.detail
    api = RaisingApi("exists", OSError("confirm boom"), lands=False)
    res = rb.recycle_checked(P, api=api)
    assert not res.ok and res.nuked is True


def test_truthy_non_bool_bin_answer_is_not_proof():
    class Junk(RaisingApi):
        def bin_contains(self, path, since=None):
            return "yes"

    res = rb.recycle_checked(P, api=Junk())
    assert not res.ok and res.nuked is True


def test_exception_detail_names_the_type_only():
    api = RaisingApi("size", OSError("synthetic\\secret\\path detail"))
    res = rb.recycle_checked(P, api=api)
    assert "OSError" in res.detail
    assert "secret" not in res.detail


def test_vod_retention_batch_survives_a_raising_api(monkeypatch):
    # vod_retention.apply documents "Never raises for a per-file failure":
    # the raising row is a failure and the rows around it stay recorded.
    import types

    import core.vod_retention as vr

    calls = []

    def recycler(path):
        calls.append(path)
        api = RaisingApi("size" if len(calls) == 2 else None)
        return rb.recycle_checked(path, api=api)

    class _Row:
        def __init__(self, path):
            self.path = path
            self.size_bytes = 1

    class _D:
        def __init__(self, path):
            self.row = _Row(path)

    plan = types.SimpleNamespace(
        candidates=[_D("a.mp4"), _D("b.mp4"), _D("c.mp4")])
    monkeypatch.setattr(vr, "_fence_violation", lambda d: None)
    out = vr.apply(plan, dry_run=False, confirm=vr.CONFIRM_TOKEN,
                   recycler=recycler)
    assert out["halted"] is False
    assert [e["path"] for e in out["recycled"]] == ["a.mp4", "c.mp4"]
    assert [e["path"] for e in out["failed"]] == ["b.mp4"]


# -- F2: NUL / wildcard paths are refused before any API call --------------------


@pytest.mark.parametrize("bad", ["a\0b.mp4", "dir\\*.mp4", "dir\\m?.mp4"])
def test_nul_or_wildcard_path_refused_before_any_api_call(bad):
    class NoTouch:
        def __getattr__(self, name):
            raise AssertionError(f"API touched: {name}")

    res = rb.recycle_checked(bad, api=NoTouch())
    assert not res.ok and not res.nuked
    assert res.detail.startswith("refused:")


@pytest.mark.skipif(sys.platform != "win32", reason="WindowsShellApi")
def test_windows_kind_on_embedded_nul_is_none_not_valueerror():
    assert rb.WindowsShellApi().kind("synthetic\0nope.mp4") is None


# -- F3: an unparseable bin policy is unprovable, not a crash --------------------


class _FakeKey:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_winreg(monkeypatch, policies, bitbucket):
    import winreg

    def open_key(hive, sub):
        if sub == rb._POLICIES:
            vals = policies.get(hive)
        else:
            vals = bitbucket
        if vals is None:
            raise OSError("no key")
        return _FakeKey(vals)

    def query(key, name):
        if name not in key.values:
            raise OSError("no value")
        return (key.values[name], 4)

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", query)
    return winreg


def _policy_api(monkeypatch):
    api = rb.WindowsShellApi()
    monkeypatch.setattr(api, "_mount_point", lambda p: "synthetic-mount\\")
    monkeypatch.setattr(api, "_volume_guid", lambda m: "{guid}")
    return api


@pytest.mark.skipif(sys.platform != "win32", reason="winreg")
def test_bin_policy_reads_capacity_and_nuke(monkeypatch):
    api = _policy_api(monkeypatch)
    _stub_winreg(monkeypatch, {}, {"MaxCapacity": 100, "NukeOnDelete": 0})
    assert api.bin_policy("x") == (100 * 1024 * 1024, False)


@pytest.mark.skipif(sys.platform != "win32", reason="winreg")
@pytest.mark.parametrize("bucket", [
    {"MaxCapacity": "not-a-number", "NukeOnDelete": 0},
    {"MaxCapacity": 100, "NukeOnDelete": b"\x01"},
    {"MaxCapacity": None, "NukeOnDelete": 0},
    {"MaxCapacity": -5, "NukeOnDelete": 0},
])
def test_bin_policy_unparseable_value_is_unprovable(monkeypatch, bucket):
    api = _policy_api(monkeypatch)
    _stub_winreg(monkeypatch, {}, bucket)
    assert api.bin_policy("x") is None


@pytest.mark.skipif(sys.platform != "win32", reason="winreg")
@pytest.mark.parametrize("val", [1, 2, 0xFFFFFFFF, "x"])
def test_no_recycle_files_policy_nonzero_or_garbage_fails_closed(
        monkeypatch, val):
    import winreg
    api = _policy_api(monkeypatch)
    _stub_winreg(monkeypatch, {winreg.HKEY_LOCAL_MACHINE: {"NoRecycleFiles": val}},
                 {"MaxCapacity": 100, "NukeOnDelete": 0})
    pol = api.bin_policy("x")
    assert pol is None or pol[1] is True


@pytest.mark.skipif(sys.platform != "win32", reason="winreg")
def test_no_recycle_files_zero_is_permissive(monkeypatch):
    import winreg
    api = _policy_api(monkeypatch)
    _stub_winreg(monkeypatch, {winreg.HKEY_CURRENT_USER: {"NoRecycleFiles": 0}},
                 {"MaxCapacity": 100, "NukeOnDelete": 0})
    assert api.bin_policy("x") == (100 * 1024 * 1024, False)


# -- F4: a truncated $I record is not proof of a landing --------------------------


def _v2(original: str, declared: int = None) -> bytes:
    name = original + "\0"
    n = len(name) if declared is None else declared
    return struct.pack("<qqqi", 2, 1, 0, n) + name.encode("utf-16-le")


def test_v2_record_shorter_than_declared_length_is_rejected():
    # Declared length runs past the bytes present: the tail of the real
    # path is missing, so the readable prefix could name a DIFFERENT file.
    assert rb.parse_index_record(_v2(SYN, declared=40)) is None


def test_v2_truncated_prefix_cannot_confirm_a_different_file(tmp_path):
    sid = tmp_path / "S-1-5-21-0"
    sid.mkdir()
    longer = SYN + ".part"
    # Record for "...m.mp4.part" cut short after "...m.mp4".
    data = _v2(longer)
    cut = 28 + 2 * len(SYN)
    (sid / "$ICUT.mp4").write_bytes(data[:cut])
    assert not rb.index_dirs_contain([sid], SYN)


def test_v1_record_shorter_than_fixed_field_is_rejected():
    raw = SYN.encode("utf-16-le")
    assert rb.parse_index_record(struct.pack("<qqq", 1, 1, 0) + raw) is None


def test_v1_and_v2_full_records_still_parse():
    orig = SYN
    raw = orig.encode("utf-16-le")
    v1 = struct.pack("<qqq", 1, 1, 0) + raw + b"\0" * (520 - len(raw))
    assert rb.parse_index_file(v1) == orig
    assert rb.parse_index_file(_v2(orig)) == orig
