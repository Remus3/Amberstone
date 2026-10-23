"""Drift guard for tools/precommit_gate.py (the commit-time ruff + glyph gate).

Unit-tests the pure helpers + the staged-diff parser (via a monkeypatched _git).
End-to-end blocking is proven live by the gate's own commit + the manual matrix;
these lock the parse/detection logic that would otherwise silently drift.
Source stays ASCII: the em-dash is built with chr(0x2014), never a literal.
"""

import ast
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import precommit_gate as G  # noqa: E402

# G's own `subprocess` name only, never the shared module (RM-801).
from tests._module_view import bind_subprocess  # noqa: E402

_EMDASH = chr(0x2014)


class TestIsCommit:
    def test_plain_commit(self):
        assert G._is_commit('git commit -m "x"')

    def test_amend(self):
        assert G._is_commit("git commit --amend --no-edit")

    def test_chain(self):
        # The hook matcher is Bash|PowerShell (MAIN FIX 1254 #4), so EVERY
        # shell command arrives here and _is_commit is the only filter.
        assert G._is_commit('git add -A && git commit -m "y"')

    def test_status_is_not_commit(self):
        assert not G._is_commit("git status")

    def test_log_with_commit_word_is_not_commit(self):
        assert not G._is_commit("git log --format=commit")

    def test_unrelated(self):
        assert not G._is_commit("py -m pytest")

    def test_dash_C_quoted_path(self):
        # The fleet's standard commit shape (PowerShell tool, repo-root -C).
        assert G._is_commit('git -C "C:\\Example Repo" commit -m "x"')

    def test_powershell_if_chain(self):
        assert G._is_commit(
            'git -C "C:\\Example Repo" add f.py; if ($?) { git -C "C:\\Example Repo" commit -m "y" }'
        )

    def test_dash_C_quoted_path_push_is_not_commit(self):
        assert not G._is_commit('git -C "C:\\Example Repo" push')


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
            'git -C "C:\\Example Repo" commit -m "x"'
        ) == "C:\\Example Repo"

    def test_unquoted_dash_C(self):
        assert G._root_from_command("git -C C:/wt/slice1 commit") == "C:/wt/slice1"

    def test_no_dash_C(self):
        assert G._root_from_command('git commit -m "x"') is None

    def test_chain_takes_commit_segment(self):
        # -C on the commit segment wins even when earlier segments differ.
        cmd = 'git -C "C:/repo" add f; git -C "C:/wt" commit -m "y"'
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

    def test_writes_no_bytecode_and_names_the_line(self, tmp_path, monkeypatch):
        # Sibling of MAIN FIX 1254 #12: py_compile left __pycache__/ beside
        # every staged file, and its first message line was the File header.
        monkeypatch.setattr(sys, "pycache_prefix", None)
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "bad.py").write_text("x = 1\ndef f(:\n", encoding="utf-8")
        out = G._compile_errors(["ok.py", "bad.py"], str(tmp_path))
        assert len(out) == 1 and "bad.py:2" in out[0] and "SyntaxError" in out[0]
        assert not (tmp_path / "__pycache__").exists()


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


def _path_of(n: int) -> str:
    """A repo-relative path of exactly n chars, under docs/_archive/ on purpose:
    that is where the 131-char copy landed (9e5386aa1), and it is a surface the
    content arms skip - the path arm must not."""
    prefix, suffix = "docs/_archive/2026-10/", ".md"
    path = prefix + "x" * (n - len(prefix) - len(suffix)) + suffix
    assert len(path) == n
    return path


