#!/usr/bin/env python3
"""PreToolUse gate on `git commit`: block NET-NEW ruff errors + banned glyphs.

Wired in .claude/settings.json under PreToolUse matcher `Bash|PowerShell`
(MAIN FIX 2026-10-21 1254 #4: the old `Bash(git commit:*)` is permission-rule
syntax and never matched, so Bash-tool commits were ungated). Every shell
command therefore reaches this script, and it filters for itself. Also run by
.githooks/pre-commit and commit-msg (the AUTHORITATIVE channel). Reads the
Claude Code hook payload on stdin (tool_name / tool_input.command).

Self-gates: if the command is not a `git commit`, exits 0 before touching git
(so it is a no-op on every other shell call - zero overhead off the commit path).

On a commit it inspects ONLY staged content of staged files (diff-filter ACM):
  0. RM-422 path length: a NEW tracked path (added / copied / rename target)
     longer than MAX_TRACKED_PATH_CHARS is refused; deletes always pass.
  1. ruff check (no --fix, --no-cache) on staged .py, keeping findings whose
     row lands in an ADDED line range of that file (net-new only - pre-existing
     repo debt in an untouched region never blocks, so an unattended headless
     run cannot wedge on unrelated errors).
  2. the 7-bit ASCII rule (every codepoint > 127) on ADDED (+) lines only, plus
     the commit-message text in the command string itself. The rule lives in
     tools/ascii_rule.py, shared with the edit hook tools/edit_lint_check.py
     (#13): one reading, two populations (edit-time advisory on the written
     text; commit-time blocking on net-new lines).

Exit 2 (block) with a terse stderr report on any violation; exit 0 otherwise.

FAILURE MODES (#10, as RULED 2026-10-22 in the C1b-3 S4 rework). The ruff run
is guarded (timeout, spawn error) and every entry point runs under
safe_main(), which splits by CHANNEL:
  * Claude PreToolUse (stdin is the hook JSON): FAIL-OPEN. A crash, a missing
    rule module or a ruff timeout exits 0 with ONE line of PreToolUse
    additionalContext naming the cause. A crash exit there was never blocking
    anyway, and the git hook below still gates the same commit.
  * git pre-commit (stdin is the text "git commit"), commit-msg
    (--message-file) and CI's --scan-files: FAIL-CLOSED. Any unexpected
    exception, a missing or unimportable tools/ascii_rule.py, or a ruff
    timeout / spawn error exits non-zero with ONE stderr line naming the cause
    (exception TYPE only - its text can carry staged content). These are the
    AUTHORITATIVE floor (CLAUDE.md), and a MAIN note lifts no safety floor
    (FLEET-COMMON item 6), so they never degrade to a pass.
  * compile() raising MemoryError / RecursionError (a source nested too deep)
    is a FINDING on every channel, never a crash.
  * stdin that cannot be read (no handle, OSError, ValueError) is a fault
    BEFORE the channel is known: exit 1 and ONE stderr line naming it, never
    "no commit in flight" (RM-783). stdin is read as bytes and decoded UTF-8,
    so a console code page cannot turn a payload into such a fault.
  * the Claude hook line's interpreter never starts (exit 127, any code
    outside 0-2): nothing in this file runs, so the shell tail on that line in
    ops/claude_settings.example.json prints the ONE context line (RM-782).
Unchanged and deliberate: no ruff installed anywhere is a warning and a pass
(a fresh clone must not wedge; CI's ruff is the backstop), and an unreadable
commit-message file passes (tests/test_precommit_gate_message_file.py).
Reverses if: MAIN or the operator rules in writing that the git-hook gate may
fail open.

Every RC-specific list sits in ONE marked REPO CONFIG block below (#10);
the logic is repo-agnostic. Dependency: tools/ascii_rule.py beside this file.
"""

from __future__ import annotations

import importlib.util
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

