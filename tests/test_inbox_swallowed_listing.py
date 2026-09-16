"""An inbox that cannot be LISTED is not an EMPTY inbox - watcher and poller.

THE GAP BEING PINNED (2026-09-16). `tools/rc_facts.py` `_inbox_entries` calls
`inbox.iterdir()` with no OSError handling. Two readers treat its result as the
whole truth about what is in the inbox:

  * the WATCHER (`_inbox_section`) subtracts it from the seen store to find
    WITHDRAWN entries;
  * the POLLER (`tools/moon_sync_poller.py` `scan_fleet`) subtracts it from its
    own seen set to find withdrawals, then SAVES it as the new watermark.

Both were safe only because `iterdir()` happens to RAISE on an unlistable
directory, so the exception escaped before the withdrawal count and before the
save. The pre-existing tests (`tests/test_inbox_reported_record.py` injects a
raising `_inbox_entries`, `tests/test_moon_sync_poller.py` likewise) exercise
that RAISED shape only. A later reader who wraps the listing in a try/except
returning an empty set - the shape a sibling tree actually has - turns an
unreadable inbox into "every note was withdrawn": the watcher prints one fake
WITHDRAWN line per acknowledged note, and the poller erases the repo's entry in
its watermark.

The acknowledge path already closed this for itself with an explicit
listability probe (`tests/test_inbox_ack_refuses.py` arm C). These arms apply
the SAME swallowing mutant to the watcher and the poller and demand that each
refuse too, independent of where the exception happens to escape.

Every arm runs under tmp_path. The watcher arms redirect `rc_facts._ROOT`; the
poller arms redirect every state path (the `state` fixture shape from
tests/test_moon_sync_poller.py). The real inbox, the real seen store and the
poller's real watermark are never addressed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import moon_sync_poller as P  # noqa: E402
from tools import rc_facts  # noqa: E402

_SEEN_KEYS = [f"note{i}.md [{i:012d}]" for i in range(5)]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _deny_listing(monkeypatch, inbox: Path) -> None:
    """Make ONE directory unlistable, in process. No real ACL is touched."""
    real_iterdir = Path.iterdir

    def deny(self):
        if Path(self) == inbox:
            raise PermissionError(13, "Access is denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", deny)


def _deny_scandir_and_swallow_iterdir(monkeypatch, inbox: Path) -> None:
    """The fault at the OS-listing primitive, hidden by a swallow ONE LAYER UP.

    Measured on Python 3.14: `Path.iterdir` IS `os.scandir` plus an eager list,
    so denying `os.scandir` for the inbox makes the real `iterdir` raise, and
    the wrapper then reads that raise as an empty directory. Every reader that
    lists through `Path.iterdir` - the UNMUTATED `_inbox_entries` included - now
    sees an empty inbox. Only a probe that calls `os.scandir` itself can tell.
    """
    real_scandir = os.scandir
    real_iterdir = Path.iterdir

    def deny(path=".", *a, **kw):
        if Path(path) == inbox:
            raise PermissionError(13, "Access is denied")
        return real_scandir(path, *a, **kw)

    def swallow(self):
        try:
            return real_iterdir(self)
        except OSError:
            return iter(())

    monkeypatch.setattr(os, "scandir", deny)
    monkeypatch.setattr(Path, "iterdir", swallow)


def _swallowing_entries(p: Path) -> set[str]:
    """The mutant: list the inbox, and read ANY listing error as empty."""
    try:
        return {f"{q.name} [000000000000]" for q in p.iterdir()}
    except OSError:
        return set()


# ------------------------------------------------------------------ watcher


def _watcher_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    (root / "ops" / "runtime").mkdir(parents=True)
    (root / "moon_sync_inbox").mkdir()
    (root / "ops" / "runtime" / "sync_inbox_seen.json").write_text(
        json.dumps({"seen": _SEEN_KEYS}, indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    monkeypatch.setattr(rc_facts, "_T0", time.monotonic())
    return root


@pytest.mark.parametrize("session", [None, "s"])
def test_watcher_does_not_report_withdrawals_when_listing_is_swallowed(
    tmp_path, monkeypatch, session
):
    root = _watcher_root(tmp_path, monkeypatch)
    _deny_listing(monkeypatch, root / "moon_sync_inbox")
    monkeypatch.setattr(rc_facts, "_inbox_entries", _swallowing_entries)

    lines, anomalies, keys = rc_facts._inbox_section(root, session, subtract=False)
    text = "\n".join(lines + anomalies)

    assert "WITHDRAWN" not in text, (
        "an inbox RC could not list was read as empty, so every acknowledged "
        "note was reported WITHDRAWN by a sibling:\n" + text
    )
    assert not any(k.startswith("WITHDRAWN:") for k in keys), keys
    assert any("UNMEASURED" in ln for ln in lines), lines
    assert any("UNMEASURED" in ln for ln in anomalies), anomalies
    assert keys == set(), "a blind state must not be recorded as shown"
    assert not (root / "ops" / "runtime" / "sync_inbox_report.txt").exists(), (
        "the report file was written with fake withdrawals"
    )


def test_watcher_unlistable_line_names_the_condition(tmp_path, monkeypatch):
    """Unlistable is its own reading, distinct from ABSENT."""
    root = _watcher_root(tmp_path, monkeypatch)
    _deny_listing(monkeypatch, root / "moon_sync_inbox")
    monkeypatch.setattr(rc_facts, "_inbox_entries", _swallowing_entries)

    lines, _anomalies, _keys = rc_facts._inbox_section(root, None, subtract=False)
    assert lines == [
        "## Cross-repo inbox - UNMEASURED: moon_sync_inbox/ unlistable (PermissionError)"
    ], lines


@pytest.mark.parametrize("session", [None, "s"])
def test_watcher_refuses_when_the_swallow_is_in_path_iterdir_itself(
    tmp_path, monkeypatch, session
):
    """The shared-seam arm. `_inbox_entries` is NOT mutated here: the swallow
    sits in `Path.iterdir`, which both it and a Path.iterdir-only probe call, so
    a probe built on that one primitive is defeated together with the listing."""
    root = _watcher_root(tmp_path, monkeypatch)
    _deny_scandir_and_swallow_iterdir(monkeypatch, root / "moon_sync_inbox")

    lines, anomalies, keys = rc_facts._inbox_section(root, session, subtract=False)
    text = "\n".join(lines + anomalies)

    assert "WITHDRAWN" not in text, text
    assert lines == [
        "## Cross-repo inbox - UNMEASURED: moon_sync_inbox/ unlistable (PermissionError)"
    ], lines
    assert keys == set(), keys
    assert not (root / "ops" / "runtime" / "sync_inbox_report.txt").exists()


def test_ack_refuses_when_the_swallow_is_in_path_iterdir_itself(
    tmp_path, monkeypatch, capsys
):
    root = _watcher_root(tmp_path, monkeypatch)
    store = root / "ops" / "runtime" / "sync_inbox_seen.json"
    before = _sha(store)
    _deny_scandir_and_swallow_iterdir(monkeypatch, root / "moon_sync_inbox")

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert _sha(store) == before, "the ack erased the watermark: " + out
    assert rc == 3, (rc, out)
    assert "REFUSED" in out and "PermissionError" in out, out


def test_watcher_negative_control_a_truly_empty_inbox_does_report_withdrawals(
    tmp_path, monkeypatch
):
    """Mandatory: without it the arms above pass on a watcher that never
    reports a withdrawal at all."""
    root = _watcher_root(tmp_path, monkeypatch)

    lines, _anomalies, keys = rc_facts._inbox_section(root, None, subtract=False)
    assert f"## Cross-repo inbox - {len(_SEEN_KEYS)} WITHDRAWN since last ack" in lines
    assert len([k for k in keys if k.startswith("WITHDRAWN:")]) == len(_SEEN_KEYS)


# ------------------------------------------------------------------- poller


@pytest.fixture()
def state(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(d))
    monkeypatch.setattr(P, "state_dir", lambda: d)
    monkeypatch.setattr(P, "_state_dir_path", lambda: d)
    monkeypatch.setattr(P, "_SELF_REPO", str(tmp_path / "self-root"))
    # A fixed stamp, so an unchanged watermark is byte-identical rather than
    # differing only in its `updated` field.
    monkeypatch.setattr(P, "_utcnow", lambda: "2026-01-01T00:00:00+00:00")
    return d


def _baselined_repo(tmp_path: Path, state: Path) -> tuple[Path, dict]:
    root = tmp_path / "sibling-a"
    (root / "moon_sync_inbox").mkdir(parents=True)
    for i in range(3):
        (root / "moon_sync_inbox" / f"n{i}.md").write_text(str(i), encoding="utf-8")
    parts = {P._norm_root(str(root)): "AAA"}
    P.scan_fleet((str(root),), parts)
    stored = json.loads((state / "poller_seen.json").read_text(encoding="utf-8"))
    assert len(stored["repos"][str(root)]) == 3, "baseline did not record the notes"
    return root, parts


def test_poller_does_not_erase_its_watermark_when_listing_is_swallowed(
    state: Path, tmp_path: Path, monkeypatch
):
    root, parts = _baselined_repo(tmp_path, state)
    store = state / "poller_seen.json"
    before = _sha(store)

    _deny_listing(monkeypatch, root / "moon_sync_inbox")
    monkeypatch.setattr(P, "_inbox_entries", _swallowing_entries)

    out = P.scan_fleet((str(root),), parts)

    assert _sha(store) == before, (
        "the poller SAVED an empty entry over its watermark for an inbox it "
        "could not list - every acknowledged note is now forgotten"
    )
    assert out["findings"] == {}, out["findings"]
    row = out["rows"][0]
    assert row["withdrawn"] == [], row
    assert row["status"] != "OK", row
    assert "PermissionError" in row["status"], row


def test_poller_refuses_when_the_swallow_is_in_path_iterdir_itself(
    state: Path, tmp_path: Path, monkeypatch
):
    root, parts = _baselined_repo(tmp_path, state)
    store = state / "poller_seen.json"
    before = _sha(store)

    _deny_scandir_and_swallow_iterdir(monkeypatch, root / "moon_sync_inbox")
    out = P.scan_fleet((str(root),), parts)

    assert _sha(store) == before, "the poller saved an empty entry over its watermark"
    assert out["findings"] == {}, out["findings"]
    row = out["rows"][0]
    assert row["withdrawn"] == [], row
    assert row["status"] == "SCAN FAULT PermissionError", row


def test_seam_negative_control_the_wrapper_alone_changes_nothing(
    state: Path, tmp_path: Path, monkeypatch
):
    """Without a denied path the injected wrappers must be transparent, or the
    three arms above could be passing on a helper that breaks every listing."""
    root, parts = _baselined_repo(tmp_path, state)
    _deny_scandir_and_swallow_iterdir(monkeypatch, tmp_path / "not-the-inbox")
    out = P.scan_fleet((str(root),), parts)
    assert out["rows"][0]["status"] == "OK", out["rows"]
    assert out["rows"][0]["entries"] == 3, out["rows"]


def test_poller_negative_control_a_truly_emptied_inbox_is_a_withdrawal(
    state: Path, tmp_path: Path
):
    root, parts = _baselined_repo(tmp_path, state)
    for p in (root / "moon_sync_inbox").iterdir():
        p.unlink()

    out = P.scan_fleet((str(root),), parts)
    assert out["rows"][0]["status"] == "OK"
    assert len(out["findings"][str(root)]["withdrawn"]) == 3
    stored = json.loads((state / "poller_seen.json").read_text(encoding="utf-8"))
    assert stored["repos"][str(root)] == []
