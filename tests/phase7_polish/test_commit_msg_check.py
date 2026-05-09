"""
tests/phase7_polish/test_commit_msg_check.py
Phase 7 — Conventional Commits validator.

Verifies the validator accepts every shape recently in `git log` and rejects
the common malformed cases.
"""
import importlib.util
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

    # ── Real-shapes from `git log` ────────────────────────────────────────────

    def test_recent_commits_accepted(self):
        for subj in [
            "feat(arch): Phase 7 — normalize phase-marker comments + auto-index",
            "docs: sync living docs — Phase 7 phase-markers (s141)",
            "feat(vision): Phase 2.4 — split moon_vision_server.py into package",
            "feat(coaching): Phase 2.3 — split coach_integration.py into package",
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

    # ── Auto-generated subjects (skipped, not parsed) ────────────────────────

    def test_merge_commits_pass_through(self):
        self._ok("Merge branch 'main' into feature/x")

    def test_revert_pass_through(self):
        self._ok("Revert \"feat(arch): foo\"")

    def test_fixup_pass_through(self):
        self._ok("fixup! feat(arch): foo")

    # ── Rejections ───────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    unittest.main()
