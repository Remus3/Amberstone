"""The Share mirror rebuild must never be able to leave Share/src empty.

INCIDENT 2026-07-19 (commit 6464532e): a commit recorded 501 deletions /
596,900 lines removed and ZERO additions across Share/src, emptying the mirror
on main. Root cause was the shape of ``_write``: it called
``shutil.rmtree(Share/src)`` and only THEN wrote the expected files back, so the
live mirror spent the whole rebuild deleted. The precommit gate invokes that on
any commit staging mirrored DS source, so an interruption or a race anywhere in
those ~483 writes leaves the tree empty and git snapshots the gap as intent.

Two independent guards are pinned here:

1. ``_write({})`` must REFUSE rather than delete. An empty expected set can only
   mean the builder failed; honouring it destroys the mirror.
2. ``_write`` must be ATOMIC with respect to the live tree - it stages into a
   temp directory and swaps, so a failure part-way through leaves the previous
   mirror fully intact rather than half-written.

Guard 2 is the one that actually fixes the incident; guard 1 is the cheap
backstop for the failure mode where the builder returns nothing at all.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

sync = importlib.import_module("tools.ds_share_sync")


class _MirrorHarness(unittest.TestCase):
    """Point the module's _SRC at a scratch tree so the real mirror is safe."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "src"
        self._orig_src = sync._SRC
        sync._SRC = self.src
        self.addCleanup(lambda: setattr(sync, "_SRC", self._orig_src))

        # Seed a populated "previous mirror".
        (self.src / "agents" / "daemon_slayer").mkdir(parents=True)
        (self.src / "agents" / "daemon_slayer" / "engine.py").write_bytes(b"OLD ENGINE")
        (self.src / "keep.txt").write_bytes(b"OLD KEEP")

    def _listing(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.src).as_posix(): p.read_bytes()
            for p in sorted(self.src.rglob("*")) if p.is_file()
        }


class RefusesEmptyExpectedTests(_MirrorHarness):

    def test_write_refuses_empty_expected_and_leaves_mirror_intact(self):
        before = self._listing()
        self.assertTrue(before, "harness seeded no files")

        with self.assertRaises(ValueError):
            sync._write({})

        self.assertEqual(self._listing(), before,
                         "an empty expected set must not touch the live mirror")

    def test_write_accepts_a_normal_expected_set(self):
        n = sync._write({
            "agents/daemon_slayer/engine.py": b"NEW ENGINE",
            "nested/deep/file.json": b"{}",
        })
        self.assertEqual(n, 2)
        self.assertEqual(self._listing(), {
            "agents/daemon_slayer/engine.py": b"NEW ENGINE",
            "nested/deep/file.json": b"{}",
        })

    def test_write_removes_files_absent_from_expected(self):
        """The rebuild is authoritative - stale files must not survive it.
        This is the behaviour the rmtree existed to provide, and the atomic
        swap must preserve it."""
        sync._write({"only.py": b"X"})
        self.assertEqual(sorted(self._listing()), ["only.py"])


class AtomicOnFailureTests(_MirrorHarness):

    def test_partial_write_failure_leaves_previous_mirror_intact(self):
        """THE INCIDENT TEST. Pre-fix this left Share/src deleted or partial."""
        before = self._listing()

        class _Exploding(dict):
            """Yields one good item, then raises - a write interrupted midway."""
            def items(self):
                yield "agents/daemon_slayer/engine.py", b"NEW ENGINE"
                raise RuntimeError("simulated interruption mid-rebuild")

        with self.assertRaises(RuntimeError):
            sync._write(_Exploding({"x": b"y"}))

        self.assertEqual(
            self._listing(), before,
            "a failure part-way through the rebuild must leave the previous "
            "mirror byte-identical, not deleted and not half-written")

    def test_no_scratch_directories_survive_a_successful_write(self):
        sync._write({"a.py": b"A"})
        leftovers = [p.name for p in self.root.iterdir() if p.name != "src"]
        self.assertEqual(leftovers, [],
                         f"scratch dirs left behind: {leftovers}")

    def test_stale_scratch_from_a_prior_crash_does_not_block_a_write(self):
        stale_tmp = self.root / (self.src.name + ".tmp")
        stale_tmp.mkdir()
        (stale_tmp / "junk.py").write_bytes(b"JUNK")

        sync._write({"a.py": b"A"})

        self.assertEqual(sorted(self._listing()), ["a.py"])
        self.assertFalse(stale_tmp.exists(), "stale scratch dir was not cleared")


if __name__ == "__main__":
    unittest.main()
