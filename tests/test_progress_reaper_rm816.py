"""RM-816 - the RM-785 residual: the progress reaper's loss window inside the
replace itself (tools/progress_watch.py reap(), mark-failed path).

RM-785 (a) moved the compare-and-swap to immediately before every replace
attempt, but a compare followed by os.replace is still two steps: a writer
whose item-12 write lands after the last compare and before the reaper's
replace is overwritten by the reaper's "failed" row (measured s128 in a free
race: 5-6 losses in 400). A lock shared with the writers is not available -
the kit writer (fleet_headless.write_progress) takes none and is kit-owned.

The fix makes the reaper's own commit create-only instead:
  1. capture: the classified file is MOVED aside to a reaper-private name
     (atomic; from here no writer write can be overwritten, a writer that
     comes back simply creates the target again);
  2. verify the captured bytes AND (mtime, size) against the classification
     (the private name has no other writer, so this compare cannot race);
     a change means a writer landed before the capture: put it back;
  3. commit the failed row with a NO-REPLACE move; a writer that came back
     after the capture already owns the target, the move fails, writer wins.

So every interleaving leaves the writer's bytes on disk. The cost is a short
window in which the target does not exist (between 1 and 3); a reader sees no
file, and a kit writer that re-reads its own row then re-stamps "started".
A pass that died inside that window leaves its aside behind: the next applying
pass moves it back when the target is still missing.

The recycle path keeps its documented window (immediately-before check, then
the recycle call): a write that lands inside the call goes to the Recycle Bin
(FOF_ALLOWUNDO, restorable), so it is recoverable, not lost.

Every test runs on tmp_path with a fake bin and a fake owner probe.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rc_tools_progress_watch_rm816", _ROOT / "tools" / "progress_watch.py")
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

NOW = 1_800_000_000.0
DAY = 86400.0
OWNER = {"pid": 4242, "start": 1.0}


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _plant(d: Path, stem: str, *, status="running", age_s=1500.0, eta_s=600) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.json"
    doc = {"task": stem, "pct": 40, "step": "planted", "eta_s": eta_s,
           "status": status, "updated": _iso_utc(NOW - age_s), "owner": OWNER}
    p.write_text(json.dumps(doc), encoding="ascii", newline="\n")
    os.utime(p, (NOW - age_s, NOW - age_s))
    return p


def _writer_doc(stem: str, pct: int = 90) -> bytes:
    return json.dumps({"task": stem, "pct": pct, "step": "writer is back",
                       "eta_s": 600, "status": "running",
                       "updated": _iso_utc(NOW), "owner": OWNER}).encode("ascii")


def _kit_like_write(p: Path, data: bytes, tag: str = "w") -> None:
    """The kit writer's shape: whole-file tmp + os.replace, no read of the
    target needed (a fresh row), PermissionError retried like a polled file."""
    tmp = p.with_name(f"{p.name}.{tag}.writer")
    tmp.write_bytes(data)
    for _ in range(200):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.001)
    raise AssertionError("writer could not land its write")


class Bin:
    def __init__(self, tmp: Path):
        self.calls = []
        self.dest = tmp / "fakebin"

    def __call__(self, path):
        self.calls.append(Path(path).name)
        self.dest.mkdir(exist_ok=True)
        Path(path).replace(self.dest / Path(path).name)
        return SimpleNamespace(ok=True, nuked=False, detail="landed (fake)")


class Alive:
    def __init__(self, answer=None, hook=None):
        self.answer, self.hook = answer, hook

    def __call__(self, owner):
        if self.hook:
            self.hook()
        return self.answer


MOVES = pytest.mark.parametrize("link_move", [False, True],
                                ids=["rename-move", "posix-link-move"])


def _use_move(monkeypatch, link_move: bool) -> None:
    """Select the commit move for one test. The rename move is create-only
    only where os.rename refuses an existing target (Windows), so it runs
    only where the module itself picks it; on POSIX os.rename REPLACES, the
    module uses the link move, and a forced rename move is a path production
    never takes (RM-885: CI on Linux reddened on exactly that). The link move
    runs everywhere (NTFS has hard links too). Read before the monkeypatch."""
    if not link_move and pw._LINK_MOVE:
        pytest.skip("rename-move is the production move only where os.rename "
                    "refuses an existing target (Windows)")
    monkeypatch.setattr(pw, "_LINK_MOVE", link_move)


@pytest.fixture
def d(tmp_path):
    return tmp_path / "ops" / "loop" / "control" / "progress"


@pytest.fixture(autouse=True)
def _no_live_steer(monkeypatch):
    attempts = []
    monkeypatch.setattr(pw, "steer_send", lambda text, key: attempts.append(key))
    yield
    assert attempts == []


def _reap(tmp_path, d, *, alive=None, recycle=None):
    return pw.reap(progress_dir=d, root=tmp_path, now=NOW, apply=True,
                   recycle=recycle if recycle is not None else Bin(tmp_path),
                   alive=alive if alive is not None else Alive(False))


def _doc(p: Path) -> dict:
    return json.loads(p.read_text(encoding="ascii"))


def _leftovers(d: Path) -> list:
    return sorted(q.name for q in d.iterdir() if not q.name.endswith(".json"))


# ------------------------------------------- deterministic: the commit window

def test_a_write_landing_after_every_passing_compare_is_never_overwritten(tmp_path, d, monkeypatch):
    """The RM-816 window: the writer lands right AFTER a compare said
    'unchanged' - on the old code that was the gap before os.replace, so the
    reaper's failed row overwrote it. Injected after every passing compare."""
    p = _plant(d, "gap")
    real = pw._unchanged
    landed = []

    def compare_then_writer(path, raw, sig):
        ok = real(path, raw, sig)
        if ok:
            _kit_like_write(p, _writer_doc("gap", pct=90 + len(landed)), tag=str(len(landed)))
            landed.append(Path(path).name)
        return ok

    monkeypatch.setattr(pw, "_unchanged", compare_then_writer)
    rep = _reap(tmp_path, d)
    assert landed, "the injection never fired: the test proves nothing"
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    doc = _doc(p)
    assert doc["status"] == "running" and doc["pct"] == 90 + len(landed) - 1
    assert _leftovers(d) == []


