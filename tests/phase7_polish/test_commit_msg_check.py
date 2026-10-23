"""
tests/phase7_polish/test_commit_msg_check.py
Phase 7 - Conventional Commits validator.

Verifies the validator accepts every shape recently in `git log` and rejects
the common malformed cases.
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "precommit_msg_check",
        _PROJECT_ROOT / "scripts" / "precommit_msg_check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CM = _load_module()


class TestValidate(unittest.TestCase):
    def _ok(self, subject: str):
        ok, err = CM.validate(subject)
        self.assertTrue(ok, f"expected ok for {subject!r}, got: {err}")

    def _bad(self, subject: str):
        ok, _ = CM.validate(subject)
        self.assertFalse(ok, f"expected reject for {subject!r}")

    # -- Real-shapes from `git log` --------------------------------------------

    def test_recent_commits_accepted(self):
        for subj in [
            "feat(arch): Phase 7 - normalize phase-marker comments + auto-index",
            "docs: sync living docs - Phase 7 phase-markers (s141)",
            "feat(vision): Phase 2.4 - split moon_vision_server.py into package",
            "feat(coaching): Phase 2.3 - split coach_integration.py into package",
            "chore: archive s128 to history_notes; trim WAKEUP_NOTES to 3 sessions",
            "fix(coach): NameError on manual_level path",
        ]:
            self._ok(subj)

    def test_all_canonical_types(self):
        for t in CM.TYPES:
            self._ok(f"{t}: a real description")

    def test_scope_with_dot_slash_dash(self):
        self._ok("feat(scripts/wakeup): add prune helper")
        self._ok("fix(api.v2): tighten validation")
        self._ok("chore(deps-dev): bump pytest")

    def test_breaking_change_marker(self):
        self._ok("feat(api)!: drop /v0 endpoints")
        self._ok("refactor!: rewrite scheduler")

    # -- Auto-generated subjects (skipped, not parsed) ------------------------

    def test_merge_commits_pass_through(self):
        self._ok("Merge branch 'main' into feature/x")
        self._ok("Merge remote-tracking branch 'origin/main'")
        self._ok("Merge branch 'lane/ds'")

    # -- Merge template (MAIN PUBREPO order 1b) -------------------------------

    def test_merge_type_accepted(self):
        self._ok("merge: stop-claim gate gaps")
        self._ok("merge(RM-123): stop-claim gate gaps")

    def test_item_id_in_scope_accepted(self):
        self._ok("fix(RM-123): close the parse cap gap")

    def _refused_with_template_hint(self, subject: str):
        ok, err = CM.validate(subject)
        self.assertFalse(ok, f"expected reject for {subject!r}")
        self.assertIn("agent worktree", err)
        self.assertIn("merge: <topic>", err)

    def test_git_merge_subject_naming_agent_worktree_refused(self):
        for subj in [
            "Merge branch 'worktree-agent-a534c48ba827e37e1' - gate gaps (s117)",
            "Merge branch 'worktree-agent-ac7faeabd642c5bcb'",
            "Merge remote-tracking branch 'origin/worktree-agent-a534c48b'",
            "Merge branch 'agent-a534c48ba827e37e1' into main",
        ]:
            self._refused_with_template_hint(subj)

    def test_merge_type_subject_naming_agent_worktree_refused(self):
        for subj in [
            "merge: worktree-agent-a534c48ba827e37e1 - gate gaps",
            "merge(RM-123): agent-ac7faeab gate gaps",
            "merge(worktree-agent-ab12): gate gaps",
        ]:
            self._refused_with_template_hint(subj)

    def test_agent_shape_needs_eight_hex_or_worktree_prefix(self):
        # Short or non-hex `agent-` words are prose, not worktree names.
        self._ok("merge: agent-abc1 notes")
        self._ok("merge: subagent-deadbeefcafe prompt split")
        self._ok("merge: agent-dispatch rules")
        self._ok("Merge branch 'feature/agent-ui'")

    def test_agent_name_outside_a_merge_subject_untouched(self):
        # The rule is scoped to merge subjects (PUBREPO 1b); other types keep
        # their existing behaviour.
        self._ok("docs: note the worktree-agent-<hex> branch shape")

    def test_revert_pass_through(self):
        self._ok("Revert \"feat(arch): foo\"")

    def test_fixup_pass_through(self):
        self._ok("fixup! feat(arch): foo")

    # -- Rejections -----------------------------------------------------------

    def test_empty_subject_rejected(self):
        self._bad("")
        self._bad("   ")

    def test_no_type_prefix_rejected(self):
        self._bad("just a thing happened")
        self._bad("WIP")

    def test_missing_colon_rejected(self):
        self._bad("feat add a thing")
        self._bad("feat(scope) add a thing")

    def test_missing_description_rejected(self):
        self._bad("feat:")
        self._bad("feat:    ")
        self._bad("feat(scope):")

    def test_unknown_type_rejected(self):
        self._bad("wibble: a real description")
        self._bad("featz: typo'd type")
        self._bad("Feat: capitalized type")


class TestReadSubject(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_msgcheck_"))
        self.msg = self.tmp / "COMMIT_EDITMSG"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skips_leading_comments_and_blanks(self):
        self.msg.write_text(
            "# comment line\n"
            "\n"
            "feat(scope): real subject\n"
            "\n"
            "body line\n",
            encoding="utf-8",
        )
        self.assertEqual(CM._read_subject(self.msg), "feat(scope): real subject")

    def test_empty_file_returns_empty(self):
        self.msg.write_text("", encoding="utf-8")
        self.assertEqual(CM._read_subject(self.msg), "")

    def test_only_comments_returns_empty(self):
        self.msg.write_text("# a\n# b\n", encoding="utf-8")
        self.assertEqual(CM._read_subject(self.msg), "")


class TestMainMergeHint(unittest.TestCase):
    """The hook's stderr points a refused merge subject at the merge template."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_msgcheck_"))
        self.msg = self.tmp / "COMMIT_EDITMSG"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, text: str):
        import contextlib
        import io
        from unittest import mock
        self.msg.write_text(text, encoding="utf-8")
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["precommit_msg_check.py", str(self.msg)]):
            with contextlib.redirect_stderr(err):
                rc = CM.main()
        return rc, err.getvalue()

    def test_agent_merge_subject_exit_1_with_template_pointer(self):
        rc, err = self._run(
            "Merge branch 'worktree-agent-a534c48ba827e37e1' - gate gaps (s117)\n"
        )
        self.assertEqual(rc, 1)
        self.assertIn("merge: <topic>", err)
        self.assertIn(".github/CONTRIBUTING.md", err)
        self.assertIn("merge", CM.TYPES)

    def test_template_doc_matches_checker(self):
        # The refusal points at this doc, so the doc must carry the template,
        # the recipe and exactly the checker's type list.
        # Spelled as `.github` / basename. Before RM-763 tools/md_guard_selector.py
        # stripped the leading dot off `.github/...`, so only the basename
        # literal selected this module for docs-only CI pushes; both select now.
        doc_path = _PROJECT_ROOT / ".github" / "CONTRIBUTING.md"
        self.assertEqual(
            doc_path, _PROJECT_ROOT / CM.MERGE_TEMPLATE_DOC,
            "the hook's refusal must point at the doc this test reads",
        )
        doc = doc_path.read_text(encoding="utf-8")
        self.assertIn("**Merge template.**", doc)
        self.assertIn("`merge: <topic>`", doc)
        self.assertIn("git merge --no-ff --no-commit <branch>", doc)
        self.assertIn("git commit -F <message file>", doc)
        listed = re.search(r"Types: ((?:`\w+`,?\s*(?:and\s+)?)+)\.", doc)
        self.assertIsNotNone(listed, "type list not found in the merge template doc")
        self.assertEqual(
            tuple(re.findall(r"`(\w+)`", listed.group(1))), CM.TYPES,
        )

    def test_template_merge_subject_exit_0(self):
        rc, err = self._run(
            "merge: stop-claim gate gaps\n\nslice: worktree-agent-a534c48b (s117)\n"
        )
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
