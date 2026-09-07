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

import functools
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
GUARD = REPO / "tools" / "drift_guard.py"

sys.path.insert(0, str(REPO / "tools"))

REQUIRE_GATE_ENV = "RC_REQUIRE_HOOK_GATE"


def _is_configured_clone() -> bool:
    """True only on a clone whose core.hooksPath has been set locally.

    `core.hooksPath` is LOCAL git config and is NOT cloned, so CI and any fresh
    checkout legitimately have it unset. An assertion about THIS machine's hook
    wiring is therefore not a property of the repository and must not run there -
    it would fail on every clone forever. The local wiring is checked by
    `tools/drift_guard.py` at each /done, which is the right home for it.
    """
    r = subprocess.run(
        ["git", "-C", str(REPO), "config", "--get", "core.hooksPath"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() != ""


def _hook_gate_is_required() -> bool:
    """True when the CALLER has declared that the gate is already armed.

    Set by the `check` job in .github/workflows/ci.yml, immediately after it
    runs `python scripts/install_hooks.py`. Unset everywhere else.
    """
    return os.environ.get(REQUIRE_GATE_ENV, "").strip().lower() not in (
        "", "0", "false", "no", "off",
    )


def requires_armed_hook_gate(func):
    """Skip on an unwired clone - unless the caller SAID it wired one.

    MEASURED 2026-07-26: all five tracked hooks in .githooks/ were committed
    mode 100644, so git silently refused to run ANY of them on every Linux
    clone, CI included. The bug survived because the two live-repo assertions
    in this file were guarded by `_is_configured_clone()`, which is false in
    CI - and a SKIPPED test reports as a green tick. CI was structurally unable
    to observe its own missing gate.

    Deleting the skip is not the fix. `core.hooksPath` is LOCAL config, is not
    cloned, and a fresh developer checkout legitimately has it unset, so an
    unconditional assertion would fail forever on every new clone - which is
    exactly the reasoning recorded in `_is_configured_clone`. The fix is an
    explicit opt-in: when RC_REQUIRE_HOOK_GATE is set, "unconfigured" stops
    being an excuse and becomes the hard failure it actually is.

    Both directions are pinned by HookGateRequirementTests below, because this
    repo has repeatedly been bitten by guards that degraded into always-passing.
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if _is_configured_clone():
            return func(self, *args, **kwargs)
        if _hook_gate_is_required():
            raise AssertionError(
                f"{REQUIRE_GATE_ENV} is set, so the hook gate was supposed to be "
                "ARMED - but core.hooksPath is unset, meaning git is running no "
                "hooks at all. Run: python scripts/install_hooks.py"
            )
        raise unittest.SkipTest("hooksPath unset - fresh clone (set "
                                f"{REQUIRE_GATE_ENV}=1 to make this a failure)")

    return wrapper


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

    def test_memory_linked_only_from_a_subindex_is_not_a_breach(self) -> None:
        """MEMORY.md may delegate a section to an INDEX_*.md sub-index (the
        real-world shape: INDEX_ds.md carries the DS section) instead of
        linking every memory directly - the clean path this fix creates."""
        import drift_guard

        d = self._mem(
            "- [a](alpha.md)\n"
            "- **DS: 1 entry in [INDEX_ds.md](INDEX_ds.md)**\n",
            ("alpha", "INDEX_ds", "ds_topic"),
        )
        (d / "INDEX_ds.md").write_text("- [t](ds_topic.md)\n", encoding="utf-8")
        self.assertEqual(drift_guard.check_memory_index(d, ()), [])

    def test_memory_absent_from_index_and_subindex_is_a_breach(self) -> None:
        """The breach path must survive the sub-index follow: a memory that
        is in NEITHER MEMORY.md nor any linked sub-index is still reported."""
        import drift_guard

        d = self._mem(
            "- [a](alpha.md)\n"
            "- **DS: 1 entry in [INDEX_ds.md](INDEX_ds.md)**\n",
            ("alpha", "INDEX_ds", "ds_topic", "orphan_ds_topic"),
        )
        (d / "INDEX_ds.md").write_text("- [t](ds_topic.md)\n", encoding="utf-8")
        out = drift_guard.check_memory_index(d, ())
        self.assertTrue(out)
        self.assertIn("orphan_ds_topic", out[0].message)

    def test_subindex_of_a_subindex_is_not_followed(self) -> None:
        """One level only - a sub-index linking a sub-sub-index is not a
        shape this repo has, so a memory buried two levels deep still
        reports (proves the follow does not silently grow into recursion)."""
        import drift_guard

        d = self._mem(
            "- [a](alpha.md)\n- [d](INDEX_ds.md)\n",
            ("alpha", "INDEX_ds", "INDEX_sub", "buried"),
        )
        (d / "INDEX_ds.md").write_text("- [s](INDEX_sub.md)\n", encoding="utf-8")
        (d / "INDEX_sub.md").write_text("- [b](buried.md)\n", encoding="utf-8")
        out = drift_guard.check_memory_index(d, ())
        self.assertTrue(any("buried" in f.message for f in out))


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

    def test_a_release_transition_line_is_history_not_a_stale_anchor(self) -> None:
        """The check excluded historical FILES by name but not historical LINES.

        MEASURED 2026-07-26 on a README carrying a release-history list whose
        entries read `- 1.259.0 -> 1.260.0 - <prose>`. That names the old
        version, so the whole-file scan flagged it - but the line is CORRECT
        history, and the honest fix is a smaller check, not a looser one. A
        `N.N.N -> N.N.N` transition on the line is the marker: it presents the
        version as a step that was taken, not as the version in force.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "REL.md").write_text(
            "# Releases\n\n"
            "- 1.259.0 -> 1.260.0 - closed three filed defects\n"
            "- 1.258.0 -> 1.259.0 - the second term the last release needed\n",
            encoding="utf-8",
        )
        self.assertEqual(drift_guard.check_version_anchors(root, "1.259.0"), [])

    def test_a_dated_status_heading_makes_its_own_section_history(self) -> None:
        """Line-level context cannot see a heading, and the heading was the fact.

        MEASURED 2026-08-12 on the 1.277.1 bump: the sweep flagged
        `docs/OVERLAY_COMPLIANCE_PLAN.md:35`, reading "in sync at engine
        1.277.0, 533 files". No transition and no closure keyword, so both
        line-level markers missed it - but it sits under `## 1b. STATUS as of
        2026-08-11`, which makes it a DATED SNAPSHOT. 1.277.0 was the live
        engine on that date; rewriting it to the current version would make the
        record FALSE rather than fresh.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "PLAN.md").write_text(
            "# Plan\n\n"
            "## 1b. STATUS as of 2026-08-11\n\n"
            "Landed this session, all verified green (`gen_archmap --check`\n"
            "in sync at engine 1.277.0).\n",
            encoding="utf-8",
        )
        self.assertEqual(drift_guard.check_version_anchors(root, "1.277.0"), [])

    def test_a_dated_status_section_does_not_shelter_the_rest_of_the_doc(self) -> None:
        """The block exemption must END at the next same-or-shallower heading.

        This is the failure mode that makes a block exemption more dangerous
        than a line one: a single dated section near the top could otherwise
        silence every stale anchor below it. The live claim under the LATER
        heading must still be reported.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "PLAN.md").write_text(
            "# Plan\n\n"
            "## 1b. STATUS as of 2026-08-11\n\n"
            "in sync at engine 1.277.0, 533 files.\n\n"
            "## 2. Current\n\n"
            "The engine is at 1.277.0 and that is the version in force.\n",
            encoding="utf-8",
        )
        out = drift_guard.check_version_anchors(root, "1.277.0")
        self.assertTrue(out, "a live anchor AFTER the dated section must be caught")
        self.assertIn("docs/PLAN.md:9", out[0].message)
        self.assertNotIn("docs/PLAN.md:5", out[0].message)

    def test_an_undated_status_heading_earns_no_exemption(self) -> None:
        """A bare "as of" is too easy to write by accident to carry a section.

        The ISO date is what makes the heading a verifiable snapshot rather
        than a phrase, so it is required.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "PLAN.md").write_text(
            "# Plan\n\n"
            "## STATUS as of today\n\n"
            "in sync at engine 1.277.0, 533 files.\n",
            encoding="utf-8",
        )
        self.assertTrue(
            drift_guard.check_version_anchors(root, "1.277.0"),
            "only an explicitly dated heading may exempt its section",
        )

    def test_a_slash_joined_version_pair_is_provenance_not_a_live_anchor(self) -> None:
        """A line naming TWO versions cannot be asserting which one is live.

        MEASURED 2026-08-04 on the 1.275.0 bump: the G2-47 live-gated row reads
        ``**G2-47** RM-42 ``apply_passive_damage`` + ``apply_extra_shot_procs``
        on the CARRY ranker (ENGINE 1.273.0 / 1.274.0)`` - the two flags shipped
        at two different revisions and the row cites both. That is provenance,
        not a claim about the engine in force, but ``/`` was not in the
        transition separator class so the sweep flagged it. A live anchor names
        exactly ONE version; ``/`` joins a pair the same way ``->`` joins a
        transition.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "GATED.md").write_text(
            "# Gated\n\n"
            "- G2-47 two flags on the carry ranker (ENGINE 1.258.0 / 1.259.0)\n",
            encoding="utf-8",
        )
        self.assertEqual(drift_guard.check_version_anchors(root, "1.258.0"), [])

    def test_a_lone_stale_version_still_breaches_after_the_slash_widen(self) -> None:
        """The widen must not swallow a genuine single-version live anchor."""
        import drift_guard

        root = self._tree()
        (root / "docs" / "LIVE.md").write_text(
            "# Live\n\nENGINE_VERSION 1.258.0 is the engine in force.\n",
            encoding="utf-8",
        )
        out = drift_guard.check_version_anchors(root, "1.258.0")
        self.assertTrue(out, "a lone stale version anchor must still breach")

    def test_a_stale_line_in_a_file_that_also_has_history_still_breaches(self) -> None:
        """The narrowing must be per LINE, not per file.

        A whole-file exemption keyed on "this doc contains a transition list"
        would re-open the exact hole the check exists to close - the stale
        anchor and the legitimate history routinely live in the SAME doc.
        """
        import drift_guard

        root = self._tree()
        (root / "docs" / "REL.md").write_text(
            "Current ENGINE_VERSION is 1.259.0.\n\n"
            "- 1.259.0 -> 1.260.0 - closed three filed defects\n",
            encoding="utf-8",
        )
        out = drift_guard.check_version_anchors(root, "1.259.0")
        self.assertTrue(out, "a live claim must still breach next to real history")
        self.assertIn("docs/REL.md:1", out[0].message)

    def test_the_live_repo_has_no_stale_anchor_for_the_previous_engine(self) -> None:
        """Pinned against the false positive that motivated the fix.

        This is the assertion the 2026-07-26 wrap could not make: the guard
        reported three sites naming 1.259.0 and all three were history. If a
        future bump leaves a genuinely stale anchor behind, this fails.
        """
        import drift_guard

        self.assertEqual(drift_guard.check_version_anchors(REPO, "1.259.0"), [])


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

    def test_fresh_clone_shape_is_a_breach(self) -> None:
        """core.hooksPath is LOCAL config and is NOT cloned.

        A fresh clone of this repo has NO hooks at all until someone sets the
        pointer - which defeats the entire purpose of a tracked .githooks dir.
        The guard must therefore fire on "tracked hooks present, pointer unset",
        not merely on "pointer aimed somewhere wrong". Raised by the parallel
        Sibling-A session; neither repo's write-up had caught it.
        """
        import drift_guard
        root = pathlib.Path(tempfile.mkdtemp())
        (root / ".githooks").mkdir()
        (root / ".githooks" / "pre-commit").write_text("x", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True)
        out = drift_guard.check_git_hooks_path(root)
        self.assertTrue(out, "an unset core.hooksPath with tracked hooks must breach")
        self.assertIn("unset", out[0].message.lower())

    @requires_armed_hook_gate
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

    @requires_armed_hook_gate
    def test_live_repo_has_no_orphans(self) -> None:
        """Pinned: this repo lost LFS checkout AND LFS upload to this exact bug."""
        import drift_guard
        self.assertEqual(drift_guard.check_orphaned_git_hooks(REPO), [])