class TestStagedPathLength:
    """RM-422 at commit time: a NEW tracked path over the cap is refused.

    tests/test_tracked_path_length_rm422.py only runs in a whole suite, so a
    131-char path rode in on 9e5386aa1 and sat there until 2497e857b.
    """

    CAP = G.MAX_TRACKED_PATH_CHARS

    def _drive(self, monkeypatch, tmp_path, name_status: str) -> int:
        monkeypatch.chdir(tmp_path)
        seen: list[list[str]] = []

        def fake_git(args, root):
            seen.append(list(args))
            return name_status if "--name-status" in args else ""

        monkeypatch.setattr(G, "_git", fake_git)
        monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
        rc = G.main()
        assert any("--name-status" in a and "-z" in a and "--cached" in a for a in seen), seen
        return rc

    def test_new_path_over_cap_is_refused_naming_path_and_length(self, monkeypatch, tmp_path, capsys):
        long = _path_of(self.CAP + 1)
        assert self._drive(monkeypatch, tmp_path, f"A\0{long}\0") == 2
        err = capsys.readouterr().err
        assert long in err
        assert f"{self.CAP + 1} chars" in err
        assert str(self.CAP) in err

    def test_path_at_exactly_the_cap_passes(self, monkeypatch, tmp_path, capsys):
        assert self._drive(monkeypatch, tmp_path, f"A\0{_path_of(self.CAP)}\0") == 0
        assert capsys.readouterr().err == ""

    def test_rename_onto_an_over_long_path_is_refused(self, monkeypatch, tmp_path, capsys):
        long = _path_of(self.CAP + 2)
        assert self._drive(monkeypatch, tmp_path, f"R100\0docs/short.md\0{long}\0") == 2
        err = capsys.readouterr().err
        assert long in err and "docs/short.md" not in err

    def test_copy_onto_an_over_long_path_is_refused(self, monkeypatch, tmp_path, capsys):
        long = _path_of(self.CAP + 1)
        assert self._drive(monkeypatch, tmp_path, f"C075\0docs/short.md\0{long}\0") == 2
        assert long in capsys.readouterr().err

    def test_deleting_an_over_long_path_is_allowed(self, monkeypatch, tmp_path):
        # The cure for an over-long path is to remove or rename it; the gate
        # must never block that.
        assert self._drive(monkeypatch, tmp_path, f"D\0{_path_of(self.CAP + 5)}\0") == 0

    def test_parser_keeps_only_added_copied_and_rename_targets(self, monkeypatch):
        out = "M\0a.py\0R087\0old.md\0new.md\0A\0b.txt\0D\0gone.txt\0C100\0src.md\0dup.md\0"
        monkeypatch.setattr(G, "_git", lambda args, root: out)
        assert G._staged_new_paths("/repo") == ["new.md", "b.txt", "dup.md"]

    def test_parser_ignores_non_name_status_output(self, monkeypatch):
        # Other harnesses fake _git with one unified diff for every call; that
        # must parse to nothing rather than raise.
        diff = "diff --git a/x b/x\n--- /dev/null\n+++ b/x\n@@ -0,0 +1 @@\n+y\n"
        monkeypatch.setattr(G, "_git", lambda args, root: diff)
        assert G._staged_new_paths("/repo") == []


# ---------------------------------------------------------------------------
# MAIN FIX 2026-10-21 1254 items #4 (code side), #10, #11, #13, #14.
# ---------------------------------------------------------------------------


class _Proc:
    def __init__(self, stdout="[]", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _one_staged_py(monkeypatch, tmp_path, line="x = 1"):
    """main() past every arm up to ruff, on one staged clean .py file."""
    (tmp_path / "x.py").write_text(line + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(G, "_staged_added", lambda root: {
        "x.py": {"ranges": [(1, 1)], "lines": [(1, line)]}})
    monkeypatch.setattr(G, "_staged_new_paths", lambda root: [])
    monkeypatch.setattr(G, "_root_from_command", lambda c: str(tmp_path))
    monkeypatch.setattr(G, "_resolve_ruff", lambda: ["ruff"])
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))


class TestRuffCallIsGuarded:
    """#10: the ruff run in main() was not guarded against TimeoutExpired."""

    def test_ruff_call_is_cacheless_and_windowless(self, monkeypatch, tmp_path):
        """#11: no .ruff_cache/ left in the repo root or cwd."""
        _one_staged_py(monkeypatch, tmp_path)
        calls = []

        def fake(argv, **kw):
            calls.append((list(argv), kw))
            return _Proc()

        bind_subprocess(monkeypatch, G, run=fake)
        assert G.main() == 0
        checks = [(a, kw) for a, kw in calls if "check" in a]
        assert checks, calls
        argv, kw = checks[0]
        assert "--no-cache" in argv and "--fix" not in argv
        assert "creationflags" in kw


