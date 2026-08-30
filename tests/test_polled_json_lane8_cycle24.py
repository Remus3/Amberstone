"""Lane 8 cycle 24 - deep audit of core/polled_json.py.

core/polled_json.py is the repo's atomic-write CONTRACT: 20 non-test modules
import it, and every other writer is told to route through it rather than
re-roll tmp+rename. Its own docstring promises readers "see either the old
content or the new, never a partial write" and that read_json_dict "always
returns a dict".

Both promises were measurably false before this slice:

  W1  read_json_dict raised UnicodeDecodeError on a file with undecodable
      bytes, against a docstring promising the default for an unreadable
      file. THREE downstream sites had already widened their own handlers to
      compensate rather than fixing the resolver (core/cost_tracker.py:490,
      coaches/_base_coach.py:502 and :539 all name it in prose).
  W2  read_json_dict shallow-copied `default`, so a nested mutable was shared
      with the caller's own default object and with every later call.
  W3  PolledJsonFile had the same shallow copy in __init__ and handed the
      shared nested mutable out of read().
  W4  An exhausted replace retry re-raised and left the scratch file on disk.
  W5  The scratch name was derived from the DESTINATION alone
      ("<dest>.tmp"), so concurrent writers to one destination opened the
      SAME scratch file - the second truncating the first mid-write. Measured
      on win32 with two threads writing data/force_scan.json-shaped payloads:
      readers saw torn, unparseable destination content.

W5 reachability is not hypothetical. data/force_scan.json has FOUR independent
writers (core/hotkeys.py:103, dashboard/_writers.py:68,
coaches/arena_coach.py:481, and tools/lcu_agent.py:1372 in its OWN PROCESS, the
RC-LCUAgent ONLOGON task) with a live reader at coaches/_base_coach.py:465;
coaching_data.json has at least THREE (app/__init__.py:253 and :272,
dashboard/_writers.py:63, and coach_integration/_coach.py:713, which still
hand-rolls its scratch name and is NOT converted - RM-261).

W2/W3 SEVERITY, stated honestly: no current production caller passes a default
containing a nested mutable - every one passes {} or a freshly-built dict - and
PolledJsonFile has ZERO production constructions (RM-264). Both are therefore
real defects in the contract with LATENT rather than live exposure. They are
fixed and guarded here because this module is the thing every new polled-JSON
site is pointed at, not because an incident was observed.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest

from core import polled_json


# ---------------------------------------------------------------------------
# Characterization - behaviour that was already correct and must stay correct.
# ---------------------------------------------------------------------------

def test_atomic_write_json_round_trips(tmp_path):
    target = tmp_path / "out.json"
    polled_json.atomic_write_json(target, {"k": 1, "nested": {"a": [1, 2]}})
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "k": 1, "nested": {"a": [1, 2]}}


def test_atomic_write_json_creates_parent_directories(tmp_path):
    target = tmp_path / "deep" / "deeper" / "out.json"
    polled_json.atomic_write_json(target, {"k": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}


def test_atomic_write_text_round_trips(tmp_path):
    target = tmp_path / "trigger.txt"
    polled_json.atomic_write_text(target, "restart")
    assert target.read_text(encoding="utf-8") == "restart"


def test_atomic_write_bytes_round_trips_exact_byte_count(tmp_path):
    target = tmp_path / "blob.bin"
    payload = b"line one\nline two\n"
    polled_json.atomic_write_bytes(target, payload)
    assert target.read_bytes() == payload


def test_read_json_dict_returns_default_when_missing(tmp_path):
    assert polled_json.read_json_dict(tmp_path / "nope.json", {"d": 1}) == {"d": 1}


def test_read_json_dict_returns_empty_dict_when_default_is_none(tmp_path):
    assert polled_json.read_json_dict(tmp_path / "nope.json") == {}


def test_read_json_dict_returns_default_on_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert polled_json.read_json_dict(p, {"d": 1}) == {"d": 1}


def test_read_json_dict_returns_default_on_non_dict_json(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert polled_json.read_json_dict(p, {"d": 1}) == {"d": 1}


def test_polled_json_file_write_read_field_and_update(tmp_path):
    pf = polled_json.PolledJsonFile(tmp_path / "pf.json", default={"mode": "client"})
    assert pf.read() == {"mode": "client"}
    pf.write({"mode": "aram"})
    assert pf.read() == {"mode": "aram"}
    assert pf.write_field("immediate", "All-In")["immediate"] == "All-In"
    assert pf.update(win_pct=42)["win_pct"] == 42
    assert pf.read() == {"mode": "aram", "immediate": "All-In", "win_pct": 42}


# ---------------------------------------------------------------------------
# W1 - the "always returns a dict" promise must hold for undecodable bytes.
# ---------------------------------------------------------------------------

def test_read_json_dict_returns_default_on_undecodable_bytes(tmp_path):
    """A non-UTF-8 polled file must yield the default, not raise.

    Pre-fix this raised UnicodeDecodeError straight through the docstring's
    "missing, unreadable, or stores something other than a dict" promise.
    """
    p = tmp_path / "bad.json"
    p.write_bytes(b'{"k": "\xff\xfe not utf8"}')
    assert polled_json.read_json_dict(p, {"d": 1}) == {"d": 1}


def test_read_json_dict_logs_a_warning_on_undecodable_bytes(tmp_path, caplog):
    p = tmp_path / "bad.json"
    p.write_bytes(b"\xff\xfe\x00")
    with caplog.at_level("WARNING", logger="rc.polled_json"):
        polled_json.read_json_dict(p, {"d": 1})
    assert any("decode" in r.message.lower() for r in caplog.records), (
        "an undecodable polled file must leave a trace, not vanish silently")


def test_polled_json_file_read_survives_undecodable_bytes(tmp_path):
    p = tmp_path / "pf.json"
    p.write_bytes(b"\xff\xfe\x00")
    pf = polled_json.PolledJsonFile(p, default={"mode": "client"})
    assert pf.read() == {"mode": "client"}


# ---------------------------------------------------------------------------
# W2 / W3 - the default must never be shared, at any depth.
# ---------------------------------------------------------------------------

def _seed(tmp_path, branch):
    """One file per fallback branch inside read_json_dict."""
    p = tmp_path / f"{branch}.json"
    if branch == "missing":
        return p
    if branch == "malformed":
        p.write_text("{not json", encoding="utf-8")
    elif branch == "non_dict":
        p.write_text("[1, 2, 3]", encoding="utf-8")
    elif branch == "undecodable":
        p.write_bytes(b"\xff\xfe\x00")
    return p


@pytest.mark.parametrize("branch", ["missing", "malformed", "non_dict", "undecodable"])
def test_read_json_dict_does_not_share_nested_default_between_calls(tmp_path, branch):
    """EVERY fallback branch must hand back a fresh deep copy.

    Parametrized because a guard that only covers the default call path is an
    untested guard - the missing-file branch is the one a naive probe reaches,
    and the corrupt-file branches are the ones that matter in production.
    """
    p = _seed(tmp_path, branch)
    default = {"log": [], "n": 0}
    first = polled_json.read_json_dict(p, default)
    first["log"].append("poison")
    second = polled_json.read_json_dict(p, default)
    assert second["log"] == [], "a later read inherited a prior caller's mutation"
    assert default["log"] == [], "the caller's own default dict was mutated"


def test_read_json_dict_does_not_mutate_the_callers_default_object(tmp_path):
    default = {"log": []}
    polled_json.read_json_dict(tmp_path / "nope.json", default)["log"].append("x")
    assert default["log"] == [], "the caller's own default dict was mutated"


def test_polled_json_file_read_does_not_share_nested_default(tmp_path):
    pf = polled_json.PolledJsonFile(tmp_path / "pf.json", default={"log": []})
    pf.read()["log"].append("poison")
    assert pf.read()["log"] == []


def test_polled_json_file_does_not_alias_the_constructor_default(tmp_path):
    caller_default = {"log": []}
    pf = polled_json.PolledJsonFile(tmp_path / "pf.json", default=caller_default)
    pf.read()["log"].append("poison")
    assert caller_default["log"] == [], (
        "the instance aliased the caller's nested default")


def test_polled_json_file_snapshots_the_constructor_default(tmp_path):
    """Construction must take a SNAPSHOT, not a live view of the caller's dict.

    This is the direction read()'s own deep copy cannot cover: the caller
    mutating its own default afterwards must not retune an already-built
    instance. Added because a mutation run proved the constructor's deep copy
    was otherwise unguarded.
    """
    caller_default = {"log": []}
    pf = polled_json.PolledJsonFile(tmp_path / "pf.json", default=caller_default)
    caller_default["log"].append("added after construction")
    assert pf.read() == {"log": []}


# ---------------------------------------------------------------------------
# W4 - a failed write must not leave its scratch file behind.
# ---------------------------------------------------------------------------

def _deny_replace(monkeypatch):
    def always_denied(src, dst):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda s: None)


def _scratch_files(d):
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


@pytest.mark.parametrize("writer,payload", [
    ("atomic_write_json", {"k": 1}),
    ("atomic_write_text", "restart"),
    ("atomic_write_bytes", b"blob"),
])
def test_exhausted_retry_leaves_no_scratch_file(tmp_path, monkeypatch, writer, payload):
    _deny_replace(monkeypatch)
    with pytest.raises(PermissionError):
        getattr(polled_json, writer)(tmp_path / "out.json", payload)
    assert _scratch_files(tmp_path) == [], "an exhausted retry orphaned its scratch file"


def test_successful_write_leaves_no_scratch_file(tmp_path):
    polled_json.atomic_write_json(tmp_path / "out.json", {"k": 1})
    assert _scratch_files(tmp_path) == []


def test_scratch_file_is_removed_when_the_write_itself_fails(tmp_path, monkeypatch):
    """A mid-write failure must clean up too, not just a failed rename."""
    real_write_bytes = polled_json.Path.write_bytes

    def boom(self, data):
        real_write_bytes(self, data[:2])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(polled_json.Path, "write_bytes", boom)
    with pytest.raises(OSError):
        polled_json.atomic_write_json(tmp_path / "out.json", {"k": 1})
    assert _scratch_files(tmp_path) == []


# ---------------------------------------------------------------------------
# W5 - concurrent writers to one destination must not share a scratch file.
# ---------------------------------------------------------------------------

def _capture_scratch_paths(monkeypatch):
    seen = []
    real = polled_json._replace_with_retry

    def spy(src, dst):
        seen.append(str(src))
        return real(src, dst)

    monkeypatch.setattr(polled_json, "_replace_with_retry", spy)
    return seen


def test_two_writes_to_one_destination_use_distinct_scratch_paths(tmp_path, monkeypatch):
    """The structural guard for W5.

    A scratch name derived from the destination alone is the defect: two
    writers open the same file and the second truncates the first mid-write.
    """
    seen = _capture_scratch_paths(monkeypatch)
    target = tmp_path / "shared.json"
    polled_json.atomic_write_json(target, {"who": "a"})
    polled_json.atomic_write_json(target, {"who": "b"})
    assert len(seen) == 2
    assert seen[0] != seen[1], (
        "both writers used one scratch path - concurrent writers would collide")


def test_scratch_path_is_distinct_across_every_public_writer(tmp_path, monkeypatch):
    seen = _capture_scratch_paths(monkeypatch)
    target = tmp_path / "shared.json"
    polled_json.atomic_write_json(target, {"k": 1})
    polled_json.atomic_write_text(target, "text")
    polled_json.atomic_write_bytes(target, b"bytes")
    assert len(seen) == len(set(seen)) == 3


def test_scratch_file_stays_in_the_destination_directory(tmp_path, monkeypatch):
    """Rename is only atomic within one filesystem, so the scratch file must
    be a sibling of the destination, never in a global temp dir."""
    seen = _capture_scratch_paths(monkeypatch)
    target = tmp_path / "sub" / "shared.json"
    polled_json.atomic_write_json(target, {"k": 1})
    assert polled_json.Path(seen[0]).parent == target.parent


def test_concurrent_writers_never_expose_torn_content(tmp_path):
    """The behavioural companion to the structural guard above.

    Pre-fix this reliably produced JSONDecodeError reads: writer A was still
    filling the shared scratch file when writer B renamed it into place.
    """
    target = tmp_path / "shared.json"
    torn: list[str] = []
    barrier = threading.Barrier(2)

    def writer(tag, pad):
        barrier.wait()
        for _ in range(80):
            try:
                polled_json.atomic_write_json(target, {"who": tag, "pad": "x" * pad})
            except (PermissionError, FileNotFoundError):
                pass
            try:
                body = target.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                json.loads(body)
            except json.JSONDecodeError:
                torn.append(body[:40])

    threads = [threading.Thread(target=writer, args=("A", 20000)),
               threading.Thread(target=writer, args=("B", 20))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert torn == [], f"readers saw partially-written content: {torn[:3]}"


def test_concurrent_writers_leave_no_scratch_litter(tmp_path):
    """Per-writer scratch names must still be cleaned up - a unique name that
    is never removed trades one defect for unbounded litter."""
    target = tmp_path / "shared.json"
    barrier = threading.Barrier(3)

    def writer(tag):
        barrier.wait()
        for _ in range(40):
            try:
                polled_json.atomic_write_json(target, {"who": tag})
            except (PermissionError, FileNotFoundError):
                pass

    threads = [threading.Thread(target=writer, args=(t,)) for t in "ABC"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert _scratch_files(tmp_path) == []


_CHILD_WRITER = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from core import polled_json
target, tag, pad, rounds, go = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
# Start barrier: interpreter startup is ~200 ms and dwarfs the write window,
# so without this the children barely overlap and the contention never happens.
while not os.path.exists(go):
    time.sleep(0.002)
for _ in range(rounds):
    try:
        polled_json.atomic_write_json(target, {"who": tag, "pad": "x" * pad})
    except (PermissionError, FileNotFoundError):
        pass
"""

