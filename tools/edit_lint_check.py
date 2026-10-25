"""PostToolUse hook: ruff (report only) + ASCII rule + CREDENTIAL scan on edits.

INPUT (MAIN FIX 2026-10-21 1254 item #1). Claude Code hands the hook its
payload as JSON on stdin and does NOT set $CLAUDE_FILE_PATHS, so the old
env-only read meant none of the three arms ever ran on a live edit. Targets
now come from the payload:
    Edit / Write       tool_input.file_path  (+ new_string / content)
    MultiEdit          tool_input.file_path  (+ edits[].new_string)
    NotebookEdit       tool_input.notebook_path  (+ new_source)
A relative path resolves against the payload's `cwd`. $CLAUDE_FILE_PATHS is
read ONLY when stdin names no path (older harnesses; tests drive it).

ARMS:
  1. ruff on .py targets: `<this interpreter's console twin> -m ruff check
     --no-cache --output-format=json` (python.exe, never pythonw.exe - see
     _console_interpreter for the console flash). REPORT ONLY (#3): `--fix` mid-edit deleted a
     just-added import as unused before its first use was written.
     `--no-cache` (#11): no .ruff_cache/ is left in the repo or the cwd.
  2. the 7-bit ASCII rule, tools/ascii_rule.py (#13) - the SAME predicate and
     exempt surfaces as the commit gate (tools/precommit_gate.py): every
     codepoint > 127. Population = the text the tool wrote (as the gate reads
     added lines), so a pre-existing glyph nobody touched does not re-flag on
     every edit; the whole file only on the env fallback, where no written
     text is known. The fix hint names the strip helpers as OPTIONAL (#14).
  3. credential-shape scan (tools/credential_patterns.py) on the whole file.
     This hook is the ONLY RC control whose population includes UNTRACKED
     files - measured in
     `docs/specs/2026-09-20-shared-git-root-bucket-rc-share-scan.md` Q3: a
     credential in a file that is not staged, not in a push range and not in
     the git index is invisible to every other RC control. NO MATCHED VALUE IS
     EVER PRINTED, LOGGED OR WRITTEN: file, line and pattern CLASS only (see
     the contract at the head of tools/credential_patterns.py).

OUTPUT (#2; fleet UI/UX standard section 5, FLEET-COMMON item 15). Silent
when clean. Otherwise ONE stdout line
    {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                            "additionalContext": "<one line>"}}
and exit 0, no ANSI. Exit 0 is what makes the JSON reach the model; stderr on
exit 0 never does, which is how a ruff or glyph finding went unseen. A
credential finding LEADS the line (it used to exit 2 with stderr; exit 2
makes the harness drop the JSON channel the other arms speak through). The
write has already happened when a PostToolUse hook runs; the line surfaces
the finding, it does not roll anything back.

FAIL-OPEN. Any fault inside the hook exits 0 in silence: hook noise must never
stop the operator's flow, and the commit gate is the blocking backstop.

Dependencies: tools/ascii_rule.py and tools/credential_patterns.py beside this
file; ruff in this interpreter (the arm is silent without it).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from tools import ascii_rule, credential_patterns
except ImportError:  # hook runs as a bare script, so sys.path[0] is tools/
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ascii_rule
    import credential_patterns

# Hooks run under windowless pythonw.exe; a console-subsystem child (ruff)
# would otherwise get a fresh console allocated - an on-screen + taskbar flash
# on every edit. CREATE_NO_WINDOW suppresses it (Windows-only; 0 elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _console_interpreter(exe: str | None = None) -> str:
    """The console twin of a pythonw.exe interpreter, for `-m` child runs.

    CREATE_NO_WINDOW governs CONSOLE-subsystem children only. pythonw.exe is a
    GUI binary, so `pythonw -m ruff` gets no console at all, and ruff's own
    wrapper then spawns ruff.exe unflagged: a fresh, visible, focus-stealing
    console on every edit. Measured 2026-10-24 (s133): all 34 console windows
    created on the desktop in a 15 min capture were this ruff.exe, 25 of them
    took the foreground. python.exe under CREATE_NO_WINDOW gets a hidden
    console that ruff.exe inherits. Same install, same packages.
    """
    path = Path(exe or sys.executable)
    if path.name.lower() == "pythonw.exe":
        twin = path.with_name("python.exe")
        if twin.is_file():
            return str(twin)
    return str(path)


_FROZEN_SKIP = ("logs/", "docs/_archive/", ".pyc", ".git/", "__pycache__/")

# Under the 15 s hook timeout in .claude/settings.json, with room to spare.
RUFF_TIMEOUT_S = 10
_MAX_ITEMS = 8
_MAX_CONTEXT_CHARS = 2000


def _is_skippable(p: Path) -> bool:
    s = str(p).replace("\\", "/")
    return any(skip in s for skip in _FROZEN_SKIP)


# ---------------------------------------------------------------------------
# input
# ---------------------------------------------------------------------------


def _read_stdin() -> str:
    """stdin as BYTES, decoded UTF-8 (RM-784 sibling): through the console
    code page a cp1252 BOM arrived as three other characters and a UTF-8
    path holding U+0101 (C4 81; cp1252 has no 0x81) faulted the read, so
    the hook went silent. _parse_payload strips the decoded BOM."""
    stream = sys.stdin
    if stream is None:  # pythonw with no standard handles
        return ""
    try:
        if stream.isatty():
            return ""
        data = (getattr(stream, "buffer", None) or stream).read()
    except (OSError, ValueError, AttributeError):
        return ""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return data or ""


def _parse_payload(raw: str) -> dict:
    # PowerShell 5.1 pipes prepend a UTF-8 BOM; json.loads rejects it.
    raw = (raw or "").lstrip(chr(0xFEFF)).strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _targets(payload: dict) -> dict[str, list[str]]:
    """{path as given: [texts the tool wrote]} from a PostToolUse payload."""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return {}
    out: dict[str, list[str]] = {}

    def add(path: object, text: object = None) -> None:
        if isinstance(path, str) and path:
            texts = out.setdefault(path, [])
            if isinstance(text, str):
                texts.append(text)

    main_path = ti.get("file_path")
    add(main_path, ti.get("content"))
    add(main_path, ti.get("new_string"))
    add(ti.get("notebook_path"), ti.get("new_source"))
    edits = ti.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict):
                add(e.get("file_path") or main_path, e.get("new_string"))
    return out


def _env_paths() -> list[str]:
    raw = os.environ.get("CLAUDE_FILE_PATHS", "").strip()
    if not raw:
        return []
    if Path(raw).is_file():  # one path that contains spaces
        return [raw]
    return raw.split()


def _resolve(raw: str, payload: dict) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        cwd = payload.get("cwd")
        p = (Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()) / p
    return p


def _rule_path(path: Path) -> str:
    """Repo-relative POSIX path for the ASCII rule's exemptions."""
    try:
        full = path.resolve()
    except OSError:
        full = path
    for parent in full.parents:
        if (parent / ".git").exists():
            try:
                return full.relative_to(parent).as_posix()
            except ValueError:
                break
    return full.as_posix()


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------