def test_a_writer_back_after_the_capture_owns_the_target(tmp_path, d, monkeypatch):
    """A writer that comes back after the reaper moved the row aside creates
    the target again; the reaper's create-only commit then loses to it."""
    p = _plant(d, "after")
    real_move = pw._move
    calls = []

    def move_with_writer_before_commit(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        if Path(dst) == p and Path(src).name.endswith(".tmp"):
            _kit_like_write(p, _writer_doc("after", pct=77))
        return real_move(src, dst)

    monkeypatch.setattr(pw, "_move", move_with_writer_before_commit)
    rep = _reap(tmp_path, d)
    assert rep["marked"] == []
    assert any("changed" in h["why"] for h in rep["held"])
    assert _doc(p)["pct"] == 77 and _doc(p)["status"] == "running"
    assert [c[1] for c in calls][-1] == "after.json"      # the commit was tried
    assert _leftovers(d) == []


def test_a_writer_back_before_the_capture_is_put_back(tmp_path, d, monkeypatch):
    """The capture took the writer's new bytes: the private compare sees the
    change and the row goes back under its own name, untouched."""
    p = _plant(d, "before")
    real_capture = pw._capture

    def writer_then_capture(src, dst):
        _kit_like_write(p, _writer_doc("before", pct=66))
        return real_capture(src, dst)

    monkeypatch.setattr(pw, "_capture", writer_then_capture)
    rep = _reap(tmp_path, d)
    assert rep["marked"] == []
    assert _doc(p)["pct"] == 66 and _doc(p)["status"] == "running"
    assert _leftovers(d) == []


@MOVES
def test_the_public_name_is_never_moved_by_link_and_unlink(tmp_path, d, monkeypatch, link_move):
    """The verifier's POSIX find: a capture by link + unlink unlinks BY NAME,
    so a writer's replace landing between the two is destroyed. The public
    name must leave only by one atomic rename (_capture); the create-only
    _move is for the reaper's private names (tmp, aside)."""
    _use_move(monkeypatch, link_move)
    p = _plant(d, "pub")
    real_move, real_capture = pw._move, pw._capture
    moved, captured = [], []

    def spy_move(src, dst):
        moved.append(Path(src))
        return real_move(src, dst)

    def spy_capture(src, dst):
        captured.append(Path(src))
        return real_capture(src, dst)

    monkeypatch.setattr(pw, "_move", spy_move)
    monkeypatch.setattr(pw, "_capture", spy_capture)
    rep = _reap(tmp_path, d)
    assert rep["marked"] == ["pub"]
    assert captured == [p]
    assert moved and p not in moved
    assert _leftovers(d) == []


@MOVES
def test_the_commit_move_never_replaces_an_existing_target(tmp_path, monkeypatch, link_move):
    _use_move(monkeypatch, link_move)
    src, dst = tmp_path / "a.tmp", tmp_path / "b.json"
    src.write_bytes(b"new")
    dst.write_bytes(b"writer")
    with pytest.raises(FileExistsError):
        pw._move(src, dst)
    assert dst.read_bytes() == b"writer" and src.read_bytes() == b"new"
    dst.unlink()
    pw._move(src, dst)
    assert dst.read_bytes() == b"new" and not src.exists()


def test_an_unchanged_row_is_marked_and_leaves_nothing_behind(tmp_path, d):
    p = _plant(d, "plain")
    rep = _reap(tmp_path, d)
    assert rep["marked"] == ["plain"]
    doc = _doc(p)
    assert doc["status"] == "failed" and doc["pct"] == 40 and "reaped" in doc["reason"]
    assert _leftovers(d) == []


def test_an_aside_left_by_a_dead_pass_is_moved_back(tmp_path, d):
    """A pass killed between the capture and the commit leaves the row under
    its private name; the next applying pass restores it, then judges it."""
    p = _plant(d, "crashed", age_s=10)           # young: not reapable itself
    aside = p.with_name(f"{p.name}.999999.reap")
    p.replace(aside)
    rep = _reap(tmp_path, d)
    assert p.exists() and not aside.exists()
    assert _doc(p)["status"] == "running"
    assert rep["marked"] == []
    assert _leftovers(d) == []


def test_an_aside_whose_target_was_rewritten_is_left_alone(tmp_path, d):
    """The target exists again (a writer came back): the aside is an older
    copy; it is reported, never moved over the writer's row."""
    p = _plant(d, "both", age_s=10)
    aside = p.with_name(f"{p.name}.999999.reap")
    aside.write_bytes(b"older")
    rep = _reap(tmp_path, d)
    assert aside.read_bytes() == b"older"
    assert _doc(p)["status"] == "running"
    assert any(h["file"] == aside.name for h in rep["held"])


def test_a_plan_only_pass_never_moves_an_aside(tmp_path, d):
    p = _plant(d, "plan", age_s=10)
    aside = p.with_name(f"{p.name}.999999.reap")
    p.replace(aside)
    pw.reap(progress_dir=d, root=tmp_path, now=NOW, apply=False,
            recycle=Bin(tmp_path), alive=Alive(False))
    assert aside.exists() and not p.exists()


# ------------------------------------------------- measured: a free race

TRIALS = 300


@MOVES
def test_a_free_race_loses_zero_writer_writes(tmp_path, monkeypatch, link_move):
    """Measured, not argued: the writer is released at the reaper's owner
    probe (after its classifying read) and lands at a random point across the
    whole mark path. Every write is newer than what the reaper read, so the
    only correct end state is the writer's row. Base code: a non-zero count
    (s128: 5-6 of 400; this test: 53 of 300). Fixed code: 0 of TRIALS, on
    the native move and on the POSIX link move (run on this filesystem)."""
    _use_move(monkeypatch, link_move)
    rng = random.Random(816)
    losses = []
    for i in range(TRIALS):
        d = tmp_path / "ops" / "loop" / "control" / "progress" / f"t{i}"
        p = _plant(d, f"race{i}")
        go = threading.Event()
        delay = rng.uniform(0.0, 0.0015)

        def writer(p=p, i=i, go=go, delay=delay):
            go.wait(5)
            end = time.perf_counter() + delay
            while time.perf_counter() < end:
                pass
            _kit_like_write(p, _writer_doc(f"race{i}", pct=90))

        t = threading.Thread(target=writer)
        t.start()
        pw.reap(progress_dir=d, root=tmp_path, now=NOW, apply=True,
                recycle=Bin(tmp_path), alive=Alive(False, hook=go.set))
        t.join(10)
        try:
            doc = _doc(p)
        except (OSError, ValueError):
            losses.append((i, "missing or torn"))
            continue
        if doc.get("pct") != 90 or doc.get("status") != "running":
            losses.append((i, doc.get("status")))
        stray = [n for n in _leftovers(d) if not n.endswith(".writer")]
        if stray:
            losses.append((i, f"left {stray}"))
    assert losses == [], f"{len(losses)} of {TRIALS} writer writes lost: {losses[:5]}"


# ------------------------------------------- the recycle path is unchanged

def test_the_recycle_path_still_checks_immediately_before_the_call(tmp_path, d, monkeypatch):
    p = _plant(d, "olddone", status="done", age_s=9 * DAY)
    raw = p.read_bytes()
    real_parse = pw.parse_updated

    def parse_then_touch(value):
        os.utime(p, (NOW - 1, NOW - 1))
        return real_parse(value)

    monkeypatch.setattr(pw, "parse_updated", parse_then_touch)
    bin_ = Bin(tmp_path)
    rep = _reap(tmp_path, d, recycle=bin_)
    assert bin_.calls == [] and rep["recycled"] == []
    assert p.read_bytes() == raw