class TestFailureModesPerChannel:
    """#10 as RULED (C1b-3 S4 rework, 2026-10-22): fail-open is for the Claude
    PreToolUse stdin-JSON channel ONLY. The git-hook modes (pre-commit,
    commit-msg) and the CI sweep (--scan-files) FAIL CLOSED: non-zero, one
    stderr line naming the cause. A MAIN note lifts no safety floor (FLEET
    item 6) and the git hooks are the AUTHORITATIVE gate (CLAUDE.md).

    Injections: crash = _glyph_hits raises (every mode reaches it); ruff
    timeout / spawn error = the check call raises; missing rule =
    tools/ascii_rule.py absent; MemoryError / RecursionError = a real
    too-deeply-nested staged .py. commit-msg and --scan-files never run ruff
    or compile(), so those two cells do not exist for them.
    """

    GIT_MODES = ("pre-commit", "commit-msg", "scan-files")
    STAGED_MODES = ("pre-commit", "claude")
    DEEP = {"MemoryError": "x = " + "-" * 200000 + "1\n",
            "RecursionError": "x = " + "1+" * 200000 + "1\n"}

    def _argv(self, mode, tmp_path, monkeypatch, text="clean ascii line"):
        f = tmp_path / "subject.txt"
        f.write_text(text + "\n", encoding="utf-8")
        if mode == "commit-msg":
            return ["precommit_gate.py", "--message-file", str(f)]
        if mode == "scan-files":
            monkeypatch.chdir(tmp_path)
            return ["precommit_gate.py", "--scan-files", "subject.txt"]
        stdin = ("git commit" if mode == "pre-commit" else json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "x"'}}))
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return ["precommit_gate.py"]

    def _stage(self, monkeypatch, tmp_path, source="x = 1\n", ruff=None):
        (tmp_path / "x.py").write_text(source, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(G, "_staged_added", lambda root: {
            "x.py": {"ranges": [(1, 1)], "lines": [(1, source.rstrip("\n"))]}})
        monkeypatch.setattr(G, "_staged_new_paths", lambda root: [])
        monkeypatch.setattr(G, "_root_from_command", lambda c: str(tmp_path))
        monkeypatch.setattr(G, "_resolve_ruff", lambda: ruff)

    @staticmethod
    def _closed(rc, capsys, *needles):
        cap = capsys.readouterr()
        assert rc != 0, f"fail-closed mode passed: {cap.err!r}"
        lines = [ln for ln in cap.err.splitlines() if ln.strip()]
        assert lines, "a refusal must say why"
        assert all(n in cap.err for n in needles), (needles, cap.err)
        return cap.err

    @staticmethod
    def _open_with_context(rc, capsys, *needles):
        cap = capsys.readouterr()
        assert rc == 0, cap.err
        lines = cap.out.splitlines()
        assert len(lines) == 1, f"ONE additionalContext line expected: {cap.out!r}"
        hso = json.loads(lines[0])["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        ctx = hso["additionalContext"]
        assert "\n" not in ctx and all(n in ctx for n in needles), ctx
        return ctx

    # ---- injected crash -------------------------------------------------

    @pytest.mark.parametrize("mode", GIT_MODES)
    def test_crash_fails_closed_in_git_and_ci_modes(self, mode, monkeypatch, tmp_path, capsys):
        argv = self._argv(mode, tmp_path, monkeypatch)
        if mode == "pre-commit":
            self._stage(monkeypatch, tmp_path)

        def boom(*a, **k):
            raise RuntimeError("synthetic gate fault")

        monkeypatch.setattr(G, "_glyph_hits", boom)
        err = self._closed(G.safe_main(argv), capsys, "RuntimeError")
        assert "synthetic gate fault" not in err, "type name only, never the text"
        assert len([ln for ln in err.splitlines() if ln.strip()]) == 1

    def test_crash_fails_open_on_the_claude_channel(self, monkeypatch, tmp_path, capsys):
        argv = self._argv("claude", tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path)

        def boom(*a, **k):
            raise RuntimeError("synthetic gate fault")

        monkeypatch.setattr(G, "_glyph_hits", boom)
        ctx = self._open_with_context(G.safe_main(argv), capsys, "RuntimeError")
        assert "synthetic gate fault" not in ctx

    def test_script_entry_point_runs_through_safe_main(self):
        tree = ast.parse(Path(G.__file__).read_text(encoding="utf-8"))
        guard = [n for n in tree.body if isinstance(n, ast.If)
                 and "__main__" in ast.unparse(n.test)]
        assert guard and "safe_main(" in ast.unparse(guard[0])

    # ---- ruff timeout / spawn error -------------------------------------

    @pytest.mark.parametrize("exc", ["TimeoutExpired", "OSError"])
    def test_ruff_failure_blocks_in_pre_commit_mode(self, exc, monkeypatch, tmp_path, capsys):
        argv = self._argv("pre-commit", tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path, ruff=["ruff"])

        def fail(cmd, **kw):
            if exc == "OSError":
                raise OSError("vanished")
            raise G.subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))

        bind_subprocess(monkeypatch, G, run=fail)
        self._closed(G.safe_main(argv), capsys, "ruff timed out / not runnable",
                     "fix or rerun")

    def test_ruff_timeout_passes_with_context_on_the_claude_channel(self, monkeypatch,
                                                                    tmp_path, capsys):
        argv = self._argv("claude", tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path, ruff=["ruff"])

        def hang(cmd, **kw):
            raise G.subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))

        bind_subprocess(monkeypatch, G, run=hang)
        self._open_with_context(G.safe_main(argv), capsys, "ruff")

    # ---- missing / unimportable tools/ascii_rule.py ----------------------

    def _lose_the_rule(self, monkeypatch, tmp_path):
        monkeypatch.setattr(G, "_RULE", None)
        monkeypatch.setattr(G, "_RULE_PATH", tmp_path / "absent" / "ascii_rule.py")

    @pytest.mark.parametrize("mode", GIT_MODES)
    def test_missing_rule_fails_closed_in_git_and_ci_modes(self, mode, monkeypatch,
                                                          tmp_path, capsys):
        argv = self._argv(mode, tmp_path, monkeypatch, text="a " + _EMDASH + " b")
        if mode == "pre-commit":
            self._stage(monkeypatch, tmp_path, source="y = 1  # a " + _EMDASH + " b\n")
        self._lose_the_rule(monkeypatch, tmp_path)
        self._closed(G.safe_main(argv), capsys, "ImportError")

    @pytest.mark.parametrize("mode", GIT_MODES)
    def test_missing_rule_blocks_even_an_all_ascii_change(self, mode, monkeypatch,
                                                         tmp_path, capsys):
        """No degrade-to-pass: a gate that cannot load its rule checks nothing."""
        argv = self._argv(mode, tmp_path, monkeypatch)
        if mode == "pre-commit":
            self._stage(monkeypatch, tmp_path)
        self._lose_the_rule(monkeypatch, tmp_path)
        self._closed(G.safe_main(argv), capsys, "ImportError")

    def test_unimportable_rule_fails_closed(self, monkeypatch, tmp_path, capsys):
        broken = tmp_path / "ascii_rule.py"
        broken.write_text("raise RuntimeError('rule module is broken')\n", encoding="utf-8")
        argv = self._argv("pre-commit", tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path)
        monkeypatch.setattr(G, "_RULE", None)
        monkeypatch.setattr(G, "_RULE_PATH", broken)
        self._closed(G.safe_main(argv), capsys, "RuntimeError")

    def test_missing_rule_fails_open_on_the_claude_channel(self, monkeypatch, tmp_path, capsys):
        argv = self._argv("claude", tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path)
        self._lose_the_rule(monkeypatch, tmp_path)
        self._open_with_context(G.safe_main(argv), capsys, "ImportError")

    def test_missing_rule_costs_nothing_off_the_commit_path(self, monkeypatch, tmp_path,
                                                          capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}})))
        self._lose_the_rule(monkeypatch, tmp_path)
        assert G.safe_main(["precommit_gate.py"]) == 0
        cap = capsys.readouterr()
        assert cap.out == "" and cap.err == ""

    # ---- MemoryError / RecursionError from compile() ---------------------

    @pytest.mark.parametrize("mode", STAGED_MODES)
    @pytest.mark.parametrize("kind", sorted(DEEP))
    def test_too_deep_to_compile_is_a_finding(self, kind, mode, monkeypatch, tmp_path, capsys):
        """A real nested source: compile() raises MemoryError / RecursionError.
        It is a finding (exit 2, named) on BOTH channels, never a crash."""
        argv = self._argv(mode, tmp_path, monkeypatch)
        self._stage(monkeypatch, tmp_path, source=self.DEEP[kind])
        rc = G.safe_main(argv)
        err = capsys.readouterr().err
        assert rc == 2, err
        assert "x.py" in err and kind in err and "BLOCKED" in err

    def test_compile_errors_reports_both_deep_kinds(self, tmp_path):
        for kind, src in self.DEEP.items():
            (tmp_path / f"{kind}.py").write_text(src, encoding="utf-8")
            out = G._compile_errors([f"{kind}.py"], str(tmp_path))
            assert len(out) == 1 and kind in out[0], out