_CHILD_SCRATCH_NAME = r"""
import sys
sys.path.insert(0, sys.argv[1])
from core import polled_json
from pathlib import Path
seen = []
polled_json._replace_with_retry = lambda src, dst: seen.append(str(src))
polled_json.atomic_write_json(Path(sys.argv[2]), {"k": 1})
print(Path(seen[0]).name)
"""


def _repo_root():
    return str(pathlib.Path(__file__).resolve().parent.parent)


def test_a_separate_process_picks_a_different_scratch_name(tmp_path, monkeypatch):
    """RM-254 acceptance: the CROSS-PROCESS case, which is the one no
    in-process lock can serialize and the reason the pid is in the name.

    Deterministic by construction - it compares the scratch name a child
    process chooses against the one this process chooses for the same
    destination, rather than racing them.
    """
    target = tmp_path / "shared.json"
    mine = _capture_scratch_paths(monkeypatch)
    polled_json.atomic_write_json(target, {"k": 1})
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRATCH_NAME, _repo_root(), str(target)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    theirs = proc.stdout.strip()
    assert theirs, proc.stderr
    assert theirs != polled_json.Path(mine[0]).name, (
        "two processes chose the same scratch file for one destination")


def test_two_processes_writing_one_file_never_tear_it(tmp_path):
    """RM-254 acceptance: the behavioural two-PROCESS contention check.

    Pre-fix, both children opened the same "<dest>.tmp"; one truncated it
    while the other was mid-write, and the rename published the fragment.

    HONEST STATUS: this is a companion SMOKE test, not the guard. Measured
    against a deliberate revert to the shared scratch name it went RED on 1 of
    2 attempts - so it does detect the real defect cross-process, but only
    about half the time, and a guard you cannot trust to fail is not a guard.
    It is safe in CI because it asserts an ABSENCE that the fix makes
    structurally impossible, so it cannot fail spuriously. The reliable guards
    for W5 are test_a_separate_process_picks_a_different_scratch_name and
    test_two_writes_to_one_destination_use_distinct_scratch_paths, both of
    which go red deterministically.
    """
    target = tmp_path / "shared.json"
    go = tmp_path / "go"
    root = _repo_root()
    children = [
        subprocess.Popen([sys.executable, "-c", _CHILD_WRITER, root,
                          str(target), "A", "120000", "120", str(go)]),
        subprocess.Popen([sys.executable, "-c", _CHILD_WRITER, root,
                          str(target), "B", "20", "120", str(go)]),
    ]
    torn = []
    try:
        go.write_text("go", encoding="utf-8")
        deadline = time.time() + 120
        while any(c.poll() is None for c in children) and time.time() < deadline:
            try:
                body = target.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                json.loads(body)
            except json.JSONDecodeError:
                torn.append(body[:60])
    finally:
        for c in children:
            try:
                c.wait(timeout=30)
            except subprocess.TimeoutExpired:
                c.kill()
    assert torn == [], f"a reader saw a partially-written file: {torn[:3]}"
    assert _scratch_files(tmp_path) == [], "child processes left scratch litter"


def test_scratch_name_carries_the_writing_process_id(tmp_path, monkeypatch):
    """Cross-process writers are the case an in-process lock cannot help, so
    the pid must be part of what makes the name unique."""
    seen = _capture_scratch_paths(monkeypatch)
    polled_json.atomic_write_json(tmp_path / "shared.json", {"k": 1})
    assert str(os.getpid()) in polled_json.Path(seen[0]).name
