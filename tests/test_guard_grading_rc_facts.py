"""Grade two tools/rc_facts.py guards that nothing else failed on when removed.

Found by a mutation sweep on 2026-09-16. Each guard below was replaced with
`if False:` and every test file that references rc_facts still passed, exit 0.
A guard nothing grades is decoration, so each arm here is written to fail under
exactly that mutation and pass on the shipped source.

1. `mark_inbox_seen` - `if not inbox.is_dir(): ... return 3`.
   With the guard removed, an absent inbox is still refused, but only because
   the later `_probe_inbox_listable` happens to raise FileNotFoundError. That
   probe lists through TWO primitives since 17f158045 - `Path.iterdir` and a
   direct `os.scandir` - so either one raising is enough to mask the missing
   guard. The guard gives two things the probe does not: the ABSENT diagnosis
   (the remedy is "run this from the tree that holds the inbox", not "fix
   permissions"), and a refusal that does not depend on the probe raising.
   Arm B makes BOTH listing primitives report an empty listing for the absent
   inbox path only (every other path delegates to the real primitive), so no
   listing layer raises for it, and demands the store survive. Patching only
   one primitive is not enough: the first version of this arm patched
   `Path.iterdir` alone and still passed with the guard removed, because the
   probe's `os.scandir` raised instead.

2. `_payload_key` - `if _is_reparse_point(f):` on the FILE loop.
   The existing junction test covers the directory loop only. A file symlink in
   a payload is a reparse point too, and without the refusal the walk reads and
   digests whatever file the link points at. Arm C is portable and runs
   everywhere; arm D uses a real symlink wherever the host allows creating one.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import rc_facts  # noqa: E402

REFUSAL_EXIT = 3

_PRELOADED = json.dumps({"seen": ["a.md [1111aaaa2222]"]}, indent=2)


def _store(root: Path) -> Path:
    return root / "ops" / "runtime" / "sync_inbox_seen.json"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _root_without_inbox(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    (root / "ops" / "runtime").mkdir(parents=True)
    _store(root).write_text(_PRELOADED, encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_ROOT", root)
    return root


# ------------------------------------------------ 1. the absent-inbox refusal


def test_absent_inbox_is_diagnosed_as_absent_not_as_unlistable(
    tmp_path, monkeypatch, capsys
):
    root = _root_without_inbox(tmp_path, monkeypatch)
    before = _sha(_store(root))

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert rc == REFUSAL_EXIT, rc
    assert _sha(_store(root)) == before
    assert "is absent" in out, (
        "an absent inbox was refused under the UNLISTABLE diagnosis - the "
        "absent-inbox guard did not run, and the operator is told to chase a "
        "permissions fault instead of the wrong working tree: " + out
    )
    assert "could not be listed" not in out, out


def test_absent_inbox_refuses_even_when_the_listing_probe_does_not_raise(
    tmp_path, monkeypatch, capsys
):
    root = _root_without_inbox(tmp_path, monkeypatch)
    before = _sha(_store(root))
    inbox = root / "moon_sync_inbox"
    real_iterdir = Path.iterdir
    real_scandir = os.scandir

    def _is_inbox(target) -> bool:
        try:
            return os.path.normcase(os.path.abspath(os.fspath(target))) == (
                os.path.normcase(os.path.abspath(os.fspath(inbox)))
            )
        except TypeError:
            return False

    class _EmptyScandir:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration

        def close(self):
            pass

    def quiet_iterdir(self):
        # A listing that reports "nothing here" for the absent inbox instead
        # of raising: the shape a softened pathlib layer would take.
        if _is_inbox(self):
            return iter(())
        return real_iterdir(self)

    def quiet_scandir(path="."):
        # Same softening one layer down, for the absent inbox ONLY.
        if _is_inbox(path):
            return _EmptyScandir()
        return real_scandir(path)

    monkeypatch.setattr(Path, "iterdir", quiet_iterdir)
    monkeypatch.setattr(os, "scandir", quiet_scandir)

    # Precondition: no listing primitive raises for the absent inbox, so a
    # refusal below can only come from the absent-inbox guard itself.
    rc_facts._probe_inbox_listable(inbox)

    rc = rc_facts.mark_inbox_seen()
    out = capsys.readouterr().out

    assert _sha(_store(root)) == before, (
        "the seen store was overwritten for an inbox that does not exist - "
        "the refusal depended on the probe raising, not on the absent-inbox "
        "guard: " + out
    )
    assert rc == REFUSAL_EXIT, rc


# ------------------------------------ 2. the file-level reparse-point refusal


def _drop_with_file(tmp_path: Path) -> Path:
    drop = tmp_path / "from-XX-verbatim"
    drop.mkdir()
    (drop / "a.txt").write_bytes(b"alpha")
    return drop


def test_payload_walk_refuses_a_file_reparse_point_without_reading_it(
    tmp_path, monkeypatch
):
    drop = _drop_with_file(tmp_path)
    (drop / "link.txt").write_bytes(b"stands in for a linked file")
    link = drop / "link.txt"

    monkeypatch.setattr(rc_facts, "_is_reparse_point", lambda p: Path(p) == link)
    digested: list[str] = []
    real_digest = rc_facts._file_digest

    def recording_digest(p):
        digested.append(Path(p).name)
        return real_digest(p)

    monkeypatch.setattr(rc_facts, "_file_digest", recording_digest)

    key = rc_facts._payload_key(drop)

    assert "link.txt" not in digested, (
        "the walk read a file reparse point instead of refusing it: " + repr(digested)
    )
    assert key.startswith("[1 files, "), key


def test_payload_walk_refuses_a_real_file_symlink_and_moves_the_digest(tmp_path):
    drop = _drop_with_file(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not ours")

    baseline = rc_facts._payload_key(drop)
    try:
        os.symlink(outside, drop / "link.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this host cannot create a file symlink: {exc}")

    after = rc_facts._payload_key(drop)
    assert after != baseline, "a file reparse point appeared and the key did not move"
    assert after.startswith("[1 files, "), (
        "the walk followed a file symlink out of the drop instead of refusing it: " + after
    )