class TestRepoConfigBlock:
    """#10: RC-specific lists live in ONE config block, not scattered."""

    NAMES = ("_CANONICAL_PY", "_FROZEN_SKIP", "MAX_TRACKED_PATH_CHARS",
             "_ATOMIC_SCOPE_PREFIXES", "_ATOMIC_SCOPE_FILES",
             "_ATOMIC_EXEMPT_PREFIXES", "_ATOMIC_EXEMPT_PARTS",
             "_ATOMIC_EXEMPT_BASENAME_PREFIXES", "_ATOMIC_EXEMPT_BASENAMES",
             "RUFF_TIMEOUT_S")

    def test_every_rc_list_is_assigned_inside_the_block(self):
        src = Path(G.__file__).read_text(encoding="utf-8")
        lines = src.splitlines()
        start = [i for i, ln in enumerate(lines, 1) if "BEGIN REPO CONFIG" in ln]
        end = [i for i, ln in enumerate(lines, 1) if "END REPO CONFIG" in ln]
        assert len(start) == 1 and len(end) == 1 and start[0] < end[0]
        where = {}
        for node in ast.parse(src).body:
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, ast.AnnAssign) else [])
            for t in targets:
                if isinstance(t, ast.Name):
                    where.setdefault(t.id, []).append(node.lineno)
        for name in self.NAMES:
            assert name in where, f"{name} is not assigned at module level"
            for ln in where[name]:
                assert start[0] < ln < end[0], f"{name} assigned outside the block at {ln}"


