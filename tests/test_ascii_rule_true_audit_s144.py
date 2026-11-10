"""True-audit of tools/ascii_rule.py, the ONE 7-bit ASCII rule shared by the
commit gate (tools/precommit_gate.py) and the edit hook
(tools/edit_lint_check.py). S144-T-583.

Two holes, both measured failing on the pre-fix tree:

1. LINE SPLITTING. `line_hits` used `str.splitlines()`, which treats U+0085,
   U+2028 and U+2029 (and the ASCII controls \\x0b \\x0c \\x1c-\\x1e) as line
   breaks. A separator glyph was CONSUMED as a break and never reported, so a
   snippet whose only non-ASCII codepoint was U+2028 passed the edit hook; the
   commit gate split the staged diff, the commit message and --scan-files
   text the same way, so the glyph passed every arm. The ASCII controls also
   shifted line numbers off the edit hook's own count of "\\n". Git counts a
   line by "\\n" only; the rule now does too (`split_lines`).

2. EXEMPTION MATCHING. `is_exempt` matched EXEMPT_PARTS as raw substrings,
   so "logs/" exempted any directory whose NAME ends in "logs" (catalogs/,
   dialogs/, changelogs/) and "docs/_archive/" exempted "mydocs/_archive/".
   A "data/../tools/x.py" path was exempt through the "data/" prefix. Parts
   now match whole path components on a normalised path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tools import ascii_rule as R

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import precommit_gate as G  # noqa: E402

LS = chr(0x2028)
PS = chr(0x2029)
NEL = chr(0x0085)
TIMES = chr(0x00D7)
SEPARATORS = (LS, PS, NEL)


# ---------------------------------------------------------------------------
# 1. line splitting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sep", SEPARATORS)
def test_line_hits_reports_a_unicode_line_separator(sep):
    found = R.line_hits("a" + sep + "b\n")
    assert found == [(1, [f"non-ascii U+{ord(sep):04X} ({sep.encode('unicode_escape').decode()})"])]


@pytest.mark.parametrize("sep", SEPARATORS)
def test_line_hits_agrees_with_hits_on_every_separator(sep):
    text = "x = 1" + sep + "y = 2\n"
    names = sorted({h for _n, hs in R.line_hits(text) for h in hs})
    assert names == R.hits(text) != []


@pytest.mark.parametrize("ctrl", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e"])
def test_line_numbers_count_newlines_only(ctrl):
    """The edit hook adds line_hits' number to its own count of "\\n"."""
    text = "a" + ctrl + "b\nc " + TIMES + "\n"
    assert R.line_hits(text) == [(2, R.hits(TIMES))]


def test_crlf_text_numbers_like_lf_text():
    assert R.line_hits("a\r\nb " + TIMES + "\r\n") == [(2, R.hits(TIMES))]
    assert R.line_hits("a\nb " + TIMES + "\n") == [(2, R.hits(TIMES))]


@pytest.mark.parametrize("text", [
    "", "a", "a\n", "a\nb", "a\nb\n", "a\r\nb\r\n", "\n", "\n\n", "a\n\nb\n",
])
def test_split_lines_matches_splitlines_on_plain_line_endings(text):
    assert R.split_lines(text) == text.splitlines()


def test_split_lines_keeps_separators_inside_the_line():
    assert R.split_lines("a" + LS + "b\nc\x0cd\n") == ["a" + LS + "b", "c\x0cd"]
    assert R.split_lines("a\rb\n") == ["a\rb"], "git does not break on a lone CR"


# ---------------------------------------------------------------------------
# 1b. the commit gate reads lines through the same split
# ---------------------------------------------------------------------------


def test_gate_staged_diff_keeps_a_separator_on_its_added_line(monkeypatch):
    diff = "+++ b/x.py\n@@ -0,0 +1,2 @@\n+a" + LS + "b\n+c\n"
    monkeypatch.setattr(G, "_git", lambda args, root: diff)
    files = G._staged_added(".")
    assert files["x.py"]["lines"] == [(1, "a" + LS + "b"), (2, "c")]
    assert G._glyph_hits(files["x.py"]["lines"][0][1], "x.py")


def test_gate_message_file_blocks_a_separator(tmp_path, capsys):
    msg = tmp_path / "MSG"
    msg.write_bytes(("fix: thing" + LS + "more\n# comment\n").encode("utf-8"))
    assert G.main(["precommit_gate.py", "--message-file", str(msg)]) != 0
    cap = capsys.readouterr()
    assert "U+2028" in cap.out + cap.err


def test_gate_message_file_still_drops_template_comments(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_bytes(("fix: thing\n# " + TIMES + " comment\n").encode("utf-8"))
    assert G.main(["precommit_gate.py", "--message-file", str(msg)]) == 0


def test_gate_scan_files_blocks_a_separator(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.md").write_bytes(("one\ntwo" + PS + "three\n").encode("utf-8"))
    assert G.main(["precommit_gate.py", "--scan-files", "a.md"]) == 1
    assert "a.md:2: non-ascii U+2029" in capsys.readouterr().err


def test_edit_hook_reports_a_separator_in_written_text(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "edit_lint_check_s144t583", REPO_ROOT / "tools" / "edit_lint_check.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    target = tmp_path / "note.md"
    body = "line one\nline" + LS + "two\n"
    target.write_bytes(body.encode("utf-8"))
    finding = hook._ascii_finding(target, [body])
    assert finding is not None and "U+2028" in finding and "line 2" in finding


# ---------------------------------------------------------------------------
# 2. exemption matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "web/js/dialogs/panel.js",
    "tools/catalogs/build.py",
    "docs/changelogs/2026.md",
    "mydocs/_archive/x.md",
    "src/not__pycache__/x.py",
    "tools/x.git/y.py",
    "data/../tools/x.py",
    "metadata/x.json",
    "logs.py",
])
def test_substring_lookalikes_are_not_exempt(path):
    assert R.is_exempt(path) is False
    assert R.hits("a " + TIMES, path) != []
    assert R.line_hits("a " + TIMES, path) != []


@pytest.mark.parametrize("path", [
    "logs/2026-10-01.log",
    "logs/sub/x.txt",
    "ops/logs/x.txt",
    "docs/_archive/2026-10/note.md",
    "a/__pycache__/b.py",
    ".git/HEAD",
    "data/items.json",
    "./data/items.json",
    "tools/../data/items.json",
    "data\\items.json",
    "docs/history_notes.md",
    "docs/LEDGER.md",
    "./docs/LEDGER.md",
    "x/y.jsonl",
    "x/y.png",
])
def test_real_exempt_surfaces_stay_exempt(path):
    assert R.is_exempt(path) is True
    assert R.hits("a " + TIMES, path) == []


def test_is_exempt_accepts_a_pathlike():
    assert R.is_exempt(Path("data") / "items.json") is True
    assert R.is_exempt(Path("tools") / "x.py") is False


@pytest.mark.parametrize("path", ["", None])
def test_no_path_is_not_exempt(path):
    assert R.is_exempt(path) is False


@pytest.mark.parametrize("bad", [b"bytes", None, 5, ["a"]])
def test_non_str_text_is_a_type_error(bad):
    with pytest.raises(TypeError):
        R.hits(bad)
    with pytest.raises(TypeError):
        R.line_hits(bad)


def test_rule_file_stays_ascii_and_lf():
    src = (REPO_ROOT / "tools" / "ascii_rule.py").read_bytes()
    assert all(b < 128 for b in src) and b"\r" not in src
    assert Path(R.__file__).name == "ascii_rule.py"