# ===========================================================================
# BEGIN REPO CONFIG (MAIN FIX 1254 #10). Every RC-specific path list and pin
# this gate reads. Another tree adopting the gate edits only this block. The
# ASCII rule's exempt surfaces are in tools/ascii_rule.py (shared, #13).
# ===========================================================================

# Staged paths the content arms never read (frozen history / build output).
_FROZEN_SKIP = ("logs/", "docs/_archive/", ".pyc", ".git/", "__pycache__/")

# RM-422 (LEDGER 1604): longest tracked path a fresh Windows clone can write
# without core.longpaths. Clone root budget = MAX_PATH - cap - 1 = 130 chars.
# ONE source of truth: tests/test_tracked_path_length_rm422.py (whole-index
# guard) and tests/test_git_hook_gate_e2e.py import these, never restate them.
MAX_PATH = 260
MAX_TRACKED_PATH_CHARS = 129

# Still an ABSOLUTE pin to the Python314 install (bare `py` resolves to the
# dep-less pymanager runtime - tests/test_bare_py_ban.py), but the account-
# specific prefix is read from the environment. A path naming one account's
# home is a gate that silently does not run under another, and a gate that does
# not run reports nothing. See _ruff_candidates for why it is a fallback.
_CANONICAL_PY = (
    pathlib.Path(os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData" / "Local"))
    / "Programs" / "Python" / "Python314" / "python.exe"
).as_posix()

# The ruff run in main(). Under the 60 s PreToolUse timeout in settings.json.
RUFF_TIMEOUT_S = 45

# Advisory non-atomic-write check: SCOPE. Rationale in the slice-D section
# further down. Production surfaces a poller can be reading mid-write:
_ATOMIC_SCOPE_PREFIXES = (
    "app/", "core/", "coaches/", "dashboard/", "game_reader/", "agents/",
    "modes/", "lcu/", "vision_server/",
)
_ATOMIC_SCOPE_FILES = ("web_dashboard.py",)
# tests/ and tools/ write scratch fixtures; ops/loop/ holds the BYTE-PINNED
# slots.py + winmutex.py (tests/test_loop_concurrency.py SHARED_SHA256).
_ATOMIC_EXEMPT_PREFIXES = ("tests/", "tools/", "scripts/", "docs/", "ops/loop/")
# Any tests/ segment, not only a leading one: agents/daemon_slayer/tests/ is
# under an in-scope prefix and is still a test tree.
_ATOMIC_EXEMPT_PARTS = ("/tests/",)
# pytest's own discovery convention, by BASENAME. MEASURED 2026-09-11 over the
# whole tree: 14 of the 18 hits were agents/agent3_testing/suite/test_*.py, a
# 42-file suite under an in-scope prefix with no tests/ segment, writing
# tmp_path fixtures. The rule is about polled files; a fixture is not one.
_ATOMIC_EXEMPT_BASENAME_PREFIXES = ("test_",)
_ATOMIC_EXEMPT_BASENAMES = ("conftest.py",)

# ===========================================================================
# END REPO CONFIG
# ===========================================================================

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NAME_STATUS = re.compile(r"^[ACDMRTUXB]\d*$")

_RULE = None
_RULE_PATH = pathlib.Path(__file__).resolve().with_name("ascii_rule.py")


class RuleUnavailable(ImportError):
    """tools/ascii_rule.py is missing or raised while loading. `reason` is a
    fixed, content-free sentence, safe to print."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _ascii_rule():
    """tools/ascii_rule.py, loaded from beside THIS file (never a same-named
    module elsewhere on sys.path). Unavailable -> RuleUnavailable, which
    safe_main() turns into a BLOCK on the git channels (no degrade to a pass)
    and a one-line context on the Claude channel."""
    global _RULE
    if _RULE is None:
        here = _RULE_PATH
        if not here.is_file():
            raise RuleUnavailable(f"tools/{here.name} is missing (ImportError)")
        try:
            spec = importlib.util.spec_from_file_location("rc_ascii_rule", here)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001 - re-raised, typed, below
            raise RuleUnavailable(
                f"tools/{here.name} is unimportable: it raised "
                f"{type(exc).__name__} while loading (ImportError)") from exc
        _RULE = mod
    return _RULE


def _is_commit(command: str) -> bool:
    s = command.strip()
    # tolerate leading env assignments, `&&`/`;` chains, PowerShell `{` blocks,
    # and global flags with quoted args (git -C "C:\path" commit). FLEET-KIT v12
    # item 16 a: a commit run through the kit's git lock
    # (`fleet_gitlock.py run --owner <id> -- git commit ...`) is still a commit.
    return bool(re.search(
        r"(^|[;&|{(]\s*|\s--\s+)git\s+(?:(?:-\S+|\"[^\"]*\"|'[^']*')\s+)*commit\b", s
    ))


def _skippable(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(s in p for s in _FROZEN_SKIP)


# RM-818: git and ruff write UTF-8 bytes whatever the console code page, so
# every text-mode child here decodes UTF-8 (errors="replace"). Through the
# locale (cp1252, a plain terminal's git hook) a staged U+201D (E2 80 9D; cp1252
# has no 0x9D) faulted the reader thread: the diff came back None and the gate
# blocked as "the gate itself failed", and a None ruff stdout passed in silence.
_CHILD_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}


def _git(args: list[str], root: str | None) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root or None, capture_output=True, **_CHILD_TEXT,
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


def _staged_new_paths(root: str) -> list[str]:
    """Paths this commit ADDS to the index: added, copied, and rename targets.

    Parsed from `git diff --cached --name-status -z`: `X\\0path\\0` per record,
    `R<n>\\0old\\0new\\0` / `C<n>\\0src\\0dst\\0` for renames and copies. NO
    _skippable filter - docs/_archive/ is exactly where the 131-char copy
    landed (9e5386aa1). Deletes and in-place edits are never new paths, so
    removing an over-long path is never blocked. Stops at the first record that
    is not name-status shaped (fail open).
    """
    out = _git(["diff", "--cached", "--name-status", "-z", "--diff-filter=ACR"], root)
    toks = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(toks) and _NAME_STATUS.match(toks[i]):
        status = toks[i]
        width = 2 if status[0] in "RC" else 1
        if i + width >= len(toks):
            break
        if status[0] in "ACR" and toks[i + width]:
            paths.append(toks[i + width])
        i += width + 1
    return paths


def _path_length_hits(paths: list[str]) -> list[str]:
    """RM-422 commit-time half: one violation line per new path over the cap.

    The whole-index guard (tests/test_tracked_path_length_rm422.py) only runs
    in a full suite, so a 131-char path rode in on 9e5386aa1 unrefused.
    """
    budget = MAX_PATH - MAX_TRACKED_PATH_CHARS - 1
    return [
        f"  {p}  path is {len(p)} chars, over the RM-422 cap of "
        f"{MAX_TRACKED_PATH_CHARS} (clone root budget {budget}) - shorten it"
        for p in paths
        if len(p) > MAX_TRACKED_PATH_CHARS
    ]


def _ascii_exempt(path: str) -> bool:
    """The shared rule's exempt surfaces (tools/ascii_rule.py EXEMPT_*).

    Kept under this name: tools/ascii_escape_py.py, the RM-300 census and the
    hand-off check in ops/loop/intents.py call it as the gate's predicate."""
    return _ascii_rule().is_exempt(path)


def _glyph_hits(text: str, path: str = "") -> list[str]:
    """The shared 7-bit rule (tools/ascii_rule.py, MAIN FIX 1254 #13).

    Named diagnostics for the six historical glyphs, then a catch-all over
    every codepoint > 127 that names the codepoint. The edit hook imports the
    same module, so the two hooks cannot hold two readings of one CLAUDE.md
    rule again (the 2026-07-28 U+00D7 incident is recorded in ascii_rule.hits).
    """
    return _ascii_rule().hits(text, path)


def _compile_errors(pyfiles: list[str], root: str) -> list[str]:
    """Syntax-check each staged .py; a syntax error crashes silently under
    pythonw.exe at runtime (CLAUDE.md hard rule), so block it at commit.

    The builtin compile(), not py_compile: py_compile writes a .pyc into
    __pycache__/ beside every staged file (the sibling of MAIN FIX 1254 #12 in
    tools/pytest_guard.py), and its message's first line is the `File ...`
    header rather than the error.

    MemoryError / RecursionError (a source nested too deep to parse or
    compile) are FINDINGS, exactly as py_compile reported them: they block the
    commit with a reason, never escape as a crash (C1b-3 S4 rework ruling)."""
    out: list[str] = []
    for rel in pyfiles:
        path = os.path.join(root, rel)
        try:
            with open(path, "rb") as fh:
                source = fh.read()
        except OSError:
            continue
        try:
            compile(source, path, "exec", dont_inherit=True)
        except SyntaxError as exc:
            msg = " ".join(str(exc.msg or "invalid syntax").split())[:160]
            out.append(f"  {rel}:{exc.lineno or 0}  py_compile: {type(exc).__name__}: {msg}")
        except (ValueError, MemoryError, RecursionError) as exc:
            # ValueError: e.g. a NUL byte. The other two: nested too deep.
            out.append(f"  {rel}  py_compile: {type(exc).__name__} - the source "
                       "cannot be compiled (NUL byte, or nested too deep)")
    return out


def _ruff_candidates() -> list[list[str]]:
    """Ruff invocations to try, in order, until one answers `--version`.

    This gate runs on TWO channels with DIFFERENT interpreters, and each one
    used to be hardcoded wrong for the other:

      * Claude PreToolUse - .claude/settings.json launches Python314's
        pythonw.exe, and that interpreter owns ruff, so sys.executable works.
      * .githooks/pre-commit - launches the gate through the `py` launcher,
        which on Legion resolves to a bare pythoncore build with NO ruff, so
        sys.executable is exactly the interpreter that cannot run it. This is
        the same dep-less runtime tests/test_bare_py_ban.py exists to keep out
        of tracked invocations.

    The original code used the launcher; 3d48e6e8 switched it to sys.executable
    to fix the PreToolUse channel and thereby broke the git-hook one - which is
    the AUTHORITATIVE channel (CLAUDE.md), and the one a headless run gets.
    Measured 2026-07-28: the ruff half had been dead there for three weeks, and
    passed a net-new UP031 in this file's own source straight to CI (8a6cdfc2).

    Resolving at call time is the fix: no channel has to be guessed. The
    launcher is deliberately NOT a candidate - it is the dep-less runtime that
    caused this - so the Legion fallback is the canonical absolute interpreter
    that docs/OPERATIONS.md pins.
    """
    return [
        [sys.executable, "-m", "ruff"],
        ["ruff"],
        [_CANONICAL_PY, "-m", "ruff"],
        ["python", "-m", "ruff"],
    ]


def _resolve_ruff() -> list[str] | None:
    """First candidate whose `--version` succeeds, or None if ruff is absent."""
    for cmd in _ruff_candidates():
        try:
            probe = subprocess.run(
                [*cmd, "--version"], capture_output=True, **_CHILD_TEXT,
                timeout=30, creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and (probe.stdout or "").strip().startswith("ruff"):
            return list(cmd)
    return None


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


def _check_scan_files(paths: list[str]) -> int:
    """--scan-files mode: whole FILES, not just added lines.

    Ported from Sibling-B 2026-09-06, credited. The commit-time arms of this
    gate only ever see a diff, so they cannot answer "is the tracked tree clean
    today" - and the hook that runs them is wired through core.hooksPath, which
    is LOCAL config and is not cloned. A fresh clone, a CI sandbox or an agent in
    a new worktree therefore enforced nothing at all.

    This mode exists so CI can sweep the tree through the SAME engine the hook
    uses. That is the whole point: RC already had CI-side glyph coverage via
    tests/test_smart_quote_hygiene.py, but that guard defines its own narrower
    banned set while _glyph_hits is a catch-all over every codepoint > 127. One
    rule, two readings, and the looser one was the one CI ran.

    Reports file:line so a hit is actionable, and returns 1 on any hit.
    """
    failures = 0
    for raw in paths:
        rel = raw.replace("\\", "/")
        if _ascii_exempt(rel):
            continue
        try:
            text = pathlib.Path(raw).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{rel}: unreadable ({exc.__class__.__name__})", file=sys.stderr)
            failures += 1
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            hits = _glyph_hits(line, rel)
            if hits:
                failures += 1
                print(f"{rel}:{lineno}: {', '.join(hits)}", file=sys.stderr)
    if failures:
        print(
            f"\n{failures} banned-glyph hit(s). CLAUDE.md requires 7-bit ASCII in "
            f"authored content: ' - ' for a clause break, '->' for an arrow, a "
            f"word for a status glyph. If a path is genuinely external data, "
            f"exempt it in tools/ascii_rule.py EXEMPT_* so the gate, the edit "
            f"hook and the guards keep ONE reading of the rule.",
            file=sys.stderr,
        )
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Advisory non-atomic-write check on NET-NEW lines (slice D, 2026-09-11).
#
# CLAUDE.md hard rule: "Atomic writes only: tmp.write_text(...); tmp.replace(
# target). Overlays poll mid-write." The canonical writer is
# core/polled_json.atomic_write_json (scratch via _scratch_path, publish via
# _replace_with_retry). Nothing at commit time enforced the rule, so a net-new
# `Path(...).write_text(...)` straight onto a polled file passed unremarked.
#
# Scope is an ALLOWLIST of production surfaces - the dirs whose files a poller
# can be reading mid-write - with an explicit denylist on top. tests/ and
# tools/ write scratch fixtures and one-off outputs where the rule does not
# apply, and ops/loop/ holds slots.py + winmutex.py, which are BYTE-PINNED
# across sibling repos (tests/test_loop_concurrency.py SHARED_SHA256): a hook
# suggestion that touched them would break a joint pin, so this check must
# never even look there.
#
# Mode is read from RC_ATOMIC_WRITE_GATE. Default WARN: this is a first-cycle
# MEASUREMENT of the false-positive rate, not enforcement. "block" reuses the
# exit-2 path the glyph half uses; "off" skips the check entirely.
#
# The scope lists (_ATOMIC_SCOPE_* / _ATOMIC_EXEMPT_*) are RC paths, so they
# live in the REPO CONFIG block at the top of this file (MAIN FIX 1254 #10).
_ATOMIC_WRITE_MODE_ENV = "RC_ATOMIC_WRITE_GATE"
_ATOMIC_WRITE_MODES = ("warn", "block", "off")
# Same-line markers that say "this is the scratch half of the idiom". `tmp`
# covers `_tmp` and `.tmp`; the comparison is case-insensitive.
_ATOMIC_SCRATCH_MARKERS = ("tmp", "scratch", ".part")
# Hunk-level markers that say "the publish step is here". `.replace(` covers
# `os.replace(` and `tmp.replace(`; `atomic_write` covers atomic_write_json /
# atomic_write_text / atomic_write_bytes / _atomic_write* (every helper the tree
# defines, measured 2026-09-11). The polled_json internals are named so a hunk
# that calls them directly is not flagged either.
_ATOMIC_PUBLISH_MARKERS = (
    ".replace(", "os.replace(", "atomic_write", "_atomic_write",
    "_write_then_replace", "_replace_with_retry",
)
# The write shapes. open() must carry a "w..." mode literal (positional or
# mode=) - "r"/"rb"/"a" are not this rule's concern.
_ATOMIC_WRITE_CALL = re.compile(
    r"\.write_text\(|\.write_bytes\(|\bjson\.dump\(|"
    r"\bopen\([^)]*?(?:\bmode\s*=\s*)?[\"']w[abt+]*[\"']"
)
_ATOMIC_WRITE_LABEL = re.compile(r"(\.write_text\(|\.write_bytes\(|json\.dump\(|\bopen\()")


def _atomic_write_mode() -> str:
    """One of warn / block / off. Unset, empty or unrecognised -> warn."""
    raw = (os.environ.get(_ATOMIC_WRITE_MODE_ENV) or "").strip().lower()
    return raw if raw in _ATOMIC_WRITE_MODES else "warn"


def _atomic_write_in_scope(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    if p.startswith(_ATOMIC_EXEMPT_PREFIXES) or any(part in p for part in _ATOMIC_EXEMPT_PARTS):
        return False
    base = p.rsplit("/", 1)[-1]
    if base in _ATOMIC_EXEMPT_BASENAMES or base.startswith(_ATOMIC_EXEMPT_BASENAME_PREFIXES):
        return False
    return p in _ATOMIC_SCOPE_FILES or p.startswith(_ATOMIC_SCOPE_PREFIXES)


def _atomic_write_hits(added_lines: list[tuple[int, str]], path: str) -> list[str]:
    """Net-new lines in `path` that write a file without the tmp+replace idiom.

    `added_lines` is the `(lineno, text)` list `_staged_added` builds per file.
    A line is a hit when ALL of:
      * the file is a production surface (see _atomic_write_in_scope);
      * the line calls .write_text( / .write_bytes( / open(x, "w..") / json.dump(;
      * the line itself carries no scratch marker (tmp / scratch / .part);
      * NO added line of this file carries a publish marker (.replace( /
        atomic_write* / _write_then_replace / _replace_with_retry).
    The hunk-level half is deliberately lenient: a str.replace( elsewhere in
    the hunk also exempts. That is a false-NEGATIVE bias, which is the right
    bias for a check whose block mode is not yet earned.
    """
    if not _atomic_write_in_scope(path):
        return []
    rel = path.replace("\\", "/")
    texts = [t for _, t in added_lines]
    if any(m in t for t in texts for m in _ATOMIC_PUBLISH_MARKERS):
        return []
    out: list[str] = []
    for lineno, text in added_lines:
        stripped = text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _ATOMIC_WRITE_CALL.search(text):
            continue
        low = text.lower()
        if any(m in low for m in _ATOMIC_SCRATCH_MARKERS):
            continue
        m = _ATOMIC_WRITE_LABEL.search(text)
        call = m.group(1).rstrip("(") if m else "write"
        out.append(f"  {rel}:{lineno}  non-atomic write ({call}): {stripped[:110]}")
    return out


class StdinFault(Exception):
    """stdin could not be read (RM-783). The channel is not known yet, so this
    is a pre-channel fault: safe_main() exits 1 with ONE stderr line naming it
    (a git hook refuses; Claude PreToolUse does not block on 1). It is never
    read as "no commit in flight". `reason` is content-free, safe to print."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _read_stdin() -> str:
    """The hook's stdin, read as BYTES and decoded UTF-8 (RM-783): the console
    code page never decides what the payload says (cp1252 has no 0x81, so a
    UTF-8 message holding U+0101 used to fault and pass), and an undecodable
    byte becomes U+FFFD - a glyph finding, not a fault. A tty is a manual run
    (empty: no commit in flight). No stream, or a read that fails, raises
    StdinFault: both real channels pipe stdin, so neither is "no commit"."""
    stream = sys.stdin
    if stream is None:
        raise StdinFault("stdin unreadable: no handle")
    try:
        if stream.isatty():
            return ""
        layer = getattr(stream, "buffer", None) or stream
        data = layer.read()
    except (OSError, ValueError, AttributeError) as exc:
        raise StdinFault(f"stdin unreadable: {type(exc).__name__}") from None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return data or ""


def _parse_stdin(raw: str) -> tuple[str, bool]:
    """(command, from_claude). Claude PreToolUse sends a JSON object; the git
    pre-commit hook pipes the plain text "git commit"."""
    # PowerShell 5.1 pipes prepend a UTF-8 BOM; json.loads rejects it and the
    # raw-string fallback then never regex-matches -> silent pass. Strip it.
    raw = (raw or "").lstrip(chr(0xFEFF)).strip()
    try:
        obj = json.loads(raw)
    except ValueError:
        return raw, False
    if not isinstance(obj, dict):
        return raw, False
    tool_input = obj.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    return (command if isinstance(command, str) else ""), True


def _claude_context(text: str) -> None:
    """ONE stdout line of PreToolUse additionalContext (fleet UI/UX standard
    section 5). Used only on the Claude channel and only on exit 0."""
    line = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": " ".join(text.split())}})
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _dispatch(args: list[str], state: dict) -> int:
    # commit-msg mode. Explicit flag rather than sniffing argv, so the hook's
    # intent is readable in the hook body itself.
    if len(args) >= 3 and args[1] == "--message-file":
        _ascii_rule()  # no rule -> no check -> refuse, never a silent pass
        return _check_message_file(args[2])
    # whole-file scan mode, for CI. Same engine, different input shape.
    if len(args) >= 2 and args[1] == "--scan-files":
        _ascii_rule()
        return _check_scan_files(args[2:])

    command, state["from_claude"] = _parse_stdin(_read_stdin())
    if not _is_commit(command):
        return 0
    # Loaded up front, so even a commit with no added lines (a pure delete)
    # cannot pass a gate that has no rule to check with.
    _ascii_rule()
    return _gate_commit(command, claude=state["from_claude"])


def main(argv: list[str] | None = None) -> int:
    """The gate WITHOUT the channel guard; exceptions propagate. Tests drive
    this. The script entry point is safe_main()."""
    return _dispatch(list(sys.argv if argv is None else argv), {"from_claude": False})


def _gate_commit(command: str, claude: bool) -> int:
    advisories: list[str] = []
    root = (
        _root_from_command(command)
        or _git(["rev-parse", "--show-toplevel"], os.getcwd()).strip()
        or os.getcwd()
    )
    staged = _staged_added(root)
    # 0. RM-422: new tracked paths over the Windows clone cap.
    violations: list[str] = _path_length_hits(_staged_new_paths(root))

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

    # 2b. non-atomic writes on net-new PRODUCTION lines. Advisory by default
    # (RC_ATOMIC_WRITE_GATE unset / warn); "block" joins the exit-2 path above;
    # "off" checks nothing. See _atomic_write_hits for the rule.
    atomic_mode = _atomic_write_mode()
    if atomic_mode != "off":
        atomic_hits: list[str] = []
        for path, info in staged.items():
            atomic_hits.extend(_atomic_write_hits(info["lines"], path))
        if atomic_hits and atomic_mode == "block":
            violations.extend(atomic_hits)
        elif atomic_hits:
            sys.stderr.write(
                "precommit_gate ADVISORY - non-atomic write(s) on net-new lines "
                f"({_ATOMIC_WRITE_MODE_ENV}=warn, NOT blocking):\n"
                + "\n".join(atomic_hits)
                + "\n  Rule: tmp.write_text(...); tmp.replace(target), or "
                "core.polled_json.atomic_write_json - overlays poll mid-write.\n"
            )

    # 3. net-new ruff errors on staged .py
    pyfiles = [
        p for p in staged if p.endswith(".py") and os.path.isfile(os.path.join(root, p))
    ]
    violations.extend(_compile_errors(pyfiles, root))
    ruff = _resolve_ruff() if pyfiles else None
    if pyfiles and ruff is None:
        # Fail OPEN, but never fail SILENT. Blocking every commit on a machine
        # without ruff would wedge the headless loop and a fresh clone; passing
        # without a word is what let 8a6cdfc2 reach CI. CI's `ruff check .` is
        # the backstop, so say the half did not run and let the commit through.
        sys.stderr.write(
            "precommit_gate WARNING: no working ruff found - the net-new ruff "
            "half did NOT run on this commit.\n  Tried: "
            + " | ".join(" ".join(c) for c in _ruff_candidates())
            + "\n  Install it (python -m pip install ruff) or CI is your only "
            "lint gate.\n"
        )
    proc = None
    if pyfiles and ruff is not None:
        # --no-cache (#11): ruff runs with cwd=root beside ruff.toml and used
        # to leave .ruff_cache/ in the repo root. The call is guarded (#10): a
        # hung or vanished ruff never crashes the gate. On the git channels it
        # BLOCKS (a found ruff that cannot finish is not a pass); on the Claude
        # channel it is one line of context, and the git hook re-runs it.
        try:
            proc = subprocess.run(
                [*ruff, "check", "--no-cache", "--output-format=json", *pyfiles],
                cwd=root,
                capture_output=True,
                **_CHILD_TEXT,
                timeout=RUFF_TIMEOUT_S,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            note = (f"ruff timed out / not runnable ({type(exc).__name__}) - fix or "
                    "rerun; the net-new ruff half could not run")
            if claude:
                advisories.append(note + " (the git pre-commit hook re-runs it)")
            else:
                violations.append("  " + note)
    if proc is not None:
        try:
            findings = json.loads(proc.stdout) if (proc.stdout or "").strip() else []
        except ValueError:
            # ruff answered --version but could not lint (bad config, crash).
            # Same rule as above: pass, but never in silence.
            findings = []
            sys.stderr.write(
                "precommit_gate WARNING: ruff produced no parseable JSON - the "
                "net-new ruff half did NOT run.\n  "
                + (proc.stderr or "").strip()[:400]
                + "\n"
            )
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
            + "\n\nFix the staged lines and re-commit. ruff: `ruff check --fix` "
            "where safe. Glyphs: " + _ascii_rule().fix_hint() + ". Path: "
            "shorten it.\n"
        )
        return 2
    if advisories:
        _claude_context("precommit_gate: " + "; ".join(advisories))
    return 0


def safe_main(argv: list[str] | None = None) -> int:
    """Script entry point: the per-CHANNEL failure contract (#10, as ruled).

    Claude PreToolUse channel (stdin JSON): an internal fault FAILS OPEN -
    exit 0 and one line of additionalContext. Every other mode - git
    pre-commit, commit-msg, CI --scan-files, and a fault before the channel
    is known - FAILS CLOSED: exit 1 (which any git hook treats as a refusal,
    and which Claude PreToolUse treats as non-blocking) with ONE stderr line.
    Only the exception TYPE (or RuleUnavailable's fixed sentence) is printed:
    exception text can carry staged content.
    """
    args = list(sys.argv if argv is None else argv)
    # The channel flag is keyed from_claude, never by the bare CLI name: this
    # gate starts git and ruff only, and tests/test_headless_env.py's spawn
    # inventory reads a bare-name string literal as a CLI reference, so the
    # file stays IN that scan rather than on its non-spawn allowlist.
    state = {"from_claude": False}
    try:
        return _dispatch(args, state)
    except StdinFault as exc:
        # RM-783: before the channel is known, so the fail-closed half below
        # in its own words - on Claude PreToolUse exit 1 does not block.
        try:
            sys.stderr.write(
                f"precommit_gate: {exc.reason} - no command was checked; exit 1 "
                "refuses a git hook, and a Claude PreToolUse hook does not block "
                "on it (the git pre-commit hook still gates the commit).\n")
        except (OSError, ValueError, AttributeError):
            pass
        return 1
    except Exception as exc:  # noqa: BLE001 - the channel decides below
        reason = exc.reason if isinstance(exc, RuleUnavailable) else type(exc).__name__
        if state["from_claude"]:
            _claude_context(
                f"precommit_gate could not run ({reason}); this PreToolUse hook did "
                "not gate the commit - the git pre-commit hook still does.")
            return 0
        try:
            sys.stderr.write(
                f"precommit_gate BLOCKED: the gate itself failed ({reason}) - fix "
                "the gate or rerun; a broken gate never passes a commit.\n")
        except (OSError, ValueError, AttributeError):
            pass
        return 1


if __name__ == "__main__":
    sys.exit(safe_main())