def _ruff_findings(py_files: list[Path]) -> list[str]:
    """Report-only ruff. Silent when ruff is absent or produces no JSON.

    RM-818: ruff writes its JSON as UTF-8 whatever the console code page, so
    it is decoded as UTF-8 here. Through the locale (cp1252) a non-ASCII path
    or message (U+0101 = C4 81; cp1252 has no 0x81) faulted the reader
    thread: the findings were dropped and a traceback went to stderr."""
    try:
        proc = subprocess.run(
            [_console_interpreter(), "-m", "ruff", "check", "--no-cache",
             "--output-format=json", *[str(p) for p in py_files]],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUFF_TIMEOUT_S,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(proc.stdout) if (proc.stdout or "").strip() else []
    except ValueError:
        return []
    out: list[str] = []
    for f in data if isinstance(data, list) else []:
        if not isinstance(f, dict):
            continue
        name = Path(str(f.get("filename") or "?")).name
        row = (f.get("location") or {}).get("row") or 0
        out.append(f"{name}:{row} {f.get('code') or 'syntax'} {f.get('message') or ''}")
    return out


def _ascii_finding(path: Path, written: list[str]) -> str | None:
    rel = _rule_path(path)
    if ascii_rule.is_exempt(rel):
        return None
    try:
        file_text: str | None = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        file_text = None
    snippets = written or ([file_text] if file_text is not None else [])
    names: set[str] = set()
    lines: set[int] = set()
    for snip in snippets:
        found = ascii_rule.line_hits(snip, rel)
        if not found:
            continue
        idx = file_text.find(snip) if file_text is not None and snip else -1
        base = file_text.count("\n", 0, idx) if idx >= 0 else None
        for n, hs in found:
            names.update(hs)
            if base is not None:
                lines.add(base + n)
    if not names:
        return None
    where = ""
    if lines:
        shown = sorted(lines)
        where = " at line " + ",".join(str(n) for n in shown[:_MAX_ITEMS])
        if len(shown) > _MAX_ITEMS:
            where += f" (+{len(shown) - _MAX_ITEMS} more)"
    return f"{path}{where}: {', '.join(sorted(names))}"


def _capped(items: list[str]) -> str:
    text = "; ".join(items[:_MAX_ITEMS])
    if len(items) > _MAX_ITEMS:
        text += f" (+{len(items) - _MAX_ITEMS} more)"
    return text


def _emit(text: str) -> None:
    """ONE stdout line of PostToolUse additionalContext (ASCII, no ANSI)."""
    one = " ".join(text.split())
    if len(one) > _MAX_CONTEXT_CHARS:
        one = one[: _MAX_CONTEXT_CHARS - 3] + "..."
    line = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": one}})
    try:
        if sys.stdout is not None:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _run() -> int:
    payload = _parse_payload(_read_stdin())
    targets = _targets(payload) or {p: [] for p in _env_paths()}
    files: dict[Path, list[str]] = {}
    for raw, written in targets.items():
        p = _resolve(raw, payload)
        if p.is_file() and not _is_skippable(p):
            files.setdefault(p, []).extend(written)
    if not files:
        return 0

    # Arm 3 first in the output: a credential is not hook noise. The scan is
    # guarded so a bug in the arm cannot hide the other arms - but a genuine
    # finding is collected OUTSIDE that guard, so it is never swallowed by the
    # same except that catches this module's own faults.
    cred_flagged: list[str] = []
    cred_faults: list[str] = []
    for p in files:
        try:
            findings = credential_patterns.scan_file(p)
            if findings:
                cred_flagged.extend(
                    " ".join(s.split())
                    for s in credential_patterns.format_findings(str(p), findings)
                )
            elif credential_patterns.was_truncated(p):
                cred_faults.append(f"{p}: larger than the scan budget, head only")
        except Exception as exc:  # noqa: BLE001 - fail-safe: never break a write
            # Type name only. Exception text can carry file content.
            cred_faults.append(f"{p}: credential scan skipped ({type(exc).__name__})")

    glyphs = [g for g in (_ascii_finding(p, w) for p, w in files.items()) if g]
    py_files = [p for p in files if p.suffix == ".py"]
    ruff = _ruff_findings(py_files) if py_files else []

    parts: list[str] = []
    if cred_flagged:
        parts.append(
            "CREDENTIAL SHAPE FOUND - DO NOT COMMIT; ROTATE IF REAL: "
            + _capped(cred_flagged)
            + ". No value is printed, by design - open the file:line yourself."
            " Exempt a deliberate fixture line with: " + credential_patterns.PRAGMA
        )
    if glyphs:
        parts.append(
            "BANNED-GLYPH FOUND (CLAUDE.md 7-bit ASCII rule): " + _capped(glyphs)
            + ". " + ascii_rule.fix_hint()
        )
    if ruff:
        parts.append("ruff (report only, nothing was changed): " + _capped(ruff))
    if cred_faults:
        parts.append("credential arm, non-blocking: " + _capped(cred_faults))
    if parts:
        _emit(" | ".join(parts))
    return 0


def main() -> int:
    try:
        return _run()
    except Exception:  # noqa: BLE001 - a hook fault must never stop an edit
        return 0


if __name__ == "__main__":
    sys.exit(main())
