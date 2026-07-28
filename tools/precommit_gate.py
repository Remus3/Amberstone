#!/usr/bin/env python3
"""PreToolUse gate on `git commit`: block NET-NEW ruff errors + banned glyphs.

Wired in .claude/settings.json under PreToolUse matcher Bash(git commit:*).
Reads the Claude Code hook payload on stdin (tool_name / tool_input.command).

Self-gates: if the command is not a `git commit`, exits 0 before touching git
(so it is a no-op on every other Bash call - zero overhead off the commit path).

On a commit it inspects ONLY staged content of staged files (diff-filter ACM):
  1. ruff check (no --fix) on staged .py, keeping findings whose row lands in an
     ADDED line range of that file (net-new only - pre-existing repo debt in an
     untouched region never blocks, so an unattended headless run cannot wedge
     on unrelated errors).
  2. banned-glyph byte scan (U+2014/2013/201C/201D/2018/2019) on ADDED (+) lines
     only, plus the commit-message text in the command string itself.

Exit 2 (block) with a terse stderr report on any violation; exit 0 otherwise.
Mirrors tools/edit_lint_check.py's banned set + frozen-skip; that hook is
edit-time + advisory, this one is commit-time + blocking on net-new only.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

# Hooks run under windowless pythonw.exe; a console-subsystem child (git /
# `py` launcher + ruff) would otherwise get a fresh console allocated - an
# on-screen + taskbar flash. CREATE_NO_WINDOW suppresses it (Windows-only;
# 0 elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_BANNED = {
    chr(0x2014): "em-dash",
    chr(0x2013): "en-dash",
    chr(0x201C): "smart-dquote-open",
    chr(0x201D): "smart-dquote-close",
    chr(0x2018): "smart-quote-open",
    chr(0x2019): "smart-quote-close",
}
_FROZEN_SKIP = ("logs/", "docs/_archive/", ".pyc", ".git/", "__pycache__/")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _is_commit(command: str) -> bool:
    s = command.strip()
    # tolerate leading env assignments, `&&`/`;` chains, PowerShell `{` blocks,
    # and global flags with quoted args (git -C "C:\path" commit).
    return bool(re.search(
        r"(^|[;&|{(]\s*)git\s+(?:(?:-\S+|\"[^\"]*\"|'[^']*')\s+)*commit\b", s
    ))


def _skippable(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(s in p for s in _FROZEN_SKIP)


def _git(args: list[str], root: str | None) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root or None, capture_output=True, text=True,
            timeout=20, creationflags=_NO_WINDOW,
        )
        return out.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


_DASH_C = re.compile(r"git\s+-C\s+(\"([^\"]+)\"|'([^']+)'|(\S+))")


def _root_from_command(command: str) -> str | None:
    """Repo dir from `git -C <path> ... commit`, preferring the segment that
    carries the commit (worktree agents commit via -C into their own tree -
    resolving the hook's CWD would gate the WRONG repo's staged diff)."""
    root = None
    for m in _DASH_C.finditer(command):
        path = m.group(2) or m.group(3) or m.group(4)
        tail = command[m.end():]
        if re.match(r"\s+(?:(?:-\S+|\"[^\"]*\"|'[^']*')\s+)*commit\b", tail):
            return path
        root = root or path
    return root


def _staged_added(root: str) -> dict[str, dict]:
    """Return {path: {"ranges": [(start,end)...], "lines": [(lineno,text)...]}}."""
    diff = _git(["diff", "--cached", "--unified=0", "--no-color"], root)
    files: dict[str, dict] = {}
    cur: str | None = None
    lineno = 0
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = None if p == "/dev/null" else p[2:] if p.startswith("b/") else p
            if cur and not _skippable(cur):
                files.setdefault(cur, {"ranges": [], "lines": []})
            else:
                cur = None
            continue
        if ln.startswith("@@"):
            m = _HUNK.match(ln)
            if m and cur:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                lineno = start
                if count:
                    files[cur]["ranges"].append((start, start + count - 1))
            continue
        if cur and ln.startswith("+") and not ln.startswith("+++"):
            files[cur]["lines"].append((lineno, ln[1:]))
            lineno += 1
    return files


# Surfaces CLAUDE.md's retroactive purge deliberately did NOT sweep (immutable
# history / non-source), plus upstream DATA mirrors. DDragon and Meraki ship
# champion and item names RC does not author and cannot fix - gating them would
# block correct commits, and a gate that blocks correct work is one people learn
# to bypass.
_ASCII_EXEMPT_PARTS = ("logs/", "docs/_archive/", "__pycache__/", ".git/")
_ASCII_EXEMPT_SUFFIXES = (".jsonl", ".log", ".pyc", ".png", ".jpg", ".ico", ".zip")
_ASCII_EXEMPT_PREFIXES = ("data/",)


def _ascii_exempt(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    if any(part in p for part in _ASCII_EXEMPT_PARTS):
        return True
    if p.endswith(_ASCII_EXEMPT_SUFFIXES):
        return True
    return p.startswith(_ASCII_EXEMPT_PREFIXES)


def _glyph_hits(text: str, path: str = "") -> list[str]:
    """Named diagnostics for the six historical glyphs, then a CATCH-ALL.

    WIDENED 2026-07-28. ``_BANNED`` held exactly six characters, so every other
    non-ASCII codepoint passed this gate unremarked. That is how U+00D7 reached
    the repo the same day: ``scripts/db_size_monitor.py`` used it as a
    missing-file marker, its output is captured verbatim into the COMMITTED
    weekly agent6 health report, and ``tests/test_smart_quote_hygiene.py``
    asserts that report is byte-ASCII - so a scheduled task turned the suite red
    through a gate working exactly as written.

    The real defect was that two rules enforcing the same CLAUDE.md hard rule
    ("7-bit ASCII authored content") disagreed about what it means, and the
    looser one ran first. The catch-all closes that, and reports the codepoint
    so the hit is actionable rather than just refused.
    """
    if _ascii_exempt(path):
        # Exempt surfaces are exempt from ALL of it, the six included. A
        # DDragon champion name like Cho'Gath carries U+2019 upstream; RC did
        # not author it and cannot fix it, so flagging it would block a correct
        # mirror refresh. The authored-content rule does not reach these.
        return []
    hits = {name for ch, name in _BANNED.items() if ch in text}
    hits |= {
        "non-ascii U+%04X (%s)" % (ord(c), c.encode("unicode_escape").decode())
        for c in text
        if ord(c) > 127 and c not in _BANNED
    }
    return sorted(hits)


def _compile_errors(pyfiles: list[str], root: str) -> list[str]:
    """py_compile each staged .py; a syntax error crashes silently under
    pythonw.exe at runtime (CLAUDE.md hard rule), so block it at commit."""
    import py_compile

    out: list[str] = []
    for rel in pyfiles:
        path = os.path.join(root, rel)
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as exc:
            out.append(f"  {rel}  py_compile: {exc.msg.splitlines()[0][:160]}")
        except OSError:
            pass
    return out


def _check_message_file(path: str) -> int:
    """commit-msg entry point: scan the prepared commit message for glyphs.

    WHY THIS EXISTS SEPARATELY FROM THE STDIN PATH
    ----------------------------------------------
    As a Claude PreToolUse hook this gate receives the whole command string, so
    the ``-m "..."`` text is scanned for free. As a GIT hook it does not:
    ``pre-commit`` runs BEFORE the message is prepared, so
    ``.git/COMMIT_EDITMSG`` does not exist yet and there is nothing to read. The
    message check therefore has to live in ``commit-msg``, which is handed the
    message file as ``$1``.

    Missing that distinction is a silent failure, not a loud one: the
    staged-content and ruff halves still fire from pre-commit, so the gate looks
    healthy while the message half checks nothing. Measured 2026-07-26 - a commit
    whose subject carried a U+2014 em-dash landed clean.

    FAILS OPEN on an unreadable file. A gate that crashes on its own bug would
    wedge every commit in the repo, which is worse than the drift it guards.
    """
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    # Drop git's own template comments - they are stripped before the commit is
    # created, so a glyph inside one is not a glyph in the message.
    body = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )
    hits = _glyph_hits(body)
    if not hits:
        return 0
    print(
        "precommit_gate BLOCKED commit - banned glyph in the commit message:\n"
        f"  {', '.join(hits)}\n\n"
        "Rewrite the message in 7-bit ASCII (spaced hyphen ' - ' for a clause "
        "break) and re-commit."
    )
    return 2


def main() -> int:
    # commit-msg mode. Explicit flag rather than sniffing argv, so the hook's
    # intent is readable in the hook body itself.
    if len(sys.argv) >= 3 and sys.argv[1] == "--message-file":
        return _check_message_file(sys.argv[2])

    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    # PowerShell 5.1 pipes prepend a UTF-8 BOM; json.loads rejects it and the
    # raw-string fallback then never regex-matches -> silent pass. Strip it.
    raw = raw.lstrip("\ufeff").strip()
    command = ""
    try:
        command = (json.loads(raw).get("tool_input") or {}).get("command", "")
    except (ValueError, AttributeError):
        command = raw
    if not _is_commit(command):
        return 0

    root = (
        _root_from_command(command)
        or _git(["rev-parse", "--show-toplevel"], os.getcwd()).strip()
        or os.getcwd()
    )
    staged = _staged_added(root)
    violations: list[str] = []

    # 1. banned glyphs on added lines
    for path, info in staged.items():
        for lineno, text in info["lines"]:
            hits = _glyph_hits(text, path)
            if hits:
                violations.append(f"  {path}:{lineno}  banned glyph: {', '.join(hits)}")

    # 2. commit-message glyphs (the -m text lives in the command string)
    msg_hits = _glyph_hits(command, "<commit-message>")
    if msg_hits:
        violations.append(f"  commit message  banned glyph: {', '.join(msg_hits)}")

    # 3. net-new ruff errors on staged .py
    pyfiles = [
        p for p in staged if p.endswith(".py") and os.path.isfile(os.path.join(root, p))
    ]
    violations.extend(_compile_errors(pyfiles, root))
    if pyfiles:
        # Use the `py` launcher (not sys.executable): under the hook the running
        # interpreter is a bare pythoncore build with no ruff installed; the
        # launcher resolves the project Python that has ruff (mirrors edit_lint_check.py).
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--output-format=json", *pyfiles],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_NO_WINDOW,
        )
        try:
            findings = json.loads(proc.stdout) if proc.stdout.strip() else []
        except ValueError:
            findings = []
        for f in findings:
            fn = (f.get("filename") or "").replace("\\", "/")
            rel = fn[len(root.replace("\\", "/")) + 1 :] if fn.startswith(root.replace("\\", "/")) else fn
            row = ((f.get("location") or {}).get("row")) or 0
            ranges = staged.get(rel, staged.get(fn, {})).get("ranges", [])
            if any(a <= row <= b for a, b in ranges):
                violations.append(
                    f"  {rel}:{row}  ruff {f.get('code', '?')}: {f.get('message', '')}"
                )

    if violations:
        sys.stderr.write(
            "precommit_gate BLOCKED commit - net-new violations in staged files:\n"
            + "\n".join(violations)
            + "\n\nFix the staged lines (ruff check --fix / strip the glyph) and re-commit.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
