"""Drift guard for tools/precommit_gate.py (the commit-time ruff + glyph gate).

Unit-tests the pure helpers + the staged-diff parser (via a monkeypatched _git).
End-to-end blocking is proven live by the gate's own commit + the manual matrix;
these lock the parse/detection logic that would otherwise silently drift.
Source stays ASCII: the em-dash is built with chr(0x2014), never a literal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import precommit_gate as G  # noqa: E402

_EMDASH = chr(0x2014)


class TestIsCommit:
    def test_plain_commit(self):
        assert G._is_commit('git commit -m "x"')

    def test_amend(self):
        assert G._is_commit("git commit --amend --no-edit")

    def test_chain(self):
        # secondary guard tolerates chained forms even though the hook matcher
        # Bash(git commit:*) only delivers commands that begin with `git commit`
        assert G._is_commit('git add -A && git commit -m "y"')

    def test_status_is_not_commit(self):
        assert not G._is_commit("git status")

    def test_log_with_commit_word_is_not_commit(self):
        assert not G._is_commit("git log --format=commit")

    def test_unrelated(self):
        assert not G._is_commit("py -m pytest")

    def test_dash_C_quoted_path(self):
        # The fleet's standard commit shape (PowerShell tool, repo-root -C).
        assert G._is_commit('git -C "C:\\Riot Commander" commit -m "x"')

    def test_powershell_if_chain(self):
        assert G._is_commit(
            'git -C "C:\\Riot Commander" add f.py; if ($?) { git -C "C:\\Riot Commander" commit -m "y" }'
        )

    def test_dash_C_quoted_path_push_is_not_commit(self):
        assert not G._is_commit('git -C "C:\\Riot Commander" push')


class TestStdinPayload:
    def test_bom_prefixed_payload_parses(self, monkeypatch, capsys):
        # PS 5.1 pipe artifact: BOM before the JSON. main() must still see the
        # inner command (here: a non-commit, so it exits 0 WITHOUT touching git).
        import io
        payload = ('\ufeff'
                   '{"tool_name":"PowerShell","tool_input":{"command":"Get-ChildItem"}}')
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        monkeypatch.setattr(G, "_git", lambda *a: (_ for _ in ()).throw(AssertionError("git touched on non-commit")))
        assert G.main() == 0


class TestRootFromCommand:
    def test_quoted_dash_C(self):
        assert G._root_from_command(
            'git -C "C:\\Riot Commander" commit -m "x"'
        ) == "C:\\Riot Commander"

    def test_unquoted_dash_C(self):
        assert G._root_from_command("git -C C:/wt/slice1 commit") == "C:/wt/slice1"

    def test_no_dash_C(self):
        assert G._root_from_command('git commit -m "x"') is None

    def test_chain_takes_commit_segment(self):
        # -C on the commit segment wins even when earlier segments differ.
        cmd = 'git -C "C:/main" add f; git -C "C:/wt" commit -m "y"'
        assert G._root_from_command(cmd) == "C:/wt"


class TestCompileErrors:
    def test_syntax_error_flagged(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def f(:\n", encoding="utf-8")
        out = G._compile_errors(["bad.py"], str(tmp_path))
        assert len(out) == 1 and "bad.py" in out[0]

    def test_clean_file_passes(self, tmp_path):
        ok = tmp_path / "ok.py"
        ok.write_text("x = 1\n", encoding="utf-8")
        assert G._compile_errors(["ok.py"], str(tmp_path)) == []


class TestGlyphHits:
    def test_emdash_detected(self):
        assert "em-dash" in G._glyph_hits(f"drake {_EMDASH} baron")

    def test_smart_quote(self):
        assert G._glyph_hits(chr(0x201C) + "hi" + chr(0x201D))

    def test_clean_ascii(self):
        assert G._glyph_hits("clean ascii - dash") == []


class TestSkippable:
    def test_logs_skipped(self):
        assert G._skippable("logs/2026-05-31.log")

    def test_archive_skipped(self):
        assert G._skippable("docs/_archive/x.md")

    def test_normal_not_skipped(self):
        assert not G._skippable("tools/foo.py")


class TestStagedParse:
    def _patch(self, monkeypatch, diff):
        monkeypatch.setattr(G, "_git", lambda args, root: diff)

    def test_new_file_ranges_and_glyph(self, monkeypatch):
        diff = (
            "diff --git a/tools/x.py b/tools/x.py\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/tools/x.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+import os\n"
            f'+LABEL = "a {_EMDASH} b"\n'
            "+OK = 1\n"
        )
        self._patch(monkeypatch, diff)
        staged = G._staged_added("/repo")
        assert "tools/x.py" in staged
        assert staged["tools/x.py"]["ranges"] == [(1, 3)]
        glyph_lines = [n for n, t in staged["tools/x.py"]["lines"] if G._glyph_hits(t)]
        assert glyph_lines == [2]

    def test_modified_hunk_range(self, monkeypatch):
        diff = (
            "diff --git a/core/y.py b/core/y.py\n"
            "--- a/core/y.py\n"
            "+++ b/core/y.py\n"
            "@@ -10,0 +11,2 @@ def f():\n"
            "+    a = 1\n"
            "+    b = 2\n"
        )
        self._patch(monkeypatch, diff)
        staged = G._staged_added("/repo")
        assert staged["core/y.py"]["ranges"] == [(11, 12)]

    def test_frozen_path_excluded(self, monkeypatch):
        diff = (
            "diff --git a/logs/z.log b/logs/z.log\n"
            "--- /dev/null\n"
            "+++ b/logs/z.log\n"
            "@@ -0,0 +1,1 @@\n"
            f"+noise {_EMDASH}\n"
        )
        self._patch(monkeypatch, diff)
        assert G._staged_added("/repo") == {}