class HookGateRequirementTests(unittest.TestCase):
    """Guards the guard's ESCAPE HATCH, both directions.

    The skip that `requires_armed_hook_gate` replaced was not wrong - it was
    unfalsifiable. It reported green on the one machine (CI) where the gate was
    entirely absent, for the whole life of the mode-100644 bug. A replacement
    that can only ever skip would be the same bug wearing a new name, so the
    opt-in is pinned in both directions: it must SKIP on a bare clone and it
    must FAIL when the caller has declared the gate armed.
    """

    def _decorated(self):
        calls: list[str] = []

        class Probe(unittest.TestCase):
            @requires_armed_hook_gate
            def runTest(probe_self) -> None:
                calls.append("ran")

        return Probe(), calls

    def test_env_unset_is_not_required(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(REQUIRE_GATE_ENV, None)
            self.assertFalse(_hook_gate_is_required())

    def test_env_set_to_one_is_required(self) -> None:
        with mock.patch.dict(os.environ, {REQUIRE_GATE_ENV: "1"}):
            self.assertTrue(_hook_gate_is_required())

    def test_falsey_spellings_are_not_required(self) -> None:
        """`RC_REQUIRE_HOOK_GATE=0` must not arm the assertion by accident."""
        for value in ("0", "", "false", "FALSE", "no", "off", "  "):
            with mock.patch.dict(os.environ, {REQUIRE_GATE_ENV: value}):
                self.assertFalse(
                    _hook_gate_is_required(), f"{value!r} must read as not-required"
                )

    def test_unconfigured_clone_skips_when_not_required(self) -> None:
        probe, calls = self._decorated()
        with mock.patch(f"{__name__}._is_configured_clone", return_value=False), \
                mock.patch(f"{__name__}._hook_gate_is_required", return_value=False):
            with self.assertRaises(unittest.SkipTest):
                probe.runTest()
        self.assertEqual(calls, [], "the body must not run on an unwired clone")

    def test_unconfigured_clone_FAILS_when_required(self) -> None:
        """The whole point: a declared-armed gate that is not armed is a failure."""
        probe, calls = self._decorated()
        with mock.patch(f"{__name__}._is_configured_clone", return_value=False), \
                mock.patch(f"{__name__}._hook_gate_is_required", return_value=True):
            with self.assertRaises(AssertionError) as ctx:
                probe.runTest()
        self.assertIn("install_hooks.py", str(ctx.exception))
        self.assertNotIsInstance(
            ctx.exception, unittest.SkipTest, "must not degrade back into a skip"
        )
        self.assertEqual(calls, [])

    def test_configured_clone_runs_the_body(self) -> None:
        probe, calls = self._decorated()
        with mock.patch(f"{__name__}._is_configured_clone", return_value=True), \
                mock.patch(f"{__name__}._hook_gate_is_required", return_value=False):
            probe.runTest()
        self.assertEqual(calls, ["ran"])


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
