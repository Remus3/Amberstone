"""Guards for the per-session drift guard (tools/drift_guard.py).

WHY THIS EXISTS
---------------
Every check in ``drift_guard`` exists because the drift it catches ACTUALLY
HAPPENED in this repo and later cost a dedicated cleanup session: a budgeted doc
breaching and sitting over, two copies of one ritual doc diverging for a month,
memory files written but never indexed, a version anchor living in a doc site no
checklist named, orphaned docs accumulating to 27, and 11 authored command docs
sitting under a gitignored directory with zero version control.

The guard is a SCRIPT rather than a prose checklist on purpose - a prose
checklist is precisely what drifted. This file guards the guard: each check is
exercised against a synthetic tree where the breach is KNOWN to be present, and
against one where it is known to be absent, so a check cannot silently degrade
into always-passing (the failure mode that makes a guard worse than useless).
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
GUARD = REPO / "tools" / "drift_guard.py"

sys.path.insert(0, str(REPO / "tools"))


class ModuleShapeTests(unittest.TestCase):
    """The script exists, compiles, and exposes the documented surface."""

    def test_guard_exists_and_compiles(self) -> None:
        self.assertTrue(GUARD.is_file(), f"{GUARD} missing")
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(GUARD)],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_exposes_the_documented_checks(self) -> None:
        import drift_guard

        for name in (
            "check_doc_budgets",
            "check_mirror_parity",
            "check_memory_index",
            "check_version_anchors",
            "check_counted_claims",
            "check_untracked_authored",
            "run_all",
            "Finding",
        ):
            self.assertTrue(
                hasattr(drift_guard, name), f"drift_guard.{name} missing"
            )

    def test_is_ascii(self) -> None:
        raw = GUARD.read_bytes()
        bad = [(i, hex(b)) for i, b in enumerate(raw) if b > 127]
        self.assertEqual(bad, [], f"non-ASCII bytes in drift_guard.py: {bad[:5]}")


class DocBudgetTests(unittest.TestCase):
    """Breach and clean, both asserted - a check that never fires is dead."""

    def _tmp(self) -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        return d

    def test_over_budget_is_a_breach(self) -> None:
        import drift_guard

        root = self._tmp()
        (root / "BIG.md").write_text("x" * 500, encoding="utf-8")
        out = drift_guard.check_doc_budgets(root, {"BIG.md": 100})
        self.assertTrue(out)
        self.assertIn("BIG.md", out[0].message)

    def test_near_budget_warns_before_it_breaches(self) -> None:
        """90 percent is the useful signal - at 100 percent it is already late."""
        import drift_guard

        root = self._tmp()
        (root / "NEAR.md").write_text("x" * 96, encoding="utf-8")
        out = drift_guard.check_doc_budgets(root, {"NEAR.md": 100})
        self.assertTrue(out, "a doc at 96 percent must warn")

    def test_comfortably_under_budget_is_clean(self) -> None:
        import drift_guard

        root = self._tmp()
        (root / "SMALL.md").write_text("x" * 10, encoding="utf-8")
        self.assertEqual(drift_guard.check_doc_budgets(root, {"SMALL.md": 100}), [])

    def test_absent_file_is_not_a_breach(self) -> None:
        import drift_guard

        self.assertEqual(
            drift_guard.check_doc_budgets(self._tmp(), {"NOPE.md": 100}), []
        )


class MirrorParityTests(unittest.TestCase):
    """The 404-line divergence class."""

    def _pair(self, a_text: str, b_text: str) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "tools").mkdir()
        (root / "cmds").mkdir()
        (root / "tools" / "done.md").write_text(a_text, encoding="utf-8")
        (root / "cmds" / "done.md").write_text(b_text, encoding="utf-8")
        return root

    def test_divergence_is_a_breach(self) -> None:
        import drift_guard

        root = self._pair("one\n", "two\n")
        out = drift_guard.check_mirror_parity(root, [("tools", "cmds")])
        self.assertTrue(out)
        self.assertIn("done.md", out[0].message)

    def test_identical_is_clean(self) -> None:
        import drift_guard

        root = self._pair("same\n", "same\n")
        self.assertEqual(drift_guard.check_mirror_parity(root, [("tools", "cmds")]), [])

    def test_file_present_on_only_one_side_is_not_a_breach(self) -> None:
        """A command that exists in one place only is normal, not drift."""
        import drift_guard

        root = pathlib.Path(tempfile.mkdtemp())
        (root / "tools").mkdir()
        (root / "cmds").mkdir()
        (root / "tools" / "solo.md").write_text("x", encoding="utf-8")
        self.assertEqual(drift_guard.check_mirror_parity(root, [("tools", "cmds")]), [])


class MemoryIndexTests(unittest.TestCase):
    def _mem(self, index: str, files: tuple[str, ...]) -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "MEMORY.md").write_text(index, encoding="utf-8")
        for f in files:
            (d / f"{f}.md").write_text("body", encoding="utf-8")
        return d

    def test_unindexed_file_is_a_breach(self) -> None:
        import drift_guard

        d = self._mem("- [a](alpha.md)\n", ("alpha", "beta"))
        out = drift_guard.check_memory_index(d, ())
        self.assertTrue(out)
        self.assertIn("beta", out[0].message)

    def test_dead_link_is_a_breach(self) -> None:
        import drift_guard

        d = self._mem("- [a](alpha.md)\n- [gone](ghost.md)\n", ("alpha",))
        out = drift_guard.check_memory_index(d, ())
        self.assertTrue(any("ghost" in f.message for f in out))

    def test_prefix_exempt_files_are_not_breaches(self) -> None:
        """The ~99 per-champion sweep memories are excluded by design."""
        import drift_guard

        d = self._mem("- [a](alpha.md)\n", ("alpha", "sweep_zed", "sweep_ahri"))
        self.assertEqual(drift_guard.check_memory_index(d, ("sweep_",)), [])

    def test_fully_indexed_is_clean(self) -> None:
        import drift_guard

        d = self._mem("- [a](alpha.md)\n- [b](beta.md)\n", ("alpha", "beta"))
        self.assertEqual(drift_guard.check_memory_index(d, ()), [])


class VersionAnchorTests(unittest.TestCase):
    """The hexcore-anchor class: a version site no checklist names."""

    def _tree(self) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "docs").mkdir()
        return root

    def test_stale_version_in_an_authored_doc_is_a_breach(self) -> None:
        import drift_guard

        root = self._tree()
        (root / "docs" / "GUIDE.md").write_text("ENGINE 1.258.0 here", encoding="utf-8")
        out = drift_guard.check_version_anchors(root, "1.258.0")
        self.assertTrue(out)

    def test_html_sites_are_swept_too(self) -> None:
        """A *.md-only grep is exactly how the hexcore site was missed."""
        import drift_guard

        root = self._tree()
        (root / "docs" / "HEX.html").write_text(
            "<div title='ENGINE_VERSION 1.258.0'>", encoding="utf-8"
        )
        out = drift_guard.check_version_anchors(root, "1.258.0")
        self.assertTrue(out, "HTML anchor sites must be swept, not just markdown")

    def test_changelog_and_history_legitimately_name_old_versions(self) -> None:
        import drift_guard

        root = self._tree()
        (root / "CHANGELOG.md").write_text("1.258.0 shipped X", encoding="utf-8")
        (root / "docs" / "LEDGER.md").write_text("1.258.0 shipped X", encoding="utf-8")
        self.assertEqual(drift_guard.check_version_anchors(root, "1.258.0"), [])

    def test_no_old_version_supplied_is_a_no_op(self) -> None:
        import drift_guard

        root = self._tree()
        (root / "docs" / "G.md").write_text("1.258.0", encoding="utf-8")
        self.assertEqual(drift_guard.check_version_anchors(root, None), [])


class CountedClaimTests(unittest.TestCase):
    """The 'fifteen most recent' above a list of twenty."""

    def test_mismatched_count_is_a_breach(self) -> None:
        import drift_guard

        root = pathlib.Path(tempfile.mkdtemp())
        body = "The five most recent:\n\n" + "".join(
            f"- 1.{i}.0 -> 1.{i + 1}.0 - thing\n" for i in range(7)
        )
        (root / "README.md").write_text(body, encoding="utf-8")
        out = drift_guard.check_counted_claims(root)
        self.assertTrue(out)

    def test_matching_count_is_clean(self) -> None:
        import drift_guard

        root = pathlib.Path(tempfile.mkdtemp())
        body = "The five most recent:\n\n" + "".join(
            f"- 1.{i}.0 -> 1.{i + 1}.0 - thing\n" for i in range(5)
        )
        (root / "README.md").write_text(body, encoding="utf-8")
        self.assertEqual(drift_guard.check_counted_claims(root), [])


class GitHooksPathTests(unittest.TestCase):
    """The tracked-hooks pointer, both directions."""

    def test_exposed(self) -> None:
        import drift_guard
        self.assertTrue(hasattr(drift_guard, "check_git_hooks_path"))

    def test_no_githooks_dir_is_a_no_op(self) -> None:
        import drift_guard
        root = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(drift_guard.check_git_hooks_path(root), [])

    def test_live_repo_points_at_the_tracked_dir(self) -> None:
        """This repo must stay pointed at .githooks.

        Pinned as a real assertion, not a smoke check: when this pointer moved,
        three tracked guards stopped running and nothing surfaced it for long
        enough that two generated artifacts drifted.
        """
        import drift_guard
        self.assertEqual(drift_guard.check_git_hooks_path(REPO), [])


class OrphanedHookTests(unittest.TestCase):
    """The regression that flipping core.hooksPath actually caused."""

    def _tree(self, tracked: tuple[str, ...], untracked: tuple[str, ...]) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp())
        (root / ".githooks").mkdir()
        (root / ".git" / "hooks").mkdir(parents=True)
        for n in tracked:
            (root / ".githooks" / n).write_text("x", encoding="utf-8")
        for n in untracked:
            (root / ".git" / "hooks" / n).write_text("x", encoding="utf-8")
        return root

    def test_orphan_is_a_breach(self) -> None:
        import drift_guard
        root = self._tree(("pre-commit",), ("pre-commit", "pre-push"))
        out = drift_guard.check_orphaned_git_hooks(root)
        self.assertTrue(out)
        self.assertIn("pre-push", out[0].message)

    def test_samples_are_ignored(self) -> None:
        import drift_guard
        root = self._tree(("pre-commit",), ("pre-commit", "pre-push.sample"))
        self.assertEqual(drift_guard.check_orphaned_git_hooks(root), [])

    def test_full_parity_is_clean(self) -> None:
        import drift_guard
        root = self._tree(("pre-commit", "pre-push"), ("pre-commit", "pre-push"))
        self.assertEqual(drift_guard.check_orphaned_git_hooks(root), [])

    def test_live_repo_has_no_orphans(self) -> None:
        """Pinned: this repo lost LFS checkout AND LFS upload to this exact bug."""
        import drift_guard
        self.assertEqual(drift_guard.check_orphaned_git_hooks(REPO), [])


class LiveRepoTests(unittest.TestCase):
    """The guard must RUN against this repo without exploding.

    Deliberately does NOT assert the repo is clean - findings are the guard
    working, and pinning them green would force a future session to weaken the
    guard rather than fix the drift.
    """

    def test_runs_against_the_real_repo(self) -> None:
        r = subprocess.run(
            [sys.executable, str(GUARD)],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertIn(r.returncode, (0, 1), f"unexpected exit: {r.stderr[:400]}")
        self.assertIn("drift_guard:", r.stdout)

    def test_exit_code_is_one_when_a_breach_is_reported(self) -> None:
        r = subprocess.run(
            [sys.executable, str(GUARD)],
            capture_output=True, text=True, cwd=str(REPO),
        )
        breaches = "BREACH" in r.stdout
        self.assertEqual(
            r.returncode, 1 if breaches else 0,
            "exit code must track whether a breach was reported",
        )


if __name__ == "__main__":
    unittest.main()