class TestSharedAsciiRuleAndHint:
    def test_glyph_hits_is_the_shared_rule(self):
        """#13: one reading of the 7-bit rule for the edit hook and this gate."""
        sys.path.insert(0, str(Path(G.__file__).resolve().parents[1]))
        from tools import ascii_rule
        for text, path in ((f"a {_EMDASH} b", "x.py"), ("v " + chr(0xD7), "data/a.json"),
                           ("n " + chr(0xD7), "docs/LEDGER.md"), ("ok", "x.py")):
            assert G._glyph_hits(text, path) == ascii_rule.hits(text, path)
        assert G._ascii_exempt("data/x.json") is ascii_rule.is_exempt("data/x.json")

    def test_block_message_names_strip_tools_as_optional(self, monkeypatch, tmp_path, capsys):
        """#14: helpers are documented as optional, never as dependencies."""
        diff = ("+++ b/docs/n.md\n@@ -0,0 +1,1 @@\n"
                f"+a {_EMDASH} b\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(G, "_git", lambda args, root: "" if "--name-status" in args else diff)
        monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
        assert G.main() == 2
        err = capsys.readouterr().err
        assert "optional" in err.lower() and "strip_em_dashes.py" in err


def test_docstring_names_the_bash_or_powershell_matcher():
    """#4 code side: settings use matcher Bash|PowerShell; the gate self-filters."""
    assert "Bash|PowerShell" in G.__doc__
    assert "matcher Bash(git commit:*)" not in G.__doc__
