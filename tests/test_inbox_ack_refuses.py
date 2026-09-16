"""The acknowledge path must REFUSE when it cannot see the inbox.

MEASURED DEFECT (2026-09-16). `mark_inbox_seen()` computed

    names = sorted(_inbox_entries(inbox)) if inbox.is_dir() else []

and then wrote the seen store UNCONDITIONALLY. With `moon_sync_inbox/` absent
the ack therefore wrote an EMPTY seen set over the live watermark and printed a
success line. On an isolated copy of the real store the file went from 22503
bytes holding 198 acknowledgement keys to 18 bytes holding `{"seen": []}`, exit
code 0, stdout `recorded 0 inbox note(s) as seen`.

REACHABLE, NOT THEORETICAL. `moon_sync_inbox/` is GITIGNORED: absent in a fresh
clone, absent in every worktree, and removable by `git clean -xdf`. RC keeps six
long-lived lane worktrees plus agent worktrees.

THE ASYMMETRY BEING PINNED. RC's WATCHER (`_inbox_section`) treats an absent
inbox as a RECORDED FAULT and emits an `UNMEASURED` line for it. The ACKNOWLEDGE
path treated the IDENTICAL condition as "zero notes". One condition, two
readings, and the destructive one was the silent one. Arm E pins the agreement.

Every arm uses a temporary root and its own store path (the shipped idiom from
tests/test_inbox_watcher.py: monkeypatch `rc_facts._ROOT`). The real inbox and
the real store at ops/runtime/sync_inbox_seen.json are never touched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import rc_facts  # noqa: E402

REFUSAL_EXIT = 3

_PRELOADED = json.dumps(
    {"seen": ["a.md [1111aaaa2222]", "from-XX-verbatim/ [3 files, content beef]"]},
    indent=2,
)


def _store(root: Path) -> Path:
    return root / "ops" / "runtime" / "sync_inbox_seen.json"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_root(tmp_path: Path, monkeypatch, *, with_inbox: bool) -> Path:
    """A fake repo root carrying a POPULATED seen store, the state the defect
    destroys. Returns the root; the store is pre-loaded so an erasure is a
    visible byte change rather than an absence that looks the same either way.
    """
    root = tmp_path / "repo"
    (root / "ops" / "runtime").mkdir(parents=True)
    _store(root).write_text(_PRELOADED, encoding="utf-8")
    if with_inbox:
        (root / "moon_sync_inbox").mkdir()
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    return root


def _says_success(out: str) -> bool:
    """A human reads `recorded N inbox note(s) as seen` as a completed act."""
    return "recorded" in out.lower() and "as seen" in out.lower()


# --------------------------------------------------------------------------
# A. ABSENT inbox.
# --------------------------------------------------------------------------
def test_absent_inbox_refuses_and_leaves_the_store_byte_identical(
    tmp_path, monkeypatch, capsys
):
    root = _make_root(tmp_path, monkeypatch, with_inbox=False)
    before = _sha(_store(root))

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert _sha(_store(root)) == before, (
        "the acknowledge path WROTE the seen store with moon_sync_inbox/ "
        "absent - this is the live data-loss defect: the watermark the whole "
        "watcher exists to keep was replaced with an empty set"
    )
    assert rc == REFUSAL_EXIT, f"expected the refusal exit {REFUSAL_EXIT}, got {rc}"
    assert not _says_success(out), (
        "stdout claims success on a path that recorded nothing: " + out
    )
    assert "REFUSED" in out, "the refusal must be legible as a refusal: " + out


# --------------------------------------------------------------------------
# B. UNLISTABLE inbox. The fault is injected IN PROCESS - no real ACL is
#    touched - and only for this one directory, so an unrelated iterdir
#    elsewhere in the call cannot be what the arm is really measuring.
# --------------------------------------------------------------------------
def test_unlistable_inbox_refuses_and_leaves_the_store_byte_identical(
    tmp_path, monkeypatch, capsys
):
    root = _make_root(tmp_path, monkeypatch, with_inbox=True)
    inbox = root / "moon_sync_inbox"
    before = _sha(_store(root))

    real_iterdir = Path.iterdir

    def deny(self):
        if Path(self) == inbox:
            raise PermissionError(13, "Access is denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", deny)

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert _sha(_store(root)) == before, (
        "the acknowledge path WROTE the seen store while the inbox was "
        "unlistable - an inbox it could not read is not an empty inbox"
    )
    assert rc == REFUSAL_EXIT, f"expected the refusal exit {REFUSAL_EXIT}, got {rc}"
    assert not _says_success(out), (
        "stdout claims success on a path that recorded nothing: " + out
    )
    assert "REFUSED" in out, "the refusal must be legible as a refusal: " + out


# --------------------------------------------------------------------------
# C. THE MUTATION ARM. Today the unlistable case is protected ONLY by the fact
#    that `_inbox_entries` lets the PermissionError propagate out of
#    `mark_inbox_seen` before the write. That is luck, not a guard: a later
#    reader who wraps `iterdir()` in a try/except returning an empty set - the
#    shape a sibling tree actually has - silently reintroduces the erasure, and
#    that mutant survives every pre-existing arm at exit 0.
#
#    This arm applies that exact mutation to `_inbox_entries` and demands the
#    ack still refuse. It therefore fails for a fix that merely relies on the
#    exception escaping, and passes only for a fix that probes listability
#    EXPLICITLY inside the acknowledge path.
# --------------------------------------------------------------------------
def test_ack_still_refuses_when_inbox_entries_swallows_the_listing_error(
    tmp_path, monkeypatch, capsys
):
    root = _make_root(tmp_path, monkeypatch, with_inbox=True)
    inbox = root / "moon_sync_inbox"
    before = _sha(_store(root))

    real_iterdir = Path.iterdir

    def deny(self):
        if Path(self) == inbox:
            raise PermissionError(13, "Access is denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", deny)

    # The mutant: the swallow-and-return-empty shape.
    def swallowing_entries(p: Path) -> set[str]:
        try:
            return {q.name for q in p.iterdir()}
        except OSError:
            return set()

    monkeypatch.setattr(rc_facts, "_inbox_entries", swallowing_entries)

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert _sha(_store(root)) == before, (
        "an unlistable inbox erased the seen store once the listing error was "
        "swallowed - the refusal is not explicit, it is an accident of where "
        "the exception happens to escape"
    )
    assert rc == REFUSAL_EXIT, f"expected the refusal exit {REFUSAL_EXIT}, got {rc}"
    assert not _says_success(out), out


# --------------------------------------------------------------------------
# C2. ONE PROBE, NOT TWO COPIES. The acknowledge path corroborates listability
#     through the SAME `_probe_inbox_listable` the watcher and the poller call,
#     so a hardening of that helper reaches all three readers. A private inline
#     copy here would pass every behaviour arm above and silently miss it.
# --------------------------------------------------------------------------
def test_ack_path_probes_through_the_shared_helper(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch, with_inbox=True)
    (root / "moon_sync_inbox" / "note.md").write_text("hello", encoding="utf-8")

    calls: list[Path] = []
    real_probe = rc_facts._probe_inbox_listable

    def spy(inbox: Path) -> None:
        calls.append(inbox)
        real_probe(inbox)

    monkeypatch.setattr(rc_facts, "_probe_inbox_listable", spy)

    assert rc_facts.mark_inbox_seen() == 0
    capsys.readouterr()
    assert calls == [root / "moon_sync_inbox"], calls


# --------------------------------------------------------------------------
# D. NEGATIVE CONTROL. Mandatory: without it, arms A to C all pass on a
#    function that refuses unconditionally.
# --------------------------------------------------------------------------
def test_populated_inbox_still_records_normally(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch, with_inbox=True)
    (root / "moon_sync_inbox" / "note.md").write_text("hello", encoding="utf-8")
    before = _sha(_store(root))

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert rc == 0, f"a normal acknowledge must still exit 0, got {rc}"
    assert _says_success(out), "a real acknowledge must still report success: " + out
    assert _sha(_store(root)) != before, "the store was not updated at all"

    seen = json.loads(_store(root).read_text(encoding="utf-8"))["seen"]
    assert len(seen) == 1 and seen[0].startswith("note.md ["), seen


def test_populated_inbox_ack_is_idempotent(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch, with_inbox=True)
    (root / "moon_sync_inbox" / "note.md").write_text("hello", encoding="utf-8")

    assert rc_facts.mark_inbox_seen() == 0
    once = _sha(_store(root))
    assert rc_facts.mark_inbox_seen() == 0
    capsys.readouterr()
    assert _sha(_store(root)) == once


# --------------------------------------------------------------------------
# E. The asymmetry itself. The watcher and the acknowledge path must AGREE
#    that an absent inbox is a fault. Pinned so it cannot silently reopen.
# --------------------------------------------------------------------------
def test_watcher_and_ack_agree_an_absent_inbox_is_a_fault(
    tmp_path, monkeypatch, capsys
):
    root = _make_root(tmp_path, monkeypatch, with_inbox=False)

    lines, anomalies, keys = rc_facts._inbox_section(root, None, subtract=False)
    watcher_calls_it_a_fault = any("UNMEASURED" in ln for ln in lines + anomalies)
    assert watcher_calls_it_a_fault, (lines, anomalies, keys)

    before = _sha(_store(root))
    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out
    ack_calls_it_a_fault = rc != 0 and _sha(_store(root)) == before

    assert ack_calls_it_a_fault == watcher_calls_it_a_fault, (
        "the watcher reports an absent moon_sync_inbox/ as UNMEASURED while "
        "the acknowledge path reads the SAME condition as zero notes and "
        "overwrites the watermark. One condition must not have two readings, "
        "and the destructive reading must never be the silent one. "
        f"ack exit={rc} stdout={out!r}"
    )


@pytest.mark.parametrize("with_inbox", [True, False])
def test_the_real_store_is_never_touched_by_this_module(with_inbox, tmp_path, monkeypatch):
    """Belt and braces: `_ROOT` is redirected, so nothing here can address the
    live ops/runtime/sync_inbox_seen.json even if an arm above regressed."""
    root = _make_root(tmp_path, monkeypatch, with_inbox=with_inbox)
    assert rc_facts._ROOT == root
    assert _store(root) != Path("C:/Riot Commander/ops/runtime/sync_inbox_seen.json")
